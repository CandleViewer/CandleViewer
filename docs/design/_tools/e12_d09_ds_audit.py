#!/usr/bin/env python3
"""E12-D09 (#244) audit: the design-system pack for the bar-mode and series components.

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads AS
TEXT at the pinned base (`git show BASE:<path>`) the plan texts (`02`, `14`, `15`, `16`, `22`,
`23`), the merged E12 design docs (D02 ... D06H), E11-D02, E11-D04, E11-D05, E08-D04, the token
JSON (`themes.json` layering: dark = primitives + semantic-dark, light = + semantic-light, hc = +
semantic-hc), `calendar_cv.py`, `E12.json`, `rbac_seed.json` and the research CVD script; then the
pack (`E12-D09.md`), its registry (`E12-D09-barmodes.json`) and the pins from the working tree.

1. **Values.** Every `{{KIND:key}}` outside a code span is COMPUTED: HEX and CONTRAST (WCAG 2.x,
   truncated to two decimals) from the token JSON, DE (CIE76, one decimal) under the CVD
   simulations, NEAREST (the nearest semantic colour token), COUNT (rows and ids of the pack's own
   tables, story names, registry modes, mutations) and DATE (a sprint start from `calendar_cv.py`
   and `E12.json`). `--fill` writes `VALUE<!--=KIND:key-->` and the mutation paragraph; `--check`
   re-derives every anchored value and FAILs on a difference, on a `{{` left outside a code span
   and on a hand-typed ratio or hex (G-FIGURE).
2. **Cites.** Every `NN`:line and `D0n`/`D0nH`/`E11-D0n`/`E08-D04`/`TOK-*`/`CAL`/`SEED`:line cite
   (with `, :n` continuations and `n–m` ranges) is read at the base; a missing or blank line FAILs
   (G-CITE) and the load-bearing fragments of CITED must sit on their lines. G-VERSION FAILs when
   any line inside a cited range differs at `origin/main`, when `origin/main` does not resolve, or
   when the last commit moved for a version-line input or for an input that feeds a computed
   value without a cited range (DRIFT_INPUTS: the token JSON, `themes.json`, `E12.json`,
   `calendar_cv.py`, the research CVD script, `rbac_seed.json`). Every such read goes through
   the passed Env, so the self-test can simulate its drift.
3. **Gates.** Lexicon and table gates read table cells and prose after the comment strip, NFKC and
   whitespace-normalised: each ruled behaviour has its sentences REQUIRED verbatim in its section
   (CLOSED ones must end their clause) and a synonym set FORBIDDEN where a paraphrase would reverse
   it. That catches every paraphrase the self-test plants (lens 2's 22 survivors among them) even
   after a repin, not every paraphrase there is: the general protection is the default-deny pins
   of item 4, the hashed New cells (G-NEWBYTES) and review of their diffs. The measured gates
   (the ledger, the dispositions, the per-mode table, the tokens and CVD criterion, the enum diff,
   the registry against D03 / D05 at the base, the A-rows byte for byte against `15` / `16` /
   `14` at the base, the pack pointers, the surface grid, the stories, the D-5 phases, the log,
   the C-rows, the dry run over every scenario, the cells of every table row, the line budget)
   follow; G-UNTOUCHED reads the committed and uncommitted paths against `git
   merge-base HEAD origin/main` and FAILs when that does not resolve.
4. **Pins (G-RULED-PIN).** A whole-document default-deny pin set over every unit of the pack in
   `e12_d09_ruled_pins.txt`: each heading, table row (by its lead cell), rule line and prose
   sentence, by region (the heading path plus occurrence) and location, NFKC and whitespace
   normalised, anchored values cut out, plus each region's line shape. A unit changed, moved,
   added or deleted FAILs (one finding per region). `--repin-ruled` is the only writer. Each §C
   New cell is also pinned byte for byte by its sha256 in NEW_SHA (G-NEWBYTES), which no flag
   writes. When any other gate FAILs, every G-RULED-PIN and G-NEWBYTES finding prints as a NOTE
   (globally, not per section); the exit status stays 1, so fix the FAILs and re-run.
5. **--self-test** applies every mutation of §15 in memory with the values frozen at the filled
   baseline; each must add exactly one FAIL, from the gate it names; every text is restored byte
   for byte (sha256). The report is ASCII.

Usage (from the repo root):
  python3 -I docs/design/_tools/e12_d09_ds_audit.py --check [--json] [--fill]
  python3 -I docs/design/_tools/e12_d09_ds_audit.py --self-test
  python3 -I docs/design/_tools/e12_d09_ds_audit.py --repin-ruled
  python3 -I docs/design/_tools/e12_d09_ds_audit.py --a-rows
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import re
import subprocess
import sys
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = "8f652abb16"  # #4848's merge: every cite was re-read here (v1 read at aba03ac309)
HEAD_REF = "origin/main"  # drift inside a cited range FAILs (G-VERSION)
SPEC_REL = "docs/design/E12/E12-D09.md"
REG_REL = "docs/design/E12/E12-D09-barmodes.json"
TOOL_REL = "docs/design/_tools/e12_d09_ds_audit.py"
PINS_REL = "docs/design/_tools/e12_d09_ruled_pins.txt"
OWN_PATHS = (SPEC_REL, REG_REL, TOOL_REL, PINS_REL)
LINE_BUDGET = 300  # BQ-4 as ruled: "One spec of at most ~300 lines"
WALK_MAX = 10  # BQ-30: "the owner walkthrough <= 10 items"
PR_TITLE = "docs(chart-engine): E12-D09 design-system pack for the bar-mode and series components"
RULING_ID = "6465614406"
BQ_LIST_ID = "6465465756"
COMMENT_IDS = (RULING_ID, BQ_LIST_ID, "6463491974", "6455151492")
OWNER = "owner approval pending (#2701)"
UNMERGED = ("#242", "#243", "#245", "#312", "#4822")

PATHS: dict[str, str] = {
    "02": "docs/plan/02-definition-of-ready-done.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "23": "docs/plan/23-ws-protocol.md",
    "24": "docs/plan/24-internal-schemas.md",
    "26": "docs/plan/26-chart-engine-design.md",
    "D02": "docs/design/E12/E12-D02.md",
    "D03": "docs/design/E12/E12-D03.md",
    "D03H": "docs/design/E12/E12-D03-handoff.md",
    "D04": "docs/design/E12/E12-D04.md",
    "D04H": "docs/design/E12/E12-D04-handoff.md",
    "D05": "docs/design/E12/E12-D05.md",
    "D05H": "docs/design/E12/E12-D05-handoff.md",
    "D06": "docs/design/E12/E12-D06.md",
    "D06H": "docs/design/E12/E12-D06-handoff.md",
    "E11-D02": "docs/design/E11/E11-D02.md",
    "E11-D04": "docs/design/E11/E11-D04.md",
    "E11-D05": "docs/design/E11/E11-D05.md",
    "E08-D04": "docs/design/E08/E08-D04.md",
    "E12-D02": "docs/design/E12/E12-D02.md",
    "CAL": "docs/plan/backlog/_tools/calendar_cv.py",
    "SEED": "services/api/candleviewer/auth/rbac_seed.json",
    "TOK-D": "packages/ui/tokens/semantic-dark.tokens.json",
    "TOK-P": "packages/ui/tokens/primitives.tokens.json",
}
E12_JSON = "docs/plan/backlog/E12.json"
CVD_SRC = "docs/research/_tools/cvd_simulate.py"
DS_SRC = "packages/ui/tokens"
THEMES = {
    "dark": ("primitives", "semantic-dark"),
    "light": ("primitives", "semantic-dark", "semantic-light"),
    "hc": ("primitives", "semantic-dark", "semantic-hc"),
}
UNTOUCHED = (
    tuple(PATHS[k] for k in ("05", "14", "15", "16", "22", "23", "24", "26"))
    + tuple(
        PATHS[k]
        for k in ("D02", "D03", "D03H", "D04", "D04H", "D05", "D05H", "D06", "D06H", "E11-D02")
    )
    + (PATHS["E11-D05"], PATHS["E08-D04"], "docs/design/E11/E11-D02.md")
)
UNTOUCHED_PREFIX = (DS_SRC + "/",)
# BQ-32's version line: input -> the sha of its last commit at the base
VERSION_PINS: dict[str, str] = {
    "D02": "41d81b2bd5",
    "D03": "41d81b2bd5",
    "D03H": "41d81b2bd5",
    "D04": "048430e034",
    "D04H": "048430e034",
    "D05": "d6597cbcf7",
    "D05H": "d6597cbcf7",
    "D06": "63b13d034a",
    "D06H": "63b13d034a",
}

# the inputs that feed computed values (tokens, layering, dates, CVD constants, the RBAC cite)
# but are cited by no line range: any commit to one after the base is a late change (G-VERSION)
DRIFT_INPUTS: tuple[str, ...] = (
    f"{DS_SRC}/primitives.tokens.json",
    f"{DS_SRC}/semantic-dark.tokens.json",
    f"{DS_SRC}/semantic-light.tokens.json",
    f"{DS_SRC}/semantic-hc.tokens.json",
    f"{DS_SRC}/themes.json",
    E12_JSON,
    PATHS["CAL"],
    CVD_SRC,
    PATHS["SEED"],
)

# ---------------------------------------------------------------------------- git


@dataclass
class Env:
    """The repository facts the gates read; the self-test swaps them to simulate drift."""

    base_cache: dict[str, str | None] = field(default_factory=dict)
    head_cache: dict[str, str | None] = field(default_factory=dict)
    merge_base: Callable[[], str | None] | None = None
    changed: Callable[[str], list[str]] | None = None
    head_override: dict[str, str | None] = field(default_factory=dict)
    head_ok: bool | None = None
    last_override: dict[str, str] = field(default_factory=dict)
    cur_override: dict[str, str] = field(default_factory=dict)
    status_raw: Callable[[], str] | None = None
    memo: dict[str, object] = field(default_factory=dict)
    grep_extra: dict[str, list[str]] = field(default_factory=dict)

    def current(self, rel: str) -> str | None:
        """The working-tree text of `rel` (the self-test may swap it)."""
        if rel in self.cur_override:
            return self.cur_override[rel]
        path = ROOT / rel
        return path.read_text(encoding="utf-8") if path.exists() else None

    def show(self, rev: str, rel: str) -> str | None:
        if rev == BASE:
            if rel not in self.base_cache:
                self.base_cache[rel] = git_show(rev, rel)
            return self.base_cache[rel]
        if rev == HEAD_REF and rel in self.head_override:
            return self.head_override[rel]
        key = f"{rev}:{rel}"
        if key not in self.head_cache:
            self.head_cache[key] = git_show(rev, rel)
        return self.head_cache[key]

    def base(self, rel: str) -> str:
        text = self.show(BASE, rel)
        if text is None:
            raise SystemExit(f"cannot read {rel} at {BASE}")
        return text

    def head_resolves(self) -> bool:
        if self.head_ok is not None:
            return self.head_ok
        return git_ok("rev-parse", "--verify", "--quiet", HEAD_REF + "^{commit}")

    def last_commit(self, rev: str, rel: str) -> str:
        key = f"{rev}:{rel}"
        if key in self.last_override:
            return self.last_override[key]
        return git_out("log", "-1", "--format=%H", rev, "--", rel)

    def mb(self) -> str | None:
        if self.merge_base is not None:
            return self.merge_base()
        out = git_out("merge-base", "HEAD", HEAD_REF)
        return out or None

    def grep_paths(self, rev: str, needle: str) -> list[str]:
        """The paths at `rev` holding `needle` (fixed string); the self-test may add paths."""
        out = git_raw("grep", "-l", "-F", "-z", needle, rev, "--")
        paths = [p.split(":", 1)[1] for p in out.split("\0") if ":" in p]
        return sorted(set(paths + self.grep_extra.get(rev, [])))

    def changed_paths(self, mb: str) -> list[str]:
        """Committed (`mb..HEAD`) and uncommitted paths; renames count on both sides."""
        if self.changed is not None:
            return self.changed(mb)
        committed = git_raw("diff", "--name-only", "--no-renames", "-z", mb, "HEAD").split("\0")
        raw = self.status_raw() if self.status_raw else git_raw(*STATUS_ARGS)
        return sorted({p for p in committed + porcelain_paths(raw) if p})


STATUS_ARGS = ("status", "--porcelain", "-z", "--no-renames", "--untracked-files=all")


def porcelain_paths(raw: str) -> list[str]:
    """The paths of `git status --porcelain -z --no-renames`: `XY path` entries, never stripped
    (a leading space is the X status, not part of the path)."""
    return [e[3:] for e in raw.split("\0") if len(e) > 3 and e[2] == " "]


def git_show(rev: str, rel: str) -> str | None:
    r = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{rev}:{rel}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return r.stdout if r.returncode == 0 else None


def git_out(*args: str) -> str:
    r = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return r.stdout.strip() if r.returncode == 0 else ""


def git_raw(*args: str) -> str:
    """Stdout as is (never stripped: porcelain status columns start with a space)."""
    r = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return r.stdout if r.returncode == 0 else ""


def git_ok(*args: str) -> bool:
    r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=False)
    return r.returncode == 0


# ---------------------------------------------------------------------------- markdown

HEADING = re.compile(r"^(#{1,6}) (.*)$")
RULE = re.compile(r"^\|(?:\s*:?-+:?\s*\|)+\s*$")
COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)
ANCHOR = re.compile(r"<!--=([A-Z]+:[^>]+?)-->")
PLACEHOLDER = re.compile(r"\{\{([A-Z]+:[^{}]+)\}\}")
CODE = re.compile(r"`[^`\n]*`")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def split_row(line: str) -> list[str]:
    """A table row's cells; an escaped `\\|` stays inside its cell (and stays escaped)."""
    body = line.strip()
    body = body.removeprefix("|")
    body = body[:-1] if body.endswith("|") and not body.endswith("\\|") else body
    return [c.strip() for c in re.split(r"(?<!\\)\|", body)]


def unescape(cell: str) -> str:
    return cell.replace("\\|", "|")


def sec_no(title: str) -> str:
    """A `##` heading's key: its number (`4`), `C` for §C, else the title."""
    m = re.match(r"(§?[0-9A-Z]+)\.? ", title)
    if title.startswith("§C"):
        return "C"
    return m[1] if m and m[1][0].isdigit() else title


def sections(text: str) -> dict[str, str]:
    """`##`-level section key -> its text (the heading line included)."""
    out: dict[str, str] = {}
    cur, buf = "(top)", list[str]()
    for ln in text.split("\n"):
        m = HEADING.match(ln)
        if m and len(m[1]) == 2:
            out[cur] = "\n".join(buf)
            cur, buf = sec_no(m[2]), []
        buf.append(ln)
    out[cur] = "\n".join(buf)
    return out


def sec_of_line(text: str, line_no: int) -> str:
    cur = "(top)"
    for i, ln in enumerate(text.split("\n"), 1):
        if i > line_no:
            break
        m = HEADING.match(ln)
        if m and len(m[1]) == 2:
            cur = sec_no(m[2])
    return cur


def tables(block: str) -> list[list[list[str]]]:
    """Every table in `block` as rows of cells (header first; the rule line dropped)."""
    out: list[list[list[str]]] = []
    cur: list[list[str]] = []
    for ln in block.split("\n"):
        if ln.startswith("|"):
            if not RULE.match(ln):
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


def strip_comments(text: str) -> str:
    return COMMENT.sub("", text)


def without_code(text: str) -> str:
    return CODE.sub(" ", text)


def norm(text: str) -> str:
    """NFKC, comments dropped, whitespace collapsed (the pins' and the REQUIRED form)."""
    t = unicodedata.normalize("NFKC", strip_comments(text))
    return " ".join(t.split())


def plain(text: str) -> str:
    """Rendered words for the lexicon: `norm`, markup dropped, lower case."""
    t = norm(text)
    t = re.sub(r"[*`]", "", t)
    return t.lower()


# ---------------------------------------------------------------------------- colour and CVD

