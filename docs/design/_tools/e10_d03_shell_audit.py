"""E10-D03 shell chrome audit: every number the hi-fi spec and its boards quote, computed.

Standalone, offline, stdlib only (run with ``python3 -I``). Nine sections, each row labelled with
its source so a reviewer can re-grep it:

1. The chrome geometry from the primitive tokens (TopBar 48 + 32 = 80, StatusBar 48, the banner
   slot 32 / 40, the rails, the controls, the badge pill, the toast stack offsets, the canvas sizes
   at 1280x800 / 1920x1080 / 2560x1440 and the 125 % / 200 % CSS-px scale), gated equal to the
   numbers E10-D02 (``docs/design/E10/E10-D02.md``) and E15-D02 (``docs/design/E15/E15-D02.md``)
   state in their text; the two geometry constants without a token (the 3 px leading bar, the
   2 px ring offset) carry their source, and the toast width is printed as a PROPOSED value with
   its computed rationale (chars per line at type.ui.body), never as a token sum.
2. The badge pairs: E30-D01 section 3's ten rows reproduced to the hundredth (gated equal) plus this
   spec's surfaces, the 7:1 stretch verdict, and the greyscale luminance of every badge channel.
3. The measured matrix: every fg / bg pair the shell renders x dark / light / high-contrast,
   resolved as ``verify_tokens.py`` does and measured with ``contrast_check.contrast_ratio()``
   (imported, never re-implemented); the bar per role; the reproductions of E09-D09 section 11,
   E05-D02 CMP-039, E17-D02 section 14 and E39-D03 section 12 (gated equal).
4. The CVD rows: ``cvd_simulate.simulate`` / ``delta_e76`` under protanopia, deuteranopia and
   tritanopia (JND floor 5.0; reported, never gated: word, glyph and weight carry every state).
5. The live-value registry: every live value the spec annotates -> its REST operation or WS topic,
   checked by name against ``docs/plan/22-api-openapi.yaml`` and ``docs/plan/23-ws-protocol.md``
   section 15.9 as text (FPS and CPU have no source: a C-row).
6. Shipped-code parity: the five global bindings, the nine cheatsheet contexts, the bootstrap /
   connection / reachability member names and the constants, the eight ShellPort capability names
   and the browser adapter's seven reason sentences, the preload allow-list and the thick-ring
   preference setter, read from the base and matched in the spec.
7. Token bindings: every token the spec binds exists in the merged dark set, or its row is marked
   PROPOSED / G-row; ``color.text.disabled`` / ``opacity.disabled`` never in a T2 row; which pairs
   ``tools/contrast/pairs.mjs`` registers.
8. String gates on the committed files (the badge contract once, the T2 rule once, every one of
   the 18 matrix cells either "none" with no gated key or "T2 per §10.1" with no "not T2", every
   section 1.3 row rendered 2a / 2b, the view-as leg first and never on the C-2.6 protective
   writes, the SCR-157 fallback block on SCR-159's offline and tailnet variants, no aggregate
   cluster line in a gated or board row, Release T2 when engaged, every PROPOSED ``health.*``
   sentence <= 60 characters with a full stop, the SCR-157 phrase, no "same as dark", no
   placeholders, no chrome trading word, no local path, no Penpot host (a generic pattern; no
   host named), no pageLink, no closing keyword with an issue number, every planned board
   PENDING, the nine catalogue pointer lines, every ``US-…`` id cited exists in
   ``docs/plan/11-user-stories.md``).
9. The counts the boards and the PR draft quote (``--json`` feeds the local check-nums).

Usage: python3 -I docs/design/_tools/e10_d03_shell_audit.py [--json] [--check]
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
SPEC = ROOT / "docs" / "design" / "E10" / "E10-D03.md"
D02_SPEC = ROOT / "docs" / "design" / "E10" / "E10-D02.md"
E15_SPEC = ROOT / "docs" / "design" / "E15" / "E15-D02.md"
CATALOGUE = ROOT / "docs" / "plan" / "14-screens-catalogue.md"
USER_STORIES = ROOT / "docs" / "plan" / "11-user-stories.md"
API = ROOT / "docs" / "plan" / "22-api-openapi.yaml"
WS = ROOT / "docs" / "plan" / "23-ws-protocol.md"
PAIRS_MJS = ROOT / "tools" / "contrast" / "pairs.mjs"
WEB = ROOT / "apps" / "web" / "src"
DESKTOP = ROOT / "apps" / "desktop" / "src"


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

THEMES = ("dark", "light", "high-contrast")
PRIM: dict[str, Any] = dict(verify.load(verify.PRIMITIVES))
JND = 5.0


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def prim(name: str) -> int:
    return int(PRIM[name]["$value"])


def theme_tokens(theme: str) -> dict[str, Any]:
    allt: dict[str, Any] = dict(PRIM)
    allt.update(verify.merged_set(verify.THEMES[theme]))
    return allt


def resolve_theme(theme: str) -> dict[str, str]:
    allt = theme_tokens(theme)
    out: dict[str, str] = {}
    for name, tok in allt.items():
        if tok.get("$type") == "color":
            out[name] = str(verify.resolve(tok["$value"], allt)).upper()
    return out


def themes() -> dict[str, dict[str, str]]:
    return {t: resolve_theme(t) for t in THEMES}


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def ratio(th: dict[str, str], fg: str, bg: str) -> float:
    return float(contrast_check.contrast_ratio(hex_rgb(th[fg]), hex_rgb(th[bg])))


def fmt(v: float) -> str:
    return f"{v:.2f}"


def luma8(h: str) -> int:
    r, g, b = hex_rgb(h)
    return round(0.2126 * r + 0.7152 * g + 0.0722 * b)


def section(text: str, start: str, end: str | None) -> str:
    a = text.find(start)
    if a < 0:
        return ""
    b = text.find(end, a + len(start)) if end else -1
    return text[a:] if b < 0 else text[a:b]


# --- 1. the chrome geometry ---------------------------------------------------------------------
# Two geometry constants have no token; each carries the merged spec that fixes it.
BAR_LEADING = 3
BAR_LEADING_SOURCE = "E15-D02 §5.2 :278 — the current workspace's 3 px leading bar (no token)"
RING_OFFSET = 2
RING_OFFSET_SOURCE = (
    "E05-D02 CMP-039 :1350 — a 2 px ring at a 2 px offset (a geometry constant, no token)"
)
# The toast width is a PROPOSED value (spec §7, G-row G11): no size.toast.width token exists, so
# it is printed with its rationale (the characters a line holds at type.ui.body), never as a token
# sum.
TOAST_WIDTH = 360
TOAST_WIDTH_STATUS = "PROPOSED size.toast.width — no token exists (G-row G11)"
TOAST_BODY_PX = 13  # type.ui.body
TOAST_EM = 0.56  # the board-geometry rule's conservative Inter advance per character (estH)
TOAST_SENTENCES = (
    "Order accepted · id 42f",
    "Update available",
    "3 more notifications",
    "Something went wrong in the app — copy details and report a bug.",
    "Too many panes for this connection — close some; refresh rates were reduced automatically.",
)


def toast_rationale(s2: int, s3: int) -> dict[str, Any]:
    glyph, dismiss = prim("size.icon.md"), prim("size.target.min")
    text_w = TOAST_WIDTH - 2 * s3 - glyph - s2 - dismiss - s2
    per_line = int(text_w // (TOAST_BODY_PX * TOAST_EM))
    lines = {s: -(-len(s) // per_line) for s in TOAST_SENTENCES}
    return {
        "text_column_px": text_w,
        "chars_per_line": per_line,
        "lines_per_sentence": lines,
        "note": (
            "the longest shipped toast sentence (E17-D02 §10 I) wraps to three lines; "
            "the rest to one or two"
        ),
    }


def geometry_report(fails: list[str]) -> dict[str, Any]:
    c_compact, c_comf = prim("size.control.compact"), prim("size.control.comfortable")
    row_compact, row_comf = prim("size.row.compact"), prim("size.row.comfortable")
    s1, s2, s3, s4 = prim("space.1"), prim("space.2"), prim("space.3"), prim("space.4")
    top_row1 = c_comf + 2 * s2  # a 32 px control row with space.2 above and below = 48
    top_row2 = row_comf  # the HealthChips row is one comfortable row = 32
    top_bar = top_row1 + top_row2
    status_bar = c_comf + 2 * s2
    banner = {"compact": row_compact + 2 * s1, "comfortable": row_comf + 2 * s1}
    d02, e15 = read(D02_SPEC), read(E15_SPEC)
    m = re.search(r"\*\*NavRail\*\* w (\d+) \((\d+) collapsed\)", d02)
    rail_expanded = int(m.group(1)) if m else 0
    rail_collapsed = c_comf + 2 * s4  # a 32 px item with space.4 each side = 64
    m2 = re.search(r"\*\*RightRail\*\* w (\d+)", d02)
    right_open = int(m2.group(1)) if m2 else 0
    m3 = re.search(r"the (\d+) px \(a (\d+) px launcher and (\d+) px each side\)", e15)
    launcher = int(m3.group(2)) if m3 else 0
    right_strip = launcher + 2 * s1  # E15-D02 OQ-A: a 40 px launcher and space.1 each side = 48
    geo: dict[str, Any] = {
        "top_bar": top_bar,
        "top_row1": top_row1,
        "top_row2": top_row2,
        "status_bar": status_bar,
        "banner": banner,
        "rail": {"expanded": rail_expanded, "collapsed": rail_collapsed},
        "right_rail": {"open": right_open, "strip": right_strip, "launcher": launcher},
        "control": {"compact": c_compact, "comfortable": c_comf},
        "row": {"compact": row_compact, "comfortable": row_comf},
        "glyph": prim("size.icon.md"),
        "lock_badge": prim("size.icon.sm"),
        "target_min": prim("size.target.min"),
        "badge": {
            "pill_compact": prim("size.icon.lg"),
            "pill_comfortable": c_compact,
            "border": prim("border.thick"),
            "glyph": prim("size.icon.md"),
            "pad_x": s2,
            "bar_leading": BAR_LEADING,
            "bar_leading_source": BAR_LEADING_SOURCE,
        },
        "toast": {
            "width": TOAST_WIDTH,
            "width_status": TOAST_WIDTH_STATUS,
            "width_rationale": toast_rationale(s2, s3),
            "step_compact": s2,
            "step_comfortable": s3,
            "offsets_compact": [0, s2, 2 * s2],
            "offsets_comfortable": [0, s3, 2 * s3],
            "header_row": s3 + prim("size.icon.md"),
            "header_row_source": "space.inset.md + size.icon: the visible row of an older toast",
            "margin": s4,
            "max": 3,
            "error_edge": prim("border.thick"),
        },
        "ring": {
            "width": prim("border.focus"),
            "offset": RING_OFFSET,
            "offset_source": RING_OFFSET_SOURCE,
        },
    }
    sizes = {"1280x800": (1280, 800), "1920x1080": (1920, 1080), "2560x1440": (2560, 1440)}
    canvas: dict[str, dict[str, list[int]]] = {}
    for key, (w, h) in sizes.items():
        ch = h - top_bar - status_bar
        canvas[key] = {
            "collapsed_strip": [w - rail_collapsed - right_strip, ch],
            "expanded_strip": [w - rail_expanded - right_strip, ch],
            "expanded_drawer": [w - rail_expanded - right_open, ch],
            "with_banner_compact": [w - rail_collapsed - right_strip, ch - banner["compact"]],
        }
    geo["canvas"] = canvas
    scale: dict[str, dict[str, Any]] = {}
    for label, f in (("125", 1.25), ("200", 2.0)):
        scale[label] = {
            "top_bar": round(top_bar * f),
            "status_bar": round(status_bar * f),
            "banner_compact": round(banner["compact"] * f),
            "row_compact": round(row_compact * f),
            "control_compact": round(c_compact * f),
            "glyph": round(prim("size.icon.md") * f),
            "viewport_css_1280x800": [round(1280 / f), round(800 / f)],
        }
    geo["scale"] = scale
    gates: dict[str, bool] = {}
    m4 = re.search(
        r"\*\*TopBar\*\* h (\d+) \(a (\d+) px first row and the (\d+) px HealthChips row\)", d02
    )
    gates["d02_topbar"] = m4 is not None and [int(x) for x in m4.groups()] == [
        top_bar,
        top_row1,
        top_row2,
    ]
    m5 = re.search(r"\*\*StatusBar\*\* h (\d+)", d02)
    gates["d02_statusbar"] = m5 is not None and int(m5.group(1)) == status_bar
    gates["d02_rail_collapsed"] = m is not None and int(m.group(2)) == rail_collapsed
    m6 = re.search(r"\| TopBar \(ENV badge[^|]*\|\s*E10\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|", e15)
    gates["e15_topbar"] = m6 is not None and [int(x) for x in m6.groups()] == [top_bar, top_bar]
    m7 = re.search(r"\| SCR-153 banner\s*\|\s*E10, E15\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|", e15)
    gates["e15_banner"] = m7 is not None and [int(x) for x in m7.groups()] == [
        banner["compact"],
        banner["comfortable"],
    ]
    m8 = re.search(r"\| StatusBar \([^|]*\|\s*E10\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|", e15)
    gates["e15_statusbar"] = m8 is not None and [int(x) for x in m8.groups()] == [
        status_bar,
        status_bar,
    ]
    c1280, c1920 = canvas["1280x800"]["collapsed_strip"], canvas["1920x1080"]["collapsed_strip"]
    gates["e15_canvas_1280"] = f"{c1280[0]}\u00d7{c1280[1]}" in e15
    gates["e15_canvas_1920"] = f"{c1920[0]}\u00d7{c1920[1]}" in e15
    gates["e15_strip_48"] = m3 is not None and int(m3.group(1)) == right_strip
    fails += [f"geometry gate failed: {k}" for k, ok in gates.items() if not ok]
    geo["gates"] = gates
    return geo


# --- 2. the badge pairs (E30-D01 section 3 reproduced; the environment-signal surfaces) ------
def rows(txt: str, sep: str = "|") -> list[list[str]]:
    """Pipe rows; a line starting with ``~`` continues the previous row (long token names)."""
    acc: list[str] = []
    for ln in txt.strip().splitlines():
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        if ln.lstrip().startswith("~"):
            acc[-1] += " " + ln.lstrip()[1:].strip()
        else:
            acc.append(ln.strip())
    return [[c.strip() for c in ln.split(sep)] for ln in acc]


# element | fg | bg | role | dark | light | hc  (E30-D01 section 3, to the hundredth; gated equal)
E30_D01_TXT = """
env.live as text on app | color.env.live | color.surface.app | text | 4.94 | 5.20 | 4.94
env.live as text on raised | color.env.live | color.surface.raised | text | 4.42 | 4.51 | 4.42
env.demo as text on app | color.env.demo | color.surface.app | text | 4.07 | 4.76 | 4.07
env.demo as text on raised | color.env.demo | color.surface.raised | text | 3.64 | 4.13 | 3.64
white on the env.live fill | palette.white | color.env.live | text | 3.91 | 5.20 | 3.91
white on the env.demo fill | palette.white | color.env.demo | text | 4.76 | 4.76 | 4.76
text.on-action on the env.live fill | color.text.on-action | color.env.live
  ~ | text | 3.91 | 5.20 | 4.94
