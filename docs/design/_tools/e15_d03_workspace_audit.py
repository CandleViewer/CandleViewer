#!/usr/bin/env python3
"""E15-D03 workspace audit: SCR-020's chrome budget, contrast, CVD, counts, frame gates and cites.

Standalone, offline, stdlib only; it executes no repo code. It reads the token JSON
(`packages/ui/tokens`, `themes.json` layering), the merged parent `docs/design/E15/E15-D02.md`,
`CONSTITUTION.md` and this ticket's spec and hand-off AS TEXT, and:

1. **Cites.** Every `NN`:line, `D02`:line, `E10-D03`:line, `CONSTITUTION.md`:line and
   `E15-D02.md:N` "fragment" cite in the spec and the hand-off is read at the pinned base
   (`git show 0a1151f325:<path>`): OK when the line exists (and holds the fragment, if quoted);
   WARN when the same line reads differently at `origin/main` (drifted since the base); FAIL when
   the file or line is gone at the base, the line is blank, or a fragment is absent or ambiguous.
   `T:`n (the issue body of #319) is not in the repo and is counted, not checked.
2. **Values.** Every `{{BUDGET:key}}`, `{{CR:row:theme:lo|hi}}`, `{{CR:row:verdict}}`,
   `{{CR:cvd.pair.sim}}` and `{{COUNT:key}}` placeholder outside backticks is COMPUTED: the chrome
   budget from the primitive tokens and E15-D02 §3's rows (parsed from its text; the allowance,
   ceiling, share, canvas and cells are gated equal to the parent's stated figures; the header
   widths are measured inside the frame from tokens, reported beside the parent's, and each
   minimum + 2 × the frame is gated to fit its column on every §6.2 frame that names one, the
   comfortable frames with the comfortable minimums: their `size.icon.md` grip and
   `size.control.comfortable` buttons; the step each such frame draws is a value too); contrast
   with the WCAG 2.x formula over the token JSON per theme
   (`lo` = against the darkest, `hi` = against the lightest background of the row's set); CVD as
   CIELAB ΔE76 after the Machado, Oliveira & Fernandes (2009) severity-1.0 sRGB matrices (the
   deuteranopia matrix is `cvd_sim.py`'s); counts parsed from the spec's own §0 / §6.1 / §8.1 /
   §11.2. `--fill` replaces each placeholder with `VALUE<!--=KEY-->`; the anchor stays, so
   `--check` re-derives every anchored value and FAILs when the number before it differs, when
   an anchor is missing for a key the tool computes, or when a `{{` remains outside backticks.
3. **Frame gates (A2).** §6.2's register parsed per frame row: a focused panel names
   "frame fill + bar"; every order-capable region name ends in its environment word (also §4.2.4);
   the restored frames carry "Restored", `*` and "Save restored layout" (also §5); every R-id the
   register names exists in §8.1; ⋮ on every header row (and "present" at every §4.2.3 step); the
   cost pair "ms · fps" twice (also §5's confirm). §8.1: every T2 row has a key, a reason (or an
   "as R-n" pointer) and a form, and never `color.text.disabled` / `opacity.disabled`; §1.4 keeps
   the leading lock glyph; §8.4's exits carry no lock, key or T2. Every register row is walked,
   the light twins included: a twin's Gated cell ("as NN" or an R-list) must cover its dark
   board's R-ids; Focus "n/a" only on the no-panel frames; ⋮ in every §4.2.4 header text; §5
   `limits-at-16` keeps T2 `layout.limit.panels`; §4.5's restored `[Save]` cells keep the label.
   The never-stored restored copy carries "Discard restored layout…" in §5, §6.2, §4.5 and
   X-4 (M-9, A3). The splitter hit band's reach and the handle / sync-badge hit boxes are
   computed and gated at size.target.min or more (F-5, F-15).
4. **Strings and tokens.** Required strings ("Save restored layout", the env words, the T2 keys incl.
   `layout.limit.panels`, the quoted E15-D02 row of §8.2 equal to `D02`:659 at the base,
   "drawn on request"); every backticked token name exists; no hex colour. Whole-text gates on
   the spec and the hand-off: no lock / T2 on a splitter or ×; no gated Esc; E15-D04 never pinned
   by a sha or quoted; issuecomment-6391925285 only as "the BQ list", the RULED heading on the
   ruling issuecomment-6391960363; every line naming BQ-3 / BQ-4 carries "owner approval pending
   (#2701)". **Keymap (MJ-4):** every §12.1 / Table K row names its `keymap.json` id (read at the
   base), or is PROPOSED-PENDING via CMP-022 with a shipped path, or is a component / reserved
   key; a chord already bound in `keymap.json` names that command.
5. **--selftest** applies one or more in-memory mutations per gate class to the filled spec; each
   must add a FAIL (or, for the drift case, a WARN) that the unmutated text does not have.

Usage:
  python3 -I docs/design/_tools/e15_d03_workspace_audit.py --check docs/design/E15/E15-D03.md \
      [--handoff docs/design/E15/E15-D03-handoff.md] [--json] [--fill]
  python3 -I docs/design/_tools/e15_d03_workspace_audit.py --selftest
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import functools
import io
import itertools
import json
import math
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
PLAN = ROOT / "docs" / "plan"
DESIGN = ROOT / "docs" / "design"
D02 = DESIGN / "E15" / "E15-D02.md"
SPEC = DESIGN / "E15" / "E15-D03.md"
HANDOFF = DESIGN / "E15" / "E15-D03-handoff.md"
BASE = "0a1151f325"  # every cite was read here (the spec's Key; re-pinned from 76edb9470f)
HEAD = "origin/main"  # drift is reported against this ref (WARN, never FAIL)
MULTI = re.MULTILINE
PRIM, DARK, LIGHT, HC = (
    "primitives.tokens.json",
    "semantic-dark.tokens.json",
    "semantic-light.tokens.json",
    "semantic-hc.tokens.json",
)
THEMES: dict[str, tuple[str, ...]] = {
    "dark": (PRIM, DARK),
    "light": (PRIM, DARK, LIGHT),
    "hc": (PRIM, DARK, HC),
}
# The hosted-panel backgrounds of §11.2's header: `lo` / `hi` are the darkest / lightest of these.
SURFACES = (
    "color.surface.sunken",
    "color.surface.app",
    "color.surface.canvas",
    "color.surface.raised",
    "color.surface.overlay",
)
REPORTED_BAR = 7.0  # the env word's AAA figure, reported only (`05`:127)
# §11.3's pairs (dark theme, the default): D-1 (the ring vs the hairline, the bar vs its empty
# slot), D-6 (the letter on the chip's `color.surface.raised` fill), D02 D-7 (LIVE vs DEMO rule).
CVD_PAIRS: dict[str, tuple[str, str]] = {
    "focus-frame": ("color.focus.ring", "color.border.default"),
    "focus-bar": ("color.focus.ring", "color.surface.raised"),
    "sync-letter": ("color.text.primary", "color.surface.raised"),
    "env-rule": ("color.env.live", "color.env.demo"),
    # lens F-11: the focus ring beside a DEMO rule (blue.300 vs blue.500, `E30-D02`:126's budget)
    "focus-vs-demo": ("color.focus.ring", "color.env.demo"),
}
# Machado, Oliveira & Fernandes (2009), severity 1.0, applied to 0-255 sRGB as `cvd_sim.py` does.
MACHADO: dict[str, tuple[tuple[float, float, float], ...]] = {
    "normal": ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    "protanopia": (
        (0.152286, 1.052583, -0.204868),
        (0.114503, 0.786281, 0.099216),
        (-0.003882, -0.048116, 1.051998),
    ),
    "deuteranopia": (
        (0.367322, 0.860646, -0.227968),
        (0.280085, 0.672501, 0.047413),
        (-0.011820, 0.042940, 0.968881),
    ),
    "tritanopia": (
        (1.255528, -0.076749, -0.178779),
        (-0.078411, 0.930809, 0.147602),
        (0.004733, 0.691367, 0.303900),
    ),
}
# (heuristic) Inter's average advance per character, the house constant of e10_d03 / e14_d07;
# widths built on it are estimates that the boards measure.
INTER_EM = 0.56
VIEWPORTS = {"1280": (1280, 800), "1920": (1920, 1080)}
DENSITIES = ("compact", "comfortable")
# Tape's own actions (E22-D02's four buttons in the action slot): CMP-002 IconButtons, square.
TAPE_ACTIONS = 4
CLUSTER_LABELS = ("Layout 1 ▾", "Sync: A ▾", "Add panel", "Save")
RESTORED_SAVE = "Save restored layout"
RESTORED_DISCARD = "Discard restored layout…"  # the never-stored copy's exit (A3, D-8, C-16)
VIEWER_REASON = "Your role can't save workspaces."
LIMIT_REASON = "This layout has the most panels it can hold."
TABS_BEFORE_OVERFLOW = 5  # `D02`:280 "for five tabs before the overflow control appears"
PARENT_TOLERANCE = 0.10  # the parent's "about N px" cluster figures (WARN beyond)
REQUIRED_STRINGS = (
    RESTORED_SAVE,
    "drawn on request",
    "LIVE",
    "DEMO",
    ", Live",
    ", Demo",
    "`layout.limit.panels`",
    "`rbac.permission`",
    "`rbac.view_as`",
    "`rbac.account`",
    '`E15-D02.md:659` "`layout.limit.panels`"',
)
# Tokens a spec may name that are not in the JSON at the base, each with its owner.
PENDING_TOKENS = {"color.sync.*": "E15-D06 (#360)"}
TOKEN_REF = re.compile(
    r"`((?:color|space|size|border|font|type|radius|elevation|opacity|motion)\.[a-z0-9.*-]+)`"
)
HEX = re.compile(
    r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|(?=[0-9a-fA-F]{3}\b)[0-9]*[a-fA-F][0-9a-fA-F]*)\b"
)
PLACEHOLDER = re.compile(r"\{\{([A-Z]+:[^{}]+)\}\}")
ANCHOR = re.compile(r"<!--=([A-Z]+:[^>]+?)-->")
CODE = re.compile(r"`[^`\n]*`")
# lens F-10: raw px. Quoted text and code spans are other documents' words; screen sizes and
# zoomed viewports are inputs, not chrome values
QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”|`[^`\n]*`')
BARE_PX = re.compile(r"(?<![\w.>])\d+(?:\.\d+)? ?px\b(?!<!--=)")
BARE_DIM = re.compile(r"(?<![\w.>])\d+×\d+(?![\d<])")
INPUT_DIMS = {"1280×800", "1920×1080", "1280×720", "1024×640", "640×400", "2×2"}
BOUNDARY = " |*(/:;,—"  # what may precede an anchored value
# the hand-off's anchored keys (the spec's are every value the tool computes for it)
HANDOFF_KEYS = (
    "BUDGET:focus.bar-px",
    "BUDGET:focus.frame-px",
    "BUDGET:v.header.comfortable",
    "BUDGET:v.header.compact",
    "BUDGET:v.restore.comfortable",
    "BUDGET:v.restore.compact",
    "BUDGET:v.tabstrip.comfortable",
    "BUDGET:v.tabstrip.compact",
)
CITE_GROUP = re.compile(
    r"`(?P<id>[A-Za-z0-9._-]+)`:(?P<first>\d+(?:[–-]\d+)?)(?P<more>(?:, :\d+(?:[–-]\d+)?)*)"
)
CITE_FRAG = re.compile(r"`(?P<id>E\d{2}-D\d{2})\.md:(?P<line>\d+)`(?: \"(?P<frag>[^\"]+)\")?")
ORDER_CAPABLE = ("Chart, ", "DOM, ", "Positions, ")
ENV_WORDS = (", Live", ", Demo")


# ---------------------------------------------------------------------------- reading


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


@functools.lru_cache(maxsize=256)
def git_show(rev: str, rel: str) -> str | None:
    """The file at `rev`, or None when it does not exist there (never raises)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "show", f"{rev}:{rel}"],
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.decode("utf-8") if out.returncode == 0 else None


def grab(pattern: str, text: str, what: str) -> str:
    m = re.search(pattern, text, MULTI)
    if not m:
        raise SystemExit(f"FAIL parse: {what} not found ({pattern})")
    return m[1]


def section(text: str, head: str) -> str:
    """From the heading starting with `head` to the next heading of the same or higher level."""
    m = re.search(rf"^(#+) {re.escape(head)}", text, MULTI)
    if not m:
        return ""
    level = len(m[1])
    rest = text[m.end() :]
    nxt = re.search(rf"^#{{1,{level}}} ", rest, MULTI)
    return text[m.start() : m.end() + (nxt.start() if nxt else len(rest))]


def table_rows(block: str) -> list[list[str]]:
    rows = []
    for ln in block.splitlines():
        if ln.startswith("|") and not re.match(r"^\|\s*-{3}", ln):
            rows.append([c.strip() for c in ln.strip().strip("|").split(" | ")])
    return rows[1:] if rows else []


# ---------------------------------------------------------------------------- tokens


def load_theme(name: str) -> dict[str, object]:
    merged: dict[str, object] = {}
    for f in THEMES[name]:
        data = json.loads(read(TOKENS / f))
        merged.update({k: v.get("$value") for k, v in data.items() if isinstance(v, dict)})
    return merged


