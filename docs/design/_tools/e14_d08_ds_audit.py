#!/usr/bin/env python3
"""E14-D08 (#352) audit: the design-system pack for the drawing primitives.

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads AS
TEXT at the pinned base (`git merge-base HEAD origin/main`, via `git show BASE:<path>`) the plan
texts (`05`, `11`, `14`, `15`, `16`, `21`, `22`, `26`), the merged E14 design docs (D02 ... D07 and
their hand-offs), E13-D03, E11-D05, E37-D03, E12-D09, the token JSON (`themes.json` layering:
dark = primitives + semantic-dark, light = + semantic-light, hc = + semantic-hc), `pairs.mjs`, the
engine export prefixes and the CVD script; then the pack (`E14-D08.md`), its hand-off
(`E14-D08-handoff.md`) and the pins from the working tree.

Gates (at least one mutation each in `--self-test`; the pins gate besides):
  (a) G-LEDGER    the A-row ledger re-pinned by content: every row of record's cited line carries
                  its id at the base; dispositions from the ruled set; counts computed; every C-n /
                  G-n / L-n a disposition cites exists and shares a cite or a name with the row;
                  A-1 is dropped once `15` §0.1 at `origin/main` declares the optional fields.
  (b) G-TOKEN     the token-proposal table: every target resolves in the three themes (TP-1 ... TP-8
                  through E13-D03 CR-1's primitives), no alias already shipped, the resolved hex
                  computed; the five parents' token tables hold no name that is neither shipped
                  nor a proposal row nor a cited proposal; the status-hue collisions are the two
                  recorded ones; every colour an `engine` row of §3 or A-6's Tokens cell binds is
                  an `ENGINE_CATEGORY_PREFIXES` name (BQ-04), the fallback clauses exempt.
  (c) G-CONTRAST  every pair of §8 and §7 unrounded in three themes, gated vs decorative per row,
                  the `PAIRS` column a read-only cross-check of `tools/contrast/pairs.mjs`.
  (d) G-CVD       the V-rows via `docs/design/_tools/cvd_sim.py`'s swatch math (Rec. 601 grey,
                  the Machado matrices in sRGB), the matrices asserted equal to the script's.
  (e) G-HANDLE    the handle arithmetic of §6 and the forbidden-treatments sentence.
  (f) G-STORIES   the Storybook unions: A-10 covers `15`'s six, D05 §12.1's eighteen, D06H's
                  PositionTool and the thirteen added; A-17 equals D03 §11's eighteen and covers
                  `15`'s four; the band strings.
  (g) G-ENTRY     every field bullet in a New cell is declared (`15` §0.1, E09-D07 A-1's four, the
                  E37-D03 Motion / Usage lead-ins); the hand-off's checklists carry `16` §11.4's
                  lines in order with evidence; table 1 covers the stories; the ledger-by-component
                  table equals the derivation from §2 and §C.
  (h) G-HYGIENE   placeholders filled and re-derived, no `{{` left anywhere (code spans included),
                  every §C Old cell equal to its line at the base (a code line after stripping),
                  every cite in range and non-blank at the base, `git diff` against the merge-base
                  empty outside the pack (PR 1) or equal to `15` + the `14` line with §C applied
                  (PR 2), no closing keyword, no hex outside an anchor, no local path, no agent
                  name, no URL or Penpot host, the mutation list equal to the tool's.
  G-RULED-PIN     a default-deny pin set over every unit of the pack and the hand-off
                  (`e14_d08_ruled_pins.txt`); `--repin-ruled` is the only writer.

Usage (from the repo root):
  python3 -I docs/design/_tools/e14_d08_ds_audit.py --check [--json] [--fill]
  python3 -I docs/design/_tools/e14_d08_ds_audit.py --json          (= --check --json)
  python3 -I docs/design/_tools/e14_d08_ds_audit.py --self-test
  python3 -I docs/design/_tools/e14_d08_ds_audit.py --repin-ruled
  python3 -I docs/design/_tools/e14_d08_ds_audit.py --a-rows
Exit 0 = no FAIL; 1 = at least one FAIL. The `--json` dump carries values and findings only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC_REL = "docs/design/E14/E14-D08.md"
HAND_REL = "docs/design/E14/E14-D08-handoff.md"
PINS_REL = "docs/design/_tools/e14_d08_ruled_pins.txt"
TOOL_REL = "docs/design/_tools/e14_d08_ds_audit.py"
OWN_PATHS = (SPEC_REL, HAND_REL, PINS_REL, TOOL_REL)
CAT_REL = "docs/plan/15-component-catalogue.md"
SCR_REL = "docs/plan/14-screens-catalogue.md"
DS_SRC = "packages/ui/tokens"
PAIRS_REL = "tools/contrast/pairs.mjs"
RGBA_REL = "tools/style-dictionary/formats/json-flat-rgba.js"
CVD_REL = "docs/design/_tools/cvd_sim.py"
PATHS: dict[str, str] = {
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": SCR_REL,
    "15": CAT_REL,
    "16": "docs/plan/16-design-system-brief.md",
    "21": "docs/plan/21-database-schema.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "26": "docs/plan/26-chart-engine-design.md",
    "D02": "docs/design/E14/E14-D02.md",
    "D03": "docs/design/E14/E14-D03.md",
    "D03H": "docs/design/E14/E14-D03-handoff.md",
    "D04": "docs/design/E14/E14-D04.md",
    "D04H": "docs/design/E14/E14-D04-handoff.md",
    "D05": "docs/design/E14/E14-D05.md",
    "D05H": "docs/design/E14/E14-D05-handoff.md",
    "D06": "docs/design/E14/E14-D06.md",
    "D06H": "docs/design/E14/E14-D06-handoff.md",
    "D07": "docs/design/E14/E14-D07.md",
    "E13D03": "docs/design/E13/E13-D03.md",
    "E11D05": "docs/design/E11/E11-D05.md",
    "E37D03": "docs/design/E37/E37-D03.md",
    "E12D09": "docs/design/E12/E12-D09.md",
    "PAIRS": PAIRS_REL,
    "RGBA": RGBA_REL,
    "CVD": CVD_REL,
}
TOKEN_FILES = ("primitives", "semantic-dark", "semantic-light", "semantic-hc")
# the version line's inputs: key -> paths whose last commit at the base is pinned
SHA_INPUTS: dict[str, tuple[str, ...]] = {
    "D02": (PATHS["D02"],),
    "D03": (PATHS["D03"], PATHS["D03H"]),
    "D04": (PATHS["D04"], PATHS["D04H"]),
    "D05": (PATHS["D05"], PATHS["D05H"]),
    "D06": (PATHS["D06"], PATHS["D06H"]),
    "D07": (PATHS["D07"],),
    "15": (CAT_REL,),
    "22": (PATHS["22"],),
    "E13D03": (PATHS["E13D03"],),
    "E11D05": (PATHS["E11D05"],),
    "TOK": tuple(f"{DS_SRC}/{f}.tokens.json" for f in TOKEN_FILES) + (f"{DS_SRC}/themes.json",),
    "CVD": (CVD_REL,),
}
THEMES = ("dark", "light", "hc")
BARS = {"text": 4.5, "non-text": 3.0}
# the parents' token tables scanned by the audit (doc key, heading prefix found by text)
AUDIT_SECTIONS = (("D03", "### 9.3"), ("D04", "### 2.1"), ("D05", "### 10.1"), ("D06", "### 2.1"),
                  ("D07", "### 3.1"))  # fmt: skip
CITED_PROPOSALS = frozenset(
    {"size.stroke.thin", "size.stroke.regular", "size.stroke.bold", "opacity.indicator.fill"}
)
# `15` §0.1's fields, E09-D07 A-1's four (carried by id) and E37-D03 §12's lead-in form
BASE_FIELDS = ("Tier", "Purpose", "Props", "Variants", "States", "A11y", "Tokens", "Storybook",
               "Tests", "API sketch", "Data contract")  # fmt: skip
NEW_FIELDS = ("Forbidden", "Security", "Performance", "Observability")
LEAD_FIELDS = ("Motion (E14-D08)", "Usage (E14-D08)")
# BQ-09's additions to CMP-191's list (the ruled union beyond the parents' lists; `ForcedColors`
# is D05 §12.1's, not an addition)
ADDED_191 = ("Handles", "Selected", "MultiSelected", "Locked", "Hidden", "Unsaved", "Conflict",
             "ViewerReadOnly", "ViewAsReadOnly", "Palette", "TwoHundredDrawings",
             "KeyboardDrawOneAnchor", "KeyboardDrawThreeAnchors")  # fmt: skip
BAND_191 = "`ChartEngine/DrawingToolOverlay`"
BAND_223 = "`Organisms/DrawingToolbar`"
DISPOSITIONS = ("applied", "applied-as-amended", "routed", "held")
HAND_ORDER = ("CMP-191", "CMP-223")
PR3_ONLY = ("Final Penpot link", "Design QA checklist (16 §12)", "Sign-off")
# cvd_sim.py's constants, re-stated here and asserted equal to the script's at the base (G-CVD)
DEUTAN = (
    0.367322,
    0.860646,
    -0.227968,
    0.280085,
    0.672501,
    0.047413,
    -0.011820,
    0.042940,
    0.968881,
)
PROTAN = (
    0.152286,
    1.052583,
    -0.204868,
    0.114503,
    0.786281,
    0.099216,
    -0.003882,
    -0.048116,
    1.051998,
)
GREY = (0.299, 0.587, 0.114)
COLLAPSE = 1.5

PLACEHOLDER = re.compile(r"\{\{([A-Z]+:[^{}]+?)\}\}")
ANCHORED = re.compile(r"([^\s<|]+)<!--=([A-Z]+:[^>]+?)-->")
CODE = re.compile(r"`[^`\n]*`")
HEADING = re.compile(r"^(#{1,6}) (.+)$")
RULE = re.compile(r"^\s*\|?\s*:?-{3,}")
HEX = re.compile(r"#[0-9A-Fa-f]{6}\b")
TOKEN_NAME = re.compile(
    r"^(?:color|size|space|radius|type|opacity|border|elevation|font|dash|glyph|pattern|motion)"
    r"\.[a-z0-9.\-]+$"
)
CITE = re.compile(
    r"(?:`([0-9]{2})`|\b(D0[2-7]H?|E1[13]D0[35]|E37D03|E12D09|PAIRS|RGBA|CVD))"
    r":(\d+)(?:[–-](\d+))?"
)
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE)
# assembled, so the deny pattern never spells the strings it refuses
LOCAL_PATH = re.compile("/" + "home/|/Users/|[A-Za-z]:\\\\|\\bwt-" + "notes\\b")
AGENT_NAME = re.compile(r"\b[a-z]{2,4}-worker-\d\b")
URL_OR_HOST = re.compile(r"https?://|penpot\.[a-z]|team-id=|file-id=", re.IGNORECASE)


# ---------------------------------------------------------------------------- git


@dataclass
class Env:
    base: str
    memo: dict[str, object]

    def show(self, rev: str, rel: str) -> str | None:
        key = f"show:{rev}:{rel}"
        if key not in self.memo:
            self.memo[key] = git_raw("show", f"{rev}:{rel}")
        v = self.memo[key]
        return v if isinstance(v, str) else None

    def at_base(self, rel: str) -> str:
        t = self.show(self.base, rel)
        if t is None:
            raise SystemExit(f"{rel} is missing at the base {self.base[:10]}")
        return t


def git_raw(*args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=False)
    except OSError:
        return None
    return r.stdout.decode("utf-8", "surrogateescape") if r.returncode == 0 else None


def merge_base() -> str | None:
    out = git_raw("merge-base", "HEAD", "origin/main")
    return out.strip() if out and re.fullmatch(r"[0-9a-f]{40}\s*", out) else None


def changed_paths(base: str) -> list[str] | None:
    """Committed and uncommitted paths that differ from the merge-base; None when git fails."""
    a = git_raw("diff", "--name-only", base)
    b = git_raw("status", "--porcelain", "--untracked-files=all")
    if a is None or b is None:
        return None
    out = {p for p in a.split("\n") if p}
    for ln in b.split("\n"):
        if len(ln) > 3:
            out.add(ln[3:].split(" -> ")[-1].strip('"'))
    return sorted(out)


def read_raw(rel: str) -> str:
    with open(ROOT / rel, encoding="utf-8", newline="") as f:
        return f.read()


def write_text(rel: str, text: str) -> None:
    with open(ROOT / rel, "w", encoding="utf-8", newline="") as f:
        f.write(text)


# ---------------------------------------------------------------------------- text helpers


def lines_of(text: str) -> list[str]:
    return text.split("\n")


def split_row(line: str) -> list[str]:
    body = line.strip().removeprefix("|")
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", body)]


def unescape(cell: str) -> str:
    return cell.replace("\\|", "|")


def tables(block: str) -> list[list[list[str]]]:
    out: list[list[list[str]]] = []
    cur: list[list[str]] = []
    for ln in lines_of(block):
        if ln.lstrip().startswith("|"):
            if RULE.match(ln):
                continue
            cur.append(split_row(ln))
        elif cur:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def table_after(block: str, header0: str) -> list[list[str]]:
    for t in tables(block):
        if t and t[0] and t[0][0] == header0:
            return t[1:]
    return []


def section(text: str, head_prefix: str) -> str:
    """The block from the heading starting with `head_prefix` to the next heading of the same or
    a higher level."""
    ls = lines_of(text)
    for i, ln in enumerate(ls):
        m = HEADING.match(ln)
        if m and ln.startswith(head_prefix + " ") or (m and ln == head_prefix):
            level = len(m[1])
            j = i + 1
            while j < len(ls):
                m2 = HEADING.match(ls[j])
                if m2 and len(m2[1]) <= level:
                    break
                j += 1
            return "\n".join(ls[i:j])
    return ""


def without_code(text: str) -> str:
    return CODE.sub("`…`", text)


def strip_anchors(text: str) -> str:
    return re.sub(r"<!--=[A-Z]+:[^>]+?-->", "", text)


# ---------------------------------------------------------------------------- colour math


def rgb(hex6: str) -> tuple[int, int, int]:
    h = hex6.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def lin(c: int) -> float:
    v = c / 255
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def luminance(hex6: str) -> float:
    r, g, b = (lin(c) for c in rgb(hex6))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def show_ratio(r: float) -> str:
    """Two decimals, truncated: never rounded up across a bar."""
    return f"{math.floor(r * 100 + 1e-9) / 100:.2f}"


def clip_byte(v: float) -> int:
    return max(0, min(255, round(v)))


def simulate(hex6: str, sim: str) -> str:
    """`cvd_sim.py`'s swatch math: Rec. 601 luma for grey; the Machado matrices applied to the
    sRGB bytes (no linearisation, as the script does), clipped to 0..255."""
    r, g, b = rgb(hex6)
    if sim == "grey":
        y = clip_byte(r * GREY[0] + g * GREY[1] + b * GREY[2])
        return f"#{y:02X}{y:02X}{y:02X}"
    m = DEUTAN if sim == "deut" else PROTAN
    out = (
        m[0] * r + m[1] * g + m[2] * b,
        m[3] * r + m[4] * g + m[5] * b,
        m[6] * r + m[7] * g + m[8] * b,
    )
    return "#" + "".join(f"{clip_byte(c):02X}" for c in out)


def cvd_src_problems(env: Env) -> list[str]:
    src = env.at_base(CVD_REL)
    bad: list[str] = []

    def nums(name: str) -> tuple[float, ...]:
        m = re.search(rf"^{name} = np\.array\(\s*\[(.*?)\]\s*\)", src, re.MULTILINE | re.DOTALL)
        return tuple(float(x) for x in re.findall(r"-?\d+\.\d+", m[1])) if m else ()

    if nums("DEUTERANOPIA_MATRIX") != DEUTAN:
        bad.append(f"DEUTERANOPIA_MATRIX differs from {CVD_REL} at the base")
    if nums("PROTANOPIA_MATRIX") != PROTAN:
        bad.append(f"PROTANOPIA_MATRIX differs from {CVD_REL} at the base")
    grey = tuple(
        float(x) for x in re.findall(r"\* (0\.\d+)", src.split("def to_greyscale", 1)[-1][:300])
    )
    if grey != GREY:
        bad.append(f"the Rec. 601 weights differ from {CVD_REL} at the base")
    return bad


# ---------------------------------------------------------------------------- tokens


def token_file(env: Env, name: str) -> dict[str, object]:
    data = json.loads(env.at_base(f"{DS_SRC}/{name}.tokens.json"))
    return data if isinstance(data, dict) else {}


def layering(env: Env) -> dict[str, tuple[str, ...]]:
    data = json.loads(env.at_base(f"{DS_SRC}/themes.json"))
    out: dict[str, tuple[str, ...]] = {}
    for th in data.get("themes", []) if isinstance(data, dict) else []:
        if isinstance(th, dict) and th.get("group") == "theme":
            name = {"high-contrast": "hc"}.get(str(th.get("name")), str(th.get("name")))
            out[name] = tuple(str(x) for x in th.get("sets", []))
    return out


def theme(env: Env, name: str) -> dict[str, str]:
    key = f"theme:{name}"
    if key not in env.memo:
        merged: dict[str, str] = {}
        for f in layering(env).get(name, ()):
            for k, v in token_file(env, f).items():
                if isinstance(v, dict) and "$value" in v:
                    merged[k] = v["$value"] if isinstance(v["$value"], str) else "(composite)"
        env.memo[key] = merged
    out = env.memo[key]
    return out if isinstance(out, dict) else {}


def shipped_names(env: Env) -> frozenset[str]:
    out: set[str] = set()
    for t in THEMES:
        out |= set(theme(env, t))
    return frozenset(out)


def e13_slots(env: Env) -> dict[str, dict[str, str]]:
    """`color.indicator.palette.N` -> {theme: `{primitive}`} from E13-D03 CR-1 at the base
    (hc inherits dark, E13-D03 §3.1)."""
    key = "e13slots"
    if key not in env.memo:
        row = next((ln for ln in lines_of(env.at_base(PATHS["E13D03"]))
                    if ln.startswith("| CR-1 ")), "")  # fmt: skip
        out: dict[str, dict[str, str]] = {}
        for n, d, lt in re.findall(
            r"`(?:color\.indicator\.palette\.|\.)(\d) = (\{[^}]+\})` / (?:light )?`(\{[^}]+\})`",
            row,
        ):
            out[f"color.indicator.palette.{n}"] = {"dark": d, "light": lt, "hc": d}
        env.memo[key] = out
    v = env.memo[key]
    return v if isinstance(v, dict) else {}


def e11_aliases(env: Env) -> dict[str, dict[str, str]]:
    """E11-D05 §4.1b's engine-chrome aliases: name -> {theme: `{target}`} (one target, all three)."""
    key = "e11aliases"
    if key not in env.memo:
        out: dict[str, dict[str, str]] = {}
        for r in table_after(section(env.at_base(PATHS["E11D05"]), "### 4.1b"), "Alias"):
            if len(r) > 1 and r[0].startswith("`color.chart."):
                tgt = r[1].strip("`")
                out[r[0].strip("`")] = {t: tgt for t in THEMES}
        out.setdefault("color.chart.pane.bg.default", {t: "{color.surface.canvas}" for t in THEMES})
        env.memo[key] = out
    v = env.memo[key]
    return v if isinstance(v, dict) else {}