text.on-action on the env.demo fill | color.text.on-action | color.env.demo
  ~ | text | 4.76 | 4.76 | 4.07
text.primary on raised: the neutral pill | color.text.primary | color.surface.raised
  ~ | badge | 14.35 | 15.62 | 16.25
env.live as a border on raised | color.env.live | color.surface.raised | ui | 4.42 | 4.51 | 4.42
"""
# element | fg | bg | role  (this spec's badge surfaces)
D03_BADGE_TXT = """
DEMO border and outline dot on the pill | color.env.demo | color.surface.raised | ui
LIVE border and dot on app | color.env.live | color.surface.app | ui
DEMO border and dot on app | color.env.demo | color.surface.app | ui
LIVE border on sunken (StatusBar pill edge) | color.env.live | color.surface.sunken | ui
DEMO border on sunken | color.env.demo | color.surface.sunken | ui
LIVE border on overlay (dialog restatement) | color.env.live | color.surface.overlay | ui
DEMO border on overlay | color.env.demo | color.surface.overlay | ui
the unconfirmed caption beside the word | color.text.secondary | color.surface.raised | text
the raised pill against the StatusBar | color.surface.raised | color.surface.sunken | structure
the raised pill against the app chrome | color.surface.raised | color.surface.app | structure
"""
E30_D01_ROWS = rows(E30_D01_TXT)
D03_BADGE_ROWS = rows(D03_BADGE_TXT)
BAR: dict[str, float | None] = {
    "text": 4.5,
    "ui": 3.0,
    "badge": 7.0,
    "structure": None,
    "rejected-text": None,
    "rejected-ui": None,
}
BADGE_CHANNELS = (
    "color.text.primary",
    "color.surface.raised",
    "color.env.live",
    "color.env.demo",
    "color.text.secondary",
)


def verdict(role: str, ratios: dict[str, float]) -> tuple[str, list[str]]:
    bar = BAR.get(role)
    if bar is None:
        if role == "structure":
            return "structure (not gated)", []
        floor = 4.5 if "text" in role else 3.0
        under = [t for t in THEMES if ratios[t] < floor]
        return (
            f"rejected (reported; under {floor} in {', '.join(under)})" if under else "rejected"
        ), []
    failing = [t for t in THEMES if ratios[t] < bar]
    return ("FAIL " + ", ".join(failing)) if failing else "PASS", failing


def badge_report(fails: list[str], th: dict[str, dict[str, str]]) -> dict[str, Any]:
    out: list[dict[str, Any]] = []
    repro_ok = True
    for element, fg, bg, role, *expected in E30_D01_ROWS:
        ratios = {t: ratio(th[t], fg, bg) for t in THEMES}
        ok = [fmt(ratios[t]) for t in THEMES] == expected
        repro_ok = repro_ok and ok
        out.append({"element": element, "fg": fg, "bg": bg, "role": role, "ratios": ratios})
        out[-1] |= {"source": "E30-D01 §3", "reproduced": ok, "expected": expected}
    if not repro_ok:
        fails.append("E30-D01 §3 badge rows not reproduced to the hundredth")
    for element, fg, bg, role in D03_BADGE_ROWS:
        ratios = {t: ratio(th[t], fg, bg) for t in THEMES}
        v, failing = verdict(role, ratios)
        if failing:
            fails.append(f"badge pair {fg} on {bg} ({role}) under its bar: {failing}")
        out.append({"element": element, "fg": fg, "bg": bg, "role": role, "ratios": ratios})
        out[-1] |= {"source": "E10-D03 §3", "verdict": v}
    word = {t: ratio(th[t], "color.text.primary", "color.surface.raised") for t in THEMES}
    stretch = all(v >= 7.0 for v in word.values())
    borders = {
        t: min(
            ratio(th[t], e, "color.surface.raised") for e in ("color.env.live", "color.env.demo")
        )
        for t in THEMES
    }
    border_ok = all(v >= 3.0 for v in borders.values())
    if not stretch or not border_ok:
        fails.append("badge stretch (word >= 7:1) or border bar (>= 3:1) failed")
    lum: dict[str, dict[str, Any]] = {}
    for t in THEMES:
        lum[t] = {}
        for c in BADGE_CHANNELS:
            hx = th[t][c]
            lum[t][c] = {"hex": hx, "luma8": luma8(hx)}
            lum[t][c]["luminance"] = round(float(cvd.relative_luminance(hx)), 4)
        live, demo = lum[t]["color.env.live"]["luma8"], lum[t]["color.env.demo"]["luma8"]
        lum[t]["live_minus_demo_luma8"] = live - demo
        word8, fill8 = (
            lum[t]["color.text.primary"]["luma8"],
            lum[t]["color.surface.raised"]["luma8"],
        )
        lum[t]["word_minus_fill_luma8"] = word8 - fill8
    return {
        "rows": out,
        "n": len(out),
        "e30_rows": len(E30_D01_ROWS),
        "d03_rows": len(D03_BADGE_ROWS),
        "stretch_word_7": stretch,
        "border_3": border_ok,
        "luminance": lum,
    }


# --- 3. the measured matrix ---------------------------------------------------------------------
# element | fg | bg | role | where in the spec
PAIRS_TXT = """
TopBar labels; cluster outline labels; Kbd | color.text.primary | color.surface.raised | text | §2
TopBar secondary; panel notice; T2 reason | color.text.secondary | color.surface.raised
  ~ | text | §2 §10