def resolve(tokens: dict[str, object], name: str) -> str:
    if name not in tokens:
        return "MISSING"
    value, hops = tokens[name], 0
    while isinstance(value, str) and value.startswith("{") and value.endswith("}") and hops < 12:
        value, hops = tokens.get(value[1:-1], "MISSING"), hops + 1
    return str(value)


def px(tokens: dict[str, object], name: str) -> int:
    v = resolve(tokens, name)
    if v == "MISSING":
        raise SystemExit(f"FAIL token {name} missing")
    return int(float(v))


def rgb(hex6: str) -> tuple[int, int, int]:
    h = hex6.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def luminance(hex6: str) -> float:
    lin = [
        c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        for c in (v / 255 for v in rgb(hex6))
    ]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def show_ratio(r: float) -> str:
    near = any(abs(r - bar) < 0.005 for bar in (3.0, 4.5, 7.0))
    return f"{r:.4f}" if near else f"{r:.2f}"


def lab(c: tuple[float, float, float]) -> tuple[float, float, float]:
    def lin(v: float) -> float:
        v = min(max(v, 0.0), 255.0) / 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(v) for v in c)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116

    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def simulate(hex6: str, sim: str) -> tuple[float, float, float]:
    c = rgb(hex6)
    m = MACHADO[sim]
    return (
        sum(m[0][i] * c[i] for i in range(3)),
        sum(m[1][i] * c[i] for i in range(3)),
        sum(m[2][i] * c[i] for i in range(3)),
    )


def delta_e(a: str, b: str, sim: str) -> float:
    la, lb = lab(simulate(a, sim)), lab(simulate(b, sim))
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(la, lb, strict=True)))


# ---------------------------------------------------------------------------- the parent's figures


def parent_facts(d02: str, constitution: str, spec: str) -> dict[str, float]:
    """E15-D02's stated rows, element widths and figures, parsed from its text (`D02`:159–186)."""
    t3 = section(d02, "3. The chrome budget")
    f: dict[str, float] = {
        "topbar": float(grab(r"an (\d+) px TopBar", t3, "TopBar height")),
        "statusbar": float(grab(r"a (\d+) px StatusBar", t3, "StatusBar height")),
        "navrail": float(grab(r"NavRail collapsed \((\d+) px\)", t3, "NavRail width")),
        "rightrail": float(grab(r"collapsed to a (\d+) px strip", t3, "RightRail strip")),
        "allowance.compact": float(
            grab(r"= \*\*(\d+) px\*\* of vertical chrome in compact", t3, "a")
        ),
        "allowance.comfortable": float(grab(r"= \*\*(\d+) px\*\* in comfortable", t3, "allowance")),
        "conditional.compact": float(grab(r"add at most (\d+) px compact", t3, "conditional")),
        "conditional.comfortable": float(grab(r"px compact or (\d+) px comfortable", t3, "cond")),
        "ceiling.compact": float(grab(r"a ceiling of (\d+) px compact", t3, "ceiling")),
        "share.compact": float(grab(r"one header row: (\d+) px compact", t3, "share")),
        "share.comfortable": float(grab(r"px compact, (\d+) comfortable", t3, "share")),
        "price_gutter.compact": float(grab(r"its (\d+) px price gutter", t3, "price gutter")),
        "price_gutter.comfortable": float(grab(r"and a (\d+) px gutter", t3, "gutter")),
        "inset": float(grab(r"side insets (\d+) \+ \d+", t3, "insets")),
        "handle": float(grab(r"the handle (\d+) \(", t3, "handle")),
        "gap": float(grab(r"; (\d+) between elements", t3, "gap")),
        "icon": float(grab(r"⋮ and × (\d+) each", t3, "⋮")),
        "icon_gap": float(grab(r"⋮ and × \d+ each, (\d+) apart", t3, "⋮ gap")),
        "kind": float(grab(r'"Tape" (\d+)', t3, "kind word")),
        "symbol": float(grab(r'"BTCUSDT ▾" (\d+)', t3, "symbol picker")),
        "interval": float(grab(r'"1m ▾" (\d+)', t3, "interval picker")),
        "badge.count": float(grab(r'"A · 1" (\d+)', t3, "badge count")),
        "badge.one": float(grab(r'"A · symbol" (\d+)', t3, "badge words")),
        "badge.three": float(grab(r"three axes in words (\d+)", t3, "badge three")),
        "env": float(grab(r"the env badge (\d+)", t3, "env badge")),
        "arm.short": float(grab(r'the arm state (\d+) \("LOCKED"', t3, "arm")),
        "arm.full": float(grab(r'"ARMED 4:32" (\d+)\)', t3, "arm countdown")),
        "prov.full": float(grab(r"the provenance (\d+) in full", t3, "provenance")),
        "prov.short": float(grab(r"in full and (\d+) as", t3, "via A")),
        "chart.actions": float(grab(r"a chart's own actions (\d+)", t3, "chart actions")),
        "positions.min": float(grab(r"\|\s+(\d+), so E29-D01", t3, "positions minimum")),
        "cluster.1280": float(grab(r"the right cluster takes about (\d+) px", d02, "cluster")),
        "tabs.1280": float(grab(r"leaving about (\d+) px for five tabs", d02, "tab space")),
        "reason.viewer": float(grab(r"beside Save adds about (\d+) px", d02, "viewer reason")),
        "reason.limit": float(grab(r"at 16 panels about (\d+) px", d02, "limit reason")),
        "p95.now": float(grab(r"Frame time now: ([\d.]+) ms", d02, "measured p95")),
        "p95.est": float(grab(r"added: about ([\d.]+) ms \(estimated\)", d02, "estimated p95")),
        "budget.ms": float(
            grab(r"\| C-14\.2 \| \d+ fps, <(\d+) ms p95 frame", constitution, "C-14.2")
        ),
        "refresh": float(grab(r"\| Q-6 \|[^|]+\| (\d+) Hz", spec, "Q-6 refresh")),
        "scalping.row": float(grab(r"`row` \(([\d.]+), [\d.]+\) ─ leaf 0 Chart", d02, "row")),
        "scalping.col": float(grab(r"`column` \(([\d.]+), [\d.]+\) ─ leaf 1 DOM", d02, "column")),
    }
    dense = re.search(r"`dense` stores `row` ([\d.]+) / ([\d.]+) / ([\d.]+)", t3)
    if not dense:
        raise SystemExit("FAIL parse: dense row sizes not found")
    f.update({f"dense.{i}": float(dense[i + 1]) for i in range(3)})
    for w, h, vw in re.findall(r"\*\*(\d+)×(\d+)\*\* at (\d+)×\d+", t3):
        f.setdefault(f"canvas.{vw}.w", float(w))
        f.setdefault(f"canvas.{vw}.h", float(h))
    rows = re.findall(r"^\| (Chart|DOM|Tape) +\|.*\| +(\d+) \| +(\d+) \|$", t3, MULTI)
    for kind, full, mn in rows:
        f[f"{kind.lower()}.full"], f[f"{kind.lower()}.min"] = float(full), float(mn)
    return f


def parent_cells(d02: str) -> dict[str, str]:
    """The parent's 2×2 cell figures (`D02`:175), W×H strings."""
    t3 = section(d02, "3. The chrome budget")
    return {
        "1920.compact": grab(r"= (\d+×\d+) at 1920×1080 and", t3, "1920 cell"),
        "1280.compact": grab(r"= \*\*(\d+×\d+)\*\* at 1280×800;", t3, "1280 cell"),
        "1280.comfortable": grab(r"(\d+×\d+) cells", t3, "comfortable cell"),
    }


# ---------------------------------------------------------------------------- the budget

Element = tuple[str, int, dict[int, int]]  # (name, full width, {step: width from that step})
RECT_ROWS = {  # §3.4's rows: (panel, width, density)
    ("chart", "1280", "compact"),
    ("dom", "1280", "compact"),
    ("chart", "1920", "compact"),
    ("chart", "1280", "comfortable"),
}
# the parent's header figures (`D02`:186), reported beside the token-measured ones
PARENT_HEADER = (
    ("chart", "full", "chart.full"),
    ("chart", "min", "chart.min"),
    ("dom", "full", "dom.full"),
    ("dom", "min", "dom.min"),
    ("tape", "s1", "tape.full"),
    ("tape", "min", "tape.min"),
    ("positions", "min", "positions.min"),
)
# §6.2's drawn frames that name a panel's column width: (layout, viewport, density) → the frame
FIT_FRAMES: dict[tuple[str, str, str], str] = {
    ("scalping", "1280", "compact"): "`populated-owner · compact · dark · 1280`",
    ("scalping", "1920", "compact"): "`populated-owner · compact · dark · 1920`",
    ("scalping", "1280", "comfortable"): "`populated-owner · comfortable · dark · 1280`",
    ("scalping", "1920", "comfortable"): "`populated-owner · comfortable · dark · 1920`",
    ("dense", "1280", "compact"): "`populated-owner-dense · compact · dark · 1280`",
}
# ruling (3): the drawn dense frame at the default density; comfortable 1280 is stated (c-4)
DENSE_REFIT = {("1280", "compact"), ("1280", "comfortable")}
STEPS: dict[str, tuple[int, ...]] = {  # the §3.6 steps each kind has (0 = full row)
    "chart": (0, 1, 3, 4, 5, 6),  # step 6: the letter-only badge (ruling (2), #319)
    "dom": (0, 1, 2, 3, 4, 5, 6),
    "tape": (0, 1, 3, 5, 6),
    "positions": (0, 1, 5),
}


def font_px(tokens: dict[str, object], style: str) -> int:
    v = tokens.get(style)
    if not isinstance(v, dict):
        raise SystemExit(f"FAIL token {style} missing")
    ref = str(v.get("fontSize", ""))
    return px(tokens, ref.strip("{}"))


def text_px(chars: str, size: int) -> int:
    return math.ceil(len(chars) * size * INTER_EM)


# The header's text widths, ported from the board builder's TIGHT / SAFE estimates (scratch builder
# `12-measure.js` CAPS + charEm + wordW + lineW, and `41-chrome.js` lw500 / lw600 / chipTextW /
# envW / syncW): per-character em upper bounds for Inter at or above its rendered advances, +2 % at
# weight 500, +5 % at 600, +4 % headroom; SAFE never below 0.57 em a character. The minimums are
# measured from tokens with these, never from the parent's 0.56 em estimates (ruling (1), #319).
INTER_CAPS_EM: dict[str, float] = {
    "A": 0.7, "B": 0.66, "C": 0.71, "D": 0.74, "E": 0.59, "F": 0.57, "G": 0.75, "H": 0.75,
    "I": 0.28, "J": 0.52, "K": 0.67, "L": 0.55, "M": 0.88, "N": 0.75, "O": 0.78, "P": 0.64,
    "Q": 0.78, "R": 0.66, "S": 0.64, "T": 0.63, "U": 0.74, "V": 0.7, "W": 0.98, "X": 0.68,
    "Y": 0.67, "Z": 0.63,
}  # fmt: skip
EM_SAFE, EM_HEADROOM = 0.57, 1.04
# the header's strings (§4.2.1, §4.2.3, §4.2.4; the builder's copy deck)
HDR_SYMBOL, HDR_INTERVAL, HDR_LETTER = "BTCUSDT", "1m", "A"
HDR_CHART_TOOLS = ("Candle", "FP", "Ind", "Draw")  # CMP-221's row: a picker, then three buttons
HDR_PROV_FULL, HDR_PROV_SHORT = "· symbol set by sync group A", "via A"
HDR_ARM_FULL, HDR_ARM_SHORT = "ARMED 4:32", "ARMED"
HDR_ENV = "LIVE"


def char_em(ch: str) -> float:
    if ch in " \u00a0":
        return 0.28
    if ch in "il.,:;'’!|":
        return 0.27
    if ch in "fjrt":
        return 0.37
    if ch == "m":
        return 0.88
    if ch == "w":
        return 0.8
    if ch in "bdghnopqu":
        return 0.6
    if "a" <= ch <= "z":
        return 0.56
    if ch in INTER_CAPS_EM:
        return INTER_CAPS_EM[ch]
    if ch.isdigit():
        return 0.64
    if ch == "·":
        return 0.4
    if ch in '()[]{}"“”‘':
        return 0.38
    if ch in "/-–":
        return 0.45
    return 1.0  # arrows, bullets, ×, ≥, —, …, %, +, −, § and other symbols


def line_w(text: str, size: int, weight: int, safe: bool) -> float:
    """One line, no wrap: the words plus the spaces between them (the builder's lineW)."""
    words = text.split(" ")
    boost = 1.05 if weight >= 600 else 1.02 if weight >= 500 else 1.0
    total = 0.0
    for w in words:
        tight = sum(char_em(c) for c in w) * size * boost * EM_HEADROOM
        total += max(tight, len(w) * size * EM_SAFE) if safe else tight
    space = size * EM_SAFE if safe else size * 0.28 * EM_HEADROOM
    return total + (len(words) - 1) * space


def font_weight(tokens: dict[str, object], style: str) -> int:
    v = tokens.get(style)
    if not isinstance(v, dict):
        raise SystemExit(f"FAIL token {style} missing")
    return px(tokens, str(v.get("fontWeight", "")).strip("{}"))