def tp_rows(spec: str) -> list[list[str]]:
    return [r for r in table_after(section(spec, "### 4.1"), "Id") if r and r[0].startswith("TP-")]


def tp_targets(spec: str) -> dict[str, dict[str, str]]:
    """TP alias -> {theme: `{target}`} from §4.1 (one target in all three themes)."""
    out: dict[str, dict[str, str]] = {}
    for r in tp_rows(spec):
        m = re.match(r"`(\{[^}]+\})`", r[2])
        if m:
            out[r[1].strip("`")] = {t: m[1] for t in THEMES}
    return out


def resolve_any(env: Env, spec: str, t: str, name: str, depth: int = 0) -> str | None:
    """A hex, through the shipped tokens, then the pack's TP rows, E13-D03's slots and E11-D05's
    aliases; None when nothing resolves."""
    if depth > 24:
        return None
    m = re.fullmatch(r"\{([^{}]+)\}", name)
    if m:
        name = m[1]
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", name):
        return name.upper()
    v = theme(env, t).get(name)
    if v is not None:
        return resolve_any(env, spec, t, v, depth + 1)
    for table in (tp_targets(spec), e13_slots(env), e11_aliases(env)):
        if name in table:
            return resolve_any(env, spec, t, table[name][t], depth + 1)
    return None