# The Brettel (1997) / Vienot protan and deutan projections and the Machado, Oliveira & Fernandes
# (2009) tritan matrix, carried as constants (no import of repo code); G-CVD-SRC checks each
# number against `docs/research/_tools/cvd_simulate.py` at the base.
RGB_TO_LMS = (
    17.8824, 43.5161, 4.11935,
    3.45565, 27.1554, 3.86714,
    0.0299566, 0.184309, 1.46709,
)  # fmt: skip
LMS_TO_RGB = (
    0.0809444479, -0.130504409, 0.116721066,
    -0.0102485335, 0.0540193266, -0.113614708,
    -0.000365296938, -0.00412161469, 0.693511405,
)  # fmt: skip
PROTAN = (0.0, 2.02344, -2.52581, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
DEUTAN = (1.0, 0.0, 0.0, 0.494207, 0.0, 1.24827, 0.0, 0.0, 1.0)
TRITAN = (
    1.255528, -0.076749, -0.178779,
    -0.078411, 0.930809, 0.147602,
    0.004733, 0.691367, 0.303900,
)  # fmt: skip
SIMS = ("normal", "protan", "deutan", "tritan")
# simulate(#8B5CF6) and simulate(#2EBD59) under protan / deutan / tritan, pinned at writing
CVD_PINNED: dict[str, tuple[str, str, str]] = {
    "#8B5CF6": ("#6363F6", "#6C6CF6", "#6C80A1"),
    "#2EBD59": ("#B4B458", "#A3A35D", "#00B9A6"),
}


def rgb(hex6: str) -> tuple[int, int, int]:
    h = hex6.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def lin(c: int) -> float:
    v = c / 255.0
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def unlin(c: float) -> float:
    s = c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055
    return max(0.0, min(1.0, s)) * 255.0


def matvec(m: tuple[float, ...], v: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        m[0] * v[0] + m[1] * v[1] + m[2] * v[2],
        m[3] * v[0] + m[4] * v[1] + m[5] * v[2],
        m[6] * v[0] + m[7] * v[1] + m[8] * v[2],
    )


def simulate(hex6: str, sim: str) -> str:
    if sim == "normal":
        return hex6.upper()
    r, g, b = rgb(hex6)
    v = (lin(r), lin(g), lin(b))
    if sim == "tritan":
        out = matvec(TRITAN, v)
    else:
        lms = matvec(RGB_TO_LMS, v)
        out = matvec(LMS_TO_RGB, matvec(PROTAN if sim == "protan" else DEUTAN, lms))
    return "#" + "".join(f"{max(0, min(255, round(unlin(c)))):02X}" for c in out)


def lab(hex6: str) -> tuple[float, float, float]:
    r, g, b = (lin(c) for c in rgb(hex6))
    x = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else (7.787 * t) + (16 / 116)

    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def delta_e(a: str, b: str) -> float:
    return math.dist(lab(a), lab(b))


def luminance(hex6: str) -> float:
    r, g, b = (lin(c) for c in rgb(hex6))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def show_ratio(r: float) -> str:
    return f"{math.floor(r * 100 + 1e-9) / 100:.2f}"


def show_de(d: float) -> str:
    """One decimal, truncated as D06 §1 (D06:134): never rounded up across a threshold."""
    return f"{math.floor(d * 10 + 1e-9) / 10:.1f}"


def cvd_src_problems(env: Env) -> list[str]:
    """Each constant equals the research script's at the base (G-CVD-SRC)."""
    src = env.show(BASE, CVD_SRC) or ""
    bad: list[str] = []

    def nums(block: str) -> tuple[float, ...]:
        return tuple(float(x) for x in re.findall(r"-?\d+\.\d+(?:e-?\d+)?|-?\d+(?=[,)\s])", block))

    def grab(name: str) -> str:
        m = re.search(rf"^{name}\s*=\s*\((.*?)^\)", src, re.MULTILINE | re.DOTALL)
        return m[1] if m else ""

    for name, mine in (("RGB_TO_LMS", RGB_TO_LMS), ("LMS_TO_RGB", LMS_TO_RGB)):
        if nums(grab(name)) != mine:
            bad.append(f"{name} differs from {CVD_SRC} at {BASE}")
    for key, mine in (("protanopia", PROTAN), ("deuteranopia", DEUTAN)):
        m = re.search(rf'"{key}":\s*\(([^)]*)\)', src)
        if not m or nums(m[1] + ",") != mine:
            bad.append(f"the {key} projection differs from {CVD_SRC} at {BASE}")
    if nums(grab("TRITAN_MACHADO")) != TRITAN:
        bad.append(f"TRITAN_MACHADO differs from {CVD_SRC} at {BASE}")
    for src_hex, want in CVD_PINNED.items():
        got = tuple(simulate(src_hex, s) for s in SIMS[1:])
        if got != want:
            bad.append(f"{src_hex} simulates to {got}, pinned {want}")
    return bad


# ---------------------------------------------------------------------------- tokens


def token_file(env: Env, name: str) -> dict[str, object]:
    data = json.loads(env.base(f"{DS_SRC}/{name}.tokens.json"))
    return data if isinstance(data, dict) else {}


def layering(env: Env) -> dict[str, tuple[str, ...]]:
    """Each theme's token sets, read from `themes.json` at the base (THEMES must equal it)."""
    data = json.loads(env.base(f"{DS_SRC}/themes.json"))
    out: dict[str, tuple[str, ...]] = {}
    for th in data.get("themes", []) if isinstance(data, dict) else []:
        if isinstance(th, dict) and th.get("group") == "theme":
            name = {"high-contrast": "hc"}.get(str(th.get("name")), str(th.get("name")))
            out[name] = tuple(str(x) for x in th.get("sets", []))
    return out


def theme(env: Env, name: str) -> dict[str, str]:
    """`name`'s tokens, layered as `themes.json` says; memoised on the Env (the self-test swaps
    the Env to simulate drift, so no read bypasses it)."""
    key = f"theme:{name}"
    if key not in env.memo:
        merged: dict[str, str] = {}
        for f in layering(env).get(name, ()):
            for k, v in token_file(env, f).items():
                if isinstance(v, dict) and isinstance(v.get("$value"), str):
                    merged[k] = str(v["$value"])
        env.memo[key] = merged
    out = env.memo[key]
    return dict(out) if isinstance(out, dict) else {}


def resolve(tokens: dict[str, str], name: str, depth: int = 0) -> str:
    v = tokens.get(name, "")
    m = re.fullmatch(r"\{([^{}]+)\}", v)
    if m and depth < 20:
        return resolve(tokens, m[1], depth + 1)
    return v


def is_hex(v: str) -> bool:
    return re.fullmatch(r"#[0-9A-Fa-f]{6}", v) is not None


def semantic_colours(env: Env, t: str) -> dict[str, str]:
    toks = theme(env, t)
    out: dict[str, str] = {}
    for k in toks:
        if k.startswith("color."):
            v = resolve(toks, k)
            if is_hex(v):
                out[k] = v.upper()
    return out


LINE_PRIMITIVE = "palette.purple.500"  # BQ-19 / D06H A-12: the proposal's alias
LINE_SET = (
    "color.candle.up",
    "color.candle.down",
    "color.order.line",
    "color.focus.ring",
    "color.cvd.buy",
    "color.cvd.sell",
)  # D06:378's comparison set
DE_MIN = 5.0  # D06:403: a pair under CIE76 5.0 passes only with a non-colour channel


def line_hex(env: Env, t: str) -> str:
    return resolve(theme(env, t), LINE_PRIMITIVE).upper()


def grey_dl(a: str, b: str) -> float:
    """The greyscale difference: |L*a - L*b| (D06 §15.2's "greyscale ΔL")."""
    return abs(lab(a)[0] - lab(b)[0])


def token_values(env: Env) -> dict[str, str]:
    v: dict[str, str] = {}
    for t in THEMES:
        line = line_hex(env, t)
        sem = semantic_colours(env, t)
        v[f"HEX:line.{t}"] = line
        v[f"CONTRAST:line.canvas.{t}"] = show_ratio(contrast(line, sem["color.surface.canvas"]))
        near = min(sorted(sem), key=lambda k: delta_e(line, sem[k]))
        v[f"NEAREST:line.{t}"] = f"`{near}`"
        v[f"DE:line.near.{t}"] = show_de(delta_e(line, sem[near]))
        v[f"CONTRAST:line.near.{t}"] = show_ratio(contrast(line, sem[near]))
        v[f"CONTRAST:line.logic.{t}"] = show_ratio(contrast(line, sem["color.node.logic"]))
        for s in SIMS:
            d = min(delta_e(simulate(line, s), simulate(sem[k], s)) for k in LINE_SET)
            v[f"DE:line.set.{t}.{s}"] = show_de(d)
        grey = min(LINE_SET, key=lambda k: grey_dl(line, sem[k]))
        v[f"DL:line.set.{t}"] = show_de(grey_dl(line, sem[grey]))
        v[f"NEAREST:line.grey.{t}"] = f"`{grey}`"
    return v


# ---------------------------------------------------------------------------- calendar


def sprint_starts(env: Env) -> tuple[datetime.date, int]:
    cal = env.base(PATHS["CAL"])
    m = re.search(r"SPRINT01_START = datetime\.date\((\d+), (\d+), (\d+)\)", cal)
    d = re.search(r"SPRINT_DAYS = (\d+)", cal)
    if not m or not d:
        raise SystemExit("calendar_cv.py: no SPRINT01_START / SPRINT_DAYS at the base")
    return datetime.date(int(m[1]), int(m[2]), int(m[3])), int(d[1])


def sprint_date(env: Env, n: int) -> str:
    start, days = sprint_starts(env)
    return (start + datetime.timedelta(days=(n - 1) * days)).isoformat()


def _tickets(env: Env) -> list[tuple[str, str, str]]:
    """(key, sprint, body) of every E12 ticket at the base, memoised on the Env."""
    if "tickets" not in env.memo:
        data = json.loads(env.base(E12_JSON))
        env.memo["tickets"] = [
            (str(t.get("key")), str(t.get("sprint")), str(t.get("body", "")))
            for t in (data if isinstance(data, list) else [])
            if isinstance(t, dict)
        ]
    out = env.memo["tickets"]
    return out if isinstance(out, list) else []


def ticket_sprint(env: Env, key: str) -> int | None:
    for k, s, _ in _tickets(env):
        if k == key:
            m = re.search(r"(\d+)", s)
            return int(m[1]) if m else None
    return None


def date_value(env: Env, key: str) -> str | None:
    m = re.fullmatch(r"Sprint (\d+)", key)
    if m:
        return sprint_date(env, int(m[1]))
    n = ticket_sprint(env, key)
    return sprint_date(env, n) if n is not None else None


# ---------------------------------------------------------------------------- cites

CITE_KEY = r"`(?:0[25]|1[456]|2[2346])`|D0[2-6]H?(?![\w-])|E1[12]-D0\d|E08-D04|TOK-[DP]|CAL|SEED"
CITE = re.compile(rf"(?<![\w`-])({CITE_KEY}):(\d+)(?:[–-](\d+))?((?:, :\d+(?:[–-]\d+)?)*)")
CONT = re.compile(r":(\d+)(?:[–-](\d+))?")


@dataclass(frozen=True)
class Cite:
    key: str
    lo: int
    hi: int
    line_no: int  # where in the spec


def cites_in(text: str) -> list[Cite]:
    out: list[Cite] = []
    for i, ln in enumerate(text.split("\n"), 1):
        for m in CITE.finditer(strip_comments(ln)):
            key = m[1].strip("`")
            lo = int(m[2])
            out.append(Cite(key, lo, int(m[3]) if m[3] else lo, i))
            for c in CONT.finditer(m[4] or ""):
                a = int(c[1])
                out.append(Cite(key, a, int(c[2]) if c[2] else a, i))
    return out


# Load-bearing fragments: each must sit on (one of) the cited line(s) at the base.
CITED: dict[tuple[str, int], tuple[str, ...]] = {
    ("15", 2170): ('"pointfigure"', "`barMode:"),
    ("15", 2187): ('"pointfigure"',),
    ("15", 2194): ("100k+ bars, ≥58fps",),
    ("15", 2129): ("§11.3",),
    ("15", 2167): ("### CMP-181 CandleSeries",),
    ("15", 2891): ("CMP-180..199", "20"),
    ("15", 2893): ("241",),
    ("15", 2903): ("241 and 242 stay unassigned",),
    ("15", 2439): ("CMP-200..243",),
    ("15", 31): ("CMP-200..243",),
    ("15", 2689): ("one home", "time remaining until the current bar closes"),
    ("15", 2690): ("`msRemaining: number`",),
    ("15", 2692): ("No countdown for tick bars",),
    ("15", 2693): ('aria-live="off"', "1 Hz"),
    ("15", 2695): ("NonTimeBar",),
    ("15", 2654): ("aria-pressed",),
    ("15", 2702): ("composition",),
    ("15", 2710): ("catalogue-level test",),
    ("15", 435): ("a load, an export or a replay only",),
    ("15", 436): ("after 5 s",),
    ("15", 276): ("never a live region",),
    ("15", 403): ("bar-close countdown",),
    ("15", 41): ("dark/light",),
    ("15", 38): ("focus ring",),
    ("15", 438): ("Cancel a CMP-001 `ghost` `sm`",),
    ("23", 757): ("`trades` is always sent", "It defaults to false"),
    ("14", 1085): ("request window entirely before recording start",),
    ("D02", 317): ("`no_data_recorded`", "`Switch to time bars`"),
    ("D05", 257): ("reuses C-6 as the mode's description",),
    ("D06", 76): ("docs/research/_tools/cvd_simulate.py",),
    ("D06", 134): ("truncated",),
    ("D06", 403): ("ΔE76 5.0",),
    ("D06", 410): ("line vs `color.order.line`",),
    ("D06", 411): ("line vs `color.focus.ring`",),
    ("D06H", 64): ("high contrast",),
    ("15", 738): ('"inline"',),
    ("15", 472): ("description?",),
    ("15", 122): ("`suffix?`",),
    ("14", 734): ("Vol 37 / 50 BTC",),
    ("14", 736): ("rebuilding", "`Cancel` after 2 s"),
    ("14", 737): ("partial-history", "Build earlier bars"),
    ("14", 738): ("coverage-gap",),
    ("14", 743): ("Precedence",),
    ("14", 1021): ("Needs recorded prints",),
    ("14", 772): ("Candlestick",),
    ("16", 56): ("color.chart.boundary", ".hatch.texture"),
    ("05", 128): ("Chart data-ink contrast", "3:1"),
    ("16", 478): ("no near-duplicate token",),
    ("02", 53): ("an explicit Architect/CDO waiver", "with reason"),
    ("22", 17365): ("heikin_ashi", "pnf"),
    ("22", 17363): ("BarType",),
    ("22", 4166): ("heikin_ashi",),
    ("22", 4164): ("atr:14",),
    ("22", 4165): ("pnf",),
    ("22", 5036): ("recording:read",),
    ("22", 17100): ("DataMeta",),
    ("22", 17113): ("recording_started_at",),
    ("22", 20939): ("heikin_ashi", "pnf"),
    ("22", 21121): ("ChartTemplateInput",),
    ("22", 21143): ("step_line",),
    ("23", 1916): ('"barType"',),
    ("23", 1917): ('"pnf", "heikin_ashi"',),
    ("23", 2809): ("barType",),
    ("23", 2815): ('"v"', '"confirm"'),
    ("23", 2844): ('"trades"',),
    ("23", 257): ("`u32 trades`", "`include_delta`"),
    ("23", 733): ("bars.{symbol}.{bar_type}.{param}", "`include_delta`"),
    ("23", 1258): ("(generation, index)",),
    ("D02", 29): ("D-5",),
    ("D02", 32): ("Bar order · not time",),
    ("D02", 33): ("D-9",),
    ("D02", 34): ("D-10",),
    ("D02", 35): ("D-11",),
    ("D02", 78): ("**Override:**",),
    ("D02", 267): ("Vol 37 / 50 BTC",),
    ("D02", 272): ("partial-history-time",),
    ("D02", 274): ("Build earlier bars",),
    ("D02", 275): ("Load more",),
    ("D02", 276): ("coverage-gaps",),
    ("D02", 406): ("NC-1", "`Dismiss`", "cleared when a new load or build starts"),
    ("D02", 480): ("OQ-2",),
    ("D02", 492): ("OQ-14", "Closed, corrected"),
    ("D03", 29): ("V-3", "Needs recorded prints: none yet"),
    ("D03", 46): ("D3-1", "E12-S12 flag"),
    ("D03", 49): ("D3-4", "meta.recording_started_at"),
    ("D03", 62): ("Time, then Tick, Volume, Range, Delta, Renko",),
    ("D03", 73): ("`pnf`", "not offered in R1"),
    ("D03", 74): ("heikin_ashi", "refused as a bar type"),
    ("D03", 96): ("[9 Vol 50]",),
    ("D03", 209): ("C-24", "Needs recorded prints: none yet"),
    ("D03", 210): ("C-25", "Lot size not known yet"),
    ("D03", 217): ("C-32",),
    ("D03", 223): ("C-38", "Vol 50 BTC"),
    ("D03", 463): ("CR-2",),
    ("D03", 465): ("CR-4",),
    ("D03", 466): ("CR-5", "heikin_ashi:*"),
    ("D03", 467): ("CR-6", "atr:14"),
    ("D03", 468): ("CR-7",),
    ("D03", 469): ("CR-8",),
    ("D03", 474): ("DS-5",),
    ("D03", 475): ("X-1",),
    ("D03", 477): ("X-3",),
    ("D03", 479): ("X-5",),
    ("D03H", 25): ("DS-2", "`elevation.popover`"),
    ("D03H", 89): ("rows wrap, never truncate",),
    ("D04", 32): ("RULED",),
    ("D04", 38): ("no SCR-041 popover exists",),
    ("D04", 116): ("Vol 50", "[9 Vol 50]"),
    ("D04H", 43): ("A-5", "PaneIntervalCode"),
    ("D04H", 53): ("FavouritesAnyBarType",),
    ("D05", 142): ("a transform, not a wire type",),
    ("D05", 150): ("Switch to time bars",),
    ("D05", 151): ("width mapping",),
    ("D05", 170): ("one intended difference",),
    ("D05", 564): ("D05-G1",),
    ("D05", 565): ("D05-G6",),
    ("D06", 49): ("scaffold",),
    ("D06", 116): ("R-2",),
    ("D06", 121): ("R-7",),
    ("D06", 239): ("not a new chip",),
    ("D06", 264): ("`dash.2-2` ring",),
    ("D06", 272): ("**Stale**",),
    ("D06", 273): ("**Corrected**",),
    ("D06", 289): ("never hatched",),
    ("D06", 355): ("bar 3 of 5",),
    ("D06", 378): ("`color.order.line`", "`color.cvd.buy`"),
    ("D06", 384): ("no override is proposed",),
    ("D06", 562): ("D06-G1", "blocking until the CMP-181 A-row lands"),
    ("D06", 565): ("D06-Q1", "Switch to time bars"),
    ("D06", 566): ("D06-Q2", "outline-only fallback"),
    ("D06", 581): ("Q10 hatch",),
    ("D06H", 29): ("A-1 … A-7", "the owner's sign-off PR"),
    ("D06H", 49): ("HeikinAshiOnNonTime",),
    ("D06H", 50): ("the option set equals CMP-181 `chartType`",),
    ("D06H", 58): ("`color.chart.line`",),
    ("D06H", 60): ("`dash.1-1`",),
    ("D06H", 68): ("InvertedConvention",),
    ("D06H", 89): ("No `color.chart.baseline.*`",),
    ("E11-D02", 118): ("D11",),
    ("E11-D02", 417): ("Zoomed out · 1 column = 12 bars",),
    ("E11-D02", 422): ("Chip order",),
    ("E11-D04", 967): ("O-11", "#242"),
    ("E11-D05", 315): ("`pattern.hatch.gap`",),
    ("E08-D04", 15): ("semantic-{dark,light,hc}.tokens.json",),
    ("TOK-D", 272): ("{palette.purple.500}",),
    ("TOK-P", 184): ("#8B5CF6",),
    ("SEED", 242): ("recording:read",),
    ("SEED", 239): ('"viewer"',),
    ("CAL", 13): ("SPRINT01_START",),
}


def cite_problems(env: Env, text: str) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    """(FAILs, drifted) for every cite: a gone or blank line, or a missing CITED fragment."""
    bad: list[tuple[str, int]] = []
    drift: list[tuple[str, int]] = []
    head_ok = env.head_resolves()
    for c in cites_in(text):
        base = env.base(PATHS[c.key]).split("\n")
        if c.hi < c.lo or c.hi > len(base) or any(not base[n - 1].strip() for n in (c.lo, c.hi)):
            bad.append((f"{c.key}:{c.lo}-{c.hi} is gone or blank at {BASE}", c.line_no))
            continue
        for n in range(c.lo, c.hi + 1):
            for frag in CITED.get((c.key, n), ()):
                if frag not in "\n".join(base[c.lo - 1 : c.hi]):
                    bad.append((f"{c.key}:{n} no longer holds {frag!r}", c.line_no))
        if head_ok:
            head = (env.show(HEAD_REF, PATHS[c.key]) or "").split("\n")
            if head[c.lo - 1 : c.hi] != base[c.lo - 1 : c.hi]:
                drift.append((f"{c.key}:{c.lo}-{c.hi} drifted at {HEAD_REF}", c.line_no))
    return bad, drift


# ---------------------------------------------------------------------------- the pack's tables


def sec(spec: str, key: str) -> str:
    return sections(spec).get(key, "")


def c_rows(spec: str) -> list[list[str]]:
    return table_after(sec(spec, "C"), "A")


def a_row(spec: str, aid: str) -> list[str] | None:
    for r in c_rows(spec):
        if r and r[0] == aid:
            return r
    return None


BR = " <br> "


def story_names(spec: str, aid: str) -> list[str]:
    """The story names of an A-row's Storybook line (New), title and theme note dropped."""
    r = a_row(spec, aid)
    if not r or len(r) < 6:
        return []
    new = unescape(r[5])
    m = re.search(
        r"\*\*Storybook\*\*:\s*(?:`[^`]*` — )?(.*?)(?: \((?:every|band|the)[^()]*\))?\.?$", new
    )
    if not m:
        return []
    body = re.sub(r"\([^()]*\)", "", m[1])
    return [x.strip() for x in body.split(",") if x.strip()]


def entry_story_names(spec: str) -> list[str]:
    r = a_row(spec, "A-44")
    if not r or len(r) < 6:
        return []
    for part in unescape(r[5]).split(BR):
        m = re.match(r"- \*\*Storybook\*\*: `[^`]*` — (.*?) \(every", part)
        if m:
            return [x.strip() for x in m[1].split(",")]
    return []


def log_ids(spec: str) -> list[str]:
    ids: list[str] = []
    for r in table_after(sec(spec, "13"), "Ids"):
        ids += [x.strip() for x in r[0].split(",") if x.strip()]
    return ids


def walk_owner_items(spec: str) -> list[str]:
    m = re.search(r"\(d\) The owner walkthrough on #244\*\* \([^)]*\): (.*?)\. Record", spec)
    return [x.strip() for x in m[1].split(";")] if m else []


@dataclass
class Values:
    v: dict[str, str]


def count_values(spec: str, reg: str) -> dict[str, str]:
    out: dict[str, str] = {}
    out["COUNT:ledger"] = str(len(table_after(sec(spec, "2"), "Row of record")))
    out["COUNT:arows"] = str(len(c_rows(spec)))
    out["COUNT:log.ids"] = str(len(log_ids(spec)))
    walk = walk_rows(spec)
    out["COUNT:walk.rows"] = str(len(walk))
    for i, k in ((2, "needs"), (3, "found"), (4, "nf")):
        out[f"COUNT:walk.{k}"] = str(sum(int(r[i]) for r in walk if r[i].isdigit()))
    out["COUNT:walk.owner"] = str(len(walk_owner_items(spec)))
    out["COUNT:mutations"] = str(len(MUTATIONS))
    try:
        modes = json.loads(reg).get("modes", [])
    except (ValueError, AttributeError):
        modes = []
    out["COUNT:registry.offered"] = str(
        sum(1 for m in modes if isinstance(m, dict) and m.get("offered") is True)
    )
    for cmp_, aid in (
        ("cmp181", "A-6"),
        ("cmp220", "A-13"),
        ("cmp222", "A-19"),
        ("cmp226", "A-23"),
    ):
        out[f"COUNT:stories.{cmp_}"] = str(len(story_names(spec, aid)))
    out["COUNT:stories.cmp248"] = str(len(entry_story_names(spec)))
    return out


def compute(env: Env, spec: str, reg: str) -> dict[str, str]:
    v = token_values(env)
    v.update(count_values(spec, reg))
    for key in set(re.findall(r"(?:\{\{|<!--=)DATE:([^}>]+?)(?:\}\}|-->)", spec)):
        d = date_value(env, key)
        if d:
            v[f"DATE:{key}"] = d
    return v


def code_spans(line: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in CODE.finditer(line)]


def fill(text: str, values: dict[str, str]) -> tuple[str, list[str]]:
    """Write every placeholder outside a code span as `VALUE<!--=KEY-->`; re-fill anchors."""
    missing: list[str] = []
    out_lines = []
    for ln in text.split("\n"):
        spans = code_spans(ln)

        def outside(pos: int, spans: list[tuple[int, int]] = spans) -> bool:
            return not any(a <= pos < b for a, b in spans)

        def ph(m: re.Match[str]) -> str:
            if not outside(m.start()):
                return m[0]
            if m[1] not in values:
                missing.append(m[1])
                return m[0]
            return f"{values[m[1]]}<!--={m[1]}-->"

        ln = PLACEHOLDER.sub(ph, ln)
        out_lines.append(ln)
    text = "\n".join(out_lines)

    # refresh anchored values: VALUE<!--=KEY--> where VALUE is the computed one
    def refresh(m: re.Match[str]) -> str:
        key = m[2]
        if key not in values:
            return m[0]
        return f"{values[key]}<!--={key}-->"

    text = re.sub(r"(`[^`\s]*`|[^\s|(/·]*?)<!--=([A-Z]+:[^>]+?)-->", refresh, text)
    return text, missing


def unfill(text: str) -> str:
    """The text with every anchored value cut (the pins' form)."""
    return re.sub(r"(`[^`\s]*`|[^\s|(/·]*?)<!--=([A-Z]+:[^>]+?)-->", r"<!--=\2-->", text)


def anchored(text: str) -> list[tuple[str, str, int]]:
    """(value, key, line) of every anchor."""
    out = []
    for i, ln in enumerate(text.split("\n"), 1):
        for m in re.finditer(r"(`[^`\s]*`|[^\s|(/·]*?)<!--=([A-Z]+:[^>]+?)-->", ln):
            out.append((m[1], m[2], i))
    return out


# ---------------------------------------------------------------------------- pins

Unit = tuple[str, str, str]  # (region, location, normalised text)
FULL_STOP = re.compile(r"(?<=[.!?])\s+(?=[*`\"(A-Z0-9§])")


def pin_norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def line_form(line: str) -> str:
    if re.match(r"^\s*[-*+] ", line):
        return "b"
    if re.match(r"^\s*\d+\. ", line):
        return "n"
    return "p"


def units(text: str) -> list[Unit]:
    """Every unit of the pack: per region (the heading path, `#n` its occurrence), the heading, the
    line shape, each rule line, each table row by its lead cell and each prose sentence."""
    out: list[Unit] = []
    path: list[tuple[int, str]] = []
    seen_regions: dict[str, int] = {}
    region, k, shape = "(top)#1", 0, ""
    rows: dict[str, int] = {}
    in_fence = False
    for raw in unfill(text).split("\n"):
        if FENCE.match(raw):
            in_fence = not in_fence
            shape += "f"
            out.append((region, f"fence-line {shape.count('f')}", pin_norm(raw)))
            continue
        if in_fence:
            shape += "f"
            out.append((region, f"fence-line {shape.count('f')}", raw))
            continue
        m = HEADING.match(raw)
        if m:
            out.append((region, "shape", shape))
            level = len(m[1])
            path = [p for p in path if p[0] < level] + [(level, pin_norm(m[2]))]
            key = " › ".join(p[1] for p in path)
            seen_regions[key] = seen_regions.get(key, 0) + 1
            region, k, shape, rows = f"{key}#{seen_regions[key]}", 0, "h", {}
            out.append((region, "heading", pin_norm(raw)))
            continue
        if not raw.strip():
            shape += "."
        elif RULE.match(raw):
            shape += "r"
            out.append((region, f"rule {shape.count('r')}", pin_norm(re.sub(r"-+", "-", raw))))
        elif raw.lstrip().startswith("|"):
            indent = len(raw) - len(raw.lstrip())
            shape += (f">{indent}" if indent else "") + "t"
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


def write_pins(us: list[Unit]) -> str:
    head = (
        "# E12-D09 pins (every unit of the pack): region (heading path #occurrence), location, "
        f"the exact normalised text; {len(us)} units.\n# Written by `--repin-ruled` only; "
        "`--check` reads it (never hand-edit; see the tool's G-RULED-PIN).\n"
    )
    return head + "".join("\t".join(u) + "\n" for u in us)


def parse_pins(text: str) -> list[Unit]:
    out: list[Unit] = []
    for ln in text.split("\n"):
        parts = ln.split("\t")
        if ln and not ln.startswith("#") and len(parts) == 3:
            out.append((parts[0], parts[1], parts[2]))
    return out


def region_sec(region: str) -> str:
    parts = region.rsplit("#", 1)[0].split(" › ")
    return sec_no(parts[1]) if len(parts) > 1 else "(top)"


def pin_problems(pinned: list[Unit], current: list[Unit]) -> list[tuple[str, str]]:
    """(message, section) per region that differs: one finding per region."""
    bad: list[tuple[str, str]] = []
    old_r = list(dict.fromkeys(u[0] for u in pinned))
    new_r = list(dict.fromkeys(u[0] for u in current))
    for r in new_r:
        if r not in old_r:
            bad.append((f"region '{r[-60:]}' is unpinned (new)", region_sec(r)))
    for r in old_r:
        if r not in new_r:
            bad.append((f"region '{r[-60:]}' deleted or renamed", region_sec(r)))
    common = [r for r in new_r if r in old_r]
    if common != [r for r in old_r if r in new_r]:
        bad.append(("a pinned region moved (the heading order changed)", "(top)"))
    for r in common:
        was = [(u[1], u[2]) for u in pinned if u[0] == r]
        now = [(u[1], u[2]) for u in current if u[0] == r]
        if was == now:
            continue
        wd, nd = dict(was), dict(now)
        what = "changed"
        for loc, txt in now:
            if loc not in wd:
                what = f"{loc} unpinned (new): {txt[:50]!r}"
                break
            if wd[loc] != txt:
                what = f"{loc} changed: {txt[:50]!r}"
                break
        else:
            gone = [loc for loc, _ in was if loc not in nd]
            what = f"{gone[0]} deleted" if gone else "units moved or reordered"
        bad.append((f"'{r[-50:]}' {what}", region_sec(r)))
    return bad


# ---------------------------------------------------------------------------- findings


@dataclass(frozen=True)
class Finding:
    level: str  # FAIL, WARN or NOTE
    gate: str
    msg: str
    sec: str | None = None


@dataclass
class Texts:
    spec: str
    reg: str
    pins: str | None
    tool: str
    values: dict[str, str]
    env: Env


def one(gate: str, problems: list[str], sec_: str | None = None) -> list[Finding]:
    """Each gate reports one FAIL line: its first problem and the count of the rest."""
    if not problems:
        return []
    more = f" (+{len(problems) - 1} more)" if len(problems) > 1 else ""
    return [Finding("FAIL", gate, problems[0] + more, sec_)]


def ruled_key(spec: str) -> str:
    for k in sections(spec):
        if k.startswith("The thirty-four questions"):
            return k
    return "RULED"


QUOTED = re.compile(r'"([^"\n]*)"|“([^”\n]*)”')
NEG = re.compile(r"\b(?:no|never|not|nor|without|none|nothing|cannot)\b")
CLAUSE_BREAK = re.compile(r"[,;:(—–]|\bbut\b|\byet\b|\bthough\b|\balthough\b")


def corpus(env: Env) -> str:
    """Every merged text a quote may come from (the plan texts, the design docs, the ticket JSON),
    read at the base; memoised on the Env."""
    if "corpus" not in env.memo:
        texts = [env.show(BASE, rel) or "" for rel in sorted(set(PATHS.values()))]
        env.memo["corpus"] = norm("\n".join(texts + [env.show(BASE, E12_JSON) or ""]))
    out = env.memo["corpus"]
    return out if isinstance(out, str) else ""


def attributed(q: str, env: Env | None) -> bool:
    if env is None or not q:
        return False
    seen = env.memo.setdefault("quotes", {})
    if not isinstance(seen, dict):
        return False
    if q not in seen:
        seen[q] = q in corpus(env)
    return bool(seen[q])


def unquote(text: str, env: Env | None) -> str:
    """Drop a quote only when it is attributed: its words stand verbatim in a merged text. A quote
    no merged text holds is the pack's own claim and is read (quote laundering, X-31)."""

    def cut(m: re.Match[str]) -> str:
        q = norm(m[1] if m[1] is not None else m[2])
        return " " if attributed(q, env) else " " + q + " "

    return QUOTED.sub(cut, text)


def live(text: str, term: str, env: Env | None = None) -> bool:
    """`term` asserted in `text`: attributed quotes dropped; a mention counts as negated only when
    a negation stands in its own clause, at most four words before it (X-07: "not waiting, the
    owner approved" is a live claim)."""
    return live_plain(plain(unquote(text, env)), term)


def live_plain(t: str, term: str) -> bool:
    """`live` on a clause already through `plain(unquote(...))`."""
    for m in re.finditer(term, t):
        head = t[: m.start()]
        cut = [b.end() for b in CLAUSE_BREAK.finditer(head)]
        clause = head[cut[-1] :] if cut else head
        before = clause.split()[-4:]
        if not any(NEG.fullmatch(w.strip(",;:()")) for w in before):
            return True
    return False


def new_cells(spec: str) -> dict[str, str]:
    return {r[0]: unescape(r[5]) for r in c_rows(spec) if len(r) >= 6}


# ---------------------------------------------------------------------------- the gates


def g_anchor(t: Texts) -> list[Finding]:
    bad = []
    for val, key, n in anchored(t.spec):
        if key not in t.values:
            bad.append(f"line {n}: anchor {key} is not a value the tool computes")
        elif val != t.values[key]:
            bad.append(f"line {n}: {key} reads {val!r}, the tool computes {t.values[key]!r}")
    for i, ln in enumerate(t.spec.split("\n"), 1):
        if PLACEHOLDER.search(without_code(ln)):
            bad.append(f"line {i}: a placeholder is unfilled (run --fill)")
    return one("G-ANCHOR", bad)


def g_marker(t: Texts) -> list[Finding]:
    bad = [
        f"a comment that is not a value anchor: {m[0][:40]!r}"
        for m in COMMENT.finditer(t.spec)
        if not ANCHOR.fullmatch(m[0])
    ]
    return one("G-MARKER", bad)


RATIO = re.compile(r"(?<![\w.])\d+\.\d+:1\b|(?<![\w.])\d+\.\d\d(?= ?/ ?\d)")
HEX = re.compile(r"(?<![\w&])#[0-9A-Fa-f]{6}(?![0-9A-Za-z])")


def g_figure(t: Texts) -> list[Finding]:
    """A ratio or hex typed by hand (outside an anchor, a code span and §C's Old cells; a New cell
    may repeat its Old cell's figures)."""
    bad = []
    cut = re.sub(r"(`[^`\s]*`|[^\s|(/·]*?)<!--=[A-Z]+:[^>]+?-->", " ", t.spec)
    old_by_id = {r[0]: unescape(r[4]) for r in c_rows(t.spec) if len(r) >= 6}
    for i, ln in enumerate(cut.split("\n"), 1):
        body = without_code(ln)
        allowed: str = ""
        if ln.startswith("| A-"):
            cells = split_row(ln)
            if len(cells) >= 6:
                allowed = old_by_id.get(cells[0], "")
                body = without_code(unescape(cells[5]))
        for m in list(RATIO.finditer(body)) + list(HEX.finditer(body)):
            if m[0] not in allowed:
                bad.append(f"line {i}: {m[0]!r} is typed by hand (use a placeholder)")
    return one("G-FIGURE", bad)


def g_cite(t: Texts) -> list[Finding]:
    bad, _ = cite_problems(t.env, t.spec)
    return one("G-CITE", [f"line {n}: {m}" for m, n in bad])


def g_version(t: Texts) -> list[Finding]:
    bad: list[str] = []
    if not t.env.head_resolves():
        return one("G-VERSION", [f"{HEAD_REF} does not resolve: the drift check cannot run"])
    _, drift = cite_problems(t.env, t.spec)
    bad += [f"line {n}: {m}" for m, n in drift]
    vline = next((ln for ln in t.spec.split("\n") if "**Version line**" in ln), "")
    for key, sha in VERSION_PINS.items():
        rel = PATHS[key]
        at_base = t.env.last_commit(BASE, rel)
        if not at_base.startswith(sha):
            bad.append(
                f"{key}'s last commit at the base is {at_base[:10]}, the version line pins {sha}"
            )
        if t.env.last_commit(HEAD_REF, rel) != at_base:
            bad.append(f"{key} changed at {HEAD_REF} after the base: a late change (§0)")
        if f"`{sha}`" not in vline:
            bad.append(f"the version line does not pin {key} at `{sha}`")
    for rel in DRIFT_INPUTS:
        if t.env.last_commit(HEAD_REF, rel) != t.env.last_commit(BASE, rel):
            bad.append(f"{rel} changed at {HEAD_REF} after the base: a late change (§0)")
    return one("G-VERSION", bad, "0")


def g_untouched(t: Texts) -> list[Finding]:
    mb = t.env.mb()
    if not mb:
        return one("G-UNTOUCHED", [f"`git merge-base HEAD {HEAD_REF}` does not resolve"])
    bad = []
    for p in t.env.changed_paths(mb):
        if p in UNTOUCHED or p.startswith(UNTOUCHED_PREFIX):
            bad.append(f"{p} changed against the merge-base: the pack PR must not edit it")
        elif p not in OWN_PATHS:
            bad.append(f"{p} changed against the merge-base: outside the pack's four files")
    return one("G-UNTOUCHED", bad)


def g_wordcount(t: Texts) -> list[Finding]:
    bad = []
    n = t.spec.count("\n")
    if n > LINE_BUDGET:
        bad.append(f"the pack has {n} lines; BQ-4's budget is {LINE_BUDGET}")
    if len(PR_TITLE) > 100 or f"`{PR_TITLE}`" not in t.spec:
        bad.append("D2's PR title is missing, altered or over 100 characters")
    items = walk_owner_items(t.spec)
    if not items or len(items) > WALK_MAX:
        bad.append(f"the owner walkthrough has {len(items)} items; at most {WALK_MAX}")
    return one("G-WORDCOUNT", bad)


# the twelve explicit confirmations of the ruling of record, carried exactly as worded:
# sha256 (first 16 hex) of each line, whitespace-collapsed
TWELVE_SHA = (
    "2e69b7f99f4f8f04",
    "ccd22643da94b142",
    "799b6caed9949097",
    "93cc1bf31ecb5cc3",
    "61c8c6a1876af667",
    "d1fc587072aec72c",
    "4cd0abccaf580aee",
    "04f0429cd518a815",
    "310726a2e34dea07",
    "8a6920efea93444b",
    "92d1caf554924709",
    "a744507b7c33c44e",
)
# the ruling delta of LANE-hcl1-163 (11:26Z): BQ-16's HistoryMarker is CMP-248, since CMP-244 is
# E10-D02's proposed HotkeyConflictChip; TWELVE_SHA hashes the ruling's own words, so BQ-16 is
# hashed with the id mapped back
REID_NEW, REID_OLD = "CMP-248", "CMP-244"
REID_LINE = "ruling 6465614406, BQ-16 re-id'd to CMP-248 at 11:26Z (LANE-hcl1-163)"


def un_reid(ln: str) -> str:
    return ln.replace(REID_NEW, REID_OLD) if ln.startswith("- **BQ-16 ") else ln


# names and copy quoted from merged texts: (string, source, line); each must sit on its line at the
# base and appear in the pack verbatim
QUOTES: tuple[tuple[str, str, int], ...] = (
    ("Needs recorded prints: none yet", "D03", 209),
    ("Lot size not known yet", "D03", 210),
    ("Checking recorded prints…", "D03", 214),
    ("Not available yet", "D03", 211),
    ("Bar order · not time", "D02", 32),
    ("Vol 37 / 50 BTC", "D02", 267),
    ("No countdown for tick bars", "15", 2692),
    ("a load, an export or a replay only", "15", 435),
    ("rows wrap, never truncate", "D03H", 89),
    ("not a new chip", "D06", 239),
    ("a transform, not a wire type", "D05", 142),
    ("Switch to time bars", "D05", 150),
    ("the option set equals CMP-181 `chartType`", "D06H", 50),
    ("blocking until the CMP-181 A-row lands", "D06", 562),
    ("no near-duplicate token", "16", 478),
    ("an explicit Architect/CDO waiver", "02", 53),
    ("Couldn't load older bars · Retry", "D02", 409),
    ("Build earlier bars", "D02", 274),
    ("Load more", "D02", 275),
    ("Zoomed out · high–low only", "D06", 250),
    ("Zoomed out · 1 column = ", "E11-D02", 417),
    ("one home", "15", 2689),
)
NEW_STORIES = {
    "A-6": ("PartialHistoryBoundary",),
    "A-19": ("HeikinAshiFootprintCallout", "WidthMappingOff"),
    "A-23": (
        "NonTimeTick", "NonTimeVolume", "NonTimeRange", "NonTimeDelta", "NonTimeRenko",
        "NonTimeRangeNoTickSize", "NonTimeDeltaNoIncludeDelta", "NonTimeStaleFrozen",
    ),
}  # fmt: skip
STORY_SRC: dict[str, tuple[tuple[str, int, int], ...]] = {
    "A-6": (("D06H", 68, 68),),
    "A-13": (("15", 2638, 2638), ("D03H", 35, 45), ("D04H", 53, 53)),
    "A-19": (("D06H", 49, 49),),
    "A-23": (("15", 2695, 2695),),
}


def base_lines(env: Env, key: str, lo: int, hi: int) -> str:
    return "\n".join(env.base(PATHS[key]).split("\n")[lo - 1 : hi])


def g_quote(t: Texts) -> list[Finding]:
    bad: list[str] = []
    ruled = sections(t.spec).get(ruled_key(t.spec), "")
    got = [
        hashlib.sha256(" ".join(un_reid(ln).split()).encode()).hexdigest()[:16]
        for ln in ruled.split("\n")
        if ln.startswith("- **BQ-")
    ]
    if tuple(got) != TWELVE_SHA:
        bad.append("the twelve explicit confirmations are not carried exactly as worded")
    cat = t.env.base(PATHS["15"])
    body = "\n".join(ln for ln in t.spec.split("\n") if not ln.startswith("| A-"))
    for m in re.finditer(r"\bCMP-(\d{3}) ([A-Z][a-z]+[A-Z][A-Za-z]*)\b", strip_comments(body)):
        if m[1] == "248":
            continue
        if not re.search(rf"^### CMP-{m[1]} {m[2]}\b", cat, re.MULTILINE):
            bad.append(f"`CMP-{m[1]} {m[2]}` is not the catalogue's name for CMP-{m[1]}")
    for s, key, n in QUOTES:
        if s not in base_lines(t.env, key, n, n):
            bad.append(f"{key}:{n} no longer holds {s!r}")
        if s not in t.spec:
            bad.append(f"the pack does not quote {s!r} verbatim")
    for aid, srcs in STORY_SRC.items():
        pool = "\n".join(base_lines(t.env, k, lo, hi) for k, lo, hi in srcs)
        for name in story_names(t.spec, aid):
            if name not in NEW_STORIES.get(aid, ()) and not re.search(
                rf"\b{re.escape(name)}\b", pool
            ):
                bad.append(f"{aid}'s story {name!r} is in no merged list")
    return one("G-QUOTE", bad)


CHARSET_NFKC_OK = frozenset("…")


def g_charset(t: Texts) -> list[Finding]:
    bad = []
    for doc, text in (("pack", t.spec), ("registry", t.reg)):
        if "\r" in text or "\t" in text:
            bad.append(f"{doc}: a CR or a tab")
        for i, ln in enumerate(text.split("\n"), 1):
            if ln != ln.rstrip():
                bad.append(f"{doc} line {i}: trailing whitespace")
            for ch in ln:
                if ch.isascii():
                    continue
                cat_ = unicodedata.category(ch)
                name = unicodedata.name(ch, "")
                if cat_[0] in "CZ" or (cat_[0] == "L" and not name.startswith("LATIN")):
                    bad.append(f"{doc} line {i}: U+{ord(ch):04X} {name or cat_} is not allowed")
                elif unicodedata.normalize("NFKC", ch) != ch and ch not in CHARSET_NFKC_OK:
                    bad.append(f"{doc} line {i}: U+{ord(ch):04X} is a compatibility character")
            if re.search(r" [.,;](?:\s|$)", CODE.sub("x", ln)):
                bad.append(f"{doc} line {i}: a space before a full stop, comma or semicolon")
    return one("G-CHARSET", bad)


def g_cells(t: Texts) -> list[Finding]:
    bad = []
    width = 0
    for i, ln in enumerate(t.spec.split("\n"), 1):
        if not ln.startswith("|"):
            width = 0
            continue
        n = len(split_row(ln))
        if width == 0:
            width = n
        elif n != width:
            bad.append(f"line {i}: {n} cells where the table has {width}")
    return one("G-CELLS", bad)


CLOSING = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b:?\s+(?:[\w.-]+/[\w.-]+)?#\d+", re.IGNORECASE
)