def header_elements(t: dict[str, object], density: str) -> dict[str, list[Element]]:
    """Each kind's header elements at their token widths (§4.2.1), with the §3.6 step changes;
    ⋮, × and the icon buttons at the density's own `size.control` (§10, ruling (1), #319)."""
    s1, s2 = px(t, "space.1"), px(t, "space.2")
    ctl, icon_sm, icon_md = (
        px(t, f"size.control.{density}"),
        px(t, "size.icon.sm"),
        px(t, "size.icon.md"),
    )
    label, caption = font_px(t, "type.ui.label"), font_px(t, "type.ui.caption")
    medium, semibold = px(t, "font.weight.medium"), px(t, "font.weight.semibold")
    cap_w = font_weight(t, "type.ui.caption")
    pill_pad = px(t, "space.inset.sm")

    def lw(text: str, weight: int) -> int:
        return math.ceil(line_w(text, label, weight, False))

    def chip(text: str) -> int:  # a caption in a chip: SAFE + 2 px of side bearings
        return math.ceil(line_w(text, caption, cap_w, True)) + 2

    def picker(text: str) -> int:  # a CMP-219 / CMP-220 trigger: the label, space.1, the caret
        return lw(text, medium) + s1 + icon_sm

    def sync(words: str | None) -> int:  # D-6's pill: the letter bold, then "· words"
        lead = chip(HDR_LETTER) + 2
        return 2 * s2 + lead + (s1 + chip(f"· {words}") if words else 0)

    env = 2 * s2 + lw(HDR_ENV, semibold) + 2 + s1 + icon_md  # CMP-075; LIVE's underline +2
    arm_full = 2 * pill_pad + lw(HDR_ARM_FULL, medium)
    arm_short = 2 * pill_pad + lw(HDR_ARM_SHORT, medium)
    close: Element = ("⋮ ×", 2 * ctl + s1, {5: ctl})
    tape_actions = TAPE_ACTIONS * ctl + (TAPE_ACTIONS - 1) * s1
    chart_tools: list[Element] = [
        ("own actions: " + HDR_CHART_TOOLS[0], picker(HDR_CHART_TOOLS[0]), {1: 0})
    ]
    chart_tools += [(f"own actions: {x}", lw(x, medium), {1: 0}) for x in HDR_CHART_TOOLS[1:]]
    return {
        "chart": [
            ("symbol", picker(HDR_SYMBOL), {}),
            ("interval", picker(HDR_INTERVAL), {}),
            *chart_tools,
            # step 6 shows the letter only, as the DOM's (§4.2.3; ruling (2), #319)
            ("sync badge", sync("symbol, crosshair, drawings"), {3: sync("3"), 6: sync(None)}),
            ("arm state", arm_full, {4: arm_short}),
            close,
        ],
        "dom": [
            ("kind", lw("DOM", semibold), {}),
            ("symbol", picker(HDR_SYMBOL), {}),
            ("provenance", chip(HDR_PROV_FULL), {2: chip(HDR_PROV_SHORT), 6: 0}),
            # step 6 shows the letter only; the name stays "Sync group A" (ruling (2), #319)
            ("sync badge", sync("symbol"), {3: sync("1"), 6: sync(None)}),
            ("env badge", env, {}),
            ("arm state", arm_full, {4: arm_short}),
            ("own actions", 0, {1: 0}),  # the DOM row has none (`D02`:186)
            close,
        ],
        "tape": [
            ("kind", lw("Tape", semibold), {}),
            ("symbol", picker(HDR_SYMBOL), {}),
            ("sync badge", sync("symbol"), {3: sync("1"), 6: sync(None)}),
            ("own actions", tape_actions, {1: 0}),
            close,
        ],
        "positions": [
            ("kind", lw("Positions", semibold), {}),
            ("scope", lw("all symbols", medium), {}),
            ("env badge", env, {}),
            close,
        ],
    }


def header_width(els: list[Element], step: int, inset: int, handle: int, gap: int) -> int:
    """Insets, the handle, then every present element with the element gap before it."""
    widths = []
    for _name, full, changes in els:
        w = full
        for s in sorted(changes):
            if s <= step:
                w = changes[s]
        if w:
            widths.append(w)
    return 2 * inset + handle + sum(widths) + gap * len(widths)


def budget(
    t: dict[str, object], f: dict[str, float], cells: dict[str, str]
) -> tuple[dict[str, str], dict[str, object], list[str], list[str]]:
    """(values by placeholder key, extra figures, parent-equality and fit FAILs, parent WARNs)."""
    v: dict[str, str] = {}
    extra: dict[str, object] = {}
    bad: list[str] = []
    warn: list[str] = []
    s1, s2, s3 = px(t, "space.1"), px(t, "space.2"), px(t, "space.3")
    ctl = {d: px(t, f"size.control.{d}") for d in DENSITIES}
    topbar, statusbar = int(f["topbar"]), int(f["statusbar"])
    hair, focus_b, thick = px(t, "border.hairline"), px(t, "border.focus"), px(t, "border.thick")
    frame_unfocused, frame_focused = 2 * hair, focus_b
    v["BUDGET:v.topbar"], v["BUDGET:v.statusbar"] = str(topbar), str(statusbar)
    rows: dict[str, dict[str, int]] = {}
    for d in DENSITIES:
        r = {
            "banner": ctl[d] + 2 * s1,
            "tabstrip": ctl[d] + 2 * s1,
            "restore": ctl[d] + 2 * s1,
            "tabgroup": ctl[d],
            "header": ctl[d],
            "status": ctl[d],
            "timestrip": ctl[d],
            "tray": ctl[d],
        }
        r["allowance"] = topbar + r["tabstrip"] + r["header"] + r["status"] + r["timestrip"]
        r["allowance"] += statusbar
        r["conditional"] = r["banner"] + r["restore"] + r["tabgroup"] + r["tray"]
        r["ceiling"] = r["allowance"] + r["conditional"]
        r["share"] = r["tabstrip"] + r["header"]
        rows[d] = r
        for k, val in r.items():
            v[f"BUDGET:v.{k}.{d}"] = str(val)
        for k in ("allowance", "conditional", "ceiling", "share"):
            want = f.get(f"{k}.{d}")
            if want is not None and int(want) != r[k]:
                bad.append(f"budget v.{k}.{d} = {r[k]} vs the parent's {int(want)} (`D02`:173)")
    gutter, hit, inset = s1, px(t, "size.target.min"), s3
    v.update(
        {
            "BUDGET:h.navrail": str(int(f["navrail"])),
            "BUDGET:h.rightrail-strip": str(int(f["rightrail"])),
            "BUDGET:h.gutter": str(gutter),
            "BUDGET:h.hitband": str(hit),
            "BUDGET:h.header-inset": str(inset),
            "BUDGET:focus.frame-px": f"{frame_focused} px",
            "BUDGET:focus.frame-axis-px": f"{2 * frame_focused} px",
            "BUDGET:focus.bar-px": f"{thick + hair} px",
        }
    )
    if frame_unfocused != frame_focused:
        bad.append(f"D-1: unfocused frame {frame_unfocused} px vs focused {frame_focused} px")
    # the splitter's hit band (D-13, §4.3): its reach past the gutter, into each neighbour past the
    # frame reservation, and the press area that stays the splitter's where a control wins (§4.3)
    reach = (hit - gutter) // 2
    v["BUDGET:h.hitband-reach"] = f"{reach} px"
    v["BUDGET:h.hitband-into-content"] = f"{reach - frame_focused} px"
    v["BUDGET:h.hitband-control-yield"] = f"{gutter + 2 * frame_focused} px"
    if reach >= frame_focused + inset:
        bad.append(f"D-13: the hit band reaches {reach} px, over the header's side inset")
    # the header's small targets (F-5): the handle's hit box spans its glyph, its space.1 and the
    # gap after it; the sync badge's hit box is the full header row; both at least size.target.min
    for d, hgap in (("compact", int(f["gap"])), ("comfortable", s3)):
        icon = px(t, "size.icon.sm" if d == "compact" else "size.icon.md")
        handle_hit = icon + s1 + hgap
        v[f"BUDGET:hit.handle.{d}"] = f"{handle_hit}×{ctl[d]}"
        v[f"BUDGET:hit.badge-visual.{d}"] = str(ctl[d] - s1)
        v[f"BUDGET:hit.badge.{d}"] = str(ctl[d])
        if min(handle_hit, ctl[d]) < hit:
            bad.append(f"F-5: the handle's hit box {handle_hit}×{ctl[d]} is below size.target.min")
    if int(f["badge.count"]) < hit or ctl["compact"] < hit:
        bad.append("F-5: the sync badge's hit box is below size.target.min")
    if int(f["handle"]) != px(t, "size.icon.sm") + s1:
        bad.append(f"F-5: the parent's handle {int(f['handle'])} px vs size.icon.sm + space.1")
    # the tab strip's right cluster (§3.5): CMP-001 labels at `type.ui.label` + paddingX each side
    label_px, caption_px = font_px(t, "type.ui.label"), font_px(t, "type.ui.caption")
    pad = px(t, "space.button.paddingX")

    def cluster(labels: tuple[str, ...]) -> int:
        widths = [text_px(lb, label_px) + 2 * pad for lb in labels] + [ctl["compact"]]
        return sum(widths) + s2 * (len(widths) - 1) + s3

    lock = px(t, "size.icon.sm") + s1  # the lock glyph that leads a T2 label (§1.4)
    c1280 = cluster(CLUSTER_LABELS)
    restored = cluster(CLUSTER_LABELS[:-1] + (RESTORED_SAVE,))
    r_viewer = lock + s2 + text_px(VIEWER_REASON, caption_px)
    r_limit = lock + s2 + text_px(LIMIT_REASON, caption_px)
    for name, got, key in (
        ("cluster", c1280, "cluster.1280"),
        ("viewer reason", r_viewer, "reason.viewer"),
        ("limit reason", r_limit, "reason.limit"),
    ):
        want = f[key]
        if abs(got - want) > PARENT_TOLERANCE * want:
            warn.append(f"tab strip {name}: {got} px vs the parent's about {int(want)} px")
    v["BUDGET:tab.cluster.1280"] = v["BUDGET:tab.cluster.1920"] = f"{c1280} px"
    v["BUDGET:tab.cluster.1280.restored"] = f"{restored} px"
    v["BUDGET:tab.reason.viewer"] = f"{r_viewer} px"
    v["BUDGET:tab.reason.limit"] = f"{r_limit} px"
    # the header's width at each collapse step (§3.6), measured from tokens (ruling (1), #319);
    # the parent's figures are reported beside them (extra .parent / .delta), never gated equal
    # comfortable: its own size.icon.md grip, its size.control buttons, space.3 gaps (§10)
    els = {d: header_elements(t, d) for d in DENSITIES}
    grip = {"compact": px(t, "size.icon.sm"), "comfortable": px(t, "size.icon.md")}
    mins: dict[str, dict[str, int]] = {d: {} for d in DENSITIES}
    step_w: dict[str, dict[str, dict[int, int]]] = {d: {} for d in DENSITIES}
    for kind, steps in STEPS.items():
        for d, gap in (("compact", s2), ("comfortable", s3)):
            handle = grip[d] + s1
            widths = {st: header_width(els[d][kind], st, inset, handle, gap) for st in steps}
            step_w[d][kind] = widths
            for st, w in widths.items():
                name = "full" if st == 0 else f"s{st}"
                key = f"hdr.{kind}.{name}"
                if d == "compact":
                    v[f"BUDGET:{key}"] = str(w)
                else:
                    extra[f"{key}.comfortable"] = w
            mins[d][kind] = widths[steps[-1]]
            if d == "compact":
                v[f"BUDGET:hdr.{kind}.min"] = str(mins[d][kind])
            else:
                v[f"BUDGET:hdr.{kind}.min.comfortable"] = str(mins[d][kind])
    for kind, step, pkey in PARENT_HEADER:
        got, want = int(v[f"BUDGET:hdr.{kind}.{step}"]), int(f[pkey])
        extra[f"hdr.{kind}.{step}.parent"] = want
        extra[f"hdr.{kind}.{step}.delta"] = got - want
    v["BUDGET:hdr.dom.min.parent"] = str(int(f["dom.min"]))
    v["BUDGET:hdr.dom.min.framed"] = str(mins["compact"]["dom"] + 2 * frame_focused)
    extra["hdr.chart.min.framed"] = mins["compact"]["chart"] + 2 * frame_focused
    for kind in STEPS:
        extra[f"hdr.{kind}.min.comfortable.framed"] = mins["comfortable"][kind] + 2 * frame_focused
    for kind in ("dom", "tape"):  # c-4: §3.3 states the comfortable 1280 split from these
        v[f"BUDGET:hdr.{kind}.min.comfortable.framed"] = str(
            mins["comfortable"][kind] + 2 * frame_focused
        )
    for vp, (vw, vh) in VIEWPORTS.items():
        cw = vw - int(f["navrail"]) - int(f["rightrail"])
        ch = vh - topbar - statusbar
        v[f"BUDGET:canvas.{vp}"] = f"{cw}×{ch}"
        if (f.get(f"canvas.{vp}.w"), f.get(f"canvas.{vp}.h")) != (float(cw), float(ch)):
            bad.append(f"budget canvas.{vp} = {cw}×{ch} vs the parent's (`D02`:175)")
        space = cw - c1280 - s3
        v[f"BUDGET:tab.space.{vp}"] = f"{space} px"
        if vp == "1280":
            v["BUDGET:tab.name-max-px"] = f"{space // TABS_BEFORE_OVERFLOW - 2 * s3} px"
        for d in DENSITIES:
            r = rows[d]
            dw, dh = cw, ch - r["tabstrip"]
            v[f"BUDGET:dock.{vp}.{d}"] = f"{dw}×{dh}"
            chart_rows = r["header"] + r["status"] + r["timestrip"]
            plot_h = dh - 2 * frame_focused - chart_rows
            v[f"BUDGET:plot.full.{vp}.{d}"] = str(plot_h)
            extra[f"plot.full.{vp}.{d}.parent_rule"] = vh - r["allowance"]
            v[f"BUDGET:plot.full.{vp}.{d}.parent"] = str(vh - r["allowance"])
            v[f"BUDGET:pct.{vp}.{d}"] = f"{100 * r['allowance'] / vh:.1f} %"
            cell_w, cell_h = (dw - gutter) // 2, (dh - gutter) // 2
            v[f"BUDGET:cell2x2.{vp}.{d}"] = f"{cell_w}×{cell_h}"
            want_cell = cells.get(f"{vp}.{d}")
            if want_cell and want_cell != f"{cell_w}×{cell_h}":
                bad.append(
                    f"budget cell2x2.{vp}.{d} = {cell_w}×{cell_h} vs the parent's {want_cell}"
                )
            pg = int(f[f"price_gutter.{d}"])
            v[f"BUDGET:plot2x2.{vp}.{d}"] = (
                f"{cell_w - 2 * frame_focused - pg}×{cell_h - 2 * frame_focused - chart_rows}"
            )
            extra[f"plot2x2.{vp}.{d}.parent_rule"] = f"{cell_w - pg}×{cell_h - chart_rows}"
            v[f"BUDGET:plot2x2.{vp}.{d}.parent"] = f"{cell_w - pg}×{cell_h - chart_rows}"
            avail = dw - gutter
            chart_w = round(avail * f["scalping.row"])
            v[f"BUDGET:scalping.split.{vp}.{d}"] = f"{chart_w} / {avail - chart_w}"
            avail3 = dw - 2 * gutter
            a, b = round(avail3 * f["dense.0"]), round(avail3 * f["dense.1"])
            extra[f"dense.split.{vp}.{d}.parent"] = f"{a} / {b} / {avail3 - a - b}"
            if (vp, d) in DENSE_REFIT:
                # ruling (3), #319: the DOM column, then the tape's, takes its framed minimum
                # from the chart column, never taking the chart below its own framed minimum
                # (D-14); c-4: comfortable 1280 needs it for both
                room = max(0, a - (mins[d]["chart"] + 2 * frame_focused))
                move_b = min(max(0, mins[d]["dom"] + 2 * frame_focused - b), room)
                c_need = mins[d]["tape"] + 2 * frame_focused - (avail3 - a - b)
                move_c = min(max(0, c_need), room - move_b)
                a, b = a - move_b - move_c, b + move_b
                if move_b + move_c:
                    extra[f"dense.split.{vp}.{d}.moved"] = move_b + move_c
            v[f"BUDGET:dense.split.{vp}.{d}"] = f"{a} / {b} / {avail3 - a - b}"
            # the fit gate (ruling (1)): every header minimum + 2 × the frame within its column
            cols = {"dense": {"chart": a, "dom": b, "tape": avail3 - a - b, "positions": dw}}
            cols["scalping"] = {"chart": chart_w, "dom": avail - chart_w}
            for layout, colmap in cols.items():
                drawn = (layout, vp, d) in FIT_FRAMES
                label = FIT_FRAMES.get((layout, vp, d), f"§3.3 {layout} {vp} {d}, not drawn")
                for kind, col in colmap.items():
                    # the step the frame draws: the first whose width fits inside the frame (§3.6)
                    inside = col - 2 * frame_focused
                    shown = [st for st, w in step_w[d][kind].items() if w <= inside]
                    if drawn:
                        v[f"BUDGET:step.{layout}.{vp}.{d}.{kind}"] = (
                            str(shown[0]) if shown else "compact view"
                        )
                    got = mins[d][kind] + 2 * frame_focused
                    extra[f"fit.{layout}.{vp}.{d}.{kind}"] = f"{got} ≤ {col}"
                    if got > col:  # c-4: every split the spec states, drawn or not
                        bad.append(
                            f"fit: hdr.{kind}.min + 2 × frame = {got} px > the {layout} {kind} "
                            f"column {col} px ({label})"
                        )
            dom_w, dom_h = avail - chart_w, round((dh - gutter) * f["scalping.col"])
            boxes = {"chart": (chart_w, dh, chart_rows), "dom": (dom_w, dom_h, r["header"])}
            for panel, (bw, bh, used) in boxes.items():
                rect = {
                    state: (bw - 2 * fr, bh - 2 * fr - used)
                    for state, fr in (("unfocused", frame_unfocused), ("focused", frame_focused))
                }
                # §3.4's four rows are values; the other panels and widths are reported
                row34 = (panel, vp, d) in RECT_ROWS
                equal = "yes" if rect["unfocused"] == rect["focused"] else "NO"
                cells34 = {st: f"{w}×{h}" for st, (w, h) in rect.items()} | {"equal": equal}
                for part, cell in cells34.items():
                    rkey = f"BUDGET:rect.{panel}.{vp}.{d}.{part}"
                    if row34:
                        v[rkey] = cell
                    else:
                        extra[rkey] = cell
    # the frame-cost pair (D-11, BQ-5): fps = min(refresh, 1000 / p95), fixture values from D02
    refresh = f["refresh"]

    def fps(ms: float) -> str:
        return str(round(min(refresh, 1000 / ms)))

    v.update(
        {
            "BUDGET:cost.p95-now-ms": f"{f['p95.now']:g}",
            "BUDGET:cost.fps-now": fps(f["p95.now"]),
            "BUDGET:cost.p95-est-ms": f"{f['p95.est']:g}",
            "BUDGET:cost.fps-est": fps(f["p95.est"]),
            "BUDGET:cost.budget-ms": f"{f['budget.ms']:g}",
            "BUDGET:cost.budget-fps": fps(f["budget.ms"]),
        }
    )
    return v, extra, bad, warn