# ---------------------------------------------------------------------------- cites


def cites_in(text: str) -> list[tuple[str, int, int]]:
    out = []
    for ln in lines_of(text):
        for m in CITE.finditer(ln):
            key = m[1] or m[2]
            if key in PATHS:
                a = int(m[3])
                out.append((key, a, int(m[4]) if m[4] else a))
    return out


def cite_problems(env: Env, text: str) -> list[str]:
    bad: list[str] = []
    seen: set[tuple[str, int, int]] = set()
    for key, a, b in cites_in(text):
        if (key, a, b) in seen:
            continue
        seen.add((key, a, b))
        ls = lines_of(env.at_base(PATHS[key]))
        if b < a or b > len(ls):
            bad.append(f"{key}:{a}–{b} is past the end of the file ({len(ls)} lines)")
            continue
        for n in (a, b):
            if not ls[n - 1].strip():
                bad.append(f"{key}:{n} is a blank line")
    return bad


# ---------------------------------------------------------------------------- the pack's rows


def sec(spec: str, prefix: str) -> str:
    return section(spec, prefix)


def ledger_rows(spec: str) -> list[list[str]]:
    return [r for r in table_after(sec(spec, "## 2."), "L") if r and r[0].startswith("L-")]


def c_rows(spec: str) -> list[list[str]]:
    return [r for r in table_after(sec(spec, "## §C"), "A") if r and r[0].startswith("A-")]


def a_row(spec: str, aid: str) -> list[str] | None:
    return next((r for r in c_rows(spec) if r[0] == aid), None)


def new_of(spec: str, aid: str) -> str:
    r = a_row(spec, aid)
    return strip_anchors(unescape(r[5])) if r and len(r) > 5 else ""


def p_rows(spec: str) -> list[list[str]]:
    return [r for r in table_after(sec(spec, "## 8."), "P") if r and r[0].startswith("P-")]


def v_rows(spec: str) -> list[list[str]]:
    return [r for r in table_after(sec(spec, "## 8."), "V") if r and r[0].startswith("V-")]


def stories_of(new: str) -> list[str]:
    body = new.split("):", 1)[-1] if "**Storybook**" in new else new
    body = body.split("(", 1)[0]
    return [s.strip() for s in body.split(":", 1)[-1].strip().rstrip(".").split(",") if s.strip()]


def a_ids(cell: str) -> list[str]:
    """`A-2 … A-12`, `A-14, A-15`, `A-21` -> the ids."""
    out: list[str] = []
    for part in re.split(r",\s*", cell):
        m = re.fullmatch(r"A-(\d+) … A-(\d+)", part.strip())
        if m:
            out += [f"A-{i}" for i in range(int(m[1]), int(m[2]) + 1)]
        elif re.fullmatch(r"A-\d+", part.strip()):
            out.append(part.strip())
    return out


# ---------------------------------------------------------------------------- computed values

P_SPEC = re.compile(r"`([a-z0-9.\-]+)`")


def sha_of(env: Env, paths: tuple[str, ...]) -> str:
    out = git_raw("log", "-1", "--format=%H", env.base, "--", *paths)
    return out.strip()[:10] if out and out.strip() else "unresolved"


def palette_slots(spec: str) -> list[str]:
    return [r[1].strip("`") for r in tp_rows(spec) if re.fullmatch(r"TP-[1-8]", r[0])]


def pair_values(env: Env, spec: str) -> dict[str, str]:
    vals: dict[str, str] = {}
    gated = failing = hc_pass = 0
    for r in p_rows(spec):
        pid = r[0].lower().replace("-", "")
        fg, bg, kind = r[2].strip("`"), r[3].strip("`"), r[4]
        ratios: dict[str, float] = {}
        for t in THEMES:
            a, b = resolve_any(env, spec, t, fg), resolve_any(env, spec, t, bg)
            if a and b:
                ratios[t] = contrast(a, b)
                vals[f"CONTRAST:{pid}.{t}"] = show_ratio(ratios[t])
        if kind in BARS:
            gated += 1
            below = [t for t in THEMES if t in ratios and ratios[t] < BARS[kind]]
            if below:
                failing += 1
            if "hc" in ratios and ratios["hc"] >= BARS[kind]:
                hc_pass += 1
            reading = (
                "meets"
                if not below
                else "below: " + ", ".join({"hc": "high contrast"}.get(t, t) for t in below)
            )
        else:
            reading = "reported"
        vals[f"PAIR:{pid}"] = f"`{reading}`"
    vals["COUNT:pairs"] = str(len(p_rows(spec)))
    vals["COUNT:pairs.gated"] = str(gated)
    vals["COUNT:pairs.failing"] = str(failing)
    vals["COUNT:pairs.hc.gated"] = str(hc_pass)
    # C-25's row: `color.border.strong` on `color.surface.raised`
    for t in THEMES:
        a, b = resolve_any(env, spec, t, "color.border.strong"), resolve_any(
            env, spec, t, "color.surface.raised"
        )
        if a and b:
            vals[f"CONTRAST:p23.{t}"] = show_ratio(contrast(a, b))
    return vals


def palette_values(env: Env, spec: str) -> dict[str, str]:
    vals: dict[str, str] = {}
    lo = 99.0
    excluded = 0
    canvas = {t: resolve_any(env, spec, t, "color.surface.canvas") for t in THEMES}
    for i, r in enumerate(tp_rows(spec), 1):
        tid = r[0].lower().replace("-", "")
        alias = r[1].strip("`")
        for t in THEMES:
            hx = resolve_any(env, spec, t, alias)
            if hx:
                vals[f"HEX:{tid}.{t}"] = hx
        if re.fullmatch(r"TP-[1-8]", r[0]):
            rs = [contrast(resolve_any(env, spec, t, alias) or "#000000", canvas[t] or "#000000")
                  for t in ("dark", "light")]  # fmt: skip
            lo = min(lo, *rs)
            if min(rs) < BARS["non-text"]:
                excluded += 1
    vals["COUNT:palette.excluded"] = str(excluded)
    vals["CONTRAST:palette.min"] = show_ratio(lo)
    vals["COUNT:tp"] = str(len(tp_rows(spec)))
    # label ink per colour and theme (§7)
    for label, name in [("default", "color.drawing.default")] + [
        (f"tp{i}", f"color.drawing.palette.{i}") for i in range(1, 9)
    ]:
        for t in THEMES:
            hx = resolve_any(env, spec, t, name)
            if hx and canvas[t]:
                vals[f"INK:{label}.{t}"] = (
                    "colour" if contrast(hx, canvas[t]) >= 4.5 else "text.primary"
                )
    return vals