def g_close(t: Texts) -> list[Finding]:
    bad = [
        f"line {i}: a closing keyword: {m[0]!r} (PR 1 carries `Refs #244` only)"
        for i, ln in enumerate(t.spec.split("\n"), 1)
        for m in CLOSING.finditer(without_code(ln))
    ]
    bad += [f"registry: a closing keyword: {m[0]!r}" for m in CLOSING.finditer(t.reg)]
    return one("G-CLOSE", bad)


URLS = re.compile(r"\bhttps?://|\bwww\.[a-z]|/home/|file://|\\\\", re.IGNORECASE)


def g_url(t: Texts) -> list[Finding]:
    bad = [
        f"line {i}: a URL, host or local path"
        for i, ln in enumerate(t.spec.split("\n"), 1)
        if URLS.search(ln)
    ]
    if URLS.search(t.reg):
        bad.append("registry: a URL, host or local path")
    return one("G-URL", bad)


UNBUILT = (
    "**The bar-mode and series components are unbuilt.** `packages/chart-engine/src` is a scaffold"
    " (D06:49), no SCR-041 popover exists in `apps/web` (D04:38), and no CMP-181, CMP-220, CMP-222"
    " or CMP-226 component ships"
)


def g_unbuilt(t: Texts) -> list[Finding]:
    ok = UNBUILT in sec(t.spec, "0")
    return one(
        "G-UNBUILT", [] if ok else ["§0 does not state that the components are unbuilt"], "0"
    )