# ---------------------------------------------------------------------------- contrast, CVD, counts


def token_list(cell: str) -> list[str]:
    """Backticked token names of a cell; `.secondary` continues the previous token's prefix."""
    out: list[str] = []
    for name in re.findall(r"`([a-z0-9.-]+)`", cell):
        if name.startswith(".") and out:
            name = out[-1].rsplit(".", 1)[0] + name
        out.append(name)
    return out


def contrast_rows(
    spec: str, themes: dict[str, dict[str, object]]
) -> tuple[dict[str, str], list[dict[str, object]], list[str]]:
    """§11.2's rows measured: (values by key, the matrix for --json, FAILs)."""
    values: dict[str, str] = {}
    matrix: list[dict[str, object]] = []
    bad: list[str] = []
    rows = table_rows(section(spec, "11.2 Contrast"))
    if not rows:
        bad.append("§11.2 has no contrast table")
    for cells in rows:
        if len(cells) < 9:
            bad.append(f"§11.2 row unparsable: {cells[:1]}")
            continue
        row = cells[0].strip("`")
        fgs, bgs = token_list(cells[2]), token_list(cells[3])
        if "panel surfaces" in cells[3] or "neighbours" in cells[3]:
            bgs = list(dict.fromkeys(bgs + list(SURFACES)))
        bar_cell = cells[4]
        # "reported" = a hue-proximity pair (no shared edge), measured and never gated (lens F-11)
        bar = None if bar_cell.startswith(("n/a", "reported")) else float(bar_cell.split()[0])
        entry: dict[str, object] = {"row": row, "fg": fgs, "bg": bgs, "bar": bar}
        ok, reported_miss = True, []
        for th, tok in themes.items():
            hexes = {b: resolve(tok, b) for b in bgs}
            if not fgs or any(x == "MISSING" for x in hexes.values()):
                bad.append(f"§11.2 {row}: a token is missing in {th}")
                ok = False
                continue
            dark_bg = min(bgs, key=lambda b: luminance(hexes[b]))
            light_bg = max(bgs, key=lambda b: luminance(hexes[b]))
            for side, b in (("lo", dark_bg), ("hi", light_bg)):
                ratio = min(contrast(resolve(tok, fg), hexes[b]) for fg in fgs)
                values[f"CR:{row}:{th}:{side}"] = show_ratio(ratio)
                entry[f"{th}.{side}"] = round(ratio, 4)
                entry[f"{th}.{side}.bg"] = b
                if bar is not None and ratio < bar:
                    ok = False
                if "7.0 reported" in bar_cell and ratio < REPORTED_BAR:
                    reported_miss.append(th)
        if bar is None:
            verdict = "reported" if bar_cell.startswith("reported") else "n/a (structure)"
        else:
            verdict = "PASS" if ok else "FAIL"
            if "7.0 reported" in bar_cell:
                miss = sorted(set(reported_miss))
                verdict += " (7.0 met)" if not miss else f" (7.0 not met: {', '.join(miss)})"
        values[f"CR:{row}:verdict"] = verdict
        entry["verdict"] = verdict
        matrix.append(entry)
        if verdict.startswith("FAIL"):
            bad.append(f"contrast {row}: FAIL against its {bar} bar (a design finding)")
    return values, matrix, bad


def cvd_values(dark: dict[str, object]) -> dict[str, str]:
    out: dict[str, str] = {}
    for pair, (a, b) in CVD_PAIRS.items():
        for sim in MACHADO:
            out[f"CR:cvd.{pair}.{sim}"] = f"{delta_e(resolve(dark, a), resolve(dark, b), sim):.1f}"
    return out


def counts(spec: str, cr: list[dict[str, object]]) -> dict[str, str]:
    s0 = section(spec, "0. Artefacts")
    boards = re.findall(r"^\| (\d{2}) +\| `E15-D03 / \d{2} ([a-z0-9-]+)`", s0, MULTI)
    matrix = table_rows(section(spec, "6.1 The matrix"))
    cells = [c for row in matrix for c in row[1:]]
    reasons = [
        q
        for row in table_rows(section(spec, "8.1 T2 rows"))
        if len(row) > 3
        for q in re.findall(r'"([^"`][^"]*)"', CITE_FRAG.sub("", row[3]))
    ]
    name = re.search(
        r'"([^"]+)" \((?:\{\{COUNT:fixture\.long-name-chars\}\}|\d+<!--=COUNT:fixture\.long-name-chars-->)',
        spec,
    )
    return {
        "COUNT:boards": str(len(boards)),
        "COUNT:boards.light-twins": str(sum(slug.endswith("-light") for _n, slug in boards)),
        "COUNT:matrix.cells": str(len(cells)),
        "COUNT:matrix.drawn": str(sum(bool(re.match(r"B\d{2}\b", c)) for c in cells)),
        "COUNT:matrix.on-request": str(sum(c.startswith("req") for c in cells)),
        "COUNT:contrast.rows": str(len(cr)),
        "COUNT:contrast.fail": str(sum(str(e["verdict"]).startswith("FAIL") for e in cr)),
        "COUNT:t2.reasons-max-chars": str(max((len(r) for r in reasons), default=0)),
        "COUNT:fixture.long-name-chars": str(len(name[1]) if name else 0),
    }


# ---------------------------------------------------------------------------- fill and anchors


def fill(text: str, values: dict[str, str]) -> tuple[str, list[str]]:
    """Replace every placeholder outside a code span with `VALUE<!--=KEY-->`."""
    unknown: list[str] = []

    def sub(m: re.Match[str]) -> str:
        if m[1] not in values:
            unknown.append(m[1])
            return m[0]
        return f"{values[m[1]]}<!--={m[1]}-->"

    out_lines = []
    for line in text.split("\n"):
        parts, pos = [], 0
        for c in CODE.finditer(line):
            parts.append(PLACEHOLDER.sub(sub, line[pos : c.start()]))
            parts.append(c[0])
            pos = c.end()
        parts.append(PLACEHOLDER.sub(sub, line[pos:]))
        out_lines.append("".join(parts))
    return "\n".join(out_lines), sorted(set(unknown))


def anchor_gates(name: str, text: str, values: dict[str, str], required: set[str]) -> list[str]:
    bad: list[str] = []
    seen: set[str] = set()
    for i, line in enumerate(text.split("\n"), 1):
        bare = CODE.sub("", line)
        for m in PLACEHOLDER.finditer(bare):
            bad.append(f"{name}:{i}: placeholder {{{{{m[1]}}}}} not filled")
        for m in ANCHOR.finditer(line):
            key = m[1]
            seen.add(key)
            want = values.get(key)
            if want is None:
                bad.append(f"{name}:{i}: anchor {key} is not a value the tool computes")
                continue
            before = line[: m.start()]
            lead = before[: len(before) - len(want)]
            if not before.endswith(want) or (lead and lead[-1] not in BOUNDARY):
                got = re.split(r"[ |*(]", before)[-1] if before else ""
                bad.append(f"{name}:{i}: {key} reads {got!r}; the tool computes {want!r}")
    for key in sorted(required - seen):
        bad.append(f"{name}: no anchored value for {key}")
    return bad


# ---------------------------------------------------------------------------- cites


def cite_path(cid: str) -> str | None:
    if re.fullmatch(r"\d{2}", cid):
        found = sorted(PLAN.glob(f"{cid}-*"))
        return found[0].relative_to(ROOT).as_posix() if found else None
    if cid == "D02":
        return "docs/design/E15/E15-D02.md"
    m = re.fullmatch(r"(E\d{2})-D\d{2}(?:\.md)?", cid)
    if m:
        return f"docs/design/{m[1]}/{cid.removesuffix('.md')}.md"
    if cid.endswith(".md") and "/" not in cid:
        return cid
    return None


