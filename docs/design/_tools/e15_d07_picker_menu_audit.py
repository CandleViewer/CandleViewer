#!/usr/bin/env python3
"""E15-D07 (#361) audit: SCR-024 panel picker and SCR-028 panel context menu.

Standalone, offline, stdlib only; it executes no repo code. It reads the token JSON
(`packages/ui/tokens`, `themes.json` layering), and AS TEXT at the pinned base `6e2c1211fc`:
the merged parent `docs/design/E15/E15-D02.md`, `docs/plan/14-…`, `15-…`, `22-api-openapi.yaml`,
`apps/web/src/keymap/keymap.json` and `apps/web/src/shell/BrowserShellAdapter.ts`; then this
ticket's spec, hand-off and the working-tree `14` (its two pointer lines). It:

1. **Cites.** Every `NN`:line, `D02`:line, `E09-D09`:line, `<file>`:line cite in the spec and the
   hand-off is read at the base (`git show 6e2c1211fc:<path>`): OK when the line exists; WARN when
   the same line reads differently at `origin/main` (drift); FAIL when the file or line is gone or
   blank at the base, or a quoted fragment (`E15-D02.md:N` "…") is absent or ambiguous.
2. **Values.** Every `{{BUDGET:key}}`, `{{COUNT:key}}` and `{{CR:key}}` placeholder outside a code
   span is COMPUTED: the menu and picker geometry from the tokens (the density map below), the
   placement rectangles at the four corners, at 1920 and at 200 % from §5.6's rule, the dialog
   sizes and the budgets parsed from the base texts, contrast by the WCAG 2.x formula per theme,
   CVD as CIELAB ΔE76 after Machado, Oliveira & Fernandes (2009) severity 1.0, and the counts from
   the spec's own tables. `--fill` writes `VALUE<!--=KEY-->`; `--check` re-derives every anchored
   value and FAILs on a difference, a missing anchor or a `{{` left outside a code span.
3. **Frame gates (RULED condition 3).** §6.2's register is read ROW BY ROW: the Order cell of the
   chart, DOM and positions menus identical per theme and equal to §5.1; every other menu row the
   same fixed set, prefixed only by the conditional groups, Pop out removed only on the browser
   frames; every T2 item a lock plus a key from merged E15-D02 §8.1 (or the ruled
   `rbac.owner_only`), paired only with an item §5.5 / §4.4 lets carry that key (G-T2-PAIR);
   no lock on a sentence item; the opening focus on the first item neither T2 nor sentence-form
   (G-FOCUS); the viewer / view-as menus with no T2 item outside the Save inset; exits present, T1 and never gated; the destructive group last after a
   rule; the browser footnote with its PROPOSED sentence; `F11` and every unshipped chord
   PROPOSED; no sync colour; clipped 0 on every overflow frame; the picker's term, headings,
   category names and the reason in the name; every row on its §0 board. Plus the spec-wide gates
   of the ruling (confirm rule, owner marks, key model, C-4, the new keys' A-rows, the inventory,
   the growth rule and its text in `14` SCR-024 (G-TAX14), no `aria-disabled` on a sentence-form
   row (G-SENTENCE-ARIA), pins, the ruling cite, the mutation list).
4. **Strings and tokens.** Every backticked token exists (or is quoted in a CR / C / A row, or is
   the PENDING `color.sync.*`); no hex; no raw px outside a quote or a code span.
5. **--selftest** applies every §6.3 mutation M-n and one mutation per further ruled sentence R-n
   in memory to the filled spec; each must add exactly one FAIL, from the gate it names (a few
   gate-class mutations, marked, need only include it), and the text is restored byte-identical.

Geometry model (the spec's §10 tokens; `(heuristic)` where an estimate): text widths use Inter's
per-character em upper bounds of the E15-D03 tool (SAFE ≥ 0.57 em, +4 % headroom), the mono Kbd
0.6 em; a line height is ⌈size × lineheight⌉. Density: compact = `size.row.compact`,
`size.control.compact`, insets `space.inset.sm`, heading gap `space.stack.md`; comfortable =
`size.row.comfortable`, `size.control.comfortable`, `space.inset.md`, `space.stack.lg`. A menu has
a `border.hairline` edge, `space.1` padding-y, rows of the density's row height, separators of a
hairline plus `space.1` above and below; an item row is inset + `size.icon.sm` glyph + `space.2` +
max(label, second line) [+ `space.2` + Kbd chip or `size.icon.sm` chevron] + inset. The browser
footnote sits under its own separator, each sentence wrapped to the menu's inner width. A submenu
opens right of its parent item, first row aligned with it; "short" means the side cannot hold it
inside the viewport less `space.2` without covering an open ancestor menu; then it flips left.
The corner frames open at a pointer `space.8` from each corner in the dense layout (Chart, DOM and
Tape over Positions); Move to ▸ lists the three other panels. The picker's thumbnail is the two
text lines tall at 16:9 (heuristic); the mini-map is `space.16` tall at the 1280×800 aspect; the
list virtualises above three list heights of compact entries in the 1920 dialog (heuristic).

Usage:
  uv run --frozen --project services/api python docs/design/_tools/e15_d07_picker_menu_audit.py \
      --check [SPEC] [--handoff FILE] [--json] [--fill]
  ... e15_d07_picker_menu_audit.py --selftest
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import functools
import json
import math
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
SPEC = ROOT / "docs" / "design" / "E15" / "E15-D07.md"
PLAN14 = ROOT / "docs" / "plan" / "14-screens-catalogue.md"
BASE = "6e2c1211fc"  # every cite was read here (the spec's Key)
HEAD = "origin/main"  # drift is reported against this ref (WARN, never FAIL)
MULTI = re.MULTILINE

D02_REL = "docs/design/E15/E15-D02.md"
P14_REL = "docs/plan/14-screens-catalogue.md"
P15_REL = "docs/plan/15-component-catalogue.md"
P22_REL = "docs/plan/22-api-openapi.yaml"
KM_REL = "apps/web/src/keymap/keymap.json"
ADAPTER_REL = "apps/web/src/shell/BrowserShellAdapter.ts"
TOOL_REL = "docs/design/_tools/e15_d07_picker_menu_audit.py"

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
DENSITY: dict[str, dict[str, str]] = {
    "compact": {
        "row": "size.row.compact",
        "control": "size.control.compact",
        "inset": "space.inset.sm",
        "stack": "space.stack.md",
    },
    "comfortable": {
        "row": "size.row.comfortable",
        "control": "size.control.comfortable",
        "inset": "space.inset.md",
        "stack": "space.stack.lg",
    },
}
# Machado, Oliveira & Fernandes (2009), severity 1.0, applied to 0-255 sRGB as `cvd_sim.py` does.
MACHADO: dict[str, tuple[tuple[float, float, float], ...]] = {
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
# §11.3's two reported pairs (dark theme, the default)
CVD_PAIRS: dict[str, tuple[str, str]] = {
    "focus-ring": ("color.focus.ring", "color.surface.hover"),
    "danger": ("color.status.danger.strong", "color.text.primary"),
}

# ---- the ruling (issuecomment-6394505202's thread) and the spec's fixed facts
RULING_ID = "6394505202"
OWNER_MARK = "owner approval pending (#2701)"
OWNER_BQS = re.compile(r"\bBQ-(?:4|8|9|17)\b")
D04_MERGE, D06_MERGE = "c73aec08", "6e2c1211"
BOARDS_RULED, TWINS_RULED = 10, 3  # RULED BQ-17: ten boards, seven dark plus three light twins
NOT_OFFERED_RULED = 5  # RULED BQ-3: the five screens with no pane kind, one inventory row
TICKET_ENTRIES = 2  # D02 D-28: the order ticket and the trade-group ticket
RULED_T2_EXTRA = {"rbac.owner_only"}  # the ruling lists it beside merged §8.1's keys
# G-T2-PAIR: the only lawful item → key pairs (§5.5, §4.4; RULED BQ-6 / BQ-11 / BQ-12)
LIMIT_OUTCOME_KEYS = {"layout.limit.min_size", "layout.limit.depth", "layout.limit.tab_group"}
MENU_T2_PAIRS = {"Duplicate": {"layout.limit.panels"}}  # plus a Move to ▸ outcome (D04)
PICKER_T2_PAIRS = {
    "Order ticket": {"rbac.view_as", "rbac.permission"},
    "Trade-group ticket": {"rbac.view_as", "rbac.permission"},
    "Deep Stats": {"recording.symbol_not_recorded"},  # the recording entry (§1.7, illustrative)
    "Desk risk overview": {"rbac.owner_only"},  # the owner-only entry (§1.7, illustrative)
}
FOCUS_STATES = ("no-settings", "keyboard-specimen")  # the register names the opening focus
FOCUS_CLAUSE = re.compile(r"(?:^|; )focus on open: (?P<item>[^;]+)")
SENTENCE_ATTRS = "no `aria-disabled`; `aria-describedby` → the sentence"  # §1.6, condition 1
SHIPPED_FOOTNOTE = "Multi-window workspaces need the desktop app."
PROPOSED_FOOTNOTE = "Maximise (F11) gives a panel the whole workspace."
NO_RESULTS_TERM = "fotprint"
SHORT_RECORDING = "Needs a recorded symbol."
BROWSER_STATES = ("browser", "clamped-200")  # §6.2: clamped-200 is the browser menu at 200 %
VIEWER_STATES = {"viewer": "rbac.permission", "view-as": "rbac.view_as"}
EXIT_LABELS = {"Close", "Move panel", "Move to ▸", "Move to", "Undo move", "Cancel", "Esc", "`Esc`"}
MENU_EXITS = re.compile(r"(?:Undo move · )?Close · Move panel · Move to ▸ T1")
PICKER_EXITS = "Cancel · `Esc` T1"
LAST_CELL = "rule · Reset settings… · Close"
DESTRUCTIVE_GROUP = "Reset settings… · Close"
PLACE_OUTCOMES = ("Left of", "Right of", "Above", "Below", "As a tab with")
CONDITIONAL = re.compile(
    r"^((?:Undo move|[A-Z][\w-]* actions)(?: · (?:Undo move|[A-Z][\w-]* actions))*) / "
)
CHORD = re.compile(r"`((?:Ctrl|Shift|Alt)\+[^`]+)`")
SYNC_CHORDS = ("`Ctrl+Shift+1..3`", "`Ctrl+Shift+0`")
LANE_NAMES = re.compile(r"\b(?:hcl|hpe|vps)-worker-\d+\b|\bmain-orchestrator\b")
ESC_GATED = re.compile(r"`?Esc`?\b(?:(?!never|not\b|\|)[^.;|]){0,40}\bgated\b", re.IGNORECASE)

# ---- geometry fixtures (the dense layout of E15-D02 / E15-D04: Chart, DOM, Tape over Positions)
DENSE_PANELS = ("Chart · BTCUSDT 1m", "DOM · BTCUSDT", "Tape · BTCUSDT", "Positions")
CORNER_PANEL = {"tl": 0, "tr": 2, "bl": 3, "br": 3}  # the panel docked at each corner
CORNERS = {  # key → (frame state, viewport)
    "tl.1280": ("corner-top-left", (1280, 800)),
    "tr.1280": ("corner-top-right", (1280, 800)),
    "bl.1280": ("corner-bottom-left", (1280, 800)),
    "br.1280": ("corner-bottom-right", (1280, 800)),
    "br.1920": ("corner-bottom-right-1920", (1920, 1080)),
}
ZOOM = 2  # the clamped frame: 1280×800 at 200 %
POINTER_TOKEN = "space.8"
MINIMAP_TOKEN = "space.16"
THUMB_RATIO = 16 / 9  # (heuristic) a panel-shaped thumbnail
VIRTUALISE_SCREENS = 3  # (heuristic) virtualise above three list heights of entries
LIST_CEILING = 1000  # CMP-213's 1 000-item performance test (`15` CMP-213 Tests)

PENDING_TOKENS = {"color.sync.*": "E15-D06 (#4470), the colour tokens' owner"}
TOKEN_REF = re.compile(
    r"`((?:color|space|size|border|font|type|radius|elevation|opacity|motion)\.[a-z0-9.*-]+)`"
)
HEX = re.compile(
    r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|(?=[0-9a-fA-F]{3}\b)[0-9]*[a-fA-F][0-9a-fA-F]*)\b"
)
PLACEHOLDER = re.compile(r"\{\{([A-Z]+:[^{}]+)\}\}")
ANCHOR = re.compile(r"<!--=([A-Z]+:[^>]+?)-->")
CODE = re.compile(r"`[^`\n]*`")
QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”|`[^`\n]*`')
BARE_PX = re.compile(r"(?<![\w.>])\d+(?:\.\d+)? ?px\b(?!<!--=)")
BOUNDARY = " |*(/:;,—×"  # what may precede an anchored value
CITE_GROUP = re.compile(
    r"`(?P<id>[A-Za-z0-9._/-]+)`:(?P<first>\d+(?:[–-]\d+)?)(?P<more>(?:, :\d+(?:[–-]\d+)?)*)"
)
CITE_FRAG = re.compile(r"`(?P<id>E\d{2}-D\d{2})\.md:(?P<line>\d+)`(?: \"(?P<frag>[^\"]+)\")?")


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


Fetch = Callable[[str, str], str | None]


def git_fetch(rev: str, rel: str) -> str | None:
    return git_show(rev, rel)


def at_base(rel: str) -> str:
    text = git_show(BASE, rel)
    if text is None:
        raise SystemExit(f"FAIL parse: {rel} is not readable at {BASE}")
    return text


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


def split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split(" | ")]


def table_rows(block: str) -> list[list[str]]:
    rows = [
        split_row(ln)
        for ln in block.splitlines()
        if ln.startswith("|") and not re.match(r"^\|\s*-{3}", ln)
    ]
    return rows[1:] if rows else []


def quotes(cell: str) -> list[str]:
    return re.findall(r'"([^"`]+)"', cell)


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


def style_of(tokens: dict[str, object], style: str) -> tuple[int, int, float]:
    """(font size px, weight, line height factor) of a `type.*` composite."""
    v = tokens.get(style)
    if not isinstance(v, dict):
        raise SystemExit(f"FAIL token {style} missing")
    size = px(tokens, str(v.get("fontSize", "")).strip("{}"))
    weight = px(tokens, str(v.get("fontWeight", "")).strip("{}"))
    lh = float(resolve(tokens, str(v.get("lineHeight", "")).strip("{}")))
    return size, weight, lh


def line_h(tokens: dict[str, object], style: str) -> int:
    size, _w, lh = style_of(tokens, style)
    return math.ceil(size * lh - 1e-9)


def all_token_names() -> set[str]:
    names: set[str] = set()
    for f in (PRIM, DARK, LIGHT, HC):
        names |= {k for k, v in json.loads(read(TOKENS / f)).items() if isinstance(v, dict)}
    return names


# ---------------------------------------------------------------------------- colour


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


# ---------------------------------------------------------------------------- text widths

# Inter's per-character em upper bounds (the E15-D03 tool's, from its board builder); SAFE never
# below 0.57 em a character, +2 % at weight 500, +5 % at 600, +4 % headroom. (heuristic)
INTER_CAPS_EM: dict[str, float] = {
    "A": 0.7, "B": 0.66, "C": 0.71, "D": 0.74, "E": 0.59, "F": 0.57, "G": 0.75, "H": 0.75,
    "I": 0.28, "J": 0.52, "K": 0.67, "L": 0.55, "M": 0.88, "N": 0.75, "O": 0.78, "P": 0.64,
    "Q": 0.78, "R": 0.66, "S": 0.64, "T": 0.63, "U": 0.74, "V": 0.7, "W": 0.98, "X": 0.68,
    "Y": 0.67, "Z": 0.63,
}  # fmt: skip
EM_SAFE, EM_HEADROOM, MONO_EM = 0.57, 1.04, 0.6


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
    return 1.0  # arrows, bullets, ×, …, %, + and other symbols


def text_w(text: str, size: int, weight: int) -> int:
    """One line, no wrap, SAFE: the words plus the spaces between them."""
    words = text.split(" ")
    boost = 1.05 if weight >= 600 else 1.02 if weight >= 500 else 1.0
    total = 0.0
    for w in words:
        tight = sum(char_em(c) for c in w) * size * boost * EM_HEADROOM
        total += max(tight, len(w) * size * EM_SAFE)
    return math.ceil(total + (len(words) - 1) * size * EM_SAFE)


def style_w(tokens: dict[str, object], style: str, text: str, weight: int | None = None) -> int:
    size, w, _lh = style_of(tokens, style)
    return text_w(text, size, weight if weight is not None else w)


def wrap_lines(text: str, size: int, weight: int, avail: int) -> int:
    lines, cur = 1, ""
    for word in text.split(" "):
        trial = f"{cur} {word}" if cur else word
        if cur and text_w(trial, size, weight) > avail:
            lines, cur = lines + 1, word
        else:
            cur = trial
    return lines


# ---------------------------------------------------------------------------- the menu (§5.1)


@dataclass(frozen=True)
class Item:
    label: str
    hint: str = ""
    submenu: bool = False


def menu_groups(spec: str) -> list[list[Item]]:
    """§5.1's fixed set (the `text` block below the conditional groups), O-desktop."""
    block = re.search(r"```text\n(.*?)\n```", section(spec, "5.1 The fixed order"), re.DOTALL)
    if block is None:
        raise SystemExit("FAIL parse: §5.1 has no ```text block")
    groups: list[list[Item]] = []
    for line in block[1].split("\n"):
        if line.startswith("["):
            continue  # the conditional groups sit above the fixed set
        if line.startswith("─"):
            groups.append([])
            continue
        if not groups or not line.strip():
            continue
        parts = re.split(r"\s{2,}", line.strip())
        label, rest = parts[0], parts[1:]
        sub = bool(rest) and rest[0].startswith("▸")
        hint = "" if sub or not rest or rest[0] == "PROPOSED;" else rest[0]
        groups[-1].append(Item(f"{label} ▸" if sub else label, hint, sub))
    return [g for g in groups if g]


