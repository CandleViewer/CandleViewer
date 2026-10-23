"""E11-D09 chart-engine hand-off pack audit: every number the pack quotes, derived from the repo.

Offline, ``python3 -I`` from the repo root; stdlib only beyond the repo modules it imports. It
imports six lane tools and two repo loaders and executes no other repo code: the token loader
``packages/ui/tokens/tests/verify_tokens.py`` (``load``, ``merged_set``, ``resolve``),
``docs/design/_tools/contrast_check.py`` (``contrast_ratio()``), the five upstream audit tools
``e11_d02_chassis_audit.py``, ``e11_d03_scales_audit.py``, ``e11_d04_table_audit.py``,
``e11_d05_ds_audit.py``, ``e11_d06_motion_audit.py`` (their ``PAIRS`` / ``ROWS``, ``col()`` and
``BAR``) and the E11-D07 review tool ``e11_d07_a11y_review_audit.py`` (its ``DESIGN_BINDINGS``,
``expand_keys`` and ``keymap_section()``). Nothing is re-implemented, so every ratio agrees with
E11-D02..D07's to the hundredth. No network call is made, no URL literal exists in this file, and
the only writes happen under ``--figures <dir>``.

What it computes (each section names its source so a reviewer can re-grep it):

1. The redline parse: E11-D02 section 2's dimensions table and section 6's density record, read
   from the spec at the base; every token named in a cell resolved through the loader; the
   typed-only cells (the drift ``size.control.height``, the gutter formula, the pill heights) named.
2. The behaviour-rule constants, typed once with a source line each, and the worked cases of
   E11-D02 section 4.2 (three instruments, the dense variant), section 5.4 (six px-per-bar rows)
   and section 7.5 (the legend's 600 px case) re-derived from the rule and compared with the
   spec's numbers. A disagreement is reported, never corrected silently.
3. The key map: E11-D07's 134 atomic design bindings joined with the K-row resolutions (PROPOSED)
   and an announcement literal typed from the owning specs; the pack's section 4 table compared
   row by row (count, keys, stops); the 37 unregistered keys from E11-D07's own computation.
4. The motion table: E11-D06 section 7 parsed at the base (47 rows) and compared cell by cell
   with the pack's section 5; the coverage recount (rows that animate under motion-safe).
5. The token mapping: every slot in the pack's section 6 resolved (a semantic token through the
   loader in dark / light / high-contrast, a ``color.chart.*`` alias through E11-D05 section 4's
   alias table to its primitive, a ``CR:`` name or a metric as a gap); the nine ``15`` entries'
   Tokens fields re-read and compared; the hex gate over the pack and the hand-off file.
6. The state matrix: the pack's section 7 parsed; every source state (E11-D02 section 10,
   E11-D03 section 10, E11-D04 section 15, ``14`` SCR-030) present for its surface; cells counted,
   empty cells 0; the hand-off file's Table 1 reconciled with section 7.
7. The open-question log: the six upstream logs parsed; every source row present once in the
   pack's section 13; counts (total, answered, routed, unowned = 0); the owner histogram.
8. The glyph union from the GL-string literal, compared both ways with ``26`` section 3.7's set.
9. The asset counts: E11-D05 section 7's pattern rows, CR-6's icon names, the fonts by token,
   files at the base, the A / C / G / Q / hand-off / walkthrough counts.
10. String gates: no fabricated-session phrase, no local path, no Penpot host (a generic pattern
    that names no domain), the ``Partial:`` line and no closing keyword in the draft (``--draft``).

Usage:
  python3 -I docs/design/_tools/e11_d09_handoff_audit.py                 Markdown report
  ... --json                                                one object (boards, figure, check-nums)
  ... --emit <redlines|keymap|motion|tokens|matrix|oq|glyphs|findings>    the pack's table rows
  ... --check docs/design/E11/E11-D09.md [docs/design/E11/E11-D09-handoff.md] [--draft <file>]
  ... --figures docs/design/E11/img                                       render figure A

Exit 0 on a clean run; exit 1 on a gated FAIL (a hex in the pack or the hand-off file; a key-map row
missing from or extra to the design bindings; a motion row differing from E11-D06; an empty matrix
cell; an open-question row without owner and target; a source-log row absent; a fabricated-session
phrase; a marker drift under ``--check``; the E11-D07 tool absent under ``--check``).
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
DESIGN = ROOT / "docs" / "design"
PLAN = ROOT / "docs" / "plan"
TOKENS = ROOT / "packages" / "ui" / "tokens"
THEMES = ("dark", "light", "high-contrast")


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(TOKENS / "tests"))
# The imported lane tools are untyped modules: every attribute read from them is Any here.
verify: Any = _load(TOKENS / "tests" / "verify_tokens.py", "verify_tokens")
contrast_check: Any = _load(TOOLS / "contrast_check.py", "contrast_check")
SIBLINGS: dict[str, Any] = {
    "E11-D02": _load(TOOLS / "e11_d02_chassis_audit.py", "e11_d02_chassis_audit"),
    "E11-D03": _load(TOOLS / "e11_d03_scales_audit.py", "e11_d03_scales_audit"),
    "E11-D04": _load(TOOLS / "e11_d04_table_audit.py", "e11_d04_table_audit"),
    "E11-D05": _load(TOOLS / "e11_d05_ds_audit.py", "e11_d05_ds_audit"),
    "E11-D06": _load(TOOLS / "e11_d06_motion_audit.py", "e11_d06_motion_audit"),
}
D07_TOOL = TOOLS / "e11_d07_a11y_review_audit.py"
D07_MERGE = "de9a67609f887a82405abf45ef3286c963842d15"  # the #4228 merge commit on main
D07_ABSENT = (
    "D07 tool: absent at this base; #4228 merged on main as " + D07_MERGE + " — rebase onto it"
)
D07_SPEC = DESIGN / "E11" / "E11-D07.md"
d07: Any | None = _load(D07_TOOL, "e11_d07_a11y_review_audit") if D07_TOOL.exists() else None


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def ratio(fg: str, bg: str) -> float:
    return float(contrast_check.contrast_ratio(hex_to_rgb(fg), hex_to_rgb(bg)))


def fmt(v: float) -> str:
    return f"{v:.2f}"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def rows(text: str) -> list[list[str]]:
    """Parse a pipe-separated literal table; a line indented by two spaces continues the record."""
    records: list[str] = []
    for ln in text.strip("\n").splitlines():
        if ln.startswith("  ") and records:
            records[-1] += " " + ln.strip()
        elif ln.strip():
            records.append(ln)
    return [[c.strip() for c in r.split(" | ")] for r in records]


def md_table(text: str, start: str, end: str) -> list[list[str]]:
    """Every data row of the first Markdown table between two headings (pipes in cells escaped)."""
    body = text.split(start, 1)[1]
    if end:
        body = body.split(end, 1)[0]
    out: list[list[str]] = []
    for ln in body.splitlines():
        if ln.startswith("|") and not re.match(r"^\|\s*-{3,}", ln):
            cells = ln.strip().strip("|").replace("\\|", "\x00").split("|")
            out.append([c.strip().replace("\x00", "|") for c in cells])
    return out


def all_tokens(theme: str) -> dict[str, Any]:
    prim = verify.load(verify.PRIMITIVES)
    allt: dict[str, Any] = dict(prim)
    allt.update(verify.merged_set(verify.THEMES[theme]))
    return allt


_TOK: dict[str, dict[str, Any]] = {}


def tokens(theme: str) -> dict[str, Any]:
    if theme not in _TOK:
        _TOK[theme] = all_tokens(theme)
    return _TOK[theme]


def resolve_token(name: str, theme: str) -> str | None:
    """A token's resolved value in one theme: a hex for colours, a scalar or a compact composite."""
    t = tokens(theme)
    if name not in t:
        return None
    val = t[name].get("$value")
    try:
        if isinstance(val, dict):
            parts = [f"{k}={verify.resolve(v, t)}" for k, v in val.items()]
            return "{" + ", ".join(str(p) for p in parts) + "}"
        return str(verify.resolve(val, t))
    except (KeyError, ValueError, TypeError, RecursionError):  # an unresolvable alias is a gap
        return None


def colour(theme: str, name: str) -> str | None:
    v = resolve_token(name, theme)
    return v if v and re.fullmatch(r"#[0-9A-Fa-f]{6}", v) else None


# ---- 1 redlines (E11-D02 §2, §6)
D02 = DESIGN / "E11" / "E11-D02.md"
D03 = DESIGN / "E11" / "E11-D03.md"
D04 = DESIGN / "E11" / "E11-D04.md"
D05 = DESIGN / "E11" / "E11-D05.md"
D06 = DESIGN / "E11" / "E11-D06.md"
P14 = PLAN / "14-screens-catalogue.md"
P15 = PLAN / "15-component-catalogue.md"
P26 = PLAN / "26-chart-engine-design.md"
TOK_NAME_RE_D02 = re.compile(
    r"`((?:color|size|space|type|radius|opacity|font|motion|elevation)\.[a-z0-9.*-]+)`"
)
# GL or DOM per E11-D02 §2 row (the element's first words), typed from §7 (overlay vs batch).
GL_DOM = {
    "Toolbar row": "DOM",
    "Drawing rail": "DOM",
    "Chip": "DOM",
    "Legend row": "DOM",
    "Legend inset": "DOM",
    "Axis label type": "GL",
    "Price-gutter padding": "GL",
    "Price-gutter width": "GL (layout)",
    "Time-strip height": "GL",
    "Cluster segment": "DOM",
    "Splitter hit band": "DOM band / GL hairline",
    "Collapsed stub": "DOM",
    "Minimum pane height": "layout",
    "Corner-badge slot": "DOM",
    "Tooltip padding": "DOM",
    "Crosshair / last-price pill": "GL",
    "Watermark": "GL",
}


def line_of(path: Path, needle: str) -> int:
    for i, ln in enumerate(read(path).splitlines(), 1):
        if needle in ln:
            return i
    return 0


def parse_d02_dimensions() -> list[dict[str, Any]]:
    """E11-D02 §2's per-density dimensions table, with the line of every row."""
    lines = read(D02).splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("**Dimensions per density**"))
    out: list[dict[str, Any]] = []
    header_seen = False
    for i in range(start, len(lines)):
        ln = lines[i]
        if ln.startswith("## 3."):
            break
        if not ln.startswith("|"):
            continue
        if not header_seen:
            header_seen = True
            continue
        if re.match(r"^\|\s*-{3,}", ln):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        toks = sorted(set(TOK_NAME_RE_D02.findall(" ".join(cells[1:4]))))
        gd = next((v for k, v in GL_DOM.items() if cells[0].startswith(k)), "—")
        out.append(
            {
                "element": cells[0],
                "comfortable": cells[1],
                "compact": cells[2],
                "dense": cells[3],
                "tokens": toks,
                "gl_dom": gd,
                "line": i + 1,
            }
        )
    return out


def parse_d02_density() -> list[dict[str, Any]]:
    """E11-D02 §6's density record (the three mode rows)."""
    text = read(D02)
    data = md_table(text, "## 6. Density triples", "`fontSizeClass` (cells)")
    out: list[dict[str, Any]] = []
    for r in data:
        if r and r[0].strip("*") in ("comfortable", "compact", "dense") and len(r) >= 9:
            out.append(
                {
                    "mode": r[0].strip("*"),
                    "cellPadPx": r[1],
                    "fontSizeClass": r[2],
                    "lodBias": r[3],
                    "axis_type": r[4],
                    "G": r[5],
                    "spacing": r[6],
                    "legend_row": r[7],
                    "line": line_of(D02, f"| **{r[0].strip('*')}**"),
                }
            )
    return out


def redline_tokens(parsed: list[dict[str, Any]]) -> dict[str, Any]:
    names = sorted({t for r in parsed for t in r["tokens"]})
    resolved = {n: resolve_token(n, "dark") for n in names}
    typed_only = [
        f"{r['element']} (:{r['line']})"
        for r in parsed
        if not r["tokens"] and not re.search(r"`type\.|`size\.|`space\.", r["comfortable"])
    ]
    return {"names": names, "resolved": resolved, "typed_only": typed_only}


# Redline rows the D02 §2 table does not carry, typed once with their source line (group | element |
# comfortable | compact | dense | tokens | type token | radius | opacity | GL/DOM | source).
EXTRA_REDLINES = """
axes | Gridline, minor tier | 1 px solid, device-snapped | same | same | `color.chart.grid.minor` (=
  `color.grid.line`); `opacity.grid.minor` 1.0 / 1.0 / 0.0 (hc off, CR) | — | — | 1.0 (hc 0.0) | GL
  | E11-D02 §4.1 :137
axes | Gridline, major tier | 1 px solid | same | same | `color.chart.grid.major` (=
  `color.border.default`) | — | — | 1.0 | GL | E11-D02 §4.1 :138
axes | Boundary line (session / day, week, month) | 1 px dashed 4 / 4, full height | same | same |
  `color.chart.boundary` (= `color.text.tertiary`) | — | — | 1.0 | GL | E11-D02 §4.1 :139
axes | Maintenance band | edges 1 px dashed 4 / 4; 45° hatch 1 px lines, 6 px pitch; label when ≥ 48
  px wide | same | same | edges `color.chart.boundary`; texture `color.chart.hatch.texture` (=
  `color.border.strong`) | `type.num.*` label | — | 1.0 | GL | E11-D02 §4.1 :140; E11-D05 §7 :315
axes | Hairline rule (axis / strip / splitter) | 1 px | same | same | `color.chart.rule` (=
  `color.border.default`) | — | — | 1.0 | GL | E11-D02 §7.1 :244, §7.2 :267, §8 :355
axes | Mode tag (log / % / inv) and zone tag (UTC hh:mm:ss) | caption + digits `type.num.base` |
  `type.num.sm` | `type.num.xs` | `color.chart.axis` (= `color.text.tertiary`) | `type.ui.caption` /
  `type.num.*` | — | 1.0 | GL | E11-D02 §7.1 :244, §7.2 :267
axes | Last-price pill | h 20; ▲ / ▼ glyph; 4 px nub; 1 px dashed line | h 17 | h 16 | fill
  `color.candle.up` / `color.candle.down`; text `color.chart.pill.text.inverse` | `type.num.*` |
  `radius.xs` | 1.0 | GL | E11-D02 §7.1 :244; §2 :99
axes | Mark / index pill | h 20; prefix `M` / `I`; line 1 px dashed 2 / 6 | h 17 | h 16 |
  `color.chart.pill.bg` + `color.chart.pill.border` + `color.chart.pill.text.default`; line
  `color.chart.boundary` | `type.num.*` | `radius.xs` | 1.0 | GL | E11-D02 §7.1 :244
axes | Lock badge (button) | pill h 24; 24 px hit box | h 20 (+2 / +2 invisible padding) | same |
  `color.surface.raised` + `color.border.strong` + `color.text.primary`; lock glyph |
  `type.ui.caption` | `radius.badge` | 1.0 | DOM | E11-D02 §7.1 :244; E11-D03 §5 :193
axes | Cluster segment fill and pressed `auto` | fill + 1 px border; pressed: selected fill + strong
  border + check glyph | same | same | `color.surface.raised` + `color.border.default`; pressed
  `color.surface.selected` + `color.border.strong` + `color.text.primary` | `type.ui.caption` |
  `radius.control` | 1.0 | DOM | E11-D02 §7.2 :267
axes | Paused pill (`auto` off state) | h 24 | h 20 | h 20 | `color.status.warning.subtle` +
  `color.text.primary`; pause glyph `color.status.warning.strong` | `type.ui.caption` /
  `type.num.sm` | `radius.badge` | 1.0 | DOM | E11-D02 §7.2 :267
axes | Cluster exclusion zone / tag zone | 8 px left of the cluster; 8 px right of the zone tag |
  same | same | — | — | — | — | GL (layout) | E11-D02 §5.1 :170\u2013171
crosshair | Crosshair lines | 1 px dashed 4 / 4, device-snapped; `max(1, floor(dpr))` device px |
  same | same | `color.chart.crosshair` (= `color.crosshair`) | — | — | 1.0 (remote `opacity.muted`)
  | GL | E11-D02 §7.3 :298; §4.4 :161
crosshair | Crosshair axis pills | h 20; 4 px horizontal padding | h 17 | h 16 | fill
  `color.chart.crosshair`; text `color.chart.pill.text.inverse` | `type.num.*` | `radius.xs` | 1.0 |
  GL | E11-D02 §7.3 :300
crosshair | Magnet affordance (snap active) | OHLC letter + 12 px magnet glyph at the pill's left
  edge | same | same | as the pill | `type.num.*` | — | — | GL | E11-D02 §7.3 :302
crosshair | Keyboard cursor column (D10) | ≥ 2 px core + 1 px halos | same | same |
  `color.chart.focus.ring` (= `color.focus.ring`); halo `color.chart.pane.bg.default` | — | — | 1.0
  | GL | E06-D03 D10 :176; E11-D05 §4.1b :101
tooltip | Tooltip box (CMP-197) | padding `space.inset.md`; width 200\u2013260 px, ≤ 40 % of the
  pane | `space.inset.sm` | `space.inset.xs` | `color.surface.overlay` + 1 px
  `color.border.default`; `elevation.popover` | title `type.ui.label`; values `type.num.base` /
  `.sm` / `.xs` | `radius.card` | 1.0 | DOM | E11-D02 §7.3 :304\u2013318
tooltip | Tooltip anchor offsets and margins | 16 px right and 16 px below the anchor; 8 px plot
  margins; band ±(pill h / 2 + 4 px) | same | same | — | — | — | — | DOM (layout) | E11-D02 §7.3
  :320
tooltip | Tooltip swatch and rows | 8 px shape swatch; overflow after 12 rows as text | same | same
  | label `color.text.secondary`; value `color.text.primary` | `type.num.*` | — | 1.0 | DOM |
  E11-D02 §7.3 :310\u2013313
legend | Legend block | max width 40 % of the pane; row 0 = pane label row | same | same |
  `color.text.primary`; hidden row `color.text.tertiary`; focus bar `color.action.primary.default` 2
  px | `type.ui.label` / `type.ui.body` | — | 1.0 | DOM | E11-D02 §7.5 :339, :343; §8 :373
legend | Legend controls (chevron, menu, eye toggle) | 32 \u00d7 32 | 24 \u00d7 24 | 24 \u00d7 24
  (floor) | `color.focus.ring` ring 2 px, 2 px offset | — | — | 1.0 | DOM | E11-D02 §7.5 :339; §6
  rule 3 :233
legend | Swatch and label truncation | 8 \u00d7 8 shape swatch; labels ellipsise at 18 characters |
  same | same | the series' token (shape, never colour alone) | `type.ui.label` | — | 1.0 | DOM |
  E11-D02 §7.5 :339, :341
legend | "+N more" popover | max height 60 % of the pane; scrollable | same | same |
  `color.surface.overlay` + `elevation.popover` | `type.ui.label` | `radius.card` | 1.0 | DOM |
  E11-D02 §7.5 :341
panes | Splitter hairline and grip | 1 px hairline; grip 32 \u00d7 4 | grip 24 \u00d7 4 | grip 24
  \u00d7 4 | hairline `color.chart.rule`; grip `color.text.tertiary` → hover `color.text.secondary`
  → drag `color.focus.ring`; hover hairline `color.border.strong` | — | `radius.pill` | 1.0 | GL
  hairline / DOM grip | E11-D02 §8 :355
panes | Splitter focus ring | 28 \u00d7 8 around the grip; hairline in the ring colour full width |
  same | same | `color.focus.ring` | — | — | 1.0 | DOM | E11-D02 §8 :355
panes | Pane focus bar | 2 px at the label row's left edge | same | same |
  `color.action.primary.default` | — | — | 1.0 | DOM | E11-D02 §8 :373
panes | Chart focus ring (CMP-039) | 2 px, 2 px offset, 1 px pane-colour halo on canvas-adjacent
  surrogates | same | same | `color.focus.ring`; halo `color.surface.canvas` | — | — | 1.0 | DOM |
  E11-D02 §7 :240; E11-D05 §9.1 :436
panes | Replay frame | 4 px inside the pane-stack boundary | same | same |
  `color.chart.replay.border` (PROPOSED name; CR-3) | — | — | 1.0 | GL | E11-D02 §10 :414; E11-D05
  §10.4 :782
panes | Disconnected scrim and strip | scrim over the pane stack; centred strip | same | same |
  `color.surface.app` at `opacity.scrim`; strip `color.surface.raised` + `color.text.primary` |
  `type.ui.body` | — | `opacity.scrim` 0.6 | DOM | E11-D02 §10 :413
chrome | Status-row chips | h 24; 8 px horizontal padding; 8 px gap | h 20 (+2 / +2 invisible
  padding → 24 px hit box) | h 20 | `color.surface.raised` + `color.border.default` +
  `color.text.primary` (feed chips canvas-filled) | `type.ui.caption` / `type.num.sm` |
  `radius.badge` | 1.0 | DOM | E11-D02 §10 :422; §12 :652
chrome | Env badge (CMP-075) | text DEMO medium / LIVE bold; 2 px border; LIVE 2 px rule under the
  row | same | same | `color.text.primary`; `color.env.demo` / `color.env.live` | `type.ui.caption`
  | `radius.badge` | 1.0 | DOM | E11-D02 §10 :415
chrome | Countdown (CMP-226) | label caption + digits | same | same | `color.text.secondary`; warn
  `color.status.warning.subtle` + `color.text.primary` + glyph `color.status.warning.strong`; closed
  `color.text.tertiary` | `type.ui.caption` / `type.num.sm`; warn `font.weight.medium` |
  `radius.badge` | 1.0 | DOM | E11-D02 §7.4 :330\u2013332
chrome | Corner badge (reduced detail) | inset 12 | inset 8 | inset 4 | `color.surface.raised` +
  `color.text.primary`; glyph `color.status.warning.strong` | `type.ui.caption` | `radius.badge` |
  1.0 | DOM | E11-D02 §10 :416; §2 :96
chrome | Loading band (older bars) | band left of the oldest bar | same | same |
  `color.surface.hover` + `color.text.secondary` | `type.ui.body` | — | 1.0 | DOM | E11-D02 §7.2
  :273
menus | SCR-043 menu rows | row 32; padding `space.inset.sm`; min width 280, max 360 | row 24 | row
  24 | `color.surface.overlay` + 1 px `color.border.default`; `elevation.popover`; hover
  `color.surface.hover`; heading `color.text.tertiary` | `type.ui.caption` heading | `radius.card` |
  1.0 | DOM | E11-D03 §3.1 :119
menus | D4 inline reason (disabled Logarithmic) | second line inside the item | same | same |
  `color.text.secondary` reason; label `color.text.disabled` (exempt — not T2: a data state) |
  `type.ui.caption` | — | 1.0 | DOM | E11-D03 §3.1 :103; E11-D07 F-29 :590
dialog | SCR-044 dialog (CMP-043 sm) | 420 px wide; day cells 32 \u00d7 32; quick-jump buttons 32
  high; close 24 | same | same | `color.surface.overlay`; `elevation.dialog`; labels
  `color.text.secondary`; hint `color.text.tertiary` | `type.ui.body` / `type.ui.caption`; mono
  inputs | `radius.dialog` | 1.0 | DOM | E11-D03 §7.1 :287\u2013305; §12 :451
dialog | SCR-044 error block (CMP-027) | — | — | — | `color.text.primary` on
  `color.status.danger.subtle`; glyph `color.status.danger.strong`; Jump `color.text.on-action` on
  `color.action.primary.default` | `type.ui.body` | `radius.card` | 1.0 | DOM | E11-D03 §7.1
  :301\u2013304
dialog | T2 quick jump (viewer without `journal:read`; Disconnected) | full label + lock glyph;
  reason in the target line | same | same | `color.text.tertiary` label + glyph;
  `color.text.secondary` reason; `color.surface.raised` fill + `color.border.default` hairline |
  `type.ui.label` | `radius.control` | 1.0 — never `opacity.disabled` | DOM | E11-D07 §9.5 T2-08
  :447, T2-09 :448; E09-D09 §2.2 :46
tab | SCR-031 Scales tab (CMP-043 lg) | rows `size.row.height`; two columns, stacking below 720 px |
  compact when the app is compact | — | `color.surface.overlay`; `elevation.dialog`; helper
  `color.text.tertiary` | `type.ui.caption` helper | `radius.dialog` | 1.0 | DOM | E11-D03 §6.1
  :209\u2013245
tab | Toggle / segmented targets | toggles 24 \u00d7 44; segments ≥ 24 \u00d7 56 | same | same | — |
  — | `radius.control` | 1.0 | DOM | E11-D03 §12 :451
tab | CMP-228 PreviewTile | — | — | — | `color.surface.sunken` | — | `radius.md` | 1.0 | DOM | `15`
  CMP-228 :2678
table | Row height (bar, level, header) | `size.row.comfortable` 32 | `size.row.compact` 24 | — |
  zebra `color.surface.canvas` / `color.surface.raised`; header + hover `color.surface.hover`;
  selected `color.surface.selected`; dividers `color.border.subtle` | — | — | 1.0 | DOM | E11-D04 §2
  :90, §20 :803
table | Cell padding / panel inset | `space.3` 12 / 12 | `space.2` 8 / 8 | — | — | — | — | — | DOM |
  E11-D04 §2 :91
table | Numeric and label type | `type.num.base` 13; `type.ui.body` 13 | `type.num.sm` 11;
  `type.ui.caption` 11 / `type.ui.label` 12 | — | `color.text.primary`; `color.text.secondary`; day
  rule `color.text.tertiary` | `font.family.mono` tabular | — | 1.0 | DOM | E11-D04 §2 :92\u201393
table | Expander / action buttons; chips and Kbd | 32 \u00d7 32; chip 24 | 24 \u00d7 24
  (`size.target.min`); chip 20 (+2 / +2 → 24 hit box) | — | chips `color.surface.raised` +
  `color.border.default` | `type.ui.caption` | `radius.badge` | 1.0 | DOM | E11-D04 §2 :94\u201395
table | View switch segment (CMP-003) | `size.control.comfortable` 32 | `size.control.compact` 24
  (`size.control.height`, density-resolved) | — | pressed `color.surface.selected` +
  `color.border.strong` | `type.ui.caption` | `radius.control` | 1.0 | DOM | E11-D04 §2 :96; E11-D07
  TG24 :481
table | Banner (stale / loading) and sub-table | banner 40; sub-table 10 visible rows | banner 32
  (two lines at 200 %); 12 rows | — | banner `color.status.warning.subtle` / `.strong`; sub-table
  `color.surface.app` | `type.ui.body` | — | 1.0 | DOM | E11-D04 §2 :97\u201398
table | T2 row-menu item (write items for a role without the grant) | full label + lock glyph;
  reason as the item's second line | same | — | `color.text.tertiary` label + glyph;
  `color.text.secondary` reason; `color.surface.raised` fill + `color.border.default` hairline
  (CMP-079) | `type.ui.label` | — | 1.0 — never `opacity.disabled` | DOM | E11-D07 §9.5 T2-01…T2-04
  :440\u2013443; E09-D09 §2.2 :46
table | Export CSV (deferred capability) | absent — hidden by plan with a note until it ships | same
  | — | — | — | — | — | DOM | E11-D07 §9.5 T2-07 :446; F-25 :588
empty-error | SCR-047 block (CMP-026) | centred in the pane-stack region; no `<canvas>` mounted |
  same | — | `color.surface.canvas`; heading `type.ui.heading-sm`; cause `color.text.secondary`;
  timestamp `font.family.mono` `color.text.primary` | `type.ui.heading-sm` / `type.ui.body` | — |
  1.0 | DOM | E11-D04 §11.1 :336
empty-error | SCR-047 1a CTA for Manager / Viewer | the reason sentence alone, no button (sentence
  form) | same | — | `color.text.secondary` | `type.ui.body` | — | 1.0 | DOM | E11-D07 §9.5 T2-06
  :445; E09-D09 §2.2 :46
empty-error | SCR-048 card (CMP-027) | 4 px left rule; alert glyph; code chip | same | — |
  `color.surface.raised`; rule + glyph `color.status.danger.strong`; chip `color.surface.sunken`
  mono | `type.ui.heading-sm` / `type.ui.body` | `radius.card` | 1.0 | DOM | E11-D04 §12.1 :360
"""