V_PAIRS: dict[str, tuple[str, str]] = {
    "v1": ("color.drawing.selected", "color.drawing.default"),
    "v2": ("color.drawing.handle", "color.surface.canvas"),
    "v3": ("color.drawing.locked", "color.surface.canvas"),
    "v4": ("color.position.loss.subtle", "color.position.reward.subtle"),
    "v5": ("color.drawing.handle.active", "color.drawing.selected"),
}


def cvd_values(env: Env, spec: str) -> dict[str, str]:
    vals: dict[str, str] = {}
    for vid, (a, b) in V_PAIRS.items():
        for t in THEMES:
            ha, hb = resolve_any(env, spec, t, a), resolve_any(env, spec, t, b)
            if ha and hb:
                for sim in ("grey", "deut", "prot"):
                    vals[f"CVD:{vid}.{sim}.{t}"] = show_ratio(
                        contrast(simulate(ha, sim), simulate(hb, sim))
                    )
    slots = palette_slots(spec)
    for t in THEMES:
        hexes = [resolve_any(env, spec, t, s) for s in slots]
        if all(hexes):
            for sim in ("grey", "deut", "prot"):
                lo = min(contrast(simulate(x or "", sim), simulate(y or "", sim))
                         for i, x in enumerate(hexes) for y in hexes[i + 1:])  # fmt: skip
                vals[f"CVD:v6.{sim}.{t}"] = show_ratio(lo)
    vals["COUNT:cvd"] = str(len(v_rows(spec)))
    return vals


RESERVED_PREFIX = ("color.status.", "color.env.", "color.position.entry", "color.position.sl",
                   "color.position.tp", "color.order.line")  # fmt: skip


def status_collisions(env: Env, spec: str) -> list[tuple[str, str, str]]:
    """(drawing token, reserved token, theme) sharing one hex in the same theme."""
    out: list[tuple[str, str, str]] = []
    names = ["color.drawing.default", "color.drawing.selected"] + palette_slots(spec)
    for t in THEMES:
        reserved = {
            k: resolve_any(env, spec, t, k) for k in theme(env, t) if k.startswith(RESERVED_PREFIX)
        }
        for n in names:
            hx = resolve_any(env, spec, t, n)
            for k, v in reserved.items():
                if hx and v == hx:
                    out.append((n, k, t))
    return out


def audit_names(env: Env, spec: str) -> tuple[set[str], set[str], set[str]]:
    """(shipped, proposed-or-cited, unlisted) token names bound by the five parents' tables."""
    shipped = shipped_names(env)
    allowed = set(tp_targets(spec)) | set(e13_slots(env)) | set(e11_aliases(env)) | CITED_PROPOSALS
    found: set[str] = set()
    for key, head in AUDIT_SECTIONS:
        block = section(env.at_base(PATHS[key]), head)
        for m in P_SPEC.finditer(block):
            n = re.sub(r"-class$", "", m[1])
            if TOKEN_NAME.match(n) and not n.endswith(".*"):
                found.add(n)
    s = {n for n in found if n in shipped}
    p = {n for n in found - s if n in allowed}
    return s, p, found - s - p


def disposition(cell: str) -> str:
    m = re.match(r"[a-z-]+", cell)
    return m[0] if m else ""


# ---------------------------------------------------------------------------- BQ-04: engine rows


def engine_prefixes(env: Env) -> tuple[str, ...]:
    """`ENGINE_CATEGORY_PREFIXES` as `json-flat-rgba.js` lists them at the base."""
    key = "engine_prefixes"
    if key not in env.memo:
        src = env.at_base(RGBA_REL)
        m = re.search(r"ENGINE_CATEGORY_PREFIXES = \[(.*?)\]", src, re.DOTALL)
        env.memo[key] = tuple(re.findall(r'"([a-z.]+)"', m[1])) if m else ()
    v = env.memo[key]
    return v if isinstance(v, tuple) else ()


def is_engine_name(env: Env, name: str) -> bool:
    return any(name == p.rstrip(".") or name.startswith(p) for p in engine_prefixes(env))


FALLBACK_CLAUSE = re.compile(r"\([^()]*\bfallback\b[^()]*\)")
COLOUR_NAME = re.compile(r"`(color\.[a-z0-9.\-]+)`")


def engine_bound_names(cell: str) -> list[str]:
    """The full colour names a binding cell names outside its fallback clause."""
    return COLOUR_NAME.findall(FALLBACK_CLAUSE.sub("", cell))


def engine_cells(spec: str) -> list[tuple[str, str]]:
    """(where, cell): the colour-binding cell of every `engine` row of §3 and A-6's Tokens cell
    before its metrics clause."""
    out = [
        (f"§3 `{r[0]}`", unescape(r[2]))
        for r in table_after(sec(spec, "## 3."), "Primitive")
        if len(r) > 2 and r[1] == "engine"
    ]
    out.append(("A-6", new_of(spec, "A-6").split("Metrics, never tokens", 1)[0]))
    return out


def count_values(spec: str, hand: str) -> dict[str, str]:
    vals: dict[str, str] = {}
    rows = ledger_rows(spec)
    vals["COUNT:ledger"] = str(len(rows))
    disp = [disposition(r[3]) for r in rows]
    vals["COUNT:ledger.applied"] = str(sum(d == "applied" for d in disp))
    vals["COUNT:ledger.amended"] = str(sum(d == "applied-as-amended" for d in disp))
    vals["COUNT:ledger.routed"] = str(sum(d == "routed" for d in disp))
    vals["COUNT:ledger.held"] = str(sum(d == "held" for d in disp))
    vals["COUNT:arows"] = str(len(c_rows(spec)))
    vals["COUNT:stories.191"] = str(len(stories_of(new_of(spec, "A-10"))))
    vals["COUNT:stories.223"] = str(len(stories_of(new_of(spec, "A-17"))))
    vals["COUNT:mutations"] = str(len(MUTATIONS))
    return vals


def compute(env: Env, spec: str, hand: str) -> dict[str, str]:
    vals: dict[str, str] = {"SHA:BASE": env.base[:10]}
    for k, paths in SHA_INPUTS.items():
        vals[f"SHA:{k}"] = sha_of(env, paths)
    vals.update(pair_values(env, spec))
    vals.update(palette_values(env, spec))
    vals.update(cvd_values(env, spec))
    for g, c in (("g24", 24), ("g8", 8), ("t10", 10)):
        for cell in (12, 10, 6):
            vals[f"HANDLE:{g}.c{cell}"] = f"{c / cell:.2f}"
    vals["COUNT:status.collisions"] = str(len(status_collisions(env, spec)))
    s, p, u = audit_names(env, spec)
    vals["COUNT:audit.names"] = str(len(s | p | u))
    vals["COUNT:audit.shipped"] = str(len(s))
    vals["COUNT:audit.proposed"] = str(len(p))
    vals["COUNT:audit.unlisted"] = str(len(u))
    vals.update(count_values(spec, hand))
    return vals


# ---------------------------------------------------------------------------- placeholders


def code_spans(line: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in CODE.finditer(line)]


def fill(text: str, values: dict[str, str]) -> tuple[str, list[str]]:
    missing: list[str] = []
    out_lines = []
    for ln in text.split("\n"):
        spans = code_spans(ln)

        def ph(m: re.Match[str], spans: list[tuple[int, int]] = spans) -> str:
            if any(a <= m.start() < b for a, b in spans):
                return m[0]
            if m[1] not in values:
                missing.append(m[1])
                return m[0]
            return f"{values[m[1]]}<!--={m[1]}-->"

        out_lines.append(PLACEHOLDER.sub(ph, ln))
    text = "\n".join(out_lines)

    def refresh(m: re.Match[str]) -> str:
        return f"{values[m[2]]}<!--={m[2]}-->" if m[2] in values else m[0]

    return ANCHORED.sub(refresh, text), missing


def unfill(text: str) -> str:
    return ANCHORED.sub(r"<!--=\2-->", text)


def anchored(text: str) -> list[tuple[str, str, int]]:
    out = []
    for i, ln in enumerate(text.split("\n"), 1):
        for m in ANCHORED.finditer(ln):
            out.append((m[1], m[2], i))
    return out


def unfilled(text: str) -> list[str]:
    return [m[1] for ln in lines_of(text) for m in PLACEHOLDER.finditer(without_code(ln))]


# ---------------------------------------------------------------------------- pins