T2 label and lock glyph; chips caption | color.text.tertiary | color.surface.raised | text | §4 §10
hovered item or chip label | color.text.primary | color.surface.hover | text | §5
current NavRail item label | color.text.primary | color.surface.selected | text | §5
count caption on the current item | color.text.secondary | color.surface.selected | text | §5
the 3 px bar against the current fill | color.border.selected | color.surface.selected | ui | §5
the 3 px bar against the rail | color.border.selected | color.surface.raised | ui | §5
count badge word; info toast title | color.text.primary | color.status.info.subtle | text | §5 §7
count badge and info toast glyph | color.status.info.strong | color.status.info.subtle | ui | §5 §7
ENV badge word DEMO / LIVE (7:1 stretch) | color.text.primary | color.surface.raised | badge | §3
ENV LIVE border and filled dot | color.env.live | color.surface.raised | ui | §3
ENV DEMO border and outline dot | color.env.demo | color.surface.raised | ui | §3
REJECTED: LIVE as coloured text | color.env.live | color.surface.raised | rejected-text | §3
REJECTED: DEMO as coloured text | color.env.demo | color.surface.raised | rejected-text | §3
REJECTED: white on the env.live fill | palette.white | color.env.live | rejected-text | §3
FREEZE… label on the danger fill (E39) | color.text.on-action | color.status.danger.default
  ~ | text | §2
cluster outline danger hairline | color.status.danger.default | color.surface.raised | ui | §2
danger accent against the app chrome | color.status.danger.default | color.surface.app | ui | §2
T2 hairline on the raised host | color.border.default | color.surface.raised | structure | §10
Kbd border on raised | color.border.strong | color.surface.raised | structure | §6
warn glyph; conflict chip; palette glyph | color.status.warning.strong | color.surface.raised
  ~ | ui | §2 §6
HealthChips error glyph | color.status.danger.strong | color.surface.raised | ui | §2
HealthChips ok glyph | color.status.success.strong | color.surface.raised | ui | §2
feed chip Delayed glyph (E17-D02) | color.status.info.default | color.surface.raised | ui | §2
StatusBar text on sunken (CMP-208) | color.text.primary | color.surface.sunken | text | §2
StatusBar secondary on sunken | color.text.secondary | color.surface.sunken | text | §2
StatusBar caption on sunken | color.text.tertiary | color.surface.sunken | text | §2
StatusBar disconnected dot | color.data-confidence.disconnected.indicator
  ~ | color.surface.sunken | ui | §2
StatusBar alt on app; SCR-159 heading | color.text.primary | color.surface.app | text | §2 §9
focus ring on app | color.focus.ring | color.surface.app | ui | §10
focus ring on canvas | color.focus.ring | color.surface.canvas | ui | §10
focus ring on raised | color.focus.ring | color.surface.raised | ui | §10
focus ring on overlay | color.focus.ring | color.surface.overlay | ui | §10
focus ring on hover | color.focus.ring | color.surface.hover | ui | §10
focus ring on selected | color.focus.ring | color.surface.selected | ui | §10
focus ring on sunken | color.focus.ring | color.surface.sunken | ui | §10
SkipLink label; primary button label | color.text.on-action | color.action.primary.default
  ~ | text | §10
SkipLink fill against the app chrome | color.action.primary.default | color.surface.app | ui | §10
palette rows; dialog title; menu items | color.text.primary | color.surface.overlay | text | §6 §9
palette group headers; dialog captions | color.text.tertiary | color.surface.overlay | text | §6
palette T2 reason; dialog body; echo | color.text.secondary | color.surface.overlay | text | §6 §10
palette destructive glyph on overlay | color.status.warning.strong | color.surface.overlay | ui | §6
success toast title | color.text.primary | color.status.success.subtle | text | §7
success toast glyph | color.status.success.strong | color.status.success.subtle | ui | §7
warning toast title; CMP-092 warning | color.text.primary | color.status.warning.subtle
  ~ | text | §7 §9
warning toast glyph; CMP-092 glyph | color.status.warning.strong | color.status.warning.subtle
  ~ | ui | §7 §9
error toast title; FROZEN title (E39) | color.text.primary | color.status.danger.subtle
  ~ | text | §7 §4
error toast glyph; FROZEN glyph | color.status.danger.strong | color.status.danger.subtle
  ~ | ui | §7 §4
error toast body; CMP-117 body | color.text.secondary | color.status.danger.subtle | text | §7 §4
warning toast body; stillWorks line | color.text.secondary | color.status.warning.subtle
  ~ | text | §7 §9
success toast body | color.text.secondary | color.status.success.subtle | text | §7
info toast body | color.text.secondary | color.status.info.subtle | text | §7
error toast 2 px edge; Delete… glyph | color.status.danger.strong | color.surface.overlay
  ~ | ui | §7 §5
toast subtle fill against the stack | color.status.danger.subtle | color.surface.overlay
  ~ | structure | §7
dialog hairline on overlay | color.border.default | color.surface.overlay | structure | §9
SCR-159 body; CMP-091 route body | color.text.secondary | color.surface.app | text | §9
SCR-159 link; the 404 Try links | color.text.link | color.surface.app | text | §9
BuildFooter line (text.muted is no token) | color.text.tertiary | color.surface.app | text | §9
CMP-091 panel heading | color.text.primary | color.surface.canvas | text | §9
CMP-091 danger glyph on the panel | color.status.danger.strong | color.surface.canvas | ui | §9
CMP-091 error id (mono) | color.text.tertiary | color.surface.canvas | text | §9
CMP-091 body; panel notice on canvas | color.text.secondary | color.surface.canvas | text | §9 §10
title bar more and close glyphs | color.text.secondary | color.surface.raised | ui | §8
REJECTED: text.disabled on raised | color.text.disabled | color.surface.raised | rejected-text | §10
REJECTED: text.disabled on canvas | color.text.disabled | color.surface.canvas | rejected-text | §10
REJECTED: text.disabled on app | color.text.disabled | color.surface.app | rejected-text | §10
Delete… menu label (CMP-041 danger item) | color.text.primary | color.surface.overlay | text | §5
REJECTED: danger.default as the Delete… label | color.status.danger.default
  ~ | color.surface.overlay | rejected-text | §5
"""
# fg | bg | dark | light | hc | source  (merged specs' values; gated equal to the hundredth)
REPRO_TXT = """
color.text.tertiary | color.surface.raised | 5.62 | 5.92 | 11.21 | E09-D09 §11
color.text.tertiary | color.surface.canvas | 5.96 | 6.36 | 11.87 | E09-D09 §11
color.text.tertiary | color.surface.app | 6.29 | 6.81 | 12.54 | E09-D09 §11
color.text.disabled | color.surface.raised | 2.86 | 3.74 | 2.86 | E09-D09 §11 REJECTED
color.text.disabled | color.surface.canvas | 3.03 | 4.02 | 3.03 | E09-D09 §11 REJECTED
color.text.disabled | color.surface.app | 3.20 | 4.31 | 3.20 | E09-D09 §11 REJECTED
color.text.secondary | color.surface.canvas | 9.33 | 9.65 | 15.20 | E09-D09 §11
color.text.secondary | color.surface.overlay | 8.14 | 8.26 | 13.27 | E09-D09 §11; E17-D02 §14
color.text.secondary | color.surface.app | 9.85 | 10.35 | 16.06 | E09-D09 §11
color.text.primary | color.surface.app | 16.06 | 17.99 | 18.18 | E09-D09 §11; E39-D03 §12
color.text.link | color.surface.app | 7.45 | 6.75 | 7.45 | E09-D09 §11
color.text.primary | color.surface.raised | 14.35 | 15.62 | 16.25 | E30-D01 §3; E17-D02 §14
color.text.secondary | color.surface.raised | 8.81 | 8.98 | 14.35 | E17-D02 §14; E39-D03 §12
color.text.primary | color.surface.hover | 12.22 | 14.37 | 13.83 | E17-D02 §14; E39-D03 §12
color.text.primary | color.surface.overlay | 13.27 | 14.37 | 15.02 | E39-D03 §12
color.text.tertiary | color.surface.overlay | 5.20 | 5.44 | 10.36 | E39-D03 §12
color.text.primary | color.surface.selected | 10.17 | 12.82 | 11.51 | E05-D02 a11y audit §4
color.text.secondary | color.surface.selected | 6.24 | 7.37 | 10.17 | E39-D03 §12
color.text.primary | color.surface.canvas | 15.20 | 16.78 | 17.21 | E17-D02 §14
color.status.danger.strong | color.surface.canvas | 9.87 | 4.41 | 9.87 | E17-D02 §14
color.text.on-action | color.status.danger.default | 5.05 | 10.31 | 4.54 | E39-D03 §12
color.text.on-action | color.action.primary.default | 4.76 | 4.76 | 7.45 | E17-D02 §14; E39-D03 §12
color.status.danger.default | color.surface.raised | 3.43 | 8.95 | 4.05 | E39-D03 §12
color.status.danger.default | color.surface.app | 3.83 | 10.31 | 4.54 | E39-D03 §12
color.status.warning.strong | color.surface.raised | 11.00 | 4.11 | 11.00 | E17-D02 §14
color.status.danger.strong | color.surface.raised | 9.32 | 4.11 | 9.32 | E17-D02 §14
color.text.primary | color.status.danger.subtle | 12.06 | 14.64 | 13.66 | E17-D02 §14; E39-D03 §12
color.text.secondary | color.status.danger.subtle | 7.40 | 8.42 | 12.06 | E17-D02 §14
color.status.danger.strong | color.status.danger.subtle | 7.83 | 3.85 | 7.83 | E17-D02 §14
color.text.primary | color.status.warning.subtle | 9.86 | 15.62 | 11.16 | E17-D02 §14; E09-D09 §11
color.text.secondary | color.status.warning.subtle | 6.05 | 8.98 | 9.86 | E17-D02 §14
color.status.warning.strong | color.status.warning.subtle | 7.56 | 4.11 | 7.56
  ~ | E17-D02 §14; E09-D09 §11
