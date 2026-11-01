#!/usr/bin/env python3
"""E47-D03 (#1302) audit: the themes, the CVD-safe chart palette, the non-colour encodings, SCR-116.

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads,
AS TEXT at the pinned base (`git show`): the token JSON and `themes.json`, `tools/contrast/`'s
pair registry, exemptions and encoding inventory, the E47-D02 register, and the plan and design
texts the spec cites; and, from the working tree, the spec `docs/design/E47/E47-D03.md`, its
hand-off and the pins file. Its form follows the E12-D07 tool (the same modes, the anchored
values, the default-deny pins and the mutations).

1. **Values.** Every `{{KIND:key}}` placeholder is written by `--fill` as `VALUE<!--=KIND:key-->`
   and re-derived under `--check` (G-ANCHOR); a placeholder left behind or a stray HTML comment
   FAILs (G-MARKER). Kinds: CR `theme/fg/bg` (WCAG 2.x ratio, truncated to two decimals), ACC
   `theme/fg` (the lowest CR over the four accent surfaces), DE `theme/sim/a/b` (CIE76 between
   the two simulated colours, truncated to one decimal), SIM `theme/sim/token` (simulated hex),
   HEX `theme/token`, RAMP `theme/sim/ramp` (`ordered` when the stops' L* distance from the
   canvas grows with every stop, `inverted` when it shrinks, else `mixed`), STEP `theme/sim/ramp`
   (the smallest adjacent L* step), COUNT and AGG (counts and aggregates of the spec's own tables
   and of the base files). Themes: `dark`, `light`, `hc`; a `+` suffix applies the hand-off's
   proposed token diff (PROPOSED below). Sims: `none`, `deut`, `prot` (Brettel/Vienot), `trit`
   (Machado 2009), `grey` (relative-luminance projection) — the matrices of
   `tools/contrast/color-math.mjs`, ported with its rounding.
2. **Cites.** Every `NN`:line and KEY:line cite resolves to a non-blank line at the base (G-CITE);
   every "verbatim" copy string occurs on its cited line (G-QUOTE); every Old fragment of the
   hand-off's A-rows occurs verbatim on its cited line (G-AROW).
3. **Gates.** One FAIL line per gate: G-PENDING (the BQ section is marked "defaults built; ruling
   pending" and names the question list), G-BOARDS (at most ten boards, light twins at most a
   third, each PENDING or drawn with its committed PNG at the stated size), G-BAR (every measured
   row's verdict names exactly the themes below its bar), G-AAA (the 7:1 stretch rows name the
   themes that meet it), G-CVD (a pair under the JND floor names a non-colour cue; "none needed"
   only when every value clears it), G-RAMP (a ramp verdict is pass only when every cell is
   ordered), G-ACCENT (each preset's warning names exactly the themes below the bar), G-ENC
   (every surface of `encodings.json` is a row with its shipped channels; designed channels
   keep them and use the inventory's vocabulary), G-D02 (the routed findings equal the register's
   rows owned by E47-D03, with their status), G-EXEMPT (every pair exemption is classified, stale
   exactly when it now meets its bar, retune naming a token-diff row), G-DIFF (the hand-off's
   token diff equals PROPOSED; Old is the base value), G-HEUR, G-WALK (at most ten items),
   G-OWNER (owners are tickets or spec owners, never an agent), G-URL (no URL, host or local
   path), G-UNTOUCHED (only this ticket's files, its boards and one `14` pointer line differ from
   the merge base with origin/main), G-BUDGET and G-MUTLIST (the spec's mutation table equals
   this tool's list).
4. **Pins (G-RULED).** The BQ bullets are pinned verbatim in `e47_d03_ruled_pins.txt`;
   `--repin-ruled` is the only writer (when the ruling lands, the section flips and is re-pinned)
   and refuses while a placeholder is unfilled.
5. **--self-test** applies every mutation (M-n) in memory with the values frozen at the filled
   baseline; each must make exactly one gate FAIL, the one it names; the texts on disk are checked
   byte-identical afterwards (sha256). Output is ASCII.

Usage (from the repo root):
  python3 -I docs/design/_tools/e47_d03_theme_audit.py --check [--fill]
  python3 -I docs/design/_tools/e47_d03_theme_audit.py --self-test
  python3 -I docs/design/_tools/e47_d03_theme_audit.py --repin-ruled
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import itertools
import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = "95a4f2765"  # origin/main when the spec was written; every cite is read here

SPEC_REL = "docs/design/E47/E47-D03.md"
HAND_REL = "docs/design/E47/E47-D03-handoff.md"
TOOL_REL = "docs/design/_tools/e47_d03_theme_audit.py"
PIN_REL = "docs/design/_tools/e47_d03_ruled_pins.txt"
OWN = (SPEC_REL, HAND_REL, TOOL_REL, PIN_REL)
OWN_BOARDS = re.compile(r"^docs/design/E47/img/E47-D03-\d\d-[a-z0-9-]+\.png$")
OWN_KIT = re.compile(r"^docs/design/_tools/sheets/e47-d03/")
POINTER_14 = "- **Hi-fi (E47-D03, #1302):**"
SPEC_BUDGET = 630
HAND_BUDGET = 170

PLAN = {
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "22": "docs/plan/22-api-openapi.yaml",
}
CITE_FILES = {
    "E05R": "docs/design/E05/E05-D02-rest.md",
    "E10D03": "docs/design/E10/E10-D03.md",
    "E11D02": "docs/design/E11/E11-D02.md",
    "E22D03": "docs/design/E22/E22-D03.md",
    "S07": "docs/design/E47/E47-S07.md",
    "CAT": "docs/plan/a11y/47-audit-catalogue.md",
    "PAIRS": "tools/contrast/pairs.mjs",
    "ENC": "tools/contrast/encodings.json",
    "EXEM": "tools/contrast/exemptions.json",
    "INK": "tools/contrast/data-ink-lib.mjs",
    "MATH": "tools/contrast/color-math.mjs",
    "MODES": "packages/ui/scripts/chart-color-modes.mjs",
    "APP": "apps/web/src/features/appearance/AppearanceScreen.tsx",
    "ENG": "apps/web/src/features/appearance/chartColorMode.ts",
    "LEG": "packages/ui/src/components/ColorConventionLegend.tsx",
    "LOF": "tools/contrast/label-on-fill.json",
    "THEMES": "packages/ui/tokens/themes.json",
    "TDARK": "packages/ui/tokens/semantic-dark.tokens.json",
    "TLIGHT": "packages/ui/tokens/semantic-light.tokens.json",
    "THC": "packages/ui/tokens/semantic-hc.tokens.json",
}
REGISTER_REL = "docs/plan/a11y/47-audit-register.json"
UNMERGED_PATHS = ("E47-D01.md", "E47-D04.md", "E47-D05.md", "E47-D08.md", "E47-D10.md")
DS = "packages/ui/tokens"
THEMES: dict[str, tuple[str, ...]] = {
    "dark": ("primitives", "semantic-dark"),
    "light": ("primitives", "semantic-dark", "semantic-light"),
    "hc": ("primitives", "semantic-dark", "semantic-hc"),
}
GATE_THEME = {"dark": "dark", "light": "light", "high-contrast": "hc"}
THEME_WORD = {"dark": "dark", "light": "light", "hc": "high contrast"}

# The hand-off's token diff (§C.2), applied by E47-D10: set -> token -> new `$value`.
PROPOSED: dict[str, dict[str, str]] = {
    "primitives": {"palette.blue.200": "#A8C7FA"},
    "semantic-dark": {
        "color.border.strong": "{palette.neutral.600}",
        "border.control": "{border.hairline}",
    },
    "semantic-light": {
        "color.border.strong": "{palette.light.neutral.500}",
        **{f"color.cvd.heatmap.bid.{i}": f"{{palette.cvd.light.blue.{i}}}" for i in (1, 2, 4, 5)},
        **{f"color.cvd.heatmap.ask.{i}": f"{{palette.cvd.light.orange.{i}}}" for i in (1, 2, 4, 5)},
    },
    "semantic-hc": {
        "color.text.link": "{palette.blue.200}",
        "border.control": "{border.thick}",
    },
}

SIMS = ("none", "deut", "prot", "trit", "grey")
JND = 5.0  # `CVD_JND_FLOOR` in tools/contrast/color-math.mjs
ACCENT_SURFACES = (
    "color.surface.app",
    "color.surface.canvas",
    "color.surface.raised",
    "color.surface.overlay",
)
CANVAS = "color.surface.canvas"
RAMPS: dict[str, tuple[str, ...]] = {
    "heatmap.bid": tuple(f"color.heatmap.bid.{i}" for i in range(1, 6)),
    "heatmap.ask": tuple(f"color.heatmap.ask.{i}" for i in range(1, 6)),
    "cvd.heatmap.bid": tuple(f"color.cvd.heatmap.bid.{i}" for i in range(1, 6)),
    "cvd.heatmap.ask": tuple(f"color.cvd.heatmap.ask.{i}" for i in range(1, 6)),
}
CHANNELS = ("glyph", "sign", "text", "pattern", "position")  # encodings.json's vocabulary
PENDING_MARK = "defaults built; ruling pending (the BQ comment on #1302)"
BQ_LIST_ID = "6552540218"
AGENT_RE = re.compile(r"worker|orchestrator|\bagent\b|anvil|claude|codex|lane\b", re.IGNORECASE)
OWNER_OK_RE = re.compile(r"\bE\d\d-[A-Z]+\d\d\b|\bowner|\bepic E\d\d")
URL_RE = re.compile(
    r"https?://|www\.|/home/|localhost|\.local\b|\b[a-z0-9-]+\.(?:com|io|org|net)\b"
)

Finding = tuple[str, str, str, str]  # gate, message, doc, region
Values = dict[str, str]


# ---------------------------------------------------------------------------- git and files


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout


@functools.lru_cache(maxsize=64)
def at_base(rel: str) -> str:
    return git("show", f"{BASE}:{rel}")


@functools.lru_cache(maxsize=64)
def base_lines(rel: str) -> tuple[str, ...]:
    return tuple(at_base(rel).split("\n"))


def changed_paths() -> tuple[str, ...]:
    fork = git("merge-base", "HEAD", "origin/main").strip()
    tracked = git("diff", "--name-only", fork).split()
    untracked = git("ls-files", "--others", "--exclude-standard").split()
    return tuple(sorted(set(tracked) | set(untracked)))


def diff_14() -> tuple[str, ...]:
    fork = git("merge-base", "HEAD", "origin/main").strip()
    out = git("diff", "--unified=0", fork, "--", PLAN["14"]).split("\n")
    return tuple(
        ln
        for ln in out
        if ln[:1] in ("+", "-") and not ln.startswith("+++") and not ln.startswith("---")
    )


# ---------------------------------------------------------------------------- markdown model


@dataclass(frozen=True)
class Texts:
    spec: str
    hand: str
    changed: tuple[str, ...]
    d14: tuple[str, ...]

    def doc(self, name: str) -> str:
        return self.spec if name == "spec" else self.hand


def line_regions(text: str) -> list[str]:
    """The heading path (with an occurrence suffix) of every line; a heading belongs to itself."""
    stack: list[tuple[int, str]] = []
    seen: dict[str, int] = {}
    current = "(top)#1"
    out: list[str] = []
    for line in text.split("\n"):
        m = re.match(r"^(#{1,6}) (.*)$", line)
        if m:
            level = len(m.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, m.group(2).strip()))
            path = " > ".join(t for _, t in stack)
            seen[path] = seen.get(path, 0) + 1
            current = f"{path}#{seen[path]}"
        out.append(current)
    return out


def section(text: str, prefix: str) -> tuple[int, int, str]:
    """(first body line index, end index, region) of the heading starting with `prefix`."""
    lines = text.split("\n")
    regions = line_regions(text)
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            level = len(line) - len(line.lstrip("#"))
            end = len(lines)
            for j in range(i + 1, len(lines)):
                m = re.match(r"^(#{1,6}) ", lines[j])
                if m and len(m.group(1)) <= level:
                    end = j
                    break
            return i + 1, end, regions[i]
    return 0, 0, f"(missing {prefix})"


def section_text(text: str, prefix: str) -> str:
    s, e, _ = section(text, prefix)
    return "\n".join(text.split("\n")[s:e])


def cells(line: str) -> list[str]:
    body = line.strip().removeprefix("|").removesuffix("|")
    return [c.strip() for c in re.split(r"(?<!\\)\|", body)]


def is_rule_row(line: str) -> bool:
    return bool(re.fullmatch(r"\|[\s:|-]+\|", line.strip()))


def tables(text: str, prefix: str) -> list[list[list[str]]]:
    """Every table in the section: a list of rows (header first), each a list of cells."""
    s, e, _ = section(text, prefix)
    out: list[list[list[str]]] = []
    cur: list[list[str]] = []
    for line in text.split("\n")[s:e]:
        if line.strip().startswith("|"):
            if not is_rule_row(line):
                cur.append(cells(line))
        elif cur:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def first_table(text: str, prefix: str) -> list[list[str]]:
    ts = tables(text, prefix)
    return ts[0] if ts else []


def plain(cell: str) -> str:
    return cell.replace("`", "").strip()


def col(header: list[str], name: str) -> int:
    for i, h in enumerate(header):
        if plain(h).lower().startswith(name.lower()):
            return i
    return -1


# ---------------------------------------------------------------------------- anchors

ANCHOR_RE = re.compile(r"(?<![0-9A-Za-z.,#])([#0-9A-Za-z.,]+)<!--=([A-Z]+):([a-z0-9.\-/+]+)-->")
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z]+):([a-z0-9.\-/+]+)\}\}")


def anchors(text: str) -> list[tuple[str, str, str]]:
    return [(m.group(1), m.group(2), m.group(3)) for m in ANCHOR_RE.finditer(text)]


# ---------------------------------------------------------------------------- colour


@functools.lru_cache(maxsize=8)
def token_file(name: str) -> dict[str, str]:
    data = json.loads(at_base(f"{DS}/{name}.tokens.json"))
    return {k: str(v["$value"]) for k, v in data.items() if isinstance(v, dict) and "$value" in v}


@functools.lru_cache(maxsize=8)
def load_theme(name: str) -> dict[str, str]:
    base, plus = name.rstrip("+"), name.endswith("+")
    merged: dict[str, str] = {}
    for f in THEMES[base]:
        merged.update(token_file(f))
        if plus:
            merged.update(PROPOSED.get(f, {}))
    return merged


def hex_of(theme: str, name: str) -> str:
    tokens = load_theme(theme)
    value = tokens.get(name, "MISSING")
    hops = 0
    while value.startswith("{") and value.endswith("}") and hops < 12:
        value, hops = tokens.get(value[1:-1], "MISSING"), hops + 1
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
        raise SystemExit(f"FAIL token {name} ({theme}) does not resolve to an opaque colour")
    return value.upper()


def rgb(hex6: str) -> tuple[int, int, int]:
    h = hex6.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def srgb_to_linear(c: int) -> float:
    x = c / 255.0
    return x / 12.92 if x <= 0.04045 else float(((x + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c: float) -> float:
    s = c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055
    return max(0.0, min(1.0, s)) * 255.0


def luminance(hex6: str) -> float:
    r, g, b = (srgb_to_linear(c) for c in rgb(hex6))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


Mat = tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]
RGB_TO_LMS: Mat = (
    (17.8824, 43.5161, 4.11935),
    (3.45565, 27.1554, 3.86714),
    (0.0299566, 0.184309, 1.46709),
)
LMS_TO_RGB: Mat = (
    (0.0809444479, -0.130504409, 0.116721066),
    (-0.0102485335, 0.0540193266, -0.113614708),
    (-0.000365296938, -0.00412161469, 0.693511405),
)
PROJECTIONS: dict[str, Mat] = {
    "prot": ((0.0, 2.02344, -2.52581), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    "deut": ((1.0, 0.0, 0.0), (0.494207, 0.0, 1.24827), (0.0, 0.0, 1.0)),
}
# Machado, Oliveira & Fernandes 2009, tritanomaly at severity 1.0, on linear RGB.
TRITAN: Mat = (
    (1.255528, -0.076749, -0.178779),
    (-0.078411, 0.930809, 0.147602),
    (0.004733, 0.691367, 0.303900),
)
# The pinned port check (`--self-test`): values `color-math.mjs` gives for these inputs.
SIM_PINS = {
    ("#2EBD59", "deut"): "#A3A35D",
    ("#E5484D", "prot"): "#6B6B4E",
    ("#58A8D9", "trit"): "#00B5B8",
    ("#E5484D", "grey"): "#818181",
}


def matvec(m: Mat, v: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
        m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
        m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
    )


def to_hex(v: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02X}" for c in v)


def simulate(hex6: str, sim: str) -> str:
    r, g, b = (srgb_to_linear(c) for c in rgb(hex6))
    lin = (r, g, b)
    if sim == "none":
        return hex6.upper()
    if sim == "grey":
        y = linear_to_srgb(0.2126 * r + 0.7152 * g + 0.0722 * b)
        return to_hex((y, y, y))
    if sim == "trit":
        out = matvec(TRITAN, lin)
    elif sim in PROJECTIONS:
        out = matvec(LMS_TO_RGB, matvec(PROJECTIONS[sim], matvec(RGB_TO_LMS, lin)))
    else:
        raise SystemExit(f"FAIL unknown simulation {sim}")
    return to_hex((linear_to_srgb(out[0]), linear_to_srgb(out[1]), linear_to_srgb(out[2])))


def lab(hex6: str) -> tuple[float, float, float]:
    r, g, b = (srgb_to_linear(c) for c in rgb(hex6))
    x = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883

    def f(t: float) -> float:
        return float(t ** (1 / 3)) if t > 0.008856 else (7.787 * t) + (16 / 116)

    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def delta_e(a: str, b: str) -> float:
    return math.dist(lab(a), lab(b))


def trunc(x: float, places: int) -> str:
    k = 10**places
    return f"{math.floor(x * k) / k:.{places}f}"


# ---------------------------------------------------------------------------- raw measures


def raw_cr(key: str) -> float:
    theme, fg, bg = key.split("/")
    return contrast(hex_of(theme, fg), hex_of(theme, bg))


def raw_acc(key: str) -> float:
    theme, fg = key.split("/")
    return min(contrast(hex_of(theme, fg), hex_of(theme, s)) for s in ACCENT_SURFACES)


def raw_de(key: str) -> float:
    theme, sim, a, b = key.split("/")
    return delta_e(simulate(hex_of(theme, a), sim), simulate(hex_of(theme, b), sim))


def ramp_distances(key: str) -> list[float]:
    theme, sim, ramp = key.split("/")
    ground = lab(simulate(hex_of(theme, CANVAS), sim))[0]
    return [abs(lab(simulate(hex_of(theme, t), sim))[0] - ground) for t in RAMPS[ramp]]


def ramp_word(key: str) -> str:
    d = ramp_distances(key)
    steps = [b - a for a, b in itertools.pairwise(d)]
    if all(s > 0 for s in steps):
        return "ordered"
    if all(s < 0 for s in steps):
        return "inverted"
    return "mixed"


def ramp_step(key: str) -> float:
    theme, sim, ramp = key.split("/")
    ls = [lab(simulate(hex_of(theme, t), sim))[0] for t in RAMPS[ramp]]
    return min(abs(b - a) for a, b in itertools.pairwise(ls))


# ---------------------------------------------------------------------------- base files


PAIR_RE = re.compile(
    r'\{\s*fg:\s*"([^"]+)",\s*bg:\s*"([^"]+)",\s*threshold:\s*THRESHOLD\.(\w+)'
    r"(?:,\s*themes:\s*\[([^\]]*)\])?"
)
THRESHOLD = {"TEXT": 4.5, "NON_TEXT": 3.0, "HIGH_CONTRAST": 7.0}


@functools.lru_cache(maxsize=1)
def registry() -> tuple[tuple[str, str, float, str], ...]:
    rows = PAIR_RE.findall(at_base(CITE_FILES["PAIRS"]))
    return tuple((fg, bg, THRESHOLD[th], ths) for fg, bg, th, ths in rows)


@functools.lru_cache(maxsize=1)
def pair_exemptions() -> tuple[str, ...]:
    data = json.loads(at_base(CITE_FILES["EXEM"]))
    return tuple(str(e["pair"]) for e in data["exemptions"] if "pair" in e)


@functools.lru_cache(maxsize=1)
def encodings() -> dict[str, dict[str, list[str]]]:
    data = json.loads(at_base(CITE_FILES["ENC"]))
    return {k: v["surfaces"] for k, v in data["encodings"].items()}


@functools.lru_cache(maxsize=1)
def routed() -> dict[str, str]:
    data = json.loads(at_base(REGISTER_REL))
    return {
        str(f["id"]): str(f["status"])
        for f in data["findings"]
        if f.get("designOwner") == "E47-D03"
    }


def registry_stats(theme: str) -> tuple[int, int, int, float]:
    """(pairs measured, below their bar, of those under a pair exemption, lowest unexempted)."""
    gate_name = {v: k for k, v in GATE_THEME.items()}[theme]
    exempt = set(pair_exemptions())
    n = below = covered = 0
    low = 99.0
    for fg, bg, bar, ths in registry():
        if ths and gate_name not in ths:
            continue
        r = contrast(hex_of(theme, fg), hex_of(theme, bg))
        n += 1
        if r < bar:
            below += 1
            if f"{gate_name}:{fg} on {bg}" in exempt:
                covered += 1
                continue
        low = min(low, r)
    return n, below, covered, low


def exemption_now(pair: str) -> tuple[str, float, float]:
    """(anchor key, value now, bar) of one pair exemption."""
    gate_name, rest = pair.split(":", 1)
    theme = GATE_THEME[gate_name]
    if " on " in rest:
        fg, bg = rest.split(" on ")
        bar = next((b for f, g, b, _ in registry() if f == fg and g == bg), 3.0)
        key = f"CR:{theme}/{fg}/{bg}"
        return key, raw_cr(key[3:]), bar
    pair_part, defic = rest.rsplit(":", 1)
    a, b = pair_part.split(" vs ")
    sim = {"deuteranopia": "deut", "protanopia": "prot", "tritanopia": "trit"}[defic]
    key = f"DE:{theme}/{sim}/{a}/{b}"
    return key, raw_de(key[3:]), JND


# ---------------------------------------------------------------------------- values


def board_rows(spec: str) -> list[list[str]]:
    return first_table(spec, "## 0.")[1:]


def count_values(t: Texts) -> Values:
    v: Values = {}
    boards = board_rows(t.spec)
    v["COUNT:boards"] = str(len(boards))
    v["COUNT:boards.light"] = str(sum(1 for r in boards if len(r) > 3 and r[3] == "light"))
    v["COUNT:copy"] = str(len(first_table(t.spec, "## 13.")[1:]))
    v["COUNT:findings"] = str(len(first_table(t.spec, "## 14.")[1:]))
    v["COUNT:walkthrough"] = str(section_text(t.hand, "## §E").count("\n- [ ]"))
    v["COUNT:d02.rows"] = str(len(routed()))
    v["COUNT:d02.fixed"] = str(sum(1 for s in routed().values() if s == "fixed"))
    v["COUNT:d02.open"] = str(sum(1 for s in routed().values() if s != "fixed"))
    v["COUNT:pairs"] = str(len(registry()))
    v["COUNT:exempt"] = str(len(pair_exemptions()))
    classes = [r[3] for r in first_table(t.spec, "### 4.2")[1:] if len(r) > 3]
    for c in ("stale", "standing", "retune"):
        v[f"COUNT:exempt.{c}"] = str(classes.count(c))
    v["COUNT:enc.surfaces"] = str(sum(len(s) for s in encodings().values()))
    v["COUNT:enc.encodings"] = str(len(encodings()))
    v["COUNT:diff"] = str(sum(len(x) for x in PROPOSED.values()))
    for theme in ("dark", "light", "hc"):
        keys = load_theme(theme)
        own = token_file(THEMES[theme][-1])
        v[f"COUNT:keys.{theme}"] = str(len(own))
        v[f"COUNT:keys.{theme}.resolved"] = str(sum(1 for k in keys if not k.startswith("palette")))
        n, below, covered, low = registry_stats(theme)
        v[f"AGG:pairs.{theme}.n"] = str(n)
        v[f"AGG:pairs.{theme}.below"] = str(below)
        v[f"AGG:pairs.{theme}.exempt"] = str(covered)
        v[f"AGG:pairs.{theme}.open"] = str(below - covered)
        v[f"AGG:pairs.{theme}.low"] = trunc(low, 2)
    return v


def value_of(kind: str, key: str, counts: Values) -> str | None:
    try:
        if kind == "CR":
            return trunc(raw_cr(key), 2)
        if kind == "ACC":
            return trunc(raw_acc(key), 2)
        if kind == "DE":
            return trunc(raw_de(key), 1)
        if kind == "SIM":
            theme, sim, tok = key.split("/")
            return simulate(hex_of(theme, tok), sim)
        if kind == "HEX":
            theme, tok = key.split("/")
            return hex_of(theme, tok)
        if kind == "RAMP":
            return ramp_word(key)
        if kind == "STEP":
            return trunc(ramp_step(key), 1)
    except (ValueError, KeyError):
        return None
    return counts.get(f"{kind}:{key}")


def compute_values(t: Texts) -> Values:
    counts = count_values(t)
    out: Values = {}
    for doc in (t.spec, t.hand):
        for kind, key in PLACEHOLDER_RE.findall(doc) + [(k, y) for _, k, y in anchors(doc)]:
            got = value_of(kind, key, counts)
            if got is not None:
                out[f"{kind}:{key}"] = got
    return out


# ---------------------------------------------------------------------------- mutations


@dataclass(frozen=True)
class Mutation:
    mid: str
    what: str
    gate: str
    doc: str  # "spec", "hand", "changed" or "d14"
    where: str  # a heading prefix; "" = the whole document; "<eof>" = append
    old: str
    new: str


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        "M-1", "mark board 01 drawn without an id", "G-BOARDS", "spec", "## 0.", "PENDING", "drawn"
    ),
    Mutation(
        "M-2", "re-word W-1", "G-QUOTE", "spec", "## 13.", "text may be hard", "text can be hard"
    ),
    Mutation(
        "M-3",
        "point a §2 cite past the end of `16`",
        "G-CITE",
        "spec",
        "## 2.",
        "`16`:354–355",
        "`16`:354–99355",
    ),
    Mutation(
        "M-4",
        "re-word the BQ-1 bullet",
        "G-RULED",
        "spec",
        "## The questions",
        "one CVD-safe chart palette",
        "one CVD theme",
    ),
    Mutation(
        "M-5",
        "drop the pending mark from the BQ heading",
        "G-PENDING",
        "spec",
        "",
        "defaults built; ruling pending",
        "defaults built",
    ),
    Mutation(
        "M-6",
        "change one anchored ratio",
        "G-ANCHOR",
        "spec",
        "### 3.1",
        "<!--=CR:dark/color.text.primary/color.surface.app-->",
        "1<!--=CR:dark/color.text.primary/color.surface.app-->",
    ),
    Mutation(
        "M-7",
        "leave a placeholder unfilled",
        "G-MARKER",
        "spec",
        "<eof>",
        "",
        "\n{{CR:dark/color.text.primary/color.surface.app}}\n",
    ),
    Mutation(
        "M-8", "call the H-8 row a pass", "G-BAR", "spec", "### 3.1", "fails hc → D03-D2", "pass"
    ),
    Mutation(
        "M-9",
        "claim no cue for the light buy / sell pair",
        "G-CVD",
        "spec",
        "### 7.2",
        "required — sign, glyph, text",
        "none needed",
    ),
    Mutation(
        "M-10",
        "pass the inverted light CVD ramp",
        "G-RAMP",
        "spec",
        "### 7.3",
        "fails light → D03-D7",
        "pass",
    ),
    Mutation(
        "M-11", "rename the heatmap surface", "G-ENC", "spec", "## 5.", "| heatmap ", "| heat map "
    ),
    Mutation(
        "M-12", "drop a routed finding", "G-D02", "spec", "## 11.", "A11Y-F-0024", "A11Y-F-0099"
    ),
    Mutation("M-13", "drop `(heuristic)` from H-1", "G-HEUR", "spec", "## 14.", "(heuristic) ", ""),
    Mutation(
        "M-14",
        "add two walkthrough items",
        "G-WALK",
        "hand",
        "## §E",
        "- [ ] Board 01",
        "- [ ] extra one\n- [ ] extra two\n- [ ] Board 01",
    ),
    Mutation(
        "M-15",
        "name an agent as D03-G1's owner",
        "G-OWNER",
        "spec",
        "### 16.2",
        "E02-T13 (#5181)",
        "the design worker",
    ),
    Mutation(
        "M-16",
        "write a page URL in §0",
        "G-URL",
        "spec",
        "## 0.",
        "Penpot file",
        "Penpot file https://x.example.com/p",
    ),
    Mutation(
        "M-17",
        "touch `22` in the working tree",
        "G-UNTOUCHED",
        "changed",
        "",
        "",
        "docs/plan/22-api-openapi.yaml",
    ),
    Mutation(
        "M-18", "pad the spec past its line budget", "G-BUDGET", "spec", "<eof>", "", "\npad" * 700
    ),
    Mutation(
        "M-19",
        "re-word D03-A1's Old fragment",
        "G-AROW",
        "hand",
        "### §C.1",
        "CVD-safe deuteranopia",
        "CVD safe deuteranopia",
    ),
    Mutation(
        "M-20",
        "change D03-D2's New value",
        "G-DIFF",
        "hand",
        "### §C.2",
        "`{palette.blue.200}`",
        "`{palette.blue.300}`",
    ),
    Mutation(
        "M-21",
        "call a stale exemption standing",
        "G-EXEMPT",
        "spec",
        "### 4.2",
        "stale",
        "standing",
    ),
    Mutation(
        "M-22",
        "drop Purple's high-contrast warning",
        "G-ACCENT",
        "spec",
        "### 8.2",
        "high contrast",
        "none",
    ),
    Mutation(
        "M-23",
        "claim the dark env word misses 7:1",
        "G-AAA",
        "spec",
        "### 3.5",
        "dark, light, hc",
        "light, hc",
    ),
    Mutation(
        "M-24",
        "replace a mutation row's gate in §15",
        "G-MUTLIST",
        "spec",
        "## 15.",
        "G-QUOTE",
        "G-CITE",
    ),
)


def mutation_rows() -> str:
    return "\n".join(f"| {m.mid} | {m.what} | {m.gate} |" for m in MUTATIONS)


def apply_mutation(t: Texts, m: Mutation) -> Texts:
    if m.doc == "changed":
        return replace(t, changed=(*t.changed, m.new))
    text = t.doc(m.doc)
    if m.where == "<eof>":
        new_text = text + m.new
    else:
        if m.where:
            s, e, _ = section(text, m.where)
            lines = text.split("\n")
            offset = len("\n".join(lines[:s])) + (1 if s else 0)
            span = "\n".join(lines[s:e])
        else:
            offset, span = 0, text
        k = span.find(m.old)
        if k < 0:
            raise SystemExit(f"FAIL {m.mid}: its target text is not in {m.doc} {m.where!r}")
        k += offset
        new_text = text[:k] + m.new + text[k + len(m.old) :]
    return replace(t, spec=new_text) if m.doc == "spec" else replace(t, hand=new_text)


# ---------------------------------------------------------------------------- gates


def per_line(t: Texts) -> list[tuple[str, int, str, str]]:
    out: list[tuple[str, int, str, str]] = []
    for doc in ("spec", "hand"):
        text = t.doc(doc)
        regions = line_regions(text)
        for i, line in enumerate(text.split("\n")):
            out.append((doc, i, line, regions[i]))
    return out


def g_anchor(t: Texts, values: Values) -> list[Finding]:
    out: list[Finding] = []
    for doc, _, line, region in per_line(t):
        for val, kind, key in anchors(line):
            want = values.get(f"{kind}:{key}")
            if want is None:
                out.append(("G-ANCHOR", f"unknown anchor {kind}:{key}", doc, region))
            elif val != want:
                out.append(("G-ANCHOR", f"{kind}:{key} reads {val}, derives {want}", doc, region))
    return out


def g_marker(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for doc, i, line, region in per_line(t):
        if "{{" in line:
            out.append(("G-MARKER", f"unfilled placeholder on line {i + 1}", doc, region))
        if "<!--" in ANCHOR_RE.sub("", line):
            out.append(("G-MARKER", f"a stray HTML comment on line {i + 1}", doc, region))
    return out


_KEYS = "|".join(sorted(CITE_FILES, key=len, reverse=True))
CITE_RE = re.compile(rf"(?:`(\d\d)`|\b({_KEYS}))(:\d+(?:–\d+)?(?:, :\d+(?:–\d+)?)*)")


def cite_targets(line: str) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for m in CITE_RE.finditer(line):
        rel = PLAN.get(m.group(1) or "") or CITE_FILES.get(m.group(2) or "")
        if rel is None:
            out.append((f"?{m.group(1)}", 0))
            continue
        for a, b in re.findall(r":(\d+)(?:–(\d+))?", m.group(3)):
            out.append((rel, int(a)))
            if b:
                out.append((rel, int(b)))
    return out


def g_cite(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for doc, _, line, region in per_line(t):
        for rel, n in cite_targets(line):
            if rel.startswith("?"):
                out.append(("G-CITE", f"unknown cite key {rel[1:]}", doc, region))
                continue
            lines = base_lines(rel)
            if not (1 <= n <= len(lines)) or not lines[n - 1].strip():
                out.append(("G-CITE", f"{rel}:{n} is not a non-blank line", doc, region))
    return out


def cited_text(cite_cell: str) -> str:
    return "\n".join(
        base_lines(rel)[n - 1]
        for rel, n in cite_targets(cite_cell)
        if not rel.startswith("?") and 1 <= n <= len(base_lines(rel))
    )


def g_quote(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    _, _, region = section(t.spec, "## 13.")
    for row in first_table(t.spec, "## 13.")[1:]:
        if len(row) < 4 or not row[3].startswith("verbatim"):
            continue
        s = row[1].strip().strip('"')
        if s not in cited_text(row[2]):
            out.append(("G-QUOTE", f"{row[0]} is not verbatim on {row[2]}", "spec", region))
    return out


def g_arow(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    _, _, region = section(t.hand, "### §C.1")
    rows = first_table(t.hand, "### §C.1")
    if len(rows) < 2:
        return [("G-AROW", "no A-rows", "hand", region)]
    for row in rows[1:]:
        old = row[3].strip()
        if old.startswith("`") and old.endswith("`") and old.count("`") == 2:
            old = old[1:-1]
        if not cite_targets(row[2]) or old not in cited_text(row[2]):
            out.append(("G-AROW", f"{row[0]}'s Old is not verbatim on {row[2]}", "hand", region))
    return out


def g_diff(t: Texts) -> list[Finding]:
    _, _, region = section(t.hand, "### §C.2")
    want = {(s, k): v for s, d in PROPOSED.items() for k, v in d.items()}
    got: dict[tuple[str, str], tuple[str, str]] = {}
    for row in first_table(t.hand, "### §C.2")[1:]:
        if len(row) < 5:
            continue
        for tok in re.findall(r"`([a-z0-9.\-]+)`", row[2]) or [plain(row[2])]:
            got[(plain(row[1]), tok)] = (plain(row[3]), plain(row[4]))
    bad: list[str] = []
    for key in sorted(set(want) | set(got)):
        if key not in want or key not in got:
            bad.append(f"{key[0]} {key[1]} not in both the tool and §C.2")
            continue
        old, new = got[key]
        base = token_file(key[0]).get(key[1])
        if new != want[key]:
            bad.append(f"{key[1]} New {new} != {want[key]}")
        if (base is None and old != "—") or (base is not None and old != base):
            bad.append(f"{key[1]} Old {old} != base {base}")
    return [("G-DIFF", "; ".join(bad[:3]), "hand", region)] if bad else []


def g_pending(t: Texts) -> list[Finding]:
    heading = next((ln for ln in t.spec.split("\n") if ln.startswith("## The questions")), "")
    body = section_text(t.spec, "## The questions")
    if PENDING_MARK not in heading or BQ_LIST_ID not in body:
        return [("G-PENDING", "the BQ section lacks its pending mark or list id", "spec", heading)]
    return []


def bq_bullets(spec: str) -> list[str]:
    return [
        ln for ln in section_text(spec, "## The questions").split("\n") if ln.startswith("- **BQ-")
    ]


def read_pins() -> list[str]:
    path = ROOT / PIN_REL
    if not path.exists():
        return []
    return [
        ln for ln in path.read_text(encoding="utf-8").split("\n") if ln and not ln.startswith("#")
    ]


def g_ruled(t: Texts) -> list[Finding]:
    have, pins = bq_bullets(t.spec), read_pins()
    if have != pins:
        n = sum(1 for a, b in zip(have, pins, strict=False) if a != b) + abs(len(have) - len(pins))
        return [("G-RULED", f"{n} BQ bullet(s) differ from the pins", "spec", "BQ")]
    return []


def png_size(rel: str) -> tuple[int, int] | None:
    path = ROOT / rel
    if not path.exists():
        return None
    head = path.read_bytes()[:24]
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def g_boards(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 0.")
    rows = board_rows(t.spec)
    bad: list[str] = []
    if not 1 <= len(rows) <= 10:
        bad.append(f"{len(rows)} boards")
    light = sum(1 for r in rows if len(r) > 3 and r[3] == "light")
    if light * 3 > len(rows):
        bad.append(f"{light} light boards of {len(rows)}")
    for r in rows:
        status = r[-1]
        if status == "PENDING":
            continue
        m = re.fullmatch(
            r"drawn: board id `[0-9a-f-]{36}`, `(docs/design/E47/img/E47-D03-\d\d-[a-z0-9-]+\.png)`"
            r" \((\d+) × (\d+)\)",
            status,
        )
        if not m or png_size(m.group(1)) != (int(m.group(2)), int(m.group(3))):
            bad.append(f"board {r[0]} status {status!r}")
    return [("G-BOARDS", "; ".join(bad), "spec", region)] if bad else []


def theme_label(key: str) -> str:
    return key.split("/")[0]


def bars(cell: str) -> dict[str, float]:
    nums = re.findall(r"(hc )?(\d+(?:\.\d+)?)", plain(cell))
    out: dict[str, float] = {}
    for hc, n in nums:
        if hc:
            out["hc"] = float(n)
        else:
            out.setdefault("*", float(n))
    return out


def bar_for(theme: str, bs: dict[str, float]) -> float:
    return bs.get(theme.rstrip("+"), bs.get("*", 4.5)) if theme.startswith("hc") else bs["*"]


def verdict_ok(verdict: str, failing: list[str]) -> bool:
    v = plain(verdict)
    if not failing:
        return v.startswith("pass")
    m = re.match(r"fails ([a-z+, ]+?) → (D03-[ADCG]\d+|exempt)", v)
    if not m:
        return False
    return sorted(x.strip() for x in m.group(1).split(",")) == sorted(failing)


def measured_rows(text: str, prefixes: tuple[str, ...]) -> list[tuple[str, list[str], list[str]]]:
    out: list[tuple[str, list[str], list[str]]] = []
    for p in prefixes:
        _, _, region = section(text, p)
        for tb in tables(text, p):
            out.extend((region, tb[0], row) for row in tb[1:])
    return out


def g_bar(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for region, head, row in measured_rows(t.spec, ("## 3.", "## 9.")):
        bi, vi = col(head, "Bar"), col(head, "Verdict")
        if bi < 0 or vi < 0 or len(row) <= max(bi, vi):
            continue
        bs = bars(row[bi])
        failing = []
        for cell in row:
            for _, kind, key in anchors(cell):
                if kind == "CR" and raw_cr(key) < bar_for(theme_label(key), bs):
                    failing.append(theme_label(key))
        if not verdict_ok(row[vi], sorted(set(failing))):
            out.append(
                ("G-BAR", f"{plain(row[0])}: verdict vs {sorted(set(failing))}", "spec", region)
            )
    return out


def g_aaa(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for region, head, row in measured_rows(t.spec, ("### 3.5",)):
        mi = col(head, "Met in")
        if mi < 0 or len(row) <= mi:
            continue
        met = [
            theme_label(k)
            for c in row
            for _, kind, k in anchors(c)
            if kind == "CR" and raw_cr(k) >= 7.0
        ]
        want = ", ".join(met) if met else "none"
        if plain(row[mi]) != want:
            out.append(("G-AAA", f"{plain(row[0])}: Met in should read {want}", "spec", region))
    return out


def g_cvd(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for region, head, row in measured_rows(t.spec, ("### 7.2",)):
        ci = col(head, "Cue")
        if ci < 0 or len(row) <= ci:
            continue
        vals = [raw_de(k) for c in row for _, kind, k in anchors(c) if kind == "DE"]
        cue = plain(row[ci])
        named = any(re.search(rf"\b{w}\b", cue) for w in CHANNELS)
        if (vals and min(vals) < JND and not named) or (
            cue.startswith("none needed") and vals and min(vals) < JND
        ):
            out.append(
                (
                    "G-CVD",
                    f"{plain(row[0])} {plain(row[1])}: below the JND without a cue",
                    "spec",
                    region,
                )
            )
    return out


def g_ramp(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for region, head, row in measured_rows(t.spec, ("### 7.3",)):
        vi = col(head, "Verdict")
        if vi < 0 or len(row) <= vi:
            continue
        failing = sorted(
            {
                theme_label(k)
                for c in row
                for _, kind, k in anchors(c)
                if kind == "RAMP" and ramp_word(k) != "ordered"
            }
        )
        if not verdict_ok(row[vi], failing):
            out.append(("G-RAMP", f"{plain(row[0])}: verdict vs {failing}", "spec", region))
    return out


def g_accent(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for region, head, row in measured_rows(t.spec, ("### 8.2",)):
        bi, wi = col(head, "Bar"), col(head, "Warning in")
        if bi < 0 or wi < 0 or len(row) <= max(bi, wi):
            continue
        bs = bars(row[bi])
        failing = [
            THEME_WORD[theme_label(k).rstrip("+")]
            for c in row
            for _, kind, k in anchors(c)
            if kind == "ACC" and raw_acc(k) < bar_for(theme_label(k), bs)
        ]
        want = ", ".join(failing) if failing else "none"
        if plain(row[wi]) != want:
            out.append(
                ("G-ACCENT", f"{plain(row[0])}: Warning in should read {want}", "spec", region)
            )
    return out


def g_enc(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 5.")
    rows = first_table(t.spec, "## 5.")
    if not rows:
        return [("G-ENC", "no encoding table", "spec", region)]
    head = rows[0]
    ei, si, hi, di = (
        col(head, "Encoding"),
        col(head, "Surface"),
        col(head, "Shipped"),
        col(head, "Designed"),
    )
    have = {(plain(r[ei]), plain(r[si])): r for r in rows[1:] if len(r) > max(ei, si, hi, di)}
    bad: list[str] = []
    for enc, surfaces in encodings().items():
        for surface, chans in surfaces.items():
            r = have.get((enc, surface))
            if r is None:
                bad.append(f"{enc} / {surface} missing")
            elif plain(r[hi]) != ", ".join(chans):
                bad.append(f"{enc} / {surface} shipped channels differ")
    for (enc, surface), r in have.items():
        designed = [x.strip() for x in plain(r[di]).split(",") if x.strip()]
        shipped = [x.strip() for x in plain(r[hi]).split(",") if x.strip() and x.strip() != "—"]
        if not designed or not set(designed) <= set(CHANNELS) or not set(shipped) <= set(designed):
            bad.append(f"{enc} / {surface} designed channels")
    return [("G-ENC", "; ".join(bad[:3]), "spec", region)] if bad else []


def g_d02(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 11.")
    rows = first_table(t.spec, "## 11.")[1:]
    got = {plain(r[0]): plain(r[1]) for r in rows if len(r) > 1}
    if got != routed():
        return [("G-D02", f"{len(got)} rows vs the register's {len(routed())}", "spec", region)]
    return []


def g_exempt(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "### 4.2")
    rows = first_table(t.spec, "### 4.2")[1:]
    bad: list[str] = []
    got = {plain(r[0]): r for r in rows if len(r) > 4}
    if set(got) != set(pair_exemptions()):
        bad.append(f"{len(got)} rows vs {len(pair_exemptions())} pair exemptions")
    for pair, r in got.items():
        if pair not in pair_exemptions():
            continue
        _, now, bar = exemption_now(pair)
        cls = plain(r[3])
        if (cls == "stale") != (now >= bar) or cls not in ("stale", "standing", "retune"):
            bad.append(f"{pair} class {cls}")
        if cls == "retune" and not re.search(r"D03-D\d+", r[4]):
            bad.append(f"{pair} retune without a D-row")
    return [("G-EXEMPT", "; ".join(bad[:3]), "spec", region)] if bad else []


def g_heur(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 14.")
    bad = [r[0] for r in first_table(t.spec, "## 14.")[1:] if "(heuristic)" not in r[1]]
    return [("G-HEUR", f"{bad} lack (heuristic)", "spec", region)] if bad else []


def g_walk(t: Texts) -> list[Finding]:
    n = section_text(t.hand, "## §E").count("\n- [ ]")
    return [("G-WALK", f"{n} walkthrough items", "hand", "§E")] if not 1 <= n <= 10 else []


def g_owner(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for prefix in ("### 16.2", "## 11."):
        _, _, region = section(t.spec, prefix)
        rows = first_table(t.spec, prefix)
        if not rows:
            continue
        oi = col(rows[0], "Owner")
        for r in rows[1:]:
            if oi < len(r) and (AGENT_RE.search(r[oi]) or not OWNER_OK_RE.search(r[oi])):
                out.append(("G-OWNER", f"{plain(r[0])} owner {r[oi]!r}", "spec", region))
    return out


def g_url(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for doc, i, line, region in per_line(t):
        if URL_RE.search(line) or any(p in line for p in UNMERGED_PATHS):
            out.append(
                ("G-URL", f"a URL, host, local path or unmerged file on line {i + 1}", doc, region)
            )
    return out


def g_untouched(t: Texts) -> list[Finding]:
    bad = [
        p
        for p in t.changed
        if p not in OWN and not OWN_BOARDS.match(p) and not OWN_KIT.match(p) and p != PLAN["14"]
    ]
    if PLAN["14"] in t.changed and (len(t.d14) != 1 or not t.d14[0].startswith("+" + POINTER_14)):
        bad.append(f"{PLAN['14']} beyond one pointer line")
    return [("G-UNTOUCHED", f"{bad}", "changed", "-")] if bad else []


def g_budget(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for doc, cap in (("spec", SPEC_BUDGET), ("hand", HAND_BUDGET)):
        n = len(t.doc(doc).rstrip("\n").split("\n"))
        if n > cap:
            out.append(("G-BUDGET", f"{n} lines > {cap}", doc, "-"))
    return out


def g_mutlist(t: Texts) -> list[Finding]:
    rows = first_table(t.spec, "## 15.")[1:]
    want = [[m.mid, m.what, m.gate] for m in MUTATIONS]
    if [[plain(c) for c in r] for r in rows] != [[plain(c) for c in r] for r in want]:
        return [("G-MUTLIST", "§15 differs from the tool's mutation list", "spec", "§15")]
    return []


def findings(t: Texts, values: Values) -> list[Finding]:
    out: list[Finding] = []
    for g in (
        g_marker,
        g_cite,
        g_quote,
        g_arow,
        g_diff,
        g_pending,
        g_ruled,
        g_boards,
        g_bar,
        g_aaa,
        g_cvd,
        g_ramp,
        g_accent,
        g_enc,
        g_d02,
        g_exempt,
        g_heur,
        g_walk,
        g_owner,
        g_url,
        g_untouched,
        g_budget,
        g_mutlist,
    ):
        out.extend(g(t))
    out.extend(g_anchor(t, values))
    return out


GATES = (
    "G-ANCHOR",
    "G-MARKER",
    "G-CITE",
    "G-QUOTE",
    "G-AROW",
    "G-DIFF",
    "G-PENDING",
    "G-RULED",
    "G-BOARDS",
    "G-BAR",
    "G-AAA",
    "G-CVD",
    "G-RAMP",
    "G-ACCENT",
    "G-ENC",
    "G-D02",
    "G-EXEMPT",
    "G-HEUR",
    "G-WALK",
    "G-OWNER",
    "G-URL",
    "G-UNTOUCHED",
    "G-BUDGET",
    "G-MUTLIST",
)


def failing_gates(fs: list[Finding]) -> list[str]:
    return sorted({f[0] for f in fs})


def report(fs: list[Finding]) -> list[str]:
    lines: list[str] = []
    for gate in GATES:
        mine = [f for f in fs if f[0] == gate]
        if mine:
            first = mine[0]
            lines.append(f"FAIL {gate} ({len(mine)}): {first[1]} [{first[2]} {first[3]}]")
        else:
            lines.append(f"ok   {gate}")
    return [ln.encode("ascii", "replace").decode("ascii") for ln in lines]


# ---------------------------------------------------------------------------- modes


def read_texts() -> Texts:
    return Texts(
        spec=(ROOT / SPEC_REL).read_text(encoding="utf-8"),
        hand=(ROOT / HAND_REL).read_text(encoding="utf-8"),
        changed=changed_paths(),
        d14=diff_14(),
    )


def fill(t: Texts) -> Texts:
    values = compute_values(t)

    def sub(text: str) -> str:
        text = text.replace("{{MUTATIONS}}", mutation_rows())

        def one(m: re.Match[str]) -> str:
            key = f"{m.group(1)}:{m.group(2)}"
            if key not in values:
                raise SystemExit(f"FAIL --fill: no value for {key}")
            return f"{values[key]}<!--={key}-->"

        text = PLACEHOLDER_RE.sub(one, text)
        return ANCHOR_RE.sub(
            lambda m: f"{values.get(m.group(2) + ':' + m.group(3), m.group(1))}<!--={m.group(2)}:{m.group(3)}-->",
            text,
        )

    return replace(t, spec=sub(t.spec), hand=sub(t.hand))


def check(do_fill: bool) -> int:
    t = read_texts()
    if do_fill:
        t = fill(t)
        (ROOT / SPEC_REL).write_text(t.spec, encoding="utf-8")
        (ROOT / HAND_REL).write_text(t.hand, encoding="utf-8")
    fs = findings(t, compute_values(t))
    for ln in report(fs):
        print(ln)
    print(f"FAIL {len(failing_gates(fs))}")
    return 1 if fs else 0


def digest() -> str:
    h = hashlib.sha256()
    for rel in (SPEC_REL, HAND_REL, PIN_REL):
        p = ROOT / rel
        h.update(p.read_bytes() if p.exists() else b"")
    return h.hexdigest()


def self_test() -> int:
    before = digest()
    problems: list[str] = []
    for (src, sim), want in SIM_PINS.items():
        if simulate(src, sim) != want:
            problems.append(f"port: {src} {sim} gives {simulate(src, sim)}, pinned {want}")
    base = read_texts()
    values = compute_values(base)
    if findings(base, values):
        print("FAIL the baseline is not clean; run --check")
        return 1
    for m in MUTATIONS:
        got = failing_gates(findings(apply_mutation(base, m), values))
        status = "ok  " if got == [m.gate] else "FAIL"
        if got != [m.gate]:
            problems.append(f"{m.mid} wants [{m.gate}], got {got}")
        print(f"{status} {m.mid} {m.gate}: {m.what}".encode("ascii", "replace").decode("ascii"))
    if digest() != before:
        problems.append("the texts on disk changed")
    for p in problems:
        print(f"FAIL {p}".encode("ascii", "replace").decode("ascii"))
    print("self-test ok" if not problems else f"self-test FAIL {len(problems)}")
    return 1 if problems else 0


def repin() -> int:
    t = read_texts()
    if PLACEHOLDER_RE.search(t.spec) or "{{" in t.spec:
        print("FAIL --repin-ruled refuses while a placeholder is unfilled")
        return 1
    bullets = bq_bullets(t.spec)
    head = (
        "# E47-D03 pins: the BQ bullets of the spec, verbatim, in order; "
        f"{len(bullets)} lines.\n"
        "# Written by `--repin-ruled` only; `--check` reads it (never hand-edit; G-RULED).\n"
    )
    (ROOT / PIN_REL).write_text(head + "\n".join(bullets) + "\n", encoding="utf-8")
    print(f"pinned {len(bullets)} BQ bullets")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--repin-ruled", action="store_true")
    ap.add_argument("--fill", action="store_true", help="with --check: write values first")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.repin_ruled:
        return repin()
    return check(args.fill)


if __name__ == "__main__":
    sys.exit(main())