def g_unmerged(t: Texts) -> list[Finding]:
    bad = []
    for i, ln in enumerate(t.spec.split("\n"), 1):
        if re.search(r"E12-D0[78](?:-handoff)?\.md|E35-D05\.md|\bE12-D0[78]:\d", ln):
            bad.append(f"line {i}: an unmerged doc is cited or linked")
        for num in UNMERGED:
            for m in re.finditer(re.escape(num) + r"(?!\d)", ln):
                tail = ln[m.end() : m.end() + 40]
                if re.match(r"[^.;|]*?`[0-9a-f]{7,40}`", tail) or re.match(r"\s*[:'’]s? \"", tail):
                    bad.append(f"line {i}: {num} is pinned or quoted; unmerged work is named only")
    return one("G-UNMERGED", bad)


def g_heuristic(t: Texts) -> list[Finding]:
    bad = []
    if WALK_HEURISTIC not in sec(t.spec, "14"):
        bad.append("§14's not-found findings are not labelled `(heuristic)`")
    if "**AC3's finding (heuristic):**" not in sec(t.spec, "8"):
        bad.append("§8's AC3 finding is not labelled `(heuristic)`")
    if "recorded as conforming `(heuristic)`" not in sec(t.spec, "10"):
        bad.append("§10's board-08 check is not labelled `(heuristic)`")
    return one("G-HEURISTIC", bad)


# Ruled sentences REQUIRED verbatim in their section (so a paraphrase FAILs even after a repin);
# "RULED" stands for the ruling's section.
REQUIRED: dict[str, tuple[str, ...]] = {
    "(top)": (
        "**Owner approval pending (#2701)**",
        "nothing here claims it",
        "Unmerged work is named only",
        "every finding is labelled `(heuristic)`",
    ),
    "RULED": (
        "Every default is taken as proposed.",
        (
            "The carried rulings C1–C11 are confirmed by analogy with #940's ruling 6463491974,"
            " and deviations D1–D4 are accepted as written"
        ),
        "**The two OWNER items** are PROPOSED, owner approval pending (#2701)",
        (
            "**BQ-9** records the enum diff as not clean and routes G-E1 and G-E2 to their owning"
            " tickets"
        ),
        "BQ-23 → A-39 … A-41 and §11 (CMP-188: no change); C-n → A-38",
    ),
    "0": (
        "no new Penpot page and no boards PR",
        "**v1 at base `8f652abb16`**",
        "The first expected deltas are #242, #243 and the BQ-28 rulings.",
        "the PR body embeds those PNGs pinned to the base `8f652abb16` (BQ-29)",
    ),
    "2": (
        "held (owner): D04-C14, D05-C23; `15` keeps #4719's text",
        "applied-as-amended (BQ-10: `pnf`, not `pointfigure`)",
    ),
    "3": (
        (
            "One new entry; every other item is a variant, an amendment, a composition or a named"
            " pattern, each row with its rejected alternative."
        ),
    ),
    "4": (
        (
            '`barMode` takes the wire spelling `"time" | "tick" | "volume" | "range" | "delta" |'
            ' "renko" | "pnf"`, `pnf` held: not offered in R1 (D03:73)'
        ),
        '**The "Needs recorded prints" state reads `meta.recording_started_at`**',
        '"recorded or not, since when"',
        "this pack places none and logs a Q-row",
    ),
    "5": (
        'This is AC4\'s "exactly a defined thing"',
        (
            "numbers are floored to the field's precision, so the text never reads"
            ' "50 / 50" before the close'
        ),
        '"No countdown: bars close on activity, not time" (PROPOSED)',
        'D06H A-7\'s title "No countdown for tick bars" is retired: tick bars do have a target',
        "A stale feed freezes the text and the status row's stale chip speaks for it",
        (
            "The host floors `done` and `target` to the field's display precision (whole numbers"
            " in this release, D03 D3-13) and passes them as strings"
        ),
        "The host subscribes delta bars with `include_delta: true` (PROPOSED)",
        "the opt-in 10 s announcement does not fire, since no close time can be predicted",
    ),
    "6": (
        "CMP-248 extends band 7A",
        "Chart-primitive with a DOM surrogate",
        "`pattern.hatch.gap` PROPOSED, never hatched for a boundary",
        "**D08's hi-fi is G-D08-1.**",
        "text-bearing and focusable in the chart's `Tab` order",
        "the action a `button`, both ringed by `color.focus.ring` at `border.focus` (`15`:38)",
    ),
    "7": (
        "The update cadence is at most 4 Hz (PROPOSED, T Perf).",
        (
            "So `Cancel` sits on the strip, not on CMP-038, and C-k goes to CMP-038's owner"
            " (E05-S02, #265) rather than widening CMP-038 here."
        ),
        "The determinate phase needs the G-2 build contract",
        "(as CMP-038's Cancel, `15`:438)",
    ),
    "8": (
        "(BQ-19, OWNER: PROPOSED, owner approval pending (#2701))",
        (
            "**Default: accept** `color.chart.line` as a semantic slot aliasing the primitive,"
            " not a new value: the duplicate is a value, not a role"
        ),
        "no token JSON edit",
        "adopted by reference, not re-proposed",
        "**Refused, recorded:**",
        "This departs from the letter of `16`:478",
        "**Rejected alternatives:**",
        (
            "**CVD criterion** (D06:403): every CVD distance to the set clears CIE76 5.0 in every"
            " theme"
        ),
    ),
    "9": (
        "(BQ-9): not clean",
        "**G-E1** to E12-S12 (#535) and the `22` / `23` owners",
        "**G-E2** to E12-S07 (#533) and the `22` owner",
        "no ticket is filed",
    ),
    "10": (
        '**"Identical" means one string per key wherever shown;**',
        "absence is not a divergence",
        '(the "shown on" row, one cell per column)',
        "**the table is complete except SCR-045.**",
        "**SCR-045 is G-D07-1, to confirm when #242 merges**",
        "two declared forms of one key, not a divergence",
        "proposed to QA as a comment on E12-Q03 (#419)",
    ),
    "11": (
        '"no component emits analytics; screens do"',
        "the pattern updates at most 4 Hz (PROPOSED)",
        "**CMP-188 PriceAxis** (BQ-23): no change",
        "D06H §D's rule (D06H:64), stricter than `15`:41's dark / light × density",
    ),
    "12": ("applied by PR 2 (BQ-5), owner approval pending (#2701)",),
    "13": ("never an agent) and a due date", "Nothing is filed.", '"Closed, corrected"'),
    "14": (
        "No session took place and none is claimed.",
        (
            "folded from its merged source (the target row names it) or carried as a G-row"
            " with its owner"
        ),
        "at most ten",
    ),
    "16": (
        "(BQ-33: PROPOSED, owner approval pending (#2701))",
        "with `Refs #244` and `Partial: PR 1 of 2` and no closing keyword",
        "**Deviations, accepted as written.**",
    ),
    "C": (
        "Old is the whole current line at the base, verbatim",
        "A-38 … A-41 wait for ACK-1.",
    ),
}
# REQUIRED strings that must close their sentence or clause: an appended qualifier FAILs (X-02,
# X-04, X-10, X-29, X-32); a string ending in "." is matched without it, then closed
CLOSED = frozenset(
    {
        "Every default is taken as proposed.",
        "A stale feed freezes the text and the status row's stale chip speaks for it",
        "The update cadence is at most 4 Hz (PROPOSED, T Perf).",
        "adopted by reference, not re-proposed",
        "absence is not a divergence",
        "No session took place and none is claimed.",
        "Nothing is filed.",
    }
)
# Synonym sets FORBIDDEN as live claims (attributed quotes dropped; a negation in the mention's
# own clause removes it); they read every section, the RULED one included (X-09), but §12 (the
# conflicts) and §15 (the mutations). Each X-n is a paraphrase lens 2 planted that survived a
# repin before this set grew; the self-test plants each again (M-77 ... M-98).
FORBIDDEN: tuple[tuple[str, str], ...] = (
    (
        (
            r"\b(?:owner|orchestrator|cdo|design-system team|a11y design lead) (?:has |had |have |"
            r"now )?(?:approved|signed off|accepted|ratified|endorsed|okayed|cleared)\b"
        ),
        "a sign-off",
    ),
    (
        (
            r"\b(?:approved|accepted|signed off|ratified|endorsed|okayed|cleared|confirmed) by "
            r"(?:the )?(?:owner|orchestrator|cdo|design-system team|a11y design lead)\b"
        ),
        "a sign-off (passive, X-05)",
    ),
    (
        (
            r"\b(?:owner|orchestrator|cdo) (?:has |had )?(?:gave|given|granted|issued) (?:the |its "
            r"|their |a )?(?:go-ahead|approval|sign-off|ok|okay|green light|nod)\b|\bgo-ahead\b|"
            r"\bgreen[- ]li(?:ght|t)\b|\brubber-stamped\b"
        ),
        "a sign-off (X-08)",
    ),
    (
        (
            r"\b(?:sign-off|approval|acceptance) (?:is |was |has been |have been )?(?:recorded|"
            r"given|granted|obtained|received|in hand|secured)\b"
        ),
        "a sign-off",
    ),
    (
        (
            r"\b(?:session|walkthrough|walk|review|meeting|call) (?:is |are |was |were |has been "
            r")?(?:held|took place|ran|happened|conducted|completed)\b|\bwas walked\b|"
            r"\b(?:owner|orchestrator|cdo|"
            r"reviewers?|participants?|we) (?:walked|reviewed|attended|met|discussed|tested|"
            r"tried)\b"
        ),
        "a session (X-10)",
    ),
    (r"\b(?:participants?|interviewees?) (?:said|noted|reported|found)\b", "a participant"),
    (
        (
            r"\bknown divergences?\b|\brecorded as known\b|\b(?:accepted|tolerated|allowed|"
            r"permitted|waived|expected) divergences?\b|\bdivergences? (?:is |are |was |were |has "
            r"been |stays |remains )?(?:accepted|tolerated|allowed|permitted|waived|ok|fine|"
            r"expected|acceptable)\b"
        ),
        "a known divergence (AC2, X-13)",
    ),
    (
        (
            r"\bcmp-038(?:'s)? (?:gains|gets|has|takes|carries|hosts|shows|holds|owns|offers|"
            r"renders|receives|is given) (?:the |a |its |an )?(?:strip's )?cancel\b|\bcancel (?:is "
            r"|was )?(?:added|moved|placed|put|given) (?:on|to|in|into) cmp-038\b"
        ),
        "Cancel on CMP-038 (X-17)",
    ),
    (
        (
            r"\bwiden(?:s|ed)? cmp-038\b|\bcmp-038(?:'s [a-z]+)? (?:is |was |gets |will be |has "
            r"been )?(?:widened|broadened|extended)\b"
        ),
        "a widened CMP-038 (X-18)",
    ),
    (r"\b(?:4|four) hz\b(?! \(?proposed)(?!, never)", "an unPROPOSED cadence"),
    (
        r"\b(?:ruled|is|now|made|deemed) final\b|\bfinali[sz]ed\b|\bno longer proposed\b",
        "a PROPOSED item made final (X-04)",
    ),
    (
        r"\bcolor\.chart\.line (?:is|was|has been) (?:accepted|adopted|shipped|approved)\b",
        "an accepted token",
    ),
    (r"\bedits? (?:the )?token json\b", "a token JSON edit"),
    (
        r"\bcatalogue pr (?:lands|merges|goes|comes) (?:first|before)\b",
        "the catalogue PR first (BQ-2)",
    ),
    (r"\b(?:history|boundary) marker (?:is|becomes) (?:a )?cmp-195\b", "a CMP-195 variant (BQ-16)"),
    (
        r"\b(?:rebuild|build) progress (?:is|becomes) (?:a )?(?:new )?(?:catalogue )?entry\b",
        "a rebuild-progress entry (BQ-17)",
    ),
    (r"\bhold(?:s|ing)? (?:the )?sign-off until #242\b", "a sign-off held on #242 (BQ-21)"),
    (
        (
            r"\bwaiver (?:is |was |has been )?(?:granted|approved|recorded|given|accepted|agreed|"
            r"in (?:force|effect|place)|stands|holds|applies)\b|\bwaived\b"
        ),
        "a granted waiver (BQ-33, X-19)",
    ),
    (
        (
            r"\b(?:countdown|cmp-226|the text) (?:is |stays |remains )?(?:hidden|suppressed|not "
            r"rendered|not shown|removed|omitted|blanked) (?:on|for|in) (?:every |all )?non-time\b"
        ),
        "a hidden countdown (BQ-14, X-20)",
    ),
    (
        (
            r"\b(?:reads?|taken|sourced|derived|fetched|pulled|comes?|obtained|loaded)(?: "
            r"[a-z]+){0,3} from (?:get )?/(?:api/v1/)?recording/symbols\b"
        ),
        "the recording state from `/recording/symbols` (BQ-12, X-21)",
    ),
    (
        (
            r"\b(?:d04-c14|d05-c23) (?:is |are |was |were |has been |have been |gets |got "
            r")?(?:applied|ruled|resolved|adopted|accepted|merged|closed|landed)\b"
        ),
        "a held row applied (BQ-28, X-22)",
    ),
    (
        (
            r"\b(?:except|excepting|save|but not) (?:for )?(?:on |in )?(?:non-time|time|tick|"
            r"volume|range|delta|renko) bars\b|\bonly (?:on|for|in) (?:non-time|time|tick|volume|"
            r"range|delta|renko) bars\b"
        ),
        "a ruled behaviour narrowed to some bar modes (X-02)",
    ),
    (
        (
            r"\bnever an agent (?:unless|except|but|other than|save)\b|\b(?:an|the|any) agent "
            r"(?:may|can|might|will|owns?)\b"
        ),
        "an agent owner lane (X-15)",
    ),
    (
        (
            r"\b(?:point & figure|point and figure|pnf) (?:is |are )?(?:now )?(?:offered|available|"
            r"enabled|shown)\b"
        ),
        "Point & Figure offered (BQ-10, X-25)",
    ),
    (r"\bre-propos(?:ed|es|ing)\b", "a re-proposal (X-29)"),
    (
        r"\b(?:16:478(?:'s gate)?|the gate) (?:is|reads|means|checks) (?:[a-z-]+ ){0,4}by role\b",
        "a gloss of `16`:478 (lens 3, M6)",
    ),
    (
        (
            r"\b(?:tickets?|issues?|follow-ups?) (?:is |are |was |were |has been |have been "
            r")?(?:filed|opened|raised|created|logged)\b|\b(?:filed|opened|raised|created|logged) "
            r"(?:a |an |the )?(?:new )?(?:ticket|issue|follow-up)\b"
        ),
        "a filed ticket (filing freeze, X-30)",
    ),
    (
        (
            r"\b(?:except|excepting|save|but not|other than) (?:for )?bq-\d+\b|\bbq-\d+ (?:is |was "
            r")?(?:excepted|excluded|reversed|overturned|rejected|declined|not taken)\b"
        ),
        "a ruled default excepted (X-32)",
    ),
)
# ruled text each New cell must carry (PR 2 writes it into `15` / `16`)
NEW_REQUIRED: dict[str, tuple[str, ...]] = {
    "A-21": ("the host floors `done` and `target` to the field's display precision",),
    "A-22": (
        "which the host sets on every delta-bar subscription, PROPOSED",
        "range without a known tick size",
    ),
    "A-35": ("each notice with its action and `Dismiss`, cleared when a new load or build starts",),
    "A-37": ("updates at most 4 Hz (PROPOSED), never per frame;",),
    "A-44": (
        'the tag is a `role="note"` with `tabindex="0"`',
        "the action is a `button`",
        "`color.focus.ring` at `border.focus`",
        "a bar's `index` under the `(generation, index)` key on every bar mode, never `t_ms`",
    ),
    "A-48": (
        "the E12-D06 hand-off's A-14",
        "it departs from the letter of the near-duplicate gate",
    ),
    "A-50": ("on non-time bars, the forming bar's progress toward its target",),
    "A-51": ("on time bars only, since no close time can be predicted on non-time bars",),
}
# the cadences the pack may state: CMP-226's 1 Hz and the pattern's PROPOSED 4 Hz (X-24)
HZ_OK = frozenset({"1", "4"})
# REQUIRED strings that must close their sentence or clause (an appended qualifier FAILs: X-02,
# X-04, X-24, X-32); the rest may continue
CLOSED_END = r"(?: \([^()]*\))?(?:[.;:]|$)"


def g_ruled(t: Texts) -> list[Finding]:
    bad: list[tuple[str, str]] = []
    secs = sections(t.spec)
    rk = ruled_key(t.spec)
    for key, needs in REQUIRED.items():
        body = norm(secs.get(rk if key == "RULED" else key, ""))
        for s in needs:
            want = norm(s)
            if s in CLOSED:
                core = want.removesuffix(".")
                ok = re.search(re.escape(core) + CLOSED_END, body) is not None
            else:
                ok = want in body
            if not ok:
                bad.append((f"§{key} lacks the ruled sentence {s[:60]!r}", key))
    for key, body in secs.items():
        if key in ("12", "15"):
            continue
        if key == "C":
            body = "\n".join(new_cells(t.spec).values())
        clauses = [plain(unquote(c, t.env)) for c in re.split(r"(?<=[.;])\s|\|", body)]
        for term, what in FORBIDDEN:
            for clause in clauses:
                if live_plain(clause, term):
                    bad.append((f"§{key} claims {what}: {clause[:60]!r}", key))
                    break
        for m in re.finditer(r"(?<![\w.])(\d+(?:\.\d+)?) ?hz\b", plain(body)):
            if m[1] not in HZ_OK:
                bad.append((f"§{key} states a {m[1]} Hz cadence; only 1 and 4 Hz are ruled", key))
                break
    news = new_cells(t.spec)
    for aid, new in news.items():
        if "/recording/symbols" in new:
            bad.append((f"{aid}'s New reads the recording state from `/recording/symbols`", "C"))
        if "Needs recorded ticks" in new or "No countdown for tick bars" in new:
            bad.append((f"{aid}'s New keeps retired copy (BQ-11, BQ-14)", "C"))
    for aid, needs in NEW_REQUIRED.items():
        for need in needs:
            if need not in news.get(aid, ""):
                bad.append((f"{aid}'s New lacks the ruled text {need[:50]!r}", "C"))
    for aid, new in news.items():
        if re.search(r"\bE12-D0\d A-\d", new):
            bad.append((f"{aid}'s New names a parent's row without its doc (hand-off)", "C"))
    if '"No countdown: bars close on activity, not time" (PROPOSED' not in news.get("A-22", ""):
        bad.append(("A-22's New lacks the PROPOSED accessible name of `—`", "C"))
    for r in c_rows(t.spec):
        if len(r) >= 3 and r[2] in ("`15`:266", "`15`:484"):
            bad.append((f"{r[0]} applies a held row (BQ-28: D04-C14, D05-C23)", "C"))
    in14 = [r for r in c_rows(t.spec) if len(r) >= 3 and r[2].startswith("`14`")]
    if [r[2] for r in in14] != ["`14`:736"]:
        bad.append(("`14` takes exactly one content line, SCR-030's rebuilding row (BQ-27)", "C"))
    if not bad:
        return []
    return one("G-RULED", [m for m, _ in bad], bad[0][1])