color.text.primary | color.status.success.subtle | 10.21 | 15.41 | 11.56 | E17-D02 §14
color.text.secondary | color.status.success.subtle | 6.27 | 8.86 | 10.21 | E17-D02 §14
color.status.success.strong | color.status.success.subtle | 6.69 | 3.34 | 6.69 | E17-D02 §14
color.text.primary | color.status.info.subtle | 10.74 | 15.44 | 12.16 | E17-D02 §14
color.text.secondary | color.status.info.subtle | 6.59 | 8.88 | 10.74 | E17-D02 §14
color.status.info.default | color.status.info.subtle | 4.64 | 3.44 | 4.64 | E17-D02 §14
color.data-confidence.disconnected.indicator | color.surface.sunken
  ~ | 4.16 | 7.35 | 4.92 | E17-D02 §14
color.border.default | color.surface.raised | 1.41 | 1.22 | 2.86 | E39-D03 §12
color.border.strong | color.surface.raised | 1.80 | 1.46 | 1.80 | E39-D03 §12
color.border.default | color.surface.overlay | 1.30 | 1.12 | 2.64 | E39-D03 §12
color.focus.ring | color.surface.app | 7.45 | 6.75 | 19.35 | E39-D03 §12
color.focus.ring | color.surface.overlay | 6.15 | 5.39 | 15.99 | E39-D03 §12
color.focus.ring | color.surface.raised | 6.66 | 5.86 | 17.30 | E17-D02 §14; E39-D03 §12
color.env.live | color.surface.raised | 4.42 | 4.51 | 4.42 | E30-D01 §3; E39-D03 §12
color.env.demo | color.surface.raised | 3.64 | 4.13 | 3.64 | E30-D01 §3; E39-D03 §12
palette.white | color.env.live | 3.91 | 5.20 | 3.91 | E30-D01 §3
"""
PAIRS = rows(PAIRS_TXT)
REPRO: dict[tuple[str, str], tuple[list[str], str]] = {
    (r[0], r[1]): (r[2:5], r[5]) for r in rows(REPRO_TXT)
}
RING_TIERS = ("app", "canvas", "raised", "overlay", "hover", "selected", "sunken")
RING_MIN = {"dark": "4.72", "light": "4.81", "high-contrast": "12.26"}  # E05-D02 CMP-039
SHELL_TOKENS_TXT = """
color.surface.app color.surface.canvas color.surface.raised color.surface.overlay
color.surface.sunken color.surface.hover color.surface.selected
color.border.default color.border.strong color.border.selected
color.text.primary color.text.secondary color.text.tertiary color.text.link
color.text.on-action color.text.inverse color.env.demo color.env.live color.focus.ring
color.action.primary.default color.action.selected
color.status.danger.subtle color.status.danger.default color.status.danger.strong
color.status.warning.subtle color.status.warning.default color.status.warning.strong
color.status.success.subtle color.status.success.default color.status.success.strong
color.status.info.subtle color.status.info.default color.status.info.strong
color.data-confidence.disconnected.indicator color.data-confidence.reconnecting.indicator
color.data-confidence.stale.indicator palette.white
"""
SHELL_TOKENS = tuple(SHELL_TOKENS_TXT.split())


def matrix_report(fails: list[str], th: dict[str, dict[str, str]]) -> dict[str, Any]:
    pairs: list[dict[str, Any]] = []
    gated = structure = rejected = 0
    failing_by_theme = dict.fromkeys(THEMES, 0)
    repro_fail: list[str] = []
    for element, fg, bg, role, use in PAIRS:
        ratios = {t: ratio(th[t], fg, bg) for t in THEMES}
        v, failing = verdict(role, ratios)
        if BAR.get(role) is not None:
            gated += 1
            for t in failing:
                failing_by_theme[t] += 1
            if failing:
                fails.append(f"contrast {fg} on {bg} ({role}) under {BAR[role]}: {failing}")
        elif role == "structure":
            structure += 1
        else:
            rejected += 1
        rep = REPRO.get((fg, bg))
        reproduced: bool | None = None
        if rep is not None:
            got = [fmt(ratios[t]) for t in THEMES]
            reproduced = got == rep[0]
            if not reproduced:
                repro_fail.append(f"{fg} on {bg}: {rep[1]} expects {rep[0]}, got {got}")
        row: dict[str, Any] = {"element": element, "fg": fg, "bg": bg, "role": role, "use": use}
        row |= {"bar": BAR.get(role), "ratios": ratios, "verdict": v, "reproduced": reproduced}
        row["source"] = rep[1] if rep else "E10-D03 §11"
        pairs.append(row)
    fails += [f"reproduction off: {s}" for s in repro_fail]
    ring = {
        t: {tier: ratio(th[t], "color.focus.ring", f"color.surface.{tier}") for tier in RING_TIERS}
        for t in THEMES
    }
    ring_min = {t: fmt(min(ring[t].values())) for t in THEMES}
    if ring_min != RING_MIN:
        fails.append(f"CMP-039 ring minima not reproduced: {ring_min} vs {RING_MIN}")
    tokens = {t: {k: th[t][k] for k in SHELL_TOKENS} for t in THEMES}
    hc_overrides = set(verify.load("semantic-hc.tokens.json").keys())
    no_hc = sorted(k for k in SHELL_TOKENS if k.startswith("color.") and k not in hc_overrides)
    return {
        "pairs": pairs,
        "rows": len(pairs),
        "gated": gated,
        "structure": structure,
        "rejected": rejected,
        "failing": failing_by_theme,
        "repro_rows": sum(1 for p in pairs if p["reproduced"] is not None),
        "repro_fail": repro_fail,
        "ring": ring,
        "ring_min": ring_min,
        "tokens": tokens,
        "no_hc_override": no_hc,
    }


# --- 4. the CVD rows ----------------------------------------------------------------------------
DEFICIENCIES = ("protanopia", "deuteranopia", "tritanopia")
# what | a | b
CVD_TXT = """
ENV borders: DEMO vs LIVE | color.env.demo | color.env.live
danger.default vs env.live (E30-D01 F5) | color.status.danger.default | color.env.live
sell.default vs env.live (E30-D01 F5) | color.sell.default | color.env.live
danger.default vs sell.default | color.status.danger.default | color.sell.default
strong tones: danger vs warning | color.status.danger.strong | color.status.warning.strong
strong tones: danger vs success | color.status.danger.strong | color.status.success.strong
strong tones: danger vs info | color.status.danger.strong | color.status.info.strong
strong tones: warning vs success | color.status.warning.strong | color.status.success.strong
strong tones: warning vs info | color.status.warning.strong | color.status.info.strong
strong tones: success vs info | color.status.success.strong | color.status.info.strong
chip glyph tones: success vs warning | color.status.success.strong | color.status.warning.strong
feed indicators: stale vs disconnected | color.data-confidence.stale.indicator
  ~ | color.data-confidence.disconnected.indicator
feed indicators: stale vs reconnecting | color.data-confidence.stale.indicator
  ~ | color.data-confidence.reconnecting.indicator
feed indicators: disconnected vs reconnecting | color.data-confidence.disconnected.indicator
  ~ | color.data-confidence.reconnecting.indicator
