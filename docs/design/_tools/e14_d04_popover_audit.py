"""E14-D04 drawing-properties popover audit: every number the hi-fi spec quotes, from the repo.

Standalone, offline, stdlib only (run with ``python3 -I``). Eight sections, each row labelled with
its source so a reviewer can re-grep it:

1. Schema parity: the spec's per-tool property table (``docs/design/E14/E14-D04.md`` section 3)
   against the registry of E14-D02's own tool (``e14_d02_interaction_audit.py`` ``REG`` - one
   source, no third copy) and the ``DrawingTool`` / ``DrawingGeometry`` / ``DrawingStyle`` /
   ``DrawingInput`` text of ``docs/plan/22-api-openapi.yaml``: every API tool has one row, the
   cursor rows say "no popover", the deferred rows are marked, every cell is a shared field with a
   real ``22`` key and bound, a declared slot or a ``G-T`` id, and the key rules hold (gated).
2. The anatomy arithmetic: widths, rows, padding, the body height per tool and density, the 90 vh
   threshold at 800 and 400 CSS px, the swatch rows (both must fit the inner width: gated) and the
   radio / tile / inner-ring geometry of E13-D03's CMP-031 (printed, not typed).
3. The measured matrix: every fg / bg pair the spec's section 10 lists x dark / light /
   high-contrast, resolved exactly as ``packages/ui/tokens/tests/verify_tokens.py`` layers the
   themes, measured with ``contrast_check.contrast_ratio()`` (imported, never re-implemented); the
   reproductions of E14-D02 section 15, E30-D02 line 361, E09-D09 section 11 and E13-D03 sections
   3.1 and 10.1 line 322 (merged, f437dc6b4) to the hundredth; gated roles 0 FAIL, structure-only
   rows reported. 3b: each theme's swatch hexes on the other theme's canvas and the hex
   collisions between the two sets (a stored hex is theme-fixed: G-T11).
4. The fill-opacity study (ticket AC 3): per swatch x theme the largest ``fill_opacity`` (step
   0.01) at which ``color.candle.up`` / ``.down`` / ``.wick`` (and the CVD-safe pair) keep >= 3:1
   over one, two and three stacked fills and over the flattened composite, both layer orders; the
   three-stack minimum rounded down to 0.05 is the stated default (gated equal to the spec's); the
   tint of a fill against the bare canvas at the default and at the flattened ceiling.
5. The CVD rows: ``cvd_simulate.simulate`` + ``delta_e76`` under three deficiencies, 5.0 floor.
6. Token bindings: every token the spec binds exists in the merged dark set, or is marked PROPOSED
   on its row; T2 rows never carry ``color.text.disabled`` or ``opacity.disabled``; validity rows
   carry ``opacity.disabled`` and never "T2" or "lock" (gated).
7. String gates on the spec and the handoff (the T2 rule once, the view-as leg first, no closing
   keyword, no local path or Penpot host, every board row PENDING, no placeholder words, no
   "merges as is" qualifier, the frame count in section 17, the colour-custom legend word, G-T11
   named in the handoff, the Q1-Q16 rulings cited by issuecomment id with no pending ruling left,
   the PROPOSED quota key named, rendering 2b named in section 8).
8. The counts the boards and the PR quote (``--json`` feeds the local board check).

Usage: python3 -I docs/design/_tools/e14_d04_popover_audit.py [--json] [--check] [--table]
A plain run prints every section and exits 0; ``--check`` exits 1 on any gated FAIL. UTF-8 stdout.
No network; no URL literal anywhere in this file.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "docs" / "design" / "_tools"
TOKENS = ROOT / "packages" / "ui" / "tokens"
PLAN = ROOT / "docs" / "plan"
SPEC = ROOT / "docs" / "design" / "E14" / "E14-D04.md"
HANDOFF = ROOT / "docs" / "design" / "E14" / "E14-D04-handoff.md"


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
cvd = _load(ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py", "cvd_simulate")
keymap_lint = _load(ROOT / "scripts" / "keymap_lint.py", "keymap_lint")
d02 = _load(TOOLS / "e14_d02_interaction_audit.py", "e14_d02_interaction_audit")

THEMES = ("dark", "light", "high-contrast")
# E13-D03 section 3.1 (merged as f437dc6b4, PR 4212): the eight slot aliases per theme;
# high-contrast inherits the dark alias. Q12 (RULED, issuecomment 6362143576) aliases
# color.drawing.palette.N to them.
SLOT_ALIAS: dict[str, tuple[str, ...]] = {
    "dark": (
        "palette.teal.500",
        "palette.cyan.600",
        "palette.amber.600",
        "palette.purple.600",
        "palette.teal.600",
        "palette.cvd.light.blue.3",
        "palette.purple.400",
        "palette.light.amber.300",
    ),
    "light": (
        "palette.teal.900",
        "palette.blue.400",
        "palette.cyan.900",
        "palette.purple.500",
        "palette.amber.900",
        "palette.teal.600",
        "palette.purple.900",
        "palette.cvd.blue.1",
    ),
}
SLOT_ALIAS["high-contrast"] = SLOT_ALIAS["dark"]
E13_SLOT_CANVAS_DARK = (7.30, 4.57, 5.90, 3.05, 4.85, 3.28, 6.73, 3.87)
# E13-D03 section 10.1 line 322: color.border.selected on color.surface.selected (the inner ring)
E13_INNER_RING = (3.46, 3.39, 4.72)
SWATCH_KEYS = ("color.drawing.default", *(f"color.drawing.palette.{i}" for i in range(1, 9)))
HUE_WORD = {
    "cvd": "blue"
}  # palette.cvd.* families are blue / orange ramps; the family word is the hue

# The per-tool schema (spec section 3), derived - never a third registry copy. D02's REG rows give
# the ids, the DrawingTool values and the anchor counts; 22 gives the key rules; D04 adds only which
# rows carry which slot and which rows take the fill fields (rectangle, ellipse, triangle,
# parallel_channel; the deferred price_range / date_range would).
FILLED = ("rectangle", "ellipse", "triangle", "parallel_channel", "price_range", "date_range")
TEXT_TOOLS = ("text", "callout")
FIB = ("fib_retracement", "fib_extension", "fib_timezone")
# the tools whose drawing changes when extend_left / extend_right flips (spec section 3; 22 allows
# the keys on every tool - a horizontal ray is a horizontal_line with extend_right)
EXTEND = (
    "trendline",
    "horizontal_line",
    "rectangle",
    "parallel_channel",
    "fib_retracement",
    "fib_extension",
)
NOT_SHOWN = "— (allowed by `22`, not shown)"
NO_BOX = "— (styles nothing until the note's box field lands)"
SLOT: dict[str, str] = {
    "fib_retracement": "levels",
    "fib_extension": "levels",
    "fib_timezone": "levels",
    "anchored_vwap": "bands",
    "text": "note",
    "callout": "note",
    "measure": "measure",
    "long_position": "position",
    "short_position": "position",
    "parallel_channel": "channel",
}
SLOT_CELL = {
    "levels": "levels: `geometry.levels` 1..24 + G-T3",
    "bands": "bands: `geometry.bands` {1, 2, 3}",
    "note": "note: `geometry.text` 1..1,000 + G-T6",
    "measure": "measure units + Pin: G-T5",
    "position": "position read-out + Send to ticket (D06)",
    "channel": "channel width read-out (derived)",
    "": "—",
}
NO_POPOVER = "no popover"
NA = "n/a"
DEFER = "deferred — API value, no story; unscheduled"
COLS = (
    "id",
    "`DrawingTool`",
    "anchors",
    "colour",
    "width",
    "style",
    "extend L / R",
    "fill",
    "font size",
    "label",
    "lock / visible",
    "slot",
    "status",
)
# the section-8 state rows: id | kind | board; the spec's table must list exactly these (gated)
STATES_TXT = """
default|none|05
hover-focus|none|02
colour-custom|none|02
save-as-default-noop|validity|02
edited-unsaved|none|05
invalid-width|validity|05
template-name-empty|validity|09
template-name-duplicate|validity|09
duplicate-level|validity|04
note-empty|validity|04
saving|none|05
saved|outcome|05
save-failed|none|05
save-failed-offline|none|05
access-changed|none|05
session-read-only|none|05
conflict|none|05
deleted-elsewhere|none|05
batch-failed|none|10
batch-target-unavailable|none|10
template-saving|none|09
template-save-failed|none|09
locked|T2|05
view-as|T2|05
viewer|T2|05
tool-defaults|validity|05
multiselect-mixed|none|10
alert-marker|marker|05
alert-live|none|05
alert-over-quota|T2|05
zoom-125|none|10
zoom-200|none|10
forced-colors|none|05
hc|none|05
reduced-motion|none|05
"""
STATES: list[list[str]] = [ln.split("|") for ln in STATES_TXT.strip().splitlines()]
BOARDS: list[tuple[str, str, list[str]]] = [
    (
        "01",
        "popover-anatomy-1280",
        [
            "anatomy-compact",
            "anatomy-comfortable",
        ],
    ),
    (
        "02",
        "shared-fields-dark",
        [
            "hover-focus",
            "swatches",
            "colour-custom",
            "swatch-focused-selected",
            "save-as-default-noop",
            "width",
            "style",
            "extend-lock",
            "anchors",
            "alert-row",
            "templates-section",
            "actions",
            "status-line",
        ],
    ),
    (
        "03",
        "shared-fields-light",
        [
            "hover-focus-light",
            "swatches-light",
            "width-light",
            "style-light",
            "templates-section-light",
            "status-line-light",
        ],
    ),
    (
        "04",
        "schema-and-slots",
        [
            "duplicate-level",
            "levels",
            "level-last-remove",
            "bands",
            "note",
            "note-empty",
            "measure",
            "position",
            "channel",
        ],
    ),
    (
        "05",
        "states-dark",
        [
            "default",
            "edited-unsaved",
            "invalid-width",
            "saving",
            "saved",
            "save-failed",
            "save-failed-offline",
            "access-changed",
            "session-read-only",
            "conflict",
            "deleted-elsewhere",
            "locked",
            "viewer",
            "viewer-filled",
            "view-as",
            "tool-defaults",
            "alert-marker",
            "alert-live",
            "alert-over-quota",
            "forced-colors",
            "hc",
            "reduced-motion",
        ],
    ),
    (
        "06",
        "states-light",
        [
            "default-light",
            "invalid-width-light",
            "save-failed-light",
            "locked-light",
            "viewer-light",
            "view-as-light",
            "alert-over-quota-light",
        ],
    ),
    (
        "07",
        "fill-opacity-study-dark",
        [
            "fill-stacked",
            "fill-flattened",
            "fill-section",
        ],
    ),
    (
        "08",
        "fill-opacity-study-light",
        [
            "fill-stacked-light",
            "fill-flattened-light",
        ],
    ),
    (
        "09",
        "templates",
        [
            "template-name-empty",
            "template-name-duplicate",
            "template-saving",
            "template-save-failed",
            "picker",
            "apply-selection",
            "apply-new",
            "manage",
            "template-empty",
            "tool-defaults-menu",
            "tool-defaults-popover",
            "templates-viewer",
            "templates-view-as",
        ],
    ),
    (
        "10",
        "multiselect-a11y-zoom",
        [
            "multiselect-mixed",
            "multiselect-viewer",
            "batch-failed",
            "batch-target-unavailable",
            "zoom-125",
            "zoom-200",
            "focus-order",
        ],
    ),
]
LIGHT_TWINS = ("03", "06", "08")
FRAMES_TOTAL = sum(len(f) for _n, _s, f in BOARDS)
STORIES = [
    "Default",
    "EditedUnsaved",
    "InvalidWidth",
    "Saving",
    "SaveFailed",
    "SaveFailedOffline",
    "AccessChanged",
    "Conflict",
    "DeletedElsewhere",
    "Locked",
    "Viewer",
    "ViewAs",
    "MultiSelectMixed",
    "BatchFailed",
    "ToolDefaults",
    "Fibonacci",
    "Text",
    "Measure",
    "Position",
    "Templates",
    "TemplateEmpty",
    "Comfortable",
    "Light",
    "HighContrast",
    "ForcedColors",
    "Zoom200",
]
# anatomy inputs (spec section 2): tokens by name; the values are read from the token files below
WIDTH = {"compact": 280, "comfortable": 320}
PAD = {"compact": "space.inset.md", "comfortable": "space.inset.lg"}
ROW = {"compact": "size.control.compact", "comfortable": "size.control.comfortable"}
LEGEND = {"compact": 20, "comfortable": 24}
HEADER = {"compact": (24, 16, 16), "comfortable": (32, 20, 20)}  # title, subtitle, status line
SWATCH_GAP = {"compact": "space.1", "comfortable": "space.2"}
SMALL_ROW = {"compact": 16, "comfortable": 20}  # a label, legend or counter line
SW, CUE, LINK = "swatch", "cue", "link"  # the colour block, the note's counter, the ghost row
VIEWPORT_H = (800, 400)  # 1280x800 at 100 %, the same at 200 % zoom (CSS px)


# --- helpers ---------------------------
def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def section(text: str, start: str, end: str) -> str:
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(end, i + len(start))
    return text[i : j if j > 0 else len(text)]


def table_rows(block: str) -> list[list[str]]:
    """The first Markdown table in a block as rows of stripped cells (header, divider dropped)."""
    rows: list[list[str]] = []
    started = False
    for ln in block.splitlines():
        if ln.startswith("|"):
            started = True
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue
            rows.append(cells)
        elif started:
            break
    return rows[1:] if rows else []


_THEME_CACHE: dict[str, dict[str, Any]] = {}


def theme(name: str) -> dict[str, Any]:
    if name not in _THEME_CACHE:
        files = [verify.PRIMITIVES, *verify.THEMES[name]]
        _THEME_CACHE[name] = verify.merged_set(files)
    return _THEME_CACHE[name]


def tok(name: str, th: str = "dark") -> Any:
    t = theme(th)
    if name not in t:
        raise KeyError(name)
    return verify.resolve(t[name]["$value"], t)


def hx(name: str, th: str) -> str:
    """A colour token's resolved hex in a theme; a PROPOSED swatch slot resolves via its alias."""
    if name.startswith("color.drawing.palette."):
        return str(tok(SLOT_ALIAS[th][int(name.rsplit(".", 1)[1]) - 1], th)).upper()
    return str(tok(name, th)).upper()


def rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def ratio(fg: str, bg: str) -> float:
    r: float = contrast_check.contrast_ratio(rgb(fg), rgb(bg))
    return r


def blend(fg: str, bg: str, a: float) -> str:
    f, b = rgb(fg), rgb(bg)
    return "#" + "".join(f"{round(f[i] * a + b[i] * (1 - a)):02X}" for i in range(3))


def de(a: str, b: str) -> float:
    d: float = cvd.delta_e76(a, b)
    return d


def sim(h: str, kind: str) -> str:
    s: str = cvd.simulate(h, kind)
    return s.upper()


def luma(h: str) -> float:
    lum: float = cvd.relative_luminance(h)
    return lum


def fmt(x: float) -> str:
    return f"{x:.2f}"


def hue_word(alias: str) -> str:
    fam = alias.split(".")[1]
    if fam == "light":
        fam = alias.split(".")[2]
    return HUE_WORD.get(fam, fam)


def swatch_name(i: int, th: str) -> str:
    """E13-D03 section 13's grammar: the ordinal, the hue word of the active theme."""
    if i == 0:
        return f"Default, {hue_word(str(theme(th)['color.drawing.default']['$value']).strip('{}'))}"
    return f"Slot {i}, {hue_word(SLOT_ALIAS[th][i - 1])}"