Fetch = Callable[[str, str], str | None]


def cite_check(name: str, text: str, fetch: Fetch) -> tuple[list[str], list[str], int]:
    """(FAILs, WARNs, cites checked) for `ID`:N[–M][, :N] groups and `ID.md:N` "fragment"."""
    fails: list[str] = []
    warns: list[str] = []
    done: set[tuple[str, int, str]] = set()

    def lines_of(rev: str, rel: str) -> list[str] | None:
        t = fetch(rev, rel)
        return None if t is None else t.split("\n")

    def one(cid: str, n: int, frag: str) -> None:
        if (cid, n, frag) in done:
            return
        done.add((cid, n, frag))
        rel = cite_path(cid)
        base = lines_of(BASE, rel) if rel else None
        tag = f"{name}: `{cid}`:{n}"
        if rel is None or base is None:
            fails.append(f"{tag}: no such file at {BASE}")
            return
        head = lines_of(HEAD, rel)
        if frag:
            hits = [i + 1 for i, ln in enumerate(base) if frag in ln]
            if n not in hits:
                kind = "gone" if not hits else ("ambiguous" if len(hits) > 1 else "pinned wrong")
                fails.append(f'{tag} "{frag[:50]}": {kind} at the base (found at {hits[:5]})')
            elif head is not None and (n > len(head) or frag not in head[n - 1]):
                warns.append(f"{tag}: drifted at {HEAD} (the fragment left the line)")
            return
        if n < 1 or n > len(base) or not base[n - 1].strip():
            fails.append(f"{tag}: line missing or blank at {BASE}")
        elif head is not None and (n > len(head) or head[n - 1] != base[n - 1]):
            warns.append(f"{tag}: drifted at {HEAD}")

    for m in CITE_FRAG.finditer(text):
        one(f"{m['id']}.md", int(m["line"]), m["frag"] or "")
    for m in CITE_GROUP.finditer(text):
        if m["id"].endswith(".md:"):
            continue
        refs = [m["first"]] + re.findall(r":(\d+(?:[–-]\d+)?)", m["more"])
        for ref in refs:
            for part in re.split(r"[–-]", ref):
                one(m["id"], int(part), "")
    return fails, warns, len(done)


def git_fetch(rev: str, rel: str) -> str | None:
    return git_show(rev, rel)


# ---------------------------------------------------------------------------- frame gates (A2)

# `D02`:292's consequence sentence, kept verbatim after the numbers (lens F-9; A-14)
COST_CONSEQUENCE = "That is over the performance budget, so charts may stutter."
COST_PAIR = re.compile(r"(\S+) ms · (\S+) fps; (\S+) ms · (\S+) fps")
COST_BODY = re.compile(
    r"Frame time now: (\S+) ms per frame \(p95, last 10 s, measured\), about (\S+) fps\. "
    r"With [A-Za-z ]+ added: about (\S+) ms \(estimated\), about (\S+) fps\. "
    r"Budget: (\S+) ms \((\S+) fps\)\."
)
DOT_CELL = re.compile(r"every header|every row|steps 0–6|its header")


def names_ok(cell: str) -> list[str]:
    """Order-capable region names lacking their environment word."""
    return [
        n
        for n in re.findall(r'"([^"]+)"', cell)
        if n.startswith(ORDER_CAPABLE) and not n.endswith(ENV_WORDS)
    ]


def anchored_ints(spec: str, key: str) -> list[int] | None:
    """The integers of the first value anchored as `key` in the spec ("522 / 383 / 255", "2 px")."""
    at = spec.find(f"<!--={key}-->")  # find the anchor, then read back (a lazy scan was ~0.6 s)
    m = re.search(r"([\d /]+?)(?: px)?$", spec[max(0, at - 80) : at]) if at >= 0 else None
    parts = [x.strip() for x in m[1].split("/")] if m else []
    return [int(x) for x in parts] if parts and all(x.isdigit() for x in parts) else None


def fit_gates(spec: str) -> list[str]:
    """Ruling (1), #319: hdr.<kind>.min + 2 × focus.frame-px ≤ its column on every §6.2 frame that
    names a column width, read from the spec's own anchors (so a minimum written over its column
    fails even before the anchor gate compares it with the tool)."""
    bad: list[str] = []
    register = section(spec, "6.2 The frame register")
    frame = anchored_ints(spec, "BUDGET:focus.frame-px")
    if not frame:
        return ["fit: the focus.frame-px anchor is missing"]
    for layout, vp, d in itertools.product(("scalping", "dense"), VIEWPORTS, DENSITIES):
        label = FIT_FRAMES.get((layout, vp, d), f"§3.3's {layout} split ({vp}, {d}; not drawn)")
        if (layout, vp, d) in FIT_FRAMES and f"| {label}" not in register:
            bad.append(f"fit: {label} is not a §6.2 frame row")
        suffix = "" if d == "compact" else f".{d}"  # comfortable: its own minimums (§3.6)
        cols = anchored_ints(spec, f"BUDGET:{layout}.split.{vp}.{d}")
        if not cols:
            bad.append(f"fit: the {layout}.split.{vp}.{d} anchor is missing")
            continue
        for kind, col in zip(("chart", "dom", "tape"), cols, strict=False):
            mn = anchored_ints(spec, f"BUDGET:hdr.{kind}.min{suffix}")
            if not mn:
                bad.append(f"fit: the hdr.{kind}.min{suffix} anchor is missing")
            elif mn[0] + 2 * frame[0] > col:
                bad.append(
                    f"fit: hdr.{kind}.min{suffix} {mn[0]} + 2 × {frame[0]} px > the {kind} column "
                    f"{col} px "
                    f"of {label}"
                )
    d3 = next((r for r in table_rows(section(spec, "2. Decisions")) if r[0] == "D-3"), [])
    if not d3 or re.search(
        r"(?:letter|badge) with its count|count[^.;|]{0,40}never collapse", d3[1]
    ):
        bad.append("D-3: the sync count is said never to collapse while step 6 drops it (c-3)")
    if not d3 or not all(c in d3[1] for c in ("`D02`:121", "`D02`:177")):
        bad.append("D-3: the step-6 count drop does not cite `D02`:121 and `D02`:177 (c-3)")
    rows = table_rows(section(spec, "4.2.3 The collapse strip"))
    step6 = [r for r in rows if r and r[0].startswith("6 = minimum")]
    if not step6 or "· A · LIVE" not in step6[0][1] or "A · 1" in step6[0][1]:
        bad.append("§4.2.3 step 6: the sync badge must show its letter only (ruling (2))")
    if not step6 or '"Sync group A"' not in " ".join(step6[0]):
        bad.append('§4.2.3 step 6: the badge\'s accessible name "Sync group A" is not stated')
    # ruling (2), #319: the chart has its own step 6, distinct from its step 5
    chart = {r[0]: r for r in rows if r and r[0].startswith("chart ")}
    c5, c6 = chart.get("chart 5"), chart.get("chart 6 = minimum")
    if not c5 or not c6 or c5[1] == c6[1]:
        bad.append("§4.2.3 step 6: the chart's step 5 and step 6 rows must both exist and differ")
    if not c6 or "· A · ARMED" not in c6[1] or "· A · 3" in c6[1] or "drawings" in c6[1]:
        bad.append("§4.2.3 step 6: the chart's sync badge must show its letter only (ruling (2))")
    if not c6 or '"Sync group A"' not in " ".join(c6):
        bad.append('§4.2.3 step 6: the chart badge\'s accessible name "Sync group A" is not stated')
    return bad


def frame_gates(spec: str) -> list[str]:
    bad: list[str] = []
    t2_ids = {row[0] for row in table_rows(section(spec, "8.1 T2 rows")) if row}
    register = table_rows(section(spec, "6.2 The frame register"))
    if len(register) < 20:
        bad.append(f"§6.2 register: {len(register)} frame rows (expected the drawn set, ≥ 20)")
    by_board: dict[str, set[str]] = {}  # each dark board's gated rows, for its light twin
    for row in register:
        if len(row) == 8 and not TWIN_ROW.match(row[0]):
            by_board.setdefault(row[1], set()).update(re.findall(r"\bR-\d+", row[5]))
    for prefix in GATED_FRAMES:
        if not any(row and row[0].startswith(prefix) for row in register):
            bad.append(f"§6.2: no register row for the gated frame {prefix}` (M-4)")
    for row in register:
        if len(row) != 8:
            bad.append(f"§6.2 row unparsable ({len(row)} cells): {row[0][:60]}")
            continue
        frame, _board, focus, names, restored, gated, dots, cost = row
        tag = f"§6.2 {frame[:70]}"
        if not focus.startswith(("n/a", "as ")) and "frame fill + bar" not in focus:
            bad.append(f"{tag}: Focus names a panel without 'frame fill + bar' (M-1)")
        if focus.startswith("n/a") and not frame.startswith(NO_PANEL_FRAMES):
            bad.append(f"{tag}: Focus 'n/a' on a frame that draws panels (M-1)")
        for n in names_ok(names):
            bad.append(f"{tag}: region name {n!r} has no environment word (M-2)")
        is_restored = frame.startswith(("`restored ·", "`restored-never-stored", "`tab-strip/"))
        triple = all(s in restored for s in ('"Restored"', "`*`", f'"{RESTORED_SAVE}"'))
        if is_restored and not restored.startswith("as ") and not triple:
            bad.append(f"{tag}: the restored triple (chip, `*`, Save label) is incomplete (M-3)")
        for rid in re.findall(r"\bR-\d+", gated):
            if rid not in t2_ids:
                bad.append(f"{tag}: gated row {rid} is not in §8.1")
        for prefix, need in GATED_FRAMES.items():
            if frame.startswith(prefix):
                cited = set(re.findall(r"\bR-\d+", gated))
                for rid in sorted(need - cited):
                    bad.append(f"{tag}: the gated frame lacks {rid} in its Gated cell (M-4)")
        twin = TWIN_ROW.match(frame)
        if twin:
            want = by_board.get(twin[2], set())
            pointer = re.match(r"as (\d{2})\b", gated)
            if pointer and pointer[1] != twin[2]:
                bad.append(f"{tag}: Gated cell points at board {pointer[1]}, not its twin (M-4)")
            got = by_board.get(pointer[1], set()) if pointer else set(re.findall(r"\bR-\d+", gated))
            for rid in sorted(want - got):
                bad.append(f"{tag}: the light twin lacks board {twin[2]}'s {rid} (M-4)")
        no_panel = focus.startswith("n/a")
        if not (no_panel and dots.startswith("n/a")) and not DOT_CELL.search(dots):
            bad.append(f"{tag}: ⋮ cell {dots!r} does not put ⋮ on every header (M-5)")
        if frame.startswith("`limits-cost-confirm") and not COST_PAIR.search(cost):
            bad.append(f"{tag}: the cost cell lacks the 'ms · fps' pair twice (M-6)")
    # §4.2.3: ⋮ present at every step and in every header text
    strip = table_rows(section(spec, "4.2.3 The collapse strip"))
    if len(strip) < 14:
        bad.append(
            f"§4.2.3: {len(strip)} step rows (expected DOM 0–6, the compact view, chart 0–6)"
        )
    for row in strip:
        if len(row) < 4 or row[3] != "present" or "⋮" not in row[1]:
            bad.append(f"§4.2.3 step {row[0]}: ⋮ missing from the row or its column (M-5)")
        for n in names_ok(row[1]):
            bad.append(f"§4.2.3 step {row[0]}: {n!r} has no environment word (M-2)")
    s424 = section(spec, "4.2.4 One row per kind")
    heads = HEADER_TEXT.findall(s424)
    if len(heads) < 12:
        bad.append(f"§4.2.4: {len(heads)} quoted header texts (expected every kind's row)")
    for h in heads:
        if "⋮" not in h:
            bad.append(f"§4.2.4 header {h[:50]!r}: ⋮ missing (M-5, D-3)")
    for row in table_rows(s424):
        if len(row) >= 2 and not HEADER_TEXT.match(row[1]) and "§4.2.3 step" not in row[1]:
            bad.append(f"§4.2.4 {row[0]}: the header cell is neither a header text nor a step")
    for row in table_rows(s424):
        env_kind = len(row) >= 4 and not row[2].startswith("none")
        if env_kind and not row[3].strip('"').endswith(ENV_WORDS):
            bad.append(f"§4.2.4 {row[0]}: region name {row[3]} has no environment word (M-2)")
    # §5: the restored rows and the cost confirm
    states = {r[0].split()[0]: " | ".join(r) for r in table_rows(section(spec, "5. SCR-020"))}
    rest = states.get("`restored`", "")
    if not all(s in rest for s in ('"Restored"', "`*`", f'"{RESTORED_SAVE}"')):
        bad.append("§5 `restored`: the restored triple (chip, `*`, Save label) is incomplete (M-3)")
    if RESTORED_SAVE not in states.get("`restored-never-stored`", ""):
        bad.append("§5 `restored-never-stored`: no 'Save restored layout' (M-3)")
    # A3 on the never-stored copy: a Discard exit in §5's notice, the register, `[⋯]` and §8.4 X-4
    never = [r for r in register if r and r[0].startswith("`restored-never-stored")]
    exits_pre = table_rows(section(spec, "8.4 Exits"))
    for where, cell in (
        ("§5 `restored-never-stored`", states.get("`restored-never-stored`", "")),
        ("§6.2 `restored-never-stored`", " | ".join(never[0]) if never else ""),
        ("§4.5 `[⋯]`", section(spec, "4.5 The toolbar")),
        ("§8.4 X-4", " | ".join(next((r for r in exits_pre if r[0] == "X-4"), []))),
    ):
        if RESTORED_DISCARD not in cell:
            bad.append(f"{where}: no '{RESTORED_DISCARD}' exit on the never-stored copy (M-9)")
    at16 = states.get("`limits-at-16`", "")
    if "T2" not in at16 or "`layout.limit.panels`" not in at16:
        bad.append("§5 `limits-at-16`: Add panel is not T2 `layout.limit.panels` (M-4)")
    save45 = next(
        (r for r in table_rows(section(spec, "4.5 The toolbar")) if r[0] == "`[Save]`"), []
    )
    if " | ".join(save45).count(f'"{RESTORED_SAVE}"') < 2:
        bad.append(f"§4.5 `[Save]`: '{RESTORED_SAVE}' missing on the restored columns (M-3)")
    if not COST_BODY.search(states.get("`limits-cost-confirm`", "")):
        bad.append("§5 `limits-cost-confirm`: the ms / fps pairs are incomplete (M-6)")
    if COST_CONSEQUENCE not in states.get("`limits-cost-confirm`", ""):
        bad.append("§5 `limits-cost-confirm`: D02:292's consequence sentence is missing (F-9)")
    # §8.1: the T2 anatomy per row; §1.4 keeps the lock glyph leading; §8.4 exits never gated
    rows81 = table_rows(section(spec, "8.1 T2 rows"))
    if not rows81:
        bad.append("§8.1 has no T2 rows")
    for row in rows81:
        line = " | ".join(row)
        if len(row) < 6:
            bad.append(f"§8.1 {row[0]}: unparsable")
            continue
        key_cell = CITE_FRAG.sub("", row[3])
        pointer = re.search(r"\bas R-\d", key_cell)
        if not pointer and not re.search(r"`(?:rbac|layout|workspace)\.[a-z_.]+`", key_cell):
            bad.append(f"§8.1 {row[0]}: no registered key (M-4)")
        reasons = re.findall(r'"([^"`][^"]*)"', key_cell)
        if not reasons and not pointer:
            bad.append(f"§8.1 {row[0]}: no reason (M-4)")
        bad += [f"§8.1 {row[0]}: reason over 60 characters" for r in reasons if len(r) > 60]
        if not re.search(r"2a|2b|pointer|notice", row[4]):
            bad.append(f"§8.1 {row[0]}: no form (M-4)")
        if re.search(r"color\.text\.disabled|opacity\.disabled", line):
            bad.append(f"§8.1 {row[0]}: a disabled token on a T2 row (M-4)")
        if close_glyph(row[1]) or EXIT_WORD.search(row[1]):  # c-2: an exit is never a T2 row
            bad.append(f"§8.1 {row[0]}: an exit ({row[1][:40]}) listed as a T2 row (M-8, §1.5)")
    s14 = section(spec, "1.4 The T2 rule")
    if "CMP-019 `lock` glyph" not in s14 or "**leads**" not in s14:
        bad.append("§1.4: the lock glyph leading the label is not stated (M-4)")
    if "(every row per §1.4)" not in spec:
        bad.append("§8.1: the heading no longer binds every row to §1.4 (M-4)")
    exits = table_rows(section(spec, "8.4 Exits"))
    if len(exits) < 5:
        bad.append(f"§8.4: {len(exits)} exit rows (expected X-1..X-5)")
    for row in exits:
        if re.search(
            r"lock|`rbac\.|`layout\.|T2|aria-disabled|reason", " | ".join(row), re.IGNORECASE
        ):
            bad.append(f"§8.4 {row[0]}: an exit carries a lock, key or reason (M-8)")
    return bad


