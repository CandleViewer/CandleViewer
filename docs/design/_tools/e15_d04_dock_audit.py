#!/usr/bin/env python3
"""E15-D04 dock-system audit: every number the SCR-021 hi-fi spec quotes, and its frame gates.

Standalone, offline, stdlib only; it executes no repo code, calls no API and contacts no host. It
reads the token JSON, ``keymap.json``, ``reserved-keys.json``, the spec
``docs/design/E15/E15-D04.md``
and its handoff AS TEXT and prints, with a source label on every row: (1) the drop-zone geometry of
the PROPOSED rule (band = 25 % of the panel's smaller side, clamped 48-160 px; an axis whose two
bands would leave the centre under 48 px withdraws them) at the three panel sizes the ticket asks
for, plus the 200 % zoom case; (2) every drop the Positions panel can attempt in the ``dense``
fixture, the resulting rectangles and the constraint that refuses it (the depth limit, a full tab
group, then a width or height minimum, the moving panel's first, then the target's, then the rest
in tree order), the AC6 case and the chooser's verdict on the ``small`` Tape's withdrawn sides;
(3) the WCAG 2.x ratio of every colour carrier SCR-021 draws over the darkest and lightest panel
content in dark / light / high-contrast (``themes.json`` layering), two-tone carriers judged by the
better tone against the content and by the two tones against each other, with the Rec. 601
greyscale twin of every ratio, plus the three single-tone figures the spec quotes (the ring alone
over ``color.text.primary`` in dark and light, ``color.text.link`` in high contrast); (4) the
tokens the spec binds, resolved or MISSING; (5) the spec's structure counts.

The check (the default run, and ``--check SPEC [--pr-body FILE]``) exits 1 on any FAIL:
- markers: every ``<!-- audit:NAME=VALUE -->`` equals the derived value; unknown or missing = FAIL;
- numbers: every quoted number in a registered context (counts, bands, ratios, the AC6 and AC2
  sizes, the minimums, the refusal sentences) equals the tool's, and every site of a two-site
  context must be found; every section 3.1 row is re-derived from its size (smaller side, 25 %,
  band, centre, zones) and every section 12 cell from its carrier and theme; each placed refusal
  sentence is the tool's for its drop; every other ``W x H`` size and two-decimal ratio of the
  spec and the handoff is a value the tool derives;
- frames (A2, keyed on frame ids): every frame row of sections 3-9 draws its own carriers (the lit
  zone, the ghost, the hatch where a drop is refused, the stage-one target mark), names its ``Esc``
  exit where it is a drag or move-mode frame, and carries its one polite string; every frame row and
  every section-0 board row is scanned for chords neither in ``keymap.json`` nor PROPOSED in their
  clause; ``Ctrl+Z`` is only ever ``chart.undo`` there; every parity row has a keyboard path;
  every key-table row leads with existing (in the keymap) or PROPOSED / RULED / CARRIED and calls
  no key shipped; the move-mode bar is ``aria-atomic="false"``;
- T2 (A1), per frame: the text a ``move-to-submenu`` or ``dirty-save-view-as`` id owns (its
  parenthesis, else its sentence) carries the CMP-019 lock, its key and ``aria-disabled``; the
  text any other frame id owns on the lines of sections 0 and 3-9 (or no frame id) carries no
  lock, CMP-079 or ``aria-disabled``, a shared line included; no frame clause gates ``Esc``; the
  one T2 statement is present;
- exits (A3), hygiene (no local path, no design-tool host), and with ``--pr-body`` no closing
  keyword.

``--self-test [SPEC]`` runs MUTATIONS on the spec in memory (the file is never written): each must
exit 1 with exactly one new FAIL, no two mutations may raise the same FAIL, and the clean spec must
exit 0 before and after. ``--json`` prints one object (the board script's check consumes it).

Usage: python3 -I docs/design/_tools/e15_d04_dock_audit.py [--json]
       python3 -I docs/design/_tools/e15_d04_dock_audit.py --check SPEC [--pr-body FILE]
       python3 -I docs/design/_tools/e15_d04_dock_audit.py --self-test [SPEC]
"""

from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
KEYMAP = ROOT / "apps" / "web" / "src" / "keymap" / "keymap.json"
RESERVED = ROOT / "apps" / "web" / "src" / "keymap" / "reserved-keys.json"
SPEC = ROOT / "docs" / "design" / "E15" / "E15-D04.md"
HANDOFF = ROOT / "docs" / "design" / "E15" / "E15-D04-handoff.md"
PRIM, DARK, LIGHT, HC = (
    "primitives.tokens.json",
    "semantic-dark.tokens.json",
    "semantic-light.tokens.json",
    "semantic-hc.tokens.json",
)
THEMES: dict[str, tuple[str, ...]] = {
    "dark": (PRIM, DARK),
    "light": (PRIM, DARK, LIGHT),
    "high-contrast": (PRIM, DARK, HC),
}
BAR: dict[str, float] = {"text": 4.5, "non-text": 3.0, "hc-text": 7.0}

# ---- the PROPOSED geometry rule (spec D04-D-1 .. D-3); every value below is printed, never typed
BAND_PCT = 0.25  # of the panel's smaller side
BAND_MIN = 48  # px, the clamp's floor (the 24 px target of `05` section 3.4 item 7, doubled)
BAND_MAX = 160  # px, the clamp's ceiling (E15-D02 P2-P6: "48-160 px")
CENTRE_MIN = 48  # px: an axis whose two bands leave less than this withdraws them
GUTTER = 4  # px between panels (E15-D02 D-23)
HIT_BAND = 24  # px, the splitter's hit band over the gutter (E15-D02 D-23)
ZONE_OUTLINE = 4  # px, the lit zone's outline (`14` SCR-021; E15-D02 P2-P6)
GHOST_OUTLINE = 2  # px, the ghost's outline (E15-D02 section 8 forced colours)
HALO = 1  # px, the contrasting halo on every two-tone carrier
HATCH_PITCH = 12  # px between hatch lines
STEP_FINE = 2  # %, arrow on a focused splitter (D-23)
STEP_COARSE = 10  # %, Shift + arrow (D-23)
ROW = {
    "compact": 24,
    "comfortable": 32,
}  # header, tab-group and tray rows (E15-D02 section 3)
BODY_ROWS_MIN = 4  # the smallest legible body: four rows (PROPOSED, spec D04-D-5)
GHOST_CARD = (240, 160)  # the ghost before any zone is lit (spec D04-D-6)
LABEL_OFFSET = 16  # px right of and below the pointer (spec D04-D-6, D04-D-7)
LABEL_MAX_W = 240  # px, the refusal pill's width cap (spec D04-D-7)
GRIP = {"compact": (24, 4), "comfortable": (32, 4)}  # the splitter grip (spec D04-D-10)
STOP_MARK = (12, 12)  # the at-minimum stop mark (spec D04-D-10)
TARGET_MIN = (24, 24)  # `05` section 3.4 item 7
# The shell at each viewport (E15-D02 D-2 and section 3): TopBar 80, StatusBar 48, NavRail 64,
# RightRail 48, tab strip 32 compact.
SHELL = {"top": 80, "status": 48, "nav": 64, "right": 48, "tabstrip": 32}
VIEWPORTS = {
    "1920x1080": (1920, 1080),
    "1280x800": (1280, 800),
    "zoom200": (640, 400),
    "1024x800": (1024, 800),  # the compact-view frame's window (spec section 8)
}
# Header minimums at compact (E15-D02 section 3, OQ-B) and the Positions floor (E29-D01 D1).
MIN_WIDTH = {"chart": 328, "dom": 380, "tape": 232, "positions": 300}
# Rows above the body per kind: a chart carries its status row and its time strip (E15-D02 s. 3).
CHROME_ROWS = {"chart": 3, "dom": 1, "tape": 1, "positions": 1}
DEPTH_MAX = 6  # `22` LayoutGridSpec: depth at most 6 counting the root
NODES_MAX = 64
LEAVES_MAX = 16
TABSET_MAX = 16
LABEL = {"chart": "Chart", "dom": "DOM", "tape": "Tape", "positions": "Positions"}

Tree = dict[str, Any]
Rect = dict[str, Any]

# Fixtures (E15-D02 section 5.3: the Positions panel in the `dense` layout; P9's result
# `row [column [chart, positions], DOM, tape]` fixes the starting tree as a column with the row
# above).
DENSE: Tree = {
    "type": "column",
    "sizes": [0.68, 0.32],
    "children": [
        {
            "type": "row",
            "sizes": [0.45, 0.33, 0.22],
            "children": [{"leaf": "chart"}, {"leaf": "dom"}, {"leaf": "tape"}],
        },
        {"leaf": "positions"},
    ],
}
# The `small` fixture holds a panel at its height minimum: the Tape under the DOM in the right
# column.
SMALL: Tree = {
    "type": "row",
    "sizes": [0.61, 0.39],
    "children": [
        {"leaf": "chart"},
        {
            "type": "column",
            "sizes": [0.81, 0.19],
            "children": [{"leaf": "dom"}, {"leaf": "tape"}],
        },
    ],
}

# ---- carriers: element | tone A | tone B (halo or backing) | kind | role ----
# kind "two-tone": A is the stroke, B its 1 px halo; the pair passes when A or B clears the bar
# against the content AND A clears it against B. kind "on": A is text or a stroke on the backing B.
CARRIERS: tuple[tuple[str, str, str, str, str], ...] = (
    ("lit zone outline (4 px)", "color.focus.ring", "color.surface.canvas", "two-tone", "non-text"),
    ("ghost outline (2 px)", "color.text.primary", "color.surface.canvas", "two-tone", "non-text"),
    (
        "hatch line (2 px, 12 px pitch)",
        "color.text.primary",
        "color.surface.canvas",
        "two-tone",
        "non-text",
    ),
    (
        "splitter grip, focused or dragging",
        "color.focus.ring",
        "color.surface.canvas",
        "two-tone",
        "non-text",
    ),
    (
        "splitter stop mark, at minimum",
        "color.text.primary",
        "color.surface.canvas",
        "two-tone",
        "non-text",
    ),
    (
        "focused panel bar (E15-D03's; context)",
        "color.focus.ring",
        "color.surface.raised",
        "on",
        "non-text",
    ),
    (
        "MoveModeBar instruction, labels, toast text, tray tabs",
        "color.text.primary",
        "color.surface.raised",
        "on",
        "text",
    ),
    (
        "MoveModeBar second line, compact-view line",
        "color.text.secondary",
        "color.surface.raised",
        "on",
        "text",
    ),
    (
        "toast [Undo], an underlined text button",
        "color.text.primary",
        "color.surface.raised",
        "on",
        "text",
    ),
    (
        "splitter line at rest (decorative)",
        "color.border.subtle",
        "color.surface.canvas",
        "on",
        "decorative",
    ),
)
# The content extremes per theme: the darkest fill a panel body can show, and the lightest.
EXTREMES = {
    "dark": ("color.surface.sunken", "color.text.primary"),
    "light": ("color.text.primary", "color.surface.app"),
    "high-contrast": ("color.surface.sunken", "color.text.primary"),
}
# fmt: off
BOUND = (
    "color.surface.app", "color.surface.canvas", "color.surface.raised", "color.surface.overlay",
    "color.surface.sunken", "color.border.subtle", "color.border.default", "color.border.strong",
    "color.text.primary", "color.text.secondary", "color.text.tertiary", "color.focus.ring",
    "color.env.demo", "color.env.live", "elevation.dock-focus", "elevation.popover", "radius.sm",
    "radius.md", "radius.pill", "border.hairline", "border.thick", "border.focus", "opacity.muted",
    "opacity.scrim", "size.target.min", "size.row.compact", "size.row.comfortable",
    "space.inset.sm", "motion.duration.instant", "motion.duration.fast",
)
# fmt: on
REQUESTED = (
    "color.accent.subtle",
    "motion.fast",
    "space.dockgrid.gutter",
    "color.border.panel",
    "color.surface.base",
)
# Hygiene: generic patterns only; no personal word and no hostname, whole or split. The path
# literal is split so this file never contains the string it forbids.
FORBIDDEN = (
    r"/(?:ho[m]e|Users)/[^/\s]+/",
    r"penpot\.[a-z0-9-]+\.[a-z]{2,}",
    r"team-i[d]=",
    r"file-i[d]=",
    r"wt-no[t]es",
)
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE)