# --- 1. the schema -----------------------
def api_rules() -> dict[str, Any]:
    """The 22 text: the per-tool point counts (D02's parser), the key rules and the bounds."""
    tools, counts = d02.api_tools()
    y = read(PLAN / "22-api-openapi.yaml")
    style = section(y, "    DrawingStyle:", "    DrawingInput:")
    geom = section(y, "    DrawingGeometry:", "    DrawingStyle:")
    inp = section(y, "    DrawingInput:", "    Drawing:\n")
    enum = section(y, "    DrawingTool:", "    DrawingPoint:")

    def rng(block: str, key: str) -> tuple[str, str]:
        m = re.search(key + r":\s*\{[^}]*minimum:\s*([-\d.]+)[^}]*maximum:\s*([-\d.]+)", block)
        if m:
            return m.group(1), m.group(2)
        m = re.search(key + r":\s*\n((?:\s{10}.*\n)+)", block)
        body = m.group(1) if m else ""
        lo = re.search(r"min(?:imum|Length|Items):\s*([-\d.]+)", body)
        hi = re.search(r"max(?:imum|Length|Items):\s*([-\d.]+)", body)
        return (lo.group(1) if lo else "?", hi.group(1) if hi else "?")

    return {
        "tools": tools,
        "points": counts,
        "width": rng(style, "width"),
        "font_size": rng(style, "font_size"),
        "fill_opacity": rng(style, "fill_opacity"),
        "dash": re.findall(r"dash:\s*\{[^}]*enum:\s*\[([^\]]*)\]", style),
        "levels": rng(geom, "levels"),
        "levels_range": (
            re.search(r"minimum:\s*(-1000)", geom) is not None,
            re.search(r"maximum:\s*(1000)", geom) is not None,
        ),
        "bands": re.search(r"enum:\s*\[1,\s*2,\s*3\]", geom) is not None,
        "text": rng(geom, "text"),
        "label": rng(inp, "label"),
        "text_only": "`text` is required for `text` and `callout`" in enum,
        "levels_only": "`levels` only for `fib_retracement`, `fib_extension`, `fib_timezone`"
        in enum,
        "bands_only": "`bands` only for\n        `anchored_vwap`" in enum
        or "`bands` only for `anchored_vwap`" in enum.replace("\n        ", " "),
        "extend_all": "`extend_left` / `extend_right` are allowed on every tool" in enum,
        "has_colour": 'colour: { type: string, pattern: "^#[0-9a-fA-F]{6}$" }' in style,
        "has_fill_colour": "fill_colour" in style,
        "locked_visible": "locked: { type: boolean" in inp and "visible: { type: boolean" in inp,
        "no_field": [
            k for k in ("template", "default", "flatten", "snap", "magnet", "units") if k in style
        ],
    }


def derive_schema(api: dict[str, Any]) -> list[dict[str, str]]:
    """One row per D02 registry row, in D02's order, with D04's cells."""
    rows: list[dict[str, str]] = []
    for r in d02.REG:
        rid, _name, tool, _anchors, group, _key, _story, status = r[:8]
        row = {c: "" for c in COLS}
        row["id"] = rid
        row["`DrawingTool`"] = f"`{tool}`" if tool != "-" else "—"
        row["status"] = status
        if group == "cursor" or group.startswith("controls"):
            fill = NO_POPOVER if group == "cursor" else NA
            for c in COLS[2:-1]:
                row[c] = fill
            row["anchors"] = "—"
            rows.append(row)
            continue
        if tool == "-":  # the emoji marker
            for c in COLS[2:-1]:
                row[c] = "—"
            row["slot"] = "no `DrawingTool` value (G1)"
            row["status"] = status.replace("deferred - ", "deferred — ")
            rows.append(row)
            continue
        n = api["points"][tool]
        row["anchors"] = f"`geometry.points` \u00d7 {n}"
        row["colour"] = "`style.colour`"
        row["width"] = (
            f"`style.width` {api['width'][0]}..{api['width'][1]}" if tool != "text" else NO_BOX
        )
        row["style"] = "`style.dash`" if tool != "text" else NO_BOX
        row["extend L / R"] = (
            "`geometry.extend_left` / `extend_right`" if tool in EXTEND else NOT_SHOWN
        )
        row["fill"] = (
            "`style.fill_colour` / `fill_opacity` "
            f"{api['fill_opacity'][0]}..{api['fill_opacity'][1]} + flatten (G-T4)"
            if tool in FILLED
            else "—"
        )
        row["font size"] = (
            f"`style.font_size` {api['font_size'][0]}..{api['font_size'][1]}"
            if tool in TEXT_TOOLS
            else "—"
        )
        row["label"] = f"`label` {api['label'][0]}..{api['label'][1]}"
        row["lock / visible"] = "`locked` / `visible`"
        row["slot"] = SLOT_CELL[SLOT.get(tool, "")]
        if status.startswith("deferred"):
            row["status"] = DEFER
        rows.append(row)
    return rows


def schema_table(rows: list[dict[str, str]]) -> str:
    head = "| " + " | ".join(COLS) + " |\n|" + "|".join(" --- " for _ in COLS) + "|\n"
    return head + "".join("| " + " | ".join(r[c] for c in COLS) + " |\n" for r in rows)


def spec_schema_rows(spec: str) -> list[dict[str, str]]:
    block = section(spec, "\n## 3.", "\n## 4.")
    out: list[dict[str, str]] = []
    for cells in table_rows(block):
        if len(cells) == len(COLS):
            out.append(dict(zip(COLS, cells, strict=True)))
    return out