def close_glyph(text: str) -> bool:
    """True when `text` names the close glyph ×, not a multiplication (1280×800, `a` × `b`,
    "7 states × 3 densities", W × H): an operand on both sides, or a digit before it."""
    for m in re.finditer("×", text):
        before, after = text[: m.start()].rstrip(" "), text[m.end() :].lstrip(" ")
        word = before.rsplit(" ", 1)[-1].lower()
        operands = bool(re.search(r"[\w`)>]$", before)) and bool(re.match(r"[\w`(]", after))
        if re.search(r"\d$", text[: m.start()]):
            continue
        if not operands or word in ("a", "an", "the"):
            return True
    return False


def text_gates(name: str, text: str) -> list[str]:
    """Whole-text gates: no lock on a splitter or ×, no gated Esc, E15-D04 never pinned or quoted,
    the ruling cited as the ruling, the #2701 marker on every BQ-3 / BQ-4 line (MJ-1..MJ-3)."""
    bad: list[str] = []
    s43 = section(text, "4.3 CMP-081 DockGrid")
    if s43 and LOCKISH.search(s43):
        bad.append(f"{name} §4.3: a lock, key or T2 drawn on a splitter (M-8)")
    for n, line in enumerate(text.split("\n"), 1):
        tag = f"{name}:{n}"
        if line.startswith("| M-"):  # §6.3 describes the mutations themselves
            continue
        # MJ-1r: the whole of every table row that names × or Close carries no lock or T2
        names_close = close_glyph(line) or re.search(r"\bClose\b", line)
        if line.startswith("|") and names_close and LOCKISH.search(line):
            bad.append(f"{tag}: a lock or T2 on a row that names × or Close (M-8)")
        # c-2: no clause that names an exit gates it, unless the clause negates
        for clause in re.split(r"[;|]|\.(?:\s|$)", line):
            exit_named = close_glyph(clause) or EXIT_WORD.search(clause)
            if exit_named and LOCKISH.search(clause) and not NEGATED.search(clause):
                bad.append(f"{tag}: an exit drawn with a lock, T2 or a key (M-8, §1.5)")
                break
        if ESC_GATED.search(line):
            bad.append(f"{tag}: Esc drawn as gated (M-8)")
        for m in re.finditer(r"E15-D04[^.|]{0,80}", line):
            if re.search(r"\b[0-9a-f]{7,40}\b", m[0]):
                bad.append(f"{tag}: E15-D04 pinned by a sha (PENDING, never pinned; A4)")
        if D04_QUOTE.search(line):  # MJ-1r: a quote on either side of "E15-D04"
            bad.append(f"{tag}: a sentence quoted as E15-D04's (PENDING, never quoted; A4)")
        if BQ_LIST in line and "the BQ list" not in line:
            bad.append(f"{tag}: issuecomment-{BQ_LIST} is the BQ list, not the ruling (A4)")
        if re.search(r"\bBQ-[34]\b", line) and OWNER_MARK not in line.lower():
            bad.append(f"{tag}: BQ-3 / BQ-4 applied without '{OWNER_MARK}'")
    if f"issuecomment-{RULING}" not in text:
        bad.append(f"{name}: the ruling issuecomment-{RULING} is never cited (A4)")
    ruled = re.search(r"^## .*RULED.*$", text, MULTI)
    if ruled and RULING not in ruled[0]:
        bad.append(f"{name}: the RULED heading does not cite the ruling (A4)")
    return bad


# c-1: each chord's own status: the shipped ids that bind it, or None for PROPOSED-PENDING
CHORD_STATUS: dict[str, tuple[str, ...] | None] = {
    "Ctrl+Alt+←": ("workspace.panel_prev", "workspace.panel_next"),
    "Ctrl+S": ("workspace.save", "workspace.save_as"),
    "Ctrl+1..9": ("workspace.preset",),
    "F11": ("workspace.fullscreen_panel",),
    "Ctrl+\\": None,
    "Shift+F10": None,
    "F2": None,
}


def keymap_gates(
    name: str, rows: list[list[str]], key_col: int, keymap: str | None, reserved: str | None = None
) -> list[str]:
    """MJ-4: every key row carries its `keymap.json` status; a chord already bound is named.
    c-1: each chord in CHORD_STATUS carries its own ids (shipped) or the PROPOSED mark (pending);
    c-5: a row citing `reserved-keys.json` names only keys that file reserves."""
    if keymap is None:
        return [f"{name}: keymap.json unreadable at {BASE}"]
    cmds = json.loads(keymap)["commands"]
    ids = {c["id"] for c in cmds}
    reserved_keys = set(json.loads(reserved)) if reserved else set()
    bad: list[str] = []
    for row in rows:
        keys, status = re.findall(r"`([^`]+)`", row[key_col]), row[-1]
        own = CHORD_STATUS.get(keys[0], ()) if keys else ()
        tag = f"{name} {row[key_col][:40]}"
        if own is None and (PENDING_KEY not in status or not status.startswith("none")):
            bad.append(f"{tag}: a pending chord lost 'none: {PENDING_KEY}' (c-1)")
        if own is None and re.search(r"\(shipped|shipped\)", status):
            bad.append(f"{tag}: a pending chord written as shipped (c-1)")
        for cid in own or ():
            if f"`{cid}`" not in status or PENDING_KEY in status:
                bad.append(f"{tag}: its own id `{cid}` (shipped) is not its status (c-1)")
        if "reserved-keys.json" in status and "not in `reserved-keys.json`" not in status:
            for k in keys:
                if reserved is None or k not in reserved_keys:
                    bad.append(f"{tag}: `{k}` is cited as reserved; reserved-keys.json lacks it")
    if not rows:
        bad.append(f"{name}: no key rows")
    for row in rows:
        status, keys = row[-1], re.findall(r"`([^`]+)`", row[key_col])
        tag = f"{name} {row[key_col][:40]}"
        named = set(re.findall(r"`([a-z]+\.[a-z_.]+)`", status)) - {"keymap.json"}
        for cid in sorted(named - ids):
            bad.append(f"{tag}: `{cid}` is not a keymap.json id")
        pending = PENDING_KEY in status
        if not named & ids and not pending and not re.search(r"component key|reserved", status):
            bad.append(f"{tag}: no keymap.json status (an id, or {PENDING_KEY})")
        if pending and not re.search(r"shipped path|until it ships", status):
            bad.append(f"{tag}: a pending chord names no shipped path")
        for c in cmds:
            scope = pending or c["context"] in ("Workspace", "Global")
            if c.get("defaultBinding") in keys and scope and c["id"] not in status:
                bad.append(f"{tag}: `{c['id']}` binds {c['defaultBinding']} and is not named")
    return bad


# ---------------------------------------------------------------------------- strings and tokens


def all_token_names() -> set[str]:
    names: set[str] = set()
    for f in (PRIM, DARK, LIGHT, HC):
        names |= {k for k, v in json.loads(read(TOKENS / f)).items() if isinstance(v, dict)}
    return names


def string_gates(name: str, text: str, d02_base: str | None, spec_mode: bool) -> list[str]:
    bad: list[str] = []
    if spec_mode:
        for s in REQUIRED_STRINGS:
            if s not in text:
                bad.append(f"{name}: required string missing: {s}")
        m = re.search(r'Its row at `D02`:659 reads: "(.+?)(?: …)?"\. ', text)
        if not m:
            bad.append(f"{name}: §8.2 no longer quotes E15-D02's row at `D02`:659")
        elif d02_base is not None:
            row659 = d02_base.split("\n")[658] if len(d02_base.split("\n")) > 658 else ""
            quote = re.sub(r"\s+", " ", m[1].rstrip(" …"))
            if quote not in re.sub(r"\s+", " ", row659):
                bad.append(f"{name}: §8.2's quote differs from `D02`:659 at the base")
    names = all_token_names()
    for line in text.split("\n"):
        # a name the catalogue uses but the JSON lacks may be QUOTED in a CR / C / A row or a
        # sentence that says so ("absent", "the catalogue's"); anywhere else it must exist
        quoted = re.match(r"\| (?:CR|C|A)-[\d.]+ ", line) or re.search(r"absent|catalogue", line)
        for tok in sorted(set(TOKEN_REF.findall(line))):
            if tok in PENDING_TOKENS:
                continue
            exists = (
                any(n.startswith(tok[:-1]) for n in names) if tok.endswith(".*") else tok in names
            )
            if not exists and not quoted:
                bad.append(f"{name}: unknown token {tok}")
    for m in HEX.finditer(text):
        bad.append(f"{name}: hex value {m[0]}")
    # lens F-10: a bare px value or a raw W×H outside a quote or a code span is neither a token
    # nor a tool value; every chrome dimension is a token name or an anchored `--json` value
    for line in text.split("\n"):
        bare = QUOTED.sub("", line)
        hits = [m[0] for m in BARE_PX.finditer(bare)]
        hits += [m[0] for m in BARE_DIM.finditer(bare) if m[0] not in INPUT_DIMS]
        for h in hits:
            bad.append(f"{name}: raw px {h!r} (a token or an anchored tool value)")
    return bad


def plot_gates(spec: str, extra: dict[str, object]) -> list[str]:
    """Each anchored plot is the parent's plot less D-1's frame on both sides, per axis (C-5)."""
    frame = re.search(r"(\d+) px<!--=BUDGET:focus\.frame-px-->", spec)
    if frame is None:
        return ["spec: no anchored focus.frame-px for the plot-vs-parent gate"]
    want = 2 * int(frame[1])
    bad: list[str] = []
    for key, rule in extra.items():
        if not key.endswith(".parent_rule"):
            continue
        plot = key.removesuffix(".parent_rule")
        m = re.search(r"([\d×]+)<!--=BUDGET:" + re.escape(plot) + "-->", spec)
        if m is None:
            bad.append(f"spec: no anchored {plot} for the plot-vs-parent gate")
            continue
        got = [int(x) for x in m[1].split("×")]
        par = [int(x) for x in str(rule).split("×")]
        if len(got) != len(par) or any(a - b != want for a, b in zip(par, got)):
            bad.append(
                f"spec: {plot} = {m[1]}; the parent's {rule} less 2 × frame ({want}) per axis"
            )
    return bad