DISPOSITIONS = ("applied", "applied-as-amended", "closed-by-#4719", "held (owner)", "routed")
# every row of record the parents routed here (D06H:29-35, D04H:30, D05H:31, D03H:7, D02:402)
RECORDS = (
    "D06H A-1.1", "D06H A-1.2", "D06H A-2", "D06H A-3", "D06H A-4", "D06H A-5", "D06H A-6.1",
    "D06H A-6.2", "D06H A-7", "D06H A-8", "D06H A-9", "D06H A-10", "D06H A-11", "D06H A-12",
    "D06H A-13", "D06H A-14", "D06H A-15", "D04H A-4", "D04H A-5", "D04H A-6", "D05H A-10",
    "D05H A-11", "D05H A-12", "D05H A-13", "D05H A-14", "D03 DS-1", "D03 DS-2", "D03 DS-3",
    "D03 DS-4", "D03 DS-5", "D02 NC-1", "D03 CR-8",
)  # fmt: skip


def expand(cell: str) -> set[str]:
    """`D06H A-2 … A-5; D05H A-11` -> each named row of record."""
    out: set[str] = set()
    for part in cell.split(";"):
        m = re.match(r"\s*(D0\dH?|D0\d)\s+(.*)$", part.strip())
        if not m:
            continue
        doc, rest = m[1], m[2]
        for item in rest.split(","):
            item = item.strip()
            r = re.fullmatch(r"([A-Z]+)-(\d+)(?:\.(\d))? … (?:[A-Z]+-)?(\d+)", item)
            if r:
                for n in range(int(r[2]), int(r[4]) + 1):
                    out.add(f"{doc} {r[1]}-{n}")
                continue
            out.add(f"{doc} {item}")
            if re.fullmatch(r"A-\d+", item):
                out.update({f"{doc} {item}.1", f"{doc} {item}.2"} & set(RECORDS))
    return out


def g_ledger(t: Texts) -> list[Finding]:
    bad = []
    rows = table_after(sec(t.spec, "2"), "Row of record")
    named: set[str] = set()
    ids = {r[0] for r in c_rows(t.spec)}
    for r in rows:
        if len(r) < 5:
            continue
        named |= expand(r[0])
        if not r[3].startswith(DISPOSITIONS):
            bad.append(f"ledger row {r[0]!r}: disposition {r[3][:30]!r} is not one of the five")
        for aid in re.findall(r"A-\d+", r[4]):
            if aid not in ids:
                bad.append(f"ledger row {r[0]!r} points at {aid}, which §C lacks")
    for rec in RECORDS:
        if rec not in named:
            bad.append(f"the routed row {rec} has no ledger row")
    return one("G-LEDGER", bad, "2")


# BQ-15 as ruled: item lead -> outcome
DISP = {
    "LOD / aggregation indicator": "accepted-as-variant",
    "partial-history boundary marker": "accepted, new entry",
    "rebuild progress + cancel": "refused-with-pattern",
    "NC-1 status strip": "accepted-as-variant",
    "NC-3 axis caption": "amendment",
    "NC-4 loading-band retry": "accepted-as-variant",
    "NC-5 forming / amended": "accepted-as-variant",
    "NC-6 activity progress": "accepted-as-variant",
    "NC-7 decision callout": "composition",
    "NC-8, NC-9 editors": "accepted-as-variant",
    "NC-10 combined commit": "accepted-as-variant",
}


def g_disp(t: Texts) -> list[Finding]:
    bad = []
    rows = table_after(sec(t.spec, "3"), "Item")
    got = {}
    for r in rows:
        lead = next((k for k in DISP if r[0].startswith(k)), None)
        if lead is None:
            bad.append(f"a disposition row {r[0][:30]!r} names no ruled item")
            continue
        got[lead] = r
        if len(r) < 5 or r[1] != DISP[lead]:
            bad.append(f"{lead}: outcome {r[1] if len(r) > 1 else ''!r}, ruled {DISP[lead]!r}")
        elif not r[4].strip() or r[4].strip() == "—":
            bad.append(f"{lead}: no rejected-alternative line")
    bad += [f"the ruled item {k!r} has no row" for k in DISP if k not in got]
    return one("G-DISP", bad, "3")


# BQ-14 as ruled: mode -> (Shows, Data condition)
AC4 = {
    "time": ('"bar close 0:41", "0:08 closing", "closed" (`15`:2692)', "always"),
    "tick": ('"Tick 412 / 1,000"', "always: `trades` is always sent (`23`:757)"),
    "volume": ('"Vol 37 / 50 BTC" (`14`:734; D02:267)', "always"),
    "range": ('"Range 23 / 40" (ticks)', 'the instrument\'s tick size known; else "—"'),
    "delta": (
        '"Delta 12 / 25 BTC"',
        'the subscription sets `include_delta` (`23`:257, :733); else "—"',
    ),
    "renko": ('"—"', "—"),
    "pnf": ("not offered (D03:73)", "—"),
}


def g_ac4(t: Texts) -> list[Finding]:
    bad = []
    rows = {r[0]: r for r in table_after(sec(t.spec, "5"), "Mode")}
    if list(rows) != list(AC4):
        bad.append(f"the per-mode rows are {list(rows)}, ruled {list(AC4)}")
    for mode, (shows, cond) in AC4.items():
        r = rows.get(mode)
        if r and (len(r) < 4 or unescape(r[1]) != shows or unescape(r[3]) != cond):
            bad.append(f"the {mode} row differs from BQ-14's table")
    if rows.get("renko") and "one fraction would mislead" not in rows["renko"][2]:
        bad.append("the renko row drops its reason")
    return one("G-AC4", bad, "5")


OPS = (
    "replace",
    "heading",
    "replace code lines",
    "row cells",
    "insert bullet after",
    "insert bullets after",
    "insert entry after",
    "insert paragraph after",
)
FIELD = re.compile(r"`(1[456])`:(\d+)(?:–(\d+))?")


def row_cells(line: str) -> str:
    return " | ".join(unescape(c) for c in split_row(line))


def arow_problems(env: Env, spec: str) -> list[str]:
    bad: list[str] = []
    rows = c_rows(spec)
    for i, r in enumerate(rows, 1):
        if len(r) != 7:
            bad.append(f"§C row {i} has {len(r)} cells, not 7")
            continue
        aid, _, fld, op, old, new, _ = r
        if aid != f"A-{i}":
            bad.append(f"§C row {i} is {aid}: the ids must run A-1 ... A-{len(rows)}")
        m = FIELD.fullmatch(fld)
        if not m or op not in OPS:
            bad.append(f"{aid}: field {fld!r} or op {op!r} does not parse")
            continue
        base = env.base(PATHS[m[1]]).split("\n")
        cur = (env.current(PATHS[m[1]]) or "").split("\n")
        lo, hi = int(m[2]), int(m[3] or m[2])
        old_u, new_u = unescape(old), unescape(new)
        if not new_u.strip() or new_u == old_u or PLACEHOLDER.search(without_code(new_u)):
            bad.append(f"{aid}: New is empty, unchanged or unfilled")
        if op.startswith("insert"):
            if old != "—" or hi != lo:
                bad.append(f"{aid}: an insert row's Old is `—` at one line")
            parts = new_u.split(BR)
            if op.startswith("insert bullet") and not all(p.startswith("- **") for p in parts):
                bad.append(f"{aid}: an inserted bullet does not start with `- **`")
            if op == "insert entry after" and not parts[0].startswith("### CMP-"):
                bad.append(f"{aid}: an inserted entry does not start with its heading")
            continue
        parts = old_u.split(BR)
        if len(parts) != hi - lo + 1:
            bad.append(f"{aid}: Old has {len(parts)} lines for {fld}")
            continue
        for k, part in enumerate(parts):
            n = lo + k
            for label, lines in (("the base", base), ("the working tree", cur)):
                line = lines[n - 1] if n <= len(lines) else ""
                if op == "row cells":
                    want = row_cells(line)
                elif op == "replace code lines":
                    want = f"`{line.strip()}`"
                else:
                    want = line
                if part != want:
                    bad.append(f"{aid}: Old is not {fld} at {label}, byte for byte")
                    break
    return bad


def g_arow(t: Texts) -> list[Finding]:
    return one("G-AROW", arow_problems(t.env, t.spec), "C")


def a_rows_export(spec: str, values: dict[str, str]) -> list[dict[str, object]]:
    """§C as data for PR 2: anchors dropped, their values kept, escapes undone."""
    out: list[dict[str, object]] = []
    for r in c_rows(spec):
        if len(r) != 7:
            continue
        m = FIELD.fullmatch(r[2])
        new = re.sub(r"<!--=[A-Z]+:[^>]+?-->", "", unescape(r[5]))
        old = unescape(r[4])
        code = r[3] == "replace code lines"

        def split(s: str, code: bool = code) -> list[str]:
            return [x[1:-1] if code else x for x in s.split(BR)]

        out.append(
            {
                "id": r[0],
                "target": r[1],
                "file": PATHS[m[1]] if m else None,
                "lines": [int(m[2]), int(m[3] or m[2])] if m else None,
                "op": r[3],
                "old": [] if old == "—" else split(old),
                "new": split(new),
                "from": r[6],
            }
        )
    return out


REG_ORDER = ["time", "tick", "volume", "range", "delta", "renko", "pnf"]
REG_KEYS = (
    "key", "offered", "label", "short_labels", "description_key", "description", "field_label",
    "unit", "accessible_name", "first_use_default", "message_keys", "messages",
)  # fmt: skip


def d03_row(env: Env, key: str) -> list[str]:
    for ln in base_lines(env, "D03", 65, 74).split("\n"):
        cells = split_row(ln)
        if cells and f"(`{key}`)" in cells[0]:
            return cells
    return []


def d05_row(env: Env, key: str) -> list[str]:
    for ln in base_lines(env, "D05", 159, 166).split("\n"):
        cells = split_row(ln)
        if cells and f"(`{key}`)" in cells[0]:
            return [strip_comments(c) for c in cells]
    return []


def deck(env: Env, cid: str) -> str:
    for ln in base_lines(env, "D03", 186, 227).split("\n"):
        cells = split_row(ln)
        if len(cells) >= 3 and cells[0] == cid:
            return cells[2]
    return ""


def registry_problems(env: Env, spec: str, reg: str) -> list[str]:
    bad: list[str] = []
    try:
        data = json.loads(reg)
    except ValueError as e:
        return [f"the registry does not parse: {e}"]
    if not isinstance(data, dict):
        return ["the registry is not an object"]
    modes = [m for m in data.get("modes", []) if isinstance(m, dict)]
    if data.get("order") != REG_ORDER or [m.get("key") for m in modes] != REG_ORDER:
        bad.append(f"the registry's order is not {REG_ORDER}")
    if data.get("base") != BASE:
        bad.append(f"the registry's base is not {BASE}")
    for v in re.findall(r'"([^"]*)"', reg):
        if re.search(r"[A-Za-z0-9+/=]{24,}", v):
            bad.append("a registry value is a high-entropy string (gitleaks)")
    trig = deck(env, "C-38") + " " + base_lines(env, "D03", 96, 96)
    table = {r[0].strip("`"): r for r in table_after(sec(spec, "10"), "Mode")}
    for m in modes:
        key = str(m.get("key"))
        if set(m) != set(REG_KEYS):
            bad.append(f"{key}: the record's fields are not the ruled eight columns' sources")
            continue
        keys_ = m.get("message_keys")
        if not isinstance(keys_, list) or m.get("messages") != [deck(env, str(k)) for k in keys_]:
            bad.append(f"{key}: messages are not its message keys' C-deck strings, verbatim")
        if key == "pnf":
            if m["offered"] is not False or "not offered in R1" not in base_lines(
                env, "D03", 73, 73
            ):
                bad.append("pnf: held, not offered in R1 (D03:73)")
            continue
        d3, d5 = d03_row(env, key), d05_row(env, key)
        if len(d3) < 7 or len(d5) < 5:
            bad.append(f"{key}: no D03 §2 / D05 §4.1 row at the base")
            continue
        label = d3[0].split(" (")[0] if key == "time" else d3[1].split(" · ")[0]
        want = {
            "label": label,
            "description_key": next(iter(re.findall(r"^(C-\d+)", d3[2])), None),
            "field_label": d5[1].strip('"'),
            "unit": None if d5[2] == "—" else d5[2].replace(" (suffix)", ""),
            "accessible_name": d5[3].strip('"'),
            "first_use_default": d5[4],
        }
        for f, w in want.items():
            if m.get(f) != w:
                bad.append(f"{key}: {f} is {m.get(f)!r}, the base has {w!r}")
        desc = deck(env, str(m.get("description_key")))
        if m.get("description") != desc:
            bad.append(f"{key}: description differs from {m.get('description_key')}'s string")
        keys = re.findall(r"C-\d+", d3[6]) + [f"C-{x}" for x in re.findall(r"/(\d+)", d3[6])]
        if m.get("message_keys") != keys:
            bad.append(f"{key}: message keys {m.get('message_keys')} vs the base's {keys}")
        for s in m.get("short_labels") or []:
            if str(s) not in trig:
                bad.append(f"{key}: short label {s!r} is not C-38's or the chip's")
        row = table.get(key)
        if not row or len(row) < 8:
            bad.append(f"{key}: §10's table has no row")
            continue
        shorts = re.findall(r'"([^"]+)"', row[2])
        cells = {
            "label": row[1],
            "description_key": row[3],
            "field_label": row[4],
            "unit": None if row[5] == "—" else row[5],
            "first_use_default": row[6],
            "accessible_name": row[7].strip('"'),
        }
        for f, v in cells.items():
            if m.get(f) != v:
                bad.append(f"{key}: §10's {f} {v!r} differs from the registry")
        if shorts != list(m.get("short_labels") or []):
            bad.append(f"{key}: §10's short labels differ from the registry")
    return bad


def g_registry(t: Texts) -> list[Finding]:
    return one("G-REGISTRY", registry_problems(t.env, t.spec, t.reg), "10")


def enum_of(line: str) -> list[str]:
    m = re.search(r"enum\"?:?\s*\[([^\]]*)\]", line)
    return [x.strip().strip('"') for x in m[1].split(",")] if m else []


def g_enum(t: Texts) -> list[Finding]:
    bad = []
    wire = enum_of(base_lines(t.env, "22", 17365, 17365))
    ws = enum_of(base_lines(t.env, "23", 1917, 1917))
    cat = re.search(r"barMode: ([^`]*)`", base_lines(t.env, "15", 2170, 2170))
    cat_m = re.findall(r'"([a-z_]+)"', cat[1]) if cat else []
    rows = {r[0]: r for r in table_after(sec(t.spec, "9"), "Source")}
    r22 = rows.get("`22` `BarType`")
    if not r22 or re.findall(r"`([a-z_]+)`", r22[1]) != wire:
        bad.append("§9's `22` row is not `BarType` at the base")
    r23 = rows.get("`23` `barType`")
    if ws != wire or not r23 or r23[1] != "the same eight":
        bad.append("§9's `23` row: the WS enum no longer equals `22`'s")
    r15 = rows.get("`15` CMP-181 `barMode`")
    if not r15 or re.findall(r"`([a-z_]+)`", r15[1].split(":")[0]) != cat_m:
        bad.append("§9's `15` row is not CMP-181's `barMode` at the base")
    ruled = [x for x in wire if x != "heikin_ashi"]
    for aid in ("A-1", "A-5"):
        new = new_cells(t.spec).get(aid, "")
        m = re.search(r"barMode: ((?:\"[a-z_]+\" ?\| ?)*\"[a-z_]+\")", new)
        if not m or re.findall(r'"([a-z_]+)"', m[1]) != ruled:
            bad.append(f"{aid}'s `barMode` is not the wire's members without `heikin_ashi`")
    return one("G-ENUM", bad, "9")


# names a New cell may bind that the token JSON does not ship: the PROPOSED ones (BQ-19), E11-D05's
# engine-chrome aliases and dash / pattern ids
UNSHIPPED_OK = frozenset(
    {
        "color.chart.line",
        "dash.1-1",
        "dash.2-2",
        "pattern.hatch.gap",
        "color.chart.boundary",
        "color.chart.hatch.texture",
        "font.mono",
    }
)
TOKEN_NAME = re.compile(
    r"`((?:color|type|space|radius|elevation|border|font|dash|pattern|opacity|size)\.[a-z0-9.-]+)`"
)


def shipped_names(env: Env) -> frozenset[str]:
    names: set[str] = set()
    for f in ("primitives", "semantic-dark", "semantic-light", "semantic-hc"):
        names |= set(token_file(env, f))
    return frozenset(names)


def g_token(t: Texts) -> list[Finding]:
    bad = []
    raw = {f: token_file(t.env, f) for f in ("semantic-dark", "semantic-light", "semantic-hc")}

    def ref(f: str, name: str) -> str:
        v = raw[f].get(name)
        return str(v.get("$value")) if isinstance(v, dict) else ""

    if ref("semantic-dark", "color.node.logic") != "{" + LINE_PRIMITIVE + "}":
        bad.append(
            "`color.node.logic` no longer aliases palette.purple.500 in dark (AC3's finding)"
        )
    if ref("semantic-hc", "color.node.logic") not in ("", "{" + LINE_PRIMITIVE + "}"):
        bad.append("`color.node.logic` is overridden in high contrast (AC3's finding)")
    if ref("semantic-light", "color.node.logic") != "{palette.purple.600}":
        bad.append("`color.node.logic` in light is no longer palette.purple.600")
    rows = {r[0]: r for r in table_after(sec(t.spec, "8"), "Theme")}
    if list(rows) != list(THEMES):
        bad.append("§8's measurement rows are not dark, light, hc")
    floor = re.search(r"meet (\d+(?:\.\d+)?):1", base_lines(t.env, "05", 128, 128))
    for th in THEMES:
        r = contrast(line_hex(t.env, th), semantic_colours(t.env, th)["color.surface.canvas"])
        if not floor or r < float(floor[1]):
            bad.append(f"`color.chart.line` misses `05`:128's data-ink minimum in {th}")
    if set(layering(t.env)) != set(THEMES):
        bad.append("`themes.json` no longer layers dark, light and high contrast")
    for th in THEMES:
        line, sem = line_hex(t.env, th), semantic_colours(t.env, th)
        for sim in SIMS:
            d = min(delta_e(simulate(line, sim), simulate(sem[k], sim)) for k in LINE_SET)
            if d < DE_MIN:
                bad.append(f"`color.chart.line` is {show_de(d)} from the set under {sim} in {th}")
        grey = min(grey_dl(line, sem[k]) for k in LINE_SET)
        if grey < DE_MIN and "the pair passes on geometry" not in sec(t.spec, "8"):
            bad.append(f"the greyscale L* gap in {th} is under {DE_MIN} with no non-colour channel")
    if "**Every theme clears the non-text minimum** of `05`:128" not in sec(t.spec, "8"):
        bad.append("§8 does not state that every theme clears `05`:128's minimum (T Tech)")
    olds = {r[0]: unescape(r[4]) for r in c_rows(t.spec) if len(r) >= 6}
    for aid, new in new_cells(t.spec).items():
        for name in TOKEN_NAME.findall(new):
            name = name.rstrip(".")
            if name.endswith(".*") or name in olds.get(aid, ""):
                continue
            if name not in shipped_names(t.env) and name not in UNSHIPPED_OK:
                bad.append(f"{aid} binds `{name}`, which is neither shipped nor PROPOSED here")
    return one("G-TOKEN", bad, "8")


def g_cvd_src(t: Texts) -> list[Finding]:
    return one("G-CVD-SRC", cvd_src_problems(t.env), "8")