def schema_report(fails: list[str], spec: str, api: dict[str, Any]) -> dict[str, Any]:
    rows = derive_schema(api)
    got = spec_schema_rows(spec)
    tools = [r for r in rows if r["`DrawingTool`"] != "—"]
    cursor = [r for r in rows if r["colour"] == NO_POPOVER]
    controls = [r for r in rows if r["colour"] == NA]
    deferred = [r for r in rows if r["status"].startswith("deferred")]
    if len(tools) != len(api["tools"]):
        fails.append(f"schema: {len(tools)} tool rows vs {len(api['tools'])} DrawingTool values")
    if {r["`DrawingTool`"].strip("`") for r in tools} != set(api["tools"]):
        fails.append("schema: the tool rows and the DrawingTool enum differ")
    for key in (
        "text_only",
        "levels_only",
        "bands_only",
        "extend_all",
        "has_colour",
        "locked_visible",
    ):
        if not api[key]:
            fails.append(f"22 rule not found in the text: {key}")
    if api["no_field"]:
        fails.append(f"22 DrawingStyle unexpectedly carries {api['no_field']}")
    if api["width"] != ("1", "8") or api["font_size"] != ("8", "48"):
        fails.append(f"22 bounds moved: width {api['width']} font_size {api['font_size']}")
    if api["levels"] != ("1", "24") or api["text"] != ("1", "1000") or api["label"] != ("1", "120"):
        fails.append(
            f"22 caps moved: levels {api['levels']} text {api['text']} label {api['label']}"
        )
    if not (api["bands"] and all(api["levels_range"])):
        fails.append("22 bands enum or levels range moved")
    for r in tools:
        t = r["`DrawingTool`"].strip("`")
        if ("geometry.text" in r["slot"]) != (t in TEXT_TOOLS):
            fails.append(f"schema: text slot on {t}")
        if ("geometry.levels" in r["slot"]) != (t in FIB):
            fails.append(f"schema: levels slot on {t}")
        if ("geometry.bands" in r["slot"]) != (t == "anchored_vwap"):
            fails.append(f"schema: bands slot on {t}")
        if ("fill_colour" in r["fill"]) != (t in FILLED):
            fails.append(f"schema: fill fields on {t}")
        if ("extend_left" in r["extend L / R"]) != (t in EXTEND):
            fails.append(f"schema: extend fields on {t}")
    # the spec's table must equal the derivation cell by cell
    if not got:
        fails.append("spec section 3 table not found")
    elif len(got) != len(rows):
        fails.append(f"spec section 3 has {len(got)} rows, the derivation {len(rows)}")
    else:
        for want, have in zip(rows, got, strict=True):
            for c in COLS:
                if want[c] != have[c]:
                    fails.append(
                        f"spec section 3 row {want['id']} cell {c!r}: {have[c]!r} != {want[c]!r}"
                    )
                    break
    g_cells = sum(1 for r in rows for c in COLS if "G-T" in r[c] or "(G1)" in r[c])
    shared_cols = [c for c in COLS[3:11]]
    slot_kinds = sorted({SLOT.get(r["`DrawingTool`"].strip("`"), "") for r in tools} - {""})
    return {
        "rows": len(rows),
        "tools": len(tools),
        "cursor": len(cursor),
        "controls": len(controls),
        "deferred": len(deferred),
        "shared_fields": len(shared_cols),
        "slot_kinds": slot_kinds,
        "slots": len(slot_kinds),
        "g_cells": g_cells,
        "filled": [t for t in FILLED if t in api["tools"]],
        "table": schema_table(rows),
        "spec_rows": len(got),
    }


# --- 2. the anatomy ----------------------
def px(name: str) -> int:
    return int(float(str(tok(name))))