# ---------------------------------------------------------------------------- the run

Computed = tuple[dict[str, str], dict[str, object], list[dict[str, object]], list[str], list[str]]


def compute(spec: str) -> Computed:
    """(values by key, extra figures, the contrast matrix, FAILs, WARNs) for one spec text."""
    themes = {k: load_theme(k) for k in THEMES}
    d02 = read(D02)
    f = parent_facts(d02, read(ROOT / "CONSTITUTION.md"), spec)
    values, extra, bad, warn = budget(themes["dark"], f, parent_cells(d02))
    cr_values, matrix, cr_bad = contrast_rows(spec, themes)
    values.update(cr_values)
    values.update(cvd_values(themes["dark"]))
    values.update(counts(spec, matrix))
    extra["parent"] = f
    return values, extra, matrix, bad + cr_bad, warn


def audit(
    spec: str, hand: str, comp: Computed, fetch: Fetch
) -> tuple[list[str], list[str], dict[str, int]]:
    values, extra, _matrix, bad, warn = comp
    fails, warns = list(bad), list(warn)
    fails += plot_gates(spec, extra)
    fails += anchor_gates("spec", spec, values, set(values) - SPEC_EXEMPT)
    if hand:
        fails += anchor_gates("hand-off", hand, values, set(HANDOFF_KEYS))
    n_cites = 0
    for name, text in (("spec", spec), ("hand-off", hand)):
        f_, w_, n = cite_check(name, text, fetch)
        fails, warns, n_cites = fails + f_, warns + w_, n_cites + n
    fails += frame_gates(spec)
    keymap = fetch(BASE, "apps/web/src/keymap/keymap.json")
    reserved = fetch(BASE, "apps/web/src/keymap/reserved-keys.json")
    rows_12 = table_rows(section(spec, "12.1 Keys"))
    fails += keymap_gates("spec §12.1", rows_12, 0, keymap, reserved)
    for name, text in (("spec", spec), ("hand-off", hand)):
        fails += text_gates(name, text) if text else []
    if hand:
        rows_k = table_rows(section(hand, "Table K"))
        fails += keymap_gates("hand-off Table K", rows_k, 1, keymap, reserved)
    fails += fit_gates(spec)
    d02_base = fetch(BASE, "docs/design/E15/E15-D02.md")
    fails += string_gates("spec", spec, d02_base, True)
    if hand:
        fails += string_gates("hand-off", hand, None, False)
    return fails, warns, {"cites": n_cites, "values": len(values)}


# every computed value is anchored in the spec, except these (the hand-off's or reported only)
SPEC_EXEMPT: set[str] = {
    "BUDGET:hdr.chart.s6",
    "BUDGET:hdr.dom.s6",
    "BUDGET:hdr.tape.s6",
}  # §3.6 shows step 6 as the minimum column


def line_sub(prefix: str, old: str, new: str) -> Callable[[str], str]:
    def fn(text: str) -> str:
        out = text.split("\n")
        for i, ln in enumerate(out):
            if ln.startswith(prefix) and old in ln:
                out[i] = ln.replace(old, new, 1)
                break
        return "\n".join(out)

    return fn


def re_sub(pattern: str, repl: str, count: int = 1) -> Callable[[str], str]:
    return lambda text: re.sub(pattern, repl, text, count=count, flags=MULTI)


# §6.2's gated frames and the §8.1 rows each must cite: blanking a Gated cell must fail (M-4, the verifier's finding)
GATED_FRAMES: dict[str, set[str]] = {
    "`CMP-082/states": {"R-7"},
    "`tab-strip/states": {"R-1", "R-2", "R-6"},
    "`populated-manager": {"R-9"},
    "`populated-viewer": {"R-2", "R-3", "R-4", "R-5", "R-6", "R-7"},
    "`populated-viewas": {"R-1", "R-3", "R-4", "R-5", "R-6"},
    "`limits-at-16": {"R-8"},
}


NO_PANEL_FRAMES = ("`tab-strip/states", "`empty")  # the only frames whose Focus may be "n/a"
TWIN_ROW = re.compile(r"board (\d{2}) \(light twin of (\d{2})\)")
HEADER_TEXT = re.compile(r'"(⠿[^"]*)"')
# MJ-1r: the lock in every form (lock, locked, locks), T2 and a gating key; case-sensitive, so the
# DOM's "LOCKED" arm state and a "lockout" never match
LOCKISH = re.compile(r"\block(?:ed|s)?\b|\bT2\b|`rbac\.|`layout\.limit|aria-disabled")
EXIT_WORD = re.compile(r"\b(?:Close|Move|Discard|Dismiss)\b|Revert to saved|`Esc`")
NEGATED = re.compile(r"\b(?:never|no|not|without)\b|n't\b")
D04_QUOTE = re.compile(r"[\"“”][^.|;]{0,80}\bE15-D04|\bE15-D04\b[^.|]{0,80}[\"“”]")
ESC_GATED = re.compile(r"`?Esc`?\b(?:(?!never|not\b|\|)[^.;|]){0,40}\bgated\b", re.IGNORECASE)
RULING, BQ_LIST = "6391960363", "6391925285"  # the orchestrator's ruling; the lane's BQ list
OWNER_MARK = "owner approval pending (#2701)"
PENDING_KEY = "PROPOSED-PENDING via CMP-022"


def dom_min_over_column(text: str) -> str:
    """hdr.dom.min written 1 px over the dense 1280 DOM column less the frame (ruling (1))."""
    cols = anchored_ints(text, "BUDGET:dense.split.1280.compact")
    frame = anchored_ints(text, "BUDGET:focus.frame-px")
    if not cols or not frame:
        return text
    over = cols[1] - 2 * frame[0] + 1
    return re.sub(r"\d+(<!--=BUDGET:hdr\.dom\.min-->)", rf"{over}\1", text)


def comfortable_min_over_column(text: str) -> str:
    """hdr.dom.min.comfortable written 1 px over the comfortable 1280 DOM column less the frame."""
    cols = anchored_ints(text, "BUDGET:scalping.split.1280.comfortable")
    frame = anchored_ints(text, "BUDGET:focus.frame-px")
    if not cols or not frame:
        return text
    over = cols[1] - 2 * frame[0] + 1
    return re.sub(r"\d+(<!--=BUDGET:hdr\.dom\.min\.comfortable-->)", rf"{over}\1", text)


def comfortable_parent_split(text: str) -> str:
    """c-4: the comfortable 1280 four-panel split written at the parent's (compact) ratios."""
    m = re.search(r"([\d /]+)<!--=BUDGET:dense\.split\.1280\.compact-->", text)
    if not m:
        return text
    key = r"[\d /]+(<!--=BUDGET:dense\.split\.1280\.comfortable-->)"
    return re.sub(key, lambda k: f" {m[1].strip()}{k[1]}", text)