LOG_IDS = tuple(
    [f"CR-{i}" for i in range(1, 9)]
    + [f"DS-{i}" for i in range(1, 6)]
    + [f"X-{i}" for i in range(1, 6)]
    + ["OQ-A"]
    + [f"D04-C{i}" for i in range(12, 16)]
    + [f"D04-G{i}" for i in range(1, 8)]
    + [f"D04-Q{i}" for i in range(1, 4)]
    + ["D05-C23"]
    + [f"D05-G{i}" for i in range(1, 10)]
    + [f"D05-Q{i}" for i in range(1, 6)]
    + [f"D06-G{i}" for i in range(1, 4)]
    + [f"D06-Q{i}" for i in range(1, 4)]
    + ["G-E1", "G-E2", "G-D07-1", "G-D07-2", "G-D08-1", "G-D08-2", "G-D08-3", "G-D08-4", "G-2"]
    + ["ACK-1"]
    + [f"DR-{i}" for i in range(1, 9)]  # the fresh reader's dry run (§14), carried (DR-9 resolved)
)
AGENT_WORDS = re.compile(r"\b(?:agent|worker|hcl|lane|orchestrator|claude)\b", re.IGNORECASE)


def g_log(t: Texts) -> list[Finding]:
    bad = []
    ids = log_ids(t.spec)
    for i in LOG_IDS:
        if ids.count(i) != 1:
            bad.append(f"the log lists {i} {ids.count(i)} times (the union by id lists it once)")
    for i in ids:
        if i not in LOG_IDS:
            bad.append(f"the log lists {i}, which no parent or this pack defines")
    for r in table_after(sec(t.spec, "13"), "Ids"):
        if len(r) < 6:
            continue
        if not r[3].strip() or AGENT_WORDS.search(r[3]):
            bad.append(f"{r[0][:20]}: the owner lane is empty or an agent")
        key = re.match(r"(E12-[A-Z]\d\d)", r[4])
        due = re.search(r"<!--=DATE:([^>]+?)-->|\{\{DATE:([^}]+)\}\}", r[5])
        if not key or ticket_sprint(t.env, key[1]) is None:
            bad.append(f"{r[0][:20]}: the consumer names no planned ticket")
        elif not due or (due[1] or due[2]) != key[1]:
            bad.append(f"{r[0][:20]}: the due date is not {key[1]}'s sprint start")
    return one("G-LOG", bad, "13")


CROW_IDS = tuple(f"C-{c}" for c in "abcdefghijklmnopqrstuvwx")


def g_crows(t: Texts) -> list[Finding]:
    bad = []
    got: list[str] = []
    for r in table_after(sec(t.spec, "12"), "C"):
        got += [x.strip() for x in r[0].split(",")]
        if len(r) < 4 or not r[2].strip():
            bad.append(f"{r[0]}: no reading taken")
    if got != list(CROW_IDS):
        bad.append(f"the C-rows are {got[:3]}...; the register is C-a ... C-x, in order")
    return one("G-CROWS", bad, "12")


def heads(spec: str) -> set[str]:
    return {sec_no(m[2]) for m in re.finditer(r"^(##) (.*)$", spec, re.MULTILINE)}


# the fresh reader's dry run (BQ-30), 2026-10-28: one row per consuming role, then the frontend-role
# and QA-role passes, in this order
WALK_DATE = "2026-10-28"
WALK_ROLES = (
    "story: E12-S06 (#395)",
    "story: E12-S10 (#396)",
    "story: E12-S12 (#535)",
    "story: E12-S07 (#533)",
    "QA: E12-Q03 (#419)",
    "a11y: E12-D11 (#312)",
    "tokens: E11-T04 (#390)",
    "frontend: typeability",
    "QA: observability",
)
WALK_FRESH = "**A fresh reader ran the dry run on 2026-10-28**"
WALK_HEURISTIC = 'Each "not found" is a finding `(heuristic)`'
WALK_TICK = "[x] The dry run recorded: §14 (a fresh reader, 2026-10-28)."
WALK_ITEM = re.compile(r"^([A-Z][A-Z0-9]*-\d+[a-z]?) (.+?) → (.+)$")


def walk_rows(spec: str) -> list[list[str]]:
    return table_after(sec(spec, "14"), "Date")


def g_walk(t: Texts) -> list[Finding]:
    bad = []
    rows = walk_rows(t.spec)
    ids = {r[0] for r in c_rows(t.spec)}
    known = set(log_ids(t.spec)) | set(CROW_IDS)
    hs = heads(t.spec)
    if WALK_FRESH not in sec(t.spec, "14"):
        bad.append("§14 does not state that a fresh reader ran the dry run")
    if [r[1] if len(r) > 1 else "" for r in rows] != list(WALK_ROLES):
        bad.append("§14's rows are not one per role plus the frontend and QA passes, in order")
    for r in rows:
        if len(r) < 6:
            bad.append(f"a dry-run row has {len(r)} cells, not six")
            continue
        if r[0] != WALK_DATE:
            bad.append(f"{r[1]}: dated {r[0]}, not the fresh reader's {WALK_DATE}")
        if not all(x.isdigit() for x in r[2:5]) or int(r[2]) != int(r[3]) + int(r[4]):
            bad.append(f"{r[1]}: needs is not found plus not found")
            continue
        items = [x.strip() for x in r[5].split(";") if x.strip()] if r[5] != "—" else []
        if len(items) != int(r[4]):
            bad.append(f"{r[1]}: {r[4]} not found, {len(items)} dispositions")
        for it in items:
            m = WALK_ITEM.match(it)
            if not m:
                bad.append(f"{r[1]}: {it[:30]!r} is not 'id what → target'")
                continue
            for tgt in (x.strip() for x in m[3].split(",")):
                ok = tgt in ids or tgt in known or (tgt.startswith("§") and tgt[1:] in hs)
                if not ok:
                    bad.append(f"the dry-run target {tgt!r} of {m[1]} does not resolve")
    if WALK_TICK not in t.spec:
        bad.append("the DoD does not tick the dry run")
    for item in walk_owner_items(t.spec):
        for s in re.findall(r"§(\d+)", item):
            if s not in hs:
                bad.append(f"the walkthrough item {item[:30]!r} points at a missing §{s}")
    return one("G-WALK", bad, "14")


def g_commentid(t: Texts) -> list[Finding]:
    bad = [
        f"comment id {m} is not one the pack may cite"
        for m in re.findall(
            r"(?<![\w-])(\d{9,})(?![\w-])",
            "\n".join(ln for ln in t.spec.split("\n") if not ln.startswith("| A-")),
        )
        if m not in COMMENT_IDS
    ]
    return one("G-COMMENTID", bad)


def mutation_paragraph() -> str:
    by: dict[str, list[str]] = {}
    for mu in MUTATIONS:
        by.setdefault(mu.gate, []).append(f"{mu.mid} {mu.desc}")
    return " ".join(f"**{g}:** " + "; ".join(v) + "." for g, v in by.items())


def g_mutlist(t: Texts) -> list[Finding]:
    body = sec(t.spec, "15").split("\n")
    ok = mutation_paragraph() in body
    return one(
        "G-MUTLIST", [] if ok else ["§15 is not the tool's mutation list (run --fill)"], "15"
    )


def g_lines(t: Texts) -> list[Finding]:
    bad = [
        f"tool line {i} has {len(ln)} characters (at most 100)"
        for i, ln in enumerate(t.tool.split("\n"), 1)
        if len(ln) > 100
    ]
    return one("G-LINES", bad)


def g_pins(t: Texts) -> list[Finding]:
    """One FAIL per section whose pinned units differ."""
    if t.pins is None:
        return [Finding("FAIL", "G-RULED-PIN", f"no {PINS_REL}; run --repin-ruled deliberately")]
    by: dict[str, list[str]] = {}
    for m, s_ in pin_problems(parse_pins(t.pins), units(t.spec)):
        by.setdefault(s_, []).append(m)
    return [one("G-RULED-PIN", ms, s_)[0] for s_, ms in by.items()]


# C11 / BQ-6: each parent row's Old cell, re-pinned by content: (parent, its line, the parent's
# base, the `15` line there, the `15` line at BASE)
REPIN: tuple[tuple[str, int, str, int, int], ...] = (
    ("D06H", 43, "5930749cdf", 2131, 2170),
    ("D06H", 45, "5930749cdf", 2132, 2171),
    ("D06H", 46, "5930749cdf", 2133, 2172),
    ("D06H", 47, "5930749cdf", 2154, 2193),
    ("D06H", 49, "5930749cdf", 2613, 2656),
    ("D06H", 51, "5930749cdf", 2649, 2692),
    ("D04H", 42, "d6597cbcf7", 2585, 2625),
    ("D04H", 43, "d6597cbcf7", 2595, 2635),
    ("D05H", 49, "15ba8bbc1b", 2675, 2715),
)


def repin_findings(t: Texts) -> list[Finding]:
    """FAIL when a parent's Old fragment vanished from `15` (or the ledger misstates the move);
    WARN when it moved off the line the ledger names."""
    fails: list[str] = []
    warns: list[str] = []
    ledger = sec(t.spec, "2")
    cat = t.env.base(PATHS["15"]).split("\n")
    for doc, n, sha, was, now in REPIN:
        cells = split_row(base_lines(t.env, doc, n, n))
        frag = unescape(cells[3]) if len(cells) > 3 else ""
        then = (t.env.show(sha, PATHS["15"]) or "").split("\n")
        if not frag or frag not in (then[was - 1] if was <= len(then) else ""):
            fails.append(f"{doc}:{n}'s Old is not `15`:{was} at {sha}")
            continue
        if f":{was}" not in ledger or f"{now}" not in ledger:
            fails.append(f"the ledger does not record {doc}:{n}'s move :{was} -> :{now}")
        if frag in cat[now - 1]:
            continue
        hits = [i for i, ln in enumerate(cat, 1) if frag in ln]
        if hits:
            warns.append(f"{doc}:{n}'s Old moved to `15`:{hits[0]}, not :{now}")
        else:
            fails.append(f"{doc}:{n}'s Old vanished from `15` at the base")
    out = one("G-REPIN", fails, "2")
    if warns:
        out.append(Finding("WARN", "G-REPIN", warns[0], "2"))
    return out


def g_repin(t: Texts) -> list[Finding]:
    return repin_findings(t)


# Every "E12-D09 §N" a New cell (or the registry) writes into `15` / `16`: the A-row may point
# only at the section it names, and that section's heading must carry the topic (lens 1, M1)
SECREF: dict[str, str] = {
    "A-7": "9",
    "A-22": "5",
    "A-24": "5",
    "A-44": "6",
    "A-47": "8",
    "A-50": "5",
    "A-51": "5",
    "registry": "10",
}
SEC_TOPIC: dict[str, str] = {
    "5": "CMP-226 BarCountdown",
    "6": "CMP-248 HistoryMarker",
    "8": "Token contributions",
    "9": "enum diff",
    "10": "consistency contract",
}
SECREF_RE = re.compile(r"E12-D09(?:\.md`)? (?:§|section )(\d+)")


def secref_problems(spec: str, reg: str) -> list[str]:
    bad: list[str] = []
    titles = {sec_no(m[1]): m[1] for m in re.finditer(r"^## (.*)$", spec, re.MULTILINE)}
    found: dict[str, set[str]] = {}
    sources = list(new_cells(spec).items()) + [("registry", reg)]
    for who, text in sources:
        for m in SECREF_RE.finditer(text):
            found.setdefault(who, set()).add(m[1])
            want = SECREF.get(who)
            if want is None:
                bad.append(f"{who} points at E12-D09 §{m[1]}, which no SECREF row rules")
            elif m[1] != want:
                bad.append(f"{who} points at E12-D09 §{m[1]}; its topic is §{want}")
    for who, want in SECREF.items():
        if want not in found.get(who, set()):
            bad.append(f"{who} no longer points at E12-D09 §{want}")
        if SEC_TOPIC[want] not in titles.get(want, ""):
            bad.append(f"§{want}'s heading no longer names {SEC_TOPIC[want]!r}")
    return bad


def g_secref(t: Texts) -> list[Finding]:
    return one("G-SECREF", secref_problems(t.spec, t.reg), "C")


# AC2's surface grid: the §10 "shown on" row states, per column, which surfaces show it; each of
# the three walked surfaces is named in every cell, a "not" with its reason (lens 3, m14)
SURFACES = ("CMP-220 / SCR-042", "SCR-031", "SCR-041")


def g_surface(t: Texts) -> list[Finding]:
    bad: list[str] = []
    rows = [r for r in table_after(sec(t.spec, "10"), "Mode") if r[0].startswith("shown on")]
    if len(rows) != 1:
        return one("G-SURFACE", ['§10\'s table has no single "shown on" row'], "10")
    row = rows[0]
    if "SCR-045" not in row[0] or "G-D07-1" not in row[0]:
        bad.append('the "shown on" row does not route SCR-045 to G-D07-1')
    head = table_after(sec(t.spec, "10"), "Mode")
    cols = ["Label", "Short labels", "Description", "Field label", "Unit", "First-use default",
            "Accessible name"]  # fmt: skip
    if len(row) != 8 or not head:
        return one("G-SURFACE", ['the "shown on" row does not have the eight cells'], "10")
    for col, cell in zip(cols, row[1:], strict=True):
        for sfc in SURFACES:
            if sfc not in cell:
                bad.append(f"{col}: {sfc} is neither shown nor not shown")
        for m in re.finditer(r"\bnot (SCR-\d{3}|CMP-\d{3})", cell):
            if not cell[m.end() :].startswith(" ("):
                bad.append(f"{col}: {m[1]} is not shown without a reason")
    return one("G-SURFACE", bad, "10")


def g_unshipped(t: Texts) -> list[Finding]:
    """Every token a New cell binds that the token JSON does not ship is marked PROPOSED (lens 3,
    M5): next to the name, in the bullet's bold label, or in the part's alias sentence."""
    bad: list[str] = []
    olds = {r[0]: unescape(r[4]) for r in c_rows(t.spec) if len(r) >= 6}
    shipped = shipped_names(t.env)
    for aid, new in new_cells(t.spec).items():
        for part in new.split(BR):
            label = re.match(r"- \*\*([^*]*)\*\*", part)
            names = list(TOKEN_NAME.finditer(part))
            for i, m in enumerate(names):
                name = m[1].rstrip(".")
                if name not in UNSHIPPED_OK or name in shipped or name in olds.get(aid, ""):
                    continue  # an unknown name is G-TOKEN's
                if name == "font.mono":
                    continue
                nxt = names[i + 1].start() if i + 1 < len(names) else len(part)
                near = part[max(0, m.start() - 14) : m.start()] + part[m.end() : nxt]
                alias = name.startswith("color.chart.") and (
                    "names are E11-D05's engine-chrome aliases, PROPOSED" in part
                )
                if "PROPOSED" in near or (label and "PROPOSED" in label[1]) or alias:
                    continue
                bad.append(f"{aid} binds the unshipped `{name}` without PROPOSED")
    return one("G-UNSHIPPED", bad, "C")


# each state an entry defines has its story (lens 3, m9): (A-row, state words, story)
STATE_STORIES: tuple[tuple[str, str, str], ...] = (
    ("A-44", "action busy", "ActionBusy"),
    ("A-44", "long tag", "LongTag"),
    ("A-44", "tag focused", "TagFocused"),
    ("A-23", "a stale feed freezes the text", "NonTimeStaleFrozen"),
    ("A-23", "delta without `include_delta`", "NonTimeDeltaNoIncludeDelta"),
    ("A-23", "range without a known tick size", "NonTimeRangeNoTickSize"),
    ("A-19", "Heikin-Ashi with footprint", "HeikinAshiFootprintCallout"),
    ("A-19", "width mapping off", "WidthMappingOff"),
)
# where the state is defined (A-23 / A-19 list stories; their states live in A-22 / A-18)
STATE_HOME = {"A-44": "A-44", "A-23": "A-22", "A-19": "A-18"}


def g_stories(t: Texts) -> list[Finding]:
    bad: list[str] = []
    news = new_cells(t.spec)
    for aid, words, story in STATE_STORIES:
        names = entry_story_names(t.spec) if aid == "A-44" else story_names(t.spec, aid)
        if words in news.get(STATE_HOME[aid], "") and story not in names:
            bad.append(f"{STATE_HOME[aid]} defines '{words}' but {aid} has no {story} story")
    return one("G-STORIES", bad, "11")


# D02 D-5's phases (D02:29), carried into §7 and A-37 with no other figure (X-23)
PHASE_SRC = ("nothing for 600 ms", "from 600 ms to 2 s", "after 2 s")
PHASE_7 = (
    "from 0 to 600 ms nothing but the pending mark; from 600 ms to 2 s CMP-038 text; after 2 s"
    " CMP-023 determinate"
)
PHASE_A37 = (
    "from 0 to 600 ms nothing but the toolbar's pending mark; from 600 ms to 2 s CMP-038 text;"
    " after 2 s CMP-023 determinate"
)
PHASE_FIGURES = frozenset({"600 ms", "2 s", "5 s"})


def g_phase(t: Texts) -> list[Finding]:
    bad: list[str] = []
    src = base_lines(t.env, "D02", 29, 29)
    bad += [f"D02:29 no longer holds {f!r}" for f in PHASE_SRC if f not in src]
    body, a37 = sec(t.spec, "7"), new_cells(t.spec).get("A-37", "")
    if PHASE_7 not in body:
        bad.append("§7 does not carry D-5's phases verbatim")
    if PHASE_A37 not in a37:
        bad.append("A-37's New does not carry D-5's phases verbatim")
    for where, text in (("§7", body), ("A-37", a37)):
        for m in re.finditer(r"(?<![\w.])(\d+(?:\.\d+)?) ?(ms|s)\b", without_code(text)):
            if f"{m[1]} {m[2]}" not in PHASE_FIGURES:
                bad.append(f"{where} states {m[0]!r}; D-5's figures are 600 ms and 2 s")
    return one("G-PHASE", bad, "7")


# PR 2 applies each New cell byte for byte, so each is pinned here by sha256 (first 16 hex) of its
# `--a-rows` export; `--repin-ruled` never writes these (lens 2, Nit 5; X-24, X-25). Like the
# pins, a finding here prints as a NOTE when another gate FAILs.
NEW_SHA: dict[str, str] = {
    "A-1": "a191d1087dba9689",
    "A-2": "d85d93d484f3c12e",
    "A-3": "83e11e47cb15c62a",
    "A-4": "99b494c93915d4b9",
    "A-5": "657f476ff1f16b50",
    "A-6": "5bc24ee69dbb6471",
    "A-7": "56998ba6341cf587",
    "A-8": "2c10470e54a5579c",
    "A-9": "5fe24f93c95f7eb9",
    "A-10": "9e53be555d805337",
    "A-11": "9efe6f04bd062652",
    "A-12": "ce1edfbc5a6b1cde",
    "A-13": "720aa617cb85b287",
    "A-14": "0e0fe962bd5f4e46",
    "A-15": "0c0ba36d08588516",
    "A-16": "17eda18d86499879",
    "A-17": "ba86802badfcdbb5",
    "A-18": "13fc2bd363db7cc2",
    "A-19": "eec344f8469d2231",
    "A-20": "76e0294695a5bb09",
    "A-21": "e2dae801aa4377a0",
    "A-22": "ba8121e7e8deff24",
    "A-23": "8d0e7c2d65d94167",
    "A-24": "fe65e6d71f9eee7b",
    "A-25": "3f16f3d5c6f959a9",
    "A-26": "15f53d1a3d50c6ae",
    "A-27": "56b2d7d15d9ed537",
    "A-28": "63aee1a87a3938d8",
    "A-29": "7d83735afb2133d2",
    "A-30": "3b046ccdd9ab1682",
    "A-31": "2d0c45a817554727",
    "A-32": "b57b10971395a842",
    "A-33": "ef64ed9ae71562e2",
    "A-34": "bade0bae694eecdb",
    "A-35": "41df528adee00b65",
    "A-36": "7524a44a3749f1d4",
    "A-37": "4e202a488c4ad144",
    "A-38": "a5ed9a79049bb5cf",
    "A-39": "8857535e826603dc",
    "A-40": "540fd40ed7c3cd1e",
    "A-41": "c7e90321c354b6d0",
    "A-42": "52fa1a48b6811479",
    "A-43": "93b06001f6e94e79",
    "A-44": "390df8c2365b773d",
    "A-45": "876caa75e621df54",
    "A-46": "1db1d212dd4181fd",
    "A-47": "6ffe33f6ef1bd60d",
    "A-48": "0e1c3fd2d1795b6d",
    "A-49": "27814111f9f237cf",
    "A-50": "947868b04ebfdab9",
    "A-51": "8e3ed1ef181f9613",
}