"""
CVD_ROWS = rows(CVD_TXT)


def cvd_report(fails: list[str], th: dict[str, dict[str, str]]) -> dict[str, Any]:
    out: list[dict[str, Any]] = []
    for what, a, b in CVD_ROWS:
        per_theme: dict[str, Any] = {}
        for t in ("dark", "light"):
            ha, hb = th[t][a], th[t][b]
            de: dict[str, float] = {"normal": round(float(cvd.delta_e76(ha, hb)), 2)}
            for d in DEFICIENCIES:
                de[d] = round(float(cvd.delta_e76(cvd.simulate(ha, d), cvd.simulate(hb, d))), 2)
            per_theme[t] = {"a": ha, "b": hb, "identical": ha == hb, "delta_e": de}
            per_theme[t]["contrast"] = round(ratio(th[t], a, b), 2)
            per_theme[t]["under_jnd"] = sorted(k for k, v in de.items() if v < JND)
        out.append({"what": what, "a": a, "b": b, "themes": per_theme})
    f5 = out[1]["themes"]["dark"]
    f5_ok = fmt(f5["contrast"]) == "1.29"
    if not f5_ok:
        fails.append(f"E30-D01 F5 pair not reproduced: contrast {f5['contrast']} (expected 1.29)")
    return {
        "rows": out,
        "n": len(out),
        "jnd": JND,
        "f5_contrast": f5["contrast"],
        "f5_delta_e_normal": f5["delta_e"]["normal"],
        "f5_reproduced": f5_ok,
        "sell_equals_live_dark": out[2]["themes"]["dark"]["identical"],
    }


# --- 5. the live-value registry -----------------------------------------------------------------
# value | source | kind (rest | ws | ws-topic | chart | none) | role cut
REGISTRY_TXT = """
ENV badge word, weight, glyph (CMP-074 / 075 / 215) | getMe | rest | session.environment, every role
account scope (CMP-105) | listExchangeAccounts | rest | the granted accounts only
trade groups in the account scope | listTradeGroups | rest | the granted groups only
workspace switcher; the NavRail's workspaces | listWorkspaces | rest | own workspaces
theme, density, text scale, motion, high contrast | getMyPreferences | rest | own settings
the palette's recency (last five) | updateMyPreferences | rest | own settings
the current bindings (SCR-013, tooltip Kbd) | getMyKeymap | rest | own profile
version line; SCR-157 current and required versions | getBuildInfo | rest | every role
rules armed count | listRules | rest | own rules
HealthChips: exchange WS, ingest lag, recorder, rate budget | health | ws | states only
HealthChips exchange cause; the Stale chip's reason | exchange_state | ws | the four fields
degraded topics behind a Stale panel | degraded_data | ws | the two fields
feed chip latency and Delayed (CMP-076) | connection_quality | ws | the four fields
clock offset chip | clock_drift | ws | clock_offset_ms
kill-switch line and the engaged pill | kill_switch | ws | engaged, scope, granted ids
shutdown notice (Read-only reason R1) | shutdown_notice | ws | the three fields
maintenance and process notices (CMP-092 blocking) | notice | ws | reason
account notices | account_notice | ws | reason, granted ids
feature flags the shell reads | feature_flags | ws | the keys the role may see
recorder count and state | recorder | ws-topic | recording:read
bar-close countdown | bars | chart | the chart's subscription
FPS | none | none | —
CPU % | none | none | —
"""
# source | note (one line each)
REGISTRY_NOTE_TXT = """
getMe | `/me` at bootstrap, re-confirmed on `auth_ok` (`environments`); no `system` kind carries it
listExchangeAccounts | `/exchange-accounts`
listTradeGroups | `/trade-groups`
listWorkspaces | `/workspaces`, at most 32 (E15-D02 §5.2)
getMyPreferences | `/me/preferences` (`themeFromSettings.ts`)
updateMyPreferences | `PATCH /me/preferences` (`14` SCR-012 Data)
getMyKeymap | `/me/keymap`
getBuildInfo | `GET /system/build` `BuildInfo`; `welcome.protocol` / `server_version` (`23` §2.3)
listRules | `15` says `?state=armed`, `14` `?status=armed&count=true`: neither exists (G-row)
health | WS `system` `health`: `components` with `name`, `state`, `last_good_at` only
exchange_state | WS `system` `exchange_state`
degraded_data | WS `system` `degraded_data`
connection_quality | WS `system` `connection_quality` plus the client's own `ping` RTT (E17-D02 §5)
clock_drift | WS `system` `clock_drift`
kill_switch | WS `system` `kill_switch`; `auth_ok.kill_switch` on (re)connect
shutdown_notice | WS `system` `shutdown_notice`
notice | WS `system` `notice` (`maintenance.enabled`)
account_notice | WS `system` `account_notice`
feature_flags | WS `system` `feature_flags`
recorder | WS `recorder` `RecorderUpdate` every 1 000 ms (`23` §3.3)
bars | the chart's `bars` topic (E11; cited, not the shell's)
none | no slot in E10-D02's TopBar and no `system` field: a C-row (engine FPS is E11's SCR-046)
"""
REGISTRY = rows(REGISTRY_TXT)
REGISTRY_NOTE = {r[0]: r[1] for r in rows(REGISTRY_NOTE_TXT)}
KINDS_HEADER = "| `kind`               | Fields a Manager or Viewer also receives"


def registry_report(fails: list[str], spec: str) -> dict[str, Any]:
    api, ws = read(API), read(WS)
    cut = section(ws, KINDS_HEADER, "\n\n")
    ops = set(re.findall(r"operationId: (\w+)", api))
    out: list[dict[str, Any]] = []
    checked = 0
    for value, source, kind, role_cut in REGISTRY:
        ok: bool | None = None
        if kind == "rest":
            ok = source in ops
        elif kind == "ws":
            ok = f"| `{source}`" in cut
        elif kind == "ws-topic":
            ok = f"| `{source}`" in ws and "`recording:read`" in ws
        elif kind == "chart":
            ok = f"| `{source}`" in ws
        if ok is not None:
            checked += 1
            if not ok:
                fails.append(f"registry source not found in the contract text: {source} ({kind})")
        row: dict[str, Any] = {"value": value, "source": source, "kind": kind}
        row["role_cut"] = role_cut
        row |= {"note": REGISTRY_NOTE[source], "in_contract": ok}
        row["in_spec"] = bool(spec) and f"`{source}`" in spec
        out.append(row)
    missing = [r["source"] for r in out if spec and r["kind"] != "none" and not r["in_spec"]]
    fails += [f"registry source absent from the spec: {s}" for s in missing]
    rules = section(api, "operationId: listRules", "operationId:")
    params = sorted(set(re.findall(r"- name: (\w+)\n\s+in: query", rules)))
    return {
        "rows": out,
        "n": len(out),
        "with_source": sum(1 for r in out if r["kind"] != "none"),
        "no_source": [r["value"] for r in out if r["kind"] == "none"],
        "checked": checked,
        "list_rules_query_params": params,
        "list_rules_has_state_or_status": any(p in ("state", "status") for p in params),
        "system_kinds_in_15_9": re.findall(r"^\| `(\w+)`", cut, re.MULTILINE),
        "missing_in_spec": missing,
    }


# --- 6. shipped-code parity ---------------------------------------------------------------------
FILES = {
    "keymap": WEB / "keymap" / "keymap.json",
    "cheatsheet": WEB / "keymap" / "Cheatsheet.tsx",
    "host": WEB / "keymap" / "KeymapHost.tsx",
    "store": WEB / "shell" / "bootstrap" / "store.ts",
    "bootstrap": WEB / "shell" / "bootstrap" / "bootstrap.ts",
    "reach": WEB / "shell" / "bootstrap" / "reachability.ts",
    "types": WEB / "lib" / "ws" / "state" / "types.ts",
    "rbac": WEB / "routes" / "rbac.ts",
    "errors": WEB / "routes" / "ErrorStates.tsx",
    "stepup": WEB / "routes" / "StepUpGate.tsx",
    "latency": WEB / "lib" / "telemetry" / "latencyIndicator.ts",
    "a11y": WEB / "features" / "a11y-preferences" / "model.ts",
    "prefs": WEB / "features" / "a11y-preferences" / "PreferencesContext.tsx",
    "port": WEB / "shell" / "ShellPort.ts",
    "browser": WEB / "shell" / "BrowserShellAdapter.ts",
    "update": DESKTOP / "main" / "updateChannel.ts",
    "main": DESKTOP / "main" / "index.ts",
    "allow": DESKTOP / "preload" / "allowList.ts",
    "gpu": DESKTOP / "main" / "gpu.ts",
}
# the name the spec must carry | file key | regex that must match the shipped file
PARITY_TXT = r"""
`global.palette` ;; keymap ;; "id": "global\.palette"[\s\S]{0,200}?"defaultBinding": "Ctrl\+K"
`global.account_picker` ;; keymap
  ~ ;; "global\.account_picker"[\s\S]{0,200}?"defaultBinding": "Ctrl\+Shift\+A"
`global.cheatsheet` ;; keymap ;; "id": "global\.cheatsheet"[\s\S]{0,200}?"defaultBinding": "Ctrl\+/"
`global.fullscreen` ;; keymap ;; "id": "global\.fullscreen"[\s\S]{0,200}?"defaultBinding": "F11"
`global.nav_rail` ;; keymap ;; "id": "global\.nav_rail"[\s\S]{0,200}?"defaultBinding": "Alt\+1\.\.9"
`workspace.preset` ;; keymap
  ~ ;; "id": "workspace\.preset"[\s\S]{0,200}?"defaultBinding": "Ctrl\+1\.\.9"
`BootstrapPhase` ;; store ;; readonly kind: "slow"
`http_error` ;; store ;; readonly reason: "timeout" \| "http_error" \| "unknown"
`ConnectionState` ;; store
  ~ ;; readonly cause: "offline" \| "tailnet_unreachable" \| "backend_unreachable"
`environment: "unknown"` ;; store ;; environment: "unknown"
`SLOW_BOOT_THRESHOLD_MS` ;; bootstrap ;; SLOW_BOOT_THRESHOLD_MS = 5_000
`BOOTSTRAP_TIMEOUT_MS` ;; bootstrap ;; BOOTSTRAP_TIMEOUT_MS = 10_000
never a client default ;; bootstrap ;; never a client default
`ReachabilityCause` ;; reach
  ~ ;; ReachabilityCause = "offline" \| "tailnet_unreachable" \| "backend_unreachable"