Unit = tuple[str, str, str]
FULL_STOP = re.compile(r"(?<=[.!?])\s+(?=[*`\"(A-Z0-9§])")


def pin_norm(text: str) -> str:
    return " ".join(text.split())


def line_form(line: str) -> str:
    if re.match(r"^\s*[-*+] ", line):
        return "b"
    if re.match(r"^\s*\d+\. ", line):
        return "n"
    return "p"


def units(text: str, doc: str) -> list[Unit]:
    out: list[Unit] = []
    path: list[tuple[int, str]] = []
    seen: dict[str, int] = {}
    region, k, shape = f"{doc}:(top)#1", 0, ""
    rows: dict[str, int] = {}
    for raw in unfill(text).split("\n"):
        m = HEADING.match(raw)
        if m:
            out.append((region, "shape", shape))
            level = len(m[1])
            path = [p for p in path if p[0] < level] + [(level, pin_norm(m[2]))]
            key = f"{doc}:" + " › ".join(p[1] for p in path)
            seen[key] = seen.get(key, 0) + 1
            region, k, shape, rows = f"{key}#{seen[key]}", 0, "h", {}
            out.append((region, "heading", pin_norm(raw)))
            continue
        if not raw.strip():
            shape += "."
        elif RULE.match(raw):
            shape += "r"
            out.append((region, f"rule {shape.count('r')}", pin_norm(re.sub(r"-+", "-", raw))))
        elif raw.lstrip().startswith("|"):
            shape += "t"
            cells = split_row(raw)
            lead = pin_norm(cells[0]) or "(blank)"
            rows[lead] = rows.get(lead, 0) + 1
            loc = f"row {lead}" + (f"#{rows[lead]}" if rows[lead] > 1 else "")
            out.append((region, loc, " | ".join(pin_norm(c) for c in cells)))
        else:
            indent = len(raw) - len(raw.lstrip())
            sents = [x for x in FULL_STOP.split(raw.strip()) if x.strip()]
            shape += (f">{indent}" if indent else "") + f"{line_form(raw)}{len(sents)}"
            for x in sents:
                k += 1
                out.append((region, f"s{k}", pin_norm(x)))
    out.append((region, "shape", shape))
    return out


def all_units(spec: str, hand: str) -> list[Unit]:
    return units(spec, "spec") + units(hand, "hand")


def write_pins(us: list[Unit]) -> str:
    head = (
        "# E14-D08 pins (every unit of the pack and the hand-off): region, location, the exact "
        f"normalised text; {len(us)} units.\n# Written by `--repin-ruled` only; `--check` reads it "
        "(never hand-edit; see the tool's G-RULED-PIN).\n"
    )
    return head + "".join("\t".join(u) + "\n" for u in us)


def parse_pins(text: str) -> list[Unit]:
    out: list[Unit] = []
    for ln in text.split("\n"):
        parts = ln.split("\t")
        if ln and not ln.startswith("#") and len(parts) == 3:
            out.append((parts[0], parts[1], parts[2]))
    return out


def pin_problems(pinned: list[Unit], current: list[Unit]) -> list[str]:
    bad: list[str] = []
    old_r = list(dict.fromkeys(u[0] for u in pinned))
    new_r = list(dict.fromkeys(u[0] for u in current))
    for r in new_r:
        if r not in old_r:
            bad.append(f"region '{r[-60:]}' is unpinned (new)")
    for r in old_r:
        if r not in new_r:
            bad.append(f"region '{r[-60:]}' deleted or renamed")
    common = [r for r in new_r if r in old_r]
    if common != [r for r in old_r if r in new_r]:
        bad.append("a pinned region moved (the heading order changed)")
    for r in common:
        was = [(u[1], u[2]) for u in pinned if u[0] == r]
        now = [(u[1], u[2]) for u in current if u[0] == r]
        if was == now:
            continue
        wd = dict(was)
        what = "units moved or reordered"
        for loc, txt in now:
            if loc not in wd:
                what = f"{loc} unpinned (new): {txt[:40]!r}"
                break
            if wd[loc] != txt:
                what = f"{loc} changed: {txt[:40]!r}"
                break
        else:
            gone = [loc for loc, _ in was if loc not in dict(now)]
            if gone:
                what = f"{gone[0]} deleted"
        bad.append(f"'{r[-48:]}' {what}")
    return bad


# ---------------------------------------------------------------------------- findings


@dataclass(frozen=True)
class Finding:
    level: str
    gate: str
    msg: str


@dataclass(frozen=True)
class Texts:
    env: Env
    spec: str
    hand: str
    pins: str
    cat15: str
    cat14: str
    changed: list[str] | None
    values: dict[str, str]


def one(gate: str, problems: list[str]) -> list[Finding]:
    return [Finding("FAIL", gate, p) for p in problems]


ANCHOR_GATE = (
    ("COUNT:ledger", "G-LEDGER"),
    ("HEX:", "G-TOKEN"), ("COUNT:tp", "G-TOKEN"), ("COUNT:status", "G-TOKEN"), ("COUNT:audit", "G-TOKEN"),
    ("CONTRAST:", "G-CONTRAST"), ("PAIR:", "G-CONTRAST"), ("COUNT:pairs", "G-CONTRAST"),
    ("COUNT:palette", "G-CONTRAST"), ("INK:", "G-CONTRAST"),
    ("CVD:", "G-CVD"), ("COUNT:cvd", "G-CVD"),
    ("HANDLE:", "G-HANDLE"),
    ("COUNT:stories", "G-STORIES"),
)  # fmt: skip


def anchor_gate(key: str) -> str:
    for prefix, gate in ANCHOR_GATE:
        if key.startswith(prefix):
            return gate
    return "G-HYGIENE"


def anchor_problems(t: Texts, gate: str) -> list[str]:
    bad: list[str] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for value, key, ln in anchored(text):
            if anchor_gate(key) != gate:
                continue
            want = t.values.get(key)
            if want is None:
                bad.append(f"{doc}:{ln} anchors `{key}`, which the tool does not compute")
            elif want != value:
                bad.append(f"{doc}:{ln} `{key}` reads {value}; the tool derives {want}")
    return bad


def row_id_form(ident: str) -> str | None:
    return ident if re.fullmatch(r"(?:C|A|G|Q|CR|G-T)-?\d+|G-\d+", ident) else None


def row_terms(cells: list[str]) -> set[str]:
    """The backticked names of ≥ 5 characters in a row (the `NN` doc keys excluded)."""
    return {
        m[1:-1] for c in cells for m in CODE.findall(c) if len(m) >= 7 and not m[1:-1].isdigit()
    }


def same_decision(ledger: list[str], other: list[str]) -> bool:
    """A ledger row and the C- / G-row it cites share a `DOC:line` cite or a backticked name."""
    text = " ".join(other)
    if set(cites_in(" ".join(ledger[:4]))) & set(cites_in(text)):
        return True
    plain = text.replace("`", "")
    return any(term in plain for term in row_terms(ledger[1:4]))


def ref_problems(spec: str, r: list[str]) -> list[str]:
    """Every C-n / G-n a disposition cites exists and names the same decision; `as L-n` exists."""
    bad: list[str] = []
    c_by = {row[0]: row for row in table_after(sec(spec, "## 11."), "C") if row}
    g_by = {row[0]: row for row in table_after(sec(spec, "## 12."), "G") if row}
    l_ids = {row[0] for row in ledger_rows(spec)}
    # a parent's own row (`D07 G-10`, `D02 G4`) is not a reference into §11 / §12
    for ref in re.findall(r"(?<!D0\d )(?<!D0\dH )\b[CG]-\d+\b", r[3]):
        target = (c_by if ref.startswith("C-") else g_by).get(ref)
        if target is None:
            bad.append(f"{r[0]}: cites {ref}, which §11 / §12 does not carry")
        elif not same_decision(r, target):
            bad.append(f"{r[0]}: cites {ref}, which shares no cite and no name with the row")
    for ref in re.findall(r"\bas (L-\d+)\b", r[3]):
        if ref not in l_ids:
            bad.append(f"{r[0]}: inherits from {ref}, which the ledger does not carry")
    return bad