# ------------------------------------------------------------------ tokens and contrast ----------
def walk(node: object, prefix: str, out: dict[str, object]) -> None:
    if isinstance(node, dict):
        if "$value" in node:
            out[prefix] = node["$value"]
            return
        for k, v in node.items():
            if not str(k).startswith("$"):
                walk(v, f"{prefix}.{k}" if prefix else str(k), out)


def token_file(name: str) -> dict[str, object]:
    out: dict[str, object] = {}
    walk(json.loads((TOKENS / name).read_text(encoding="utf-8")), "", out)
    return out


def load_theme(name: str) -> dict[str, object]:
    out: dict[str, object] = {}
    for f in THEMES[name]:
        out.update(token_file(f))
    return out


def resolve(tokens: dict[str, object], name: str, depth: int = 0) -> str:
    v = tokens.get(name)
    if v is None or depth > 8:
        return "MISSING"
    if isinstance(v, str) and v.startswith("{") and v.endswith("}"):
        return resolve(tokens, v[1:-1], depth + 1)
    return str(v)


def luminance(hex6: str) -> float:
    def lin(c: int) -> float:
        x = c / 255
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex6[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def grey(hex6: str) -> str:
    r, g, b = (int(hex6[i : i + 2], 16) for i in (1, 3, 5))
    y = round(0.299 * r + 0.587 * g + 0.114 * b)  # Rec. 601, as cvd_sim.py's greyscale
    return f"#{y:02X}{y:02X}{y:02X}"


def r2(x: float) -> float:
    return round(x, 2)


def contrast_matrix() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    extremes: dict[str, dict[str, str]] = {}
    singles: dict[str, float] = {}
    gated = failed = 0
    worst: dict[str, float] = {}
    worst_row = 99.0
    for theme in THEMES:
        tok = load_theme(theme)
        dark_c, light_c = (resolve(tok, n) for n in EXTREMES[theme])
        extremes[theme] = {"darkest": dark_c, "lightest": light_c}
        worst[theme] = 99.0  # the two-tone carriers' worst in this theme
        for element, a_name, b_name, kind, role in CARRIERS:
            a, b = resolve(tok, a_name), resolve(tok, b_name)
            hc_text = theme == "high-contrast" and role == "text"
            bar = None if role == "decorative" else BAR["hc-text" if hc_text else role]
            row: dict[str, Any] = {
                "theme": theme,
                "element": element,
                "a": a_name,
                "b": b_name,
            }
            if kind == "two-tone":
                low = r2(min(contrast(a, b), contrast(grey(a), grey(b))))
                over: dict[str, dict[str, float]] = {}
                for cname, c in (("darkest", dark_c), ("lightest", light_c)):
                    best = max(contrast(a, c), contrast(b, c))
                    gbest = max(contrast(grey(a), grey(c)), contrast(grey(b), grey(c)))
                    over[cname] = {"best": r2(best), "grey": r2(gbest)}
                    low = min(low, r2(best), r2(gbest))
                row.update(
                    a_vs_b=r2(contrast(a, b)),
                    a_vs_b_grey=r2(contrast(grey(a), grey(b))),
                )
                row.update(over=over, worst=low)
            else:
                ratio, gratio = r2(contrast(a, b)), r2(contrast(grey(a), grey(b)))
                low = ratio if bar is None else min(ratio, gratio)
                row.update(ratio=ratio, grey=gratio, worst=low)
            ok = bar is None or row["worst"] >= bar
            row.update(bar=bar, ok=ok)
            rows.append(row)
            if bar is not None:
                gated += 1
                failed += 0 if ok else 1
                worst_row = min(worst_row, row["worst"])
                if kind == "two-tone":
                    worst[theme] = min(worst[theme], row["worst"])
        ring, primary = (
            resolve(tok, "color.focus.ring"),
            resolve(tok, "color.text.primary"),
        )
        singles[f"ring_alone_{theme}"] = r2(contrast(ring, primary))
        link, raised = (
            resolve(tok, "color.text.link"),
            resolve(tok, "color.surface.raised"),
        )
        if link != "MISSING":
            singles[f"link_{theme}"] = r2(contrast(link, raised))
    return {
        "rows": rows,
        "extremes": extremes,
        "singles": singles,
        "gated": gated,
        "failed": failed,
        "worst": worst,
        "worst_row": worst_row,
    }


# ------------------------------------------------------------------ geometry --------------------
def dock_area(viewport: tuple[int, int]) -> tuple[int, int]:
    w, h = viewport
    return w - SHELL["nav"] - SHELL["right"], h - SHELL["top"] - SHELL["status"] - SHELL["tabstrip"]


def layout(node: Tree, x: int, y: int, w: int, h: int, depth: int, out: dict[str, Rect]) -> None:
    if "leaf" in node:
        out[node["leaf"]] = {"x": x, "y": y, "w": w, "h": h, "depth": depth}
        return
    n = len(node["children"])
    free = (w if node["type"] == "row" else h) - GUTTER * (n - 1)
    sizes = [round(free * s) for s in node["sizes"]]
    sizes[-1] = free - sum(sizes[:-1])
    pos = x if node["type"] == "row" else y
    for child, size in zip(node["children"], sizes, strict=True):
        if node["type"] == "row":
            layout(child, pos, y, size, h, depth + 1, out)
        else:
            layout(child, x, pos, w, size, depth + 1, out)
        pos += size + GUTTER


def count_tree(node: Tree) -> tuple[int, int, int]:
    """nodes, leaves, depth (the root counts as 1)."""
    if "leaf" in node:
        return 1, 1, 1
    nodes, leaves, depth = 1, 0, 0
    for c in node["children"]:
        n, lv, d = count_tree(c)
        nodes, leaves, depth = nodes + n, leaves + lv, max(depth, d)
    return nodes, leaves, depth + 1


def band(w: int, h: int) -> int:
    return int(min(BAND_MAX, max(BAND_MIN, round(BAND_PCT * min(w, h)))))


def zones(w: int, h: int) -> dict[str, Any]:
    b = band(w, h)
    cx, cy = w - 2 * b, h - 2 * b
    withdrawn: list[str] = []
    if cx < CENTRE_MIN:
        withdrawn += ["left", "right"]
        cx = w
    if cy < CENTRE_MIN:
        withdrawn += ["top", "bottom"]
        cy = h
    offered = [z for z in ("left", "right", "top", "bottom", "centre") if z not in withdrawn]
    return {
        "w": w,
        "h": h,
        "smaller": min(w, h),
        "pct": round(BAND_PCT * min(w, h)),
        "band": b,
        "centre_w": cx,
        "centre_h": cy,
        "offered": offered,
        "withdrawn": withdrawn,
    }


def min_height(kind: str, density: str = "compact") -> int:
    return ROW[density] * (CHROME_ROWS[kind] + BODY_ROWS_MIN)


def leaves_of(node: Tree) -> list[str]:
    if "leaf" in node:
        return [str(node["leaf"])]
    return [leaf for c in node["children"] for leaf in leaves_of(c)]


def remove_leaf(node: Tree, leaf: str) -> Tree | None:
    if "leaf" in node:
        return None if node["leaf"] == leaf else node
    kids: list[Tree] = []
    sizes: list[float] = []
    for c, s in zip(node["children"], node["sizes"], strict=True):
        r = remove_leaf(c, leaf)
        if r is not None:
            kids.append(r)
            sizes.append(s)
    if len(kids) == 1:
        return kids[0]  # a split left with one child collapses into it (E15-D02 section 4)
    total = sum(sizes)
    return {"type": node["type"], "sizes": [s / total for s in sizes], "children": kids}


def insert_at(node: Tree, target: str, zone: str, moving: str) -> Tree:
    """E15-D02 section 4: an edge zone splits the target (or inserts beside it in a
    same-direction parent, the target's share halved); the centre tabifies."""
    direction = {
        "left": "row",
        "right": "row",
        "top": "column",
        "bottom": "column",
    }.get(zone, "tabset")
    before = zone in ("left", "top")
    if "leaf" in node:
        if node["leaf"] != target:
            return node
        if direction == "tabset":
            return {"type": "tabset", "children": [node, {"leaf": moving}], "active": 1}
        pair = [{"leaf": moving}, node] if before else [node, {"leaf": moving}]
        return {"type": direction, "sizes": [0.5, 0.5], "children": pair}
    kids: list[Tree] = []
    sizes: list[float] = []
    for c, s in zip(node["children"], node["sizes"], strict=True):
        if c.get("leaf") == target and node["type"] == direction:
            half = s / 2
            pairs = (
                [({"leaf": moving}, half), (c, half)]
                if before
                else [(c, half), ({"leaf": moving}, half)]
            )
            for k, v in pairs:
                kids.append(k)
                sizes.append(v)
        else:
            kids.append(insert_at(c, target, zone, moving))
            sizes.append(s)
    return {"type": node["type"], "sizes": sizes, "children": kids}


def flatten_tabsets(node: Tree) -> Tree:
    if "leaf" in node:
        return node
    if node.get("type") == "tabset":
        return {"leaf": "tabset:" + ",".join(c["leaf"] for c in node["children"])}
    kids = [flatten_tabsets(c) for c in node["children"]]
    return {"type": node["type"], "sizes": node["sizes"], "children": kids}


def rects_of(tree: Tree, viewport: tuple[int, int]) -> dict[str, Rect]:
    w, h = dock_area(viewport)
    out: dict[str, Rect] = {}
    layout(flatten_tabsets(tree), 0, 0, w, h, 1, out)
    for name, box in list(out.items()):
        if name.startswith("tabset:"):
            del out[name]
            for leaf in name.split(":")[1].split(","):
                tabbed = dict(box, tab_group=True)
                tabbed["h"] -= ROW["compact"]  # the tab-group row above the visible panel
                out[leaf] = tabbed
    return out


def refusal(
    tree: Tree, viewport: tuple[int, int], moving: str, target: str
) -> dict[str, Any] | None:
    """D04-D-3's order: depth, a full tab group, then a minimum - the moving panel's first, then
    the target's, then the others in tree order; width before height within a panel."""
    nodes, leaves, depth = count_tree(tree)
    if depth > DEPTH_MAX:
        return {"key": "layout.limit.depth", "names": None}
    if nodes > NODES_MAX or leaves > LEAVES_MAX:
        return {"key": "layout.limit.panels", "names": None}
    rects = rects_of(tree, viewport)
    order = [moving, target] + [leaf for leaf in leaves_of(tree) if leaf not in (moving, target)]
    for kind in order:
        box = rects.get(kind)
        if box is None or kind not in MIN_WIDTH:
            continue
        if box["w"] < MIN_WIDTH[kind]:
            return {
                "key": "layout.limit.min_size",
                "names": kind,
                "axis": "narrower",
                "min": MIN_WIDTH[kind],
                "got": box["w"],
            }
        if box["h"] < min_height(kind):
            return {
                "key": "layout.limit.min_size",
                "names": kind,
                "axis": "shorter",
                "min": min_height(kind),
                "got": box["h"],
            }
    return None


def refusal_text(ref: dict[str, Any] | None, verb: str = "dock") -> str:
    if ref is None:
        return "valid"
    if ref["key"] == "layout.limit.min_size":
        who = LABEL[str(ref["names"])]
        return f"Can't {verb} here: {who} would be {ref['axis']} than its {ref['min']} px minimum."
    if ref["key"] == "layout.limit.depth":
        return (
            f"Can't {verb} here: the layout can't be split this deeply. "
            "Choose a neighbouring panel or a tab."
        )
    return f"Can't {verb} here: this tab group already holds {TABSET_MAX} panels."


def attempt(tree: Tree, viewport: tuple[int, int], moving: str, target: str, zone: str) -> Rect:
    without = remove_leaf(tree, moving)
    if without is None:
        raise ValueError(f"{moving} is the whole tree")
    after = insert_at(without, target, zone, moving)
    rects = rects_of(after, viewport)
    ref = refusal(after, viewport, moving, target)
    nodes, leaves, depth = count_tree(after)
    return {
        "target": target,
        "zone": zone,
        "nodes": nodes,
        "leaves": leaves,
        "depth": depth,
        "after": {k: {"w": v["w"], "h": v["h"]} for k, v in rects.items()},
        "refusal": ref,
        "text": refusal_text(ref),
    }


def deep_tree() -> Tree:
    """A tree already at the depth limit: four nested splits here + the fixture's root row."""
    node: Tree = {"leaf": "chart"}
    for i, k in enumerate(["tape", "dom", "positions", "tape"]):
        kids = [node, {"leaf": f"{k}{i}"}]
        node = {
            "type": "row" if i % 2 else "column",
            "sizes": [0.5, 0.5],
            "children": kids,
        }
    return node


def geometry() -> dict[str, Any]:
    dense1920 = rects_of(DENSE, VIEWPORTS["1920x1080"])
    dense1280 = rects_of(DENSE, VIEWPORTS["1280x800"])
    dense1024 = rects_of(DENSE, VIEWPORTS["1024x800"])
    small1280 = rects_of(SMALL, VIEWPORTS["1280x800"])
    z200w, z200h = dock_area(VIEWPORTS["zoom200"])
    sizes = {
        "chart-1920": (dense1920["chart"]["w"], dense1920["chart"]["h"]),
        "chart-1280": (dense1280["chart"]["w"], dense1280["chart"]["h"]),
        "minimum": (MIN_WIDTH["tape"], min_height("tape")),
        "small-tape-1280": (small1280["tape"]["w"], small1280["tape"]["h"]),
        "zoom200-collapse": (z200w, z200h - ROW["compact"]),
    }
    drops: dict[str, list[Rect]] = {}
    for vp in ("1280x800", "1920x1080"):
        drops[vp] = [
            attempt(DENSE, VIEWPORTS[vp], "positions", t, z)
            for t in ("chart", "dom", "tape")
            for z in ("left", "right", "top", "bottom", "centre")
        ]
    deep = deep_tree()
    # a third leaf keeps the root a row once Positions leaves it, so the deep branch keeps depth 6
    leaves = [deep, {"leaf": "positions"}, {"leaf": "dom9"}]
    deep_before: Tree = {"type": "row", "sizes": [0.5, 0.25, 0.25], "children": leaves}
    deep_case = attempt(deep_before, VIEWPORTS["1920x1080"], "positions", "chart", "left")
    ac6 = attempt(DENSE, VIEWPORTS["1920x1080"], "chart", "tape", "bottom")
    small_chooser = {
        f"{m}:{z}": attempt(SMALL, VIEWPORTS["1280x800"], m, "tape", z)
        for m in ("dom", "chart")
        for z in ("left", "right", "top", "bottom", "centre")
    }
    return {
        "zones": {k: zones(w, h) for k, (w, h) in sizes.items()},
        "dock_area": {k: dock_area(v) for k, v in VIEWPORTS.items()},
        "dense_1920": dense1920,
        "dense_1280": dense1280,
        "dense_1024": dense1024,
        "small_1280": small1280,
        "drops": drops,
        "depth_case": {
            "before": count_tree(deep_before)[2],
            "after": deep_case["depth"],
            "text": deep_case["text"],
        },
        "large_over_small": dict(
            ac6, tape_band=band(dense1920["tape"]["w"], dense1920["tape"]["h"])
        ),
        "small_chooser": small_chooser,
        "tabified_chart_1280": rects_of(
            insert_at(remove_leaf(DENSE, "positions") or DENSE, "chart", "centre", "positions"),
            VIEWPORTS["1280x800"],
        )["chart"],
    }


# ------------------------------------------------------------------ keymap ----------------------
def keymap_bindings() -> tuple[set[str], int, int]:
    data = json.loads(KEYMAP.read_text(encoding="utf-8"))
    cmds = data["commands"] if isinstance(data, dict) and "commands" in data else data
    out: set[str] = set()
    for c in cmds:
        b = c.get("defaultBinding")
        if isinstance(b, str):
            out.add(b)
        elif isinstance(b, list):
            out.update(x for x in b if isinstance(x, str))
    reserved = json.loads(RESERVED.read_text(encoding="utf-8"))
    return out, len(cmds), len(reserved)


# ------------------------------------------------------------------ spec structure --------------
def section(text: str, start: str, end: str) -> str:
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(end, i + len(start))
    return text[i : j if j > 0 else len(text)]


def count(pattern: str, body: str) -> int:
    return len(re.findall(pattern, body, re.MULTILINE))


def table_after(body: str, header_first_cell: str) -> list[list[str]]:
    """The rows (cells) of the table whose header's first cell is ``header_first_cell``."""
    out: list[list[str]] = []
    inside = False
    for row in body.split("\n"):
        if row.startswith(f"| {header_first_cell} "):
            inside = True
            continue
        if inside:
            if not row.startswith("|"):
                break
            if not row.startswith("| -"):
                out.append([c.strip() for c in row.strip().strip("|").split("|")])
    return out


PARITY_OPS = r"(?:Move|Split|Tabify|Resize|Pop out|Return|Close|Maximise|Minimise|Equal|Undo)"


def structure(spec: str, handoff: str) -> dict[str, Any]:
    s0 = section(spec, "## 0. ", "## 1. ")
    keys = table_after(section(spec, "## 10. ", "## 11. "), "Function")
    existing = [r for r in keys if len(r) > 2 and "**existing**" in r[2]]
    # the ids each existing row binds (a `shadows` note names another row's id, not this row's)
    bound = [re.sub(r"shadows `[^`]+`", "", r[2]) for r in existing]
    ids_existing = {i for b in bound for i in re.findall(r"`([a-z]+\.[a-z_]+)`", b)}
    frames_all = set(re.findall(r"`SCR-021/([a-z0-9-]+)`", spec))
    frames_s0 = set(re.findall(r"`SCR-021/([a-z0-9-]+)`", s0))
    rest = spec.replace(s0, "")
    frames_rest = set(re.findall(r"`SCR-021/([a-z0-9-]+)`", rest))
    k_ids = re.findall(r"^\| (K[1-6]) ", section(spec, "## 5. ", "## 6. "), re.MULTILINE)
    return {
        "boards": count(r"^\| \d\d +\| `", s0),
        "light_boards": count(r"^\| \d\d +\| `[a-z0-9-]*light", s0),
        "ac_rows": count(
            r"^\| (?:Sc\. \d|`14`|Test plan|Security|A11y|Performance|Observability|DoD)",
            section(spec, "## Acceptance-criteria trace", "## 0. "),
        ),
        "decisions": count(r"^\| D04-D-\d+ ", section(spec, "## 2. ", "## 3. ")),
        "p_frames": count(r"^\| P\d+ ", section(spec, "## 4. ", "## 5. ")),
        "k_frames": len(set(k_ids)),
        "k_frame_rows": len(k_ids),
        "parity_rows": count(rf"^\| {PARITY_OPS}", section(spec, "## 5. ", "## 6. ")),
        "splitter_states": count(
            r"^\| (?:rest|hover|active-drag|focused|at-minimum) ",
            section(spec, "## 6. ", "## 7. "),
        ),
        "key_rows": len(keys),
        "key_rows_existing": len(existing),
        "key_rows_other": len(keys) - len(existing),
        "key_ids_existing": len(ids_existing),
        "announcements": count(r"^\| AN-\d+ ", section(spec, "## 10. ", "## 11. ")),
        "copy_rows": count(r"^\| `[a-z._]+` ", section(spec, "## 13. ", "## 14. ")),
        "a_rows": count(r"^\| D04-A-\d+ ", section(spec, "## 14. ", "## 15. ")),
        "c_rows": count(r"^\| D04-C-\d+ ", section(spec, "## 18. ", "## 19. ")),
        "g_rows": count(r"^\| D04-G-\d+ ", section(spec, "## 18. ", "## 19. ")),
        "q_rows": count(r"^\| D04-Q-\d+ ", section(spec, "## 18. ", "## 19. ")),
        "handoff_blocks": count(r"^## Handoff checklist", handoff),
        "frames_named": len(frames_all),
        "frames_board_only": len(frames_s0 - frames_rest),
    }


# ------------------------------------------------------------------ derived ---------------------
def derived(spec: str, handoff: str) -> dict[str, Any]:
    g = geometry()
    cm = contrast_matrix()
    bindings, n_commands, n_reserved = keymap_bindings()
    dark = load_theme("dark")
    missing = [n for n in BOUND if resolve(dark, n) == "MISSING"]
    requested_absent = [n for n in REQUESTED if resolve(dark, n) == "MISSING"]
    st = structure(spec, handoff)
    z = g["zones"]
    d1280, d1920 = g["drops"]["1280x800"], g["drops"]["1920x1080"]

    def drop(table: list[Rect], target: str, zone: str) -> Rect:
        return next(a for a in table if a["target"] == target and a["zone"] == zone)

    ac6, sc = g["large_over_small"], g["small_chooser"]
    p9, east, west = (
        drop(d1280, "chart", "bottom"),
        drop(d1920, "chart", "right"),
        drop(d1920, "chart", "left"),
    )
    chart_side, dom_side = drop(d1280, "chart", "left"), drop(d1280, "dom", "left")
    worst = cm["worst"]
    # fmt: off
    m: dict[str, Any] = {
        "band_pct": int(BAND_PCT * 100), "band_min": BAND_MIN, "band_max": BAND_MAX,
        "centre_min": CENTRE_MIN, "gutter": GUTTER, "hit_band": HIT_BAND,
        "zone_outline": ZONE_OUTLINE, "ghost_outline": GHOST_OUTLINE, "halo": HALO,
        "hatch_pitch": HATCH_PITCH, "step_fine": STEP_FINE, "step_coarse": STEP_COARSE,
        "row_compact": ROW["compact"], "row_comfortable": ROW["comfortable"],
        "body_rows_min": BODY_ROWS_MIN, "depth_max": DEPTH_MAX, "nodes_max": NODES_MAX,
        "leaves_max": LEAVES_MAX, "tabset_max": TABSET_MAX, "min_w_chart": MIN_WIDTH["chart"],
        "min_w_dom": MIN_WIDTH["dom"], "min_w_tape": MIN_WIDTH["tape"],
        "min_w_positions": MIN_WIDTH["positions"], "min_h_chart": min_height("chart"),
        "min_h_dom": min_height("dom"), "min_h_tape": min_height("tape"),
        "min_h_positions": min_height("positions"),
        "min_h_chart_comfortable": min_height("chart", "comfortable"),
        "min_h_tape_comfortable": min_height("tape", "comfortable"),
        "band_chart_1920": z["chart-1920"]["band"], "band_chart_1280": z["chart-1280"]["band"],
        "band_minimum": z["minimum"]["band"], "band_zoom200": z["zoom200-collapse"]["band"],
        "centre_chart_1920_w": z["chart-1920"]["centre_w"],
        "centre_chart_1920_h": z["chart-1920"]["centre_h"],
        "centre_chart_1280_w": z["chart-1280"]["centre_w"],
        "centre_chart_1280_h": z["chart-1280"]["centre_h"],
        "centre_minimum_w": z["minimum"]["centre_w"], "centre_minimum_h": z["minimum"]["centre_h"],
        "withdrawn_minimum": len(z["minimum"]["withdrawn"]),
        "offered_minimum": len(z["minimum"]["offered"]), "small_tape_w": z["small-tape-1280"]["w"],
        "small_tape_h": z["small-tape-1280"]["h"], "chart_1920_w": z["chart-1920"]["w"],
        "chart_1920_h": z["chart-1920"]["h"], "chart_1280_w": z["chart-1280"]["w"],
        "chart_1280_h": z["chart-1280"]["h"], "dom_1280_w": g["dense_1280"]["dom"]["w"],
        "tape_1280_w": g["dense_1280"]["tape"]["w"],
        "positions_1280_h": g["dense_1280"]["positions"]["h"],
        "dom_1920_w": g["dense_1920"]["dom"]["w"], "tape_1920_w": g["dense_1920"]["tape"]["w"],
        "positions_1920_h": g["dense_1920"]["positions"]["h"],
        "dom_1024_w": g["dense_1024"]["dom"]["w"], "dock_1280_w": g["dock_area"]["1280x800"][0],
        "dock_1280_h": g["dock_area"]["1280x800"][1], "dock_1920_w": g["dock_area"]["1920x1080"][0],
        "dock_1920_h": g["dock_area"]["1920x1080"][1],
        "dock_zoom200_w": g["dock_area"]["zoom200"][0],
        "dock_zoom200_h": g["dock_area"]["zoom200"][1], "bar_h_compact": SHELL["tabstrip"],
        "bar_h_two_line": SHELL["tabstrip"] + ROW["compact"],
        "bar_h_comfortable": SHELL["tabstrip"] + 8,
        "bar_h_two_line_comfortable": SHELL["tabstrip"] + 8 + ROW["comfortable"],
        "ghost_card_w": GHOST_CARD[0], "ghost_card_h": GHOST_CARD[1], "label_offset": LABEL_OFFSET,
        "label_max_w": LABEL_MAX_W, "tray_compact": ROW["compact"],
        "tray_comfortable": ROW["comfortable"],
        "valid_drops_1280": sum(a["refusal"] is None for a in d1280),
        "valid_drops_1920": sum(a["refusal"] is None for a in d1920),
        "attempts_per_viewport": len(d1280), "depth_case_before": g["depth_case"]["before"],
        "depth_case_after": g["depth_case"]["after"], "ac6_ghost_w": ac6["after"]["chart"]["w"],
        "ac6_ghost_h": ac6["after"]["chart"]["h"], "ac6_tape_w": ac6["after"]["tape"]["w"],
        "ac6_tape_h": ac6["after"]["tape"]["h"], "ac6_dom_w": ac6["after"]["dom"]["w"],
        "ac6_valid": ac6["refusal"] is None, "tape_band_1920": ac6["tape_band"],
        "small_dom_below_h": sc["dom:bottom"]["after"]["dom"]["h"],
        "small_dom_below_valid": sc["dom:bottom"]["refusal"] is None,
        "small_dom_side_w": sc["dom:left"]["after"]["dom"]["w"],
        "small_dom_tab_h": sc["dom:centre"]["after"]["dom"]["h"],
        "small_chart_half_h": sc["chart:bottom"]["after"]["chart"]["h"],
        "small_chart_below_valid": sc["chart:bottom"]["refusal"] is None,
        "p9_chart_h": p9["after"]["chart"]["h"], "p9_positions_h": p9["after"]["positions"]["h"],
        "p9_dom_h": p9["after"]["dom"]["h"], "p9_valid": p9["refusal"] is None,
        "east_chart_w": east["after"]["chart"]["w"],
        "east_positions_w": east["after"]["positions"]["w"],
        "east_dom_h": east["after"]["dom"]["h"], "east_valid": east["refusal"] is None,
        "west_dom_w": west["after"]["dom"]["w"], "west_tape_w": west["after"]["tape"]["w"],
        "side_chart_1280_w": chart_side["after"]["chart"]["w"],
        "side_dom_1280_w": dom_side["after"]["dom"]["w"],
        "tabified_chart_1280_h": g["tabified_chart_1280"]["h"], "contrast_gated": cm["gated"],
        "contrast_fail": cm["failed"], "contrast_rows": len(cm["rows"]),
        "worst_dark": f"{worst['dark']:.2f}", "worst_light": f"{worst['light']:.2f}",
        "worst_hc": f"{worst['high-contrast']:.2f}", "worst_carrier": f"{min(worst.values()):.2f}",
        "worst_gated": f"{cm['worst_row']:.2f}", "both_axes_withdraw": 2 * BAND_MIN + CENTRE_MIN,
        "ring_alone_dark": f"{cm['singles']['ring_alone_dark']:.2f}",
        "ring_alone_light": f"{cm['singles']['ring_alone_light']:.2f}",
        "link_hc": f"{cm['singles']['link_high-contrast']:.2f}", "tokens_bound": len(BOUND),
        "tokens_missing": len(missing), "tokens_requested": len(requested_absent),
        "tokens_primitives": len(token_file(PRIM)), "tokens_dark": len(token_file(DARK)),
        "tokens_light": len(token_file(LIGHT)), "tokens_hc": len(token_file(HC)),
        "keymap_commands": n_commands, "keymap_bindings": len(bindings),
        "reserved_keys": n_reserved,
    }
    # fmt: on
    m.update(st)
    return {
        "markers": m,
        "geometry": g,
        "contrast": cm,
        "tokens": {n: resolve(dark, n) for n in BOUND + REQUESTED},
        "bindings": sorted(bindings),
        "counts": st,
    }


# ------------------------------------------------------------------ check: markers and numbers ---
MARKER = re.compile(r"<!--\s*audit:([A-Za-z0-9_.-]+)=([^\s>]+)\s*-->")
WORDS = {
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "fifteen": 15,
}

# (label, pattern with one group per marker, markers): every match must equal the derived value and
# the pattern must match at least once. Word numbers are read through WORDS.
CONTEXTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("named frames", r"(\d+) named `SCR-021/<state>` frames", ("frames_named",)),
    ("board-only frames", r"except the (\w+) board-only frames", ("frames_board_only",)),
    ("gated rows", r"(\d+) gated rows", ("contrast_gated",)),
    ("gated FAIL", r"gated rows, (\d+) FAIL", ("contrast_fail",)),
    (
        "worst per theme",
        r"worst (\d+\.\d\d):1 in light, (\d+\.\d\d):1 in dark, (\d+\.\d\d):1 in high contrast",
        ("worst_light", "worst_dark", "worst_hc"),
    ),
    (
        "worst carrier",
        r"\*\*Worst two-tone carrier:\*\* (\d+\.\d\d)|worst carrier (\d+\.\d\d)",
        ("worst_carrier", "worst_carrier"),
    ),
    ("worst gated row", r"\*\*worst gated row\*\* (\d+\.\d\d)", ("worst_gated",)),
    (
        "ring alone",
        r"measures (\d+\.\d\d):1 there in dark and (\d+\.\d\d):1 in light",
        ("ring_alone_dark", "ring_alone_light"),
    ),
    ("link colour", r"`color\.text\.link` measures (\d+\.\d\d)", ("link_hc",)),
    ("band 1920", r"810\u00d7623(?:,? band | → )(\d+)", ("band_chart_1920",)),
    ("band 1280", r"522\u00d7432(?:,? band | → )(\d+)", ("band_chart_1280",)),
    ("band minimum", r"232\u00d7120(?:: band | → )(\d+)", ("band_minimum",)),
    ("band zoom", r"528\u00d7216(?:,? band | collapse → )(\d+)", ("band_zoom200",)),
    (
        "Tape band 1920",
        r"396 wide, band (\d+)|Tape's bottom zone, band (\d+)",
        ("tape_band_1920", "tape_band_1920"),
    ),
    (
        "AC6 ghost",
        r"(?:ghost|Tape's) (\d+)\u00d7(\d+)(?= lower half| \"Below Tape\"| below the Tape)",
        ("ac6_ghost_w", "ac6_ghost_h"),
    ),
    ("AC6 Tape", r"under the Tape at (\d+)\u00d7(\d+)", ("ac6_tape_w", "ac6_tape_h")),
    ("AC6 DOM", r"DOM grown to (\d+) wide|\(DOM (\d+), Tape", ("ac6_dom_w", "ac6_dom_w")),
    ("AC2 east", r"Chart (\d+) → Positions (\d+) wide", ("east_chart_w", "east_positions_w")),
    (
        "P2 neighbours",
        r"the DOM \((\d+)\) and the Tape \((\d+)\) grown",
        ("west_dom_w", "west_tape_w"),
    ),
    ("side split", r"halves (\d+) into (\d+)", ("chart_1280_w", "side_chart_1280_w")),
    ("side split DOM", r"of the DOM into (\d+)", ("side_dom_1280_w",)),
    ("conflict C-1", r"the tool: (\d+) → (\d+) against", ("chart_1280_w", "side_chart_1280_w")),
    (
        "valid 1280",
        r"(\w+) of 15 drops valid|\*\*1280\u00d7800\*\* (\w+) of fifteen",
        ("valid_drops_1280", "valid_drops_1280"),
    ),
    (
        "valid 1920",
        r"(\w+) of 15 at 1920\u00d71080|where (\w+) of fifteen",
        ("valid_drops_1920", "valid_drops_1920"),
    ),
    (
        "key rows",
        r"Keys: (\d+) rows, (\d+) existing \(naming (\d+) ids\)",
        ("key_rows", "key_rows_existing", "key_ids_existing"),
    ),
    ("key rows rest", r"the other (\d+) PROPOSED, RULED or CARRIED", ("key_rows_other",)),
    ("operations", r"([Ee]leven|\d+) operations", ("parity_rows",)),
    ("announcements", r"; (\w+) announcements;", ("announcements",)),
    (
        "tokens bound",
        r"resolves (\d+) bound tokens, (\d+) missing",
        ("tokens_bound", "tokens_missing"),
    ),
    ("tokens bound list", r"\*\*Tokens bound\*\* \((\d+), all resolved\)", ("tokens_bound",)),
    ("tokens requested", r"requested for E15-D13 \((\d+)\)", ("tokens_requested",)),
    (
        "token files",
        r"(\d+) primitives · (\d+) dark · (\d+) light · (\d+) high-contrast",
        ("tokens_primitives", "tokens_dark", "tokens_light", "tokens_hc"),
    ),
    (
        "keymap commands",
        r"`keymap\.json` \((\d+) commands\)|\| (\d+) commands; ",
        ("keymap_commands", "keymap_commands"),
    ),
    ("reserved keys", r"`reserved-keys\.json` (\d+) entries", ("reserved_keys",)),
    ("depth case", r"refuses one more split \(depth (\d+)\)", ("depth_case_after",)),
    ("both axes", r"a panel under (\d+) px on both sides", ("both_axes_withdraw",)),
    ("compact DOM", r"the DOM (\d+) wide, under its", ("dom_1024_w",)),
    (
        "tabified chart",
        r"a tabified Chart at 1280\u00d7800 is (\d+)\u00d7(\d+)",
        ("chart_1280_w", "tabified_chart_1280_h"),
    ),
    # m-7: the whole numbers outside the first 38 contexts (the §3.1 table is re-derived per row)
    (
        "§20 bands",
        r"810\u00d7623 \(band (\d+)\), 522\u00d7432 \((\d+)\) and 232\u00d7120 \((\d+);",
        ("band_chart_1920", "band_chart_1280", "band_minimum"),
    ),
    ("P2 band", r"left band \((\d+) px\)", ("band_chart_1920",)),
    (
        "§3.2 clamp",
        r"clamped to (\d+); two (\d+) px bands leave (\d+) px across",
        ("band_minimum", "band_minimum", "centre_minimum_w"),
    ),
    (
        "§3.2 sibling drops",
        r"whole (\d+) px column, so .{0,40} are valid (\d+)\u00d7(\d+) drops",
        ("dock_1280_h", "small_tape_w", "small_dom_below_h"),
    ),
    (
        "mover's side",
        (
            r"leaves both (\d+) wide, under the DOM's (\d+) and the Tape's (\d+)"
            r"|at (\d+) px; on either side the Tape's (\d+) breaks"
        ),
        ("small_dom_side_w", "min_w_dom", "min_w_tape", "small_dom_side_w", "min_w_tape"),
    ),
    (
        "§3.2 Chart over small",
        (
            r"leaves the Tape at (\d+) px, so its top and bottom halves are (\d+) px .{0,60}?the "
            r"Chart's (\d+) px height minimum .{0,80}?break the Tape's (\d+)\."
        ),
        ("small_tape_h", "small_chart_half_h", "min_h_chart", "min_h_tape"),
    ),
    (
        "D04-D-5 heights",
        (
            r"at compact (\d+) px for the DOM, Tape and Positions and (\d+) for a chart "
            r"\(comfortable (\d+) / (\d+)\)"
            r"|height under (\d+) px \((\d+) for a chart\) at compact \(D04-D-5; "
            r"comfortable (\d+) / (\d+)\)"
        ),
        ("min_h_dom", "min_h_chart", "min_h_tape_comfortable", "min_h_chart_comfortable") * 2,
    ),
    (
        "D04-D-5 widths",
        (
            r"\(chart (\d+), DOM (\d+), tape (\d+), Positions (\d+)\)|width under (\d+) \(chart\), "
            r"(\d+) \(DOM\), (\d+) \(tape\) or (\d+) px \(Positions"
        ),
        ("min_w_chart", "min_w_dom", "min_w_tape", "min_w_positions") * 2,
    ),
    (
        "board 08 minimum",
        r"under its (\d+) px width or (\d+) px height minimum",
        ("min_w_tape", "min_h_tape"),
    ),
)
BAND_TABLE = ("Smaller side", "25 %", "Band", "Centre", "Offered", "Withdrawn")
REFUSAL_SENTENCE = re.compile(r"Can't d(?:rop|ock) here: [^\"”]*(?=[\"”])")
DIM = re.compile(r"(?<![\d.])(\d{2,4})\u00d7(\d{1,4})(?![\d])")
RATIO = re.compile(r"(?<![\d.§])(\d{1,2}\.\d\d)(?![\d.])")