`REACHABILITY_WINDOW_MS` ;; reach ;; REACHABILITY_WINDOW_MS = 5_000
`OfflineCause` ;; types ;; "backend_unreachable" \| "fatal"
`KillSwitchView` ;; types ;; readonly state: "unknown"
`OrderEntryReason` ;; types ;; "kill_switch_engaged" \| "shutdown_pending" \| "kill_switch_unknown"
`STEP_UP_TTL_MS` ;; rbac ;; STEP_UP_TTL_MS = 30 \* 60 \* 1000
`denyAs: "404"` ;; rbac ;; denies non-owners with 404, not 403
`LATENCY_OK_MS` ;; latency ;; LATENCY_OK_MS = 100
`LATENCY_BREACH_MS` ;; latency ;; LATENCY_BREACH_MS = 250
`LatencyState` ;; latency ;; LatencyState = "ok" \| "degraded" \| "breach" \| "unavailable"
`aria-modal="false"` ;; cheatsheet ;; aria-modal="false"
Keyboard shortcuts ;; cheatsheet ;; Keyboard shortcuts
⚠ Conflict ;; cheatsheet ;; ⚠ Conflict
the "?" cheatsheet ;; host ;; the "\?" cheatsheet
<h1>Forbidden</h1> ;; errors ;; <h1>Forbidden</h1>
<h1>Not found</h1> ;; errors ;; <h1>Not found</h1>
Confirm it's you ;; stepup ;; Confirm it&apos;s you
`thick_focus_ring` ;; a11y ;; readonly thick_focus_ring: boolean
`dataset["focusRing"]` ;; prefs
  ~ ;; dataset\["focusRing"\] = prefs\.thick_focus_ring \? "thick" : "normal"
`caps.floatingWindows` ;; port ;; readonly floatingWindows: boolean;
`caps.tray` ;; port ;; readonly tray: boolean;
`caps.autoUpdate` ;; port ;; readonly autoUpdate: boolean;
`caps.keychain` ;; port ;; readonly keychain: boolean;
`caps.osNotifications` ;; port ;; readonly osNotifications: boolean;
`caps.gpuInfo` ;; port ;; readonly gpuInfo: boolean;
`caps.deepLinks` ;; port ;; readonly deepLinks: boolean;
`caps.crashLog` ;; port ;; readonly crashLog: boolean;
hidden with a reason, never shown disabled ;; port
  ~ ;; hidden[\s\S]{0,120}?reason[\s\S]{0,120}?never[\s\S]{0,40}?disabled
Multi-window workspaces need the desktop app. ;; browser
  ~ ;; floatingWindows: "Multi-window workspaces need the desktop app\."
there is no installer to update. ;; browser
  ~ ;; autoUpdate: "Browser tabs update on page reload; there is no installer to update\."
A system tray is not available in a browser tab. ;; browser
  ~ ;; tray: "A system tray is not available in a browser tab\."
The OS keychain bridge is only available in the desktop app. ;; browser
  ~ ;; keychain: "The OS keychain bridge is only available in the desktop app\."
Enable browser notification permission, or use the desktop app for OS-level alerts. ;; browser
  ~ ;; "Enable browser notification permission, or use the desktop app for OS-level alerts\."
Deep links (custom protocol) require the desktop app. ;; browser
  ~ ;; deepLinks: "Deep links \(custom protocol\) require the desktop app\."
Crash logs are written to the desktop app's local log file only. ;; browser
  ~ ;; crashLog: "Crash logs are written to the desktop app's local log file only\."