def g_ledger(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-LEDGER")
    aids = {r[0] for r in c_rows(t.spec)}
    for r in ledger_rows(t.spec):
        if len(r) < 5:
            bad.append(f"{r[0]}: the ledger row has {len(r)} cells, not 5")
            continue
        m = re.fullmatch(r"(\w+?) (.+?) \(([0-9A-Z]+H?):(\d+)(?:[–-](\d+))?\)", r[1])
        if not m or m[3] not in PATHS:
            if r[0] != "L-42":
                bad.append(f"{r[0]}: the row of record is not `DOC id (DOC:line)`")
            continue
        ls = lines_of(t.env.at_base(PATHS[m[3]]))
        n = int(m[4])
        if n > len(ls):
            bad.append(f"{r[0]}: {m[3]}:{n} is past the end of the file")
            continue
        ident = m[2].split(" ")[0]
        if row_id_form(ident) and not re.match(rf"^\|\s*{re.escape(ident)}\s*\|", ls[n - 1]):
            bad.append(f"{r[0]}: {m[3]}:{n} does not carry the row id {ident}")
        if disposition(r[3]) not in DISPOSITIONS:
            bad.append(f"{r[0]}: the disposition is not one of {', '.join(DISPOSITIONS)}")
        for aid in a_ids(r[4]):
            if aid not in aids:
                bad.append(f"{r[0]}: names {aid}, which §C does not carry")
        bad += ref_problems(t.spec, r)
    head = t.env.show("origin/main", CAT_REL)
    if head is not None:
        ls = lines_of(head)
        if len(ls) > 17 and "**Forbidden**" in ls[17] and a_row(t.spec, "A-1"):
            bad.append(
                "`15`:18 at origin/main declares the optional fields: drop A-1 and L-42 (re-pin)"
            )
    return one("G-LEDGER", bad)


def g_token(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-TOKEN")
    shipped = shipped_names(t.env)
    for r in tp_rows(t.spec):
        alias = r[1].strip("`")
        if alias in shipped:
            bad.append(f"{r[0]}: `{alias}` already ships; a proposal cannot re-declare it")
        for th in THEMES:
            if resolve_any(t.env, t.spec, th, alias) is None:
                bad.append(f"{r[0]}: `{alias}` does not resolve to a colour in {th}")
        if r[9] != "PROPOSED":
            bad.append(f"{r[0]}: the status is not PROPOSED")
    _shipped, _proposed, unlisted = audit_names(t.env, t.spec)
    for n in sorted(unlisted):
        bad.append(f"the parents bind `{n}`, which neither ships nor is a proposal row (AC 1)")
    text = sec(t.spec, "## 5.")
    for d, k, th in status_collisions(t.env, t.spec):
        if f"`{d}`" not in text or f"`{k}`" not in text:
            bad.append(f"{d} = {k} in {th} is a status-hue collision §5 does not record")
    for where, cell in engine_cells(t.spec):
        for n in engine_bound_names(cell):
            if not is_engine_name(t.env, n):
                bad.append(
                    f"{where} binds `{n}`, which no `ENGINE_CATEGORY_PREFIXES` name covers (BQ-04)"
                )
    return one("G-TOKEN", bad)


def g_contrast(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-CONTRAST")
    pairs = t.env.at_base(PAIRS_REL)
    for r in p_rows(t.spec):
        if len(r) < 10:
            bad.append(f"{r[0]}: the pair row has {len(r)} cells, not 10")
            continue
        fg, bg, kind, reg = r[2].strip("`"), r[3].strip("`"), r[4], r[9]
        if kind not in BARS and kind != "decorative":
            bad.append(f"{r[0]}: the kind `{kind}` is neither text, non-text nor decorative")
        present = re.search(rf'fg: "{re.escape(fg)}", bg: "{re.escape(bg)}"', pairs) is not None
        if reg == "registered" and not present:
            bad.append(f"{r[0]}: claims a registered `pairs.mjs` row; none at the base")
        if reg == "PROPOSED" and present:
            bad.append(f"{r[0]}: claims a PROPOSED `pairs.mjs` row; it is registered at the base")
        if reg not in ("registered", "PROPOSED", "—"):
            bad.append(f"{r[0]}: the `PAIRS` cell is not registered / PROPOSED / —")
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, ln in enumerate(lines_of(text), 1):
            for m in HEX.finditer(ln):
                if not ln[m.end() :].startswith("<!--=HEX:"):
                    bad.append(f"{doc}:{i} carries a hex outside an anchored Resolved value")
    return one("G-CONTRAST", bad)


def g_cvd(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-CVD") + cvd_src_problems(t.env)
    for r in v_rows(t.spec):
        vid = r[0].lower().replace("-", "")
        if vid not in V_PAIRS and vid != "v6":
            bad.append(f"{r[0]}: the tool defines no pair for this row")
    return one("G-CVD", bad)


FORBIDDEN_HANDLE = "no per-handle text and no per-handle shadow"


def g_handle(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-HANDLE")
    s6 = sec(t.spec, "## 6.")
    if FORBIDDEN_HANDLE not in s6:
        bad.append(f"§6 lacks the forbidden-treatments sentence ({FORBIDDEN_HANDLE!r})")
    for want in ("24 × 24 CSS px", "10 px pointer / 16 px touch", "8 px two-tone"):
        if want not in s6:
            bad.append(f"§6 lacks the ruled number {want!r}")
    return one("G-HANDLE", bad)


def base_stories(t: Texts, line: int) -> list[str]:
    return stories_of(lines_of(t.env.at_base(CAT_REL))[line - 1])


def g_stories(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-STORIES")
    a10, a17 = new_of(t.spec, "A-10"), new_of(t.spec, "A-17")
    s191 = stories_of(a10)
    want = set(base_stories(t, 2427))
    d05 = lines_of(t.env.at_base(PATHS["D05"]))[431]
    want |= {x.strip("`") for x in re.findall(r"`(\w+)`", d05)}
    want |= {"PositionTool"} | set(ADDED_191)
    for s in sorted(want - set(s191)):
        bad.append(f"A-10 lacks the story {s}")
    if len(set(s191)) != len(s191):
        bad.append("A-10 repeats a story")
    if BAND_191 not in a10:
        bad.append(f"A-10 does not name the band {BAND_191}")
    d03 = lines_of(t.env.at_base(PATHS["D03"]))
    ruled = [m[1] for ln in d03[414:432] for m in [re.match(r"^- `(\w+)` — ", ln)] if m]
    s223 = stories_of(a17)
    if s223 != ruled:
        bad.append(
            f"A-17's list is not D03 §11's eighteen in order ({len(ruled)} ruled, {len(s223)} listed)"
        )
    if not set(base_stories(t, 2770)) <= set(s223):
        bad.append("A-17 drops one of `15`'s four stories")
    if BAND_223 not in a17:
        bad.append(f"A-17 does not name the band {BAND_223}")
    return one("G-STORIES", bad)


def checklist_labels(t: Texts) -> tuple[str, ...]:
    """`16` §11.4's checklist lines, from its heading to its first table (the block is a fence)."""
    ls = lines_of(t.env.at_base(PATHS["16"]))
    i = next(k for k, ln in enumerate(ls) if ln.startswith("### 11.4 "))
    j = next(k for k in range(i, len(ls)) if ls[k].startswith("### Table 1"))
    return tuple(re.findall(r"^- \[ \] \*\*(.+?)\*\*", "\n".join(ls[i:j]), flags=re.MULTILINE))


def derived_components(spec: str) -> list[tuple[str, str, str]]:
    """(target, ledger rows, A-rows) from §2's Here cells and §C's Target cells."""
    by_a: dict[str, list[str]] = {}
    for r in ledger_rows(spec):
        for aid in a_ids(r[4]):
            by_a.setdefault(aid, []).append(r[0])
    out: dict[str, tuple[list[str], list[str]]] = {}
    for r in c_rows(spec):
        ls, as_ = out.setdefault(r[1], ([], []))
        as_.append(r[0])
        for l_ in by_a.get(r[0], []):
            if l_ not in ls:
                ls.append(l_)
    rows = []
    for tgt, (ls, as_) in out.items():
        ls_s = sorted(ls, key=lambda x: int(x[2:])) or ["—"]
        a_s = f"{as_[0]} … {as_[-1]}" if len(as_) > 2 else ", ".join(as_)
        rows.append((tgt, ", ".join(ls_s), a_s))
    return rows


def g_entry(t: Texts) -> list[Finding]:
    bad: list[str] = []
    allowed = set(BASE_FIELDS) | set(NEW_FIELDS) | set(LEAD_FIELDS)
    for r in c_rows(t.spec):
        if r[0] == "A-1" or len(r) < 6 or r[2].startswith("`14`"):
            continue
        for part in unescape(r[5]).split("<br>"):
            m = re.match(r"- \*\*([^*]+)\*\*", part)
            if m and m[1] not in allowed:
                bad.append(
                    f"{r[0]}: the field **{m[1]}** is declared neither in §0.1, by E09-D07 A-1 nor as a lead-in"
                )
            for lead in LEAD_FIELDS:
                if f"**{lead}**" in part and not part.startswith(f"- **{lead}**: "):
                    bad.append(f"{r[0]}: the {lead} bullet is not in E37-D03 §12's form")
    a1 = new_of(t.spec, "A-1")
    if (
        a1
        and tuple(re.findall(r"\*\*(\w+)\*\*", a1.split("optional fields ", 1)[-1])) != NEW_FIELDS
    ):
        bad.append("A-1 does not declare the four optional fields, and only them")
    # the hand-off
    labels = checklist_labels(t)
    parts = re.split(r"^## Handoff checklist — ", t.hand, flags=re.MULTILINE)[1:]
    if tuple(p[:7] for p in parts) != HAND_ORDER:
        bad.append("the hand-off does not carry the two checklists in order")
    for p in parts:
        cid = p[:7]
        checks = re.findall(r"^- \[([x ])\] \*\*(.+?)\*\* (.*)$", p, flags=re.MULTILINE)
        if tuple(c[1] for c in checks) != labels:
            bad.append(f"{cid}: the checklist lines differ from `16` §11.4's")
        for mark, label, rest in checks:
            if not re.match(r"(?:and the \*\*.+?\*\* )?— \S", rest):
                bad.append(f"{cid}: '{label}' has no evidence or reason")
            if label in PR3_ONLY and mark != " ":
                bad.append(f"{cid}: '{label}' is ticked; it lands with PR 3 (or after)")
        t1 = table_after(p, "Variant")
        names = {x.strip() for r in t1 for x in r[3].split(",") if len(r) > 3}
        aid = "A-10" if cid == "CMP-191" else "A-17"
        missing = sorted(set(stories_of(new_of(t.spec, aid))) - names)
        if missing:
            bad.append(f"{cid}: table 1 misses the stories {', '.join(missing)}")
    want = [list(r) for r in derived_components(t.spec)]
    got = [r[:3] for r in table_after(t.hand, "Component")]
    if got != want:
        bad.append("the hand-off's ledger-by-component table is not the derivation from §2 and §C")
    return one("G-ENTRY", bad)


def mutation_paragraph(spec: str) -> str:
    blk = sec(spec, "## 16.")
    return blk.split("\n", 2)[2] if blk.count("\n") >= 2 else ""


def old_cell_problems(t: Texts) -> list[str]:
    """Every §C Old cell is its line at the base, verbatim (a code line after stripping)."""
    bad: list[str] = []
    for r in c_rows(t.spec):
        m = FIELD.fullmatch(r[2]) if len(r) == 7 else None
        if not m or r[4] == "—":
            continue
        ls = lines_of(t.env.at_base(CAT_REL if m[1] == "15" else SCR_REL))
        n = int(m[2])
        base = ls[n - 1] if 0 < n <= len(ls) else ""
        old = unescape(r[4])
        same = old.strip("`") == base.strip() if r[3] == "replace code line" else old == base
        if not same:
            bad.append(f"{r[0]}: its Old cell is not `{m[1]}`:{n} at the base, verbatim")
    return bad


def g_hygiene(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-HYGIENE")
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for key in unfilled(text):
            bad.append(f"{doc}: the placeholder `{key}` is unfilled (run --check --fill)")
        bad += [f"{doc}: {p}" for p in cite_problems(t.env, text)]
        for i, ln in enumerate(lines_of(text), 1):
            if "{{" in ln:
                bad.append(f"{doc}:{i} carries `{{{{` (a placeholder outside the fill, or a stray)")
            if CLOSING.search(ln):
                bad.append(f"{doc}:{i} carries a closing keyword (PR 3 alone closes #352)")
            if LOCAL_PATH.search(ln):
                bad.append(f"{doc}:{i} carries a local filesystem path or a notes-folder name")
            if AGENT_NAME.search(ln):
                bad.append(f"{doc}:{i} carries an agent name")
            if URL_OR_HOST.search(ln):
                bad.append(f"{doc}:{i} carries a URL, a host or a Penpot id parameter")
    bad += old_cell_problems(t)
    # the diff against the merge-base
    if t.changed is None:
        bad.append("cannot list the changed paths (`git diff` / `git status` failed)")
    else:
        own = [p for p in t.changed if p in OWN_PATHS]
        other = [p for p in t.changed if p not in OWN_PATHS]
        if own or not other:
            for p in other:
                bad.append(f"PR 1 changes {p}, outside the pack's four files")
        else:
            rows = a_rows_export(t.spec, t.env.at_base(CAT_REL), t.env.at_base(SCR_REL))
            want15, bad15 = apply_rows(
                t.env.at_base(CAT_REL), [r for r in rows if r["file"] == CAT_REL]
            )
            want14, bad14 = apply_rows(
                t.env.at_base(SCR_REL), [r for r in rows if r["file"] == SCR_REL]
            )
            bad += bad15 + bad14
            if t.cat15 != want15:
                bad.append("PR 2: `15` is not the base with §C applied exactly (an extra byte)")
            if t.cat14 != want14:
                bad.append("PR 2: `14` is not the base with A-37 applied exactly")
            for p in other:
                if p not in (CAT_REL, SCR_REL):
                    bad.append(f"PR 2 changes {p}, outside `15` and `14`")
    # the mutation list
    para = mutation_paragraph(t.spec)
    gates_named = re.findall(r"\*\*(G-[A-Z-]+)\*\*", para)
    if len(re.findall(r"\bM-\d+\b", para)) != len(MUTATIONS):
        bad.append(
            f"§16 lists {len(re.findall(r'M-\\d+', para))} mutations; the tool has {len(MUTATIONS)}"
        )
    if gates_named != [g.__name__.upper().replace("G_", "G-") for g in GATES] + ["G-RULED-PIN"]:
        bad.append("§16 does not name each gate once, in the tool's order")
    return one("G-HYGIENE", bad)


def g_pins(t: Texts) -> list[Finding]:
    pinned = parse_pins(t.pins)
    if not pinned:
        return one("G-RULED-PIN", [f"{PINS_REL} is empty or missing (run --repin-ruled)"])
    return one("G-RULED-PIN", pin_problems(pinned, all_units(t.spec, t.hand)))


GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_ledger, g_token, g_contrast, g_cvd, g_handle, g_stories, g_entry, g_hygiene,
)  # fmt: skip


def audit(t: Texts) -> list[Finding]:
    found: list[Finding] = []
    for g in GATES:
        found += g(t)
    pins = g_pins(t)
    if found:
        pins = [replace(f, level="NOTE") for f in pins]
    return found + pins


# ---------------------------------------------------------------------------- §C export and PR 2

FIELD = re.compile(r"`(14|15)`:(\d+)")


def a_rows_export(spec: str, base15: str, base14: str) -> list[dict[str, object]]:
    """§C as data for PR 2: anchors dropped, their values kept, escapes undone; each row carries
    its file, its entry heading and its anchor line at the base so PR 2 re-points by content."""
    out: list[dict[str, object]] = []
    for r in c_rows(spec):
        if len(r) != 7:
            continue
        m = FIELD.fullmatch(r[2])
        if not m:
            continue
        rel = CAT_REL if m[1] == "15" else SCR_REL
        lines = lines_of(base15 if rel == CAT_REL else base14)
        n = int(m[2])
        anchor = lines[n - 1] if 0 < n <= len(lines) else ""
        head = next((lines[i] for i in range(min(n, len(lines)) - 1, -1, -1)
                     if lines[i].startswith("### ")), "")  # fmt: skip
        new = strip_anchors(unescape(r[5]))
        if r[3] == "replace code line":
            indent = anchor[: len(anchor) - len(anchor.lstrip())]
            new = indent + new.strip("`")
        out.append(
            {
                "id": r[0],
                "target": r[1],
                "file": rel,
                "line": n,
                "entry": head,
                "anchor": anchor,
                "op": r[3],
                "old": [] if r[4] == "—" else [unescape(r[4])],
                "new": new.split("<br>"),
                "from": r[6],
            }
        )
    return out


def apply_rows(text: str, rows: list[dict[str, object]]) -> tuple[str, list[str]]:
    """`text` with every row applied, re-pointed by content: its entry heading, then its anchor
    line inside that entry, each found once; (result, problems)."""
    lines = lines_of(text)
    bad: list[str] = []
    plan: list[tuple[int, int, dict[str, object]]] = []
    for k, r in enumerate(rows):
        heads = [i for i, ln in enumerate(lines) if ln == r["entry"]]
        if len(heads) != 1:
            bad.append(f"{r['id']}: its entry heading stands {len(heads)} times")
            continue
        end = next(
            (i for i in range(heads[0] + 1, len(lines)) if lines[i].startswith("#")), len(lines)
        )
        hits = [i for i in range(heads[0], end) if lines[i] == r["anchor"]]
        if len(hits) != 1:
            bad.append(f"{r['id']}: its anchor stands {len(hits)} times in its entry")
            continue
        plan.append((hits[0], k, r))
    for i, _, r in sorted(plan, key=lambda p: (-p[0], -p[1])):
        new = [str(x) for x in r["new"]] if isinstance(r["new"], list) else []
        if str(r["op"]).startswith("replace"):
            lines[i : i + 1] = new
        else:
            lines[i + 1 : i + 1] = new
    return "\n".join(lines), bad


# ---------------------------------------------------------------------------- load, mutations, self-test


def load() -> Texts:
    base = merge_base()
    if base is None:
        raise SystemExit("`git merge-base HEAD origin/main` does not resolve; fetch origin first")
    env = Env(base, {})
    spec, hand = read_raw(SPEC_REL), read_raw(HAND_REL)
    pins = read_raw(PINS_REL) if (ROOT / PINS_REL).exists() else ""
    t = Texts(env, spec, hand, pins, read_raw(CAT_REL), read_raw(SCR_REL), changed_paths(base), {})
    return replace(t, values=compute(env, spec, hand))


@dataclass(frozen=True)
class Mutation:
    gate: str
    what: str
    apply: Callable[[Texts], Texts]


def flex(old: str) -> re.Pattern[str]:
    return re.compile(r"\s+".join(re.escape(p) for p in old.split(" ") if p != ""))


def subst(old: str, new: str, doc: str = "spec") -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        text = getattr(t, doc)
        m = flex(old).search(text)
        if not m:
            raise SystemExit(f"self-test: {doc} lacks {old[:60]!r}")
        return replace(t, **{doc: text[: m.start()] + new + text[m.end() :]})

    return f


def anchor_edit(key: str, new_value: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        rx = re.compile(rf"([^\s<|]+)<!--={re.escape(key)}-->")
        m = rx.search(t.spec)
        if not m:
            raise SystemExit(f"self-test: the spec has no anchored {key}")
        return replace(
            t, spec=t.spec[: m.start()] + f"{new_value}<!--={key}-->" + t.spec[m.end() :]
        )

    return f


M = Mutation
# grouped by gate, in the tool's order; §16 lists them under the same numbers
MUTATIONS: tuple[Mutation, ...] = (
    M("G-LEDGER", "re-point a ledger row's cite to a line that does not carry its id",
      subst("D02 C13 (D02:659)", "D02 C13 (D02:658)")),
    M("G-LEDGER", "re-point L-3's C-ref to a C-row that shares no cite and no name with it",
      subst("no token line (§4.2, C-20)", "no token line (§4.2, C-11)")),
    M("G-TOKEN", "re-point a TP target to a token name no theme resolves",
      subst("| TP-13 | `color.drawing.snap`            | `{color.focus.ring}`", "| TP-13 | `color.drawing.snap` | `{color.focus.rng}`")),
    M("G-TOKEN", "bind the §3 stroke row to a name outside the engine export",
      subst("| stroke | engine | the drawing's colour: `color.drawing.default` or TP-1 … TP-8",
            "| stroke | engine | the drawing's colour: `color.text.primary` or TP-1 … TP-8")),
    M("G-CONTRAST", "type a ratio by hand in §8", anchor_edit("CONTRAST:p9.dark", "8.51")),
    M("G-CVD", "alter a simulated value in §8's V-table", anchor_edit("CVD:v1.grey.dark", "9.99")),
    M("G-HANDLE", "alter the 8 px glyph's row coverage in §6", anchor_edit("HANDLE:g8.c12", "0.68")),
    M("G-STORIES", "drop D05's MeasurePinned from A-10", subst("MeasurePinned, MeasureAcrossGap, DensityComposite, HighContrast, ForcedColors, ReducedMotion, Greyscale, PositionTool", "MeasureAcrossGap, DensityComposite, HighContrast, ForcedColors, ReducedMotion, Greyscale, PositionTool")),
    M("G-ENTRY", "add an undeclared field bullet to A-12",
      subst("- **Motion (E14-D08)**: none by design; the snap, selection and undo feedback pairs are E14-D09's (#353) and will append here.<br>- **Usage (E14-D08)**: `docs/design/E14/E14-D08.md`",
            "- **Motion (E14-D08)**: none by design; the snap, selection and undo feedback pairs are E14-D09's (#353) and will append here.<br>- **Composition**: a note.<br>- **Usage (E14-D08)**: `docs/design/E14/E14-D08.md`")),
    M("G-HYGIENE", "write a closing keyword against #352 in §17",
      subst("the closing line rides on PR 3 alone", "Closes #352")),
    M("G-HYGIENE", "leave a `{{` placeholder inside a code span of §0",
      subst("**Nothing here is built or published.**", "**Nothing here is built or published.** (`{{SHA:BASE}}`)")),
    M("G-HYGIENE", "misquote A-3's Old cell by one letter",
      subst("base drawing-tools primitive kit (per digest 10", "base drawing-tool primitive kit (per digest 10")),
    M("G-RULED-PIN", "re-word one pinned sentence of §5",
      subst("Until the field exists, D04's client rule stands as the fallback", "Until the field exists, D04's client rule is the fallback")),
)  # fmt: skip


def digest(t: Texts) -> str:
    return hashlib.sha256((t.spec + "\0" + t.hand + "\0" + t.pins).encode()).hexdigest()


def ascii_line(s: str) -> str:
    for a, b in (("→", "->"), ("›", ">"), ("…", "..."), ("—", "-"), ("–", "-"), ("×", "x"),
                 ("§", "S"), ("·", "|"), ("≤", "<="), ("≥", ">=")):  # fmt: skip
        s = s.replace(a, b)
    return s.encode("ascii", "replace").decode()[:100]


def selftest() -> tuple[bool, list[str]]:
    base = load()
    disk = [hashlib.sha256(read_raw(r).encode()).hexdigest() for r in OWN_PATHS]
    before = digest(base)
    base_found = [f for f in audit(base) if f.level == "FAIL"]
    out = [f"self-test: baseline {len(base_found)} FAIL"]
    ok = not base_found
    for f in base_found:
        out.append(ascii_line(f"  baseline {f.gate}: {f.msg}"))
    for i, m in enumerate(MUTATIONS, 1):
        t = m.apply(base)
        fails = [f for f in audit(t) if f.level == "FAIL"]
        gates = sorted({f.gate for f in fails})
        good = bool(fails) and gates == [m.gate]
        ok &= good
        mark = "ok  " if good else "FAIL"
        out.append(ascii_line(f"{mark} M-{i} {m.gate}: {m.what} -> {', '.join(gates) or 'none'}"))
    rows = a_rows_export(base.spec, base.env.at_base(CAT_REL), base.env.at_base(SCR_REL))
    c15, _ = apply_rows(base.env.at_base(CAT_REL), [r for r in rows if r["file"] == CAT_REL])
    c14, _ = apply_rows(base.env.at_base(SCR_REL), [r for r in rows if r["file"] == SCR_REL])
    pr2 = replace(base, cat15=c15, cat14=c14, changed=[CAT_REL, SCR_REL])
    extra = [f for f in audit(pr2) if f.level == "FAIL"]
    ok &= not extra
    out.append(ascii_line(f"{'ok  ' if not extra else 'FAIL'} N-1 PR 2 with §C applied exactly -> "
                          f"{', '.join(sorted({f.gate for f in extra})) or 'none'}"))  # fmt: skip
    restored = digest(base) == before and disk == [
        hashlib.sha256(read_raw(r).encode()).hexdigest() for r in OWN_PATHS
    ]
    ok &= restored
    out.append(
        f"self-test: {len(MUTATIONS)} mutations, texts restored: {'yes' if restored else 'NO'}"
    )
    out.append(f"self-test: {'PASS' if ok else 'FAIL'}")
    return ok, out


def render(found: list[Finding]) -> list[str]:
    return [ascii_line(f"{f.level} {f.gate}: {f.msg}") for f in found]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else "")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="the default mode")
    g.add_argument("--self-test", action="store_true")
    g.add_argument("--repin-ruled", action="store_true")
    g.add_argument("--a-rows", action="store_true")
    ap.add_argument("--json", action="store_true", help="--check's dump; alone it implies --check")
    ap.add_argument("--fill", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        ok, lines = selftest()
        print("\n".join(lines))
        return 0 if ok else 1
    t = load()
    if a.a_rows:
        rows = a_rows_export(t.spec, t.env.at_base(CAT_REL), t.env.at_base(SCR_REL))
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if a.repin_ruled:
        for doc, text in (("spec", t.spec), ("hand", t.hand)):
            if unfilled(text):
                print(f"refused: {doc} has an unfilled placeholder (run --check --fill)")
                return 1
        other = [f for f in audit(t) if f.level == "FAIL" and f.gate != "G-RULED-PIN"]
        if other:
            print(f"refused: {len(other)} FAIL outside the pins (first: {other[0].gate}); fix them")
            return 1
        write_text(PINS_REL, write_pins(all_units(t.spec, t.hand)))
        print(f"wrote {PINS_REL}")
        return 0
    if a.fill:
        spec, miss1 = fill(t.spec, t.values)
        hand, miss2 = fill(t.hand, t.values)
        write_text(SPEC_REL, spec)
        write_text(HAND_REL, hand)
        for m in miss1 + miss2:
            print(f"unfilled: {m}")
        t = load()
    found = audit(t)
    fails = [f for f in found if f.level == "FAIL"]
    if a.json:
        dump = {"base": t.env.base, "values": t.values,
                "findings": [{"level": f.level, "gate": f.gate, "msg": f.msg} for f in found]}  # fmt: skip
        print(json.dumps(dump, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for ln in render(found):
            print(ln)
        notes = len(found) - len(fails)
        print(f"{len(fails)} FAIL / 0 WARN / {notes} NOTE ({len(GATES) + 1} gates)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