def anatomy_report(fails: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    # Sections per tool at the default state (spec section 2.1), each a list of items: an int n is
    # n field rows; SW is the colour block (the group-label row + the tile row + the legend row);
    # CUE is the note's counter line; LINK is the Manage templates ghost row. Anchors and Templates
    # are closed CMP-065 disclosures by default (a legend row only: []), opened in the "(... open)"
    # case; Fill shows the "Same as stroke" box checked, so no fill swatch row; text hides width and
    # style (section 3). Section order: Style, [Fill], [Geometry], Visibility and lock, Anchors,
    # [the slot], Alert, Templates, Actions.
    cases: dict[str, list[list[Any]]] = {
        "trendline": [[SW, 1, 1, 1], [1, 1], [1, 1], [], [1], [], [1]],
        "trendline (anchors and templates open)": [
            [SW, 1, 1, 1],
            [1, 1],
            [1, 1],
            [1, 1],
            [1],
            [1, 1, LINK],
            [1],
        ],
        "rectangle": [[SW, 1, 1, 1], [1, 1, 1], [1, 1], [1, 1], [], [1], [], [1]],
        "text": [[SW, 1, 1], [1, 1], [], [3, CUE], [1], [], [1]],
        "fib_retracement (7 levels)": [[SW, 1, 1, 1], [1, 1], [1, 1], [], [1] * 8, [1], [], [1]],
        "fib_retracement (24 levels)": [[SW, 1, 1, 1], [1, 1], [1, 1], [], [1] * 25, [1], [], [1]],
    }
    for dens in ("compact", "comfortable"):
        pad, row, gap = px(PAD[dens]), px(ROW[dens]), px("space.field.gap")
        stack = px("space.stack.md") if dens == "compact" else px("space.stack.lg")
        title, sub, status = HEADER[dens]
        inner = WIDTH[dens] - 2 * pad
        small = SMALL_ROW[dens]
        d: dict[str, Any] = {
            "width": WIDTH[dens],
            "pad": pad,
            "inner": inner,
            "row": row,
            "gap": gap,
            "stack": stack,
            "legend": LEGEND[dens],
            "small_row": small,
            "swatch_block": small + row + small,
            "header": title + sub + status,
        }
        item_h = {SW: small + row + small, CUE: small, LINK: LEGEND[dens]}
        heights: dict[str, int] = {}
        for name, secs in cases.items():
            body = 0
            for items in secs:
                rows_h = sum(item_h[i] if isinstance(i, str) else int(i) * row for i in items)
                body += LEGEND[dens] + rows_h + max(0, len(items) - 1) * gap
            body += (len(secs) - 1) * stack
            heights[name] = pad + d["header"] + stack + body + pad
        d["heights"] = heights
        d["vh90"] = {str(v): int(0.9 * v) for v in VIEWPORT_H}
        d["scrolls"] = {
            str(v): [n for n, h in heights.items() if h > int(0.9 * v)] for v in VIEWPORT_H
        }
        d["fits_800"] = [n for n, h in heights.items() if h <= int(0.9 * VIEWPORT_H[0])]
        tile, radio, sgap = px("size.icon.md"), px("size.target.min"), px(SWATCH_GAP[dens])
        row_width = 9 * radio + 8 * sgap
        d["swatch"] = {
            "tile": tile,
            "radio": radio,
            "gap": sgap,
            "row_width": row_width,
            "fits": row_width <= inner,
            "stroke_px": px("border.thick"),
            "ring_px": px("border.thick"),
            "ring_box": radio,
            "check": px("size.icon.sm"),
            "focus_offset": px("border.focus"),
            "focus_box": radio + 2 * (px("border.focus") + px("border.thick")),
            "label_row": small,
        }
        if row_width > inner:
            fails.append(
                f"anatomy: the swatch rows ({row_width}) overflow the inner width {inner} ({dens})"
            )
        out[dens] = d
    out["type"] = {
        "label": f"{px('font.size.sm')} / {px('font.weight.medium')}",
        "caption": f"{px('font.size.xs')} / {px('font.weight.regular')}",
        "body": f"{px('font.size.base')} / {px('font.weight.regular')}",
        "num_md": f"{px('font.size.md')} / {px('font.weight.medium')} mono",
    }
    out["radius"] = {
        "card": px("radius.card"),
        "control": px("radius.control"),
        "dialog": px("radius.dialog"),
    }
    out["motion"] = {
        k: str(tok(f"motion.duration.{k}")) for k in ("instant", "fast", "normal", "slow")
    }
    out["opacity_disabled"] = float(str(tok("opacity.disabled")))
    return out


# --- 3. the matrix -----------------------
# element | fg | bg | role ; role: text 4.5, non-text 3.0, structure (reported), reported (adjacent)
PAIRS_TXT = """
D02 s15 title / cell text|color.text.primary|color.surface.canvas|text
D02 s15 title / cell text|color.text.primary|color.surface.raised|text
D02 s15 title / cell text|color.text.primary|color.surface.sunken|text
D02 s15 labels|color.text.secondary|color.surface.canvas|text
D02 s15 labels|color.text.secondary|color.surface.raised|text
D02 s15 labels|color.text.secondary|color.surface.sunken|text
D02 s15 footnotes; E09-D09 s11 the T2 label on raised|color.text.tertiary|color.surface.canvas|text
D02 s15 footnotes; E09-D09 s11 the T2 label on raised|color.text.tertiary|color.surface.raised|text
D02 s15 footnotes; E09-D09 s11 the T2 label on raised|color.text.tertiary|color.surface.sunken|text
D02 s15 outlines (structure only)|color.border.default|color.surface.canvas|structure
D02 s15 outlines (structure only)|color.border.default|color.surface.raised|structure
D02 s15 outlines (structure only)|color.border.default|color.surface.sunken|structure
D02 s15 chip outlines (structure only)|color.border.strong|color.surface.canvas|structure
D02 s15 chip outlines (structure only)|color.border.strong|color.surface.raised|structure
D02 s15 chip outlines (structure only)|color.border.strong|color.surface.sunken|structure
E30-D02 361 focus ring on the panel|color.focus.ring|color.surface.canvas|non-text
E30-D02 361 focus ring on raised|color.focus.ring|color.surface.raised|non-text
popover title, field values, Kbd on the overlay|color.text.primary|color.surface.overlay|text
labels, notice, T2 reasons, status text|color.text.secondary|color.surface.overlay|text
captions, counters, the legend on the overlay|color.text.tertiary|color.surface.overlay|text
field value, Kbd on a raised control|color.text.primary|color.surface.raised|text
T2 reason beside a raised control|color.text.secondary|color.surface.raised|text
the hairline on the overlay (structure only)|color.border.default|color.surface.overlay|structure
the meaning-carrying field border (E13-D03 s2)|color.text.tertiary|color.surface.overlay|non-text
chip outline on the overlay (structure only)|color.border.strong|color.surface.overlay|structure
focus ring on the overlay|color.focus.ring|color.surface.overlay|non-text
the checked radio's inner ring (E13-D03 322)|color.border.selected|color.surface.selected|non-text
the inner ring beside the canvas tile|color.border.selected|color.surface.canvas|non-text
the check glyph on the canvas tile|color.text.primary|color.surface.canvas|non-text
the tile border inside a selected radio|color.text.tertiary|color.surface.selected|non-text
the canvas tile's edge (structure only)|color.surface.canvas|color.surface.overlay|structure
focus ring vs the inner ring (never touching)|color.focus.ring|color.border.selected|reported
validity glyph (E30-D02 D16)|color.status.danger.strong|color.surface.overlay|non-text
the 2 px field boundary (E30-D02 D16)|color.status.danger.default|color.surface.overlay|non-text
Delete as danger-ink text (rejected)|color.status.danger.default|color.surface.overlay|rejected-text
Saved check glyph|color.status.success.default|color.surface.overlay|non-text
save-failed / offline glyph (.strong)|color.status.warning.strong|color.surface.overlay|non-text
warning.default (rejected)|color.status.warning.default|color.surface.overlay|rejected-non-text
Save (primary) fill on the overlay|color.action.primary.default|color.surface.overlay|non-text
Save (primary) label|color.text.on-action|color.action.primary.default|text
checked box (CMP-005 token rejected)|color.action.primary.default|color.surface.overlay|non-text
checkbox check glyph on the checked box|color.text.on-action|color.action.primary.default|non-text
unchecked checkbox border (the border rule)|color.text.tertiary|color.surface.overlay|non-text
CMP-005 fill as the box (rejected)|color.action.selected|color.surface.overlay|rejected-non-text
pairs.mjs drawing.selected on the canvas|color.drawing.selected|color.surface.canvas|non-text
"""
TOKEN_SET = {
    "color.surface.app",
    "color.surface.hover",
    "color.surface.selected",
    "color.text.link",
    "color.text.inverse",
    "color.text.disabled",
    "color.candle.up",
    "color.candle.down",
    "color.candle.wick",
    "color.cvd.buy",
    "color.cvd.sell",
    "color.status.warning.default",
    "color.status.info.default",
    "color.env.live",
    "color.env.demo",
}
BAR = {"text": 4.5, "non-text": 3.0, "rejected-text": 4.5, "rejected-non-text": 3.0}


def matrix_report(fails: list[str]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = [
        dict(zip(("element", "fg", "bg", "role"), ln.split("|"), strict=True))
        for ln in PAIRS_TXT.strip().splitlines()
    ]

    def sw(i: int) -> str:
        return f"swatch {i}" + (" (PROPOSED alias)" if i else "")

    for i, key in enumerate(SWATCH_KEYS):
        rows.append(
            {
                "element": f"{sw(i)} on the canvas",
                "fg": key,
                "bg": "color.surface.canvas",
                "role": "non-text",
            }
        )
    gated = failing = 0
    per_theme_fail = dict.fromkeys(THEMES, 0)
    for r in rows:
        r["ratios"] = {th: ratio(hx(r["fg"], th), hx(r["bg"], th)) for th in THEMES}
        bar = BAR.get(r["role"])
        if r["role"] in ("text", "non-text"):
            gated += 1
            bad = [th for th in THEMES if bar is not None and r["ratios"][th] < bar]
            r["verdict"] = "PASS" if not bad else "FAIL: " + ", ".join(bad)
            if bad:
                failing += 1
                for th in bad:
                    per_theme_fail[th] += 1
                fails.append(
                    f"matrix: {r['element']} ({r['fg']} on {r['bg']}) under {bar} in {bad}"
                )
        elif r["role"].startswith("rejected"):
            bad = [th for th in THEMES if bar is not None and r["ratios"][th] < bar]
            r["verdict"] = (
                "rejected by design; would FAIL: " + ", ".join(bad)
                if bad
                else "passes (not relied on)"
            )
        else:
            r["verdict"] = "reported"
    rep: dict[str, Any] = {
        "d02_s15": {f"{r['fg']}|{r['bg']}": fmt(r["ratios"]["dark"]) for r in rows[:15]},
        "d02_s15_light_hc": {
            f"{r['fg']}": (fmt(r["ratios"]["light"]), fmt(r["ratios"]["high-contrast"]))
            for r in rows[:15]
            if r["bg"] == "color.surface.canvas"
        },
        "e30_d02_361": [fmt(rows[15]["ratios"][th]) for th in THEMES]
        + [fmt(rows[16]["ratios"][th]) for th in THEMES],
        "e09_d09_s11_tertiary_raised": [fmt(rows[7]["ratios"][th]) for th in THEMES],
        "e13_d03_s31_dark": [
            fmt(ratio(hx(f"color.drawing.palette.{i}", "dark"), hx("color.surface.canvas", "dark")))
            for i in range(1, 9)
        ],
    }
    if [float(v) for v in rep["e13_d03_s31_dark"]] != list(E13_SLOT_CANVAS_DARK):
        fails.append(
            f"E13-D03 s3.1 reproduction: {rep['e13_d03_s31_dark']} != {E13_SLOT_CANVAS_DARK}"
        )
    ring = next(
        r
        for r in rows
        if r["fg"] == "color.border.selected" and r["bg"] == "color.surface.selected"
    )
    rep["e13_d03_322_inner_ring"] = [fmt(ring["ratios"][th]) for th in THEMES]
    if [float(v) for v in rep["e13_d03_322_inner_ring"]] != list(E13_INNER_RING):
        fails.append(
            f"E13-D03 line 322 reproduction: {rep['e13_d03_322_inner_ring']} != {E13_INNER_RING}"
        )
    hc_over = set(verify.load("semantic-hc.tokens.json"))
    used = sorted({r[k] for r in rows for k in ("fg", "bg")} - set(SWATCH_KEYS[1:]))
    tokens = {
        th: {name: hx(name, th) for name in sorted(set(used) | set(SWATCH_KEYS) | TOKEN_SET)}
        for th in THEMES
    }
    no_hc = [t for t in used if t not in hc_over]
    return {
        "rows": rows,
        "count": len(rows),
        "gated": gated,
        "failing": failing,
        "per_theme_fail": per_theme_fail,
        "reproductions": rep,
        "no_hc_override": no_hc,
        "swatch_names": {th: [swatch_name(i, th) for i in range(9)] for th in THEMES},
        "swatch_hex": {th: [hx(k, th) for k in SWATCH_KEYS] for th in THEMES},
        "cross_theme": cross_theme(),
        "tokens": tokens,
    }


def cross_theme() -> dict[str, Any]:
    """3b: a stored hex is theme-fixed (22 DrawingStyle.colour) - each theme's set on the other
    theme's canvas, the hex collisions between the sets and the slots whose hue family changes."""
    out: dict[str, Any] = {}
    for th, oth in (("dark", "light"), ("light", "dark")):
        canvas = hx("color.surface.canvas", oth)
        vals = [ratio(hx(k, th), canvas) for k in SWATCH_KEYS]
        out[f"{th}_set_on_{oth}_canvas"] = [fmt(v) for v in vals]
        out[f"{th}_set_under_3_on_{oth}_canvas"] = [i for i, v in enumerate(vals) if v < 3.0]
    dk = {hx(k, "dark"): i for i, k in enumerate(SWATCH_KEYS)}
    lt = {hx(k, "light"): i for i, k in enumerate(SWATCH_KEYS)}
    out["collisions"] = [[h, dk[h], lt[h]] for h in dk if h in lt and dk[h] != lt[h]]
    out["family_changes"] = [
        i + 1
        for i in range(8)
        if hue_word(SLOT_ALIAS["dark"][i]) != hue_word(SLOT_ALIAS["light"][i])
    ]
    return out


# --- 4. the fill study -------------------
def max_alpha(th: str, swatch: str, n: int, order: str, pair: tuple[str, str]) -> float:
    """The largest a (step 0.01, contiguous from 0) keeping every ink >= 3:1 (05 s5 item 4)."""
    canvas, fill = hx("color.surface.canvas", th), hx(swatch, th)
    fgs = [hx(pair[0], th), hx(pair[1], th), hx("color.candle.wick", th)]
    best = 0.0
    for step in range(1, 101):
        a = step / 100
        eff = 1 - (1 - a) ** n
        bg = blend(fill, canvas, eff)
        ok = True
        for fg in fgs:
            ink = fg if order == "under" else blend(fill, fg, eff)
            if ratio(ink, bg) < 3.0:
                ok = False
                break
        if not ok:
            break
        best = a
    return best


def fill_report(fails: list[str], spec: str) -> dict[str, Any]:
    pairs = {
        "candles": ("color.candle.up", "color.candle.down"),
        "cvd": ("color.cvd.buy", "color.cvd.sell"),
    }
    table: list[dict[str, Any]] = []
    min3: dict[str, float] = {}
    excluded: list[str] = []
    for i, key in enumerate(SWATCH_KEYS):
        row: dict[str, Any] = {"swatch": key, "i": i}
        for th in THEMES:
            for order in ("under", "over"):
                for pname, pair in pairs.items():
                    vals = [max_alpha(th, key, n, order, pair) for n in (1, 2, 3)]
                    row[f"{th}|{order}|{pname}"] = vals
                    if pname == "candles":
                        k = f"{th}|{order}"
                        min3[k] = min(min3.get(k, 1.0), vals[2])
                        if vals[0] == 0.0 and f"{key}@{th}" not in excluded:
                            excluded.append(f"{key}@{th}")
        table.append(row)
    overall = min(v for v in min3.values())
    default = math.floor(overall * 20 + 1e-9) / 20
    min1 = {
        f"{th}|{o}": min(table[i][f"{th}|{o}|candles"][0] for i in range(len(SWATCH_KEYS)))
        for th in THEMES
        for o in ("under", "over")
    }
    overall1 = min(min1.values())
    flat_default = math.floor(overall1 * 20 + 1e-9) / 20
    flattened = {
        th: {k: table[i][f"{th}|over|candles"][0] for i, k in enumerate(SWATCH_KEYS)}
        for th in THEMES
    }
    stated = re.search(r"default `fill_opacity` of (\d\.\d\d) \(measured", spec)
    if not stated:
        fails.append("spec: the stated default fill_opacity sentence not found")
    elif float(stated.group(1)) != default:
        fails.append(f"spec: stated default {stated.group(1)} != computed {default:.2f}")
    if excluded and not all(e.split("@")[0] in spec for e in excluded):
        fails.append("spec: an excluded swatch is not named")
    if not excluded and re.search(r"excluded from fills: `color", spec):
        fails.append("spec names an excluded swatch but none fails")
    at_default: dict[str, dict[str, list[float]]] = {}
    for th in THEMES:
        canvas, fill = hx("color.surface.canvas", th), hx("color.drawing.default", th)
        inks = [hx(k, th) for k in ("color.candle.up", "color.candle.down", "color.candle.wick")]
        at_default[th] = {}
        for n in (1, 2, 3):
            eff = 1 - (1 - default) ** n
            bg = blend(fill, canvas, eff)
            at_default[th][f"stacked_{n}"] = [
                round(ratio(blend(fill, fg, eff), bg), 2) for fg in inks
            ]
        bg1 = blend(fill, canvas, default)
        at_default[th]["flattened"] = [
            round(ratio(blend(fill, fg, default), bg1), 2) for fg in inks
        ]
    limiting: dict[str, tuple[float, str]] = {}
    for th in THEMES:
        names = ("color.candle.up", "color.candle.down", "color.candle.wick")
        limiting[th] = min((ratio(hx(k, th), hx("color.surface.canvas", th)), k) for k in names)
    # the tint of a fill against the bare canvas: one / two / three stacked at the default, and one
    # layer at the flattened ceiling (how visible a new zone is where no candle sits)
    tint: dict[str, Any] = {}
    for th in THEMES:
        canvas = hx("color.surface.canvas", th)
        per: dict[str, list[float]] = {}
        for key in SWATCH_KEYS:
            f = hx(key, th)
            per[key] = [
                round(ratio(blend(f, canvas, 1 - (1 - default) ** n), canvas), 2) for n in (1, 2, 3)
            ] + [round(ratio(blend(f, canvas, flat_default), canvas), 2)]
        tint[th] = {
            "per_swatch": per,
            "one_layer": [min(v[0] for v in per.values()), max(v[0] for v in per.values())],
            "three_stacked": [min(v[2] for v in per.values()), max(v[2] for v in per.values())],
            "at_flat_ceiling": [min(v[3] for v in per.values()), max(v[3] for v in per.values())],
        }
    return {
        "table": table,
        "min3": min3,
        "overall_min3": overall,
        "default": default,
        "min1": min1,
        "overall_min1": overall1,
        "flat_default": flat_default,
        "flattened": flattened,
        "excluded": excluded,
        "step": 0.01,
        "round_to": 0.05,
        "at_default": at_default,
        "candle_on_canvas": {th: (fmt(v), k) for th, (v, k) in limiting.items()},
        "tint": tint,
    }


# --- 5. the CVD rows ---------------------
def cvd_report() -> dict[str, Any]:
    kinds = ("protanopia", "deuteranopia", "tritanopia")
    out: dict[str, Any] = {"rows": [], "collapses": [], "per_theme": {}}
    for th in THEMES:
        sw = [hx(k, th) for k in SWATCH_KEYS]
        pairs: list[tuple[str, str, str]] = []
        for i in range(9):
            for j in range(i + 1, 9):
                pairs.append((f"swatch {i} vs swatch {j}", sw[i], sw[j]))
        sel = hx("color.drawing.selected", th)
        for i in range(9):
            pairs.append((f"swatch {i} vs drawing.selected", sw[i], sel))
        pairs.append(
            ("status.danger.strong vs drawing.selected", hx("color.status.danger.strong", th), sel)
        )
        ok_, wn, dg = [
            hx(f"color.status.{k}.default", th) for k in ("success", "warning", "danger")
        ]
        pairs += [
            ("success vs warning", ok_, wn),
            ("warning vs danger", wn, dg),
            ("success vs danger", ok_, dg),
        ]
        pairs.append(
            (
                "T2 fill (raised) vs overlay",
                hx("color.surface.raised", th),
                hx("color.surface.overlay", th),
            )
        )
        n_collapse = 0
        for name, a, b in pairs:
            des = {k: de(sim(a, k), sim(b, k)) for k in kinds}
            des["none"] = de(a, b)
            low = [k for k, v in des.items() if v < 5.0]
            out["rows"].append(
                {
                    "theme": th,
                    "pair": name,
                    "de": {k: round(v, 1) for k, v in des.items()},
                    "low": low,
                }
            )
            if low:
                n_collapse += 1
                out["collapses"].append(f"{th}: {name} ({', '.join(low)})")
        out["per_theme"][th] = {"pairs": len(pairs), "collapses": n_collapse}
    out["count"] = len(out["rows"])
    out["luma"] = {
        th: {
            k: round(luma(hx(k, th)), 3)
            for k in (
                "color.surface.overlay",
                "color.surface.raised",
                "color.surface.canvas",
                "color.action.primary.default",
                "color.action.selected",
                "color.drawing.selected",
                "color.status.danger.default",
                "color.status.success.default",
                "color.status.warning.default",
                *SWATCH_KEYS,
            )
        }
        for th in THEMES
    }
    return out


# --- 6. token bindings -------------------
TOKEN_RE = re.compile(
    r"`((?:color|space|size|radius|border|type|elevation|opacity|motion)\.[A-Za-z0-9.-]+)`"
)


def state_rows(spec: str) -> list[list[str]]:
    return table_rows(section(spec, "\n## 8.", "\n## 9."))


def binding_report(fails: list[str], spec: str) -> dict[str, Any]:
    dark = theme("dark")
    bound: dict[str, str] = {}
    missing: list[str] = []
    proposed: list[str] = []
    for ln in spec.splitlines():
        for name in TOKEN_RE.findall(ln):
            if name in dark:
                bound[name] = "ok"
            elif name.startswith("color.drawing.palette.") and "PROPOSED" in ln:
                proposed.append(name)
            else:
                missing.append(name)
    missing = sorted(set(missing))
    if missing:
        fails.append(
            "tokens not in the merged dark set and not PROPOSED on their row: " + ", ".join(missing)
        )
    icon_lines = [ln for ln in spec.splitlines() if "color.icon." in ln]
    if any("G-T" not in ln for ln in icon_lines):
        fails.append("color.icon.* cited outside its G-row")
    rows = state_rows(spec)
    ids = [r[0].strip("`") for r in rows]
    want = [s[0] for s in STATES]
    if ids != want:
        fails.append(f"spec section 8 state ids differ from the tool's list: {ids} vs {want}")
    kinds: dict[str, int] = {}
    for r in rows:
        if len(r) < 2:
            continue
        text = " | ".join(r)
        kind = r[1].split()[0] if r[1] else ""
        kinds[kind] = kinds.get(kind, 0) + 1
        if kind == "T2":
            if "color.text.disabled" in text or "opacity.disabled" in text:
                fails.append(f"T2 row {r[0]} carries a dimming token")
            if "T2" not in text or "lock" not in text.lower() or "aria-disabled" not in text:
                fails.append(f"T2 row {r[0]} lacks T2 / the lock glyph / aria-disabled")
        if kind == "validity" and (
            "opacity.disabled" not in text or "T2" in text or "lock" in text.lower()
        ):
            fails.append(f"validity row {r[0]} must carry opacity.disabled and never T2 or lock")
    exp = {
        k: sum(1 for s in STATES if s[1] == k)
        for k in ("T2", "validity", "marker", "outcome", "none")
    }
    if rows and kinds != exp:
        fails.append(f"spec section 8 kinds {kinds} != {exp}")
    return {
        "bound": len(bound),
        "proposed": sorted(set(proposed)),
        "missing": missing,
        "kinds": exp,
        "states": len(STATES),
    }


# --- 7. string gates ---------------------
LOCAL_PATH = re.compile(r"/(?:home|Users)/[^/\s]+/")
PENPOT_HOST = re.compile(r"penpot\.[a-z0-9-]+\.[a-z]{2,}", re.IGNORECASE)
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d", re.IGNORECASE)


def string_report(fails: list[str], spec: str, hand: str, fill: dict[str, Any]) -> dict[str, Any]:
    both = spec + "\n" + hand
    checks: dict[str, bool] = {
        "T2 rule stated once": spec.count("stated once here and cited from every gated row") == 1,
        "view-as leg first": "the view-as leg first" in spec,
        "four kinds of no named once": spec.count('**Four kinds of "no"') == 1,
        "no same-as-dark": "same as dark" not in both.lower(),
        "no placeholder words": not re.search(r"SET-ME|\bTODO\b|\bTBD\b", both),
        "no local path": not LOCAL_PATH.search(both),
        "no penpot host": not PENPOT_HOST.search(both),
        "no pageLink": "pageLink" not in both,
        "no closing keyword": not CLOSING.search(both),
        "template cap 80 with its 22 line": "1..80" in spec and "22:19527" in spec,
        "stated default with measured": f"default `fill_opacity` of {fill['default']:.2f} (measured"
        in spec,
        "no merges-as-is qualifier (E13-D03 merged)": "merges as is" not in both,
        "section 17 names the frame count": f"{FRAMES_TOTAL} nested frames"
        in section(spec, "\n## 17.", "\n## 18."),
        "colour-custom legend word": "Custom colour" in spec,
        "handoff names G-T11": "G-T11" in hand,
        "forced-colors T2 label in CanvasText": "GrayText"
        not in section(spec, "\n## 8.", "\n## 9."),
        "handoff has three blocks": hand.count("## Handoff checklist —") == 3,
        "handoff has no blank checklist line": not [
            ln for ln in hand.splitlines() if ln.startswith("- [ ]") and "N/A" not in ln
        ],
        "Q1-Q16 RULED by issuecomment id, nothing pending": "6362143576" in spec
        and "RULING PENDING" not in spec
        and "no orchestrator ruling exists" not in spec,
        "the PROPOSED quota key named": "alert.quota_reached" in spec,
        "rendering 2b named in section 8": "(2b)" in section(spec, "\n## 8.", "\n## 9."),
    }
    boards = table_rows(section(spec, "\n## 0.", "\n## 1."))
    checks["ten board rows, every one PENDING"] = len(boards) == len(BOARDS) and all(
        r[-1] == "PENDING" for r in boards
    )
    anatomy = section(spec, "\n## 2.", "\n## 3.")
    checks["no trading word in the anatomy"] = not re.search(
        r"\b(?:Buy|Sell|Place|Order)\b", anatomy
    )
    for name, ok in checks.items():
        if not ok:
            fails.append(f"string gate: {name}")
    return {"checks": checks, "boards_in_spec": len(boards)}


# --- 8. the counts -----------------------
def counts_report(spec: str, hand: str) -> dict[str, Any]:
    s16 = section(spec, "\n## 16.", "\n## 17.")
    ids = {
        p: sorted({m for m in re.findall(rf"^\| ({p}\d+)\s*\|", s16, re.MULTILINE)})
        for p in ("A", "C", "G-T", "Q")
    }
    frames = {n: list(fr) for n, _slug, fr in BOARDS}
    for sid, _kind, board in STATES:
        if sid not in frames[board]:
            raise SystemExit(f"state {sid} has no frame on board {board}")
    km = json.loads(
        (ROOT / "apps" / "web" / "src" / "keymap" / "keymap.json").read_text(encoding="utf-8")
    )
    lint = keymap_lint.lint_keymap(km)
    return {
        "boards": len(BOARDS),
        "light_twins": len(LIGHT_TWINS),
        "frames_per_board": {b: len(f) for b, f in frames.items()},
        "frames_total": sum(len(f) for f in frames.values()),
        "states": len(STATES),
        "stories": len(STORIES),
        "swatches": len(SWATCH_KEYS),
        "A": len(ids["A"]),
        "C": len(ids["C"]),
        "G": len(ids["G-T"]),
        "Q": len(ids["Q"]),
        "handoff_blocks": hand.count("## Handoff checklist —"),
        "handoff_lines": len(hand.splitlines()),
        "spec_lines": len(spec.splitlines()),
        "keymap_commands": len(km["commands"]),
        "keymap_lint_errors": len(lint),
    }


# --- main ---------------------------------
def p(line: str = "") -> None:
    sys.stdout.write(line + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="E14-D04 drawing-properties popover audit")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true", help="exit 1 on any gated FAIL")
    ap.add_argument("--table", action="store_true", help="print the derived section-3 table only")
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # TextIO at runtime
    except (AttributeError, ValueError):
        pass
    fails: list[str] = []
    spec, hand = read(SPEC), read(HANDOFF)
    api = api_rules()
    if args.table:
        sys.stdout.write(schema_table(derive_schema(api)))
        return 0
    schema = schema_report(fails, spec, api)
    anatomy = anatomy_report(fails)
    matrix = matrix_report(fails)
    fill = fill_report(fails, spec)
    cvdr = cvd_report()
    binding = binding_report(fails, spec)
    strings = string_report(fails, spec, hand, fill)
    counts = counts_report(spec, hand)
    out = {
        "schema": {k: v for k, v in schema.items() if k != "table"},
        "anatomy": anatomy,
        "matrix": {k: v for k, v in matrix.items() if k != "rows"},
        "fill": fill,
        "cvd": {k: v for k, v in cvdr.items() if k != "rows"},
        "binding": binding,
        "strings": strings,
        "counts": counts,
        "fails": fails,
    }
    if args.json:
        sys.stdout.write(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    else:
        p("## 1. Schema parity (spec s3 vs D02 REG vs 22)")
        sc = schema
        p(
            f"rows {sc['rows']} = tools {sc['tools']} + cursor {sc['cursor']} + controls "
            f"{sc['controls']} + emoji 1; deferred {sc['deferred']}; shared field columns "
            f"{sc['shared_fields']}; slot kinds {sc['slots']} {sc['slot_kinds']}; G cells "
            f"{sc['g_cells']}; spec rows {sc['spec_rows']}"
        )
        p(
            f"22 bounds: width {api['width']} font_size {api['font_size']} fill_opacity "
            f"{api['fill_opacity']} levels {api['levels']} text {api['text']} label "
            f"{api['label']} dash {api['dash']}"
        )
        p("## 2. Anatomy")
        for dens in ("compact", "comfortable"):
            d = anatomy[dens]
            p(
                f"{dens}: width {d['width']} pad {d['pad']} inner {d['inner']} row {d['row']} "
                f"gap {d['gap']} stack {d['stack']} legend {d['legend']} header {d['header']}"
            )
            p(f"  heights {d['heights']}; 90 vh {d['vh90']}; scrolls {d['scrolls']}")
            p(f"  fits 90 vh at 800: {d['fits_800']}")
            p(f"  swatch {d['swatch']}")
        p(f"type {anatomy['type']} radius {anatomy['radius']} motion {anatomy['motion']}")
        p(f"opacity.disabled {anatomy['opacity_disabled']}")
        p("## 3. Matrix (dark / light / high-contrast)")
        for r in matrix["rows"]:
            p(
                f"{r['element']} | {r['fg']} on {r['bg']} | {r['role']} | "
                + " / ".join(fmt(r["ratios"][th]) for th in THEMES)
                + f" | {r['verdict']}"
            )
        p(
            f"pairs {matrix['count']}, gated {matrix['gated']}, failing {matrix['failing']} "
            f"{matrix['per_theme_fail']}"
        )
        p(f"reproductions {matrix['reproductions']}")
        p(f"no hc override: {matrix['no_hc_override']}")
        p(f"swatch names {matrix['swatch_names']}; hex {matrix['swatch_hex']}")
        p(f"3b. swatch hexes across themes {matrix['cross_theme']}")
        p("## 4. Fill-opacity study (max a per swatch: 1 / 2 / 3 stacked; under = the fill under")
        p("   the candles, over = the fill over them)")
        for row in fill["table"]:
            p(f"{row['swatch']}: " + "; ".join(f"{k} {v}" for k, v in row.items() if "|" in k))
        p(
            f"three-stack minima {fill['min3']}; overall {fill['overall_min3']:.2f}; stated "
            f"default {fill['default']:.2f}"
        )
        p(
            f"one-layer minima {fill['min1']}; overall {fill['overall_min1']:.2f}; flattened "
            f"ceiling {fill['flat_default']:.2f}"
        )
        p(f"per swatch, one layer over the candles {fill['flattened']}")
        p(f"candle inks at the default (up / down / wick; over): {fill['at_default']}")
        p("tint vs the bare canvas (1 / 2 / 3 stacked at the default; one layer at the ceiling):")
        p(f"  {fill['tint']}")
        p(
            f"excluded {fill['excluded']}; the lowest candle ink on the canvas "
            f"{fill['candle_on_canvas']}"
        )
        p("## 5. CVD rows (CIE76 delta E; JND 5.0)")
        p(f"rows {cvdr['count']}; per theme {cvdr['per_theme']}")
        p(f"collapses: {cvdr['collapses']}")
        p(f"luma {cvdr['luma']}")
        p("## 6. Token bindings")
        p(f"bound {binding['bound']}, PROPOSED {binding['proposed']}, missing {binding['missing']}")
        p(f"state kinds {binding['kinds']}")
        p("## 7. String gates")
        p(str(strings))
        p("## 8. Counts")
        p(json.dumps(counts))
        p(f"FAIL count (gated): {len(fails)}")
        for f in fails:
            p("  FAIL " + f)
    return 1 if (args.check and fails) else 0


if __name__ == "__main__":
    raise SystemExit(main())