`ALLOWED_IPC_CHANNELS` ;; allow ;; export const ALLOWED_IPC_CHANNELS: readonly string\[\] = \[
`isAutoUpdateEnabled()` ;; update
  ~ ;; export function isAutoUpdateEnabled\(\): boolean \{\s+return false;
`UPDATE_CHANNEL_DISABLED_REASON` ;; update
  ~ ;; UPDATE_CHANNEL_DISABLED_REASON = "UPDATE_CHANNEL_DISABLED"
`applyUpdate(): never` ;; update ;; export function applyUpdate\(\): never
`show: false` ;; main ;; width: 1280,\s+height: 800,\s+show: false
`cv:updates:check` ;; allow ;; "cv:gpu:info",\s+"cv:keychain:getKekHandle",\s+"cv:updates:check"
`GpuProbeResult` ;; gpu ;; readonly webgl2CapabilityParity: boolean
"""
PARITY = rows(PARITY_TXT, sep=" ;; ")


def parity_report(fails: list[str], spec: str) -> dict[str, Any]:
    out: list[dict[str, Any]] = []
    for needle, key, pattern in PARITY:
        path = FILES[key]
        in_code = bool(re.search(pattern, read(path)))
        in_spec = needle in spec if spec else False
        if not in_code:
            fails.append(f"shipped code moved: {needle} ({path.relative_to(ROOT)})")
        if spec and not in_spec:
            fails.append(f"spec lacks the shipped name: {needle}")
        out.append({"needle": needle, "file": str(path.relative_to(ROOT))})
        out[-1] |= {"in_code": in_code, "in_spec": in_spec}
    keymap = json.loads(read(FILES["keymap"]) or "{}")
    contexts = list(keymap.get("cheatsheetContexts", []))
    commands = list(keymap.get("commands", []))
    globals_ = [
        c
        for c in commands
        if c.get("context") == "Global"
        and str(c.get("id", "")).startswith("global.")
        and "SCR-010" in (c.get("screens") or [])
    ]
    ctx_missing = [c for c in contexts if spec and c not in spec]
    if spec and ctx_missing:
        fails.append(f"spec lacks cheatsheet contexts: {ctx_missing}")
    theme_css = read(ROOT / "packages" / "ui" / "src" / "theme" / "theme.css")
    prefs_sets = 'dataset["focusRing"]' in read(FILES["prefs"])
    return {
        "rows": out,
        "n": len(out),
        "in_code": sum(1 for r in out if r["in_code"]),
        "in_spec": sum(1 for r in out if r["in_spec"]),
        "cheatsheet_contexts": contexts,
        "contexts_n": len(contexts),
        "global_scr010_bindings": {c["id"]: c["defaultBinding"] for c in globals_},
        "global_scr010_n": len(globals_),
        "commands_n": len(commands),
        "theme_css_has_focus_ring_attr": "data-focus-ring" in theme_css,
        "prefs_sets_focus_ring_attr": prefs_sets,
    }


# --- 7. token bindings --------------------------------------------------------------------------
TOKEN_RE = re.compile(
    r"`((?:color|space|size|radius|border|type|elevation|opacity|motion|font|layout)\.[a-z0-9.*-]+)`"
)
MARKED_RE = re.compile(r"PROPOSED|G-row|\| G\d+ |not a token|no such token|does not exist")
EXPECTED_MISSING = (
    "layout.shell.*",
    "size.navrail.width",
    "motion.toast",
    "motion.drawer",
    "color.surface.base",
    "space.emptystate.*",
    "font.mono",
    "color.icon.*",
    "color.text.muted",
    "color.callout.*",
)


def token_report(fails: list[str], spec: str) -> dict[str, Any]:
    known = set(theme_tokens("dark").keys())
    bound: set[str] = set()
    missing: set[str] = set()
    marked: set[str] = set()
    bad_t2: list[str] = []
    for ln in spec.splitlines():
        for tok in TOKEN_RE.findall(ln):
            bound.add(tok)
            if tok not in known:
                (marked if MARKED_RE.search(ln) else missing).add(tok)
        dimming = "color.text.disabled" in ln or "opacity.disabled" in ln
        if ln.startswith("| ") and "T2" in ln and "never" not in ln and dimming:
            bad_t2.append(ln[:80])
    fails += [f"token bound but unknown and unmarked: {t}" for t in sorted(missing)]
    fails += [f"T2 row with a dimming token: {s}" for s in bad_t2]
    registered = set(re.findall(r'\{\s*fg:\s*"([^"]+)",\s*bg:\s*"([^"]+)"', read(PAIRS_MJS)))
    gated = {(r[1], r[2]) for r in PAIRS if BAR.get(r[3]) is not None}
    gated |= {(r[1], r[2]) for r in D03_BADGE_ROWS if BAR.get(r[3]) is not None}
    proposed = sorted(f"{fg} on {bg}" for fg, bg in gated if (fg, bg) not in registered)
    return {
        "bound": sorted(bound),
        "bound_n": len(bound),
        "known_n": len(known),
        "missing": sorted(missing),
        "marked_missing": sorted(marked),
        "expected_missing": list(EXPECTED_MISSING),
        "bad_t2_rows": bad_t2,
        "pairs_registered_n": len(registered),
        "gated_pairs_n": len(gated),
        "pairs_already_registered": sorted(
            f"{fg} on {bg}" for fg, bg in gated if (fg, bg) in registered
        ),
        "pairs_proposed": proposed,
        "pairs_proposed_n": len(proposed),
    }


# --- 8. string gates -----------------------------------------------------------------------------
BADGE_SENTENCE = "The LIVE treatment is never weakened by theme, density or preference"
WEAKEN_RE = re.compile(
    r"LIVE treatment (?:may be|can be|is|gets|becomes) (?:weakened|hidden|dropped|dimmed|neutral)"
)
T2_SENTENCE = (
    "Every role-, grant-, environment-, session- or state-gated control in the shell "
    "is E09-D09's T2"
)
SHAPE_SENTENCE = "every state is carried by word, glyph and weight before colour"
VALIDITY_SENTENCE = "no form-validity control exists in the shell"
UPDATE_PHRASE = "unavailable until you update"
VIEW_AS, PERMISSION, OWNER_ONLY = "`rbac.view_as`", "`rbac.permission`", "`rbac.owner_only`"
LOCAL_PATH_RE = re.compile(r"/(?:home|Users)/[^/\s]+/")
PENPOT_HOST_RE = re.compile(r"penpot\.[a-z0-9-]+\.[a-z]{2,}", re.IGNORECASE)
CLOSING_RE = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b\s*:?\s*#\d+", re.IGNORECASE)
TRADE_WORD_RE = re.compile(r"^(?:Buy|Sell|Place)\b")
D02_PAGE_ID_RE = re.compile(r"page id `([0-9a-f-]{36})`")
HEX_RE = re.compile(r"#[0-9A-Fa-f]{6}\b")
US_ID_RE = re.compile(r"\bUS-[A-Z]+-(\d{3})(?:\.\.(\d{3}))?\b")
T2_EXACT = "T2 per §10.1"
NOT_T2_RE = re.compile(r"\b(?:not|never|no)\s+T2(?![\w-])", re.IGNORECASE)
CARVE_OUT_SENTENCE = "View-as never gates the C-2.6 protective writes"
PROTECTIVE = ("FLATTEN ALL", "CANCEL ALL", "FREEZE", "Kill switch…", "the cluster")
FALLBACK_CMD = "candleviewer kill"
# the exact carve-out clauses each gated place must keep (the delta lens's Nit 1: a reworded row
# or a dropped section 6.1 / row 4 clause must fail, not only a leading "view-as;")
CARVE_OUT_CLAUSES = (
    "never view-as — the C-2.6 carve-out keeps both enabled on the target's accounts",
    "view-as on the global scope and Release… only — engaging on the target's accounts"
    " stays enabled",
    "view-as on every write command but the C-2.6 protective ones",
)
PALETTE_CARVE_OUT = '"Cancel all orders on this account…" stays enabled while viewing as'
FALLBACK_LINE = "Fallback: the server console command"
AGGREGATE_LINE = "Safety · your role can't use these"  # D02 :84's cluster line, superseded (C25)
RELEASE_SENTENCE = "Only the owner can release the kill switch."  # E09-D09 §3.1 :97 (C28)
# the PROPOSED state keys and their sentences
PROPOSED_KEY_RE = re.compile(r"`health\.[a-z_]+` \"([^\"]+)\"")
NINE = (
    "SCR-010",
    "SCR-011",
    "SCR-012",
    "SCR-013",
    "SCR-015",
    "SCR-027",
    "SCR-156",
    "SCR-157",
    "SCR-159",
)


def table_rows(block: str) -> list[str]:
    return [ln for ln in block.splitlines() if ln.startswith("| ") and not re.match(r"^\| -", ln)]


def us_ids(spec: str) -> list[str]:
    """Every ``US-…`` id the spec cites, a ``001..006`` range expanded to its members."""
    out: list[str] = []
    for m in US_ID_RE.finditer(spec):
        prefix, lo, hi = m.group(0).split("-")[1], int(m.group(1)), m.group(2)
        for n in range(lo, (int(hi) if hi else lo) + 1):
            out.append(f"US-{prefix}-{n:03d}")
    return sorted(set(out))


def string_report(fails: list[str], spec: str) -> dict[str, Any]:
    g: dict[str, bool] = {}
    cat = read(CATALOGUE)
    stories = read(USER_STORIES)
    cited = us_ids(spec)
    us_missing = [i for i in cited if not re.search(rf"(?m)^#### {re.escape(i)} ", stories)]
    g["us_ids_exist_in_11"] = bool(cited) and not us_missing  # the pre-PR lens round 1 (F-1)
    g["badge_contract_once"] = spec.count(BADGE_SENTENCE) == 1
    g["no_weakening_clause"] = not WEAKEN_RE.search(spec)
    g["t2_rule_once"] = spec.count(T2_SENTENCE) == 1
    s1, s4 = section(spec, "## 1.", "## 2."), section(spec, "## 4.", "## 5.")
    s9, s10 = section(spec, "## 9.", "## 10."), section(spec, "## 10.", "## 11.")
    keys = ("rbac.", "health.", UPDATE_PHRASE)
    # every matrix cell: its T2 column is "none" with no gated key, or names "T2 per §10.1" exactly
    # and never "not T2" (the orchestrator's text round 1, Minor 8)
    mcells = [r for r in table_rows(s4) if re.match(r"^\| \d+ +\| ", r)]
    t2cols = [[c.strip() for c in r.split("|")[1:-1]][4] for r in mcells]
    gated_rows = [c for c in t2cols if not c.startswith("none")]
    g["t2_in_every_cell"] = len(mcells) == 18 and all(
        (not any(k in c for k in keys)) if c.startswith("none") else T2_EXACT in c for c in t2cols
    )
    g["no_not_t2_in_cells"] = not any(NOT_T2_RE.search(c) for c in t2cols)
    g["t2_rows_cite_rule"] = bool(gated_rows) and all("§10.1" in c for c in gated_rows)
    s13 = section(spec, "### 1.3", "### 1.4")
    rows13 = [r for r in table_rows(s13) if not r.startswith("| Control")]
    g["t2_rendering_in_1_3"] = len(rows13) == 6 and all(
        re.search(r"\b2a\b|\b2b\b|T2 rendering", r) for r in rows13
    )
    # the C-2.6 carve-out: view-as never gates the protective writes (cell 6, section 1.3, 10.1)
    cell6 = next((c for r, c in zip(mcells, t2cols, strict=True) if re.match(r"^\| 6 ", r)), "")
    before = cell6.split(T2_EXACT)[0]
    g["view_as_spares_carve_out"] = (
        CARVE_OUT_SENTENCE in s1
        and "never gates the C-2.6 protective writes" in s10
        and "enabled on the target's accounts" in cell6
        and not any(p in before for p in PROTECTIVE)
        and not any(r.split("|")[2].strip().startswith("view-as;") for r in rows13[:2])
        and len(rows13) == 6
        and all(
            clause in r.split("|")[2]
            and not re.search(r"view-as on every scope|engaging included", r)
            for clause, r in zip(CARVE_OUT_CLAUSES, (rows13[0], rows13[1], rows13[3]), strict=True)
        )
        and PALETTE_CARVE_OUT in rows13[3]
        and "never on a C-2.6 protective command" in section(spec, "### 6.1", "### 6.2")
        and PALETTE_CARVE_OUT in section(spec, "### 6.1", "### 6.2")
    )
    va = s1.find(VIEW_AS)
    g["view_as_first"] = 0 <= va < s1.find(PERMISSION) and va < s1.find(OWNER_ONLY)
    g["update_phrase_on_scr157"] = UPDATE_PHRASE in s9 and UPDATE_PHRASE in s4
    s92 = section(spec, "### 9.2", "### 9.3")
    variants = [r for r in table_rows(s92) if re.match(r"^\| (?:offline|tailnet-unreachable) ", r)]
    # both columns of both rows: the page ("Where") and its copy name the command (Nit 1)
    vcells = [[c.strip() for c in r.split("|")[1:-1]] for r in variants]
    g["offline_fallback_named"] = len(variants) == 2 and all(
        len(c) == 4 and FALLBACK_CMD in c[2] and FALLBACK_CMD in c[3] and FALLBACK_LINE in c[3]
        for c in vcells
    )
    g["no_same_as_dark"] = "same as dark" not in spec.lower()
    g["no_placeholders"] = not re.search(r"SET-ME|TODO|TBD", spec)
    g["no_local_path"] = not LOCAL_PATH_RE.search(spec)
    g["no_penpot_host"] = not PENPOT_HOST_RE.search(spec)
    g["no_pagelink"] = "pageLink" not in spec
    g["no_closing_keyword"] = not CLOSING_RE.search(spec)
    board_rows = [
        r for r in table_rows(section(spec, "## 0.", "## 1.")) if re.match(r"^\| \d\d ", r)
    ]
    g["boards_pending"] = bool(board_rows) and all(
        re.search(r"PENDING\s*\|\s*$", r) for r in board_rows
    )
    g["stamps_present"] = "PROPOSED" in spec and "RULED" in spec
    g["shape_sentence"] = SHAPE_SENTENCE in spec
    g["validity_sentence"] = VALIDITY_SENTENCE in spec
    # E09-D09 §2.2's one reason node per control (no aggregate line in a gated row or a board
    # row), Release… T2 for a non-owner when engaged (§3.1 :97), every PROPOSED health.* sentence
    # <= 60 characters with a full stop (§3.1)
    s0 = section(spec, "## 0.", "## 1.")
    g["no_aggregate_cluster_line"] = (
        AGGREGATE_LINE not in s4
        and AGGREGATE_LINE not in s0
        and AGGREGATE_LINE in section(spec, "### 17.3", "### 17.4")
    )
    g["release_t2_when_engaged"] = RELEASE_SENTENCE in s4 and RELEASE_SENTENCE in s10
    proposed = set(PROPOSED_KEY_RE.findall(spec))
    g["proposed_keys_form"] = bool(proposed) and all(
        len(t) <= 60 and t.endswith(".") and "SR-" not in t for t in proposed
    )
    cells = [c.strip().strip('`"“”') for r in table_rows(s10) for c in r.split("|")[1:-1]]
    bad_copy = [c for c in cells if TRADE_WORD_RE.match(c)]
    g["no_chrome_trading_word"] = not bad_copy
    d02_id = D02_PAGE_ID_RE.search(read(D02_SPEC))
    if (
        d02_id is not None
    ):  # E10-D02's page id is quoted at most once, as D02's (no literal id here)
        g["d02_page_id_at_most_once"] = spec.count(d02_id.group(1)) <= 1
    nine = cat.count("Hi-fi (E10-D03)")
    g["catalogue_nine_lines"] = nine == 9 and "E10-D03" not in section(
        cat, "### SCR-152", "### SCR-156"
    )
    under = [s for s in NINE if "Hi-fi (E10-D03)" in section(cat, f"### {s} ", "\n### SCR-")]
    g["catalogue_lines_under_the_nine"] = tuple(under) == NINE
    fails += [f"string gate failed: {k}" for k, ok in g.items() if not ok]
    return {
        "gates": g,
        "matrix_cells": len(mcells),
        "gated_rows": len(gated_rows),
        "board_rows": len(board_rows),
        "catalogue_lines": nine,
        "catalogue_under": under,
        "bad_copy_cells": bad_copy,
        "us_ids_cited": len(cited),
        "us_ids_missing": us_missing,
        "hex_literals_in_spec": len(HEX_RE.findall(spec)),
        "spec_lines": len(spec.splitlines()),
    }


# --- 9. counts and the CLI ------------------------------------------------------------------------
def count_rows(spec: str, start: str, end: str | None, pattern: str) -> int:
    return len(re.findall(r"(?m)^" + pattern, section(spec, start, end)))


def spec_counts(spec: str) -> dict[str, Any]:
    s0 = section(spec, "## 0.", "## 1.")
    nested = 0
    for r in table_rows(s0):
        cells = [c.strip() for c in r.split("|")[1:-1]]
        if re.fullmatch(r"\d\d", cells[0]) and len(cells) >= 5 and cells[4].isdigit():
            nested += int(cells[4])
    stories = 0
    for r in table_rows(section(spec, "### 13.1", "### 13.2")):
        cells = [c.strip() for c in r.split("|")[1:-1]]
        if len(cells) >= 2 and cells[0].startswith("CMP-"):
            stories += len(re.findall(r"`[A-Z][A-Za-z0-9]*`", cells[1]))
    return {
        "boards": count_rows(spec, "## 0.", "## 1.", r"\| \d\d "),
        "light_twins": len(re.findall(r"(?m)^\| \d\d [^|]*\| [^|]*light twin", s0)),
        "nested_frames": nested,
        "cells": count_rows(spec, "## 4.", "## 5.", r"\| \d+ +\| "),
        "state_rows": count_rows(spec, "### 17.6", "### 17.7", r"\| SCR-"),
        "registry_rows": count_rows(spec, "### 14.2", "### 14.3", r"\| [^|-][^|]*\| [^|]*\| `"),
        "storybook": stories,
        "a_rows": count_rows(spec, "### 17.2", "### 17.3", r"\| A\d+ "),
        "c_rows": count_rows(spec, "### 17.3", "### 17.4", r"\| C\d+ "),
        "g_rows": count_rows(spec, "### 17.4", "### 17.5", r"\| G\d+ "),
        "q_rows": count_rows(spec, "### 17.5", "### 17.6", r"\| Q\d+ "),
        "handoff_rows": count_rows(spec, "### 17.6", "### 17.7", r"\| H\d+ "),
        "deviations": count_rows(spec, "### 17.7", "## 18.", r"\| D\d+ "),
        "names": count_rows(spec, "### 10.2", "### 10.3", r'\| [^|]+\| [^|]+\| "'),
    }


def print_human(rep: dict[str, Any], counts: dict[str, Any], fails: list[str]) -> None:
    geo, badge, matrix, cvdr = rep["geometry"], rep["badge"], rep["matrix"], rep["cvd"]
    registry, parity, toks, strings = rep["registry"], rep["parity"], rep["tokens"], rep["strings"]
    hdr = "|---|---|---|---|---|---|---|---|---|"
    print("## 1. Chrome geometry (primitive tokens; gated to E10-D02 :65 and E15-D02 §3)\n")
    print(json.dumps(geo, ensure_ascii=False))
    print("\n## 2. Badge pairs (E30-D01 §3 reproduced; this spec's surfaces; greyscale)\n")
    print("| element | fg | bg | role | dark | light | hc | source | note |\n" + hdr)
    for r in badge["rows"]:
        cells = " | ".join(fmt(r["ratios"][t]) for t in THEMES)
        note = "reproduced" if r.get("reproduced") else r.get("verdict", "NOT reproduced")
        print(f"| {r['element']} | `{r['fg']}` | `{r['bg']}` | {r['role']} | {cells} | ", end="")
        print(f"{r['source']} | {note} |")
    print(f"\nword >= 7:1 in every theme: {badge['stretch_word_7']} · ", end="")
    print(f"borders >= 3:1: {badge['border_3']}")
    print("greyscale: " + json.dumps(badge["luminance"], ensure_ascii=False))
    print("\n## 3. Measured matrix (contrast_ratio; bars text 4.5 / ui 3.0 / badge 7.0)\n")
    print("| element | fg | bg | role | dark | light | hc | verdict | source |\n" + hdr)
    for p in matrix["pairs"]:
        cells = " | ".join(fmt(p["ratios"][t]) for t in THEMES)
        mark = "" if p["reproduced"] is None else (" ✓" if p["reproduced"] else " ✗")
        print(f"| {p['element']} | `{p['fg']}` | `{p['bg']}` | {p['role']} | {cells} | ", end="")
        print(f"{p['verdict']} | {p['source']}{mark} |")
    print(
        f"\nrows {matrix['rows']} · gated {matrix['gated']} · structure {matrix['structure']} · ",
        end="",
    )
    print(f"rejected {matrix['rejected']} · failing {matrix['failing']} · ", end="")
    print(f"reproductions {matrix['repro_rows']}")
    print(f"CMP-039 ring minima over the seven tiers: {matrix['ring_min']} (E05-D02: {RING_MIN})")
    print(f"no hc override among the shell's tokens: {matrix['no_hc_override']}")
    print("\n| token | dark | light | hc |\n|---|---|---|---|")
    for k in SHELL_TOKENS:
        print(f"| `{k}` | " + " | ".join(matrix["tokens"][t][k] for t in THEMES) + " |")
    print(f"\n## 4. CVD (cvd_simulate; ΔE76; JND {JND})\n")
    for r in cvdr["rows"]:
        print(f"- {r['what']}: " + json.dumps(r["themes"], ensure_ascii=False))
    print(
        f"E30-D01 F5 reproduced: {cvdr['f5_reproduced']} (contrast {cvdr['f5_contrast']}, ", end=""
    )
    print(
        f"ΔE76 {cvdr['f5_delta_e_normal']}); sell ≡ live in dark: {cvdr['sell_equals_live_dark']}"
    )
    print("\n## 5. Live-value registry (22 operationIds; 23 §15.9 kinds)\n")
    for r in registry["rows"]:
        print(f"- {r['value']} → {r['source']} ({r['kind']}; contract {r['in_contract']}; ", end="")
        print(f"spec {r['in_spec']}) — {r['note']}")
    print(f"listRules query params: {registry['list_rules_query_params']} ", end="")
    print(f"(state/status present: {registry['list_rules_has_state_or_status']})")
    print("\n## 6. Shipped-code parity\n")
    for r in parity["rows"]:
        print(f"- {r['needle']}: code {r['in_code']} · spec {r['in_spec']}")
    print(json.dumps({k: v for k, v in parity.items() if k != "rows"}, ensure_ascii=False))
    print("\n## 7. Token bindings\n")
    print(json.dumps({k: v for k, v in toks.items() if k != "bound"}, ensure_ascii=False))
    print("\n## 8. String gates\n")
    print(json.dumps(strings, ensure_ascii=False))
    print("\n## 9. Counts\n")
    print(json.dumps(counts, ensure_ascii=False))
    print(f"\nFAIL count (gated): {len(fails)}")
    for f in fails:
        print(f"- {f}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="E10-D03 shell chrome audit")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true", help="exit 1 on any gated FAIL")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    spec = read(SPEC)
    fails: list[str] = []
    th = themes()
    rep: dict[str, Any] = {"geometry": geometry_report(fails), "badge": badge_report(fails, th)}
    rep |= {"matrix": matrix_report(fails, th), "cvd": cvd_report(fails, th)}
    rep |= {"registry": registry_report(fails, spec), "parity": parity_report(fails, spec)}
    rep |= {"tokens": token_report(fails, spec)}
    rep["strings"] = string_report(fails, spec) if spec else {"gates": {}, "spec_lines": 0}
    if not spec:
        fails.append("spec absent: string gates not checked")
    sc = spec_counts(spec) if spec else {}
    m, b, c, r = rep["matrix"], rep["badge"], rep["cvd"], rep["registry"]
    counts: dict[str, Any] = {"themes": len(THEMES), "boards": 12, "light_twins": 2, "cells": 18}
    counts |= {"badge_rows": b["n"], "e30_rows": b["e30_rows"], "matrix_rows": m["rows"]}
    counts |= {"matrix_gated": m["gated"], "matrix_structure": m["structure"]}
    counts |= {"matrix_rejected": m["rejected"], "matrix_failing": m["failing"]}
    counts |= {"repro_rows": m["repro_rows"], "cvd_rows": c["n"], "registry_rows": r["n"]}
    counts |= {"registry_with_source": r["with_source"], "parity_rows": rep["parity"]["n"]}
    counts |= {"contexts": rep["parity"]["contexts_n"]}
    counts |= {"global_bindings": rep["parity"]["global_scr010_n"]}
    counts |= {"tokens_bound": rep["tokens"]["bound_n"]}
    counts |= {"pairs_proposed": rep["tokens"]["pairs_proposed_n"]}
    counts |= {"no_hc_override": len(m["no_hc_override"])}
    counts |= {f"spec_{k}": v for k, v in sc.items()}
    if counts["light_twins"] * 3 > counts["boards"]:
        fails.append("light twins exceed one third of the boards (lever 4)")
    for key, want in (("boards", 12), ("light_twins", 2), ("cells", 18)):
        if spec and sc.get(key) != want:
            fails.append(f"spec {key} = {sc.get(key)}, expected {want}")
    if a.json:
        out: dict[str, Any] = {"counts": counts} | rep | {"fails": fails}
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print_human(rep, counts, fails)
    return 1 if (a.check and fails) else 0


if __name__ == "__main__":
    raise SystemExit(main())