def order_text(groups: list[list[Item]], browser: bool) -> str:
    keep = [[i.label for i in g if not (browser and i.label == "Pop out")] for g in groups]
    return " / ".join(" · ".join(g) for g in keep if g)


# ---------------------------------------------------------------------------- geometry


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    def text(self) -> str:
        return f"{self.x}, {self.y}, {self.w}, {self.h}"

    def inside(self, vw: int, vh: int, m: int = 0) -> bool:
        return (
            self.x >= m and self.y >= m and self.x + self.w <= vw - m and self.y + self.h <= vh - m
        )

    def meets(self, o: Rect) -> bool:
        return (
            self.x < o.x + o.w
            and o.x < self.x + self.w
            and self.y < o.y + o.h
            and o.y < self.y + self.h
        )


@dataclass
class Box:
    """One menu level: its rows (label, kind: item / sep), width and its measures."""

    rows: list[str]
    w: int
    row: int
    sep: int
    pad: int
    edge: int
    extra: int = 0  # the browser footnote block under its own separator

    @property
    def h(self) -> int:
        items = sum(r != "—" for r in self.rows)
        seps = sum(r == "—" for r in self.rows)
        return 2 * self.edge + 2 * self.pad + items * self.row + seps * self.sep + self.extra

    def item_y(self, label: str) -> int:
        y = self.edge + self.pad
        for r in self.rows:
            if r == label:
                return y
            y += self.sep if r == "—" else self.row
        raise SystemExit(f"FAIL geometry: no row {label!r}")


@dataclass
class MenuMetrics:
    t: dict[str, object]
    density: str = "compact"
    row: int = 0
    inset: int = 0
    edge: int = 0
    pad: int = 0
    sep: int = 0
    glyph: int = 0
    gap: int = 0
    caption_lh: int = 0
    kbd_h: int = 0
    values: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        t, d = self.t, DENSITY[self.density]
        self.row, self.inset = px(t, d["row"]), px(t, d["inset"])
        self.edge, self.pad = px(t, "border.hairline"), px(t, "space.1")
        self.sep = self.edge + 2 * self.pad
        self.glyph, self.gap = px(t, "size.icon.sm"), px(t, "space.2")
        self.caption_lh = line_h(t, "type.ui.caption")
        self.kbd_h = line_h(t, "type.num.sm") + 2 * self.edge

    def kbd_w(self, hint: str) -> int:
        size, _w, _lh = style_of(self.t, "type.num.sm")
        return math.ceil(len(hint) * size * MONO_EM) + 2 * px(self.t, "space.1") + 2 * self.edge

    def width(self, items: list[Item], seconds: dict[str, list[str]], glyph: bool) -> int:
        """The widest row: lead + max(label, its second lines) + its Kbd chip or chevron."""
        lead = self.inset + (self.glyph + self.gap if glyph else 0)
        rows = []
        for i in items:
            body = [style_w(self.t, "type.ui.body", i.label.removesuffix(" ▸"))]
            body += [style_w(self.t, "type.ui.caption", s) for s in seconds.get(i.label, [])]
            tail = self.gap + (self.kbd_w(i.hint) if i.hint else self.glyph)
            rows.append(max(body) + (tail if i.hint or i.submenu else 0))
        return 2 * self.edge + lead + max(rows) + self.inset

    def box(
        self, groups: list[list[Item]], seconds: dict[str, list[str]], glyph: bool = True
    ) -> Box:
        rows: list[str] = []
        for g in groups:
            if rows:
                rows.append("—")
            rows += [i.label for i in g]
        items = [i for g in groups for i in g]
        return Box(rows, self.width(items, seconds, glyph), self.row, self.sep, self.pad, self.edge)

    def footnote_h(self, menu_w: int) -> int:
        size, weight, _lh = style_of(self.t, "type.ui.caption")
        avail = menu_w - 2 * self.edge - 2 * self.inset
        lines = sum(
            wrap_lines(s, size, weight, avail) for s in (SHIPPED_FOOTNOTE, PROPOSED_FOOTNOTE)
        )
        return 2 * self.inset + lines * self.caption_lh


@dataclass
class Placed:
    menu: Rect
    side: str
    clamped: bool
    sub: Rect | None = None
    sub2: Rect | None = None
    clipped: int = 0
    covers: list[str] = field(default_factory=list)
    margin: list[str] = field(default_factory=list)


def place_menu(
    vw: int, vh: int, at: tuple[int, int], w: int, h: int, m: int
) -> tuple[Rect, str, bool]:
    """§5.6 rules (1)–(4): below; flip above; shift inside less `space.2`; clamp and scroll."""
    px_, py_ = at
    below, above = vh - m - py_, py_ - m
    clamped = False
    if h <= below:
        y, side = py_, "below"
    elif h <= above:
        y, side = py_ - h, "above (flipped)"
    else:
        y, h, side, clamped = m, vh - 2 * m, "clamped, scrolls", True
    x = px_
    if x + w > vw - m:
        x, side = vw - m - w, f"{side}, shifted left"
    if x < m:
        x, side = m, f"{side}, shifted right"
    return Rect(x, y, w, h), side, clamped


def place_sub(
    vw: int,
    vh: int,
    parent: Rect,
    item: Rect,
    size: tuple[int, int, int],
    m: int,
    ancestors: list[Rect],
) -> Rect:
    """§5.6 rule (5): right of the parent item, its first row level with the item; flip left
    when the right is short (outside the viewport less `space.2`, or over an open ancestor)."""
    w, h, lead = size
    y = item.y - lead
    right = Rect(parent.x + parent.w, y, w, h)
    if right.x + w <= vw - m and not any(right.meets(a) for a in ancestors):
        r = right
    else:
        r = Rect(parent.x - w, y, w, h)
    if r.y + h > vh - m:
        r = Rect(r.x, vh - m - h, w, h)
    if r.y < m:
        r = Rect(r.x, m, w, h)
    return r


def item_rects(box: Box, at: Rect, visible: int | None = None) -> list[Rect]:
    out: list[Rect] = []
    y = at.y + box.edge + box.pad
    shown = 0
    for r in box.rows:
        if r == "—":
            y += box.sep
            continue
        if visible is not None and shown >= visible:
            break  # the clamped menu scrolls: later rows are reachable, never clipped
        out.append(Rect(at.x + box.edge, y, box.w - 2 * box.edge, box.row))
        y += box.row
        shown += 1
    return out


def menu_seconds(spec: str) -> dict[str, list[str]]:
    """The main menu's possible second lines by item: §5.5's sentences, except Move to ▸'s."""
    out: dict[str, list[str]] = {}
    for r in table_rows(section(spec, "5.5 Static predicates")):
        if len(r) >= 4 and not r[0].startswith("Move to") and quotes(r[3]):
            out[r[0]] = quotes(r[3])
    return out


def flat(seconds: dict[str, list[str]]) -> list[str]:
    return [s for v in seconds.values() for s in v]


def t2_strings(spec: str, control: str) -> list[str]:
    """The quoted strings of the §8.1 row whose Control names `control`."""
    for r in table_rows(section(spec, "8.1 T2 rows")):
        if len(r) >= 5 and control in r[2]:
            return quotes(r[4])
    return []