MUTATIONS: tuple[tuple[str, str, Callable[[str], str], str], ...] = (
    # (gate class, name, mutation, expected outcome)
    ("fit", "a header minimum written 1 px over its column", dom_min_over_column, "FAIL"),
    (
        "fit",
        "a comfortable minimum written 1 px over its column",
        comfortable_min_over_column,
        "FAIL",
    ),
    (
        "fit",
        "step 6's sync badge restored to full",
        line_sub("| 6 = minimum", "· A · LIVE", "· A · 1 · LIVE"),
        "FAIL",
    ),
    (
        "fit",
        "the chart's step 6 drawn with the full sync badge",
        line_sub("| chart 6 = minimum", "· A · ARMED", "· A · symbol, crosshair, drawings · ARMED"),
        "FAIL",
    ),
    ("1 cites", "a line cite past the file's end", re_sub(r"`D02`:173\b", "`D02`:99999"), "FAIL"),
    (
        "1 cites",
        "a fragment cite's text gone",
        re_sub(r'`E15-D02\.md:944` "SCR-020', '`E15-D02.md:944` "SCR-021'),
        "FAIL",
    ),
    ("1 cites", "the cited file drifted at origin/main", lambda t: t, "WARN"),
    (
        "2 values",
        "the compact allowance changed",
        re_sub(r"\d+(<!--=BUDGET:v\.allowance\.compact-->)", r"231\1"),
        "FAIL",
    ),
    (
        "2 values",
        "a focused rect differs from its unfocused twin (M-7)",
        re_sub(r"(\d+)×(\d+)(<!--=BUDGET:rect\.chart\.1280\.compact\.focused-->)", r"1\1×\2\3"),
        "FAIL",
    ),
    (
        "2 values",
        "a contrast cell changed",
        re_sub(r"[\d.]+(<!--=CR:hdr-text:dark:lo-->)", r"1.00\1"),
        "FAIL",
    ),
    (
        "2 values",
        "a contrast verdict changed",
        re_sub(r"\w+(<!--=CR:focus-fill:verdict-->)", r"FAIL\1"),
        "FAIL",
    ),
    (
        "2 values",
        "a CVD ΔE changed",
        re_sub(r"[\d.]+(<!--=CR:cvd\.env-rule\.deuteranopia-->)", r"0.0\1"),
        "FAIL",
    ),
    (
        "2 values",
        "a matrix cell redrawn (the drawn count moves)",
        line_sub("| loading · compact·dense", "| req ", "| B06 "),
        "FAIL",
    ),
    ("2 values", "an anchor removed", re_sub(r"<!--=COUNT:boards-->", ""), "FAIL"),
    (
        "2 values",
        "a plot equal to the parent's (the frame not subtracted, C-5)",
        re_sub(
            r"564<!--=BUDGET:plot\.full\.1280\.compact-->",
            "568<!--=BUDGET:plot.full.1280.compact-->",
        ),
        "FAIL",
    ),
    (
        "2 values",
        "a placeholder left unfilled",
        re_sub(r"^(### 3\.1 .*)$", r"\1 {{BUDGET:v.topbar}}"),
        "FAIL",
    ),
    (
        "2 values",
        "a gated contrast row on a failing pair",
        line_sub("| `hdr-text`", "`color.text.primary`", "`color.surface.raised`"),
        "FAIL",
    ),
    (
        "3 frames",
        "M-1 the focus bar dropped from a focused frame",
        line_sub("| `populated-owner · compact · dark · 1920` ", "frame fill + bar", "focused"),
        "FAIL",
    ),
    (
        "3 frames",
        "M-2 the env word dropped from a register name",
        re_sub(r'"Chart, BTCUSDT 1 minute, Demo"', '"Chart, BTCUSDT 1 minute"'),
        "FAIL",
    ),
    (
        "3 frames",
        "M-2 the env word dropped from §4.2.4",
        line_sub("| `positions`", '"Positions, all symbols, Live"', '"Positions, all symbols"'),
        "FAIL",
    ),
    (
        "3 frames",
        "M-3 the Save label dropped from a restored frame",
        line_sub("| `restored · compact", '· "Save restored layout"', ""),
        "FAIL",
    ),
    (
        "3 frames",
        "M-9 the Discard exit dropped from the never-stored notice",
        line_sub("| `restored-never-stored`", "[Discard restored layout…] ", ""),
        "FAIL",
    ),
    (
        "3 frames",
        "M-9 the Discard exit dropped from §8.4 X-4",
        re_sub(
            r"^(\| X-4 [^\n]*?)Discard restored layout…([^\n]*?)Discard restored layout…", r"\1\2"
        ),
        "FAIL",
    ),
    (
        "2 values",
        "the splitter line back on color.border.strong (F-3)",
        re_sub(
            r"(\| `splitter-line` +\|[^|]*\| )`color\.text\.tertiary`", r"\1`color.border.strong`"
        ),
        "FAIL",
    ),
    (
        "2 values",
        "the handle's hit box shrunk to its glyph (F-5)",
        re_sub(r"24×24(<!--=BUDGET:hit\.handle\.compact-->)", r"16×24\1"),
        "FAIL",
    ),
    (
        "2 values",
        "the hit band's reach misstated (F-15)",
        re_sub(r"\d+ px(<!--=BUDGET:h\.hitband-reach-->)", r"12 px\1"),
        "FAIL",
    ),
    (
        "3 frames",
        "M-3 the chip dropped from §5's restored row",
        line_sub("| `restored` (stored layout)", '+ "Restored" ', ""),
        "FAIL",
    ),
    (
        "3 frames",
        "M-4 the key and reason dropped from R-9",
        line_sub("| R-9 ", '`rbac.account` "This account isn\'t assigned to you."', "scope"),
        "FAIL",
    ),
    (
        "3 frames",
        "M-4 a disabled token on a T2 row",
        line_sub("| R-2 ", "2a beside Save", "2a beside Save in `color.text.disabled`"),
        "FAIL",
    ),
    (
        "3 frames",
        "M-4 the lock glyph no longer leads",
        re_sub(r"the CMP-019 `lock` glyph", "the CMP-019 glyph"),
        "FAIL",
    ),
    (
        "3 frames",
        "M-5 ⋮ dropped from a collapse step",
        line_sub("| 3  ", "| present |", "| absent  |"),
        "FAIL",
    ),
    (
        "3 frames",
        "M-5 ⋮ dropped from a register row",
        line_sub("| `populated-viewer", "every header", "—"),
        "FAIL",
    ),
    (
        "3 frames",
        "M-6 fps without its ms in the register",
        line_sub("| `limits-cost-confirm · compact", " ms · ", " · "),
        "FAIL",
    ),
    (
        "3 frames",
        "M-6 the fps dropped from §5's confirm",
        line_sub("| `limits-cost-confirm`", " fps. With", ". With"),
        "FAIL",
    ),
    (
        "3 frames",
        "D02's consequence sentence dropped from §5's confirm",
        line_sub("| `limits-cost-confirm`", " " + COST_CONSEQUENCE, ""),
        "FAIL",
    ),
    (
        "3 frames",
        "M-4 a gated frame's Gated cell blanked",
        line_sub("| `limits-at-16", "| R-8 ", "| — "),
        "FAIL",
    ),
    (
        "3 frames",
        "M-8 an exit gated",
        line_sub("| X-1 ", "Close a panel", "Close a panel (T2 `rbac.view_as`)"),
        "FAIL",
    ),
    (
        "3 frames",
        "MJ-1 board 09's Gated cell 'as 05' blanked (light twin)",
        re_sub(r"^(\| board 09[^|]*\|(?:[^|]*\|){4} )as 05( +\|)", r"\1—    \2"),
        "FAIL",
    ),
    (
        "3 frames",
        "MJ-1 board 10's Gated cell R-8 blanked (light twin)",
        re_sub(r"^(\| board 10 .*?\| )R-8( +\|)", r"\1—  \2"),
        "FAIL",
    ),
    (
        "3 frames",
        "MJ-1 ⋮ removed from §4.2.4's chart header",
        line_sub("| `chart`", "ARMED 4:32 · ⋮ · ×", "ARMED 4:32 · ×"),
        "FAIL",
    ),
    (
        "3 frames",
        "MJ-1 ⋮ removed from §4.2.4's tape header",
        line_sub("| `tape`", "[Columns…] · ⋮ · ×", "[Columns…] · ×"),
        "FAIL",
    ),
    (
        "3 frames",
        "m-2 a lock drawn on a splitter (§4.3)",
        line_sub(
            "| hover ", "`color.text.tertiary` (§11.2", "`color.text.tertiary` and a lock (§11.2"
        ),
        "FAIL",
    ),
    (
        "3 frames",
        "m-2 T2 drawn on × (a register row)",
        re_sub(r"^(\| `populated-viewer .*?R-7)( +\|)", r"\1; × T2\2"),
        "FAIL",
    ),
    (
        "3 frames",
        "m-2 'Esc is gated' in §5 `conflict-entry`",
        re_sub(r"^(\| `conflict-entry` +\| )", r"\1`Esc` is gated; "),
        "FAIL",
    ),
    (
        "3 frames",
        "m-2 a populated frame's Focus written 'n/a'",
        line_sub("| `save-failed ·", "| Chart: frame fill + bar", "| n/a (no panel)"),
        "FAIL",
    ),
    (
        "3 frames",
        "m-2 §5's T2 key dropped from `limits-at-16`",
        line_sub(
            "| `limits-at-16`",
            "Add panel T2 `layout.limit.panels` with",
            "Add panel unavailable with",
        ),
        "FAIL",
    ),
    (
        "3 frames",
        "m-2 the Save label dropped from §4.5's restored column",
        line_sub("| `[Save]`", 'enabled **"Save restored layout"** |', 'enabled "Save" |'),
        "FAIL",
    ),
    (
        "4 strings",
        "m-2 E15-D04 pinned by a sha",
        re_sub(r"E15-D04 \(#4454\)", "E15-D04 (#4454) at `1234abcd`"),
        "FAIL",
    ),
    (
        "4 strings",
        "m-2 a sentence quoted as E15-D04's",
        re_sub(r"^(## 23\. .*)$", r'\1\n\nE15-D04 reads "The ghost follows the pointer."'),
        "FAIL",
    ),
    (
        "4 strings",
        "MJ-1r a quote written before E15-D04",
        re_sub(r"^(## 23\. .*)$", r'\1\n\n"The ghost follows the pointer." (E15-D04)'),
        "FAIL",
    ),
    (
        "3 frames",
        "MJ-1r 'locked for a viewer' on a §4.3 splitter row",
        line_sub(
            "| hover ", "(§11.2 `splitter-line`;", "(locked for a viewer; §11.2 `splitter-line`;"
        ),
        "FAIL",
    ),
    (
        "3 frames",
        "MJ-1r 'an × (locked for a viewer)' in §4.4's close row",
        line_sub(
            "| close ", "an × on the active tab", "an × (locked for a viewer) on the active tab"
        ),
        "FAIL",
    ),
    (
        "3 frames",
        "MJ-1r '× locked' in the viewer register row",
        re_sub(r"^(\| `populated-viewer .*?R-7)( +\|)", r"\1; × locked\2"),
        "FAIL",
    ),
    (
        "3 frames",
        "MJ-1r T2 and the lock in the next cell of §4.2.1 row 12",
        re_sub(r'^(\| 12 +\| × "Close \{Kind\}, \{symbol\}" +\| CMP-002)', r"\1; T2, a lock"),
        "FAIL",
    ),
    (
        "3 frames",
        "MJ-1r 'T2 for a viewer' replacing 'never gated' in §4.4's close row",
        line_sub("| close ", "never gated (§1.5)", "T2 for a viewer (§1.5)"),
        "FAIL",
    ),
    (
        "3 frames",
        "c-2 Close listed as a §8.1 T2 row",
        line_sub(
            "| R-9 ", "a manager's DOM arm toggle", "Close a panel and a manager's DOM arm toggle"
        ),
        "FAIL",
    ),
    (
        "3 frames",
        "c-2 §4.7's Close / Move written as T2",
        line_sub("The menu is D02 D-20's union", "themselves are never gated", "themselves are T2"),
        "FAIL",
    ),
    (
        "4 strings",
        "c-1 F2 written as `rules.rename` (shipped)",
        line_sub(
            "| `F2`",
            "none: PROPOSED-PENDING via CMP-022; collides with `rules.rename` (`F2`, context Rules)",
            "`rules.rename` (shipped)",
        ),
        "FAIL",
    ),
    (
        "4 strings",
        "c-1 Ctrl+S given another chord's id",
        line_sub(
            "| `Ctrl+S`",
            "`workspace.save` / `workspace.save_as` (shipped)",
            "`workspace.preset` (shipped)",
        ),
        "FAIL",
    ),
    (
        "4 strings",
        "c-3 D-3 says the sync count never collapses",
        line_sub("| D-3 ", "sync letter, env badge", "sync letter with its count, env badge"),
        "FAIL",
    ),
    (
        "fit",
        "c-4 the comfortable 1280 split back at the parent's ratios",
        comfortable_parent_split,
        "FAIL",
    ),
    (
        "4 strings",
        "c-5 the Esc row cites reserved-keys.json again",
        line_sub(
            "| `Esc`",
            "component key (APG menus, listboxes and dialogs), not a `keymap.json` row and not in "
            "`reserved-keys.json`",
            "reserved (`reserved-keys.json`), not a command row",
        ),
        "FAIL",
    ),
    (
        "4 strings",
        "MJ-2 the RULED heading cites the BQ list",
        re_sub(r"(RULED \(orchestrator, issuecomment-)6391960363", r"\g<1>6391925285"),
        "FAIL",
    ),
    (
        "4 strings",
        "MJ-3 the #2701 marker dropped from D-14 (BQ-3)",
        re_sub(r"\(BQ-3; owner approval pending \(#2701\)\)\.\*\*", "(BQ-3).**"),
        "FAIL",
    ),
    (
        "4 strings",
        "MJ-4 F2's collision with rules.rename unnamed",
        re_sub(
            r"collides with `rules\.rename` \(`F2`, context Rules\)", "collides with a Rules row"
        ),
        "FAIL",
    ),
    (
        "4 strings",
        "MJ-4 Ctrl+S's keymap ids dropped",
        re_sub(r"`workspace\.save` / `workspace\.save_as` \(shipped\)", "shipped"),
        "FAIL",
    ),
    ("4 strings", "'drawn on request' removed", re_sub("drawn on request", "later", 0), "FAIL"),
    (
        "4 strings",
        "a raw px value added (lens F-10)",
        re_sub(r"^(## 23\. .*)$", r"\1\n\nThe grip is 24×4 and the gutter 4 px."),
        "FAIL",
    ),
    ("4 strings", "a hex value added", re_sub(r"^(## 23\. .*)$", r"\1 #a1b2c3"), "FAIL"),
    (
        "4 strings",
        "an unknown token named",
        re_sub(r"^(## 23\. .*)$", r"\1\n\nThe ring uses `color.focus.rings`."),
        "FAIL",
    ),
    (
        "4 strings",
        "§8.2's quote of `D02`:659 altered",
        re_sub(r"\| none: the working copy \|", "| none: the copy |"),
        "FAIL",
    ),
    (
        "4 strings",
        "the layout.limit.panels key dropped",
        re_sub(r"`layout\.limit\.panels`", "`layout.limit.panes`", 0),
        "FAIL",
    ),
)


def drifting_fetch(rev: str, rel: str) -> str | None:
    text = git_fetch(rev, rel)
    if rev == HEAD and rel.endswith("E15-D02.md") and text is not None:
        return "inserted\n" + text
    return text


def selftest(spec: str, hand: str) -> tuple[bool, list[str]]:
    comp = compute(spec)
    filled, _ = fill(spec, comp[0])
    hand_f, _ = fill(hand, comp[0])
    base_fails, base_warns, _ = audit(filled, hand_f, compute(filled), git_fetch)
    lines = [f"baseline (filled in memory): {len(base_fails)} FAIL, {len(base_warns)} WARN"]
    ok = True
    for gate, name, fn, want in MUTATIONS:
        mutated = fn(filled)
        fetch: Fetch = drifting_fetch if want == "WARN" else git_fetch
        if mutated == filled and want != "WARN":
            ok = False
            lines.append(f"  [{gate}] {name}: NOT APPLIED (the anchor text moved)")
            continue
        try:
            fails, warns, _ = audit(mutated, hand_f, compute(mutated), fetch)
        except SystemExit as exc:
            fails, warns = [str(exc)], []
        new = [x for x in (fails if want == "FAIL" else warns) if x not in base_fails + base_warns]
        if gate == "fit":  # the fit gate itself must trip, not only the anchor gate beside it
            new = [x for x in new if x.startswith(("fit:", "§4.2.3 step 6"))]
        hit = bool(new)
        ok = ok and hit
        first = new[0][:110] if new else "no new " + want
        lines.append(f"  [{gate}] {name}: {'ok' if hit else 'MISSED'} — {first}")
    return ok, lines


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="E15-D03 workspace audit (see the module docstring)")
    ap.add_argument("--check", metavar="SPEC", help="audit this spec (default E15-D03.md)")
    ap.add_argument("--handoff", metavar="FILE", help="the hand-off (default: SPEC's -handoff.md)")
    ap.add_argument("--json", action="store_true", help="print every computed value as JSON")
    ap.add_argument("--fill", action="store_true", help="replace placeholders, then check")
    ap.add_argument("--selftest", action="store_true", help="mutation-test every gate class")
    args = ap.parse_args(argv)
    if isinstance(sys.stdout, io.TextIOWrapper):  # c-8: "≤" and "×" on a cp1252 console
        sys.stdout.reconfigure(encoding="utf-8")
    spec_path = Path(args.check) if args.check else SPEC
    hand_path = (
        Path(args.handoff) if args.handoff else spec_path.with_name(spec_path.stem + "-handoff.md")
    )
    spec = read(spec_path)
    hand = read(hand_path) if hand_path.exists() else ""
    if args.selftest:
        ok, lines = selftest(spec, hand)
        print("\n".join(lines))
        print(f"--selftest: {'ok' if ok else 'FAIL'} — {len(MUTATIONS)} mutations in memory")
        return 0 if ok else 1
    comp = compute(spec)
    if args.fill:
        spec, unknown = fill(spec, comp[0])
        hand, unknown_h = fill(hand, comp[0])
        spec_path.write_text(spec, encoding="utf-8")
        if hand:
            hand_path.write_text(hand, encoding="utf-8")
        for u in unknown + unknown_h:
            print(f"FAIL --fill: no value for {{{{{u}}}}}")
        comp = compute(spec)
    values, extra, matrix, _bad, _warn = comp
    if args.json and not args.check:
        print(json.dumps({"values": values, "extra": extra, "contrast": matrix}, indent=1))
        return 0
    fails, warns, n = audit(spec, hand, comp, git_fetch)
    if args.json:
        doc = {"values": values, "extra": extra, "contrast": matrix}
        doc.update({"fails": fails, "warnings": warns, "numbers": n})
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        print(
            f"## E15-D03 audit of {spec_path.name} (+ {hand_path.name if hand else 'no hand-off'})"
        )
        print(f"values computed: {n['values']}; cites checked: {n['cites']} at {BASE}")
        print("\n".join(f"WARN {w}" for w in warns))
        print("\n".join(f"FAIL {x}" for x in fails) or "OK — every gate passed")
        print(f"summary: {len(fails)} FAIL, {len(warns)} WARN")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