def new_digest(spec: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in a_rows_export(spec, {}):
        blob = json.dumps(row["new"], ensure_ascii=False)
        out[str(row["id"])] = hashlib.sha256(blob.encode()).hexdigest()[:16]
    return out


def g_reid(t: Texts) -> list[Finding]:
    """The ruling delta (LANE-hcl1-163): HistoryMarker is CMP-248, an id no other doc holds."""
    bad = []
    for rev in (BASE, HEAD_REF):
        if rev == HEAD_REF and not t.env.head_resolves():
            continue
        for p in t.env.grep_paths(rev, REID_NEW):
            if p not in OWN_PATHS:
                bad.append(f"{p} holds {REID_NEW} at {rev}: the id is taken")
    # CMP-244 may appear only in the version line's delta, never for HistoryMarker
    for name, text in (("the pack", t.spec), ("the registry", t.reg)):
        for i, ln in enumerate(text.split("\n"), 1):
            if REID_OLD in ln.replace(REID_LINE, "") and not (
                "**Version line**" in ln and ln.count(REID_OLD) == 1 and "HotkeyConflictChip" in ln
            ):
                bad.append(f"{name} line {i} uses {REID_OLD} (E10-D02's id), not {REID_NEW}")
    if f"### {REID_NEW} HistoryMarker" not in new_cells(t.spec).get("A-44", ""):
        bad.append(f"A-44 does not catalogue HistoryMarker as {REID_NEW}")
    if REID_LINE not in (next((ln for ln in t.spec.split("\n") if "**Version line**" in ln), "")):
        bad.append("the version line does not record the re-id as a ruling delta")
    return one("G-REID", bad, "0")


def g_newbytes(t: Texts) -> list[Finding]:
    got = new_digest(t.spec)
    bad = [f"{k}'s New changed (PR 2 applies it byte for byte)" for k in NEW_SHA if got.get(k)
           != NEW_SHA[k]]  # fmt: skip
    bad += [f"{k}'s New is not pinned in NEW_SHA" for k in got if k not in NEW_SHA]
    return one("G-NEWBYTES", bad, "C")


GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_anchor, g_marker, g_figure, g_cite, g_version, g_untouched, g_wordcount, g_quote,
    g_charset, g_cells, g_close, g_url, g_unbuilt, g_unmerged, g_heuristic, g_ruled, g_ledger,
    g_disp, g_ac4, g_arow, g_registry, g_enum, g_token, g_cvd_src, g_log, g_crows, g_walk,
    g_commentid, g_mutlist, g_lines, g_repin, g_secref, g_surface, g_unshipped, g_phase,
    g_stories, g_reid,
)  # fmt: skip


def audit(t: Texts) -> list[Finding]:
    found: list[Finding] = []
    for g in GATES:
        found += g(t)
    pins = g_pins(t) + g_newbytes(t)
    if any(f.level == "FAIL" for f in found):
        pins = [replace(f, level="NOTE") for f in pins]
    return found + pins


# ---------------------------------------------------------------------------- mutations


@dataclass(frozen=True)
class Mutation:
    mid: str
    gate: str
    desc: str
    fn: Callable[[Texts], Texts]
    want: str = ""  # when set, the one FAIL's message must equal it


def set_doc(t: Texts, doc: str, text: str) -> Texts:
    if doc == "spec":
        return replace(t, spec=text)
    if doc == "reg":
        return replace(t, reg=text)
    return replace(t, tool=text)


def flex(old: str) -> re.Pattern[str]:
    """`old` with each run of spaces matching any run (Prettier pads table cells)."""
    return re.compile(r" +".join(re.escape(p) for p in old.split(" ")))


def subst(old: str, new: str, count: int = 1, doc: str = "spec") -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        text = getattr(t, doc)
        if old in text:
            return set_doc(t, doc, text.replace(old, new, count))
        out, n = flex(old).subn(lambda _m: new, text, count=count)
        if not n:
            raise AssertionError(f"mutation anchor missing: {old[:60]!r}")
        return set_doc(t, doc, out)

    return f


def resub(pattern: str, new: str, doc: str = "spec") -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        text = getattr(t, doc)
        out, n = re.subn(pattern, new, text, count=1)
        if not n:
            raise AssertionError(f"mutation pattern missing: {pattern[:60]!r}")
        return set_doc(t, doc, out)

    return f


def with_env(tweak: Callable[[Env], None]) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        e = Env(
            base_cache=dict(t.env.base_cache),
            head_cache=dict(t.env.head_cache),
            merge_base=t.env.merge_base,
            changed=t.env.changed,
            head_override=dict(t.env.head_override),
            head_ok=t.env.head_ok,
            last_override=dict(t.env.last_override),
            cur_override=dict(t.env.cur_override),
            status_raw=t.env.status_raw,
            grep_extra={k: list(v) for k, v in t.env.grep_extra.items()},
        )
        tweak(e)
        return replace(t, env=e)

    return f


def base_line_edit(rel: str, n: int, new: str, head_too: bool = True) -> Callable[[Env], None]:
    def tweak(e: Env) -> None:
        lines = e.base(rel).split("\n")
        lines[n - 1] = new
        text = "\n".join(lines)
        e.base_cache[rel] = text
        if head_too:
            e.head_override[rel] = text

    return tweak


def head_line_edit(rel: str, n: int, new: str) -> Callable[[Env], None]:
    def tweak(e: Env) -> None:
        lines = e.base(rel).split("\n")
        lines[n - 1] = new
        e.head_override[rel] = "\n".join(lines)

    return tweak


def changed_also(path: str) -> Callable[[Env], None]:
    def tweak(e: Env) -> None:
        e.changed = lambda mb: [path]

    return tweak


def no_mb(e: Env) -> None:
    e.merge_base = lambda: None


def head_gone(e: Env) -> None:
    e.head_ok = False


def late_commit(e: Env) -> None:
    e.last_override[f"{HEAD_REF}:{PATHS['D04']}"] = "0" * 40


def late_input(rel: str) -> Callable[[Env], None]:
    def tweak(e: Env) -> None:
        e.last_override[f"{HEAD_REF}:{rel}"] = "0" * 40

    return tweak


def wt_edit(e: Env) -> None:
    lines = e.base(PATHS["15"]).split("\n")
    lines[2169] = lines[2169].replace("upColor", "upColour")
    e.cur_override[PATHS["15"]] = "\n".join(lines)


def hc_logic(e: Env) -> None:
    rel = f"{DS_SRC}/semantic-hc.tokens.json"
    data = json.loads(e.base(rel))
    data["color.node.logic"] = {"$type": "color", "$value": "{palette.purple.300}"}
    text = json.dumps(data, indent=2)
    e.base_cache[rel] = text
    e.head_override[rel] = text


def cvd_drift(e: Env) -> None:
    src = e.base(CVD_SRC).replace("2.02344", "2.02345", 1)
    e.base_cache[CVD_SRC] = src
    e.head_override[CVD_SRC] = src


def porcelain(raw: str) -> Callable[[Env], None]:
    def tweak(e: Env) -> None:
        e.status_raw = lambda: raw
        e.changed = None

    return tweak


def cvd_clash(e: Env) -> None:
    rel = f"{DS_SRC}/semantic-light.tokens.json"
    data = json.loads(e.base(rel))
    data["color.cvd.buy"] = {"$type": "color", "$value": "{" + LINE_PRIMITIVE + "}"}
    text = json.dumps(data, indent=2)
    e.base_cache[rel] = text
    e.head_override[rel] = text


def reid_taken(e: Env) -> None:
    e.grep_extra[BASE] = ["docs/design/E33/E33-D04.md"]


def tool_long(t: Texts) -> Texts:
    return replace(t, tool=t.tool + "\n# " + "x" * 120 + "\n")