def geometry(
    t: dict[str, object], spec: str
) -> tuple[dict[str, str], dict[str, object], list[str]]:
    """Menu measures, the four-corner, 1920 and 200 % rectangles (§5.6) and their FAILs."""
    groups = menu_groups(spec)
    browser_groups = [[i for i in g if i.label != "Pop out"] for g in groups]
    seconds = menu_seconds(spec)
    outcomes = t2_strings(spec, "Move to ▸ outcomes")
    vals: dict[str, str] = {}
    extra: dict[str, object] = {}
    bad: list[str] = []
    for dens in DENSITY:
        mm = MenuMetrics(t, dens)
        box = mm.box(groups, seconds)
        sfx = "" if dens == "compact" else ".comfortable"
        vals[f"BUDGET:menu.w{sfx}"] = f"{box.w} px"
        vals[f"BUDGET:menu.row.{dens}"] = f"{mm.row} px"
        vals[f"BUDGET:menu.row2.{dens}"] = f"{mm.row + mm.caption_lh} px"
        vals[f"BUDGET:menu.footnote.h{sfx}"] = f"{mm.footnote_h(box.w)} px"
    mm = MenuMetrics(t, "compact")
    menu = mm.box(groups, seconds)
    bmenu = mm.box(browser_groups, seconds)
    bmenu.extra = mm.sep + mm.footnote_h(bmenu.w)
    scroll_h = mm.caption_lh + 2 * px(t, "space.1")
    lead = mm.edge + mm.pad
    vals["BUDGET:menu.sep"] = f"{mm.sep} px"
    vals["BUDGET:kbd.h"] = f"{mm.kbd_h} px"
    vals["BUDGET:menu.scroll.h"] = f"{scroll_h} px"
    vals["BUDGET:menu.h.desktop"] = f"{menu.h} px"
    vals["BUDGET:menu.h.browser"] = f"{bmenu.h} px"
    all_panels = [Item(f"{p} ▸", "", True) for p in DENSE_PANELS]
    sub_w = mm.width(all_panels, {}, glyph=False)
    vals["BUDGET:menu.sub.w"] = f"{sub_w} px"
    sub2 = mm.box([[Item(o) for o in PLACE_OUTCOMES]], {PLACE_OUTCOMES[0]: outcomes}, glyph=False)
    m, pin = px(t, "space.2"), px(t, POINTER_TOKEN)
    vals["BUDGET:corner.pointer-inset"] = f"{pin} px"
    for key, (state, (vw, vh)) in CORNERS.items():
        c = key.split(".")[0]
        at = (pin if c[1] == "l" else vw - pin, pin if c[0] == "t" else vh - pin)
        rect, side, clamped = place_menu(vw, vh, at, menu.w, menu.h, m)
        own = CORNER_PANEL[c]
        sub = Box(
            [f"{p} ▸" for i, p in enumerate(DENSE_PANELS) if i != own],
            sub_w,
            mm.row,
            mm.sep,
            mm.pad,
            mm.edge,
        )
        move = Rect(
            rect.x + mm.edge, rect.y + menu.item_y("Move to ▸"), menu.w - 2 * mm.edge, mm.row
        )
        srect = place_sub(vw, vh, rect, move, (sub.w, sub.h, lead), m, [rect])
        first = Rect(srect.x + mm.edge, srect.y + lead, sub.w - 2 * mm.edge, mm.row)
        s2rect = place_sub(vw, vh, srect, first, (sub2.w, sub2.h, lead), m, [rect, srect])
        rows = item_rects(menu, rect) + item_rects(sub, srect) + item_rects(sub2, s2rect)
        clipped = sum(not r.inside(vw, vh) for r in rows)
        vals[f"BUDGET:corner.{key}.menu"] = rect.text()
        vals[f"BUDGET:corner.{key}.side"] = side
        vals[f"BUDGET:corner.{key}.sub"] = srect.text()
        vals[f"BUDGET:corner.{key}.sub2"] = s2rect.text()
        vals[f"COUNT:corner.{key}.clipped"] = str(clipped)
        tag = f"[G-GEOM] §5.6 `{state}`"
        if clipped or clamped:
            bad.append(f"{tag}: {clipped} clipped item(s), clamped={clamped} (AC4; RULED BQ-14)")
        if srect.meets(move):
            bad.append(f"{tag}: Move to ▸'s submenu covers its parent item (D-15)")
        if s2rect.meets(first):
            bad.append(f"{tag}: the outcomes submenu covers its parent item (D-15)")
        if not all(r.inside(vw, vh, m) for r in (rect, srect, s2rect)):
            bad.append(f"{tag}: a level leaves the viewport less `space.2` (D-15)")
        extra[f"corner.{key}"] = {
            "pointer": at,
            "menu": rect.text(),
            "sub": srect.text(),
            "sub2": s2rect.text(),
            "side": side,
        }
    vw, vh = 1280 // ZOOM, 800 // ZOOM
    rect, side, clamped = place_menu(vw, vh, (pin, pin), bmenu.w, bmenu.h, m)
    visible = (rect.h - 2 * lead - 2 * scroll_h) // mm.row if clamped else None
    rows = item_rects(bmenu, rect, visible)
    # AC4 at 200 %: Move to ▸ and the first panel's outcomes open from the clamped menu at
    # scroll 0 (the item is in view), so the flip and shift at the 640 px CSS width are gated
    own = CORNER_PANEL["tl"]
    sub = Box(
        [f"{p} ▸" for i, p in enumerate(DENSE_PANELS) if i != own],
        sub_w,
        mm.row,
        mm.sep,
        mm.pad,
        mm.edge,
    )
    move = Rect(rect.x + mm.edge, rect.y + bmenu.item_y("Move to ▸"), bmenu.w - 2 * mm.edge, mm.row)
    srect = place_sub(vw, vh, rect, move, (sub.w, sub.h, lead), m, [rect])
    first = Rect(srect.x + mm.edge, srect.y + lead, sub.w - 2 * mm.edge, mm.row)
    s2rect = place_sub(vw, vh, srect, first, (sub2.w, sub2.h, lead), m, [rect, srect])
    rows += item_rects(sub, srect) + item_rects(sub2, s2rect)
    clipped = sum(not r.inside(vw, vh) for r in rows) + (
        1 if visible is not None and visible < 1 else 0
    )
    in_view = visible is None or move.y + move.h <= rect.y + rect.h - lead - scroll_h
    vals["BUDGET:clamp.css-viewport"] = f"{vw}×{vh}"
    vals["BUDGET:clamp.menu"] = rect.text()
    vals["BUDGET:clamp.side"] = side
    vals["BUDGET:clamp.sub"] = srect.text()
    vals["BUDGET:clamp.sub2"] = s2rect.text()
    vals["BUDGET:clamp.sub.side"] = "right" if srect.x >= rect.x + rect.w else "left (flipped)"
    vals["BUDGET:clamp.sub2.side"] = "right" if s2rect.x >= srect.x + srect.w else "left (flipped)"
    vals["COUNT:clamp.clipped"] = str(clipped)
    extra["clamp"] = {
        "clamped": clamped,
        "visible_rows": visible,
        "content_h": bmenu.h,
        "sub": srect.text(),
        "sub2": s2rect.text(),
    }
    tag = "[G-GEOM] §5.6 `clamped-200`"
    if clipped:
        bad.append(f"{tag}: {clipped} clipped item(s) (AC4)")
    if not in_view:
        bad.append(f"{tag}: Move to ▸ is not in view at scroll 0 (AC4)")
    if srect.meets(move):
        bad.append(f"{tag}: Move to ▸'s submenu covers its parent item (D-15)")
    if s2rect.meets(first):
        bad.append(f"{tag}: the outcomes submenu covers its parent item (D-15)")
    if not all(r.inside(vw, vh, m) for r in (rect, srect, s2rect)):
        bad.append(f"{tag}: a level leaves the viewport less `space.2` (D-15)")
    return vals, extra, bad