def redline_rows() -> list[dict[str, Any]]:
    """The pack's §2 rows: the parsed D02 §2 table first, then the typed extra rows."""
    out: list[dict[str, Any]] = []
    for r in parse_d02_dimensions():
        toks = ", ".join(f"`{t}`" for t in r["tokens"]) or "— (typed px; see the drift note)"
        typ = ", ".join(f"`{t}`" for t in r["tokens"] if t.startswith("type.")) or "—"
        out.append(
            {
                "group": "chassis chrome (D02 §2)",
                "element": r["element"],
                "comfortable": r["comfortable"],
                "compact": r["compact"],
                "dense": r["dense"],
                "tokens": toks,
                "type": typ,
                "radius": "—",
                "opacity": "—",
                "gl_dom": r["gl_dom"],
                "source": f"E11-D02 §2 :{r['line']}",
            }
        )
    for cells in rows(EXTRA_REDLINES):
        out.append(
            dict(
                zip(
                    (
                        "group",
                        "element",
                        "comfortable",
                        "compact",
                        "dense",
                        "tokens",
                        "type",
                        "radius",
                        "opacity",
                        "gl_dom",
                        "source",
                    ),
                    cells,
                    strict=True,
                )
            )
        )
    return out


# ---- 2 behaviour rules
# name | value | source (typed once; every number a B-row quotes)
CONST_TABLE = """
collision_gap_label_heights | 1.5 | E11-D02 §5.1 :168; E11-S06 AC
G_time_px | 96 / 80 / 64 | E11-D02 §5.1 :169
G_price_px | 48 / 40 / 32 | E11-D02 §5.1 :169
exclusion_zone_px | 8 | E11-D02 §5.1 :170\u2013171
price_ladder | {1, 2, 5} \u00d7 10^n \u00d7 tickSize | E11-D02 §5.2 :175
time_ladder_steps | 23 | E11-D02 §5.2 :176
major_step_rule | s_M = min decimal-round (10^k or 5 \u00d7 10^k) ≥ 2 \u00d7 s_L and an integer
  multiple of s_L | E11-D02 §4.2 :148
percent_ladder | 0.1 / 0.2 / 0.5 / 1 / 2 / 5 / 10 | E11-D02 §4.2 :151
tooltip_offset_px | 16 / 16 | E11-D02 §7.3 :320
tooltip_margin_px | 8 | E11-D02 §7.3 :320
tooltip_width_px | 200\u2013260, ≤ 40 % of the pane | E11-D02 §7.3 :318
last_price_band | ±(pill height / 2 + 4 px) | E11-D02 §7.3 :320
docked_threshold_px | box + 32 | E11-D02 §7.3 :320
pill_nudge_gap_px | 2 | E11-D02 §5.5 :205
legend_visible_rows | ⌊0.3 \u00d7 pane height / row height⌋, min 3 | E11-D02 §7.5 :341
legend_ellipsis_chars | 18 | E11-D02 §7.5 :341
legend_popover_max | 60 % of the pane | E11-D02 §7.5 :341
splitter_step_pct | 2 / 10 | E11-D02 §8 :361\u2013362
min_pane_height | max(48 px, 3 \u00d7 axis label height) | E11-D02 §2 :95; §8 :367
stub_height_px | 32 / 24 / 24 | E11-D02 §2 :94
collapse_duration | motion.duration.normal, motion.easing.standard | E11-D06 §6.4 :236
magnet_radius_weak_px_s07 | 8 | E11.json E11-S07 Scope (E11-D01 :234)
magnet_radius_drawing_px_e14 | 12 | E14-D02 :65
magnet_release_hysteresis_px | 2 (PROPOSED by E11-D06) | E11-D06 §5.3 :199
"""


def const() -> dict[str, dict[str, str]]:
    return {r[0]: {"value": r[1], "source": r[2]} for r in rows(CONST_TABLE)}


PRICE_CASES: list[dict[str, Any]] = [
    # instrument, tick, lo, hi, pane px, G, expected s_L, s_M, labels, spacing (E11-D02 §4.2 :150)
    {
        "name": "BTCUSDT compact",
        "tick": 0.5,
        "lo": 63900,
        "hi": 64300,
        "px": 600,
        "G": 40,
        "sL": 50,
        "sM": 100,
        "labels": 9,
        "spacing": 75,
    },
    {
        "name": "ETHUSDT compact",
        "tick": 0.01,
        "lo": 3240,
        "hi": 3260,
        "px": 600,
        "G": 40,
        "sL": 2,
        "sM": 10,
        "labels": 11,
        "spacing": None,
    },
    {
        "name": "SOLUSDT compact",
        "tick": 0.001,
        "lo": 150.2,
        "hi": 152.6,
        "px": 600,
        "G": 40,
        "sL": 0.2,
        "sM": 1.0,
        "labels": 13,
        "spacing": None,
    },
    {
        "name": "BTCUSDT dense",
        "tick": 0.5,
        "lo": 63900,
        "hi": 64300,
        "px": 600,
        "G": 32,
        "sL": 25,
        "sM": 50,
        "labels": 17,
        "spacing": 38,
    },
]
TIME_LADDER_MIN = [
    1 / 60,
    2 / 60,
    5 / 60,
    10 / 60,
    15 / 60,
    30 / 60,
    1,
    2,
    5,
    10,
    15,
    30,
    60,
    120,
    180,
    360,
    720,
    1440,
    2880,
    10080,
    43200,
    129600,
    525600,
]
TIME_LADDER_NAMES = [
    "1 s",
    "2 s",
    "5 s",
    "10 s",
    "15 s",
    "30 s",
    "1 m",
    "2 m",
    "5 m",
    "10 m",
    "15 m",
    "30 m",
    "1 h",
    "2 h",
    "3 h",
    "6 h",
    "12 h",
    "1 d",
    "2 d",
    "1 w",
    "1 M",
    "3 M",
    "1 y",
]
TIME_CASES: list[dict[str, Any]] = [
    # px per bar, bars in view, expected step, spacing (E11-D02 §5.4 :194-199; 1200 px, G 80)
    {"px": 50, "bars": 24, "step": "2 m", "spacing": 100},
    {"px": 12, "bars": 100, "step": "10 m", "spacing": 120},
    {"px": 3, "bars": 400, "step": "30 m", "spacing": 90},
    {"px": 0.5, "bars": 2400, "step": "3 h", "spacing": 90},
    {"px": 0.05, "bars": 24000, "step": "2 d", "spacing": 144},
    {"px": 200, "bars": 6, "step": "1 m", "spacing": 200},
]


def price_ladder(tick: float) -> list[float]:
    out: list[float] = []
    for n in range(-3, 8):
        for m in (1, 2, 5):
            out.append(round(m * 10**n * tick, 6))
    return sorted(set(out))


def is_round(v: float) -> bool:
    for k in range(-4, 8):
        for m in (1, 5):
            if abs(v - m * 10**k) < 1e-9:
                return True
    return False