def reg_set(path: tuple[str, ...], value: object) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        data = json.loads(t.reg)
        node = data
        for k in path[:-1]:
            node = node[int(k)] if isinstance(node, list) else node[k]
        if isinstance(node, list):
            node[int(path[-1])] = value
        else:
            node[path[-1]] = value
        return replace(t, reg=json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    return f


M = Mutation
MUTATIONS: tuple[Mutation, ...] = (
    M("M-1", "G-ANCHOR", "hand-edit the dark canvas ratio's value",
      resub(r"\d\.\d\d(?=<!--=CONTRAST:line\.canvas\.dark-->)", "9.99")),
    M("M-2", "G-ANCHOR", "leave the ledger count as a placeholder",
      resub(r"\d+<!--=COUNT:ledger-->", "{{COUNT:ledger}}")),
    M("M-3", "G-MARKER", "add a comment that is not an anchor in §0",
      subst("**Version line** (PROPOSED", "<!-- draft -->**Version line** (PROPOSED")),
    M("M-4", "G-FIGURE", "type the dark canvas ratio by hand in §8",
      subst("contrast is WCAG 2.x, truncated to two decimals;",
            "contrast is WCAG 2.x, truncated to two decimals, the line reading 4.32:1;")),
    M("M-5", "G-FIGURE", "type the dark hex by hand in §8",
      resub(r"#[0-9A-F]{6}<!--=HEX:line\.dark-->", "#8B5CF6")),
    M("M-6", "G-CITE", "move a D06H cite past the end of D06H", subst("(D06H:58)", "(D06H:958)")),
    M("M-7", "G-CITE", "simulate a cited fragment gone from D06:384",
      with_env(base_line_edit(PATHS["D06"], 384, "High contrast inherits the dark values."))),
    M("M-8", "G-VERSION", "simulate a merged change inside a cited D06 range",
      with_env(head_line_edit(PATHS["D06"], 49, "**The chart UI is built.**"))),
    M("M-9", "G-VERSION", "simulate an unresolvable origin/main", with_env(head_gone)),
    M("M-10", "G-VERSION", "pin D05 at a wrong sha in the version line",
      subst("D05 / D05H at `d6597cbcf7`", "D05 / D05H at `d6597cbcf8`")),
    M("M-11", "G-VERSION", "simulate a late commit to D04 at origin/main", with_env(late_commit)),
    M("M-12", "G-UNTOUCHED", "simulate an edit to `15` in the pack PR",
      with_env(changed_also(PATHS["15"]))),
    M("M-13", "G-UNTOUCHED", "simulate a failed merge-base", with_env(no_mb)),
    M("M-14", "G-UNTOUCHED", "simulate a hand-off file beside the pack",
      with_env(changed_also("docs/design/E12/E12-D09-handoff.md"))),
    M("M-15", "G-WORDCOUNT", "append lines past the budget",
      lambda t: replace(t, spec=t.spec + "\nExtra.\n" * 12)),
    M("M-16", "G-WORDCOUNT", "add owner walkthrough items past ten",
      subst("the design-ahead waiver (§16). Record",
            "the design-ahead waiver (§16); a; b; c; d. Record")),
    M("M-17", "G-QUOTE", "reword one of the twelve confirmations",
      subst("**BQ-27 — one `14` content line**", "**BQ-27 — a single `14` content line**")),
    M("M-18", "G-QUOTE", "misspell a merged string everywhere",
      lambda t: replace(t, spec=t.spec.replace("Lot size not known yet", "Lot size unknown yet"))),
    M("M-19", "G-QUOTE", "misname CMP-226 in the header",
      subst("CMP-226 BarCountdown; a disposition", "CMP-226 BarTimer; a disposition")),
    M("M-20", "G-QUOTE", "add a story no merged list holds to A-6",
      subst("InvertedConvention, PartialHistoryBoundary", "InvertedConvention, Sparkline, "
            "PartialHistoryBoundary")),
    M("M-21", "G-CHARSET", "write a trailing space after §0's version line",
      subst("and the BQ-28 rulings.\n", "and the BQ-28 rulings. \n")),
    M("M-22", "G-CHARSET", "write a Cyrillic letter inside a §14 word",
      subst("under synonyms", "under synоnyms")),
    M("M-23", "G-CHARSET", "write a fullwidth letter in §11",
      subst("The screen-reader script", "The screen-reader ｓcript")),
    M("M-24", "G-CELLS", "merge two cells of §1's first row",
      subst("| D02:25–39 | §3, §5, §7 |", "| D02:25–39 §3, §5, §7 |")),
    M("M-25", "G-CLOSE", "write a closing keyword in §16",
      subst("**D4** The dry run", "PR 2 closes #244. **D4** The dry run")),
    M("M-26", "G-URL", "write a local path in §0",
      subst("exported under `docs/design/E12/img/`", "exported under /home/x/img")),
    M("M-27", "G-UNBUILT", "delete the unbuilt clause of §0",
      subst("**The bar-mode and series components are unbuilt.** ", "")),
    M("M-28", "G-UNMERGED", "pin #4822 at a sha", subst("and PR #4822, closed",
                                                       "and PR #4822 (`0a1b2c3d4e`), closed")),
    M("M-29", "G-UNMERGED", "link E12-D08's unmerged doc",
      subst("**D08's hi-fi is G-D08-1.**", "**D08's hi-fi is G-D08-1.** See E12-D08.md.")),
    M("M-30", "G-HEURISTIC", "drop the label from the dry run's not-found findings",
      subst('Each "not found" is a finding `(heuristic)`, folded', 'Each "not found" is folded')),
    M("M-31", "G-RULED", "write that the owner approved the token rows in §8",
      subst("**Refused, recorded:**", "The owner approved the rows. **Refused, recorded:**")),
    M("M-32", "G-RULED", "drop PROPOSED from the 4 Hz cadence in §7",
      subst("at most 4 Hz (PROPOSED, T Perf)", "at most 4 Hz (T Perf)")),
    M("M-33", "G-ENUM", "restore `pointfigure` in A-1's New",
      subst('\\|"renko"\\|"pnf"` (the wire', '\\|"renko"\\|"pointfigure"` (the wire')),
    M("M-34", "G-RULED", "write that a review session was held in §14",
      subst("**(b)** the frontend-role pass", "a review session was held, **(b)** the "
            "frontend-role pass")),
    M("M-35", "G-RULED", "drop 'except SCR-045' from §10",
      subst("**the table is complete except SCR-045.**", "**the table is complete.**")),
    M("M-36", "G-RULED", "write that CMP-038 gains the Cancel in §7",
      subst("AC5's screen pointer is A-49", "CMP-038 gains the Cancel. AC5's screen pointer is"
            " A-49")),
    M("M-37", "G-RULED", "drop the owner-pending mark from BQ-33 in §16",
      subst("(BQ-33: PROPOSED, owner approval pending (#2701))", "(BQ-33)")),
    M("M-38", "G-RULED", "record a known divergence in §10",
      subst("absence is not a divergence.", "absence is not a divergence; SCR-031's unit is a"
            " known divergence.")),
    M("M-39", "G-RULED", "write the retired 'Needs recorded ticks' into A-10's New",
      subst('reading "Needs recorded prints: none yet" (C-24)',
            'reading "Needs recorded ticks" (C-24)')),
    M("M-40", "G-RULED", "source A-15's state from `/recording/symbols`",
      subst("favourites need `settings:write`; no component emits analytics",
            "the state is read from `/recording/symbols`; favourites need `settings:write`; no"
            " component emits analytics")),
    M("M-41", "G-RULED", "write that the PR edits the token JSON in §8",
      subst("**Where:** `16` gets", "**Where:** this PR edits the token JSON; `16` gets")),
    M("M-42", "G-LEDGER", "drop D05H A-12 from the ledger",
      subst("| D04H A-6; D05H A-12 |", "| D04H A-6 |")),
    M("M-43", "G-LEDGER", "write an unknown disposition",
      subst("| routed: the owner's sign-off PR", "| parked: the owner's sign-off PR")),
    M("M-44", "G-DISP", "change NC-7's outcome",
      subst("| NC-7 decision callout | composition |",
            "| NC-7 decision callout | accepted-as-variant |")),
    M("M-45", "G-DISP", "empty NC-10's rejected alternative",
      subst("| a combined-picker entry |", "| — |")),
    M("M-46", "G-AC4", "drop the delta row's fallback",
      subst('`include_delta` (`23`:257, :733); else "—" |', "`include_delta` (`23`:257, :733) |")),
    M("M-47", "G-AC4", "give Renko a fraction",
      subst('| renko | "—" |', '| renko | "Renko 3 / 5" |')),
    M("M-48", "G-AROW", "alter one character of A-3's Old",
      subst("| - **A11y**: bar-level DOM mirror", "| - **A11y**: bar-level DOM-mirror")),
    M("M-49", "G-AROW", "simulate a working-tree edit of `15`:2170", with_env(wt_edit)),
    M("M-50", "G-AROW", "give an insert row an Old cell",
      subst("| `15`:2170 | insert bullet after | — |", "| `15`:2170 | insert bullet after | x |")),
    M("M-51", "G-REGISTRY", "change the registry's tick default",
      reg_set(("modes", "1", "first_use_default"), "1000"), ),
    M("M-52", "G-REGISTRY", "write a high-entropy registry value",
      reg_set(("modes", "1", "label"), "Tick" + "Q7xP2mZ9wK4vB8nR3tY6uL1s")),
    M("M-53", "G-REGISTRY", "offer pnf in the registry", reg_set(("modes", "6", "offered"), True)),
    M("M-54", "G-ENUM", "drop `delta` from A-5's barMode line",
      subst('\\| "range" \\| "delta" \\| "renko" \\| "pnf";`', '\\| "range" \\| "renko" \\|'
            ' "pnf";`')),
    M("M-55", "G-TOKEN", "bind an unshipped token in A-12's New",
      subst("`radius.control`, `color.action.selected`",
            "`radius.control`, `color.border.input`, `color.action.selected`")),
    M("M-56", "G-TOKEN", "simulate a high-contrast override of `color.node.logic`",
      with_env(hc_logic)),
    M("M-57", "G-CVD-SRC", "simulate a drifted protan constant in the research script",
      with_env(cvd_drift)),
    M("M-58", "G-LOG", "drop D04-G7 from the log",
      subst("D04-G6, D04-G7, D04-Q1", "D04-G6, D04-Q1")),
    M("M-59", "G-LOG", "give a log row an agent as its owner lane",
      resub(r"\| E12-D07 \(#242\); DR-4: E11-T07 and E12-Q03 \(#419\)( +)\| E12-Q03",
            r"| the hcl agent\1| E12-Q03")),
    M("M-60", "G-LOG", "date an E12-S11 row by E12-S07's sprint",
      resub(r"\| E12-S11 \(#451\) \| [0-9-]+<!--=DATE:E12-S11-->",
            "| E12-S11 (#451) | 2026-11-20<!--=DATE:E12-S07-->")),
    M("M-61", "G-CROWS", "drop the C-v row",
      resub(r"\| C-v +\|[^\n]*\n", "")),
    M("M-62", "G-WALK", "point a dry-run target at a missing A-row",
      subst("S06-4 index spacing → A-7;", "S06-4 index spacing → A-99;")),
    M("M-63", "G-WALK", "drop one not-found's disposition from the E12-S06 row",
      subst("; S06-11 observability labels → DR-1", "")),
    M("M-64", "G-WALK", "untick the dry run in the DoD",
      subst("[x] The dry run recorded: §14 (a fresh", "[ ] The dry run recorded: §14 (a fresh")),
    M("M-65", "G-COMMENTID", "cite an unknown comment id",
      subst("(comment 6455151492)", "(comment 6455151493)")),
    M("M-66", "G-MUTLIST", "rename M-1 in §15", subst("M-1 hand-edit", "M-01 hand-edit")),
    M("M-67", "G-LINES", "add a 120-character line to the tool", tool_long),
    M("M-68", "G-RULED", "write that the catalogue PR lands first in §0",
      subst("**Version line** (PROPOSED",
            "The catalogue PR lands first. **Version line** (PROPOSED")),
    M("M-69", "G-RULED", "write that the history marker is a CMP-195 variant in §6",
      subst("**D08's hi-fi is G-D08-1.**", "**D08's hi-fi is G-D08-1.** The history marker is a"
            " CMP-195 variant.")),
    M("M-70", "G-RULED", "write that the waiver is granted in §16",
      subst("E12-D12 (#313) is already past its sprint.", "E12-D12 (#313) is already past its"
            " sprint. The waiver is granted.")),
    M("M-71", "G-RULED", "write that the countdown is hidden on non-time bars in §5",
      subst("(C-l). A stale feed", "(C-l). The countdown is hidden on non-time bars. A stale"
            " feed")),
    M("M-72", "G-TOKEN", "drop §8's non-text minimum sentence",
      subst("**Every theme clears the non-text minimum** of `05`:128", "The minimum of `05`:128")),
    M("M-73", "G-RULED", "write that D04-C14 is applied in §2",
      subst("re-pinned by content at the base;", "re-pinned by content at the base; D04-C14 is"
            " applied;")),
    M("M-74", "G-REPIN", "simulate D06H A-3's Old gone from its parent row",
      with_env(base_line_edit(PATHS["D06H"], 46, "| A-3 | CMP-181 | Tokens | gone | gone |"))),
    M("M-75", "G-REPIN", "drop A-7's move from the ledger",
      subst("| moved from :2649 |", "| unchanged |")),
    M("M-76", "G-RULED", "drop the owner-pending mark from C-a",
      subst("applied by PR 2 (BQ-5), owner approval pending (#2701)", "applied by PR 2 (BQ-5)")),
    M("M-77", "G-VERSION", "simulate a late commit to the primitives token JSON",
      with_env(late_input(f"{DS_SRC}/primitives.tokens.json"))),
    M("M-78", "G-VERSION", "simulate a late commit to the dark token JSON",
      with_env(late_input(f"{DS_SRC}/semantic-dark.tokens.json"))),
    M("M-79", "G-VERSION", "simulate a late commit to the light token JSON",
      with_env(late_input(f"{DS_SRC}/semantic-light.tokens.json"))),
    M("M-80", "G-VERSION", "simulate a late commit to the high-contrast token JSON",
      with_env(late_input(f"{DS_SRC}/semantic-hc.tokens.json"))),
    M("M-81", "G-VERSION", "simulate a late commit to `themes.json`",
      with_env(late_input(f"{DS_SRC}/themes.json"))),
    M("M-82", "G-VERSION", "simulate a late commit to `E12.json`", with_env(late_input(E12_JSON))),
    M("M-83", "G-VERSION", "simulate a late commit to `calendar_cv.py`",
      with_env(late_input(PATHS["CAL"]))),
    M("M-84", "G-VERSION", "simulate a late commit to the research CVD script",
      with_env(late_input(CVD_SRC))),
    M("M-85", "G-VERSION", "simulate a late commit to `rbac_seed.json`",
      with_env(late_input(PATHS["SEED"]))),
    M("M-86", "G-UNTOUCHED", "simulate an unstaged edit of `15` in porcelain status",
      with_env(porcelain(" M docs/plan/15-component-catalogue.md\0")),
      want=f"{PATHS['15']} changed against the merge-base: the pack PR must not edit it"),
    M("M-87", "G-UNTOUCHED", "simulate porcelain with an own path first and `16` second",
      with_env(porcelain(f" M {TOOL_REL}\0 M docs/plan/16-design-system-brief.md\0")),
      want=f"{PATHS['16']} changed against the merge-base: the pack PR must not edit it"),
    M("M-88", "G-RULED", "narrow §5's stale-feed rule to time bars (X-02)",
      subst("speaks for it (D06:272).", "speaks for it, except on non-time bars (D06:272).")),
    M("M-89", "G-RULED", "call the 4 Hz cadence final in §7 (X-04)",
      subst("at most 4 Hz (PROPOSED, T Perf).", "at most 4 Hz (PROPOSED, T Perf). It is ruled"
            " final.")),
    M("M-90", "G-RULED", "write that the rows are approved by the owner in §8 (X-05)",
      subst("**Refused, recorded:**", "The rows are approved by the owner. **Refused,"
            " recorded:**")),
    M("M-91", "G-RULED", "hide a sign-off behind a negation in another clause in §8 (X-07)",
      subst("**Refused, recorded:**", "Not waiting, the owner approved the rows. **Refused,"
            " recorded:**")),
    M("M-92", "G-RULED", "write that the owner gave the go-ahead in §8 (X-08)",
      subst("**Refused, recorded:**", "The owner gave the go-ahead. **Refused, recorded:**")),
    M("M-93", "G-RULED", "write a sign-off into the RULED section (X-09)",
      subst("Every default is taken as proposed. The carried",
            "Every default is taken as proposed. The owner has approved BQ-19. The carried")),
    M("M-94", "G-RULED", "contradict 'no session' with a dated walk in §14 (X-10)",
      subst("No session took place and none is claimed.", "No session took place and none is"
            " claimed. The owner walked the pack on 2026-10-27.")),
    M("M-95", "G-RULED", "tolerate a divergence in §10 (X-13)",
      subst("absence is not a divergence.", "absence is not a divergence; SCR-041's unit is a"
            " divergence tolerated by design.")),
    M("M-96", "G-RULED", "let an agent own a log row in §13 (X-15)",
      subst("never an agent) and a due date", "never an agent unless the owner delegates) and a"
            " due date")),
    M("M-97", "G-RULED", "write that CMP-038 hosts a Cancel in §7 (X-17)",
      subst("AC5's screen pointer is A-49", "CMP-038 hosts a Cancel meanwhile. AC5's screen"
            " pointer is A-49")),
    M("M-98", "G-RULED", "write that CMP-038 is widened in §7 (X-18)",
      subst("AC5's screen pointer is A-49", "CMP-038 is widened meanwhile. AC5's screen pointer"
            " is A-49")),
    M("M-99", "G-RULED", "write that the waiver stands in §16 (X-19)",
      subst("E12-D12 (#313) is already past its sprint.", "E12-D12 (#313) is already past its"
            " sprint. The waiver stands.")),
    M("M-100", "G-RULED", "write that the countdown is suppressed on non-time bars (X-20)",
      subst("(C-l). A stale feed", "(C-l). The countdown is suppressed on non-time bars. A stale"
            " feed")),
    M("M-101", "G-RULED", "take the recording state from `/recording/symbols` in §4 (X-21)",
      subst("under `marketdata:read`, and the entry states", "under `marketdata:read`, or is"
            " taken from `GET /recording/symbols`, and the entry states")),
    M("M-102", "G-RULED", "write that D04-C14 has been applied in §2 (X-22)",
      subst("re-pinned by content at the base;", "re-pinned by content at the base; D04-C14 has"
            " been applied;")),
    M("M-103", "G-PHASE", "move D-5's 2 s phase to 3 s in §7 (X-23)",
      subst("from 600 ms to 2 s CMP-038 text; after 2 s", "from 600 ms to 3 s CMP-038 text; after"
            " 3 s")),
    M("M-104", "G-RULED", "add a 10 Hz cadence to A-37's New (X-24)",
      subst("updates at most 4 Hz (PROPOSED), never per frame;", "updates at most 4 Hz (PROPOSED)"
            " or 10 Hz, never per frame;")),
    M("M-105", "G-RULED", "offer Point & Figure in A-8's New (X-25)",
      subst("Renko; Point & Figure is not offered in R1 (E12-D03 §2). |", "Renko; Point & Figure"
            " is offered in R1 (E12-D03 §2). |")),
    M("M-106", "G-RULED", "re-propose the hatch in §8 (X-29)",
      subst("adopted by reference, not re-proposed.", "adopted by reference, not re-proposed, and"
            " now re-proposed.")),
    M("M-107", "G-RULED", "write that a ticket was filed for G-E1 in §9 (X-30)",
      subst("CR-5 and CR-6 are carried, not re-proposed.", "CR-5 and CR-6 are carried, not"
            " re-proposed. A ticket was filed for G-E1.")),
    M("M-108", "G-RULED", "launder a sign-off through an unattributed quote in §8 (X-31)",
      subst("**Refused, recorded:**", '"The owner approved the rows." **Refused, recorded:**')),
    M("M-109", "G-RULED", "except BQ-14 from the defaults in RULED (X-32)",
      subst("Every default is taken as proposed. The carried", "Every default is taken as"
            " proposed, except BQ-14. The carried")),
    M("M-110", "G-SECREF", "re-point A-22's pack pointer at §7",
      subst("text, never a bare fill (E12-D09 §5). |", "text, never a bare fill (E12-D09 §7). |")),
    M("M-111", "G-SECREF", "re-point the registry's contract pointer at section 12",
      subst("consistency contract (E12-D09 section 10)", "consistency contract (E12-D09 section"
            " 12)", doc="reg")),
    M("M-112", "G-RULED", "drop CMP-188's no-change note from §11",
      subst("**CMP-188 PriceAxis** (BQ-23): no change:", "**CMP-188 PriceAxis** (BQ-23):")),
    M("M-113", "G-RULED", "drop the PR-body PNG embedding from §0",
      subst("and the PR body embeds those PNGs pinned to the base `8f652abb16` (BQ-29), so the"
            " pack adds none;", "so the pack adds none;")),
    M("M-114", "G-RULED", "cite `15`:41 for the three-theme story rule in §11",
      subst("D06H §D's rule (D06H:64), stricter than `15`:41's dark / light × density", "`15`:41")),
    M("M-115", "G-RULED", "drop 'Closed, corrected' from G-D07-2 in §13",
      subst(' the state value "Closed, corrected" and', " and")),
    M("M-116", "G-RULED", "name A-48's source row without its hand-off",
      subst("the E12-D06 hand-off's A-14;", "E12-D06 A-14;")),
    M("M-117", "G-RULED", "drop the `15`:438 source of the strip's Cancel in §7",
      subst(" (as CMP-038's Cancel, `15`:438)", "")),
    M("M-118", "G-AC4", "drop the range row's fallback",
      subst("the instrument's tick size known; else \"—\" |",
            "the instrument's tick size known |")),
    M("M-119", "G-AC4", "drop the time row from the per-mode table",
      resub(r"\| time +\| \"bar close 0:41\"[^\n]*\n", "")),
    M("M-120", "G-RULED", "drop 'on time bars only' from A-51's announcement",
      subst("on time bars only, since no close time can be predicted on non-time bars",
            "on every bar mode")),
    M("M-121", "G-RULED", "drop the tag's role from A-44's New",
      subst('the tag is a `role="note"` with `tabindex="0"` in', "the tag is focusable in")),
    M("M-122", "G-UNSHIPPED", "drop PROPOSED from `dash.2-2` in A-2's New",
      subst("`dash.2-2` (PROPOSED, E11-D05 §7.2) ring", "`dash.2-2` ring")),
    M("M-123", "G-RULED", "gloss `16`:478 as a gate by role in §8",
      subst('This departs from the letter of `16`:478, whose gate checks "that no near-duplicate'
            ' token exists": it is the owner\'s call, not a reading of that gate.',
            '`16`:478\'s gate is "no near-duplicate token" by role.')),
    M("M-124", "G-WALK", "date the E12-S07 row off the fresh reader's run",
      resub(r"\| 2026-10-28( +\| story: E12-S07)", r"| 2026-10-27\1")),
    M("M-125", "G-TOKEN", "drop the non-colour channel of the greyscale pair in §8",
      subst("the pair passes on geometry", "the pair is listed")),
    M("M-126", "G-TOKEN", "simulate a light `color.cvd.buy` equal to the line",
      with_env(cvd_clash)),
    M("M-127", "G-STORIES", "drop the LongTag story from A-44",
      subst("ActionBusy, LongTag, HighContrast", "ActionBusy, HighContrast")),
    M("M-128", "G-STORIES", "drop the frozen-on-stale story from A-23",
      subst(", NonTimeStaleFrozen (band 7A", " (band 7A")),
    M("M-129", "G-RULED", "drop the slot key of CMP-248's `from` / `to` in A-44",
      subst("both x-axis slots: a bar's `index` under the `(generation, index)` key on every bar"
            " mode, never `t_ms`;", "both x-axis positions;")),
    M("M-130", "G-RULED", "drop who floors the progress numbers in §5",
      subst("The host floors `done` and `target`", "The component floors `done` and `target`")),
    M("M-131", "G-RULED", "drop the host's `include_delta` rule in A-22",
      subst(", which the host sets on every delta-bar subscription, PROPOSED)", ")")),
    M("M-132", "G-SURFACE", "drop SCR-031 from the Unit cell of the shown-on row",
      subst("not SCR-041 (no field) | CMP-220 / SCR-042, SCR-031; not SCR-041 (a slot",
            "not SCR-041 (no field) | CMP-220 / SCR-042; not SCR-041 (a slot")),
    M("M-133", "G-SURFACE", "drop the reason of a not-shown surface",
      subst("not SCR-041 (a slot keeps its own value)", "not SCR-041")),
    M("M-134", "G-RULED", "drop `Dismiss` and the clear rule from A-35's strip",
      subst(", each notice with its action and `Dismiss`, cleared when a new load or build starts,"
            " E12-D02 NC-1)", ", E12-D02 NC-1)")),
    M("M-135", "G-NEWBYTES", "double a space inside A-37's New",
      subst("never progress (E12-D02 §7; CMP-023", "never progress  (E12-D02 §7; CMP-023")),
    M("M-136", "G-NEWBYTES", "write three full stops for an ellipsis in A-3's New",
      subst('("bar 3 of 5, opened …") before the candle cells',
            '("bar 3 of 5, opened ...") before the candle cells')),
    M("M-137", "G-WALK", "credit the dry run to the author, not a fresh reader",
      subst("**A fresh reader ran the dry run on 2026-10-28**",
            "**The author ran the dry run on 2026-10-28**")),
    M("M-138", "G-WALK", "make the E12-D11 row's needs disagree with found plus not found",
      resub(r"(\| a11y: E12-D11 \(#312\) +\| )9( )", r"\g<1>10\2")),
    M("M-139", "G-WALK", "drop the frontend-role pass row",
      resub(r"\n\| 2026-10-28 +\| frontend: typeability[^\n]*", "")),
    M("M-140", "G-REID", "simulate another doc at the base holding CMP-248",
      with_env(reid_taken), want=f"docs/design/E33/E33-D04.md holds {REID_NEW} at {BASE}: the id"
      " is taken"),
    M("M-141", "G-REID", "give HistoryMarker E10-D02's id in A-46's addendum",
      subst("**Addendum (E12-D09, #244):** CMP-248 HistoryMarker",
            "**Addendum (E12-D09, #244):** CMP-244 HistoryMarker")),
    M("M-142", "G-REGISTRY", "change the tick record's message from its C-7 string",
      reg_set(("modes", "1", "messages", "0"), "Enter 100 to 1,000,000 trade.")),
    M("M-143", "G-RULED", "append a dated walk to §14",
      subst("No session took place and none is claimed.", "No session took place and none is"
            " claimed. A walk was held on 2026-10-27.")),
    M("P-1", "G-RULED-PIN", "reword an unruled sentence of §0",
      subst("cited by number and page", "cited by number and name")),
    M("P-2", "G-RULED-PIN", "swap two log rows",
      lambda t: _swap_rows(t, "| D04-C14, D05-C23 |", "| D06-G1, DR-1, DR-5 |")),
    M("P-3", "G-RULED-PIN", "drop the blank line before §2's table",
      subst(" rows.\n\n| Row of record", " rows.\n| Row of record")),
    M("P-4", "G-RULED-PIN", "rename §11's heading",
      subst("## 11. Storybook lists and the entry lines", "## 11. Storybook and entry lines")),
    M("P-5", "G-RULED-PIN", "add a sentence to §3's intro",
      subst("each row with its rejected alternative.", "each row with its rejected alternative."
            " The table has eleven rows.")),
    M("P-6", "G-RULED-PIN", "change a C-row's owner lane",
      subst("| retired (§5) | E12-S10 (#396) |", "| retired (§5) | E12-S09 (#421) |")),
)  # fmt: skip


def _swap_rows(t: Texts, a: str, b: str) -> Texts:
    lines = t.spec.split("\n")
    la, lb = split_row(a)[0], split_row(b)[0]
    ia = next(i for i, ln in enumerate(lines) if ln.startswith("|") and split_row(ln)[0] == la)
    ib = next(i for i, ln in enumerate(lines) if ln.startswith("|") and split_row(ln)[0] == lb)
    lines[ia], lines[ib] = lines[ib], lines[ia]
    return replace(t, spec="\n".join(lines))


# ---------------------------------------------------------------------------- self-test and main


def read(rel: str) -> str:
    path = ROOT / rel
    return path.read_text(encoding="utf-8") if path.exists() else ""


def load(env: Env | None = None) -> Texts:
    env = env or Env()
    spec, reg = read(SPEC_REL), read(REG_REL)
    pins = read(PINS_REL) if (ROOT / PINS_REL).exists() else None
    return Texts(spec, reg, pins, read(TOOL_REL), compute(env, spec, reg), env)


def digest() -> list[str]:
    return [hashlib.sha256(read(p).encode()).hexdigest() for p in OWN_PATHS]


def render(found: list[Finding]) -> list[str]:
    out = [f"{f.level} {f.gate}: {f.msg}" for f in found]
    n = {lv: sum(1 for f in found if f.level == lv) for lv in ("FAIL", "WARN", "NOTE")}
    out.append(f"FAIL {n['FAIL']} / WARN {n['WARN']} / NOTE {n['NOTE']}")
    return out


def ascii_line(s: str) -> str:
    return s.encode("ascii", "backslashreplace").decode("ascii")


def selftest() -> tuple[bool, list[str]]:
    before = digest()
    t = load()
    report: list[str] = []
    base_fail = [f for f in audit(t) if f.level == "FAIL"]
    ok = not base_fail
    report.append(f"baseline: {len(base_fail)} FAIL")
    report += [f"  {f.gate}: {f.msg}" for f in base_fail]
    gates_seen: set[str] = set()
    for mu in MUTATIONS:
        try:
            mt = mu.fn(t)
        except (AssertionError, KeyError, IndexError, StopIteration) as e:
            ok = False
            report.append(f"{mu.mid} ERROR: the mutation does not apply ({e})")
            continue
        fails = [f for f in audit(mt) if f.level == "FAIL"]
        good = len(fails) == 1 and fails[0].gate == mu.gate
        good = good and (not mu.want or fails[0].msg == mu.want)
        ok = ok and good
        gates_seen.add(mu.gate)
        got = ", ".join(f.gate for f in fails) or "none"
        report.append(f"{mu.mid} {'ok  ' if good else 'BAD '} {mu.gate}: {mu.desc} -> {got}")
    names = {g.__name__ for g in GATES}
    for g in sorted(names):
        tag = "G-" + g[2:].upper().replace("_", "-")
        if tag not in gates_seen and tag not in ("G-CVD-SRC",):
            pass
    restored = digest() == before
    ok = ok and restored
    report.append(f"restored byte for byte: {'yes' if restored else 'NO'}")
    report.append(f"self-test: {'PASS' if ok else 'FAIL'} ({len(MUTATIONS)} mutations)")
    return ok, report


def write_text(rel: str, text: str) -> None:
    (ROOT / rel).write_text(text, encoding="utf-8", newline="\n")


def fill_mutlist(spec: str) -> str:
    lines = spec.split("\n")
    out, in15, done = [], False, False
    for ln in lines:
        m = HEADING.match(ln)
        if m and len(m[1]) == 2:
            in15 = sec_no(m[2]) == "15"
        if in15 and not done and (ln.startswith("**G-") or ln == "M-PLACEHOLDER"):
            out.append(mutation_paragraph())
            done = True
            continue
        out.append(ln)
    return "\n".join(out)


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fill", action="store_true")
    ap.add_argument("--self-test", "--selftest", dest="selftest", action="store_true")
    ap.add_argument("--repin-ruled", action="store_true")
    ap.add_argument("--a-rows", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        ok, rep = selftest()
        print("\n".join(ascii_line(x) for x in rep))
        return 0 if ok else 1
    if a.fill:
        t = load()
        spec = fill_mutlist(t.spec)
        values = compute(t.env, spec, t.reg)
        spec, missing = fill(spec, values)
        values = compute(t.env, spec, t.reg)
        spec, missing = fill(spec, values)
        write_text(SPEC_REL, spec)
        if missing:
            print("unfilled: " + ", ".join(sorted(set(missing))))
    if a.repin_ruled:
        spec = read(SPEC_REL)
        if PLACEHOLDER.search(without_code(spec)):
            print("refused: a placeholder is unfilled (run --fill first)")
            return 1
        us = units(spec)
        write_text(PINS_REL, write_pins(us))
        print(f"pinned {len(us)} units")
        if not a.check:
            return 0
    t = load()
    if a.a_rows:
        print(json.dumps(a_rows_export(t.spec, t.values), ensure_ascii=False, indent=2))
        return 0
    found = audit(t)
    if a.json:
        print(
            json.dumps(
                {
                    "base": BASE,
                    "values": t.values,
                    "findings": [f.__dict__ for f in found],
                    "a_rows": len(c_rows(t.spec)),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print("\n".join(render(found)))
    return 1 if any(f.level == "FAIL" for f in found) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