def picker(t: dict[str, object], spec: str, d02: str) -> tuple[dict[str, str], list[str]]:
    """SCR-024's measures from the tokens and `D02`:494's dialog sizes."""
    vals: dict[str, str] = {}
    bad: list[str] = []
    s59 = section(d02, "5.9 SCR-024")
    m = re.search(r"(\d+)×(\d+) at 1920×1080 and (\d+)×(\d+) at 1280×800", s59)
    if m is None:
        raise SystemExit("FAIL parse: `D02`:494's dialog sizes")
    w1920, h1920, w1280, h1280 = (int(x) for x in m.groups())
    vals["BUDGET:picker.dialog.1920"] = f"{w1920}×{h1920}"
    vals["BUDGET:picker.dialog.1280"] = f"{w1280}×{h1280}"
    pad = px(t, "space.dialog.padding")
    content = w1280 - 2 * pad
    vals["BUDGET:picker.content-w.1280"] = f"{content} px"
    chips = grab(r"toggle chips — ([^—]+?) —", section(spec, "4.2 The category filter"), "§4.2")
    inset, gap1 = px(t, "space.inset.sm"), px(t, "space.1")
    semibold = px(t, "font.weight.semibold")
    names = chips.split(" · ")
    filt = sum(2 * inset + style_w(t, "type.ui.label", n, semibold) for n in names)
    filt += (len(names) - 1) * gap1
    vals["BUDGET:picker.filter-w.1280"] = f"{filt} px"
    if filt > content:
        bad.append(f"[G-FIT] §4.2: the filter row ({filt}) exceeds the content width ({content})")
    lines = line_h(t, "type.ui.body-strong") + line_h(t, "type.ui.caption")
    thumb_w = round(lines * THUMB_RATIO)
    vals["BUDGET:entry.thumb.w"] = str(thumb_w)
    vals["BUDGET:entry.thumb.h"] = str(lines)
    entry: dict[str, int] = {}
    for dens, d in DENSITY.items():
        sfx = "" if dens == "compact" else ".comfortable"
        entry[dens] = 2 * px(t, d["inset"]) + lines
        vals[f"BUDGET:entry.h{sfx}"] = f"{entry[dens]} px"
        heading = line_h(t, "type.ui.heading-sm") + px(t, d["stack"])
        vals[f"BUDGET:picker.heading.h{sfx}"] = f"{heading} px"
        vals[f"BUDGET:picker.filter-chip.h{sfx}"] = f"{px(t, d['control'])} px"
    gap2, icon = px(t, "space.2"), px(t, "size.icon.md")
    column = content - 2 * inset - thumb_w - gap2 - icon - gap2
    descs = [r[5] for r in inventory_rows(spec) if r[0].isdigit()]
    longest = max((style_w(t, "type.ui.caption", s) for s in descs), default=0)
    vals["BUDGET:picker.desc-fit.1280"] = f"{longest} of {column} px"
    if longest > column:
        bad.append(f"[G-FIT] §3.1: the longest description ({longest}) exceeds one line ({column})")
    vals["BUDGET:chip.h"] = f"{line_h(t, 'type.ui.caption') + 2 * px(t, 'border.hairline')} px"
    mini_h = px(t, MINIMAP_TOKEN)
    vals["BUDGET:picker.minimap"] = f"{round(mini_h * 1280 / 800)}×{mini_h}"
    vals["BUDGET:picker.fullscreen-below"] = str(w1280 + 2 * px(t, "space.4"))
    title = px(t, "size.control.comfortable")
    field_h = px(t, "size.control.compact")
    list_h = h1920 - 2 * pad - title - 2 * field_h - mini_h - 4 * px(t, "space.stack.md")
    threshold = VIRTUALISE_SCREENS * (list_h // entry["compact"])
    vals["BUDGET:picker.virtualise-above"] = str(threshold)
    offered = sum(r[0].isdigit() for r in inventory_rows(spec))
    if not offered <= threshold <= LIST_CEILING:
        bad.append(f"[G-FIT] D-2: virtualise above {threshold}; R1 has {offered} (≤ 1 000)")
    return vals, bad


def budgets_from_base(p14: str, p15: str) -> dict[str, str]:
    scr28 = section(p14, "SCR-028")
    scr24 = section(p14, "SCR-024")
    cmp48 = section(p15, "CMP-048")
    return {
        "BUDGET:perf.menu-open-ms": grab(r"Menu opens in <=(\d+) ms", scr28, "`14` SCR-028"),
        "BUDGET:perf.panel-mount-ms": grab(r"Panel mounts <=(\d+) ms", scr24, "`14` SCR-024"),
        "BUDGET:announce.throttle-ms": grab(
            r"once per settled query, (\d+) ms after", cmp48, "`15` CMP-048"
        ),
    }


# ---------------------------------------------------------------------------- the spec's tables


def inventory_rows(spec: str) -> list[list[str]]:
    return table_rows(section(spec, "3.1 The inventory"))


@dataclass
class Frame:
    line: str
    name: str
    surface: str
    state: str
    width: str
    theme: str
    cells: list[str]

    @property
    def tag(self) -> str:
        return f"§6.2 `{self.name}`"

    def cell(self, col: str) -> str:
        return self.cells[REG_COLS.index(col)] if len(self.cells) == len(REG_COLS) else ""


REG_COLS = (
    "Frame",
    "Board",
    "Order",
    "T2",
    "Sentence",
    "Exits",
    "Last",
    "Footnote",
    "Kbd",
    "Geometry",
    "Picker",
)


def register(spec: str) -> list[Frame]:
    out: list[Frame] = []
    block = section(spec, "6.2 The frame register")
    lines = [
        ln for ln in block.splitlines() if ln.startswith("| `") and not re.match(r"^\|\s*-{3}", ln)
    ]
    for ln in lines:
        cells = split_row(ln)
        name = cells[0].strip("`")
        parts = name.split(" · ")
        surface, _, state = parts[0].partition("/")
        width = next((p for p in parts[1:-1] if p.isdigit()), "")
        width = width or ("1920" if state.endswith("-1920") else "1280")
        out.append(Frame(ln, name, surface, state, width, parts[-1], cells))
    return out


def board_rows(spec: str) -> dict[str, str]:
    """§0's boards: number → its Draws cell."""
    out: dict[str, str] = {}
    for r in table_rows(section(spec, "0. Artefacts")):
        if r and re.fullmatch(r"\d{2}", r[0]) and len(r) >= 3:
            out[r[0]] = r[2]
    return out


def matrix_states(spec: str, frames: list[Frame]) -> dict[str, list[str]]:
    """§6.1's states per surface, `corner-*` (N) expanded from the register's corner frames."""
    out: dict[str, list[str]] = {}
    for r in table_rows(section(spec, "6.1 The matrix")):
        if len(r) < 2:
            continue
        states: list[str] = []
        for m in re.finditer(r"`([a-z0-9*-]+)`(?: \((\d+)\))?", r[1]):
            if m[1].endswith("*"):
                found = sorted(
                    {f.state for f in frames if f.surface == r[0] and f.state.startswith(m[1][:-1])}
                )
                states += found if len(found) == int(m[2] or 0) else [f"{m[1]}?{len(found)}"]
            else:
                states.append(m[1])
        out[r[0]] = states
    return out


def fixed_viewport(state: str) -> bool:
    return state.startswith("corner-") or state == "clamped-200"


def counts(spec: str, d02: str, frames: list[Frame]) -> dict[str, str]:
    inv = inventory_rows(spec)
    offered = [r for r in inv if r[0].isdigit()]
    groups = menu_groups(spec)
    vals = {
        "COUNT:inventory.offered": str(len(offered)),
        "COUNT:inventory.desc-max-chars": str(max((len(r[5]) for r in offered), default=0)),
        "COUNT:menu.groups": str(len(groups)),
        "COUNT:menu.items.desktop": str(sum(len(g) for g in groups)),
        "COUNT:menu.items.browser": str(sum(1 for g in groups for i in g if i.label != "Pop out")),
    }
    sentence_keys = {
        "flag.panel_off": "flag-off",
        "layout.panel.no_settings": "no-settings",
        "layout.panel.at_defaults": "at-defaults",
    }
    for r in table_rows(section(spec, "8.2 Sentence-form rows")):
        if len(r) < 5:
            continue
        key = re.search(r"`([a-z_.]+)`", r[4])
        name = sentence_keys.get(key[1], key[1]) if key else "one-panel"
        said = quotes(r[3])
        vals[f"COUNT:reason.{name}.chars"] = str(len(said[0]) if said else 0)
    deck = {r[0]: r for r in table_rows(section(spec, "9. Copy deck")) if r}
    k15 = quotes(deck.get("K-15", ["", "", ""])[2])
    vals["COUNT:reason.recording-short.chars"] = str(len(k15[0]) if k15 else 0)
    d02_row = re.search(r"^\| `recording\.symbol_not_recorded` +\| \"([^\"]+)\"", d02, MULTI)
    vals["COUNT:reason.recording-d02.chars"] = str(len(d02_row[1]) if d02_row else 0)
    menu_texts = flat(menu_seconds(spec)) + t2_strings(spec, "Move to ▸ outcomes")
    menu_texts += t2_strings(spec, "Duplicate")
    vals["COUNT:reason.menu-max.chars"] = str(max((len(s) for s in menu_texts), default=0))
    states = matrix_states(spec, frames)
    total = sum(
        2 * (1 if fixed_viewport(s) else 2) for ss in states.values() for s in ss if "?" not in s
    )
    vals["COUNT:frames.drawn"] = str(len(frames))
    vals["COUNT:frames.on-request"] = str(total - len({f.name for f in frames}))
    vals["COUNT:boards"] = str(len({f.cell("Board") for f in frames}))
    vals["COUNT:boards.light-twins"] = str(
        len({f.cell("Board") for f in frames if f.theme == "light"})
    )
    return vals


# ---------------------------------------------------------------------------- contrast and CVD


def token_list(cell: str) -> list[str]:
    return re.findall(r"`([a-z0-9.-]+)`", cell)


def contrast_rows(
    spec: str, themes: dict[str, dict[str, object]]
) -> tuple[dict[str, str], list[dict[str, object]], list[str]]:
    vals: dict[str, str] = {}
    matrix: list[dict[str, object]] = []
    bad: list[str] = []
    rows = table_rows(section(spec, "11.2 Contrast"))
    if not rows:
        bad.append("[G-CONTRAST] §11.2 has no contrast table")
    for cells in rows:
        if len(cells) < 9:
            bad.append(f"[G-CONTRAST] §11.2 row unparsable: {cells[:1]}")
            continue
        row = cells[0].strip("`")
        fg, bg = token_list(cells[2]), token_list(cells[3])
        bar = None if cells[4].startswith("n/a") else float(cells[4])
        entry: dict[str, object] = {"row": row, "fg": fg, "bg": bg, "bar": bar}
        ok = True
        for th, tok in themes.items():
            a = resolve(tok, fg[0]) if fg else "MISSING"
            b = resolve(tok, bg[0]) if bg else "MISSING"
            if "MISSING" in (a, b):
                bad.append(f"[G-CONTRAST] §11.2 {row}: a token is missing in {th}")
                ok = False
                continue
            r = contrast(a, b)
            vals[f"CR:{row}:{th}"] = show_ratio(r)
            entry[th] = round(r, 4)
            ok = ok and (bar is None or r >= bar)
        if f"CR:{row}:verdict" in cells[8]:
            verdict = "PASS" if ok else "FAIL"
            vals[f"CR:{row}:verdict"] = verdict
            entry["verdict"] = verdict
            if not ok:
                bad.append(f"[G-CONTRAST] §11.2 {row}: below its {bar} bar (a design finding)")
        else:
            entry["verdict"] = cells[8]
        matrix.append(entry)
    return vals, matrix, bad


def cvd_values(dark: dict[str, object]) -> dict[str, str]:
    out: dict[str, str] = {}
    for pair, (a, b) in CVD_PAIRS.items():
        des = [delta_e(resolve(dark, a), resolve(dark, b), sim) for sim in MACHADO]
        out[f"CR:cvd.{pair}.min-de"] = f"{min(des):.1f}"
    return out


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
        for m in PLACEHOLDER.finditer(CODE.sub("", line)):
            bad.append(f"[G-ANCHOR] {name}:{i}: placeholder {{{{{m[1]}}}}} not filled")
        for m in ANCHOR.finditer(line):
            key = m[1]
            seen.add(key)
            want = values.get(key)
            if want is None:
                bad.append(f"[G-ANCHOR] {name}:{i}: anchor {key} is not a value the tool computes")
                continue
            before = line[: m.start()]
            lead = before[: len(before) - len(want)]
            if not before.endswith(want) or (lead and lead[-1] not in BOUNDARY):
                got = re.split(r"[ |*(]", before)[-1] if before else ""
                bad.append(
                    f"[G-ANCHOR] {name}:{i}: {key} reads {got!r}; the tool computes {want!r}"
                )
    for key in sorted(required - seen):
        bad.append(f"[G-ANCHOR] {name}: no anchored value for {key}")
    return bad


# ---------------------------------------------------------------------------- cites


def cite_path(cid: str) -> str | None:
    if re.fullmatch(r"\d{2}", cid):
        listing = git_show(BASE, "docs/plan/")
        names = (
            [] if listing is None else [n for n in listing.split("\n") if n.startswith(cid + "-")]
        )
        return f"docs/plan/{min(names)}" if names else None
    if cid == "D02":
        return D02_REL
    m = re.fullmatch(r"(E\d{2})-D\d{2}(?:\.md)?", cid)
    if m:
        return f"docs/design/{m[1]}/{cid.removesuffix('.md')}.md"
    if cid == "BrowserShellAdapter.ts":
        return ADAPTER_REL
    if "/" in cid or cid.endswith(".md"):
        return cid
    return None


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
        tag = f"[G-CITE] {name}: `{cid}`:{n}"
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
        refs = [m["first"], *re.findall(r":(\d+(?:[–-]\d+)?)", m["more"])]
        for ref in refs:
            for part in re.split(r"[–-]", ref):
                one(m["id"], int(part), "")
    return fails, warns, len(done)


# ---------------------------------------------------------------------------- frame gates (A2)


def lawful_keys(d02: str) -> set[str]:
    """Merged E15-D02 §8.1's keys at the base, plus the ruled `rbac.owner_only` (condition 1)."""
    s81 = section(d02, "8.1 Gated controls")
    keys = set(re.findall(r"`((?:rbac|layout|workspace|scale|recording|notice)\.[a-z_.]+)`", s81))
    return keys | RULED_T2_EXTRA


def d02_categories(d02: str) -> list[str]:
    heads = grab(r"categories as real headings: (.+?)\. Each entry", d02, "`D02`:494 headings")
    parts, depth, cur = [], 0, ""
    for ch in heads + ";":
        depth += (ch == "(") - (ch == ")")
        if ch == ";" and depth == 0:
            parts.append(cur.split(" (")[0].strip())
            cur = ""
        else:
            cur += ch
    return parts


T2_ITEM = re.compile(r"(?P<label>.+?): (?P<lock>lock · )?`(?P<key>[a-z_.]+)`")


def t2_items(cell: str) -> tuple[list[str], str | None]:
    """(the items outside the inset, the inset's item or None)."""
    inset = re.search(r"\s*\(inset: (.+)\)$", cell)
    main = cell[: inset.start()].strip() if inset else cell.strip()
    items = [] if main in ("", "—") else [x.strip() for x in main.split("; ")]
    return items, inset[1] if inset else None


def menu_order_gates(frames: list[Frame], groups: list[list[Item]]) -> list[str]:
    bad: list[str] = []
    desk, brow = order_text(groups, False), order_text(groups, True)
    trio = ("menu-chart", "menu-dom", "menu-positions")
    for theme in sorted({f.theme for f in frames}):
        cells = [f.cell("Order") for f in frames if f.state in trio and f.theme == theme]
        if cells and (len(set(cells)) > 1 or cells[0] != desk or len(cells) != len(trio)):
            bad.append(
                f"[G-ORDER] §6.2 {theme}: the chart, DOM and positions Order cells are not "
                "byte-identical to §5.1 (AC2; RULED BQ-8)"
            )
    for f in frames:
        order = f.cell("Order")
        if f.surface == "SCR-024":
            if order != "—":
                bad.append(f"[G-ORDER] {f.tag}: a picker frame carries a menu order")
            continue
        if f.state in trio:
            continue
        rest = CONDITIONAL.sub("", order, count=1)
        browser = f.state in BROWSER_STATES
        if rest == (brow if browser else desk):
            continue
        if browser and "Pop out" in rest:
            bad.append(f"[G-ABSENCE] {f.tag}: Pop out drawn in the browser (condition 2: absent)")
        else:
            bad.append(f"[G-ORDER] {f.tag}: the Order differs from §5.1's fixed set (D-9)")
    return bad


def t2_gates(frames: list[Frame], lawful: set[str]) -> list[str]:
    bad: list[str] = []
    for f in frames:
        items, inset = t2_items(f.cell("T2"))
        anatomy: list[str] = []
        for it in items + ([inset] if inset else []):
            m = T2_ITEM.fullmatch(it)
            if m is None or not m["lock"]:
                anatomy.append(it[:40])
                continue
            label = m["label"].split(" (")[0]
            if m["key"] not in lawful:
                bad.append(
                    f"[G-T2-KEY] {f.tag}: a lock on `{m['key']}`, a key not in merged E15-D02 "
                    "§8.1 (condition 1)"
                )
            if label in EXIT_LABELS:
                bad.append(f"[G-EXIT-GATED] {f.tag}: {label} drawn T2 (condition 4)")
            elif m["key"] in lawful and it != inset and f.state not in VIEWER_STATES:
                bad += t2_pair(f, m["label"], m["key"])
        if anatomy:
            bad.append(f"[G-T2-ANATOMY] {f.tag}: T2 without the lock and a key: {anatomy} (§1.4)")
        want = VIEWER_STATES.get(f.state)
        if want is not None and (items or inset != f"Save: lock · `{want}`"):
            bad.append(
                f"[G-VIEWER] {f.tag}: a menu item gated, or the inset is not Save with `{want}` "
                "(RULED BQ-12)"
            )
        elif want is None and inset is not None:
            bad.append(f"[G-VIEWER] {f.tag}: a Save inset on a frame that is not viewer / view-as")
    return bad


def t2_pair(f: Frame, labels: str, key: str) -> list[str]:
    """G-T2-PAIR: a lawful key on an item that may not carry it (row by row, item by item)."""
    bad: list[str] = []
    for one in labels.split(", "):
        label = one.split(" (")[0].strip()
        outcome = label.startswith(PLACE_OUTCOMES)
        if outcome:
            ok = key in LIMIT_OUTCOME_KEYS
        elif f.surface == "SCR-028":
            ok = key in MENU_T2_PAIRS.get(label, set())
        else:
            ok = key in PICKER_T2_PAIRS.get(label, set())
        if not ok:
            bad.append(
                f"[G-T2-PAIR] {f.tag}: {label} drawn T2 on `{key}`; §5.5 / §4.4 pair no such "
                "item and key (RULED BQ-6 / BQ-11 / BQ-12)"
            )
    return bad


def focus_gates(frames: list[Frame]) -> list[str]:
    """G-FOCUS: the menu opens on the first item that is neither T2 nor sentence-form (AC6)."""
    bad: list[str] = []
    for f in frames:
        if f.surface != "SCR-028":
            continue
        m = FOCUS_CLAUSE.search(f.cell("Kbd"))
        if m is None:
            if f.state in FOCUS_STATES:
                bad.append(f"[G-FOCUS] {f.tag}: the opening focus is not named (AC6; D-17)")
            continue
        blocked: set[str] = set()
        for col in ("T2", "Sentence"):
            items, _inset = t2_items(f.cell(col))
            for it in items:
                head = it.split(": ")[0]
                blocked |= {x.split(" (")[0].strip() for x in head.split(", ")}
        order = [x for g in f.cell("Order").split(" / ") for x in g.split(" · ")]
        want = next((x for x in order if x not in blocked), None)
        if m["item"].strip() != want:
            bad.append(
                f"[G-FOCUS] {f.tag}: focus opens on {m['item'].strip()!r}, not the first item "
                f"that is neither T2 nor sentence-form ({want!r}; AC6; D-17)"
            )
    return bad


def sentence_gates(frames: list[Frame]) -> list[str]:
    bad: list[str] = []
    for f in frames:
        cell = f.cell("Sentence")
        for it in [] if cell in ("", "—") else cell.split("; "):
            label = it.split(":")[0].split(" (")[0].strip()
            if "lock" in it:
                bad.append(f"[G-SENTENCE] {f.tag}: a lock on a sentence-form item (§1.6)")
            if label in EXIT_LABELS:
                bad.append(f"[G-EXIT-GATED] {f.tag}: {label} drawn with a sentence (condition 4)")
    return bad


def exit_gates(frames: list[Frame]) -> list[str]:
    bad: list[str] = []
    for f in frames:
        cell = f.cell("Exits")
        if f.surface == "SCR-024":
            ok = cell == PICKER_EXITS
        else:
            undo = f.cell("Order").startswith("Undo move")
            ok = MENU_EXITS.fullmatch(cell) is not None and cell.startswith("Undo move") == undo
        if not ok:
            bad.append(f"[G-EXITS] {f.tag}: the exits are not all present and T1 (condition 4)")
    return bad


def last_gates(frames: list[Frame]) -> list[str]:
    bad: list[str] = []
    for f in frames:
        cell, order = f.cell("Last"), f.cell("Order")
        if f.surface == "SCR-024":
            ok = cell == "—"
        else:
            ok = cell.startswith(LAST_CELL) and order.split(" / ")[-1] == DESTRUCTIVE_GROUP
        if not ok:
            bad.append(f"[G-LAST] {f.tag}: not a rule, then Reset settings…, then Close (BQ-10)")
    return bad


def footnote_gates(frames: list[Frame]) -> list[str]:
    bad: list[str] = []
    for f in frames:
        cell = f.cell("Footnote")
        if f.state in BROWSER_STATES and f.surface == "SCR-028":
            miss = []
            if f'"{SHIPPED_FOOTNOTE}"' not in cell:
                miss.append("the shipped sentence (RULED BQ-9)")
            if f'"{PROPOSED_FOOTNOTE}" PROPOSED' not in cell:
                miss.append("the second sentence drawn PROPOSED (condition 2)")
            if miss:
                bad.append(f"[G-FOOTNOTE] {f.tag}: missing {'; '.join(miss)}")
        elif cell != "—":
            bad.append(f"[G-FOOTNOTE] {f.tag}: a footnote outside the browser build")
    return bad


def kbd_gates(frames: list[Frame]) -> list[str]:
    bad: list[str] = []
    for f in frames:
        cell = f.cell("Kbd")
        if f.surface == "SCR-024":
            if cell != "—":
                bad.append(f"[G-KBD] {f.tag}: a Kbd hint on a picker frame")
            continue
        miss: list[str] = []
        if "Maximise `F11`" not in cell:
            miss.append("Maximise `F11`")
        for part in cell.split("; "):
            for m in CHORD.finditer(part):
                if "PROPOSED" not in part[m.end() :]:
                    miss.append(f"PROPOSED after `{m[1]}`")
        pop = "Pop out `Ctrl+Shift+O`" in cell
        if pop == (f.state in BROWSER_STATES):
            miss.append("Pop out's chord exactly on the desktop frames")
        if f.state == "sync-submenu" and not all(c in cell for c in SYNC_CHORDS):
            miss.append("the sync chords")
        if miss:
            bad.append(f"[G-KBD] {f.tag}: {', '.join(miss)} (RULED BQ-15)")
    return bad


def sync_gates(frames: list[Frame]) -> list[str]:
    return [
        f"[G-SYNC] {f.tag}: a sync colour drawn here; E15-D06 owns it (RULED BQ-13)"
        for f in frames
        if "color.sync." in f.line
    ]


def geometry_row_gates(frames: list[Frame], extra: dict[str, object]) -> list[str]:
    bad: list[str] = []
    for f in frames:
        cell = f.cell("Geometry")
        overflow = f.state.startswith("corner-") or f.state == "clamped-200"
        if not overflow:
            if cell != "—":
                bad.append(f"[G-GEOM-ROW] {f.tag}: a geometry claim on a non-overflow frame")
            continue
        m = re.match(r"clipped (\d+)(?:<!--=COUNT:([^>]+)-->)?", cell)
        problems: list[str] = []
        if m is None or m[1] != "0":
            problems.append(f"clipped {m[1] if m else '?'}, not 0")
        if f.state == "clamped-200":
            clamp = extra.get("clamp")
            if "▲ / ▼ shown" not in cell or not (isinstance(clamp, dict) and clamp["clamped"]):
                problems.append("the clamped menu with ▲ / ▼")
        if problems:
            bad.append(f"[G-GEOM-ROW] {f.tag}: {'; '.join(problems)} (AC4; RULED BQ-14)")
    return bad


def picker_gates(frames: list[Frame], cats: list[str]) -> list[str]:
    bad: list[str] = []
    heads = "headings " + " · ".join(cats) + " (`h3`)"
    for f in frames:
        cell = f.cell("Picker")
        if f.surface == "SCR-028":
            if cell != "—":
                bad.append(f"[G-PICKER] {f.tag}: a picker claim on a menu frame")
            continue
        miss: list[str] = []
        if f.state == "default" and heads not in cell:
            miss.append("D02's five headings in D02's order (BQ-4)")
        if f.state == "no-results":
            named = "categories named: " + " · ".join(cats) + ";"
            for need in (f"term `{NO_RESULTS_TERM}` kept", named, "[Clear search] [Clear filter]"):
                if need not in cell:
                    miss.append(f"{need!r} (AC3)")
        if f.state.startswith("search") and not re.search(r"term `[^`]+` kept", cell):
            miss.append("the term kept")
        t2, _inset = t2_items(f.cell("T2"))
        sent = [] if f.cell("Sentence") in ("", "—") else f.cell("Sentence").split("; ")
        entries = [x for x in t2 + sent if not x.startswith(PLACE_OUTCOMES)]
        if entries and not re.search(r'reason in name: (?:the banner node )?"[^"]+\."', cell):
            miss.append("the reason in the accessible name (AC1; D-5)")
        if miss:
            bad.append(f"[G-PICKER] {f.tag}: {'; '.join(miss)}")
    return bad


def board_gates(spec: str, frames: list[Frame]) -> list[str]:
    bad: list[str] = []
    boards = board_rows(spec)
    reg = {f.cell("Board") for f in frames}
    twins = {n for n, d in boards.items() if "light twin of" in d}
    if (
        set(boards) != reg
        or len(boards) != BOARDS_RULED
        or len(twins) != TWINS_RULED
        or 3 * len(twins) > len(boards)
    ):
        bad.append(
            f"[G-BOARDS] §0: {len(boards)} boards ({len(twins)} twins) vs the register's "
            f"{len(reg)}; RULED BQ-17: ten, three light twins, at most a third"
        )
    for f in frames:
        draws = boards.get(f.cell("Board"))
        if draws is None:
            continue  # the board-cut gate above reports a missing §0 row once
        twin = re.search(r"light twin of (\d{2})", draws)
        if (f.theme == "light") != bool(twin):
            bad.append(f"[G-BOARDS] {f.tag}: theme {f.theme} on board {f.cell('Board')}")
            continue
        src = boards.get(twin[1], "") if twin else draws
        if not re.search(rf"(?<![\w-]){re.escape(f.state)}(?![\w-])", src):
            bad.append(f"[G-BOARDS] {f.tag}: board {f.cell('Board')} does not draw this state")
    return bad


def matrix_gates(spec: str, frames: list[Frame]) -> list[str]:
    bad: list[str] = []
    states = matrix_states(spec, frames)
    for r in table_rows(section(spec, "6.1 The matrix")):
        if len(r) < 4 or r[0] not in states:
            continue
        mine = [f for f in frames if f.surface == r[0]]
        listed = states[r[0]]
        if any("?" in s for s in listed) or any(f.state not in listed for f in mine):
            bad.append(f"[G-MATRIX] §6.1 {r[0]}: the register names a state §6.1 does not list")
        m = re.match(r"drawn except (.+)$", r[2])
        dark = set(listed) - set(re.findall(r"`([a-z0-9-]+)`", m[1])) if m else set()
        light = set(re.findall(r"`([a-z0-9-]+)`", r[3]))
        if dark != {f.state for f in mine if f.theme == "dark"}:
            bad.append(f"[G-MATRIX] §6.1 {r[0]}: the Dark cell differs from the register")
        if light != {f.state for f in mine if f.theme == "light"}:
            bad.append(f"[G-MATRIX] §6.1 {r[0]}: the Light cell differs from the register")
    if len({f.name for f in frames}) != len(frames):
        bad.append("[G-MATRIX] §6.2: a frame is registered twice")
    return bad


def frame_gates(spec: str, d02: str, extra: dict[str, object]) -> list[str]:
    frames = register(spec)
    if not frames:
        return ["[G-FRAMES] §6.2: no frame register"]
    bad = [f"[G-FRAMES] {f.tag}: {len(f.cells)} cells" for f in frames if len(f.cells) != 11]
    bad += menu_order_gates(frames, menu_groups(spec))
    bad += t2_gates(frames, lawful_keys(d02))
    bad += sentence_gates(frames)
    bad += exit_gates(frames)
    bad += last_gates(frames)
    bad += footnote_gates(frames)
    bad += kbd_gates(frames)
    bad += focus_gates(frames)
    bad += sync_gates(frames)
    bad += geometry_row_gates(frames, extra)
    bad += picker_gates(frames, d02_categories(d02))
    bad += board_gates(spec, frames)
    bad += matrix_gates(spec, frames)
    return bad


# ---------------------------------------------------------------------------- the ruling's gates


def row_starting(block: str, first: str) -> list[str] | None:
    for r in table_rows(block):
        if r and r[0] == first:
            return r
    return None


def ruled_gates(spec: str, hand: str, p14: str, base: dict[str, str]) -> list[str]:
    """One gate per ruled sentence that is not a register row (see MUTATIONS)."""
    bad: list[str] = []
    d02 = base["d02"]
    lawful = lawful_keys(d02)
    # BQ-10 / D-11: Reset settings… confirms, Close never, nothing else
    for r in table_rows(section(spec, "5.2 Items")):
        if len(r) < 4:
            continue
        want = "yes" if r[0] == "Reset settings…" else "no"
        if r[0] == "{Kind} actions":
            continue
        if not r[3].startswith(want):
            bad.append(f"[G-CONFIRM] §5.2 {r[0]}: Confirm reads {r[3]!r}; RULED BQ-10 says {want}")
    # BQ-4 / BQ-8 / BQ-9 / BQ-17: every line naming them carries the owner mark
    for name, text in (("spec", spec), ("hand-off", hand)):
        for n, line in enumerate(text.split("\n"), 1):
            if line.startswith(("| M-", "| R-")):
                continue
            if OWNER_BQS.search(line) and OWNER_MARK not in line:
                bad.append(f"[G-OWNER] {name}:{n}: an owner-level BQ without '{OWNER_MARK}'")
    # BQ-16: the CMP-041 / APG key model, `End` on Close
    keys = table_rows(section(spec, "12.1 Keys"))
    menu_keys = {r[1]: r for r in keys if len(r) >= 4 and r[0] == "menu"}
    home = menu_keys.get("`Home` / `End`")
    if home is None or "`End` lands on Close" not in home[2]:
        bad.append("[G-KEYMODEL] §12.1: `End` must land on Close (RULED BQ-16)")
    # BQ-15: the opener is D04's PROPOSED chord; `F11` the one shipped hint
    km = json.loads(base["km"])
    ids = {c["id"]: c.get("defaultBinding") for c in km["commands"]}
    opener = next((r for r in keys if len(r) >= 4 and r[1].startswith("`Shift+F10`")), None)
    if opener is None or "PROPOSED `workspace.panel_menu`" not in opener[3]:
        bad.append("[G-OPENER] §12.1: `Shift+F10` is D04's PROPOSED `workspace.panel_menu`")
    if "workspace.panel_menu" in ids:
        bad.append("[G-OPENER] `KM` now binds workspace.panel_menu: it is shipped, restate it")
    if ids.get("workspace.fullscreen_panel") != "F11":
        bad.append("[G-OPENER] `KM`: workspace.fullscreen_panel is not `F11` at the base")
    # condition 1: the short sentence is a C-row to E16-D02's owner
    s193 = section(spec, "19.3 Contradictions")
    if not any(
        f'"{SHORT_RECORDING}"' in r[2] and "E16-D02's owner" in r[3]
        for r in table_rows(s193)
        if len(r) >= 4
    ):
        bad.append(f'[G-C4] §19.3: no C-row sends "{SHORT_RECORDING}" to E16-D02\'s owner')
    # condition 1: every new key a PROPOSED A-row, sentence form; §8.1 only lawful keys
    new: set[str] = set()
    for r in table_rows(section(spec, "8.2 Sentence-form rows")):
        new |= set(re.findall(r"`([a-z_]+\.[a-z_.]+)`", r[4] if len(r) > 4 else ""))
    new |= set(re.findall(r"PROPOSED `([a-z_]+\.[a-z_.]+)`", section(spec, "5.5 Static")))
    rows194 = [ln for ln in section(spec, "19.4 Amendments").split("\n") if ln.startswith("| A-")]
    for key in sorted(new - lawful):
        if not any(f"`{key}`" in ln and "sentence form" in ln for ln in rows194):
            bad.append(f"[G-NEWKEY] §19.4: no PROPOSED A-row (sentence form) for `{key}`")
    for r in table_rows(section(spec, "8.1 T2 rows")):
        for key in re.findall(r"`([a-z_]+\.[a-z_.]+)`", r[4] if len(r) > 4 else ""):
            if key not in lawful:
                bad.append(f"[G-T2ROWS] §8.1 {r[0]}: `{key}` is not in merged §8.1 (condition 1)")
    # condition 1: §8.1 carries the recording key: quote it and say PROPOSED there
    said = re.search(r"^\| `recording\.symbol_not_recorded` +\| \"([^\"]+)\"", d02, MULTI)
    cond = next((p for p in spec.split("\n") if p.startswith("**Condition 1 (RULED).**")), "")
    if said is None or f'"{said[1]}"' not in cond or "PROPOSED" not in cond:
        bad.append("[G-RECQUOTE] §1.4: merged §8.1's recording sentence not quoted, PROPOSED")
    # condition 2: the second sentence is a copy CR to E15-S02
    a12 = row_starting(section(spec, "19.4 Amendments"), "A-12")
    if a12 is None or "E15-S02" not in a12[1] or PROPOSED_FOOTNOTE not in a12[2]:
        bad.append("[G-A12] §19.4: no A-12 copy CR to E15-S02 for the second footnote sentence")
    if SHIPPED_FOOTNOTE not in base["adapter"]:
        bad.append("[G-A12] the shipped footnote is not in BrowserShellAdapter.ts at the base")
    # condition 3: the frame-mutation list equals the tool's M-n
    listed = set(re.findall(r"^\| (M-\d+) ", section(spec, "6.3 The frame-mutation"), MULTI))
    tool = {m.mid for m in MUTATIONS if m.mid.startswith("M-")}
    if listed != tool:
        bad.append(f"[G-MLIST] §6.3 lists {sorted(listed ^ tool)} unlike the tool (condition 3)")
    # BQ-3: fourteen entries with synonyms; the five screens not offered as one row
    bad += inventory_gates(spec, base["p22"], d02_categories(d02))
    # BQ-5: a sixth category needs an amendment to SCR-024
    if "a sixth category needs an amendment to SCR-024" not in section(spec, "3.2 The growth"):
        bad.append("[G-GROWTH] §3.2: a sixth category must need an amendment to SCR-024")
    # BQ-2: `14` SCR-024 carries the taxonomy and the growth rule as §3.2's text (A-1, applied)
    bad += taxonomy14_gates(spec, p14, d02)
    # condition 1: a sentence-form row is never `aria-disabled` (§1.6; §8.2 row by row)
    for r in table_rows(section(spec, "8.2 Sentence-form rows")):
        if len(r) >= 7 and r[0].startswith("S-") and r[6] != SENTENCE_ATTRS:
            bad.append(
                f"[G-SENTENCE-ARIA] §8.2 {r[0]}: attributes {r[6]!r}, not {SENTENCE_ATTRS!r} "
                "(condition 1: no `aria-disabled` lock)"
            )
        elif len(r) < 7 and r[0].startswith("S-"):
            bad.append(f"[G-SENTENCE-ARIA] §8.2 {r[0]}: no Attributes cell (condition 1)")
    # the correction and condition 4: merged texts at their merge shas, PENDING by name only
    pinned = next((p for p in spec.split("\n") if p.startswith("**Inputs pinned.**")), "")
    if not re.search(rf"E15-D04 as \*\*merged text\*\* \(merge `{D04_MERGE}`\)", pinned):
        bad.append(f"[G-PINS] E15-D04 is merged text pinned to `{D04_MERGE}` (the correction)")
    if not re.search(rf"E15-D06 as \*\*merged text\*\* \([^)]*merge `{D06_MERGE}`\)", pinned):
        bad.append(f"[G-PINS] E15-D06 is merged text pinned to `{D06_MERGE}` (the correction)")
    for name, text in (("spec", spec), ("hand-off", hand)):
        if re.search(r"`(?:E15-)?D03(?:\.md)?`:\d|E15-D03[^.|\n]{0,60}\b[0-9a-f]{7,40}\b", text):
            bad.append(f"[G-PINS] {name}: E15-D03 pinned (PENDING: by name only; condition 4)")
    # condition 4: RULED cites this comment; no lane as authority; `Esc` never gated
    ruled = re.search(r"^## .*RULED.*$", spec, MULTI)
    if ruled is None or RULING_ID not in ruled[0]:
        bad.append(f"[G-RULED] the RULED heading does not cite issuecomment-{RULING_ID}")
    for name, text in (("spec", spec), ("hand-off", hand)):
        for n, line in enumerate(text.split("\n"), 1):
            if LANE_NAMES.search(line):
                bad.append(f"[G-LANE] {name}:{n}: a lane named as authority (condition 4)")
            if not line.startswith("| M-") and ESC_GATED.search(line):
                bad.append(f"[G-EXIT-TEXT] {name}:{n}: `Esc` drawn as gated (condition 4)")
    # BQ-1: the spec, the hand-off and this tool are the artefacts
    key = next((p for p in spec.split("\n") if p.startswith("**Key.**")), "")
    if f"`{TOOL_REL}`" not in key or "`docs/design/E15/E15-D07-handoff.md`" not in spec:
        bad.append("[G-ARTEFACTS] the Key names the tool and §0 the hand-off (RULED BQ-1)")
    # BQ-2: one `14` pointer line under SCR-024 and one under SCR-028
    for scr in ("SCR-024", "SCR-028"):
        n = section(p14, scr).count("- **Hi-fi (E15-D07):**")
        if n != 1:
            bad.append(f"[G-POINTER14] `14` {scr}: {n} Hi-fi (E15-D07) pointer lines, not 1")
    # BQ-18: the Storybook lists in the hand-off, the CRs to E15-D13
    table_s = section(hand, "Table S")
    for comp in ("CMP-213 FuzzyList", "CMP-216 PanelMenu"):
        if row_starting(table_s, comp) is None:
            bad.append(f"[G-STORYBOOK] hand-off Table S: no {comp} story list (RULED BQ-18)")
    s191 = section(spec, "19.1 Design-system change requests to E15-D13")
    crs = set(re.findall(r"^\| (CR-\d+) ", s191, MULTI))
    if crs != {f"CR-{i}" for i in range(1, 7)}:
        bad.append(f"[G-STORYBOOK] §19.1: the CRs to E15-D13 are {sorted(crs)} (RULED BQ-18)")
    # BQ-4: the taxonomy mapping is a C-row; BQ-8: Float = Pop out; BQ-9: AC2's one exception
    c1 = row_starting(s193, "C-1")
    maps = ("Charting→Charts", "Analysis→Market context", "System→Account")
    if c1 is None or not all(x in " ".join(c1) for x in maps) or OWNER_MARK not in c1[3]:
        bad.append("[G-TAXONOMY] §19.3 C-1: the ticket's taxonomy mapped to D02's (RULED BQ-4)")
    d9 = row_starting(section(spec, "2. Decisions"), "D-9")
    if d9 is None or "Float = Pop out and Full screen = Maximise" not in d9[1]:
        bad.append("[G-FLOAT] D-9: Float = Pop out, Full screen = Maximise (RULED BQ-8)")
    c9 = row_starting(s193, "C-9")
    if c9 is None or "absent with a footnote" not in c9[2] or OWNER_MARK not in c9[3]:
        bad.append("[G-AC2EXC] §19.3 C-9: AC2's one stated exception (RULED BQ-9)")
    # BQ-17: every undrawn cell "specified (drawn on request)"
    if "**Specified (drawn on request)**" not in section(spec, "0. Artefacts"):
        bad.append('[G-UNDRAWN] §0: the undrawn cells are not "specified (drawn on request)"')
    # reasons: one sentence, ≤ 60 characters (G-T2.4)
    texts = [
        q for r in table_rows(section(spec, "8.1 T2 rows")) if len(r) > 4 for q in quotes(r[4])
    ]
    texts += [
        q for r in table_rows(section(spec, "8.2 Sentence")) if len(r) > 3 for q in quotes(r[3])
    ]
    texts += flat(menu_seconds(spec))
    for q in texts:
        if len(q) > 60 or not q.endswith("."):
            bad.append(f"[G-REASON] {q[:40]!r}: {len(q)} characters, one sentence ≤ 60")
    # honesty: every heuristic finding says so
    for r in table_rows(section(spec, "16. Heuristic evaluation")):
        if len(r) >= 2 and not r[1].endswith("(heuristic)"):
            bad.append(f"[G-HONESTY] §16 {r[0]}: a finding not marked (heuristic)")
    return bad


def taxonomy14_gates(spec: str, p14: str, d02: str) -> list[str]:
    """G-TAX14: `14` SCR-024's Type carries A-1 verbatim: the five categories in D02's order,
    §3.2 rule 1's data-to-category mapping, the fixed order, the sixth-category rule and the
    virtualisation threshold (RULED BQ-2: the same text as spec §3.2)."""
    problems: list[str] = []
    a1 = row_starting(section(spec, "19.4 Amendments"), "A-1")
    new = re.search(r'append \(applied\): "(.+)"$', a1[2]) if a1 else None
    if a1 is None or new is None:
        return ["[G-TAX14] §19.4 A-1: no 'append (applied): \"…\"' text (RULED BQ-2)"]
    text = ANCHOR.sub("", new[1])
    rule1 = re.search(
        r"^1\. \*\*Where a new kind lands, decided by its data:\*\* (.+)$", spec, MULTI
    )
    want = {
        "the five categories in order": "Categories, in order: " + " · ".join(d02_categories(d02)),
        "rule 1's mapping": rule1[1].replace("**", "") if rule1 else "§3.2 rule 1",
        "the fixed order": "fixed order",
        "the sixth-category rule": "a sixth category needs an amendment to SCR-024",
        "the threshold": "virtualises above ",
    }
    problems += [f"A-1 lacks {k}" for k, v in want.items() if v not in text]
    type_line = next(
        (ln for ln in section(p14, "SCR-024").split("\n") if ln.startswith("- **Type:**")), ""
    )
    if text not in type_line:
        problems.append("`14` SCR-024 Type does not carry A-1's text verbatim")
    if problems:
        return [f"[G-TAX14] {'; '.join(problems)} (RULED BQ-2)"]
    return []


def inventory_gates(spec: str, p22: str, cats: list[str]) -> list[str]:
    bad: list[str] = []
    at = p22.find("\n    PaneKind:\n")
    enum = re.search(r"enum:\s*\[([^\]]*)\]", p22[at : at + 800]) if at >= 0 else None
    kinds = [k.strip() for k in enum[1].split(",") if k.strip()] if enum else []
    rows = inventory_rows(spec)
    offered = [r for r in rows if r[0].isdigit()]
    if len(offered) != len(kinds) + TICKET_ENTRIES:
        bad.append(
            f"[G-INVENTORY] §3.1: {len(offered)} entries; `22` PaneKind + tickets = "
            f"{len(kinds) + TICKET_ENTRIES} (RULED BQ-3)"
        )
    drawn = [k for r in offered for k in re.findall(r"^`([a-z_]+)`$", r[3])]
    if sorted(drawn) != sorted(kinds):
        bad.append("[G-INVENTORY] §3.1: the PaneKind column is not `22`'s twelve values once each")
    last = -1
    for r in offered:
        if len(r) < 10 or r[9] in ("", "—"):
            bad.append(f"[G-INVENTORY] §3.1 #{r[0]}: no search synonyms (RULED BQ-3)")
        idx = cats.index(r[1]) if len(r) > 1 and r[1] in cats else -2
        if idx < last:
            bad.append(f"[G-INVENTORY] §3.1 #{r[0]}: category {r[1]!r} out of D02's order")
        last = max(last, idx)
    other = [r for r in rows if r and r[0] == "—"]
    if len(other) != 1 or len(re.findall(r"SCR-\d{3}", other[0][2])) != NOT_OFFERED_RULED:
        bad.append("[G-INVENTORY] §3.1: the five screens not offered are not one row (RULED BQ-3)")
    return bad


# ---------------------------------------------------------------------------- strings and tokens


def string_gates(name: str, text: str) -> list[str]:
    bad: list[str] = []
    names = all_token_names()
    for line in text.split("\n"):
        quoted = re.match(r"\| (?:CR|C|A)-[\d.]+ ", line) or re.search(
            r"absent|catalogue|does not exist", line
        )
        for tok in sorted(set(TOKEN_REF.findall(line))):
            if tok in PENDING_TOKENS or any(
                tok.startswith(p[:-1]) for p in PENDING_TOKENS if p.endswith("*")
            ):
                continue
            exists = (
                any(n.startswith(tok[:-1]) for n in names) if tok.endswith(".*") else tok in names
            )
            if not exists and not quoted:
                bad.append(f"[G-STRING] {name}: unknown token {tok}")
    for m in HEX.finditer(text):
        bad.append(f"[G-STRING] {name}: hex value {m[0]}")
    for line in text.split("\n"):
        for m in BARE_PX.finditer(QUOTED.sub("", line)):
            bad.append(f"[G-STRING] {name}: raw px {m[0]!r} (a token or an anchored tool value)")
    return bad


# ---------------------------------------------------------------------------- the run

Computed = tuple[dict[str, str], dict[str, object], list[dict[str, object]], list[str]]


@functools.lru_cache(maxsize=1)
def base_texts() -> dict[str, str]:
    return {
        "d02": at_base(D02_REL),
        "p14": at_base(P14_REL),
        "p15": at_base(P15_REL),
        "p22": at_base(P22_REL),
        "km": at_base(KM_REL),
        "adapter": at_base(ADAPTER_REL),
    }


def compute(spec: str) -> Computed:
    """(values by key, extra figures, the contrast matrix, FAILs) for one spec text."""
    base = base_texts()
    themes = {k: load_theme(k) for k in THEMES}
    values, extra, bad = geometry(themes["dark"], spec)
    pv, pbad = picker(themes["dark"], spec, base["d02"])
    values.update(pv)
    values.update(budgets_from_base(base["p14"], base["p15"]))
    cr, matrix, cbad = contrast_rows(spec, themes)
    values.update(cr)
    values.update(cvd_values(themes["dark"]))
    values.update(counts(spec, base["d02"], register(spec)))
    return values, extra, matrix, bad + pbad + cbad


def handoff_keys(hand: str) -> set[str]:
    return set(PLACEHOLDER.findall(CODE.sub("", hand))) | set(ANCHOR.findall(hand))


def audit(
    spec: str, hand: str, p14: str, comp: Computed, fetch: Fetch, hand_keys: set[str]
) -> tuple[list[str], list[str], dict[str, int]]:
    values, extra, _matrix, bad = comp
    base = base_texts()
    fails: list[str] = list(bad)
    warns: list[str] = []
    fails += anchor_gates("spec", spec, values, set(values))
    if hand:
        fails += anchor_gates("hand-off", hand, values, hand_keys)
    n_cites = 0
    for name, text in (("spec", spec), ("hand-off", hand)):
        f_, w_, n = cite_check(name, text, fetch)
        fails, warns, n_cites = fails + f_, warns + w_, n_cites + n
    fails += frame_gates(spec, base["d02"], extra)
    fails += ruled_gates(spec, hand, p14, base)
    fails += string_gates("spec", spec)
    if hand:
        fails += string_gates("hand-off", hand)
    return fails, warns, {"cites": n_cites, "values": len(values)}


# ---------------------------------------------------------------------------- mutations

Edit = Callable[[str], str]


def set_cell(line: str, idx: int, fn: Edit) -> str:
    cells = [c.strip() for c in line.strip()[1:-1].split(" | ")]
    cells[idx] = fn(cells[idx])
    return "| " + " | ".join(cells) + " |"


def on_lines(pick: Callable[[str], bool], fn: Edit) -> Edit:
    """Apply `fn` to the first line `pick` selects."""

    def run(text: str) -> str:
        out = text.split("\n")
        for i, ln in enumerate(out):
            if pick(ln):
                out[i] = fn(ln)
                break
        return "\n".join(out)

    return run


def reg(frame: str, col: str, fn: Edit) -> Edit:
    """A register row's cell (§6.2), the row named by its Frame cell."""
    return on_lines(
        lambda ln: ln.startswith(f"| `{frame}`"),
        lambda ln: set_cell(ln, REG_COLS.index(col), fn),
    )


def replace(old: str, new: str) -> Edit:
    return lambda c: c.replace(old, new)


def cell_where(head: str, first: str, idx: int, fn: Edit) -> Edit:
    """A cell of the row whose first cell is `first`, inside the section `head`."""

    def run(text: str) -> str:
        block = section(text, head)
        if not block:
            return text
        lines = block.split("\n")
        for i, ln in enumerate(lines):
            if ln.startswith("|") and split_row(ln)[0] == first:
                lines[i] = set_cell(ln, idx, fn)
                break
        return text.replace(block, "\n".join(lines), 1)

    return run


def drop(pattern: str) -> Edit:
    return lambda text: re.sub(pattern + r".*\n", "", text, count=1, flags=MULTI)


def line_sub(prefix: str, old: str, new: str) -> Edit:
    return on_lines(lambda ln: ln.startswith(prefix) and old in ln, replace(old, new))


def re_sub(pattern: str, repl: str) -> Edit:
    return lambda text: re.sub(pattern, repl, text, count=1, flags=MULTI)


def both(a: Edit, b: Edit) -> Edit:
    return lambda text: b(a(text))


@dataclass(frozen=True)
class Mutation:
    mid: str
    ruled: str  # the ruled sentence (or gate class) it trips
    gate: str  # the gate tag that must trip
    fn: Edit
    target: str = "spec"  # spec | hand | p14
    exact: bool = True  # exactly one new FAIL (else: at least the named one)


R1280 = " · 1280 · dark"
MUTATIONS: tuple[Mutation, ...] = (
    # ---- §6.3's frame-mutation list (each: exactly one FAIL)
    Mutation(
        "M-1",
        "identical order on the chart, DOM and positions frames (AC2; BQ-8)",
        "G-ORDER",
        reg(
            "SCR-028/menu-dom" + R1280,
            "Order",
            replace("Settings… · Duplicate", "Duplicate · Settings…"),
        ),
    ),
    Mutation(
        "M-2",
        "no lock on a row whose key is not in merged E15-D02 §8.1 (condition 1)",
        "G-T2-KEY",
        both(
            reg(
                "SCR-028/no-settings" + R1280,
                "T2",
                lambda c: "Settings…: lock · `layout.panel.no_settings`",
            ),
            reg(
                "SCR-028/no-settings" + R1280,
                "Sentence",
                lambda c: "Reset settings…: `layout.panel.no_settings`",
            ),
        ),
    ),
    Mutation(
        "M-3",
        "the T2 anatomy on every gated row (§1.4)",
        "G-T2-ANATOMY",
        reg("SCR-028/limits" + R1280, "T2", replace("lock · ", "")),
    ),
    Mutation(
        "M-4",
        "the reason inside the accessible name on every disabled picker entry (AC1)",
        "G-PICKER",
        reg("SCR-024/disabled-recording" + R1280, "Picker", lambda c: ""),
    ),
    Mutation(
        "M-5",
        "the browser footnote on every browser-menu frame (BQ-9)",
        "G-FOOTNOTE",
        reg("SCR-028/browser · 1280 · light", "Footnote", lambda c: ""),
    ),
    Mutation(
        "M-6",
        "absence stays absence in the browser (condition 2)",
        "G-ABSENCE",
        reg(
            "SCR-028/browser" + R1280,
            "Order",
            replace("Maximise · Minimise /", "Maximise · Minimise · Pop out /"),
        ),
    ),
    Mutation(
        "M-7",
        "Close, Move panel and Move to ▸ on every menu frame, never locked (condition 4)",
        "G-EXITS",
        reg("SCR-028/view-as" + R1280, "Exits", replace(" · Move to ▸", "")),
    ),
    Mutation(
        "M-8",
        "the separator before the destructive group, Reset settings… then Close (BQ-10)",
        "G-LAST",
        reg(
            "SCR-028/corner-bottom-right · 1280 · dense · dark",
            "Last",
            lambda c: "Close · Reset settings…",
        ),
    ),
    Mutation(
        "M-9",
        "no clipped item on every overflow frame (AC4; BQ-14)",
        "G-GEOM-ROW",
        reg("SCR-028/corner-bottom-right · 1280 · dense · dark", "Geometry", lambda c: "clipped 1"),
    ),
    Mutation(
        "M-10",
        "the retained term and the five category names on no results (AC3)",
        "G-PICKER",
        reg("SCR-024/no-results" + R1280, "Picker", replace(" · Trading", "")),
    ),
    Mutation(
        "M-11",
        "the `F11` Kbd on Maximise (BQ-15)",
        "G-KBD",
        reg("SCR-028/keyboard-specimen" + R1280, "Kbd", replace("Maximise `F11`", "Maximise")),
    ),
    Mutation(
        "M-12",
        '"PROPOSED" beside every unshipped chord (BQ-15)',
        "G-KBD",
        reg(
            "SCR-028/menu-chart" + R1280,
            "Kbd",
            replace("`Ctrl+Shift+O` PROPOSED", "`Ctrl+Shift+O`"),
        ),
    ),
    Mutation(
        "M-13",
        "viewer and view-as menus identical to the owner's, the gate on Save (BQ-12)",
        "G-VIEWER",
        reg(
            "SCR-028/viewer · 1280 · light",
            "T2",
            replace("— (inset:", "Settings…: lock · `rbac.permission` (inset:"),
        ),
    ),
    Mutation(
        "M-14",
        "the second footnote sentence drawn as PROPOSED (condition 2)",
        "G-FOOTNOTE",
        reg("SCR-028/clamped-200" + R1280, "Footnote", lambda c: c.removesuffix(" PROPOSED")),
    ),
    Mutation(
        "M-15",
        "D02's five headings in D02's order (BQ-4)",
        "G-PICKER",
        reg(
            "SCR-024/default · 1920 · dark",
            "Picker",
            replace("Account · Trading", "Trading · Account"),
        ),
    ),
    Mutation(
        "M-16",
        "Reset settings… confirms, Close never (BQ-10)",
        "G-CONFIRM",
        cell_where("5.2 Items", "Close", 3, lambda c: "yes"),
    ),
    Mutation(
        "M-17",
        "the Sync group submenu's entries only; E15-D06 owns colours (BQ-13)",
        "G-SYNC",
        reg("SCR-028/sync-submenu" + R1280, "Kbd", lambda c: c + "; `color.sync.a`"),
    ),
    Mutation(
        "M-18",
        "every owner-level departure marked (BQ-4, BQ-8, BQ-9, BQ-17)",
        "G-OWNER",
        re_sub(r"^(\| D-10 .*?); owner approval pending \(#2701\)", r"\1"),
    ),
    Mutation(
        "M-19",
        "ten boards, three light twins, at most a third (BQ-17)",
        "G-BOARDS",
        drop(r"^\| 10 +\| `E15-D07 / 10 "),
    ),
    Mutation(
        "M-20",
        "the CMP-041 / APG key model with `End` on Close (BQ-16)",
        "G-KEYMODEL",
        re_sub(
            r"(^\| menu +\| `Home` / `End` .*?)`End` lands on Close",
            r"\1`End` lands on Reset settings…",
        ),
    ),
    Mutation(
        "M-21",
        "Undo move never gated (condition 4)",
        "G-EXIT-GATED",
        reg(
            "SCR-028/undo-available" + R1280,
            "T2",
            lambda c: "Undo move: lock · `layout.limit.panels`",
        ),
    ),
    Mutation(
        "M-22",
        'the short "Needs a recorded symbol." is a C-row to E16-D02\'s owner (condition 1)',
        "G-C4",
        drop(r"^\| C-4 "),
    ),
    Mutation(
        "M-23",
        "every new key carries a PROPOSED A-row (condition 1)",
        "G-NEWKEY",
        drop(r"^\| A-7 "),
    ),
    Mutation(
        "M-24",
        "the picker's exits never gated (condition 4)",
        "G-EXITS",
        reg("SCR-024/disabled-viewas" + R1280, "Exits", lambda c: ""),
    ),
    Mutation(
        "M-25",
        "menu items are client state, T1 for every session; the gate lands on Save (BQ-12)",
        "G-T2-PAIR",
        reg("SCR-028/menu-chart" + R1280, "T2", lambda c: "Settings…: lock · `rbac.permission`"),
    ),
    Mutation(
        "M-26",
        "only Duplicate and the Move to ▸ outcomes take a limit key (BQ-11; §5.5)",
        "G-T2-PAIR",
        reg("SCR-028/menu-chart" + R1280, "T2", lambda c: "Maximise: lock · `layout.limit.depth`"),
    ),
    Mutation(
        "M-27",
        "the menu opens with the first enabled item focused (AC6; BQ-16)",
        "G-FOCUS",
        reg(
            "SCR-028/no-settings" + R1280,
            "Kbd",
            replace("focus on open: Duplicate", "focus on open: Settings…"),
        ),
    ),
    # ---- the ruling's other sentences (rulings.md), one mutation each
    Mutation(
        "R-1",
        "E15-D04 is cited as merged text pinned to c73aec08",
        "G-PINS",
        line_sub("**Inputs pinned.**", "(merge `c73aec08`)", "(PENDING)"),
    ),
    Mutation(
        "R-2",
        "E15-D06 (#4470) merged at 6e2c1211: cite it as merged text too",
        "G-PINS",
        line_sub("**Inputs pinned.**", "(#4470, merge `6e2c1211`)", "(#4470)"),
    ),
    Mutation(
        "R-3",
        "PENDING siblings by name only (E15-D03, #4478)",
        "G-PINS",
        line_sub(
            "**Inputs pinned.**",
            "E15-D03 (#4478) is open",
            "E15-D03 (#4478, head `a1b2c3d4e5`) is open",
        ),
    ),
    Mutation(
        "R-4",
        "BQ-1: the spec, the hand-off and e15_d07_picker_menu_audit.py",
        "G-ARTEFACTS",
        line_sub("**Key.**", "e15_d07_picker_menu_audit.py", "e15_d07_audit.py"),
    ),
    Mutation(
        "R-5",
        "BQ-3: the fourteen R1 entries with search synonyms",
        "G-INVENTORY",
        cell_where("3.1 The inventory", "5", 9, lambda c: "—"),
    ),
    Mutation(
        "R-6",
        "BQ-3: the five not-offered screens as an inventory row",
        "G-INVENTORY",
        cell_where("3.1 The inventory", "—", 2, replace(", replay SCR-097", "")),
    ),
    Mutation(
        "R-7",
        "BQ-5: a sixth category needs a SCR-024 amendment",
        "G-GROWTH",
        line_sub(
            "4. **Categories:**",
            "a sixth category needs an amendment to SCR-024; no epic adds one by itself",
            "an epic may add a sixth category",
        ),
    ),
    Mutation(
        "R-8",
        "BQ-15: the opener D04's PROPOSED `workspace.panel_menu`",
        "G-OPENER",
        re_sub(r"none: D04's PROPOSED `workspace\.panel_menu`", "`workspace.panel_menu`"),
    ),
    Mutation(
        "R-9",
        "BQ-18: the Storybook lists in the hand-off",
        "G-STORYBOOK",
        drop(r"^\| CMP-216 PanelMenu "),
        target="hand",
    ),
    Mutation(
        "R-10",
        "BQ-18: the CRs to E15-D13",
        "G-STORYBOOK",
        drop(r"^\| CR-5 "),
    ),
    Mutation(
        "R-11",
        "BQ-4: Charting→Charts, Analysis→Market context + Journal→Account, System→Account",
        "G-TAXONOMY",
        drop(r"^\| C-1 "),
    ),
    Mutation(
        "R-12",
        "BQ-8: Float = Pop out, Full screen = Maximise",
        "G-FLOAT",
        cell_where(
            "2. Decisions",
            "D-9",
            1,
            replace("Float = Pop out and Full screen = Maximise", "Float and Full screen kept"),
        ),
    ),
    Mutation(
        "R-13",
        "BQ-9: the one stated AC2 exception for an item a build can never offer",
        "G-AC2EXC",
        drop(r"^\| C-9 "),
    ),
    Mutation(
        "R-14",
        'BQ-17: every undrawn cell "specified (drawn on request)"',
        "G-UNDRAWN",
        re_sub(r"\*\*Specified \(drawn on request\)\*\*", "**Not drawn**"),
    ),
    Mutation(
        "R-15",
        "condition 1: recording.symbol_not_recorded iff §8.1 carries it (quote it; PROPOSED)",
        "G-RECQUOTE",
        line_sub(
            "**Condition 1 (RULED).**",
            '"This panel needs a recorded symbol."',
            f'"{SHORT_RECORDING}"',
        ),
    ),
    Mutation(
        "R-16",
        "condition 1: flag.panel_off, layout.panel.no_settings, at_defaults never T2",
        "G-T2ROWS",
        cell_where("8.1 T2 rows", "R-5", 4, lambda c: c + "; `layout.panel.at_defaults`"),
    ),
    Mutation(
        "R-17",
        "condition 2: the second footnote sentence is a copy CR to E15-S02",
        "G-A12",
        drop(r"^\| A-12 "),
    ),
    Mutation(
        "R-18",
        "condition 3: the frame-mutation list, one mutation per ruled sentence",
        "G-MLIST",
        drop(r"^\| M-24 "),
    ),
    Mutation(
        "R-19",
        '"RULED" cites this comment',
        "G-RULED",
        re_sub(r"(^## .*RULED.*issuecomment-)6394505202", r"\g<1>6394505201"),
    ),
    Mutation(
        "R-20",
        "no lane as authority",
        "G-LANE",
        cell_where("21. Deviations", "DV-1", 2, lambda c: c + " (RULED by hcl-worker-1)"),
    ),
    Mutation(
        "R-21",
        "condition 4: `Esc` never gated on any frame",
        "G-EXIT-TEXT",
        cell_where("2. Decisions", "D-13", 1, lambda c: c + " `Esc` is gated while viewing as."),
    ),
    Mutation(
        "R-22",
        "BQ-2: two `14` pointer lines",
        "G-POINTER14",
        drop(r"^- \*\*Hi-fi \(E15-D07\):\*\* .*SCR-028 in colour"),
        target="p14",
    ),
    Mutation(
        "R-23",
        "BQ-2: the taxonomy and growth rule in `14` SCR-024, the same text as §3.2",
        "G-TAX14",
        line_sub("- **Type:** Modal. Grouped catalogue", "→ Market context;", "→ Account;"),
        target="p14",
    ),
    Mutation(
        "R-24",
        "condition 1: the sentence form carries no `aria-disabled` lock",
        "G-SENTENCE-ARIA",
        cell_where("8.2 Sentence-form rows", "S-2", 6, lambda c: '`aria-disabled="true"`'),
    ),
    # ---- gate classes (standing rules: cites, values, tokens, honesty, reasons)
    Mutation(
        "X-1", "a line cite past the file's end", "G-CITE", re_sub(r"`D02`:948\b", "`D02`:99999")
    ),
    Mutation("X-2", "the cited file drifted at origin/main", "G-CITE", lambda t: t),
    Mutation(
        "X-3",
        "an anchored value changed",
        "G-ANCHOR",
        re_sub(r"\d+( px<!--=BUDGET:menu\.w-->)", r"1\1"),
    ),
    Mutation(
        "X-4",
        "a hex value",
        "G-STRING",
        line_sub("No hex and no free px", "No hex and", "No hex (#FF0000) and"),
    ),
    Mutation(
        "X-5",
        "a raw px value",
        "G-STRING",
        line_sub("No hex and no free px", "no free px:", "no free px (12 px):"),
    ),
    Mutation(
        "X-6",
        "an unknown token",
        "G-STRING",
        line_sub("No hex and no free px", "no free px:", "no free px (`color.text.accentx`):"),
    ),
    Mutation(
        "X-7",
        "a heuristic finding not marked",
        "G-HONESTY",
        cell_where(
            "16. Heuristic evaluation",
            "Visibility of status",
            1,
            lambda c: c.removesuffix(" (heuristic)"),
        ),
    ),
    Mutation(
        "X-8",
        "a reason over 60 characters",
        "G-REASON",
        cell_where(
            "8.1 T2 rows",
            "R-3",
            4,
            replace(
                "Only the owner can add this panel.",
                "Only the owner of this desk can add this panel to a layout today.",
            ),
        ),
    ),
)


def drifting_fetch(rev: str, rel: str) -> str | None:
    text = git_fetch(rev, rel)
    if rev == HEAD and rel == D02_REL and text is not None:
        return "inserted\n" + text
    return text


def selftest(spec: str, hand: str, p14: str) -> tuple[bool, list[str]]:
    comp = compute(spec)
    filled, _ = fill(spec, comp[0])
    hand_f, _ = fill(hand, comp[0])
    keys = handoff_keys(hand)
    base_fails, base_warns, _ = audit(filled, hand_f, p14, compute(filled), git_fetch, keys)
    lines = [f"baseline (filled in memory): {len(base_fails)} FAIL, {len(base_warns)} WARN"]
    lines += [f"  baseline FAIL {x[:150]}" for x in base_fails]
    ok = not base_fails
    for mu in MUTATIONS:
        texts = {"spec": filled, "hand": hand_f, "p14": p14}
        before = dict(texts)
        texts[mu.target] = mu.fn(texts[mu.target])
        drift = mu.mid == "X-2"
        if texts[mu.target] == before[mu.target] and not drift:
            ok = False
            lines.append(f"  {mu.mid} [{mu.gate}] NOT APPLIED (the target text moved)")
            continue
        try:
            fails, warns, _ = audit(
                texts["spec"],
                texts["hand"],
                texts["p14"],
                compute(texts["spec"]),
                drifting_fetch if drift else git_fetch,
                keys,
            )
        except SystemExit as exc:
            fails, warns = [str(exc)], []
        got = warns if drift else fails
        new = [x for x in got if x not in base_fails + base_warns]
        named = [x for x in new if x.startswith(f"[{mu.gate}]")]
        hit = bool(named) and (len(new) == 1 or not mu.exact or drift)
        restored = filled == before["spec"] and hand_f == before["hand"]
        ok = ok and hit and restored
        first = (named or new or ["nothing new"])[0][:110]
        lines.append(
            f"  {mu.mid} [{mu.gate}] {'ok' if hit else 'MISSED'} ({len(new)} new"
            f"{'' if restored else ', NOT RESTORED'}) — {first}"
        )
    return ok, lines


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="E15-D07 picker and menu audit (module docstring)")
    ap.add_argument("--check", nargs="?", const=str(SPEC), metavar="SPEC", help="audit a spec")
    ap.add_argument("--handoff", metavar="FILE", help="the hand-off (default: SPEC's -handoff.md)")
    ap.add_argument("--json", action="store_true", help="print every computed value as JSON")
    ap.add_argument("--fill", action="store_true", help="replace placeholders, then check")
    ap.add_argument("--selftest", action="store_true", help="apply every mutation in memory")
    args = ap.parse_args(argv)
    spec_path = Path(args.check) if args.check else SPEC
    hand_path = (
        Path(args.handoff) if args.handoff else spec_path.with_name(spec_path.stem + "-handoff.md")
    )
    spec = read(spec_path)
    hand = read(hand_path) if hand_path.exists() else ""
    p14 = read(PLAN14)
    keys = handoff_keys(hand)
    if args.selftest:
        ok, lines = selftest(spec, hand, p14)
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
    values, extra, matrix, _bad = comp
    if args.json and not (args.check or args.fill):
        doc = {"values": values, "extra": extra, "contrast": matrix}
        print(json.dumps(doc, ensure_ascii=False, indent=1))
        return 0
    fails, warns, n = audit(spec, hand, p14, comp, git_fetch, keys)
    if args.json:
        doc = {"values": values, "extra": extra, "contrast": matrix}
        doc.update({"fails": fails, "warnings": warns, "numbers": n})
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        print(
            f"## E15-D07 audit of {spec_path.name} (+ {hand_path.name if hand else 'no hand-off'})"
        )
        print(f"values computed: {n['values']}; cites checked: {n['cites']} at {BASE}")
        print("\n".join(f"WARN {w}" for w in warns))
        print("\n".join(f"FAIL {x}" for x in fails) or "OK — every gate passed")
        print(f"summary: {len(fails)} FAIL, {len(warns)} WARN")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