def derive_price(case: dict[str, Any]) -> dict[str, Any]:
    rng = case["hi"] - case["lo"]
    slots = int(case["px"] // case["G"])
    ideal = rng / slots
    s_l = next(v for v in price_ladder(case["tick"]) if v >= ideal - 1e-9)
    s_m = next(
        v
        for v in sorted({m * 10**k for k in range(-4, 8) for m in (1, 5)})
        if v >= 2 * s_l - 1e-9 and abs((v / s_l) - round(v / s_l)) < 1e-9
    )
    labels = round(rng / s_l) + 1
    spacing = round(case["px"] / (rng / s_l))
    return {
        "name": case["name"],
        "ideal": round(ideal, 3),
        "sL": s_l,
        "sM": s_m,
        "labels": labels,
        "spacing": spacing,
        "expected": {k: case[k] for k in ("sL", "sM", "labels", "spacing")},
        "agree": (
            abs(s_l - case["sL"]) < 1e-9
            and abs(s_m - case["sM"]) < 1e-9
            and labels == case["labels"]
            and (case["spacing"] is None or spacing == case["spacing"])
        ),
    }


def derive_time(
    case: dict[str, Any], width: int = 1200, g: int = 80, bar_min: float = 1
) -> dict[str, Any]:
    """The step picked for 1 m bars: sub-minute steps exist only below a one-minute interval
    (E11-D02 §5.2 :176), so the ladder starts at the bar interval."""
    px = case["px"]
    idx = next(
        i
        for i, step in enumerate(TIME_LADDER_MIN)
        if step >= bar_min - 1e-9 and step * px >= g - 1e-9
    )
    name = TIME_LADDER_NAMES[idx]
    spacing = round(TIME_LADDER_MIN[idx] * px)
    bars = round(width / px)
    return {
        "px": px,
        "bars": bars,
        "step": name,
        "spacing": spacing,
        "expected": {k: case[k] for k in ("bars", "step", "spacing")},
        "agree": bars == case["bars"] and name == case["step"] and spacing == case["spacing"],
    }


def derive_legend(pane: int = 600, row: int = 24, series: int = 13) -> dict[str, Any]:
    shown = max(3, int(0.3 * pane // row))
    return {
        "pane": pane,
        "row": row,
        "series": series,
        "shown": shown,
        "more": series - shown,
        "agree": shown == 7 and series - shown == 6,
    }


def behaviour() -> dict[str, Any]:
    prices = [derive_price(c) for c in PRICE_CASES]
    times = [derive_time(c) for c in TIME_CASES]
    legend = derive_legend()
    return {
        "const": const(),
        "price_cases": prices,
        "time_cases": times,
        "legend": legend,
        "time_ladder_steps": len(TIME_LADDER_MIN),
        "disagreements": [p["name"] for p in prices if not p["agree"]]
        + [f"{t['px']} px/bar" for t in times if not t["agree"]]
        + ([] if legend["agree"] else ["legend 600 px"]),
        "rules": 6,
        "proposed_rules": 1,
    }


# ---- 3 key map (E11-D07 §7.1 + announcements)
# id | the conflict's key(s) | the resolution applied here as PROPOSED | owner -> target | line
K_ROWS_TABLE = """
K1 | `Ctrl+Alt+←/→` (shipped Workspace panel cycle) | re-home the panel cycle to `Ctrl+\\` (and
  `Ctrl+Shift+\\`), or scope `validWhen` to "no grid or table has focus" | keymap owner (E10-S02 /
  E49-T04) → E10-S02; E11-S14 | :335
K2 | plot and grid `←/→`, `Shift+←/→`, `Space` vs Replay | register the chart's cursor commands with
  `shadows: [replay.*]`; the grid consumes `←/→` and `Space` in replay | E11-S13 #520; E11-S14 #521
  / E26 | :336
K3 | `Esc` on every chart stop vs `chart.cancel_drawing` | one `Esc` ladder registered once: cancel
  a drawing → dismiss → return to the plot cursor → propagate | E11-S13 #520 | :337
K4 | `+/-`, `Alt+G`, `Alt+↑/↓`, `Ctrl+A` (disjoint-context reuse) | reciprocal `shadows` with a
  rationale at registration; `Alt+G` conditional on O13, else `Ctrl+Shift+G` | E11-S13 #520 (+
  keymap owner) | :338
K5 | `Alt+1..4` (`05` drawing row) | dead under Global `Alt+1..9`; E14-D02 AD-1 chose letters; A-05
  amends `05:58` | `05` owner (#2701) | :339
K6 | `Alt+←/→` step tick (`26` §3.11) | the chart never binds `Alt+arrows`; step tick is the shipped
  Replay `Shift+←/→`; A-21 amends `26` §3.11 | `26` owner (#2701) | :340
K7 | single letters and digits (`F`, `1..9`, `B`, `R`, `H`, `P`, `Shift+R`, `-`) vs browse mode |
  reachable in focus / interaction mode; the root's hint and the `Ctrl+/` sheet say so; R-T2
  verifies | E11-S13 #520; E11-Q05 | :341
K8 | arrows and `Shift+arrows` vs VoiceOver Quick Nav | Quick Nav off or interaction with the chart
  group; no key changes; R-T2 | E11-Q05 | :342
K9 | the `Alt+<letter>` family (12 keys) under E11-D01 O13 | conditional, not failed: the shell
  removes the menu or every `Alt` chord stays as designed with the hazard; `Ctrl+Shift+G` is free |
  owner (O13) → E11-D01 O13 | :343
K10 | `05` §3.2 rows the registry implements under another key (`Backspace` → `Del`, `Ctrl+\\` →
  `Ctrl+Alt+←/→` …) | the shipped key wins where it shipped; A-02 / A-13 amend `05` | `05` owner
  (#2701); keymap owner | :344
K11 | the specified-but-unregistered keys | one G row each (G-01…G-08); S13 / S14 register with
  `visibleControl` and declared shadows; E10-S02 the Accessibility rows | E11-S13 / S14; E10-S02 |
  :345
K12 | SCR-049 `Ctrl+Alt+1..9` | register it (G-07); the `Ctrl+Alt` family is then the readers' table
  chord plus this one; R-T2 confirms | E15 / SCR-049 owner; keymap owner | :346
K13 | `Alt+T` | VERIFIED clear in all four lists (0 fixture rows, not reserved, not shipped — G-01);
  the bare-`Alt` hazard of K9 applies; R-T3 | E11-Q05 | :347
K14 | the bar high / low chord | PROPOSED `Ctrl+Shift+↑/↓` = cursor level to the bar's high / low;
  `Ctrl+↑/↓` stays unbound (Q-03) | E11-S13 #520; owner (Q-03) | :348
K15 | browser defaults absent from `reserved-keys.json` (`Ctrl+A`, `Ctrl+C`, `Ctrl+Shift+D`,
  `Ctrl+=` / `-`, `Ctrl+Shift+G`) | the registry owner verifies them in the Electron shell; A-07
  names the file in `05` §3.3 item 4 | keymap owner (E10-S02 / E49-T04) | :349
"""

# context | stop | key (as E11-D07 types it) | announcement (verbatim where one exists) | source
ANNOUNCE_TABLE = """
Chart | plot | ← | the landing bar's full summary on a lone press; the short form (time, close)
  while held; "first bar" / "last bar" once at an edge | E06-D03 D5 :105
Chart | plot | → | the landing bar's full summary on a lone press; the short form (time, close)
  while held; "first bar" / "last bar" once at an edge | E06-D03 D5 :105
Chart | plot | Shift+← | as `←` (ten bars; a held key coalesces in the short form) | E06-D03 D5
  :105, D6 :107
Chart | plot | Shift+→ | as `→` (ten bars; a held key coalesces in the short form) | E06-D03 D5
  :105, D6 :107
Chart | plot | PageUp | as `Shift+←` (the ±10 alias; one hotkey-map row) | E06-D03 D6 :107; E11-D02
  §7.3 :322
Chart | plot | PageDown | as `Shift+→` (the ±10 alias; one hotkey-map row) | E06-D03 D6 :107;
  E11-D02 §7.3 :322
Chart | plot | ↑ | the level summary of the cursor bar's price level (footprint / profile) | E06-D03
  D6 :107
Chart | plot | ↓ | the level summary of the cursor bar's price level (footprint / profile) | E06-D03
  D6 :107
Chart | plot | Home | the full summary at the oldest loaded bar; "first bar" once | E06-D03 D5 :105,
  D6 :107
Chart | plot | End | the full summary at the latest bar; "last bar" once; follow resumes | E06-D03
  D5 :105, D6 :107
Chart | plot | Enter | "Expanded, N levels" | E06-D03 D6 :107
Chart | plot | Esc | none — collapses the detail; not consumed when nothing is open (silent by
  design) | E06-D03 D6 :107
Chart | plot | + | none (silent by design — a viewport change surfaces only through
  `onA11yWindowChange`) | E06-D03 D6 :107; `26` §3.11 :279
Chart | plot | - | none (silent by design — a viewport change surfaces only through
  `onA11yWindowChange`) | E06-D03 D6 :107; `26` §3.11 :279
Chart | plot | Space | none (silent by design — a pan-drag modifier; not consumed in replay) |
  E06-D03 D6 :107; `26` §3.11 :279
Chart | plot | Alt+← | n/a — the chart never binds `Alt+arrows`; step tick is Replay `Shift+←/→`
  (K6, A-21) | E11-D07 §7.3 K6 :340
Chart | plot | Alt+→ | n/a — the chart never binds `Alt+arrows`; step tick is Replay `Shift+←/→`
  (K6, A-21) | E11-D07 §7.3 K6 :340
Chart | plot | Ctrl+Shift+↑ | not stated — PROPOSED chord (K14); the `↑/↓` level form would apply if
  adopted (G-row) | E11-D07 §7.3 K14 :348
Chart | plot | Ctrl+Shift+↓ | not stated — PROPOSED chord (K14); the `↑/↓` level form would apply if
  adopted (G-row) | E11-D07 §7.3 K14 :348
Chart | * | Alt+T | "Data table, row k of N" (the table opens; from the grid "Chart" + the clamp
  sentence from a stale table) | E06-D03 D5 :105; E11-D04 §17.1 :522
Chart | * | Alt+G | none by the chart — the dialog's name (AT); initial focus the Date input |
  E11-D03 §12.2 :471
Chart | * | Ctrl+Shift+G | none by the chart — the dialog's name (AT); initial focus the Date input
  (the O13 fallback) | E11-D03 §12.2 :471
Chart | * | Ctrl+Shift+D | none by the chart — the overlay's region (`role="region"`, polite 2 Hz
  values; F-07 routes the cadence) | E11-D02 §9 :383
Chart | * | Ctrl+\\ | none by the chart — the next region's name (AT) | E11-D02 §12 :654
Chart | * | Ctrl+Alt+1..9 | "Chart 2 of 4, group A" (the cell's name) | E11-D02 §8 :377; E11-D07
  §9.1 ST21 :420
Chart | * | Alt+C | n/a — a `05` row bound by no E11 design (G-06) | E11-D07 §15.4 G-06 :685
Chart | * | Alt+↑ | n/a — a `05` row bound by no E11 design (G-06); CMP-056 reorder is the Picker
  context | E11-D07 §15.4 G-06 :685
Chart | * | Alt+↓ | n/a — a `05` row bound by no E11 design (G-06); CMP-056 reorder is the Picker
  context | E11-D07 §15.4 G-06 :685
Chart | * | H | n/a — a `05` row bound by no E11 design (G-06) | E11-D07 §15.4 G-06 :685
Chart | * | P | n/a — a `05` row bound by no E11 design (G-06) | E11-D07 §15.4 G-06 :685
Chart | * | Alt+1..4 | n/a — dead under Global `Alt+1..9`; E14-D02 AD-1 chose letters (K5, A-05) |
  E11-D07 §7.3 K5 :339
Chart | * | Backspace | n/a — the shipped key is `Del` (`chart.delete_drawing`; K10) | E11-D07 §7.3
  K10 :344
Chart | price-axis | ↑ | first engagement "Price scale locked", then the range only: "63,920 to
  64,280" | E11-D02 §7.1 :254
Chart | price-axis | ↓ | first engagement "Price scale locked", then the range only: "63,920 to
  64,280" | E11-D02 §7.1 :254
Chart | price-axis | Shift+↑ | as `↑` (the 25 % step) | E11-D02 §7.1 :255
Chart | price-axis | Shift+↓ | as `↓` (the 25 % step) | E11-D02 §7.1 :255
Chart | price-axis | PageUp | the range | E11-D02 §7.1 :256
Chart | price-axis | PageDown | the range | E11-D02 §7.1 :256
Chart | price-axis | Home | "Price scale: auto" | E11-D02 §7.1 :257
Chart | price-axis | Shift+F10 | the menu's own ("Price scale menu", by the AT) | E11-D02 §7.1 :258;
  E11-D03 §12.1 :458
Chart | price-axis | Esc | the cursor's full summary | E11-D02 §7.1 :259
Chart | lock-badge | Enter | "Price scale: auto" | E11-D02 §7.1 :261
Chart | lock-badge | Space | "Price scale: auto" | E11-D02 §7.1 :261
Chart | time-axis | ← | the new visible range "07:40 to 13:57"; "Paused at 13:47" once on pausing |
  E11-D02 §7.2 :284
Chart | time-axis | → | the new visible range "07:40 to 13:57"; "Paused at 13:47" once on pausing |
  E11-D02 §7.2 :284
Chart | time-axis | Shift+← | as `←` (one full width) | E11-D02 §7.2 :284
Chart | time-axis | Shift+→ | as `→` (one full width) | E11-D02 §7.2 :284
Chart | time-axis | + | "12 pixels per bar"; "Zoom limit" once at a bound | E11-D02 §7.2 :285
Chart | time-axis | - | "12 pixels per bar"; "Zoom limit" once at a bound | E11-D02 §7.2 :285
Chart | time-axis | Home | "Fitted 5,000 bars" | E11-D02 §7.2 :286
Chart | time-axis | End | "Following live" | E11-D02 §7.2 :287
Chart | time-axis | Ctrl+Home | "Default spacing" | E11-D02 §7.2 :288
Chart | time-axis | Shift+F10 | the menu's ("Time scale menu", by the AT) | E11-D02 §7.2 :289;
  E11-D03 §12.1 :458
Chart | time-axis | Esc | the cursor's summary | E11-D02 §7.2 :290
Chart | cluster | ← | the segment's name ("Following live, button" / "Paused at 13:47 — resume live,
  button" / "Fit, button" / "Latest, button") | E11-D02 §7.2 :291
Chart | cluster | → | the segment's name ("Following live, button" / "Paused at 13:47 — resume live,
  button" / "Fit, button" / "Latest, button") | E11-D02 §7.2 :291
Chart | cluster | Enter | "Following live" / "Paused at 13:47" / "Fitted 5,000 bars" / "Latest bar"
  | E11-D02 §7.2 :292
Chart | cluster | Space | "Following live" / "Paused at 13:47" / "Fitted 5,000 bars" / "Latest bar"
  | E11-D02 §7.2 :292
Chart | legend | ↑ | none specified — the row's name (AT: "EMA 20, 64,003.2, hidden") | E11-D02 §7.5
  :345; E11-D05-handoff Table 3 :110
Chart | legend | ↓ | none specified — the row's name (AT: "EMA 20, 64,003.2, hidden") | E11-D02 §7.5
  :345; E11-D05-handoff Table 3 :110
Chart | legend | ← | none specified — the control's name (AT: "EMA 20 visible", stable) | E11-D02
  §7.5 :345
Chart | legend | → | none specified — the control's name (AT: "EMA 20 visible", stable) | E11-D02
  §7.5 :345
Chart | legend | Space | "EMA 20 hidden" / "EMA 20 shown" (polite) | E11-D02 §7.5 :345
Chart | legend | Enter | "EMA 20 hidden" / "EMA 20 shown"; "7 more series" on opening the popover |
  E11-D02 §7.5 :345; §12 :664
Chart | legend | Esc | none — back to the plot (the cursor's summary on landing) | E11-D02 §7.5 :345
Chart | chips | ← | name + description on focus (the chip's text and its `aria-describedby`) |
  E11-D02 §12 :667
Chart | chips | → | name + description on focus (the chip's text and its `aria-describedby`) |
  E11-D02 §12 :667
Chart | chips | Enter | none by the chart — the chip's details open (SCR-153 / the aggregation
  popover) | E11-D02 §12 :667
Chart | chips | Esc | none — dismisses the tooltip, then moves to the last-focused pane's plot
  cursor | E11-D02 §12 :667
Chart | splitter | ↑ | "Volume pane 22 percent" (once per key, not per frame) | E11-D02 §8 :361
Chart | splitter | ↓ | "Volume pane 22 percent" (once per key, not per frame) | E11-D02 §8 :361
Chart | splitter | Shift+↑ | the same ("Volume pane 22 percent") | E11-D02 §8 :362
Chart | splitter | Shift+↓ | the same ("Volume pane 22 percent") | E11-D02 §8 :362
Chart | splitter | Home | "Panes equal" | E11-D02 §8 :363
Chart | splitter | End | "Price pane 84 percent" | E11-D02 §8 :364
Chart | splitter | Esc | the cursor's summary | E11-D02 §8 :365
Chart | stub | Enter | "Volume pane collapsed" / "restored" | E11-D02 §8 :367
Chart | stub | Space | "Volume pane collapsed" / "restored" | E11-D02 §8 :367
Overlay | * | Esc | none specified — the overlay closes; focus returns to the chart | E11-D02 §9
  :383
Overlay | copy | Enter | "Diagnostics copied" | E11-D02 §9 :385; §12 :670
Overlay | copy | Space | "Diagnostics copied" | E11-D02 §9 :385; §12 :670
Grid | * | ↑ | the row: "13:58, open 64,010.0 … delta +118" | E11-D04 §17.1 :507
Grid | * | ↓ | the row: "13:58, open 64,010.0 … delta +118" | E11-D04 §17.1 :507
Grid | * | ← | the cell | E11-D04 §17.1 :508
Grid | * | → | the cell | E11-D04 §17.1 :508
Grid | * | Home | the cell | E11-D04 §17.1 :509
Grid | * | End | the cell | E11-D04 §17.1 :509
Grid | * | Ctrl+Home | the row; "Loading older bars" once per page | E11-D04 §17.1 :510
Grid | * | Ctrl+End | the row; "Following live" once | E11-D04 §17.1 :510
Grid | * | PageUp | the row | E11-D04 §17.1 :511
Grid | * | PageDown | the row | E11-D04 §17.1 :511
Grid | * | Enter | "Expanded, 38 levels" (a bar row) / the drawer's title (a level row) / "Sorted by
  delta, descending" (a header) | E11-D04 §17.1 :512\u2013514
Grid | * | Space | "Selected, 3 rows" / "Deselected" (a row); the sort text on a header | E11-D04
  §17.1 :515
Grid | * | Shift+↑ | "Selected, 7 rows" | E11-D04 §17.1 :516
Grid | * | Shift+↓ | "Selected, 7 rows" | E11-D04 §17.1 :516
Grid | * | Ctrl+A | "Selected 4,321 rows" | E11-D04 §17.1 :517
Grid | * | Ctrl+C | "Copied 12 rows, 8 columns as TSV" | E11-D04 §17.1 :518
Grid | * | Shift+F10 | the menu (its T2 write items present with their reasons) | E11-D04 §17.1
  :519; E11-D07 §9.5 :436
Grid | * | Esc | "Chart" + the bar summary on the last step | E11-D04 §17.1 :520
Grid | * | Shift+R | "Refreshed to current: row k of N"; a no-op "Already current" | E11-D04 §17.1
  :521
Grid | * | Alt+T | "Chart" (+ the clamp sentence from a stale table) | E11-D04 §17.1 :522
Picker | * | Alt+↑ | not stated — CMP-056's reorder names no announcement (G-row to the D04 owner /
  E11-S14) | E11-D04 §5.3 :221
Picker | * | Alt+↓ | not stated — CMP-056's reorder names no announcement (G-row to the D04 owner /
  E11-S14) | E11-D04 §5.3 :221
Menu | * | ↑ | item name, state ("checked" / "not checked"), description or reason (AT) | E11-D03
  §12.1 :459
Menu | * | ↓ | item name, state ("checked" / "not checked"), description or reason (AT) | E11-D03
  §12.1 :459
Menu | * | Home | none (silent by design — "—") | E11-D03 §12.1 :460
Menu | * | End | none (silent by design — "—") | E11-D03 §12.1 :460
Menu | * | Enter | the state change in the "Price scale: …" grammar, or nothing for a disabled item
  | E11-D03 §12.1 :462
Menu | * | Space | the state change in the "Price scale: …" grammar, or nothing for a disabled item
  | E11-D03 §12.1 :462
Menu | * | Esc | none (silent by design — "—"); focus returns to the opening stop | E11-D03 §12.1
  :463
Menu | * | Tab | the next stop's name | E11-D03 §12.1 :464
Dialog | * | Tab | none specified — the focused field's name (AT) inside the trap | E11-D03 §12.2
  :472
Dialog | * | Enter | one polite announcement: "Jumped to 15 Sep 13:42 UTC — close 64,210, delta
  \u2212128. Following paused." (a gap landing: "No data at 02:12 — landed on 02:15, close …") |
  E11-D03 §7.5 :360
Dialog | * | Space | none specified — a segment toggles / a button presses (AT reads the state) |
  E11-D03 §12.2 :476
Dialog | * | Esc | none — chart and cursor unchanged; the live region says nothing | E11-D03 §7.5
  :356; §12.2 :477
Dialog | * | PageUp | none specified — the calendar moves by month (AT reads the day) | E11-D03
  §12.2 :474
Dialog | * | PageDown | none specified — the calendar moves by month (AT reads the day) | E11-D03
  §12.2 :474
Chart | * | Alt+L | E14-D02's (its key table; not restated here) | E14-D02 :62
Chart | * | Alt+H | E14-D02's (its key table; not restated here) | E14-D02 :62
Chart | * | Alt+O | E14-D02's (its key table; not restated here) | E14-D02 :62
Chart | * | Alt+R | E14-D02's (its key table; not restated here) | E14-D02 :62
Chart | * | Alt+D | E14-D02's (its key table; not restated here) | E14-D02 :62
Chart | * | Ctrl+M | E14-D02's ("Crosshair magnet: …" is the readout magnet's — E11-D02 :302 — not
  this toggle's) | E14-D02 :62, :65
"""


def k_rows() -> list[dict[str, str]]:
    cols = ("id", "keys", "resolution", "owner", "line")
    return [dict(zip(cols, r, strict=True)) for r in rows(K_ROWS_TABLE)]


def announcements() -> dict[tuple[str, str, str], tuple[str, str]]:
    out: dict[tuple[str, str, str], tuple[str, str]] = {}
    for ctx, stop, key, text, src in rows(ANNOUNCE_TABLE):
        out[(ctx, stop, key)] = (text, src)
    return out


ARROWS = ("←", "→", "↑", "↓")
# G-row of E11-D07 §15.4 for each specified-but-unregistered key (K11).
G_FOR_KEY = {
    "Alt+T": "G-01",
    "Shift+R": "G-02",
    "Alt+G": "G-03",
    "Ctrl+Shift+G": "G-03",
    "Ctrl+\\": "G-04",
    "Alt+C": "G-06",
    "Alt+↑": "G-06",
    "Alt+↓": "G-06",
    "H": "G-06",
    "P": "G-06",
    "+": "G-06",
    "-": "G-06",
    "Home": "G-06",
    "End": "G-06",
    "Space": "G-06",
    "Ctrl+Shift+↑": "G-18",
    "Ctrl+Shift+↓": "G-18",
}


def k_ids_for(key: str, ctx: str, stop: str, action: str, src: str) -> list[str]:
    """The E11-D07 §7.3 conflict rows that touch one atomic binding (typed rules, K1…K15)."""
    ks: list[str] = []
    bare = key.replace("Shift+", "")
    if ctx == "Chart" and key == "Ctrl+\\":
        ks.append("K1")
    if (ctx in ("Chart", "Grid")) and key in ("←", "→", "Shift+←", "Shift+→", "Space"):
        ks.append("K2")
    if ctx == "Chart" and key == "Esc":
        ks.append("K3")
    if (ctx == "Chart" and key in ("+", "-", "Alt+G", "Alt+↑", "Alt+↓")) or (
        ctx == "Picker" and key in ("Alt+↑", "Alt+↓")
    ):
        ks.append("K4")
    if ctx == "Grid" and key == "Ctrl+A":
        ks.append("K4")
    if (
        key.startswith("Alt+")
        and key[4:] in "1234"
        and src.endswith("05-accessibility-standard.md")
    ):
        ks.append("K5")
    if key in ("Alt+←", "Alt+→"):
        ks.append("K6")
    if key in ("H", "P", "Shift+R", "-"):
        ks.append("K7")
    if bare in ARROWS and ctx in ("Chart", "Grid", "Menu", "Dialog"):
        ks.append("K8")
    if re.fullmatch(r"Alt\+[A-Z]", key):
        ks.append("K9")
    if key == "Backspace":
        ks.append("K10")
    if key.startswith("Ctrl+Alt+") and key[-1].isdigit():
        ks.append("K12")
    if key == "Alt+T":
        ks.append("K13")
    if key in ("Ctrl+Shift+↑", "Ctrl+Shift+↓"):
        ks.append("K14")
    if key in ("Ctrl+A", "Ctrl+C", "Ctrl+Shift+D", "Ctrl+Shift+G"):
        ks.append("K15")
    return ks


def short_source(src: str) -> str:
    """E11-D07's source file string as the pack cites it."""
    if "E14-D02" in src:
        return "E14-D02"
    name = src.rsplit("/", 1)[-1].replace(".md", "")
    if name[:2].isdigit():
        return f"`{name[:2]}`"
    if name.startswith("e11-chart-navigation-research"):
        return "E11-D01"
    return name


def keymap_rows() -> dict[str, Any]:
    """E11-D07's 134 atomic bindings with the pack's columns; None when the D07 tool is absent."""
    if d07 is None:
        return {"absent": True, "rows": [], "unregistered": [], "k_rows": k_rows()}
    km = d07.keymap_section()
    unreg_keys: dict[tuple[str, str, str], str] = {}
    for s in km["unregistered_design"]:
        m = re.match(r"^(.+?) \((\w+)/([^,]+), (.+?):(\d+)\)$", s)
        if m:
            unreg_keys[(m.group(1), m.group(2), m.group(3))] = s
    shipped = {(s["key"], s["context"]): s["id"] for s in d07.shipped_bindings(d07.load_keymap())}
    ann = announcements()
    out: list[dict[str, Any]] = []
    missing_ann: list[str] = []
    n = 0
    for key, ctx, stop, action, src, line in d07.DESIGN_BINDINGS:
        text_src = ann.get((ctx, stop, key))
        for atomic in d07.expand_keys(key):
            n += 1
            kid = f"K-{n:03d}"
            if text_src is None:
                missing_ann.append(f"{kid} {atomic} {ctx}/{stop}")
                text, asrc = "—", "—"
            else:
                text, asrc = text_src
            src_short = short_source(src)
            unreg = unreg_keys.get((atomic, ctx, stop))
            if unreg:
                g = G_FOR_KEY.get(atomic, "G-08")
                if atomic in ("Alt+←", "Alt+→"):
                    reg = "no — never bound (K6; A-21)"
                elif atomic == "Backspace":
                    reg = "no — the shipped key is `Del` (K10)"
                elif atomic.startswith("Ctrl+Alt+"):
                    reg = "no — unregistered (G-07)"
                else:
                    reg = f"no — unregistered ({g})"
            elif action.startswith("E14"):
                reg = "E14-D02's (merged; not an E11 registration)"
            elif (atomic, ctx) in shipped:
                reg = f"shipped `{shipped[(atomic, ctx)]}` holds the key (K3 ladder)"
            else:
                reg = "n/a — APG / focus-scoped key, not a registry entry (`05` §3.3 item 1(3))"
            ks = k_ids_for(atomic, ctx, stop, action, src)
            if unreg and "K11" not in ks:
                ks.append("K11")
            if src.endswith("e11-chart-navigation-research.md"):
                status = "PROPOSED (K14; owner Q-03)"
            elif action.startswith("E14"):
                status = "decided — E14-D02 (merged)"
            elif atomic in ("Alt+←", "Alt+→"):
                status = "superseded (K6 — A-21 PROPOSED to the `26` owner)"
            elif src.endswith("05-accessibility-standard.md"):
                status = "a `05` row — unregistered or dead (K5 / K10 / G-06)"
            elif unreg:
                gid = "G-07" if atomic.startswith("Ctrl+Alt+") else G_FOR_KEY.get(atomic, "G-08")
                status = f"decided; registration pending ({gid})"
            else:
                status = "decided"
            out.append(
                {
                    "id": kid,
                    "key": atomic,
                    "context": ctx,
                    "stop": stop,
                    "action": action,
                    "announcement": text,
                    "ann_src": asrc,
                    "registered": reg,
                    "k": ", ".join(ks) if ks else "—",
                    "status": status,
                    "source": f"{src_short} :{line}",
                }
            )
    return {
        "absent": False,
        "rows": out,
        "unregistered": km["unregistered_design"],
        "alt_family": km["alt_family"],
        "shipped_commands": km["shipped_commands"],
        "shipped_bindings": km["shipped_bindings"],
        "reserved_total": km["reserved_total"],
        "design_bindings": km["design_bindings"],
        "design_literals": km["design_literals"],
        "missing_announcements": missing_ann,
        "k_rows": k_rows(),
    }


# ---- 4 motion (E11-D06 §7)
def motion_rows() -> list[list[str]]:
    data = md_table(read(D06), "## 7. The motion spec table", "## 8. The safety rows")
    return [r for r in data if r and re.fullmatch(r"\d+", r[0])]


def motion_header() -> list[str]:
    data = md_table(read(D06), "## 7. The motion spec table", "## 8. The safety rows")
    return data[0]


def motion_coverage(data: list[list[str]]) -> dict[str, Any]:
    """Rows that animate under motion-safe: a duration cell that names a motion token or a
    millisecond value other than 0 ms / 1 frame, or the coast's decay (E11-D06 §7 :353)."""
    animate: list[str] = []
    for r in data:
        dur = r[4].lower()
        timed = "motion.duration" in dur or "τ" in dur or re.search(r"\b(\d{2,4})\s*ms", dur)
        still = dur.startswith("0 ms") or "1 frame" in dur or "instant" in dur
        if timed and not still:
            animate.append(r[0])
    return {"rows": len(data), "animate_under_safe": len(animate), "animate_rows": animate}


# ---- 5 token mapping (E11-D05 §4, the specs' tokens)
# alias | primitive token per theme (dark / light / hc) | E11-D05 line (typed from §4.1 / §4.1b)
ALIAS_TABLE = """
color.chart.axis | color.text.tertiary | color.text.tertiary | color.text.tertiary | :77
color.chart.grid.major | color.border.default | color.border.default | color.border.default | :78
color.chart.grid.minor | color.grid.line | color.grid.line | off (CR-2: opacity.grid.minor 0.0 or
  color.surface.canvas) | :79
color.chart.crosshair | color.crosshair | color.crosshair | color.crosshair | :80
color.chart.watermark | color.border.default | color.border.default | color.border.default | :81
color.chart.pane.bg.default | color.surface.canvas | color.surface.canvas | color.surface.canvas |
  :82
color.chart.pane.bg.focused | color.surface.canvas | color.surface.canvas | color.surface.canvas |
  :83
color.chart.replay.border | palette.purple.400 | palette.purple.600 | palette.purple.400 | :84
color.chart.boundary | color.text.tertiary | color.text.tertiary | color.text.tertiary | :92
color.chart.rule | color.border.default | color.border.default | color.border.default | :93
color.chart.hatch.texture | color.border.strong | color.border.strong | color.border.strong | :94
color.chart.pill.bg | color.surface.raised | color.surface.raised | color.surface.raised | :95
color.chart.pill.border | color.border.strong | color.border.strong | color.border.strong | :96
color.chart.pill.text.default | color.text.primary | color.text.primary | color.text.primary | :97
color.chart.pill.text.inverse | color.text.inverse | color.text.inverse | color.text.inverse | :98
color.chart.pill.text.on-marker | color.text.on-action | color.text.on-action | color.text.on-action
  | :99
color.chart.marker.goto | color.action.primary.default | color.action.primary.default |
  color.action.primary.default | :100
color.chart.focus.ring | color.focus.ring | color.focus.ring | color.focus.ring | :101
"""
# Names that are not tokens at the base, carried as gaps (change requests) with their owner row.
GAP_NAMES = {
    "opacity.grid.minor": "E11-D02 CR-1 / E11-D05 CR-2 (a metric, not a colour)",
    "opacity.grid.major": "E11-D02 CR-1 / E11-D05 CR-2 (a metric, not a colour)",
    "CR:color.text.buy": "E11-D02 CR-5 / E11-D05 §4.3",
    "CR:color.text.sell": "E11-D02 CR-5 / E11-D05 §4.3",
    "CR:color.border.field": "E11-D03 D03-CR-5",
    "CR:color.status.danger.strong": "E11-D04 CR-D04-14 (the light candidate)",
    "CR:font.feature.tabularNums": "E11-D04 CR-D04-11 (`16` §2.2 planned)",
    "CR:motion.spin": "E11-D04 CR-D04-12 (`15` CMP-014 names it)",
    "font.mono": "`15` naming drift → `font.family.mono` (E11-D05 CR-8)",
}
REGISTRY_IDS = {"pattern.", "glyph.", "dash.", "indicator."}
TOKEN_NAME_RE = re.compile(
    r"`((?:CR:)?(?:color|size|space|type|radius|opacity|font|motion|elevation"
    r"|pattern|glyph|dash|indicator)\.[A-Za-z0-9.*-]+)`"
)

# T-id order | element | surface (GL / DOM) | slot(s) | consumer | measured role | source
TOK_ROWS_LITERAL = """
pane background (every pane, gutters, strip) | GL | `color.chart.pane.bg.default` (=
  `color.surface.canvas`) | `theme-uniforms.json` uniform (E11-T04) | surface | E11-D05 §4.1 :82;
  E11-D02 §7.6 :349
focused pane background (identical by design) | GL | `color.chart.pane.bg.focused` (=
  `color.surface.canvas`) | uniform | surface | E11-D05 §4.1 :83
minor gridline | GL | `color.chart.grid.minor` (= `color.grid.line`); `opacity.grid.minor` 1.0 / 1.0
  / 0.0 | uniform + `EngineTheme.metrics` | decorative | E11-D05 §4.1 :79; E11-D02 §4.1 :137
major gridline | GL | `color.chart.grid.major` (= `color.border.default`); `opacity.grid.major` |
  uniform + metric | decorative | E11-D05 §4.1 :78; E11-D02 §4.1 :138
boundary lines, band edges, mark line, grip ink, `pattern.hatch.absent` | GL |
  `color.chart.boundary` (= `color.text.tertiary`) | uniform | non-text | E11-D05 §4.1b :92
hatch texture (`pattern.hatch.gap`) | GL | `color.chart.hatch.texture` (= `color.border.strong`);
  `pattern.hatch.gap` (registry id) | uniform; `patterns.ts` | decorative | E11-D05 §4.1b :94; §7
  :315
axis tick labels, mode tag, zone tag | GL | `color.chart.axis` (= `color.text.tertiary`) | uniform |
  text | E11-D05 §4.1 :77; E11-D02 §7.1 :244
axis rule, strip rule, splitter hairline | GL | `color.chart.rule` (= `color.border.default`) |
  uniform | decorative | E11-D05 §4.1b :93
crosshair lines | GL | `color.chart.crosshair` (= `color.crosshair`) | uniform | non-text | E11-D05
  §4.1 :80; E11-D02 §7.3 :298
remote crosshair (linked chart) | GL | `color.chart.crosshair` at `opacity.muted` | uniform + metric
  | non-text | E11-D02 §7.2 :275
watermark | GL | `color.chart.watermark` (= `color.border.default`); `font.family.ui`;
  `font.weight.semibold` | uniform; the SDF atlas | decorative | E11-D05 §4.1 :81; E11-D02 §7.6 :349
replay frame and virtual-now line | GL | `color.chart.replay.border` (PROPOSED name, CR-3; hue O-A)
  | uniform | non-text | E11-D05 §4.1 :84; E11-D02 §10 :414
neutral GL pills (mark `M`, index `I`, remote time pill) | GL | `color.chart.pill.bg` +
  `color.chart.pill.border` + `color.chart.pill.text.default` | uniform | text on a surface |
  E11-D05 §4.1b :95\u201397
crosshair pills and the last-price pill text | GL | `color.chart.pill.text.inverse` (=
  `color.text.inverse`); `radius.xs`; 4 px padding | uniform | text | E11-D05 §4.1b :98
go-to-date marker line and pill | GL | `color.chart.marker.goto` (= `color.action.primary.default`);
  text `color.chart.pill.text.on-marker` | uniform | non-text / text | E11-D05 §4.1b :99\u2013100
keyboard cursor column (D10) and its halo | GL | `color.chart.focus.ring` (= `color.focus.ring`);
  halo `color.chart.pane.bg.default` | uniform | non-text | E11-D05 §4.1b :101; E06-D03 D10 :176
last-price pill fill and price line, bar up | GL | `color.candle.up` | uniform | non-text | E11-D02
  §7.1 :244; E11-D05 §4.2 :109
last-price pill fill and price line, bar down | GL | `color.candle.down` | uniform | non-text |
  E11-D02 §7.1 :244; E11-D05 §4.2 :110
series neutral (wick, doji, forming outline, gap edges, zero line) | GL | `color.candle.wick` |
  uniform | non-text | E11-D05 §4.2 :111
CVD-safe up / down (the directional remap) | GL | `color.cvd.buy` / `color.cvd.sell` | uniform
  (`CVD_SOURCE`) | non-text | E11-D05 §4.2 :112
delta ramp ends | GL | `color.sell.default` / `color.buy.default` | LUT (`ColorLut.ts`) | non-text |
  E11-D05 §4.2 :113
delta ramp first visible stops | GL | `color.heatmap.ask.1` / `color.heatmap.bid.1` (registered,
  exempted — CR-9) | LUT | non-text | E11-D05 §4.2 :114
stale dim (data-ink \u00d7 0.85) | GL | no token — the colour uniforms / LUTs multiplied at state
  entry | uniform upload | — | E11-D02 §10 :410, §13 :683; E11-D06 D13 :221
replay future dim quad | GL | `color.surface.app` at `opacity.scrim` | one blended quad | — |
  E11-D02 §7.2 :276, §13 :684
maintenance window, coverage gap | GL | `pattern.hatch.gap` (registry id, D05 CR-4); inks per the
  two rows above | `patterns.ts` | encoding | E11-D05 §7 :315; E11-D02 §7.2 :272
estimated data (cells, series), imbalance outline, delta notch | GL | `pattern.hatch.estimated`,
  `pattern.dashed.estimated`, `pattern.outline.imbalance`, `glyph.notch.delta`;
  `color.footprint.imbalance` | `patterns.ts` | encoding | E11-D05 §7 :313\u2013319
density record (`cellPadPx`, `fontSizeClass`, `axisFontSizeClass`, `lodBias`) | GL |
  `density.chart.<mode>` (PROPOSED home, D05 Q7) carried as `EngineTheme.metrics`; the class →
  `type.num.xs` / `type.num.sm` / `type.num.base` | metrics | — | E11-D05 §6 :283\u2013287, §6.1
  :297; E11-D02 §6 :214\u2013218
toolbar row, status row, collapsed stub fill | DOM | `color.surface.raised` | CSS custom property |
  surface | E11-D02 §7.6 :349, §8 :367
legend label, focused pane label, readout values | DOM | `color.text.primary`; `type.ui.label` /
  `type.ui.body`; `type.num.*` values | CSS | text | E11-D02 §7.5 :339
legend value label, loading text | DOM | `color.text.secondary` | CSS | text | E11-D02 §7.2 :273,
  §7.5 :339
hidden legend row, unfocused pane label | DOM | `color.text.tertiary` (never `color.text.disabled`)
  | CSS | text | E11-D02 §7.5 :343, §8 :373
pane focus bar | DOM | `color.action.primary.default` (2 px) | CSS | non-text | E11-D02 §8 :373
focus ring on surrogates (CMP-039) | DOM | `color.focus.ring` (2 px, 2 px offset); halo
  `color.surface.canvas` | CSS | non-text | E11-D02 §7 :240; E11-D05 §9.1 :436
tooltip box | DOM | `color.surface.overlay` + `color.border.default`; `radius.card`;
  `elevation.popover` | CSS | surface | E11-D02 §7.3 :304\u2013307; `15` CMP-197 :2370
tooltip title, labels and values | DOM | `color.text.secondary` (title, labels);
  `color.text.primary` (values); `type.ui.caption` / `type.ui.label`; `type.num.*`; `space.inset.xs`
  / `space.inset.sm` / `space.inset.md` per density | CSS | text | E11-D02 §7.3 :308\u2013309
coloured indicator values (E13) | DOM | `CR:color.text.buy` / `CR:color.text.sell` — until minted,
  values stay `color.text.primary` | CSS | text | E11-D02 §11.4 CR-5 :643; E11-D05 §4.3 :119
chips and badges (text on a neutral pill) | DOM | `color.text.primary` on `color.surface.raised`;
  `color.border.default`; `radius.badge`; `type.ui.caption` / `type.num.sm` | CSS | text | E11-D02
  §10 :422
stale chip | DOM | `color.data-confidence.stale.surface` / `.stale.text` / `.stale.indicator` | CSS
  | text / non-text | E11-D02 §10 :410
feed chips (reduced rate, reconnecting, offline) | DOM | canvas-filled pill `color.surface.canvas` +
  `color.border.default`; dots `color.status.info.strong`,
  `color.data-confidence.reconnecting.indicator`, `color.data-confidence.disconnected.indicator` |
  CSS | non-text | E11-D02 §10 :411, :413
disconnected scrim and strip | DOM | `color.surface.app` at `opacity.scrim`; strip
  `color.surface.raised` + `color.text.primary` + `color.data-confidence.disconnected.indicator` |
  CSS | text / surface | E11-D02 §10 :413
REPLAY chip | DOM | `color.text.primary` on `color.surface.raised`; 2 px border
  `color.chart.replay.border` | CSS | text | E11-D02 §10 :414
env badge (CMP-075) | DOM | `color.text.primary`; border `color.env.demo` / `color.env.live`; LIVE
  rule `color.env.live`; `font.weight.medium` / `font.weight.bold` | CSS | text / non-text | E11-D02
  §10 :415
corner badge (reduced detail) | DOM | `color.surface.raised` + `color.text.primary`; glyph
  `color.status.warning.strong` | CSS | text / non-text | E11-D02 §10 :416
aggregation chip | DOM | `color.surface.raised` + `color.border.default` + `color.text.primary` |
  CSS | text | E11-D02 §10 :417
cluster segments; pressed `auto` (Live) | DOM | `color.surface.raised` + `color.border.default`;
  pressed `color.surface.selected` + `color.border.strong` + `color.text.primary` | CSS | text /
  non-text | E11-D02 §7.2 :267
Paused pill (`auto` off) | DOM | `color.status.warning.subtle` + `color.text.primary`; glyph
  `color.status.warning.strong` | CSS | text / non-text | E11-D02 §7.2 :267
loading band; skeleton blocks | DOM | `color.surface.hover` + `color.text.secondary` | CSS | text /
  surface | E11-D02 §7.2 :273, §10 :407
countdown (CMP-226) normal / warn / closed | DOM | `color.text.secondary`; warn
  `color.status.warning.subtle` + `color.text.primary` + `color.status.warning.strong` +
  `font.weight.medium`; closed `color.text.tertiary`; `type.ui.caption` / `type.num.sm`;
  `font.family.mono` | CSS | text / non-text | E11-D02 §7.4 :330\u2013332; `15` CMP-226 :2655
lock badge (button) | DOM | `color.surface.raised` + `color.border.strong` + `color.text.primary` |
  CSS | text | E11-D02 §7.1 :244; E11-D03 §5 :193
splitter grip rest / hover / drag; hairline hover | DOM / GL | `color.text.tertiary` →
  `color.text.secondary` → `color.focus.ring`; hairline `color.border.strong` on hover;
  `radius.pill` | CSS; uniform | non-text | E11-D02 §8 :355
collapsed stub text and restore button | DOM | `color.surface.raised` + `color.text.secondary` | CSS
  | text | E11-D02 §8 :367
SCR-043 menus (CMP-041) | DOM | `color.surface.overlay` + `color.border.default`;
  `elevation.popover`; `radius.card`; heading `color.text.tertiary`; hover / focused row
  `color.surface.hover` | CSS | text / surface | E11-D03 §3.1 :97\u2013119
D4 disabled Logarithmic item (a data state, not T2) | DOM | reason `color.text.secondary`; label
  `color.text.disabled` (exempt — D03 :103) | CSS | text | E11-D03 §3.1 :103; E11-D07 F-29 :590
SCR-044 dialog (CMP-043 sm) | DOM | `color.surface.overlay`; `elevation.dialog`; `radius.dialog`;
  labels `color.text.secondary`; hint `color.text.tertiary`; mono inputs `font.family.mono` | CSS |
  text / surface | E11-D03 §7.1 :287\u2013305
SCR-044 error block and primary action | DOM | `color.text.primary` on `color.status.danger.subtle`;
  glyph `color.status.danger.strong` (light candidate `CR:color.status.danger.strong`); Jump
  `color.text.on-action` on `color.action.primary.default` | CSS | text / non-text | E11-D03 §7.1
  :301\u2013304; §14.2 :670
SCR-044 T2 quick jumps (T2-08, T2-09) | DOM | label + lock glyph `color.text.tertiary`; reason
  `color.text.secondary`; fill `color.surface.raised` + `color.border.default` hairline — never
  `color.text.disabled` | CSS | text | E11-D07 §9.5 :447\u2013448; E09-D09 §2.2 :46
SCR-031 Scales tab (CMP-043 lg) | DOM | `color.surface.overlay`; `elevation.dialog`;
  `radius.dialog`; helper `color.text.tertiary`; toggles `CR:color.border.field` (D03-CR-5) | CSS |
  text / surface | E11-D03 §6.1 :209\u2013245; §14.2 :663
CMP-228 PreviewTile | DOM | `color.surface.sunken`; `radius.md` | CSS | surface | `15` CMP-228 :2678
table body, rows, header, selection | DOM | `color.surface.canvas` (odd rows) /
  `color.surface.raised` (even) / `color.surface.hover` (header, hover) / `color.surface.selected`
  (selected) / `color.surface.app` (sub-table) / `color.surface.sunken` (code chip);
  `color.border.subtle` dividers | CSS | surface | E11-D04 §20 :803
table text | DOM | `color.text.primary`; `color.text.secondary`; `color.text.tertiary` (the day
  rule); `color.text.link`; `color.text.on-action`; `type.num.sm` / `type.num.base`;
  `type.ui.caption` / `type.ui.label` / `type.ui.body` / `type.ui.heading-sm`; `font.family.mono`;
  `CR:font.feature.tabularNums` | CSS | text | E11-D04 §20 :804\u2013805
table chips, Kbd, segment, buttons | DOM | `color.surface.raised`; `color.border.default`;
  `radius.control`; `radius.badge`; `size.control.height` (density-resolved: `size.control.compact`
  / `size.control.comfortable`); `size.target.min`; `size.row.compact` / `size.row.comfortable`;
  `space.1` / `space.2` / `space.3`; `space.inset.sm` / `space.inset.md` | CSS | text / non-text |
  E11-D04 §20 :806; E11-D07 F-19 :600
stale banner, restoring strip | DOM | `color.status.warning.subtle` / `color.status.warning.strong`;
  `motion.duration.fast` fade | CSS | text / non-text | E11-D04 §20 :803, :807
SCR-048 card | DOM | `color.surface.raised`; rule + glyph `color.status.danger.strong`; code chip
  `color.surface.sunken`; `radius.card` | CSS | text / non-text | E11-D04 §12.1 :360
`(estimated)` chip (CMP-227) | DOM | `color.status.info.subtle` / `color.status.info.strong` | CSS |
  text / non-text | E11-D04 §20 :803
imbalance flag bar | DOM | `color.footprint.imbalance` | CSS | non-text | E11-D04 §20 :803
T2 row-menu write items (CMP-079 + CMP-019 `lock`) | DOM | label + lock glyph `color.text.tertiary`;
  reason `color.text.secondary`; fill `color.surface.raised` + `color.border.default` hairline —
  never `opacity.disabled` | CSS | text | E11-D07 §9.5 :440\u2013443; E09-D09 §2.2 :46
SCR-047 block (CMP-026) | DOM | `color.surface.canvas`; heading `type.ui.heading-sm`; cause
  `color.text.secondary`; timestamp `font.family.mono` `color.text.primary`; link `color.text.link`
  | CSS | text | E11-D04 §11.1 :336
loading spinner inside CMP-038 (reduce pair) | DOM | `CR:motion.spin` (named by `15` CMP-014, not
  minted) | CSS | — | E11-D04 §17.5 :545, §20 :807
dialog, menu, tooltip, chip and popover motion | DOM | `motion.duration.fast` /
  `motion.duration.normal`; `motion.easing.standard`; `motion.duration.instant` | CSS | — | E11-D06
  §7 rows 12, 39, 40; E11-D03 §12.4 :490\u2013491
validity-disabled control (not T2 — the lane's validity look) | DOM | own fill and label at
  `opacity.disabled`; reason full-opacity `color.text.secondary` under it | CSS | text | E30-D02 D3
  :128; [LANE-55] 2026-10-23 02:13Z
"""


def alias_table() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for name, d, li, hc, line in rows(ALIAS_TABLE):
        out[name] = {"dark": d, "light": li, "high-contrast": hc, "line": line}
    return out


def classify_name(name: str) -> tuple[str, dict[str, str | None]]:
    """A slot name → (status class, resolved value per theme)."""
    aliases = alias_table()
    if name in GAP_NAMES or name.startswith("CR:"):
        return "gap", {t: None for t in THEMES}
    if name in aliases:
        res: dict[str, str | None] = {}
        for t in THEMES:
            prim = aliases[name][t]
            res[t] = colour(t, prim) if prim.startswith(("color.", "palette.")) else prim
        return "proposed", res
    if any(name.startswith(p) for p in REGISTRY_IDS):
        return "registry", {t: "registry id (E11-D05 §7)" for t in THEMES}
    if "*" in name:
        return "family", {t: "a token family" for t in THEMES}
    res = {t: resolve_token(name, t) for t in THEMES}
    if all(v is None for v in res.values()):
        return "unknown", res
    return "token", res


def token_rows() -> dict[str, Any]:
    out: list[dict[str, Any]] = []
    unknown: list[str] = []
    for i, r in enumerate(rows(TOK_ROWS_LITERAL), 1):
        element, surface, slot, consumer, role, source = r
        names = TOKEN_NAME_RE.findall(slot)
        classes = {n: classify_name(n)[0] for n in names}
        unknown += [n for n, c in classes.items() if c == "unknown"]
        if any(c == "gap" for c in classes.values()):
            status = "gap → change request"
        elif any(c == "proposed" for c in classes.values()):
            status = "PROPOSED alias → primitive"
        elif names and all(c == "registry" for c in classes.values()):
            status = "registry id"
        elif names:
            status = "token"
        else:
            status = "no token (a metric or a rule)"
        resolves = (
            "yes"
            if names
            and all(c in ("token", "proposed", "registry", "family") for c in classes.values())
            else (
                "partly"
                if names and any(c in ("token", "proposed") for c in classes.values())
                else "—"
            )
        )
        out.append(
            {
                "id": f"T-{i:02d}",
                "element": element,
                "surface": surface,
                "slot": slot,
                "status": status,
                "resolves": resolves,
                "consumer": consumer,
                "role": role,
                "source": source,
                "names": names,
            }
        )
    counts = {
        "token": sum(1 for r in out if r["status"] == "token"),
        "proposed": sum(1 for r in out if r["status"].startswith("PROPOSED")),
        "gap": sum(1 for r in out if r["status"].startswith("gap")),
        "other": sum(
            1 for r in out if r["status"] in ("registry id", "no token (a metric or a rule)")
        ),
    }
    return {"rows": out, "counts": counts, "unknown": sorted(set(unknown))}


def catalogue_tokens() -> dict[str, Any]:
    """The nine `15` entries' Tokens fields (D05's rule: backticked, dotted); fragments and
    negated names excluded with their reason."""
    text = read(P15).splitlines()
    names: set[str] = set()
    excluded = {
        "elevation.3": "cited as the rejected primitive (`not elevation.3`)",
        "warning.strong": "a fragment of `color.status.warning.strong` in CMP-226's measured note",
    }
    for cmp in (
        "CMP-180",
        "CMP-188",
        "CMP-189",
        "CMP-190",
        "CMP-196",
        "CMP-197",
        "CMP-198",
        "CMP-199",
        "CMP-226",
        "CMP-228",
    ):
        for i, ln in enumerate(text):
            if ln.startswith((f"### {cmp} ", f"### {cmp}\t")):
                for j in range(i, min(i + 40, len(text))):
                    if text[j].startswith("- **Tokens**"):
                        for m in re.findall(r"`([^`]+)`", text[j]):
                            ok = re.fullmatch(r"[a-z][a-z0-9-]*(\.[a-z0-9*-]+)+", m)
                            if ok and "*" not in m and m not in excluded:
                                names.add(m)
                        break
                break
    return {"names": sorted(names), "excluded": excluded}


# ---- 6 state matrix
# surface | state | dark | light | hc | edge density | non-colour carrier | frame | source
MATRIX_TABLE = """
SCR-030 chassis | loading | skeleton grid, label blocks `color.surface.hover`, "Loading 5 000 bars…"
  `color.text.secondary`, shimmer `motion.duration.slow` | same tokens, light resolutions (§11.2
  :532) | same; shimmer static under reduce | the count in the sentence; no layout change | the
  sentence with the count | E11-D02-09-feed-states.png | E11-D02 §10 :407
SCR-030 chassis | loading older bars | `color.surface.hover` band left of the oldest bar, "Loading
  older bars…" | same tokens | same | band keeps its width at every density | the sentence |
  E11-D02-09-feed-states.png | E11-D02 §10 :408
SCR-030 chassis | streaming | no chip; countdown live; last-price pill live; cluster `auto` pressed
  reading Live | same | same | — | "Live" on the cluster | E11-D02-01-chassis-anatomy.png | E11-D02
  §10 :409
SCR-030 chassis | stale | data-ink uniforms \u00d7 0.85; chip "Stale 7s · last 13:42:05"
  (`color.data-confidence.stale.*`) | same; post-dim data-ink ≥ 3.55:1 measured (§11.1 :430) | same
  | chip never wraps; readout truncates first (:422) | the chip text with the age (≤ 1 Hz) |
  E11-D02-09-feed-states.png | E11-D02 §10 :410
SCR-030 chassis | delayed (reduced rate) | chip "Reduced rate \u00d74": canvas-filled pill,
  `color.status.info.strong` dot; corner tag "1 s refresh" | same (dot 4.71:1 light, :411) | same |
  chips side by side, never stacked | the words | E11-D02-09-feed-states.png | E11-D02 §10 :411
SCR-030 chassis | resyncing (book-level) | chart price unaffected; heatmap columns hatched (E21) |
  same | same | — | "(estimated)" on hatched columns | text-only — E11-D02 :412 (E21 draws the
  columns) | E11-D02 §10 :412
SCR-030 chassis | disconnected | frozen frame; scrim `color.surface.app` at `opacity.scrim`; strip
  "Disconnected — last data 00:12"; chip Reconnecting (3) / Offline | same; frozen chart below 3:1
  by design (O-K) | same | the strip stays one line; the countdown reads `—` | the sentence with the
  age; the chip text | E11-D02-09-feed-states.png | E11-D02 §10 :413
SCR-030 chassis | replay | 4 px `color.chart.replay.border` frame; chip "REPLAY 14:32:05";
  virtual-now line; future dim; watermark ` · replay` | `palette.purple.600` frame (5.60:1) | same
  as dark | the chip's clock at 1 Hz, never per tick | the word REPLAY + the clock; the marker |
  E11-D02-10-env-replay-states.png | E11-D02 §10 :414
SCR-030 chassis | demo / live badge | DEMO medium / LIVE bold, 2 px `color.env.*` border, env glyph;
  LIVE 2 px rule | same (border ≥ 3:1 everywhere) | same | text, not a stop; never wraps | the word,
  the glyph shape, the rule | E11-D02-10-env-replay-states.png | E11-D02 §10 :415
SCR-030 chassis | low-GPU / reduced detail | corner badge "Reduced detail — footprint text hidden"
  on `color.surface.raised`, glyph `color.status.warning.strong` | same (glyph 4.11:1 light) |
  same |
  inset 12 / 8 / 4 per density (:96) | the sentence | E11-D02-15-diagnostics-overlay.png | E11-D02
  §10 :416
SCR-030 chassis | aggregated (LOD chip) | chip "Zoomed out · 1 column = 12 bars", neutral pill,
  merge glyph; disclosure on focus | same | same | ratio live; the chip never wraps | the words and
  the ratio | E11-D02-09-feed-states.png | E11-D02 §10 :417
SCR-030 chassis | paused (follow off) | the cluster's `auto` segment becomes the "Paused at 13:47"
  warning pill | same (text 15.62:1 light) | same | the cluster widens leftwards; the exclusion zone
  follows | the words and the time | E11-D02-05-time-axis.png | E11-D02 §10 :418
SCR-030 chassis | scale locked | the lock badge "Price scale locked" at the gutter's bottom (badge
  states E11-D03 §5) | same | same | the pill overhangs the plot edge in compact / dense (D03 :403)
  | "Price scale locked" | E11-D02-04-price-axis.png; E11-D03-04-lock-badge-states.png | E11-D02 §10
  :419
SCR-030 chassis | empty / error | toolbar and status rows kept; CMP-029 placeholder, no GL context;
  SCR-047 / SCR-048 content (E11-D04) | same | same | — | E11-D04's words |
  E11-D04-08-empty-reasons-dark.png; E11-D04-10-error-engine.png | E11-D02 §10 :420
SCR-030 chassis | empty history (SCR-047 1a / 1b) | heading + cause + the `14` §0.5 rule 3 stem; CTA
  only for `recording:write` (sentence form otherwise) | same | same | long symbol names wrap at 200
  % | the heading and the timestamp | E11-D04-08-empty-reasons-dark.png | `14` :684; E11-D04 §11.2
  :338
SCR-030 chassis | symbol delisted / paused (SCR-047 3) | heading "instrument not trading" + cause;
  live-data sentence only where true | same | same | long `status_reason` wraps at 200 % | the
  heading | E11-D04-08-empty-reasons-dark.png | `14` :684; E11-D04 §11.2 :338
SCR-030 bar series (E12-D02) | cache-loading | previous frame held; pending mark on the toolbar
  target; strip line after 600 ms | same | same | a fresh panel shows CMP-029 (static under reduce)
  | the pill's pending mark; the strip text | E12-D02 §7 boards (E12's) | `14` :699
SCR-030 bar series (E12-D02) | progressive-backfill | E11-D02's loading band left of the oldest
  loaded bar | same | same | — | "Loading older bars…" | E11-D02-09-feed-states.png | `14` :700
SCR-030 bar series (E12-D02) | streaming | baseline: live bars, no chrome; stale / disconnected per
  E11-D02 §10 | same | same | — | the status-row chip when degraded | E11-D02-01-chassis-anatomy.png
  | `14` :701
SCR-030 bar series (E12-D02) | forming-bar | a distinct non-colour treatment on the last bar
  (E12-D06's form); CMP-226 countdown | same | same | activity progress in its slot on non-time bars
  | the countdown; the treatment's shape | E12-D02 §7 boards (E12's) | `14` :702
SCR-030 bar series (E12-D02) | closed-bar | solid baseline treatment; an amended bar carries a
  "corrected" marker | same | same | — | the "corrected" marker | E12-D02 §7 boards (E12's) | `14`
  :703
SCR-030 bar series (E12-D02) | rebuilding | previous series stays drawn; strip phases: text + static
  glyph from 600 ms, progress bar with `Cancel` after 2 s | same | same | — | the strip text and the
  pending pill | E12-D02 §7 boards (E12's) | `14` :704
SCR-030 bar series (E12-D02) | partial-history | dashed full-height boundary with a text tag
  (recording start / built range / lookback) | same | same | non-time: E11-D02's loading band | the
  tag's words | E12-D02 §7 boards (E12's) | `14` :705
SCR-030 bar series (E12-D02) | coverage-gap | hatched, labelled band over the gap's time slots
  (`pattern.hatch.gap`), or the labelled seam | same | same | a column spanning a seam still shows
  it | the label | E11-D02-05-time-axis.png | `14` :706; E11-D05 §7 :315
SCR-030 bar series (E12-D02) | LOD-aggregated | E11-D02's status-row chip, persistent while active,
  never a toast; L1 keeps hairline wicks | same | same | — | the chip's words and ratio |
  E11-D02-09-feed-states.png | `14` :707
SCR-030 bar series (E12-D02) | empty | SCR-047 replaces the pane stack, no GL context; toolbar,
  status row and strip stay usable | same | same | — | SCR-047's heading |
  E11-D04-08-empty-reasons-dark.png | `14` :708
SCR-030 bar series (E12-D02) | error | SCR-048 replaces the pane stack; toolbar, status row and
  strip stay usable | same | same | — | SCR-048's heading | E11-D04-10-error-engine.png | `14` :709
SCR-030 chassis motion (E11-D06 §6) | countdown warn / closed (D12) | the word "closing" + weight;
  the flip is instant in both modes | same | same | — | the word |
  E11-D06-05-countdown-stale-strips.png | E11-D06 §6.1 :207; M-32
SCR-030 chassis motion (E11-D06 §6) | stale dimming (D13) | data-ink ramp 1.00 → 0.85 over
  `motion.duration.normal`; chip at 0 ms | same | same | — | the chip |
  E11-D06-05-countdown-stale-strips.png | E11-D06 §6.2 :219; M-18 / M-19
SCR-030 chassis motion (E11-D06 §6) | LOD step and the aggregation chip (D14) | one-frame step, no
  crossfade; chip at 0 ms | same | same | — | the chip's words | E11-D06-06-lod-collapse-strips.png
  | E11-D06 §6.3 :230; M-22
SCR-030 chassis motion (E11-D06 §6) | splitter drag, collapse, restore (D17, D18) | grip follows the
  pointer; collapse / restore as translate + clip over `motion.duration.normal` | same | same | — |
  the stub's word "collapsed" | E11-D06-06-lod-collapse-strips.png | E11-D06 §6.4 :234\u2013236;
  M-28
SCR-030 chassis motion (E11-D06 §6) | context-loss recovery (D19) | last frame held; CMP-028 strip
  at 0 ms, text swaps, no spinner; restore is a cut | same | same | — | the strip's text and attempt
  count | E11-D06-07-context-loss-safety-strips.png | E11-D06 §6.5 :240; M-33
SCR-030 chassis motion (E11-D06 §6) | loading skeleton (D16) | 1,200 ms shimmer, stops at 5 s;
  static two-tone under reduce | same | same | — | the text counting ≤ 1 Hz |
  E11-D06-05-countdown-stale-strips.png | E11-D06 §6.7 :248; M-31
SCR-043 price-scale menu | empty | n/a (fixed items); "Merge indicator scales" and "Reset scale"
  disabled with inline reasons (data states, not T2) | same | same | — | the reason lines |
  E11-D03-01-price-scale-menu.png | E11-D03 §10 :401
SCR-043 price-scale menu | loading | none (synchronous) | — | — | — | — | text-only — E11-D03 :401 |
  E11-D03 §10 :401
SCR-043 price-scale menu | error | the disabled Logarithmic item with its inline D4 reason; after a
  D5 fallback the one-shot announcement | same | same | the reason line always visible | the reason
  sentence | E11-D03-01-price-scale-menu.png | E11-D03 §10 :401
SCR-043 price-scale menu | populated | Linear ✓ · Lock ☑ · Invert ☐ · Merge ☐ · Scale price only ☐ ·
  Reset · Move scale · Scale settings…; focused / hover rows | board 02 | board 02 | comfortable
  rows 32 with the Lock description; compact / dense 24, descriptions on focus; min 280 px | glyph
  shapes ◉ / ○ and ☑ / ☐ | E11-D03-02-price-scale-menu-themes.png | E11-D03 §10 :401
SCR-043 price-scale menu | edge density | rows 24 at compact / dense; the menu never narrower than
  280 px | same | same | the reason line always visible | — | E11-D03-01-price-scale-menu.png |
  E11-D03 §10 :401
SCR-043 time-scale menu | empty | no preset checked when the spacing matches none
  (`aria-checked="false"`) | same | same | — | the unchecked radios | E11-D03-03-time-scale-menu.png
  | E11-D03 §10 :402
SCR-043 time-scale menu | loading | none | — | — | — | — | text-only — E11-D03 :402 | E11-D03 §10
  :402
SCR-043 time-scale menu | error | "Go to date…" disabled with the inline reason (never recorded / no
  symbol) | same | same | — | the reason sentence | E11-D03-03-time-scale-menu.png | E11-D03 §10
  :402
SCR-043 time-scale menu | populated | Standard ✓ · dividers ☑ · maintenance ☑ · UTC ✓ | board 02 /
  03 | board 02 / 03 | the Local item's IANA name ellipsises after 24 characters | glyph shapes |
  E11-D03-03-time-scale-menu.png | E11-D03 §10 :402
SCR-043 time-scale menu | edge density | as the price-scale menu | same | same | 24 px rows; full
  name in the accessible name | — | E11-D03-03-time-scale-menu.png | E11-D03 §10 :402
Scale-lock badge | empty | absent while auto | — | — | — | — | text-only — E11-D03 :403 | E11-D03
  §10 :403
Scale-lock badge | loading | none | — | — | — | — | text-only — E11-D03 :403 | E11-D03 §10 :403
Scale-lock badge | error | n/a | — | — | — | — | text-only — E11-D03 :403 | E11-D03 §10 :403
Scale-lock badge | populated | resting / hover / focus / active (§5) | board 04 | board 04 | the
  pill extends over the plot edge in compact and dense gutters | the words "Price scale locked" +
  lock glyph | E11-D03-04-lock-badge-states.png | E11-D03 §10 :403
Scale-lock badge | edge density | never truncated, never icon-only | same | same | ≤ 16 px terminal
  overhang (D03 §24) | the words | E11-D03-04-lock-badge-states.png | E11-D03 §10 :403
SCR-031 Scales tab | empty | preview "Preview unavailable — no bars loaded" with every field enabled
  | same | same | — | the sentence | E11-D03-06-scales-tab-states.png | E11-D03 §10 :404
SCR-031 Scales tab | loading | none in the tab (live apply); the dialog's open is
  `motion.duration.normal`, instant under reduce | same | same | — | — | text-only — E11-D03 :404 |
  E11-D03 §10 :404
SCR-031 Scales tab | error | preview "Preview unavailable — chart error; settings still apply";
  Logarithmic disabled with the D4 reason; a stepper out of range shows CMP-007's invalid state (the
  validity look) | same | same | — | the sentences; the field's error text |
  E11-D03-06-scales-tab-states.png | E11-D03 §10 :404
SCR-031 Scales tab | populated | every field at its value; the preview live; "Apply to: This panel"
  | board 06 | board 06 | comfortable default; compact rows 24; columns side by side above 720 px |
  the state words beside toggles | E11-D03-05-scales-tab.png | E11-D03 §10 :404
SCR-031 Scales tab | edge density | at 200 % the columns stack and the preview goes below the fields
  | same | same | compact when the app is compact | — | E11-D03-06-scales-tab-states.png | E11-D03
  §10 :404
SCR-044 go-to-date | empty | fields prefilled with the cursor's bar; quick jumps "No journal entries
  for BTCUSDT yet" / "No alerts have fired" / "No confirmed swing" (outcomes, not T2) | same | same
  | — | the sentences | E11-D03-07-go-to-date-default.png | E11-D03 §10 :405
SCR-044 go-to-date | loading | "Checking…" on Jump (≤ 2 s, busy — not T2); quick-jump target lines
  "Loading…" | same | same | — | the words | E11-D03-07-go-to-date-default.png | E11-D03 §10 :405
SCR-044 go-to-date | error | before recorded history · invalid format · after the latest bar · after
  the replay clock · needs paging while disconnected · couldn't check · couldn't load · never
  recorded; warning: no recorded data at the target | board 10 | board 10 | — | the CMP-027
  sentence; `aria-invalid` + `aria-describedby` | E11-D03-08-go-to-date-errors.png | E11-D03 §10
  :405
SCR-044 go-to-date | populated | fields + twin-zone line + hint; five quick jumps with targets; Jump
  enabled | board 10 | board 10 | 420 px at every density | the resolved target under each button |
  E11-D03-07-go-to-date-default.png; E11-D03-10-go-to-date-themes.png | E11-D03 §10 :405
SCR-044 go-to-date | edge density | at 200 % the quick jumps wrap one per row and keep their reason
  lines; never taller than the viewport \u2212 32 px | same | same | scrolls inside | — |
  E11-D03-11-keyboard-and-landing.png | E11-D03 §10 :405
SCR-044 RBAC variants | empty | viewer without `journal:read`: "Last journal entry" is T2 (T2-08) —
  `color.text.tertiary` label + `lock`, reason `rbac.permission` "Your role can't see the journal."
  under it, CMP-079 | same | same | same slot, same layout | the lock glyph and the reason sentence
  | E11-D03-09-go-to-date-rbac-feed.png (D03's anatomy; F-29 re-draws it) | E11-D03 §10 :406;
  E11-D07 §9.5 T2-08 :447
SCR-044 RBAC variants | loading | n/a — no such state (the variant is a permission leg) | — | — | —
  | — | text-only — E11-D03 :406 | E11-D03 §10 :406
SCR-044 RBAC variants | error | n/a — no such state | — | — | — | — | text-only — E11-D03 :406 |
  E11-D03 §10 :406
SCR-044 RBAC variants | populated | owner / manager: all five enabled; viewing as: reads answer as
  the target (no view-as leg on a read) | same | same | — | — | E11-D03-09-go-to-date-rbac-feed.png
  | E11-D03 §10 :406; E09-D09 §3.1 :83
SCR-044 RBAC variants | edge density | n/a — as the dialog's | — | — | — | — | text-only — E11-D03
  :406 | E11-D03 §10 :406
SCR-044 feed variants | empty | n/a | — | — | — | — | text-only — E11-D03 :407 | E11-D03 §10 :407
SCR-044 feed variants | loading | n/a | — | — | — | — | text-only — E11-D03 :407 | E11-D03 §10 :407
SCR-044 feed variants | error | Disconnected: paging refused; "Last journal entry" / "Last alert"
  are T2 (T2-09, a state leg — `lock` only, no CMP-079; reason PROPOSED as an E17-D01 state key) |
  same | same | — | the lock glyph and the reason | E11-D03-09-go-to-date-rbac-feed.png (F-29
  re-draws it) | E11-D03 §10 :407; E11-D07 §9.5 T2-09 :448
SCR-044 feed variants | populated | Stale / Delayed: the header repeats the feed chip verbatim;
  everything enabled | same | same | — | the chip text | E11-D03-09-go-to-date-rbac-feed.png |
  E11-D03 §10 :407
SCR-044 feed variants | edge density | n/a | — | — | — | — | text-only — E11-D03 :407 | E11-D03 §10
  :407
Chart after a jump | empty | n/a | — | — | — | — | text-only — E11-D03 :408 | E11-D03 §10 :408
Chart after a jump | loading | the E11-D02 loading band around the target while E11-S15 pages (≤ 800
  ms) | same | same | — | "Loading older bars…" | E11-D03-11-keyboard-and-landing.png | E11-D03 §10
  :408
Chart after a jump | error | the dialog re-opens with the server's error; the chart has not moved |
  same | same | — | the error sentence | E11-D03-08-go-to-date-errors.png | E11-D03 §10 :408
Chart after a jump | populated | target centred, dashed `color.chart.marker.goto` marker + pill,
  cursor column on the target, "Paused at 15 Sep 13:42" | same | `palette.blue.300` marker (7.05:1)
  | at 0.5 px/bar the marker is still 1 px dashed over the column | the marker's pill; the
  announcement | E11-D03-11-keyboard-and-landing.png | E11-D03 §10 :408
Chart after a jump | edge density | at 200 px/bar the marker sits at the bar's centre | same | same
  | — | — | E11-D03-11-keyboard-and-landing.png | E11-D03 §10 :408
view switch (CMP-221 slot) | empty | n/a (always present) | — | — | — | — | text-only — E11-D04 :449
  | E11-D04 §15 :449
view switch (CMP-221 slot) | loading | n/a | — | — | — | — | text-only — E11-D04 :449 | E11-D04 §15
  :449
view switch (CMP-221 slot) | error | still operable on SCR-048 | same | same | — | the pressed
  segment's check glyph | E11-D04-01-entry-point.png; E11-D04-10-error-engine.png | E11-D04 §15 :449
view switch (CMP-221 slot) | populated | Chart pressed / Table pressed (`color.surface.selected` +
  `color.border.strong`) | E11-D04-03-table-light.png | E11-D04-04-table-hc.png | the
  minimum-viewport toolbar with the never-overflow set | the glyph + text label; `aria-checked` |
  E11-D04-01-entry-point.png | E11-D04 §15 :449
view switch (CMP-221 slot) | edge density | the never-overflow set at 640 CSS px | same | same |
  `size.control.height` 24 / 32 by density | — | E11-D04-05-table-200-zoom.png | E11-D04 §15 :449
SCR-045 bar table | empty | the SCR-047 block in the shell; caption "0 bars loaded" | same | same |
  — | the heading | E11-D04-07-table-states.png | E11-D04 §15 :450; §10 :320
SCR-045 bar table | loading | header row kept; twelve CMP-015 row skeletons `color.surface.hover`;
  caption "Loading 5,000 bars…"; `aria-busy`; 10 s → SCR-048 | same | same | skeletons static under
  reduce | the caption's sentence | E11-D04-07-table-states.png | E11-D04 §15 :450; §10 :319
SCR-045 bar table | error | the SCR-048 card in the shell, header row kept | same | same | — | the
  card's heading | E11-D04-07-table-states.png | E11-D04 §15 :450
SCR-045 bar table | populated | caption, header, zebra (`color.surface.canvas` / `.raised`), focused
  row ring, selected row `color.surface.selected` + ✓, forming row | E11-D04-03-table-light.png |
  E11-D04-04-table-hc.png | 100k rows virtualised; 200 % at 640 CSS px; stacked reflow at 320;
  comfortable → compact step | ✓ glyph; `aria-current`; `aria-selected` | E11-D04-02-table-dark.png
  | E11-D04 §15 :450
SCR-045 bar table | edge density | 100k rows virtualised (≤ 60 in the DOM); 200 % at 640 CSS px;
  stacked reflow at 320 CSS px with the F11 hint | same | same | the fit ladder of §5.2 | the hint
  sentence | E11-D04-05-table-200-zoom.png | E11-D04 §15 :450; §10 :327
SCR-045 bar table | filtered to zero | CMP-026 `filtered-empty`: "No rows match: …" + Clear filters;
  header row kept | same | same | — | the sentence | E11-D04-06-sort-filter-copy.png | E11-D04 §10
  :322
SCR-045 bar table | before recorded history | static band row with the `14` §0.5 rule 3 stem + Show
  coverage; Older disabled "History starts here" (an outcome, not T2) | same | same | — | the stem
  sentence | E11-D04-07-table-states.png | E11-D04 §10 :324
SCR-045 bar table | new bars while not following | the "3 new bars ↓" pill above the footer
  (`Ctrl+End`); rows append silently | same | same | — | the pill's words |
  E11-D04-07-table-states.png | E11-D04 §10 :325
SCR-045 bar table | stale context | the banner "Data is for bar 13:42, no longer in view — press
  Shift+R or Refresh to current" | same | same | two lines at 200 % | the banner sentence |
  E11-D04-07-table-states.png | E11-D04 §10 :326; §7 :268
level sub-table | empty | "No footprint for this bar" row | same | same | — | the sentence |
  E11-D04-02-table-dark.png | E11-D04 §15 :451
level sub-table | loading | "Loading levels…" one row, bounded at 2 s → "Levels unavailable — retry"
  (an outcome) | same | same | — | the words | E11-D04-07-table-states.png | E11-D04 §15 :451
level sub-table | error | inherits the card | same | same | — | the card |
  E11-D04-07-table-states.png | E11-D04 §15 :451
level sub-table | populated | 12 rows on `color.surface.app` then inner scroll;
  `pattern.outline.imbalance` flag as text "Bid-stacked" / "Ask-stacked" |
  E11-D04-03-table-light.png | E11-D04-04-table-hc.png | 300 levels | the state words |
  E11-D04-02-table-dark.png | E11-D04 §15 :451
level sub-table | edge density | 300 levels; the sub-table scrolls after 12 rows | same | same | — |
  — | E11-D04-07-table-states.png | E11-D04 §15 :451
filter toolbar and chips | empty | no chips | same | same | — | — | E11-D04-06-sort-filter-copy.png
  | E11-D04 §15 :452
filter toolbar and chips | loading | n/a | — | — | — | — | text-only — E11-D04 :452 | E11-D04 §15
  :452
filter toolbar and chips | error | n/a | — | — | — | — | text-only — E11-D04 :452 | E11-D04 §15 :452
filter toolbar and chips | populated | chips, "Showing n of m", the sort-status chip "not in time
  order" | E11-D04-03-table-light.png strip | E11-D04-04-table-hc.png strip | long filter list at
  200 % | the words | E11-D04-06-sort-filter-copy.png | E11-D04 §15 :452
filter toolbar and chips | edge density | the long filter list wraps at 200 % | same | same | — | —
  | E11-D04-05-table-200-zoom.png | E11-D04 §15 :452
stale banner | empty | n/a | — | — | — | — | text-only — E11-D04 :453 | E11-D04 §15 :453
stale banner | loading | n/a | — | — | — | — | text-only — E11-D04 :453 | E11-D04 §15 :453
stale banner | error | n/a | — | — | — | — | text-only — E11-D04 :453 | E11-D04 §15 :453
stale banner | populated | shown: `color.status.warning.subtle` + `.strong`, the sentence + Refresh
  to current (`role="status"`, A-11) | E11-D04-07-table-states.png strip |
  E11-D04-07-table-states.png strip | two lines at 200 % | the sentence |
  E11-D04-07-table-states.png | E11-D04 §15 :453
stale banner | edge density | two lines at 200 % | same | same | — | — |
  E11-D04-05-table-200-zoom.png | E11-D04 §15 :453
loading-older / before-history bands | empty | the before-history band (the `14` §0.5 rule 3 stem) |
  same | same | — | the stem sentence | E11-D04-07-table-states.png | E11-D04 §15 :454
loading-older / before-history bands | loading | "Loading older bars…" band + the Older control
  (CMP-053 cursor mode) | same | same | — | the words | E11-D04-07-table-states.png | E11-D04 §15
  :454
loading-older / before-history bands | error | a failed page → the card | same | same | — | the card
  | E11-D04-07-table-states.png | E11-D04 §15 :454
loading-older / before-history bands | populated | n/a | — | — | — | — | text-only — E11-D04 :454 |
  E11-D04 §15 :454
loading-older / before-history bands | edge density | n/a | — | — | — | — | text-only — E11-D04 :454
  | E11-D04 §15 :454
SCR-047 pane | empty | reasons 1a / 1b / 2 / 3 \u00d7 CTA (owner, `recording:write`) / explanatory
  sentence (sentence-form T2, T2-06); in situ | E11-D04-09-empty-reasons-light-hc.png |
  E11-D04-09-empty-reasons-light-hc.png | long symbol names and long `status_reason` at 200 % | the
  heading, the cause, the timestamp | E11-D04-08-empty-reasons-dark.png | E11-D04 §15 :455; E11-D07
  §9.5 T2-06 :445
SCR-047 pane | loading | n/a (the fetch's loading is the chart's skeleton) | — | — | — | — |
  text-only — E11-D04 :455 | E11-D04 §15 :455
SCR-047 pane | error | a timed-out fetch → SCR-048 | same | same | — | the card |
  E11-D04-10-error-engine.png | E11-D04 §15 :455
SCR-047 pane | populated | n/a | — | — | — | — | text-only — E11-D04 :455 | E11-D04 §15 :455
SCR-047 pane | edge density | long symbol names and long `status_reason` wrap at 200 % | same | same
  | — | — | E11-D04-08-empty-reasons-dark.png | E11-D04 §15 :455
SCR-048 card and strip | empty | n/a | — | — | — | — | text-only — E11-D04 :456 | E11-D04 §15 :456
SCR-048 card and strip | loading | the restoring strip with attempts "Graphics context lost —
  restoring… attempt 1 of 3" (busy, not T2) | same | same | — | the attempt count |
  E11-D04-10-error-engine.png | E11-D04 §15 :456
SCR-048 card and strip | error | engine / data feed / backend headings; the deferred variant while
  Disconnected; in situ | E11-D04-12-errors-light-hc.png | E11-D04-12-errors-light-hc.png | a long
  correlation id wraps, never truncates | the heading, body, code and ref line |
  E11-D04-10-error-engine.png; E11-D04-11-error-feed-backend.png | E11-D04 §15 :456
SCR-048 card and strip | populated | n/a | — | — | — | — | text-only — E11-D04 :456 | E11-D04 §15
  :456
SCR-048 card and strip | edge density | a long correlation id wraps, never truncates | same | same |
  — | — | E11-D04-12-errors-light-hc.png | E11-D04 §15 :456
row-action menu | empty | no registered flow → no item | same | same | — | — |
  E11-D04-06-sort-filter-copy.png | E11-D04 §15 :457
row-action menu | loading | n/a | — | — | — | — | text-only — E11-D04 :457 | E11-D04 §15 :457
row-action menu | error | n/a | — | — | — | — | text-only — E11-D04 :457 | E11-D04 §15 :457
row-action menu | populated | five items; the write items T2 for a role without the grant
  (T2-01…T2-04: `lock`, full label `color.text.tertiary`, `rbac.permission` second line, CMP-079);
  view-as leg first | E11-D04-06-sort-filter-copy.png strip | E11-D04-06-sort-filter-copy.png strip
  | 200 % menu height | the lock glyph and the reason line | E11-D04-06-sort-filter-copy.png (F-27 /
  F-28 re-draw the T2 items) | E11-D04 §15 :457; E11-D07 §9.5 :440\u2013443
row-action menu | edge density | 200 % menu height scrolls | same | same | — | — |
  E11-D04-05-table-200-zoom.png | E11-D04 §15 :457
SCR-046 diagnostics overlay | hidden | enabled from SCR-118; `Ctrl+Shift+D` opens (E06-D02 §2.1) | —
  | — | — | — | text-only — E11-D02 :383 | E11-D02 §9 :383
SCR-046 diagnostics overlay | shown | CMP-069 shell top-right over the active chart panel; CMP-036
  rows; CMP-024 sparklines at 2 Hz | same | same | ≤ 0.5 ms per frame | the row labels and values |
  E11-D02-15-diagnostics-overlay.png | E11-D02 §9 :383
SCR-046 diagnostics overlay | pinned | the pin keeps the overlay open across panel focus changes |
  same | same | — | the pin's pressed state | E11-D02-15-diagnostics-overlay.png | E11-D02 §9 :383
SCR-046 diagnostics overlay | threshold-breach | the "above budget" chip: `color.text.primary` on
  `color.status.danger.subtle` + `color.status.danger.strong` icon (A-6 corrects E06-D02's pair) |
  same | same | — | the words "above budget" | E11-D02-15-diagnostics-overlay.png | E11-D02 §9 :383;
  §19 A-6 :795
SCR-049 grid cell | populated | the cell header's sync-group tag: `color.text.primary` chip on
  `color.surface.raised` with a 2 px border in the group's colour, the letter as text | same | same
  | 1\u00d72 … 3\u00d73 and custom grids (E15's) | the letter | E11-D02-08-multi-pane-chrome.png |
  E11-D02 §8 :377; `14` :1072
SCR-049 grid cell | focused cell | the focused cell gets the chart ring; "Chart 2 of 4, group A" |
  same | same | — | the ring; the name | E11-D02-08-multi-pane-chrome.png | E11-D02 §8 :377
SCR-049 grid cell | degraded (GPU budget) | E15's: the explicit reduce-quality prompt when the grid
  exceeds the GPU budget | same | same | — | the prompt's words | text-only — `14` :1085 (E15's) |
  `14` :1085
"""

# Source state labels → the row label in the pack's §7 (typed once; the tool asserts presence).
SOURCE_STATE_MAP: dict[str, dict[str, str]] = {
    "D02 §10": {
        "loading": "loading",
        "loading older bars": "loading older bars",
        "streaming": "streaming",
        "stale": "stale",
        "delayed (reduced rate)": "delayed (reduced rate)",
        "resyncing (book-level)": "resyncing (book-level)",
        "disconnected": "disconnected",
        "replay": "replay",
        "demo / live badge": "demo / live badge",
        "low-GPU / reduced detail": "low-GPU / reduced detail",
        "aggregated (LOD chip)": "aggregated (LOD chip)",
        "paused (follow off)": "paused (follow off)",
        "scale locked": "scale locked",
        "empty / error": "empty / error",
    },
    "14 :684": {
        "loading": "loading",
        "streaming": "streaming",
        "stale": "stale",
        "disconnected": "disconnected",
        "empty history": "empty history (SCR-047 1a / 1b)",
        "symbol delisted/paused": "symbol delisted / paused (SCR-047 3)",
        "replay mode": "replay",
        "demo vs live badge": "demo / live badge",
        "low-GPU degraded": "low-GPU / reduced detail",
    },
}
FIVE_STATES = ("empty", "loading", "error", "populated", "edge density")


def source_states() -> dict[str, Any]:
    d02 = [
        r[0].strip("*")
        for r in md_table(read(D02), "## 10. States per SCR-030", "Chip order in the status row")
        if r and r[0].strip("*") != "State"
    ]
    p14 = read(P14).splitlines()[683]
    p14_clean = re.sub(r"\((?:[^()]|\([^()]*\))*\)", "", p14.split("**States:**", 1)[1])
    p14_states = [s.strip().strip("*").strip() for s in p14_clean.split("·")]
    p14_states = [re.sub(r"\.$", "", s).strip() for s in p14_states if s.strip()]
    e12 = [
        r[0]
        for r in md_table(
            read(P14), "**E12 bar-series state matrix (E12-D02):**", "**Precedence (E12-D01"
        )
        if r and r[0] not in ("State",)
    ]
    d03 = [
        r[0]
        for r in md_table(read(D03), "## 10. State inventory per surface", "## 11. Component map")
        if r and r[0] != "Surface"
    ]
    d04 = [
        r[0]
        for r in md_table(read(D04), "## 15. State inventory per surface", "## 16. Component map")
        if r and r[0] != "Surface"
    ]
    return {
        "D02 §10": d02,
        "14 :684": p14_states,
        "14 E12-D02": e12,
        "D03 §10": d03,
        "D04 §15": d04,
    }


def matrix_rows() -> list[dict[str, str]]:
    cols = ("surface", "state", "dark", "light", "hc", "edge", "carrier", "frame", "source")
    return [dict(zip(cols, r, strict=True)) for r in rows(MATRIX_TABLE)]


def matrix_check(pack_rows: list[dict[str, str]]) -> dict[str, Any]:
    """Every source state present for its surface; cells counted."""
    src = source_states()
    have = {(r["surface"], r["state"]) for r in pack_rows}
    missing: list[str] = []
    for key, mapping in SOURCE_STATE_MAP.items():
        for s in src[key]:
            if s not in mapping:
                missing.append(f"{key}: unmapped source state {s!r}")
            elif ("SCR-030 chassis", mapping[s]) not in have:
                missing.append(f"{key}: {s!r} → {mapping[s]!r} not in the pack")
    for s in src["14 E12-D02"]:
        if ("SCR-030 bar series (E12-D02)", s) not in have:
            missing.append(f"14 E12-D02: {s!r} not in the pack")
    for surface in src["D03 §10"] + src["D04 §15"]:
        for st in FIVE_STATES:
            if (surface, st) not in have:
                missing.append(f"{surface}: {st} not in the pack")
    cells = 0
    empty = 0
    for r in pack_rows:
        for c in ("dark", "light", "hc", "edge", "carrier", "frame"):
            cells += 1
            if not r[c].strip():
                empty += 1
    surfaces = sorted({r["surface"] for r in pack_rows})
    return {
        "surfaces": len(surfaces),
        "states": len(pack_rows),
        "cells": cells,
        "empty": empty,
        "missing": missing,
        "t2_rows": sum(1 for r in pack_rows if "T2" in r["dark"]),
        "source_counts": {k: len(v) for k, v in src.items()},
    }


# ---- 7 open-question log
# from | id | question (short) | status | answered where / owner | target | by
OQ_TABLE = """
E11-D02 §20 | O-A | replay hue: purple or teal | routed | owner | #2701 (E11-D05 Q3 keeps purple as
  the default) | was due 2026-10-22; before E11-T04's token PR
E11-D02 §20 | O-B | `dense` as a per-panel override | answered | E11-D05 §6 :79 (ruled 2026-10-21
  20:27Z) | — | —
E11-D02 §20 | O-C | `symbol` / `interval` / `env` in the diagnostics snapshot | routed | owner |
  E11-T07 (A-6 / A-10 of E11-D02) | before E11-T07 starts (Sprint 09)
E11-D02 §20 | O-D | high-contrast minor grid off | answered | E11-D05 §6 :79 (ruled 2026-10-21
  20:27Z) | — | —
E11-D02 §20 | O-E | the pressed `auto` word; a `\u203a` word; a second countdown home | routed |
  owner
  via E11-D03 (its O-8) | E11-D03 follow-up; #2701 | 2026-10-29
E11-D02 §20 | O-F | the E06-T01 run on the reference machine | routed | owner | #2701 (E06-T01 / T02
  / T03) | run before 2026-10-29
E11-D02 §20 | O-G | the footprint readout unit (E11-D01 O4) | routed | owner (product) | E11-D01 O4;
  E11-S07 #388 (pill rounds to the tick until ruled) | before E11-S07 starts (Sprint 06)
E11-D02 §20 | O-H | legend overflow threshold 30 % / min 3 | routed | owner | #2701; E13 |
  2026-10-29
E11-D02 §20 | O-I | Penpot boards | answered | E11-D02 §20 :819 (done 2026-10-21; sixteen boards r4)
  | — | —
E11-D02 §20 | O-J | mark pill on, index pill opt-in | routed | owner via E11-D03 (its O-8) | E11-D03
  §6.1 :239 defaults; E11-S07 #388 | 2026-10-29
E11-D02 §20 | O-K | the disconnected scrim below 3:1 by design | routed | owner | E17-D02 #325 |
  2026-10-29
E11-D03 §21 | O-1 | "Last swing" parameters | routed | owner (product); E13-T02 for the kernel |
  E13-T02; `22` docs-PR request (CG-1) | 2026-10-29
E11-D03 §21 | O-2 | "Last journal entry" lands on `opened_at` or `closed_at` | routed | owner |
  E11-S15 #448 | 2026-10-29
E11-D03 §21 | O-3 | the go-to-date chord under O13 | routed | owner (E11-D01 O13) | E11-D07 Q-04;
  E11-S13 #520 | before E11-S13 starts (Sprint 09)
E11-D03 §21 | O-4 | "Lock scale" vs "Auto-scale" | routed | owner | E11-D03 follow-up | 2026-10-29
E11-D03 §21 | O-5 | the default bar spacing and right offset (CG-6) | routed | E11-S04 #385 for the
  owner | E11-S04 #385 | 2026-10-29
E11-D03 §21 | O-6 | quick jumps act immediately or fill the fields | routed | owner, in the
  walkthrough | #331 owner walkthrough item 7 | after this PR's text round
E11-D03 §21 | O-7 | "As new default" scope | routed | owner | E11-D03 follow-up; E15 | 2026-10-29
E11-D03 §21 | O-8 | E11-D02's O-E / O-J routed here | routed | owner | E11-D03 follow-up |
  2026-10-29
E11-D03 §21 | O-9 | Penpot boards | answered | E11-D03 §21 :871 (closed 2026-10-21) | — | —
E11-D03 §21 | O-10 | the before-history stem across surfaces | routed | owner; E16-D05 (#373) for
  the final wording | E16-D05 #373 | 2026-10-29
E11-D03 §21 | O-11 | submit-time error politeness | answered | E11-D07 §1.4 :78 — `role="alert"`
  once per submit accepted (E11-D07 merged, #4228) | — | —
E11-D04 §24 | O-1 | default opening in place vs a split | routed | owner | E11-S14 #521 | 2026-10-29
E11-D04 §24 | O-2 | CVD rejoin, the comfortable → compact step, the `state` column | routed | owner
  | E11-S14 #521; CMP-056 (CR-D04-8) | 2026-10-29
E11-D04 §24 | O-3 | `Alt+T` a pure toggle | answered | E11-D04 §24 :959 (ruled 2026-10-20 18:30Z) |
  — | —
E11-D04 §24 | O-4 | the 10,000-row TSV cap | routed | owner | E11-S14 #521 | 2026-11-05
E11-D04 §24 | O-5 | one expanded bar at a time | routed | owner, with E18 | E11-S14 #521; E18 |
  2026-11-05
E11-D04 §24 | O-6 | a table in its own panel: persistence and an opt-in crosshair-follow | routed |
  E15 owner; E06-D03's owner for the opt-in | E15; E11-S14 #521 | 2026-11-12
E11-D04 §24 | O-7 | the before-history stem | answered | E11-D04 §24 :963 (ruled 2026-10-20 18:30Z;
  E16-D05 finalises the wording) | — | —
E11-D04 §24 | O-8 | the SCR-047 CTA Owner-only | answered | E11-D04 §24 :964 (ruled 2026-10-20
  18:30Z) | — | —
E11-D04 §24 | O-9 | automatic retries stop after five attempts | routed | owner | E11-S01 / S14 |
  2026-11-05
E11-D04 §24 | O-10 | Penpot boards | answered | E11-D04 §24 :966 (done 2026-10-21) | — | —
E11-D04 §24 | O-11 | E12-D07's per-bar-mode variants of the shell | routed | E12-D07's author with
  hpe-worker-1 | E12-D07 #242 | 2026-10-29
E11-D04 §24 | O-12 | the two wait bounds (10 s bootstrap, 2 s levels) | routed | owner | E11-S01;
  E11-S14 #521 | 2026-11-05
E11-D05 §14 | Q1 | ruling 1 — the `15` / `16` edit set | answered | E11-D05 §14 :853 (as ruled; the
  owner may reverse at approval) | — | —
E11-D05 §14 | Q2 | the hc minor grid: opacity metric or the alias line | routed | E11-T04 token PR;
  owner | first E11-T04 PR | Sprint 06
E11-D05 §14 | Q3 | the replay token's name and hue | routed | owner (O-A); devsecops if the prefix
  route | first E11-T04 PR | Sprint 06
E11-D05 §14 | Q4 | decorative chrome below 3:1: exemptions or a `decorative` class | routed | a11y
  reviewer; devsecops | first E11-T04 PR | Sprint 06
E11-D05 §14 | Q5 | the delta ramp's range and symmetry | routed | E05 / E47 owner; E18-D01 | before
  `ColorLut.ts` (Sprint 06) | Sprint 06
E11-D05 §14 | Q6 | named `color.chart.ramp.delta.*` aliases | routed | token PR | first E11-T04 PR
  (default: no) | Sprint 06
E11-D05 §14 | Q7 | the density record's home | routed | token PR; chart-engine CODEOWNER | first
  E11-T04 PR | Sprint 06
E11-D05 §14 | Q8 | the chart root's role | answered | E11-D07 §2 :84 — `application` + one roving
  stop, PROPOSED until E11-Q05 (E11-D07 merged, #4228) | — | —
E11-D05 §14 | Q9 | the harness owner and home | routed | owner; the E11 lane | E11-S06 #387 | before
  E11-S06 starts (Sprint 06)
E11-D05 §14 | Q10 | E12-D06 D8's gap band adopts `pattern.hatch.gap` | routed | E12-D09 | E12-D09's
  spec | E12-D09
E11-D05 §14 | Q11 | O-F: the E06 spike run | routed | owner | #2701 | run by 2026-10-29
E11-D05 §14 | Q12 | one spelling "(estimated)" vs "Est." | routed | owner (`25` owner) | E25-D01 Q4
  | with E25-D01's Q4
E11-D05 §14 | Q13 | high-contrast chrome louder (`color.border.default` hc override) | routed |
  owner, beside O-D | first E11-T04 PR | Sprint 06
E11-D06 §13.4 | O-1 | τ, floors, cut thresholds, duration pair, easing — the feel run; the pin
  waiver | routed | owner | #2701 (the run; §11 protocol) | before E11-S04 starts (Sprint 06)
E11-D06 §13.4 | O-2 | the interactive surface for the run | routed | owner | E11-D01 O2a harness or
  E11-S04's first build | Sprint 06
E11-D06 §13.4 | O-3 | the pan cut threshold 3 W or 2 W | routed | owner | the run (T5) | Sprint 06
E11-D06 §13.4 | O-4 | `standard` or `decelerate` for jumps | routed | owner | the run (T7) | Sprint
  06
E11-D06 §13.4 | O-5 | collapse / restore animated or instant | routed | owner | the run; E11-S09
  #446 | Sprint 06
E11-D06 §13.4 | O-6 | crosshair leave fade; the coast's return | routed | owner | the run (T9);
  E11-S07 #388 | Sprint 06
E11-D06 §13.4 | O-7 | weak-magnet radius 8 px or 12 px | routed | owner; E11-S07 #388 (this pack's
  B-4 records S07's 8 px as a G-row) | E11-S07 #388; E14-D01 #204 | before E11-S07 starts (Sprint
  06)
E11-D06 §13.4 | O-8 | `flashOnTick` default | routed | owner; the `flags.ts` owner (E47-S07) |
  E47-S07 | Sprint 06
E11-D06 §13.4 | O-9 | Penpot boards | answered | E11-D06 §13.4 :587 (done; seven boards) | — | —
E11-D06 §13.4 | O-10 | one target per surface: the 16.6 ms p95 gate | routed | owner | #2701 (A-4) |
  Sprint 06
E11-D06 §13.4 | O-11 | auto-scale during a coast | routed | owner | the run (T11); E11-S04 #385 |
  Sprint 06
E11-D06 §13.4 | O-12 | coast by input type | routed | owner | the run; E11-S04 #385; E47 (A-17) |
  Sprint 06
E11-D07 §15.5 | Q-01 | the chart root's role under E11-Q05 | routed | E11-Q05 (the run); owner |
  E11-Q05 | Sprint 09
E11-D07 §15.5 | Q-02 | the panel cycle's new home (K1) | routed | keymap owner | E10-S02 | before
  E10-S02 starts
E11-D07 §15.5 | Q-03 | the high / low chord vs the TradingView habit | routed | owner | E11-S13 #520
  | before E11-S13 starts (Sprint 09)
E11-D07 §15.5 | Q-04 | E11-D01 O13 — the `Alt+<letter>` family | routed | owner | E11-D01 O13 |
  before E11-S13 starts (Sprint 09)
E11-D07 §15.5 | Q-05 | the 200-row cap vs the 1 ms slice | routed | E06-T02 | E06-T02's run |
  E06-T02
E11-D07 §15.5 | Q-06 | SCR-046's values: a live region or on-demand text | routed | E11-T07 owner |
  E11-T07 | before E11-T07 starts (Sprint 09)
this pack | Q1 | the deliverable path (`docs/design/E11/`) | routed | main-orchestrator (default
  built: PROPOSED) | the lane thread; this PR's text round | before the pre-PR lens
this pack | Q2 | the branch name (recorded) | routed | main-orchestrator (recorded; rename only if
  `pr-metadata` refuses) | this PR | at push
this pack | Q3 | the hand-off file's form (b-lite) | routed | main-orchestrator (default built:
  PROPOSED) | the lane thread; this PR's text round | before the pre-PR lens
this pack | Q4 | the `14` / `15` edit set (two `14` lines) | routed | main-orchestrator (default
  built: PROPOSED) | the lane thread; this PR's text round | before the pre-PR lens
this pack | Q5 | the motion table verbatim by tool | routed | main-orchestrator (default built:
  PROPOSED) | the lane thread; this PR's text round | before the pre-PR lens
this pack | Q6 | the key map's source: the E11-D07 import | routed | main-orchestrator (default
  built: PROPOSED) | the lane thread; #4228 merged — rebase onto it first | before push
this pack | Q7 | the walkthrough's form: protocol + agent dry run + owner items | routed |
  main-orchestrator (default built: PROPOSED) | the lane thread; the dry run after the writer |
  before this PR opens
this pack | Q8 | three boards + figure A | routed | main-orchestrator (default built: PROPOSED) |
  the lane thread; the boards PR | before the boards PR
this pack | Q9 | assets: enumerate and route | routed | main-orchestrator (default built: PROPOSED)
  | the lane thread | before the pre-PR lens
this pack | Q10 | routed = closed for the open-question log | routed | main-orchestrator (default
  built: PROPOSED) | the lane thread | before the pre-PR lens
this pack | Q11 | the sibling boundaries | routed | main-orchestrator (default built: PROPOSED) |
  the lane thread | before the pre-PR lens
this pack | Q12 | `13` flows and CG-1…6 as A- / G-rows | routed | main-orchestrator (default built:
  PROPOSED) | the lane thread; #2701 docs-PR request | before the pre-PR lens
this pack | Q13 | the magnet rule (B-4) PROPOSED | routed | main-orchestrator; E11-S07 #388 owns the
  radius | the lane thread; E11-S07 #388 | before E11-S07 starts (Sprint 06)
this pack | Q14 | no hex anywhere | routed | main-orchestrator (default built: PROPOSED) | the lane
  thread | before the pre-PR lens
"""
SOURCE_LOGS: list[tuple[str, Path, str, str, str]] = [
    ("E11-D02 §20", D02, "## 20. Open questions", "## 21. Hand-offs", r"O-[A-K]"),
    ("E11-D03 §21", D03, "## 21. Open questions", "## 22. Sign-off", r"O-\d+"),
    ("E11-D04 §24", D04, "## 24. Open questions", "## 25. Sign-off", r"O-\d+"),
    ("E11-D05 §14", D05, "## 14. Open questions", "## 15. Hand-offs", r"Q\d+"),
    ("E11-D06 §13.4", D06, "### 13.4 Open questions", "## 14. Sign-off", r"O-\d+"),
    ("E11-D07 §15.5", D07_SPEC, "### 15.5 Q", "### 15.6 H", r"Q-\d+"),
]


def source_log_ids() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for label, path, start, end, rx in SOURCE_LOGS:
        if not path.exists():
            out[label] = []
            continue
        ids = [r[0] for r in md_table(read(path), start, end) if r and re.fullmatch(rx, r[0])]
        out[label] = ids
    return out


def oq_rows() -> list[dict[str, str]]:
    cols = ("from", "id", "question", "status", "where_or_owner", "target", "by")
    return [dict(zip(cols, r, strict=True)) for r in rows(OQ_TABLE)]


def oq_check(pack: list[dict[str, str]]) -> dict[str, Any]:
    src = source_log_ids()
    have: dict[tuple[str, str], int] = {}
    for r in pack:
        have[(r["from"], r["id"])] = have.get((r["from"], r["id"]), 0) + 1
    missing = [f"{lab} {i}" for lab, ids in src.items() for i in ids if have.get((lab, i), 0) == 0]
    dup = [f"{k[0]} {k[1]}" for k, n in have.items() if n > 1]
    unowned: list[str] = []
    hist: dict[str, int] = {}
    for r in pack:
        if r["status"] == "routed":
            if r["where_or_owner"] in ("", "—") or r["target"] in ("", "—"):
                unowned.append(f"{r['from']} {r['id']}")
            owner = re.split(r"[;(]", r["where_or_owner"])[0].strip()
            hist[owner] = hist.get(owner, 0) + 1
        elif r["status"] == "answered":
            if r["where_or_owner"] in ("", "—"):
                unowned.append(f"{r['from']} {r['id']}")
        else:
            unowned.append(f"{r['from']} {r['id']} (status {r['status']!r})")
    return {
        "total": len(pack),
        "answered": sum(1 for r in pack if r["status"] == "answered"),
        "routed": sum(1 for r in pack if r["status"] == "routed"),
        "unowned": len(unowned),
        "unowned_rows": unowned,
        "source_rows": sum(len(v) for v in src.values()),
        "source_counts": {k: len(v) for k, v in src.items()},
        "source_missing": missing,
        "duplicates": dup,
        "owner_histogram": dict(sorted(hist.items(), key=lambda kv: -kv[1])),
        "d07_log_present": D07_SPEC.exists(),
    }


# ---- 8 glyph union (GL text)
# surface | example string(s) drawn in GL | source
GL_STRINGS_TABLE = """
price tick labels (CMP-188) | 64,050.0 ; 3,240.00 ; 150.200 ; 63,900 | E11-D02 §5.2 :175; §4.2 :150
time labels (CMP-189) | 13:30 ; 08:00 ; 14 Oct ; Oct ; 2027 ; 14 Oct 13:30 ; 29 Sep ; 01 Oct |
  E11-D02 §5.3 :183\u2013186; §5.4 :194\u2013199
zone tag with the live clock | UTC 13:47:05 ; UTC+2 15:47:05 | E11-D02 §7.2 :267
price-axis mode tag | log ; % ; inv ; log inv ; idx (E11-D03 A-3, PROPOSED) | E11-D02 §7.1 :244;
  E11-D03 §3.3 :139
last-price pill | ▲64,011.0 ; ▼64,011.0 | E11-D02 §7.1 :244 (the ▲ / ▼ nub-vs-glyph question is D02
  §17 item 4 :747)
mark and index pills | M 64,012.5 ; I 64,012.0 | E11-D02 §7.1 :244
crosshair price and time pills | H 64,120.0 ; 13:42 ; 14 Oct 13:42 | E11-D02 §7.3 :300, :302
watermark | BTCUSDT · 1m ; BTCUSDT · 1m · replay | E11-D02 §7.6 :349
maintenance band label | 01:55 \u2013 02:25 maintenance | E11-D02 §7.2 :272
go-to-date pill (GL, A-9) | 15 Sep 13:42 | E11-D02 §7.2 :274; E11-D03 §7.5 :357
E11-K01's named extras | (estimated) ; 1.2K ; 1.2M ; 1.2B | E11.json E11-K01 Scope; `26` §3.7 :220
"""
GLYPH_SET_26 = (
    set("0123456789.,-+%\u00d7KMB")
    | set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    | set("abcdefghijklmnopqrstuvwxyz")
)


def gl_strings() -> list[dict[str, str]]:
    cols = ("surface", "examples", "source")
    return [dict(zip(cols, r, strict=True)) for r in rows(GL_STRINGS_TABLE)]


def glyph_union() -> dict[str, Any]:
    chars: set[str] = set()
    for r in gl_strings():
        for ex in r["examples"].split(" ; "):
            ex = re.sub(r"\s*\((?:E11-D03|the ▲).*$", "", ex)
            chars |= set(ex)
    union = sorted(chars)
    return {
        "union": union,
        "count": len(union),
        "extras_vs_26": sorted(chars - GLYPH_SET_26),
        "missing_vs_26": sorted(GLYPH_SET_26 - chars),
        "set_26": len(GLYPH_SET_26),
    }


# ---- 9 assets
def patterns() -> list[dict[str, Any]]:
    data = md_table(
        read(D05), "## 7. The pattern / encoding registry", "### 7.1 The three gap geometries"
    )
    out: list[dict[str, Any]] = []
    for r in data:
        if r and r[0].startswith(("`pattern.", "`glyph.")) and len(r) >= 9:
            out.append(
                {
                    "id": r[0].strip("`"),
                    "geometry": r[1],
                    "ink": r[2],
                    "opacity": r[3],
                    "meaning": r[4],
                    "consumers": r[5],
                    "source": r[8],
                    "line": line_of(D05, "| " + r[0]),
                }
            )
    return out


def icons_requested() -> list[str]:
    for ln in read(D05).splitlines():
        if ln.startswith("| CR-6 "):
            return re.findall(r"`(icon/[a-z-]+)`", ln)
    return []


def fonts() -> dict[str, Any]:
    prim = tokens("dark")
    fams = {k: prim[k]["$value"] for k in prim if k.startswith("font.family.")}
    weights = {k: prim[k]["$value"] for k in prim if k.startswith("font.weight.")}
    font_dir = ROOT / "packages" / "ui" / "src" / "fonts"
    files = sorted(
        str(p.relative_to(ROOT))
        for p in (ROOT / "packages" / "ui").rglob("*")
        if p.suffix in (".woff2", ".woff", ".ttf", ".otf")
    )
    icons = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "packages" / "ui").rglob("*.svg"))
    return {
        "families": fams,
        "weights": weights,
        "font_dir_exists": font_dir.exists(),
        "font_files": files,
        "icon_files": icons,
    }


# ---- 10 string gates
FABRICATED = [
    re.compile(
        r"\b(engineer|lead|participant)s?\b.{0,40}\b(said|asked|agreed|attended|confirmed)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bsession (was )?(held|run|recorded)\b", re.IGNORECASE),
    re.compile(r"\brecording (is )?attached\b", re.IGNORECASE),
]
LOCAL_PATH = re.compile(r"/(?:home|Users)/[^/\s]+/")
NOTES_DIR = re.compile(r"\b\w+-notes[/\\]")
PENPOT_HOST = re.compile(r"penpot\.[a-z0-9-]+\.[a-z]{2,}", re.IGNORECASE)
WORKSPACE_LINK = re.compile(r"(?:team|file)-id=|#/workspace")
HEX = re.compile(r"#[0-9A-Fa-f]{6}\b")
CLOSING = re.compile(
    r"\b(clos(?:e|es|ed|ing)|fix(?:es|ed|ing)?|resolv(?:e|es|ed|ing))\b", re.IGNORECASE
)
ISSUE_REF = re.compile(r"#\d+")


def strip_code_and_markers(text: str) -> str:
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    return text


def hex_hits(text: str) -> list[str]:
    return [m.group(0) for m in HEX.finditer(strip_code_and_markers(text))]


def string_gates(text: str, label: str) -> list[str]:
    errs: list[str] = []
    for i, ln in enumerate(text.splitlines(), 1):
        for rx in FABRICATED:
            if rx.search(ln):
                errs.append(f"{label}:{i} fabricated-session phrase: {ln.strip()[:80]}")
        if LOCAL_PATH.search(ln):
            errs.append(f"{label}:{i} local path")
        if NOTES_DIR.search(ln):
            errs.append(f"{label}:{i} notes-folder path")
        if PENPOT_HOST.search(ln) or WORKSPACE_LINK.search(ln):
            errs.append(f"{label}:{i} Penpot host / workspace reference")
    return errs


def draft_gates(text: str) -> list[str]:
    errs = string_gates(text, "draft")
    for i, ln in enumerate(text.splitlines(), 1):
        if CLOSING.search(ln) and ISSUE_REF.search(ln):
            errs.append(f"draft:{i} closing keyword beside an issue number: {ln.strip()[:80]}")
    if not re.search(r"^Partial:", text, re.MULTILINE):
        errs.append("draft: no `Partial:` line")
    if not re.search(r"^Refs #331", text, re.MULTILINE):
        errs.append("draft: no `Refs #331` line")
    return errs


# ---- contrast counts (the five matrices, by import)
DEFAULT_BAR: dict[str, float | None] = {
    "text": 4.5,
    "non-text": 3.0,
    "hc-text": 7.0,
    "decorative": None,
    "surface": None,
}


def sibling_contrast(name: str) -> dict[str, Any]:
    """Rows and gated FAIL count of one upstream matrix, measured through that tool's own
    ``col()`` and the shared ``contrast_ratio()`` (E11-D05 through its ``measure()``)."""
    mod = SIBLINGS[name]
    if name == "E11-D05":
        pairs = mod.measure(mod.registered_pairs(), mod.exempted_pairs())
        return {"rows": len(pairs), "fail": sum(1 for p in pairs if p["gated"] and p["failing"])}
    pairs = mod.ROWS if name == "E11-D06" else mod.PAIRS
    bar = getattr(mod, "BAR", DEFAULT_BAR)
    fail = 0
    for p in pairs:
        fg, bg, role = p[1], p[2], p[3]
        b = bar.get(role, DEFAULT_BAR.get(role))
        if b is None or str(role).startswith("rejected"):
            continue
        themes = ("high-contrast",) if str(role).endswith("hc-text") else THEMES
        for t in themes:
            if ratio(mod.col(t, fg), mod.col(t, bg)) < b:
                fail += 1
                break
    return {"rows": len(pairs), "fail": fail}


# (name, fg token, bg token) — the chassis pairs board 02 prints as light ratios; E11-D02 §11.1 rows
LIGHT_PAIRS = (
    ("axis", "color.text.tertiary", "color.surface.canvas"),
    ("grid_major", "color.border.default", "color.surface.canvas"),
    ("grid_minor", "color.grid.line", "color.surface.canvas"),
    ("crosshair", "color.crosshair", "color.surface.canvas"),
    ("pill_text", "color.text.primary", "color.surface.raised"),
    ("pill_inverse", "color.text.inverse", "color.crosshair"),
    ("ring", "color.focus.ring", "color.surface.canvas"),
    ("replay", "CR:color.replay.border", "color.surface.canvas"),
)


def light_ratios() -> dict[str, str]:
    """The light-theme ratios of the chassis pairs, through E11-D02's ``col()`` (never by hand)."""
    d02 = SIBLINGS["E11-D02"]
    return {n: fmt(ratio(d02.col("light", fg), d02.col("light", bg))) for n, fg, bg in LIGHT_PAIRS}


def contrast_summary() -> dict[str, Any]:
    out = {n: sibling_contrast(n) for n in SIBLINGS}
    out["total_rows"] = sum(v["rows"] for v in out.values())
    out["total_fail"] = sum(v["fail"] for v in out.values() if isinstance(v, dict))
    return out


# ---- E11-D07 findings (by parse, when present)
def d07_findings() -> dict[str, Any]:
    if not D07_SPEC.exists():
        return {
            "present": False,
            "f": [],
            "g": [],
            "q": [],
            "t2": [],
            "stops": 0,
            "targets": 0,
            "handoffs": 0,
        }
    text = read(D07_SPEC)
    f = [
        r for r in md_table(text, "### 15.1 F", "### 15.2 A") if r and re.fullmatch(r"F-\d+", r[0])
    ]
    g = [
        r for r in md_table(text, "### 15.4 G", "### 15.5 Q") if r and re.fullmatch(r"G-\d+", r[0])
    ]
    q = [
        r for r in md_table(text, "### 15.5 Q", "### 15.6 H") if r and re.fullmatch(r"Q-\d+", r[0])
    ]
    t2 = [
        r
        for r in md_table(text, "### 9.5 Gated controls", "## 10. Target sizes")
        if r and re.fullmatch(r"T2-\d+", r[0])
    ]
    stops = [
        r
        for r in md_table(text, "### 9.1 The stop table", "### 9.2 N panes")
        if r and re.fullmatch(r"ST\d+", r[0])
    ]
    targets = [
        r
        for r in md_table(text, "## 10. Target sizes", "## 11. Composed contrast")
        if r and re.fullmatch(r"TG\d+", r[0])
    ]
    ho = [
        r
        for r in md_table(text, "## 19. Hand-offs", "## 20. Summary")
        if r and re.fullmatch(r"HO-\d+", r[0])
    ]
    lines = {r[0]: line_of(D07_SPEC, f"| {r[0]} ") for r in f}
    return {
        "present": True,
        "f": [
            {
                "id": r[0],
                "class": r[1],
                "severity": r[2],
                "clause": r[3],
                "owner": r[5],
                "target": r[6],
                "line": lines[r[0]],
            }
            for r in f
        ],
        "f_live": sum(1 for r in f if not r[2].startswith("withdrawn")),
        "g": [r[0] for r in g],
        "q": [r[0] for r in q],
        "t2": [r[0] for r in t2],
        "stops": len(stops),
        "targets": len(targets),
        "handoffs": len(ho),
    }


# ---- the pack's own tables
PACK = DESIGN / "E11" / "E11-D09.md"
HANDOFF = DESIGN / "E11" / "E11-D09-handoff.md"
SECTIONS = {
    "redlines": ("## 2. Redlines", "## 3. Behaviour rules"),
    "keymap": ("### 4.1 The complete key map", "### 4.2 The conflict resolutions"),
    "motion": ("## 5. The motion table", "## 6. Token mapping"),
    "tokens": ("## 6. Token mapping", "## 7. State matrix"),
    "matrix": ("## 7. State matrix", "## 8. The accessibility contract"),
    "oq": ("## 13. Open-question log", "## 14. Contradictions, gaps and the pack's questions"),
    "a": ("## 11. Amendments for the owner", "## 12. Engineering walkthrough"),
    "cgq": ("## 14. Contradictions, gaps and the pack's questions", "## 15. Acceptance criteria"),
    "handoffs": ("## 17. Hand-offs", "## 18. Summary"),
    "walkthrough": ("### 12.1 Session protocol", "### 12.2 Protocol index"),
    "dryrun": ("### 12.3 Dry run", "### 12.4 Owner walkthrough"),
    "owner": ("### 12.4 Owner walkthrough", "## 13. Open-question log"),
    "perf": ("## 10. Performance flags", "## 11. Amendments for the owner"),
    "glyphs": ("### 9.3 The glyph set", "### 9.4 Icons"),
    "findings": ("### 8.7 E11-D07's findings", "## 9. Assets"),
}


def pack_table(text: str, key: str) -> list[list[str]]:
    """The data rows of the FIRST table under a pack heading (it ends at a non-table line)."""
    start, end = SECTIONS[key]
    if start not in text:
        return []
    body = text.split(start, 1)[1].split(end, 1)[0]
    out: list[list[str]] = []
    started = False
    for ln in body.splitlines():
        if ln.startswith("|"):
            started = True
            if re.match(r"^\|\s*-{3,}", ln):
                continue
            cells = ln.strip().strip("|").replace("\\|", "\x00").split("|")
            out.append([c.strip().replace("\x00", "|") for c in cells])
        elif started:
            break
    return out[1:] if out else []


def id_rows(text: str, key: str, rx: str) -> int:
    start, end = SECTIONS[key]
    if start not in text:
        return 0
    body = text.split(start, 1)[1].split(end, 1)[0]
    return sum(1 for ln in body.splitlines() if re.match(rf"^\|\s*{rx}\s*\|", ln))


def compare_keymap(pack: list[list[str]], computed: list[dict[str, Any]]) -> dict[str, Any]:
    want = {(r["key"], r["context"], r["stop"]) for r in computed}
    have: set[tuple[str, str, str]] = set()
    for r in pack:
        if len(r) < 4:
            continue
        key = r[1].strip("`")
        ctx_stop = r[2]
        m = re.match(r"^(\w+)\s*/\s*(.+)$", ctx_stop)
        if m:
            have.add((key, m.group(1), m.group(2).strip("`")))
    return {
        "rows": len(pack),
        "missing": sorted(f"{k} {c}/{s}" for k, c, s in want - have),
        "extra": sorted(f"{k} {c}/{s}" for k, c, s in have - want),
    }


def compare_motion(pack: list[list[str]], d06: list[list[str]]) -> int:
    diff = 0
    for i, row in enumerate(d06):
        if i >= len(pack):
            diff += 1
            continue
        if [c.strip() for c in row] != [c.strip() for c in pack[i][: len(row)]]:
            diff += 1
    return diff + max(0, len(pack) - len(d06))


def handoff_t1_diff(handoff_text: str, pack_rows: list[dict[str, str]]) -> dict[str, Any]:
    """The hand-off file's Table 1 states per surface against §7's."""
    if "### Table 1" not in handoff_text:
        return {"diff": -1, "detail": ["Table 1 absent"]}
    data = md_table(handoff_text, "### Table 1", "### Table 2")
    by_surface: dict[str, set[str]] = {}
    for cells in data[1:]:
        if len(cells) >= 3:
            states = {s.strip() for s in cells[2].split(" · ") if s.strip()}
            by_surface.setdefault(cells[0], set()).update(states)
    pack_by: dict[str, set[str]] = {}
    for r in pack_rows:
        pack_by.setdefault(r["surface"], set()).add(r["state"])
    detail: list[str] = []
    for surf, states in pack_by.items():
        got = by_surface.get(surf)
        if got is None:
            detail.append(f"{surf}: absent from Table 1")
        elif got != states:
            detail.append(f"{surf}: Table 1 {sorted(got - states)} vs §7 {sorted(states - got)}")
    return {"diff": len(detail), "detail": detail}


# ---- build, emit, check, json
def build(spec_path: Path | None, handoff_path: Path | None) -> dict[str, Any]:
    spec_text = read(spec_path) if spec_path and spec_path.exists() else ""
    handoff_text = read(handoff_path) if handoff_path and handoff_path.exists() else ""
    d02 = parse_d02_dimensions()
    red = redline_rows()
    rt = redline_tokens(d02)
    beh = behaviour()
    km = keymap_rows()
    d06 = motion_rows()
    cov = motion_coverage(d06)
    tok = token_rows()
    cat = catalogue_tokens()
    tok_names: set[str] = set()
    for r in tok["rows"]:
        tok_names.update(r["names"])
    cat_absent = [n for n in cat["names"] if n not in tok_names]
    mat = matrix_rows()
    mc = matrix_check(mat)
    oq = oq_rows()
    oc = oq_check(oq)
    gl = glyph_union()
    pat = patterns()
    ic = icons_requested()
    fo = fonts()
    con = contrast_summary()
    f07 = d07_findings()
    problems: list[str] = []
    if km["absent"]:
        problems.append(D07_ABSENT + " (the key map cannot be derived here)")
    problems += [f"token name resolves nowhere: {n}" for n in tok["unknown"]]
    problems += mc["missing"]
    problems += [f"source-log row missing from the pack: {m}" for m in oc["source_missing"]]
    problems += [f"open-question row without owner + target: {u}" for u in oc["unowned_rows"]]
    problems += [f"duplicate open-question row: {d}" for d in oc["duplicates"]]
    problems += [f"catalogue token absent from the mapping: {n}" for n in cat_absent]
    problems += [f"worked case disagrees with E11-D02: {d}" for d in beh["disagreements"]]
    # the pack's own tables, when the spec exists
    pack_red = pack_table(spec_text, "redlines")
    pack_km = pack_table(spec_text, "keymap")
    pack_mo = pack_table(spec_text, "motion")
    pack_tok = pack_table(spec_text, "tokens")
    pack_mat = pack_table(spec_text, "matrix")
    pack_oq = pack_table(spec_text, "oq")
    red_missing: list[str] = []
    km_cmp: dict[str, Any] = {"rows": 0, "missing": [], "extra": []}
    mo_diff = -1
    t1: dict[str, Any] = {"diff": -1, "detail": []}
    if spec_text:
        have_el = {r[2] for r in pack_red if len(r) > 2}
        red_missing = [r["element"] for r in d02 if r["element"] not in have_el]
        problems += [f"D02 §2 row absent from the pack's §2: {m}" for m in red_missing]
        if not km["absent"]:
            km_cmp = compare_keymap(pack_km, km["rows"])
            problems += [f"key-map row missing: {m}" for m in km_cmp["missing"]]
            problems += [f"key-map row extra: {m}" for m in km_cmp["extra"]]
        mo_diff = compare_motion(pack_mo, d06)
        if mo_diff:
            problems.append(f"motion table differs from E11-D06 §7 in {mo_diff} row(s)")
        hx = hex_hits(spec_text)
        if hx:
            problems.append(f"hex in the pack: {hx[:5]}")
        problems += string_gates(spec_text, "pack")
        if len(pack_mat) != len(mat):
            problems.append(f"matrix rows in the pack {len(pack_mat)} != computed {len(mat)}")
        if len(pack_oq) != len(oq):
            problems.append(f"open-question rows in the pack {len(pack_oq)} != computed {len(oq)}")
        if len(pack_tok) != len(tok["rows"]):
            problems.append(
                f"token rows in the pack {len(pack_tok)} != computed {len(tok['rows'])}"
            )
        for i, r in enumerate(pack_tok):
            if len(r) > 4 and i < len(tok["rows"]) and r[4].strip() != tok["rows"][i]["status"]:
                tid, want = tok["rows"][i]["id"], tok["rows"][i]["status"]
                problems.append(f"token row {tid} status {r[4].strip()!r} != computed {want!r}")
        for key, task in (("walkthrough", r"W-T\d"),):
            if id_rows(spec_text, key, task) != 6:
                problems.append("walkthrough: W-T1…W-T6 not all present")
        body = (
            spec_text.split(SECTIONS["walkthrough"][0], 1)[1].split(SECTIONS["walkthrough"][1], 1)[
                0
            ]
            if SECTIONS["walkthrough"][0] in spec_text
            else ""
        )
        for ln in body.splitlines():
            if re.match(r"^\|\s*W-T\d", ln) and "not run" not in ln:
                problems.append(f"walkthrough task without a 'not run' log line: {ln[:40]}")
    if handoff_text:
        hx = hex_hits(handoff_text)
        if hx:
            problems.append(f"hex in the hand-off file: {hx[:5]}")
        problems += string_gates(handoff_text, "handoff")
        t1 = handoff_t1_diff(handoff_text, mat)
        problems += [f"hand-off Table 1 vs §7: {d}" for d in t1["detail"]]
        t2_keys = {
            r[1].strip("`")
            for r in md_table(handoff_text, "### Table 2", "### Table 3")[1:]
            if len(r) > 1
        }
        km_keys = {r["key"] for r in km["rows"]}
        for k in sorted(t2_keys):
            for atom in re.split(r"\s*[;/]\s*|\s*,\s*", k):
                atom = atom.strip("` ").replace("Shift+", "Shift+")
                if (
                    atom
                    and atom not in km_keys
                    and not re.match(r"^(Tab|Shift\+Tab|cluster|`)", atom)
                    and atom not in ("—", "the §4 plot keys", "the plot keys")
                ):
                    pass
        if len(re.findall(r"^## Handoff checklist", handoff_text, re.MULTILINE)) != 0:
            problems.append("the hand-off file holds a checklist block (Q3's form has none)")
    counts: dict[str, Any] = {
        "redline_rows": len(red),
        "redline_parsed": len(d02),
        "redline_tokens_resolved": len([n for n, v in rt["resolved"].items() if v]),
        "redline_typed_only": len(rt["typed_only"]),
        "behaviour_rules": beh["rules"],
        "proposed_rules": beh["proposed_rules"],
        "worked_cases": len(beh["price_cases"]) + len(beh["time_cases"]) + 1,
        "worked_disagreements": len(beh["disagreements"]),
        "time_ladder_steps": beh["time_ladder_steps"],
        "keymap_rows": len(km["rows"]),
        "keymap_missing": len(km_cmp["missing"]),
        "keymap_extra": len(km_cmp["extra"]),
        "unregistered": len(km["unregistered"]),
        "k_rows": len(km["k_rows"]),
        "design_literals": km.get("design_literals", 0),
        "shipped_commands": km.get("shipped_commands", 0),
        "shipped_bindings": km.get("shipped_bindings", 0),
        "reserved_total": km.get("reserved_total", 0),
        "alt_family": len(km.get("alt_family", [])),
        "announcement_gaps": sum(
            1 for r in km["rows"] if r["announcement"].startswith("not stated")
        ),
        "motion_rows": len(d06),
        "motion_diff": max(mo_diff, 0),
        "motion_animate": cov["animate_under_safe"],
        "token_rows": len(tok["rows"]),
        "token_resolved": tok["counts"]["token"],
        "token_proposed": tok["counts"]["proposed"],
        "token_gap": tok["counts"]["gap"],
        "token_other": tok["counts"]["other"],
        "token_aliases": len(alias_table()),
        "catalogue_tokens": len(cat["names"]),
        "catalogue_absent": len(cat_absent),
        "hex_spec": len(hex_hits(spec_text)) if spec_text else 0,
        "hex_handoff": len(hex_hits(handoff_text)) if handoff_text else 0,
        "matrix_surfaces": mc["surfaces"],
        "matrix_states": mc["states"],
        "matrix_cells": mc["cells"],
        "matrix_empty": mc["empty"],
        "matrix_t2": mc["t2_rows"],
        "handoff_t1_diff": max(t1["diff"], 0),
        "oq_total": oc["total"],
        "oq_answered": oc["answered"],
        "oq_routed": oc["routed"],
        "oq_unowned": oc["unowned"],
        "oq_source_rows": oc["source_rows"],
        "oq_source_missing": len(oc["source_missing"]),
        "glyphs": gl["count"],
        "glyph_extras": len(gl["extras_vs_26"]),
        "glyph_missing": len(gl["missing_vs_26"]),
        "glyph_set_26": gl["set_26"],
        "patterns": len(pat),
        "icons_requested": len(ic),
        "font_families": len(fo["families"]),
        "font_weights": len(fo["weights"]),
        "font_files": len(fo["font_files"]),
        "icon_files": len(fo["icon_files"]),
        "a_rows": id_rows(spec_text, "a", r"A-\d+"),
        "c_rows": id_rows(spec_text, "cgq", r"C-\d+"),
        "g_rows": id_rows(spec_text, "cgq", r"G-\d+"),
        "q_rows": id_rows(spec_text, "cgq", r"Q\d+"),
        "handoffs": id_rows(spec_text, "handoffs", r"H-\d+"),
        "walkthrough_tasks": id_rows(spec_text, "walkthrough", r"W-T\d"),
        "dryrun_rows": id_rows(spec_text, "dryrun", r"\d{4}-\d{2}-\d{2}"),
        "owner_items": id_rows(spec_text, "owner", r"\d+"),
        "perf_rows": id_rows(spec_text, "perf", r"P-\d+"),
        "boards": 3,
        "light_twins": 1,
        "figures": 1,
        "contrast_rows": con["total_rows"],
        **{f"light_{k}": v for k, v in light_ratios().items()},
        "contrast_fail": con["total_fail"],
        "d02_pairs": con["E11-D02"]["rows"],
        "d03_pairs": con["E11-D03"]["rows"],
        "d04_pairs": con["E11-D04"]["rows"],
        "d05_pairs": con["E11-D05"]["rows"],
        "d06_pairs": con["E11-D06"]["rows"],
        "d07_f_rows": len(f07["f"]),
        "d07_f_live": f07.get("f_live", 0),
        "d07_g_rows": len(f07["g"]),
        "d07_q_rows": len(f07["q"]),
        "d07_t2_rows": len(f07["t2"]),
        "d07_stops": f07["stops"],
        "d07_targets": f07["targets"],
        "d07_handoffs": f07["handoffs"],
    }
    return {
        "counts": counts,
        "problems": problems,
        "redlines": red,
        "redline_tokens": rt,
        "density": parse_d02_density(),
        "behaviour": beh,
        "keymap": {k: v for k, v in km.items() if k != "rows"},
        "keymap_rows": km["rows"],
        "motion_header": motion_header(),
        "motion_rows": d06,
        "motion_coverage": cov,
        "tokens": tok,
        "catalogue": {"names": cat["names"], "absent": cat_absent, "excluded": cat["excluded"]},
        "matrix": mat,
        "matrix_check": mc,
        "oq": oq,
        "oq_check": oc,
        "glyphs": gl,
        "gl_strings": gl_strings(),
        "patterns": pat,
        "icons": ic,
        "fonts": fo,
        "contrast": con,
        "light_ratios": light_ratios(),
        "d07": f07,
        "theme_hex": {
            t: {
                n: colour(t, n)
                for n in (
                    "color.surface.app",
                    "color.surface.canvas",
                    "color.surface.raised",
                    "color.surface.overlay",
                    "color.surface.hover",
                    "color.surface.selected",
                    "color.surface.sunken",
                    "color.text.primary",
                    "color.text.secondary",
                    "color.text.tertiary",
                    "color.text.inverse",
                    "color.text.on-action",
                    "color.border.default",
                    "color.border.strong",
                    "color.focus.ring",
                    "color.grid.line",
                    "color.crosshair",
                    "color.candle.up",
                    "color.candle.down",
                    "color.candle.wick",
                    "color.action.primary.default",
                    "color.status.warning.subtle",
                    "color.status.warning.strong",
                    "color.status.info.strong",
                    "color.env.demo",
                    "color.env.live",
                )
            }
            for t in THEMES
        },
    }


def mdrow(cells: list[str]) -> str:
    return "| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |"


def emit(d: dict[str, Any], what: str) -> str:
    out: list[str] = []
    if what == "redlines":
        out.append(
            mdrow(
                [
                    "Id",
                    "Group",
                    "Element",
                    "comfortable",
                    "compact",
                    "dense",
                    "Token(s)",
                    "Type token",
                    "Radius",
                    "Opacity",
                    "GL / DOM",
                    "Source",
                ]
            )
        )
        out.append(mdrow(["---"] * 12))
        for i, r in enumerate(d["redlines"], 1):
            out.append(
                mdrow(
                    [
                        f"R-{i:02d}",
                        r["group"],
                        r["element"],
                        r["comfortable"],
                        r["compact"],
                        r["dense"],
                        r["tokens"],
                        r["type"],
                        r["radius"],
                        r["opacity"],
                        r["gl_dom"],
                        r["source"],
                    ]
                )
            )
    elif what == "keymap":
        out.append(
            mdrow(
                [
                    "Id",
                    "Key",
                    "Context / stop",
                    "Action",
                    "Announcement (verbatim where the spec has one)",
                    "Announcement source",
                    "Registered in `keymap.json`?",
                    "E11-D07 K-rows",
                    "Status",
                    "Source",
                ]
            )
        )
        out.append(mdrow(["---"] * 10))
        for r in d["keymap_rows"]:
            out.append(
                mdrow(
                    [
                        r["id"],
                        f"`{r['key']}`",
                        (
                            f"{r['context']} / {r['stop']}"
                            if r["stop"] != "*"
                            else f"{r['context']} / *"
                        ),
                        r["action"],
                        r["announcement"],
                        r["ann_src"],
                        r["registered"],
                        r["k"],
                        r["status"],
                        r["source"],
                    ]
                )
            )
    elif what == "motion":
        out.append(mdrow(d["motion_header"]))
        out.append(mdrow(["---"] * len(d["motion_header"])))
        for r in d["motion_rows"]:
            out.append(mdrow(r))
    elif what == "tokens":
        out.append(
            mdrow(
                [
                    "Id",
                    "Element",
                    "Surface",
                    "Slot(s)",
                    "Status",
                    "Resolves dark / light / hc?",
                    "Consumer",
                    "Measured role",
                    "Source",
                ]
            )
        )
        out.append(mdrow(["---"] * 9))
        for r in d["tokens"]["rows"]:
            out.append(
                mdrow(
                    [
                        r["id"],
                        r["element"],
                        r["surface"],
                        r["slot"],
                        r["status"],
                        r["resolves"],
                        r["consumer"],
                        r["role"],
                        r["source"],
                    ]
                )
            )
    elif what == "matrix":
        out.append(
            mdrow(
                [
                    "Id",
                    "Surface",
                    "State",
                    "dark",
                    "light",
                    "high-contrast",
                    "Edge density",
                    "Non-colour carrier",
                    "Frame",
                    "Source",
                ]
            )
        )
        out.append(mdrow(["---"] * 10))
        for i, r in enumerate(d["matrix"], 1):
            out.append(
                mdrow(
                    [
                        f"S-{i:03d}",
                        r["surface"],
                        r["state"],
                        r["dark"],
                        r["light"],
                        r["hc"],
                        r["edge"],
                        r["carrier"],
                        r["frame"],
                        r["source"],
                    ]
                )
            )
    elif what == "oq":
        out.append(
            mdrow(
                [
                    "From",
                    "Id",
                    "Question (short)",
                    "Status",
                    "Answered where / owner",
                    "Target",
                    "By",
                ]
            )
        )
        out.append(mdrow(["---"] * 7))
        for r in d["oq"]:
            out.append(
                mdrow(
                    [
                        r["from"],
                        r["id"],
                        r["question"],
                        r["status"],
                        r["where_or_owner"],
                        r["target"],
                        r["by"],
                    ]
                )
            )
    elif what == "glyphs":
        out.append(mdrow(["Surface", "Example strings (GL text)", "Source"]))
        out.append(mdrow(["---"] * 3))
        for r in d["gl_strings"]:
            out.append(
                mdrow(
                    [
                        r["surface"],
                        "`" + "` · `".join(r["examples"].split(" ; ")) + "`",
                        r["source"],
                    ]
                )
            )
    elif what == "findings":
        out.append(mdrow(["Id", "Class", "Severity", "Clause", "Owner", "Target", "E11-D07 line"]))
        out.append(mdrow(["---"] * 7))
        for r in d["d07"]["f"]:
            out.append(
                mdrow(
                    [
                        r["id"],
                        r["class"],
                        r["severity"],
                        r["clause"],
                        r["owner"],
                        r["target"],
                        f":{r['line']}",
                    ]
                )
            )
    elif what == "patterns":
        out.append(
            mdrow(["Id", "Geometry", "Ink", "Opacity", "Meaning", "Consumers", "E11-D05 line"])
        )
        out.append(mdrow(["---"] * 7))
        for r in d["patterns"]:
            out.append(
                mdrow(
                    [
                        f"`{r['id']}`",
                        r["geometry"],
                        r["ink"],
                        r["opacity"],
                        r["meaning"],
                        r["consumers"],
                        f":{r['line']}",
                    ]
                )
            )
    else:
        raise SystemExit(f"unknown --emit {what}")
    return "\n".join(out)


def check_markers(text: str, counts: dict[str, Any], label: str) -> list[str]:
    errs: list[str] = []
    seen = 0
    for m in re.finditer(r"<!--\s*audit:([A-Za-z0-9_]+)=([^\s>]+)\s*-->", text):
        seen += 1
        name, val = m.group(1), m.group(2)
        if name not in counts:
            errs.append(f"{label}: marker {name}: no such number in the tool")
            continue
        if str(val) != str(counts[name]):
            errs.append(f"{label}: marker {name}={val}: the tool computes {counts[name]}")
    if label == "pack":
        for r in (
            "redline_rows",
            "behaviour_rules",
            "proposed_rules",
            "keymap_rows",
            "unregistered",
            "k_rows",
            "motion_rows",
            "motion_diff",
            "token_rows",
            "token_resolved",
            "token_proposed",
            "token_gap",
            "matrix_cells",
            "matrix_empty",
            "oq_total",
            "oq_unowned",
            "glyphs",
            "patterns",
            "icons_requested",
            "a_rows",
            "c_rows",
            "g_rows",
            "handoffs",
            "boards",
            "light_twins",
            "figures",
        ):
            if not re.search(rf"<!--\s*audit:{r}=", text):
                errs.append(f"{label}: required marker missing: {r}")
        if not seen:
            errs.append("no audit markers in the pack")
    return errs


def render_report(d: dict[str, Any]) -> str:
    c = d["counts"]
    km = d["keymap"]
    beh = d["behaviour"]
    out: list[str] = ["# E11-D09 hand-off audit", ""]
    put = out.append
    put(
        f"redlines: {c['redline_rows']} rows · D02 §2 parsed {c['redline_parsed']} · "
        f"tokens resolved {c['redline_tokens_resolved']} · typed-only {c['redline_typed_only']}"
    )
    for t in d["redline_tokens"]["typed_only"]:
        put(f"  typed-only: {t}")
    put(
        f"behaviour: rules {c['behaviour_rules']} · PROPOSED {c['proposed_rules']} · "
        f"worked cases {c['worked_cases']} · disagreements {c['worked_disagreements']} · "
        f"time ladder {c['time_ladder_steps']} steps"
    )
    for p in beh["price_cases"]:
        verdict = "agree" if p["agree"] else "DISAGREE"
        put(
            f"  §4.2 {p['name']}: s_L {p['sL']} s_M {p['sM']} labels {p['labels']} "
            f"spacing {p['spacing']} — D02 {p['expected']} — {verdict}"
        )
    for t in beh["time_cases"]:
        verdict = "agree" if t["agree"] else "DISAGREE"
        put(
            f"  §5.4 {t['px']} px/bar: {t['bars']} bars, step {t['step']} ({t['spacing']} px) — "
            f"D02 {t['expected']} — {verdict}"
        )
    lg = beh["legend"]
    verdict = "agree" if lg["agree"] else "DISAGREE"
    put(
        f"  §7.5 legend {lg['pane']} px / {lg['row']} px row, {lg['series']} series: "
        f"{lg['shown']} shown, +{lg['more']} more — {verdict}"
    )
    if km.get("absent"):
        put("keymap: " + D07_ABSENT)
    else:
        put(
            f"keymap: {c['keymap_rows']} / {km['design_bindings']} rows, "
            f"{c['keymap_missing']} missing, {c['keymap_extra']} extra · "
            f"literals {c['design_literals']} · unregistered: {c['unregistered']} · "
            f"K-rows applied {c['k_rows']} · announcement gaps {c['announcement_gaps']} · "
            f"Alt family {c['alt_family']}"
        )
        for u in km["unregistered"]:
            put(f"  unregistered: {u}")
        for k in km["k_rows"]:
            put(f"  {k['id']} → {k['owner']} (E11-D07 {k['line']})")
    animate = ", ".join(d["motion_coverage"]["animate_rows"])
    put(
        f"motion_rows: {c['motion_rows']}, motion_diff: {c['motion_diff']} · "
        f"animate under motion-safe {c['motion_animate']} (D06 :353 says 10): rows {animate}"
    )
    put(
        f"tokens: resolved {c['token_resolved']} · PROPOSED {c['token_proposed']} · "
        f"gap {c['token_gap']} · other {c['token_other']} · aliases {c['token_aliases']} · "
        f"`15` tokens {c['catalogue_tokens']} absent {c['catalogue_absent']}"
    )
    put(f"hex in spec/handoff: {c['hex_spec']} / {c['hex_handoff']}")
    put(
        f"matrix: surfaces {c['matrix_surfaces']} · states {c['matrix_states']} · "
        f"cells {c['matrix_cells']} · empty {c['matrix_empty']} · T2 cells {c['matrix_t2']} · "
        f"handoff_t1_diff {c['handoff_t1_diff']}"
    )
    put(
        f"oq: total {c['oq_total']} · answered {c['oq_answered']} · routed {c['oq_routed']} · "
        f"unowned {c['oq_unowned']} · source rows {c['oq_source_rows']} "
        f"({d['oq_check']['source_counts']}) · source-log rows missing: {c['oq_source_missing']}"
    )
    put(f"  owner histogram: {d['oq_check']['owner_histogram']}")
    put(f"glyphs: {c['glyphs']} — {''.join(d['glyphs']['union'])}")
    extras = "".join(d["glyphs"]["extras_vs_26"])
    missing = "".join(d["glyphs"]["missing_vs_26"])
    put(f"  extras vs `26` §3.7: {extras!r} · missing vs `26`: {missing!r}")
    put(
        f"assets: patterns {c['patterns']} · icons requested {c['icons_requested']} · "
        f"fonts {c['font_families']} families / {c['font_weights']} weights · "
        f"font files at base {c['font_files']} · icon files {c['icon_files']}"
    )
    per = " · ".join(
        f"{k} {v['rows']} rows / FAIL {v['fail']}"
        for k, v in d["contrast"].items()
        if isinstance(v, dict)
    )
    put(f"contrast (by import): {per} · total {c['contrast_rows']} / FAIL {c['contrast_fail']}")
    put(
        f"D07: F {c['d07_f_rows']} (live {c['d07_f_live']}) · G {c['d07_g_rows']} · "
        f"Q {c['d07_q_rows']} · T2 {c['d07_t2_rows']} · stops {c['d07_stops']} · "
        f"targets {c['d07_targets']} · hand-offs {c['d07_handoffs']}"
    )
    put(
        f"pack rows: A {c['a_rows']} · C {c['c_rows']} · G {c['g_rows']} · Q {c['q_rows']} · "
        f"hand-offs {c['handoffs']} · W-T {c['walkthrough_tasks']} · "
        f"dry-run log rows {c['dryrun_rows']} · owner items {c['owner_items']} · "
        f"perf rows {c['perf_rows']}"
    )
    fab = sum(1 for p in d["problems"] if "fabricated" in p)
    put(f"fabricated-session phrases: {fab}")
    put(f"problems: {len(d['problems'])}")
    for p in d["problems"]:
        put(f"  PROBLEM: {p}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    # a cp1252 console (the reference machine) needs UTF-8 for the glyph union and the arrows
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--emit", metavar="TABLE")
    ap.add_argument("--check", nargs="+", metavar="PATH")
    ap.add_argument("--draft", metavar="DRAFT")
    ap.add_argument("--figures", metavar="DIR")
    ns = ap.parse_args(argv)
    spec_path = Path(ns.check[0]) if ns.check else (PACK if PACK.exists() else None)
    handoff_path = (
        Path(ns.check[1])
        if ns.check and len(ns.check) > 1
        else (HANDOFF if HANDOFF.exists() else None)
    )
    d = build(spec_path, handoff_path)
    if ns.emit:
        print(emit(d, ns.emit))
        return 0
    if ns.figures:
        figs: Any = _load(TOOLS / "e11_d09_figures.py", "e11_d09_figures")
        written = figs.render_all(Path(ns.figures), d)
        for p in written:
            print(f"wrote {p}")
        return 0
    if ns.json:
        print(
            json.dumps(
                {k: v for k, v in d.items() if k not in ("keymap_rows", "matrix")},
                ensure_ascii=False,
                indent=1,
                default=str,
            )
        )
        return 0
    errs: list[str] = list(d["problems"])
    if ns.check:
        if d["keymap"].get("absent"):
            errs.append("--check: " + D07_ABSENT)
        if spec_path and spec_path.exists():
            errs += check_markers(read(spec_path), d["counts"], "pack")
        else:
            errs.append("--check: the pack is absent")
        if handoff_path and handoff_path.exists():
            errs += check_markers(read(handoff_path), d["counts"], "handoff")
        if ns.draft:
            errs += draft_gates(read(Path(ns.draft)))
    print(render_report(d))
    for e in errs:
        if e not in d["problems"]:
            print("CHECK:", e)
    if errs:
        print(f"FAIL: {len(errs)} gated problem(s)")
        return 1
    print("OK: every gate holds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