def number_of(raw: str) -> str:
    return str(WORDS.get(raw.lower(), raw))


def allowed_dims(d: dict[str, Any]) -> set[tuple[int, int]]:
    g = d["geometry"]
    out: set[tuple[int, int]] = set(VIEWPORTS.values())
    out |= {(int(v[0]), int(v[1])) for v in g["dock_area"].values()}
    out |= {GHOST_CARD, STOP_MARK, TARGET_MIN, *GRIP.values()}
    for z in g["zones"].values():
        out |= {(z["w"], z["h"]), (z["centre_w"], z["centre_h"])}
    boxes: list[Rect] = []
    for key in ("dense_1920", "dense_1280", "dense_1024", "small_1280"):
        boxes += list(g[key].values())
    attempts = g["drops"]["1280x800"] + g["drops"]["1920x1080"] + list(g["small_chooser"].values())
    attempts.append(g["large_over_small"])
    for a in attempts:
        boxes += list(a["after"].values())
    boxes.append(g["tabified_chart_1280"])
    out |= {(b["w"], b["h"]) for b in boxes}
    return out


def allowed_ratios(d: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for row in d["contrast"]["rows"]:
        for k in ("a_vs_b", "a_vs_b_grey", "ratio", "grey", "worst"):
            if k in row:
                out.add(f"{row[k]:.2f}")
        for v in row.get("over", {}).values():
            out |= {f"{v['best']:.2f}", f"{v['grey']:.2f}"}
    out |= {f"{v:.2f}" for v in d["contrast"]["singles"].values()}
    for tree in (DENSE, SMALL):
        stack = [tree]
        while stack:
            node = stack.pop()
            out |= {f"{s:.2f}" for s in node.get("sizes", [])}
            stack += node.get("children", [])
    return out


def refusal_texts(d: dict[str, Any]) -> set[str]:
    g = d["geometry"]
    texts = {g["depth_case"]["text"], refusal_text({"key": "tab"})}
    for a in g["drops"]["1280x800"] + g["drops"]["1920x1080"] + list(g["small_chooser"].values()):
        texts.add(a["text"])
    return texts | {t.replace("Can't dock", "Can't drop") for t in texts}


def check_markers(text: str, m: dict[str, Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for hit in MARKER.finditer(text):
        name, value = hit.group(1), hit.group(2)
        if name in seen:
            out.append(f"FAIL marker audit:{name} appears twice")
        seen.add(name)
        if name not in m:
            out.append(f"FAIL unknown marker audit:{name}")
        elif str(m[name]).lower() != value.lower():
            out.append(f"FAIL marker audit:{name}={value} but derived {m[name]}")
    for name in sorted(set(m) - seen):
        out.append(f"FAIL marker audit:{name} missing from the spec (derived {m[name]})")
    return out


def alternatives(pattern: str) -> list[str]:
    """m-12: the top-level alternatives of a context's pattern, one per site."""
    out: list[str] = []
    depth, start, i, in_class = 0, 0, 0, False
    while i < len(pattern):
        c = pattern[i]
        if c == "\\":
            i += 2
            continue
        if in_class:
            in_class = c != "]"
        elif c == "[":
            in_class = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == "|" and depth == 0:
            out.append(pattern[start:i])
            start = i + 1
        i += 1
    out.append(pattern[start:])
    return out


def line_of(text: str, pos: int) -> str:
    end = text.find("\n", pos)
    return text[text.rfind("\n", 0, pos) + 1 : end if end >= 0 else len(text)]


def refusal_sites(d: dict[str, Any]) -> tuple[tuple[str, str, str], ...]:
    """m-13: (label, pattern with the sentence as group 1, the tool's sentence) per refusal site."""
    side = d["geometry"]["small_chooser"]["dom:left"]["text"].replace("Can't dock", "Can't drop")
    drop = frame_polite(d)["move-invalid"]
    return (
        ("§3.2 DOM beside the small Tape", r'are refused \("([^"]+)" at \d+ px', side),
        ("K4 bar second line", r'its second line reads "([^"]+)"', drop),
        ("move-target-minimum bar second line", r'the bar\'s second line "([^"]+)" as K4', side),
        ("AN-4", r'\| AN-4 [^"]*"([^"]+)"', drop),
    )


def check_numbers(spec: str, handoff: str, d: dict[str, Any]) -> list[str]:
    out: list[str] = []
    m = d["markers"]
    prose = "\n".join(r for r in spec.split("\n") if not r.startswith("<!--"))
    covered: set[tuple[int, int]] = set()
    for label, pattern, names in CONTEXTS:
        sites = alternatives(pattern)
        first = 0
        for k, site in enumerate(sites, start=1):
            group_names = names[first : first + re.compile(site).groups]
            first += len(group_names)
            hits = list(re.finditer(site, prose))
            if not hits:
                where = f" (site {k} of {len(sites)})" if len(sites) > 1 else ""
                out.append(f"FAIL number context vanished: {label}{where}")
            for hit in hits:
                for i, name in enumerate(group_names, start=1):
                    if hit.group(i) is None:
                        continue
                    covered.add(hit.span(i))
                    if number_of(hit.group(i)) != str(m[name]):
                        out.append(
                            f"FAIL {label}: the spec says {hit.group(i)}, the tool {m[name]}"
                        )
    dims = allowed_dims(d)
    ratios = allowed_ratios(d)
    matrix = {"| " + "|".join(r) for r in contrast_table(spec)}
    for label, text in (("spec", prose), ("handoff", handoff)):
        for hit in DIM.finditer(text):
            if label == "spec" and hit.span(1) in covered:
                continue
            if (int(hit.group(1)), int(hit.group(2))) not in dims:
                out.append(f"FAIL {label}: {hit.group(0)} is not a size the tool derives")
        for hit in RATIO.finditer(text):
            if label == "spec" and hit.span(1) in covered:
                continue
            if label == "spec" and norm_row(line_of(text, hit.start())) in matrix:
                continue  # the §12 matrix is checked cell by cell (check_contrast_table)
            if hit.group(1) not in ratios:
                out.append(f"FAIL {label}: ratio {hit.group(1)} is not a ratio the tool derives")
    out += check_band_table(spec)
    out += check_contrast_table(spec, d)
    texts = refusal_texts(d)
    for hit in REFUSAL_SENTENCE.finditer(prose):
        if "…" not in hit.group(0) and "{" not in hit.group(0) and hit.group(0) not in texts:
            out.append(f"FAIL refusal sentence not the tool's: {hit.group(0)!r}")
    for label, pattern, want in refusal_sites(d):
        hits = list(re.finditer(pattern, prose))
        if not hits:
            out.append(f"FAIL number context vanished: the {label} refusal")
        for hit in hits:
            # a sentence that is no tool sentence already failed above; this catches a swap
            if hit.group(1) in texts and hit.group(1) != want:
                out.append(f"FAIL {label}: the spec says {hit.group(1)!r}, the tool {want!r}")
    return out


def norm_row(row: str) -> str:
    return "| " + "|".join(c.strip() for c in row.strip().strip("|").split("|"))


def contrast_table(spec: str) -> list[list[str]]:
    return table_after(section(spec, "## 12. ", "## 13. "), "Carrier (tone A · tone B)")


def check_contrast_table(spec: str, d: dict[str, Any]) -> list[str]:
    """m-13: each §12 cell equals its own carrier's and theme's figures, so a swap fails."""
    out: list[str] = []
    rows = contrast_table(spec)
    tool = d["contrast"]["rows"]
    if len(rows) != len(CARRIERS):
        out.append(f"FAIL §12 matrix has {len(rows)} rows, the tool {len(CARRIERS)}")
        return out
    for i, row in enumerate(rows):
        for j, theme in enumerate(THEMES, start=1):
            r = next(t for t in tool if t["theme"] == theme and t["element"] == CARRIERS[i][0])
            if "over" in r:
                o = r["over"]
                want = (
                    f"{r['a_vs_b']:.2f} ({r['a_vs_b_grey']:.2f}) · "
                    f"{o['darkest']['best']:.2f} ({o['darkest']['grey']:.2f}) · "
                    f"{o['lightest']['best']:.2f} ({o['lightest']['grey']:.2f})"
                )
            else:
                want = f"{r['ratio']:.2f} ({r['grey']:.2f})"
            have = row[j] if j < len(row) else ""
            if have != want:
                out.append(f"FAIL §12 row {i + 1} {theme}: the spec says {have}, the tool {want}")
    return out


def check_band_table(spec: str) -> list[str]:
    """m-7: each §3.1 row re-derived from its Size (smaller side, 25 %, band, centre, zones)."""
    out: list[str] = []
    rows = table_after(section(spec, "### 3.1 ", "### 3.2 "), "Panel (fixture)")
    if not rows:
        out.append("FAIL number context vanished: the §3.1 band table")
    for row in rows:
        size = DIM.fullmatch(row[1]) if len(row) > 7 else None
        if size is None:
            out.append(f"FAIL §3.1 row `{row[0]}` has no W\u00d7H size")
            continue
        z = zones(int(size.group(1)), int(size.group(2)))
        want = (
            str(z["smaller"]),
            str(z["pct"]),
            str(z["band"]),
            f"{z['centre_w']}\u00d7{z['centre_h']}",
            ", ".join(z["offered"]) if z["withdrawn"] else "all five",
            ", ".join(z["withdrawn"]) or "—",
        )
        said = [re.sub(r" \(\d\)$", "", c) for c in row[2:8]]
        said[2] = re.sub(r"^\*\*(\d+)\*\*.*", r"\1", said[2])
        for label, have, need in zip(BAND_TABLE, said, want, strict=True):
            if have != need:
                out.append(
                    f"FAIL §3.1 row `{row[0]}` {label}: the spec says {have}, the tool {need}"
                )
    return out


# ------------------------------------------------------------------ check: frames (A1-A3) -------
LIT = "4 px `color.focus.ring` outline with its halo"
GHOST = (
    "`color.surface.overlay` at `opacity.muted`",
    "2 px `color.text.primary` outline",
)
HATCH = "2 px `color.text.primary` lines"
MARK = "2 px `color.focus.ring` with the halo"
CARRIER_NEEDLES: dict[str, tuple[str, ...]] = {
    "the lit zone": (LIT,),
    "the ghost": GHOST,
    "the hatch": (HATCH,),
    "the stage-one target mark": (MARK,),
}
# frame id -> the carriers its row must draw (A2) and the Esc exit it must name (A3).
# fmt: off
FRAME_CARRIERS: dict[str, tuple[str, ...]] = {
    "zones-1920": ("the lit zone",), "zones-1280": ("the lit zone",),
    "zones-minimum": ("the lit zone",), "zones-zoom200": ("the lit zone",),
    "drag-start": ("the ghost",), "zone-left": ("the lit zone", "the ghost"),
    "zone-right": ("the lit zone", "the ghost"), "zone-top": ("the lit zone", "the ghost"),
    "zone-bottom": ("the lit zone", "the ghost"), "zone-centre": ("the lit zone", "the ghost"),
    "zone-large-over-small": ("the lit zone", "the ghost"), "invalid-min-size": ("the hatch",),
    "invalid-depth": ("the hatch", "the lit zone"),
    "invalid-tab-group": ("the hatch", "the lit zone"), "esc": (), "dropped": (), "undone": (),
    "move-menu": (), "move-mode": ("the stage-one target mark",),
    "move-step-panel": ("the stage-one target mark",),
    "move-step-side": ("the lit zone", "the ghost"), "move-invalid": ("the hatch",),
    "move-dropped": (), "move-esc": (), "move-no-panel": ("the stage-one target mark",),
    "move-target-minimum": ("the lit zone", "the ghost", "the hatch"), "move-to-submenu": (),
    "splitter-rest": (), "splitter-hover": (), "splitter-drag": (), "splitter-focused": (),
    "splitter-minimum": (),
}
# fmt: on
POINTER_ESC = "`Esc` cancels the drag"
BAR_ESC = "Esc: cancel"
# fmt: off
FRAME_ESC: dict[str, str] = {
    "drag-start": POINTER_ESC, "zone-left": POINTER_ESC, "zone-right": POINTER_ESC,
    "zone-top": POINTER_ESC, "zone-bottom": POINTER_ESC, "zone-centre": POINTER_ESC,
    "zone-large-over-small": POINTER_ESC, "invalid-min-size": POINTER_ESC,
    "invalid-depth": POINTER_ESC, "invalid-tab-group": POINTER_ESC, "esc": "`Esc` during the drag",
    "move-mode": BAR_ESC, "move-step-panel": BAR_ESC, "move-step-side": BAR_ESC,
    "move-invalid": BAR_ESC, "move-no-panel": BAR_ESC, "move-target-minimum": BAR_ESC,
    "move-esc": "`Esc` at any step",
}
# fmt: on
T2_FRAMES: dict[str, str] = {
    "move-to-submenu": "`layout.limit.",
    "dirty-save-view-as": "`rbac.view_as`",
}
T2_NEEDLES = (
    ("the CMP-019 lock", "CMP-019 lock"),
    ("`aria-disabled`", "aria-disabled"),
)
T2_RULE = (
    '`aria-disabled="true"`, never the `disabled` attribute',
    "a CMP-019 `lock` glyph",
    "CMP-079 RbacGate",
    "(E09-D09 §9.3)",
)
LOCKISH = re.compile(r"CMP-019|lock glyph|`lock`|aria-disabled|CMP-079")
FRAME_ID = re.compile(r"`SCR-021/([a-z0-9-]+)`")
SEGMENT_END = re.compile(r"\.(?= +[A-Z*`\"“(])")  # m-11: the end of a sentence
CTRL_Z = "`Ctrl+Z`"  # n-7: only ever `chart.undo` in a clause that names it (D04-D-12)
# A3: a clause naming `Esc` with a gating word must say "never" (P8 "`Esc` is gated" is a FAIL).
ESC_GATED = re.compile(r"\bEsc\b[^;|.]*\b(?:gated|locked|disabled|blocked|T2)\b")
CHORD = re.compile(r"`((?:(?:Ctrl|Alt|Shift|Meta)\+)+[^`\s]+|F\d{1,2})`")


def frame_polite(d: dict[str, Any]) -> dict[str, str]:
    """frame id -> its one polite string (E15-D02 section 8's grammar; refusals from the tool)."""
    g = d["geometry"]
    drop = next(
        a for a in g["drops"]["1280x800"] if a["target"] == "tape" and a["zone"] == "bottom"
    )
    return {
        "move-menu": "Panel options.",
        "move-mode": "Move mode. Positions. Choose a panel.",
        "move-step-panel": "Chart, BTCUSDT 1m.",
        "move-step-side": "Below Chart.",
        "move-invalid": drop["text"].replace("Can't dock", "Can't drop"),
        "move-dropped": "Positions moved below Chart.",
        "move-esc": "Move cancelled. Layout unchanged.",
        "move-no-panel": "No panel further that way.",
        "move-target-minimum": "Below Tape.",
        "invalid-min-size": drop["text"],
        "invalid-depth": g["depth_case"]["text"],
        "invalid-tab-group": refusal_text({"key": "tab"}),
        "esc": "Move cancelled. Layout unchanged.",
        "dropped": "Positions moved below Chart.",
        "undone": "Move undone.",
        "splitter-minimum": "Minimum size.",
    }


FRAME_TABLES = ("Panel (fixture)", "Step", "State", "Frame")
STATUS_LEAD = r"\*\*(?:existing|PROPOSED(?:-PENDING)?|RULED|CARRIED)\*\*|the item by design"


def frame_rows(spec: str) -> dict[str, list[str]]:
    """frame id -> the table rows of sections 3-9 whose Frame cell names it (its defining rows)."""
    body = section(spec, "## 3. ", "## 10. ")
    out: dict[str, list[str]] = {}
    col = -1
    for row in body.split("\n"):
        if not row.startswith("|"):
            col = -1
            continue
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        if col < 0:
            state_table = cells[0] in FRAME_TABLES and "Frame" in cells
            col = cells.index("Frame") if state_table else 99
            continue
        if col < len(cells):
            hit = re.match(r"`SCR-021/([a-z0-9-]+)`", cells[col])
            if hit:
                out.setdefault(hit.group(1), []).append(row)
    return out


def chord_unmarked(line: str, bindings: set[str]) -> list[str]:
    out: list[str] = []
    for hit in CHORD.finditer(line):
        token = hit.group(1)
        head, _, tail = token.rpartition("+")
        variants = [f"{head}+{t}" for t in tail.split("/")] if head else [token]
        if all(v in bindings for v in variants):
            continue
        start = max(
            line.rfind(";", 0, hit.start()),
            line.rfind("|", 0, hit.start()),
            line.rfind(". ", 0, hit.start()),
        )
        stops = [
            i
            for i in (
                line.find(";", hit.end()),
                line.find("|", hit.end()),
                line.find(". ", hit.end()),
            )
            if i >= 0
        ]
        clause = line[start + 1 : min(stops) if stops else len(line)]
        if "PROPOSED" not in clause:
            out.append(token)
    return out


def check_frames(spec: str, d: dict[str, Any]) -> list[str]:
    out: list[str] = []
    rows = frame_rows(spec)
    polite = frame_polite(d)
    for frame in sorted(set(rows) - set(FRAME_CARRIERS)):
        out.append(f"FAIL frame row `SCR-021/{frame}` has no gate entry in the tool")
    for frame, carriers in FRAME_CARRIERS.items():
        found = rows.get(frame, [])
        if len(found) != 1:
            out.append(f"FAIL frame `SCR-021/{frame}` has {len(found)} defining rows, not 1")
            continue
        row = found[0]
        for carrier in carriers:
            if not all(n in row for n in CARRIER_NEEDLES[carrier]):
                out.append(f"FAIL frame `SCR-021/{frame}` does not draw {carrier}")
        if frame in FRAME_ESC and FRAME_ESC[frame] not in row:
            out.append(f"FAIL frame `SCR-021/{frame}` does not name its Esc exit")
        said = re.findall(r"polite: [\"“]([^\"”]+)[\"”]", row)
        want = polite.get(frame)
        if want is None and said:
            out.append(f"FAIL frame `SCR-021/{frame}` announces {len(said)} string(s), not 0")
        if want is not None and said != [want]:
            out.append(f"FAIL frame `SCR-021/{frame}` lacks its one polite string {want!r}")
    return out


def frame_body(spec: str) -> str:
    return section(spec, "## 3. ", "## 10. ")


def frame_lines(spec: str) -> list[tuple[str, str]]:
    """(where, line) for every line of section 0 and sections 3-9 that names a frame."""
    out: list[tuple[str, str]] = []
    for where, body in (
        ("§0", section(spec, "## 0. ", "## 1. ")),
        ("§3-§9", section(spec, "## 3. ", "## 10. ")),
    ):
        for line in body.split("\n"):
            if "`SCR-021/" in line:
                board = re.match(r"\| (\d\d) ", line)
                tag = (
                    f"board {board.group(1)}" if board else line.split("`SCR-021/")[1].split("`")[0]
                )
                out.append((f"{where} {tag}", line))
    return out


def frame_segments(line: str) -> list[tuple[str, int, int]]:
    """(frame id, start, end): the text each frame id on a line owns (M-5, per frame, not per line).

    A frame owns the parenthesis that directly follows its id, else the text up to the next frame
    id, the end of its sentence (m-11) or the line's end; text outside every
    segment (a board's lead-in, its trailing cells, a sentence appended after it) is owned by no
    frame, so a lock there fails like a lock on any non-T2 frame.
    """
    hits = list(FRAME_ID.finditer(line))
    out: list[tuple[str, int, int]] = []
    for i, hit in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(line)
        stop = SEGMENT_END.search(line, hit.end(), end)
        if stop:
            end = stop.start() + 1
        j = hit.end()
        while j < end and line[j] == " ":
            j += 1
        if j < end and line[j] == "(":
            depth = 0
            for k in range(j, len(line)):
                depth += {"(": 1, ")": -1}.get(line[k], 0)
                if depth == 0:
                    end = min(end, k + 1)
                    break
        out.append((hit.group(1), hit.start(), end))
    return out


def check_t2_and_chords(spec: str, bindings: set[str]) -> list[str]:
    out: list[str] = []
    for where, line in frame_lines(spec):
        segments = frame_segments(line)
        for frame, start, end in segments:
            if frame not in T2_FRAMES:
                continue
            needles = (*T2_NEEDLES, (T2_FRAMES[frame].strip("`."), T2_FRAMES[frame]))
            lacks = [label for label, needle in needles if needle not in line[start:end]]
            if lacks:
                out.append(f"FAIL T2 frame `{frame}` ({where}) lacks {', '.join(lacks)}")
        owners: list[str] = []
        for hit in LOCKISH.finditer(line):
            owner = next((f for f, a, b in segments if a <= hit.start() < b), "no frame")
            if owner not in T2_FRAMES and owner not in owners:
                owners.append(owner)
        for owner in owners:
            out.append(
                f"FAIL {where}: a lock, CMP-079 or aria-disabled on `{owner}`, "
                "not one of the two T2 frames"
            )
        for hit in ESC_GATED.finditer(line):
            if "never" not in hit.group(0):
                out.append(f"FAIL {where}: `Esc` is gated or locked in a frame (A3: never gated)")
                break
        for token in chord_unmarked(line, bindings):
            out.append(f"FAIL {where}: chord `{token}` is not in keymap.json and not PROPOSED")
    for where, body in (("§0", section(spec, "## 0. ", "## 1. ")), ("§3-§9", frame_body(spec))):
        for line in body.split("\n"):
            if line.startswith("#"):
                continue
            for clause in re.split(r"; |\. | \| ", line):
                if CTRL_Z in clause and "`chart.undo`" not in clause:
                    out.append(f"FAIL {where}: `Ctrl+Z` drawn as something other than chart.undo")
    rule = next((r for r in spec.split("\n") if r.startswith("**The rule, once.**")), "")
    for needle in T2_RULE:
        if needle not in rule:
            out.append(f"FAIL the one T2 statement (section 11) lacks {needle}")
    return out


def check_tables(spec: str, bindings: set[str]) -> list[str]:
    out: list[str] = []
    for row in table_after(section(spec, "## 5. ", "## 6. "), "Operation"):
        if (
            len(row) < 3
            or not row[2]
            or re.search(r"pointer[- ]only", " ".join(row), re.IGNORECASE)
        ):
            out.append(f"FAIL parity row `{row[0]}` lacks a keyboard path or is pointer-only")
    for row in table_after(section(spec, "## 10. ", "## 11. "), "Function"):
        chords = re.findall(r"`([^`]+)`", row[1]) if len(row) > 2 else []
        status = row[2] if len(row) > 2 else ""
        # m-10: the cell's own lead decides its status; a RULED elsewhere in it does not
        if re.search(r"(?<!drawn as )\bshipped\b", status, re.IGNORECASE):
            out.append(f"FAIL key row `{row[0]}` calls a key shipped")
        elif not re.match(STATUS_LEAD, status):
            out.append(f"FAIL key row `{row[0]}` is neither existing nor PROPOSED / RULED")
        elif "**existing**" in status and any(
            c not in bindings for c in chords if re.search(r"\+|^F\d", c)
        ):
            out.append(f"FAIL key row `{row[0]}`: an existing chord is not in keymap.json")
    if not re.search(r"`Esc` is never gated or locked", spec):
        out.append("FAIL the A3 sentence (`Esc` is never gated or locked) is missing")
    bar = next((r for r in spec.split("\n") if r.startswith("| D04-D-8 ")), "")
    if 'aria-atomic="false"' not in bar:
        out.append('FAIL D04-D-8: the status bar lacks aria-atomic="false" (`05` §6.2, once)')
    return out


def check_hygiene(text: str, label: str) -> list[str]:
    return [
        f"FAIL {label}: forbidden pattern /{p}/ present"
        for p in FORBIDDEN
        if re.search(p, text, re.IGNORECASE)
    ]


def evaluate(spec: str, handoff: str) -> tuple[list[str], dict[str, Any]]:
    d = derived(spec, handoff)
    bindings = set(d["bindings"])
    problems = check_markers(spec, d["markers"])
    problems += check_numbers(spec, handoff, d)
    problems += check_frames(spec, d)
    problems += check_t2_and_chords(spec, bindings)
    problems += check_tables(spec, bindings)
    problems += check_hygiene(spec, "spec") + check_hygiene(handoff, "handoff")
    problems += check_hygiene(Path(__file__).read_text(encoding="utf-8"), "tool")
    if d["contrast"]["failed"]:
        problems.append(f"FAIL contrast: {d['contrast']['failed']} gated row(s) under the bar")
    if d["markers"]["tokens_missing"]:
        problems.append("FAIL tokens: a bound token does not resolve")
    if "Boards as drawn" not in section(spec, "## 0. ", "## 1. "):
        problems.append("FAIL section 0 does not list the boards as drawn")
    return problems, d


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def check(spec_path: Path, pr_body: Path | None) -> int:
    spec = read(spec_path)
    problems, d = evaluate(spec, read(HANDOFF))
    if pr_body is not None:
        body = read(pr_body)
        if CLOSING.search(body):
            problems.append("FAIL PR body carries a closing keyword")
        problems += check_hygiene(body, "PR body")
        if "Refs #320" not in body or "Partial:" not in body:
            problems.append("FAIL PR body lacks `Refs #320` or the `Partial:` line")
    for p in problems:
        print(p)
    m = d["markers"]
    print(
        f"{'FAIL' if problems else 'OK'}: {len(MARKER.findall(spec))} markers, "
        f"{len(CONTEXTS)} number contexts, {len(FRAME_CARRIERS)} gated frame rows, "
        f"{len(problems)} problem(s); contrast {m['contrast_gated']} gated rows, "
        f"{m['contrast_fail']} FAIL, worst {m['worst_gated']}"
    )
    return 1 if problems else 0


# ------------------------------------------------------------------ self-test -------------------
# The text review's frame-level and number mutations (round 1), then the folds' and the boards
# PR's (name, old, new); each must raise exactly one new FAIL, and no two the same FAIL. Gates with
# no mutation here (n-6): section 0's PENDING (every PROPOSED-PENDING stamp carries the word),
# ``--pr-body`` (not part of ``evaluate``), and the contrast / token verdicts (read from the token
# files, not the spec); each fires under ``--check``.
MUTATIONS: tuple[tuple[str, str, str], ...] = (
    ("K3 move-step-panel announcement dropped", 'polite: "Chart, BTCUSDT 1m."', "silent"),
    ("K1 announcement dropped", 'polite: "Panel options."', "silent"),
    ("Close parity keyboard cell emptied", "| Close (last item)  ", "|   "),
    (
        "a §10 PROPOSED status called shipped",
        "| **PROPOSED** `workspace.cycle_region`",
        "| shipped `workspace.cycle_region`",
    ),
    (
        "a lock drawn on board 03",
        "P7 `SCR-021/invalid-min-size` (the Tape's",
        "P7 `SCR-021/invalid-min-size` (a CMP-019 lock glyph; the Tape's",
    ),
    ("F11 to F12 in an existing key row", "| `F11`  ", "| `F12`  "),
    # n-6: a cell inserted in the K5 row (a real deletion fails three ways: rows, polite, Esc)
    ("a cell inserted in the K5 row", "| K5 `dropped` |", "| K5 `dropped` | dropped |"),
    ("K3 move-step-side announcement dropped", 'polite: "Below Chart."', "silent"),
    (
        "P2 lit outline removed",
        "Over the Chart's left band (156 px): the band lit by the " + LIT,
        "Over the Chart's left band (156 px): the band lit",
    ),
    ("K3 side lit outline removed", '"Tab with Chart", lit by the ' + LIT, '"Tab with Chart", lit'),
    ("K3 panel target mark removed", "its five zones in " + MARK, "its five zones marked"),
    (
        "P1 ghost removed",
        "a 240\u00d7160 card, `color.surface.overlay` at `opacity.muted`",
        "a 240\u00d7160 card",
    ),
    (
        "K3 side ghost removed",
        "the ghost (`color.surface.overlay` at `opacity.muted`",
        "the ghost (filled",
    ),
    (
        "Alt+Shift+→ added to K3",
        '`↓` moves to "Below Chart"',
        '`↓` or `Alt+Shift+→` moves to "Below Chart"',
    ),
    (
        "Alt+Shift+→ added to the §6 focused row",
        "arrows move the split 2 %",
        "arrows or `Alt+Shift+→` move the split 2 %",
    ),
    (
        "board 05 lock removed",
        'Right of" in the T2 form — the CMP-019 lock glyph',
        'Right of" in the T2 form — the glyph',
    ),
    (
        "board 05 reason key removed",
        "the `layout.limit.min_size` sentence as the second line,",
        "the sentence as the second line,",
    ),
    (
        "§5 Move to lock and key removed",
        "carry the CMP-019 lock before the full label and `layout.limit.min_size`",
        "carry the label and the sentence",
    ),
    ("Esc removed from K6", "`Esc` at any step", "Any step"),
    ("Esc removed from P8", "`Esc` during the drag", "During the drag"),
    ("Esc removed from the K2 bar", "Enter: choose it · Esc: cancel ·", "Enter: choose it ·"),
    (
        "named frames 48 to 49",
        "48 named `SCR-021/<state>` frames",
        "49 named `SCR-021/<state>` frames",
    ),
    ("gated rows 27 to 28", "**27 gated rows", "**28 gated rows"),
    ("band 156 to 158", "(810\u00d7623, band 156", "(810\u00d7623, band 158"),
    (
        "worst 6.30 to 6.31",
        "**Worst two-tone carrier:** 6.30:1",
        "**Worst two-tone carrier:** 6.31:1",
    ),
    (
        "ghost 722\u00d7309 to 722\u00d7300",
        "Tape's 722\u00d7309 lower half",
        "Tape's 722\u00d7300 lower half",
    ),
    (
        "a lock drawn on K4's chooser sides",
        "and every side of it are hatched",
        "and every side of it are hatched, each with the CMP-019 lock glyph",
    ),
    (
        "board 08 aria-disabled removed",
        "Save T2 under the SCR-124 banner, `aria-disabled`",
        "Save T2 under the SCR-124 banner",
    ),
    ("an unmarked chord on board 06", "`Alt+Shift+arrows` PROPOSED-PENDING", "`Alt+Shift+arrows`"),
    ("P7 hatch removed", "the band hatched with " + HATCH, "the band hatched"),
    ("P9 announcement dropped", 'polite: "Positions moved below Chart."; the tab', "the tab"),
    ("a marker value drifts", "audit:band_max=160", "audit:band_max=170"),
    ("the ring-alone ratio drifts", "measures 2.16:1 there", "measures 2.17:1 there"),
    (
        "a refusal sentence not the tool's",
        '("Can\'t drop here: DOM would be narrower than its 380 px minimum." at',
        '("Can\'t drop here: Tape would be narrower than its 380 px minimum." at',
    ),
    ("key rows 17 to 18", "Keys: 17 rows", "Keys: 18 rows"),
    ("a local path in the spec", "## 19. Deviations", "/ho" + "me/x/y\n\n## 19. Deviations"),
    (
        "the T2 statement loses aria-disabled",
        'it is `aria-disabled="true"`, never',
        "it is greyed, never",
    ),
    ("the A3 sentence gated", "`Esc` is never gated or locked", "`Esc` is sometimes gated"),
    # the text delta (fold 2): M-5, m-9, m-10, m-7 (two) and m-8: six mutations for five fixes
    (
        "a lock drawn on move-no-panel, on board 05's T2 line",
        '`SCR-021/move-no-panel` ("No panel further that way.")',
        '`SCR-021/move-no-panel` ("No panel further that way.", `aria-disabled`)',
    ),
    ("P8 Esc gated", "`Esc` is never gated (A3)", "`Esc` is gated under view-as (A3)"),
    (
        "a §10 status RULED only elsewhere in the cell",
        "| **RULED** by default (Q-6)",
        "| live by default (RULED Q-6)",
    ),
    ("§3.1 band column 108 to 110", "| 108  | **108** ", "| 108  | **110** "),
    ("the Tape's 232 to 230 in §3.2", "the Tape's 232 breaks", "the Tape's 230 breaks"),
    ("D04-D-8 loses aria-atomic", 'carries `aria-atomic="false"`', "carries the role"),
    # the boards PR (carries of the text-first approval): m-11, m-12 (two sites), m-13 (two),
    # n-7, and n-6's gates that had none
    (
        "m-11 a lock in a sentence appended after §9's T2 inset",
        "the one notice (§11).\n",
        "the one notice (§11). The toast's Undo is `aria-disabled` under view-as.\n",
    ),
    (
        "m-12 §8's chart height reworded (D04-D-5's other site still found)",
        "height under 120 px (168 for a chart)",
        "height under 120 px (or 170 for a chart)",
    ),
    (
        "m-12 D04-D-3's widths reworded (§3.2's site still found)",
        "leaves both 226 wide, under",
        "leaves both of them 228 wide, under",
    ),
    (
        "m-13 §12: the dark cell takes the light value",
        "| 8.81 (8.77)  ",
        "| 8.98 (8.77)  ",
    ),
    (
        "m-13 §3.2: the refusal swapped for another tool sentence",
        '("Can\'t drop here: DOM would be narrower than its 380 px minimum." at',
        '("Can\'t drop here: Positions would be narrower than its 300 px minimum." at',
    ),
    ("n-7 Ctrl+Z drawn as layout undo in P10", "After Undo:", "After `Ctrl+Z`:"),
    ("n-6 a size the tool does not derive", "the 454\u00d7318 ghost", "the 454\u00d7319 ghost"),
    (
        "n-6 a number context vanishes",
        "refuses one more split (depth 7)",
        "refuses another split (depth 7)",
    ),
    (
        "n-6 an unknown marker",
        "<!-- audit:halo=1 -->",
        "<!-- audit:halo=1 --> <!-- audit:nope=1 -->",
    ),
    ("n-6 a marker missing", " <!-- audit:halo=1 -->", ""),
    ("n-6 a marker twice", "<!-- audit:halo=1 -->", "<!-- audit:halo=1 --> <!-- audit:halo=1 -->"),
    (
        "n-6 a second polite string in P10",
        'polite: "Move undone."',
        'polite: "Move undone."; polite: "Layout restored."',
    ),
)


def self_test(spec_path: Path) -> int:
    spec = read(spec_path)
    handoff = read(HANDOFF)
    before = spec_path.read_bytes() if spec_path.exists() else b""
    base, _ = evaluate(spec, handoff)
    ok = not base
    print(f"clean spec: rc {1 if base else 0} ({len(base)} problem(s))")
    for p in base:
        print(f"  {p}")
    seen: dict[str, str] = {}
    for no, (name, old, new) in enumerate(MUTATIONS, start=1):
        if spec.count(old) < 1:
            ok = False
            print(f"mutation {no:02d} {name}: DOES NOT APPLY (the text to mutate is gone)")
            continue
        got, _ = evaluate(spec.replace(old, new, 1), handoff)
        fresh = [p for p in got if p not in base]
        rc = 1 if got else 0
        dup = [p for p in fresh if p in seen]
        caught = rc == 1 and len(fresh) == 1 and not dup
        ok = ok and caught
        flag = "" if caught else " - NOT CAUGHT EXACTLY ONCE" if not dup else " - DUPLICATE FAIL"
        print(f"mutation {no:02d} {name}: rc {rc}, {len(fresh)} new FAIL{flag}")
        for p in fresh:
            print(f"  {p}")
            seen.setdefault(p, name)
    restored, _ = evaluate(spec, handoff)
    same = (spec_path.read_bytes() if spec_path.exists() else b"") == before
    ok = ok and not restored and same
    print(
        f"restore: rc {1 if restored else 0}; spec file byte-identical: {same}; "
        f"--self-test: {'ok' if ok else 'FAIL'} - {len(MUTATIONS)} mutations in memory, "
        f"{len(seen)} distinct FAILs"
    )
    return 0 if ok else 1


# ------------------------------------------------------------------ report ----------------------
def report(d: dict[str, Any]) -> str:
    g, cm, m = d["geometry"], d["contrast"], d["markers"]
    out = ["ZONE GEOMETRY (PROPOSED: band = 25 % of the smaller side, clamp 48-160, centre >= 48)"]
    for name, z in g["zones"].items():
        out.append(
            f"  {name:18s} {z['w']}x{z['h']}  band {z['band']}  centre {z['centre_w']}x"
            f"{z['centre_h']}  offered {','.join(z['offered'])}  withdrawn "
            f"{','.join(z['withdrawn']) or '-'}"
        )
    for key in ("dense_1920", "dense_1280", "dense_1024", "small_1280"):
        out.append(
            f"  {key}: " + ", ".join(f"{LABEL[k]} {v['w']}x{v['h']}" for k, v in g[key].items())
        )
    out.append("DROPS of Positions in `dense` (moving panel's minimum first, D04-D-3)")
    for vp, table in g["drops"].items():
        for a in table:
            after = ", ".join(f"{LABEL[k]} {v['w']}x{v['h']}" for k, v in a["after"].items())
            out.append(f"  {vp} {LABEL[a['target']]:5s} {a['zone']:6s} -> {a['text']}  [{after}]")
    dc = g["depth_case"]
    out.append(f"  depth case: depth {dc['before']} -> {dc['after']}: {dc['text']}")
    ac6 = g["large_over_small"]
    out.append(f"  AC6: band {ac6['tape_band']} -> {ac6['text']} {ac6['after']}")
    for key, a in g["small_chooser"].items():
        out.append(f"  small chooser {key:13s} -> {a['text']}  {a['after']}")
    out.append("CONTRAST (worst of the better tone over each extreme, A/B, and their greyscale)")
    for row in cm["rows"]:
        val = row.get("a_vs_b", row.get("ratio"))
        verdict = "PASS" if row["ok"] else "FAIL"
        out.append(
            f"  {row['theme']:13s} {row['element'][:50]:50s} {val:.2f} "
            f"worst {row['worst']:.2f} {verdict} >= {row['bar']}"
        )
    out.append(f"  singles: {cm['singles']}")
    out.append(f"MARKERS ({len(m)}): " + ", ".join(f"{k}={v}" for k, v in m.items()))
    return "\n".join(out)


USAGE = "usage: e15_d04_dock_audit.py [--json] | --check SPEC [--pr-body FILE] | --self-test [SPEC]"


def main(argv: list[str]) -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    if "--self-test" in argv:
        i = argv.index("--self-test")
        return self_test(Path(argv[i + 1]) if i + 1 < len(argv) else SPEC)
    if "--check" in argv:
        i = argv.index("--check")
        if i + 1 >= len(argv) or ("--pr-body" in argv and argv.index("--pr-body") + 1 >= len(argv)):
            print(USAGE, file=sys.stderr)
            return 2
        body = Path(argv[argv.index("--pr-body") + 1]) if "--pr-body" in argv else None
        return check(Path(argv[i + 1]), body)
    if "--json" in argv:
        print(
            json.dumps(
                derived(read(SPEC), read(HANDOFF)), indent=2, ensure_ascii=False, default=str
            )
        )
        return 0
    print(report(derived(read(SPEC), read(HANDOFF))))
    return check(SPEC, None)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
