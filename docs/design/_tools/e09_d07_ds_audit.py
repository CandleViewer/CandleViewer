#!/usr/bin/env python3
"""E09-D07 (#190) audit: the design-system pack for the auth component band.

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads AS
TEXT at the pinned base (`git show BASE:<path>`) the plan texts (`02`, `04`, `05`, `12`, `14`,
`15`, `16`, `18`, `20`, `22`, `24`), the merged E09 design docs (D02 ... D12, D03A, D05H, S03),
E12-D09, the design README, the E09 threat model, the token JSON (`themes.json` layering: dark =
primitives + semantic-dark, light = + semantic-light, hc = + semantic-hc), `calendar_cv.py`, the
backlog JSON and the research CVD script; then the pack (`E09-D07.md`), its hand-off
(`E09-D07-handoff.md`), its composition map (`E09-D07-composition.json`) and the pins from the
working tree.

1. **Values.** Every `{{KIND:key}}` outside a code span is COMPUTED: CONTRAST (WCAG 2.x, truncated
   to two decimals, three themes), PAIR (a pair's reading against its bar), CVD (the least CIE76
   distance under the three simulations, one decimal; the least greyscale ratio), COUNT (the
   pack's own rows, ids, stories, records and mutations), DATE (a sprint start from
   `calendar_cv.py` and the backlog JSON) and TOKEN (a primitive's value). `--fill` writes
   `VALUE<!--=KIND:key-->` and the mutation paragraph; `--check` re-derives every anchored value
   (G-ANCHOR) and FAILs a ratio typed by hand (G-FIGURE), a figure typed by hand before a counted
   noun or a count written as a word (G-WORDCOUNT).
2. **Cites.** Every `NN`:line and declared-key:line cite (with `, :n` continuations and `n-m`
   ranges) is read at the base; a missing or blank line FAILs (G-CITE), and the load-bearing
   fragments of CITED must sit on their lines, each reached by a cite of at most 24 lines.
   G-VERSION is content-based: each cited range must stand, in order and contiguous, at its own
   line at `origin/main` or, moved, at the nearest line where it stands (a WARN; a text that
   repeats in its file must keep the two lines before it); a range that stands nowhere (an edit)
   FAILs, and so does an unresolvable `origin/main`. The version line's shas are each input's last
   commit at the base. An input without a cited range is a late change by what the pack's values
   read: a commit after the base to the token JSON or the CVD script, a change to the calendar's
   sprint-1 start or sprint length, or to the sprint field of a ticket a DATE value names (a later
   commit to the calendar or the backlog JSON that moves none of these is not one).
3. **Gates.** Lexicon gates read table cells and prose after the comment strip, NFKC and
   whitespace-normalised: each ruled behaviour has its words REQUIRED where it lives and a synonym
   set FORBIDDEN where a paraphrase would reverse it (a negation in the mention's own clause, or a
   **Forbidden** line, removes a mention). A lexicon is a finite word list: a paraphrase outside
   every list is caught by the default-deny pins alone. The measured gates follow: the ledger and
   its parent rows, the A-rows byte for byte against `15` at the base, the tokens, the pairs, the
   stories, the composition map and the consistency contract, the id band, the log, the C-rows,
   the dry run, the hand-off's ten checklists, the cells of every table row and the line budget.
   **PR 2** (the catalogue PR) is a mode the tree selects: when none of the pack's files differs
   from `git merge-base HEAD origin/main` but `15` does, `15` must equal the merge-base with every
   §C row not in HELD applied, each re-pointed by content (a replace finds its Old, an insert its
   anchor line), with no other byte (files read with no newline translation). A row whose source
   cell reads `applied by #N` (A-1 since #5025, every other row since #5058) already stands at the
   base: G-AROW reads a replace row's New on its line and an insert row's bullets right after its
   anchor line, and PR 2 skips it; it is not a HELD entry. G-UNTOUCHED reads
   committed and uncommitted paths against the merge-base, failing closed when it does not
   resolve or a git call fails: in PR 1 only the pack's five files may differ; PR 3 (the boards)
   also admits the board PNGs and their CVD renders, `sheets/e09-d07/` and `sheets/MANIFEST.sha256`,
   and G-HANDOFF reads a ticked Final Penpot link: it names the band page by name + id and a board
   PNG that is in the tree. G-EDGE matches
   patterns, never literals (S-22, S-23): an all-caps cite key the key table does not declare, a
   server-tree path, a source file with a line number, or a fix-direction wording arm. G-CHARSET
   holds every file to an allow-list of non-ASCII characters (no compatibility form, homoglyph,
   filler or separator); G-ENTRY holds the entry lines to BQ-22/23/32 (only declared fields, one
   Forbidden list with no carve-out, the ruled Performance and Observability lines); G-AHEAD
   refuses a "served" claim for an operation a design-ahead consumer still builds; G-DOD refuses a
   ticked box that names a later act; the map refuses a repeated JSON key.
4. **Pins (G-RULED-PIN).** A whole-document default-deny pin set over every unit of the pack and
   the hand-off (each heading, table row by its lead cell, rule line and prose sentence, by region
   and location, whitespace-normalised and never NFKC, anchored values cut out, plus each region's
   line shape) and every record of the composition map, in `e09_d07_ruled_pins.txt`. `--repin-ruled`
   is the only writer and refuses while a placeholder is unfilled. When another gate FAILs, every
   G-RULED-PIN finding prints as a NOTE; the exit status stays 1.
5. **--self-test** applies every mutation of §13 in memory with the values frozen at the filled
   baseline and `origin/main` read as the base (a late change at the live head never hides a
   mutation; `--check` is the live gate); each must add exactly one FAIL, from the gate it names
   (a mutation marked WARN: exactly one WARN and no FAIL), and every text is restored byte for
   byte (sha256). The report is ASCII, every line at most 100 characters. It re-runs every gate
   once per mutation, so it is slow: about 630 s on the round-1 host (325 s on the round-2 fold's
   host, once the head was frozen). Run it once, at the end, with a timeout of 900 s or more.

The `--json` dump carries values and findings only: no key or value names a credential field.

Usage (from the repo root):
  python3 -I docs/design/_tools/e09_d07_ds_audit.py --check [--json] [--fill]
  python3 -I docs/design/_tools/e09_d07_ds_audit.py --self-test   (slow: about 630 s, see item 5)
  python3 -I docs/design/_tools/e09_d07_ds_audit.py --repin-ruled
  python3 -I docs/design/_tools/e09_d07_ds_audit.py --a-rows
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
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = "fef3148c56"  # `origin/main` at the second re-pin (#5265's merge); merge-base stays 16d70feed9
HEAD_REF = "origin/main"  # drift inside a cited range FAILs (G-VERSION)
SPEC_REL = "docs/design/E09/E09-D07.md"
HAND_REL = "docs/design/E09/E09-D07-handoff.md"
COMP_REL = "docs/design/E09/E09-D07-composition.json"
TOOL_REL = "docs/design/_tools/e09_d07_ds_audit.py"
PINS_REL = "docs/design/_tools/e09_d07_ruled_pins.txt"
OWN_PATHS = (SPEC_REL, HAND_REL, COMP_REL, TOOL_REL, PINS_REL)
CAT_REL = "docs/plan/15-component-catalogue.md"
LINE_BUDGET = 345  # BQ-3: "<= ~300 lines, the #244 sections plus §C"; §C alone is 56 lines
PR1_TITLE = "docs(auth-rbac): E09-D07 design-system contribution for the auth component band"
RULING_ID = "6505239981"
BQ_LIST_ID = "6505027715"
HELD: frozenset[str] = frozenset()  # §C: "The HELD set is empty at the base"

PATHS: dict[str, str] = {
    "02": "docs/plan/02-definition-of-ready-done.md",
    "04": "docs/plan/04-security-program.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "12": "docs/plan/12-sitemap.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": CAT_REL,
    "16": "docs/plan/16-design-system-brief.md",
    "18": "docs/plan/18-traceability-matrix.md",
    "20": "docs/plan/20-architecture.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "24": "docs/plan/24-internal-schemas.md",
    "D02": "docs/design/E09/E09-D02.md",
    "D03": "docs/design/E09/E09-D03.md",
    "D03A": "docs/design/E09/E09-D03-a11y-audit.md",
    "D04": "docs/design/E09/E09-D04.md",
    "D05": "docs/design/E09/E09-D05.md",
    "D05H": "docs/design/E09/E09-D05-handoff.md",
    "D06": "docs/design/E09/E09-D06.md",
    "D08": "docs/design/E09/E09-D08.md",
    "D09": "docs/design/E09/E09-D09.md",
    "D10": "docs/design/E09/E09-D10.md",
    "D12": "docs/design/E09/E09-D12.md",
    "S03": "docs/design/E09/E09-S03.md",
    "E12D09": "docs/design/E12/E12-D09.md",
    "README": "docs/design/README.md",
    "CAL": "docs/plan/backlog/_tools/calendar_cv.py",
    "TM": "docs/security/threat-models/e09-auth-rbac.md",
    "E09J": "docs/plan/backlog/E09.json",
}
ALL_TICKETS = "docs/plan/backlog/all-tickets.json"
CVD_SRC = "docs/research/_tools/cvd_simulate.py"
DS_SRC = "packages/ui/tokens"
THEMES = {
    "dark": ("primitives", "semantic-dark"),
    "light": ("primitives", "semantic-dark", "semantic-light"),
    "hc": ("primitives", "semantic-dark", "semantic-hc"),
}
# the standing rule: no edit to these in PR 1 (`15` only by §C in PR 2)
UNTOUCHED = tuple(PATHS[k] for k in ("05", "14", "15", "16", "22", "24")) + (
    "docs/plan/21-database-schema.md",
    "docs/plan/23-ws-protocol.md",
)
UNTOUCHED_PREFIX = (DS_SRC + "/", "docs/design/E09/E09-D0", "docs/design/E09/E09-D1",
                    "docs/design/E09/E09-S")  # fmt: skip
# BQ-35's version line: input -> the sha of its last commit at the base
VERSION_PINS: dict[str, str] = {
    "D02": "ff8933a1c2",
    "D03": "ff8933a1c2",
    "D04": "ff8933a1c2",
    "D06": "ff8933a1c2",
    "D03A": "a30c6ec6ad",
    "D05": "2145b48036",
    "D05H": "2145b48036",
    "D08": "c99ad48d78",
    "D09": "d117dc7328",
    "S03": "2fd29ecc34",
    "D12": "67ab4aa8a5",
    "D10": "ccaad0fea6",
    "15": "8bae585409",
    "22": "fef3148c56",
}
# inputs that feed computed values but are cited by no line range: a commit to one after the base
# is a late change (G-VERSION). The backlog JSON and the calendar are not listed: most ticket edits
# commit to them, so `date_facts` compares only what the DATE values read from them.
DRIFT_INPUTS: tuple[str, ...] = (
    f"{DS_SRC}/primitives.tokens.json",
    f"{DS_SRC}/semantic-dark.tokens.json",
    f"{DS_SRC}/semantic-light.tokens.json",
    f"{DS_SRC}/semantic-hc.tokens.json",
    f"{DS_SRC}/themes.json",
    CVD_SRC,
)

# ---------------------------------------------------------------------------- git


@dataclass
class Env:
    """The repository facts the gates read; the self-test swaps them to simulate drift."""

    base_cache: dict[str, str | None] = field(default_factory=dict)
    head_cache: dict[str, str | None] = field(default_factory=dict)
    merge_base: Callable[[], str | None] | None = None
    changed: Callable[[str], list[str] | None] | None = None
    head_override: dict[str, str | None] = field(default_factory=dict)
    head_ok: bool | None = None
    last_override: dict[str, str] = field(default_factory=dict)
    cur_override: dict[str, str] = field(default_factory=dict)
    memo: dict[str, object] = field(default_factory=dict)

    def current(self, rel: str) -> str | None:
        """The working-tree text of `rel` (the self-test may swap it)."""
        if rel in self.cur_override:
            return self.cur_override[rel]
        path = ROOT / rel
        return read_raw(path) if path.exists() else None

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
        log = f"log:{key}"
        if log not in self.head_cache:
            self.head_cache[log] = git_out("log", "-1", "--format=%H", rev, "--", rel)
        return self.head_cache[log] or ""

    def mb(self) -> str | None:
        if self.merge_base is not None:
            return self.merge_base()
        out = git_out("merge-base", "HEAD", HEAD_REF)
        return out or None

    def changed_paths(self, mb: str) -> list[str] | None:
        """Committed (`mb..HEAD`) and uncommitted paths; renames count on both sides. None when
        either git call fails (G-UNTOUCHED then FAILs: it never passes on an empty list)."""
        if self.changed is not None:
            return self.changed(mb)
        diff = git_raw("diff", "--name-only", "--no-renames", "-z", mb, "HEAD")
        raw = git_raw("status", "--porcelain", "-z", "--no-renames", "--untracked-files=all")
        if diff is None or raw is None:
            return None
        return sorted({p for p in diff.split("\0") + porcelain_paths(raw) if p})


def porcelain_paths(raw: str) -> list[str]:
    """The paths of `git status --porcelain -z --no-renames`: `XY path` entries, never stripped."""
    return [e[3:] for e in raw.split("\0") if len(e) > 3 and e[2] == " "]


def read_raw(path: Path) -> str:
    """A file's text as is: `newline=""` keeps a CR (universal newlines would drop it)."""
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def git_show(rev: str, rel: str) -> str | None:
    """`rev:rel` as is (bytes decoded, no newline translation)."""
    r = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{rev}:{rel}"], capture_output=True, check=False
    )
    return r.stdout.decode("utf-8") if r.returncode == 0 else None


def git_out(*args: str) -> str:
    r = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return r.stdout.strip() if r.returncode == 0 else ""


def git_raw(*args: str) -> str | None:
    """Stdout as is (never stripped: porcelain status columns start with a space); None when the
    call fails."""
    r = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return r.stdout if r.returncode == 0 else None


def git_ok(*args: str) -> bool:
    r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=False)
    return r.returncode == 0


# ---------------------------------------------------------------------------- markdown

HEADING = re.compile(r"^(#{1,6}) (.*)$")
RULE = re.compile(r"^\|(?:\s*:?-+:?\s*\|)+\s*$")
COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)
ANCHOR = re.compile(r"<!--=([A-Z]+:[^>]+?)-->")
PLACEHOLDER = re.compile(r"\{\{([A-Z]+(?::[^{}]+)?)\}\}")
CODE = re.compile(r"`[^`\n]*`")
ANCHORED = re.compile(r"(`[^`\n]*`|[^\s|(/·]*?)<!--=([A-Z]+:[^>]+?)-->")


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
    if title.startswith("§C"):
        return "C"
    m = re.match(r"(\d+)\. ", title)
    return m[1] if m else title


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
    """NFKC, comments dropped, whitespace collapsed (the REQUIRED and lexicon form)."""
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
SIMS = ("protan", "deutan", "tritan")


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
    """One decimal, truncated: never rounded up across a threshold."""
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
    """`name`'s tokens, layered as `themes.json` says; memoised on the Env."""
    key = f"theme:{name}"
    if key not in env.memo:
        merged: dict[str, str] = {}
        for f in layering(env).get(name, ()):
            for k, v in token_file(env, f).items():
                if isinstance(v, dict) and "$value" in v:
                    merged[k] = v["$value"] if isinstance(v["$value"], str) else "(composite)"
        env.memo[key] = merged
    out = env.memo[key]
    return dict(out) if isinstance(out, dict) else {}


def resolve(tokens: dict[str, str], name: str, depth: int = 0) -> str:
    v = tokens.get(name, "")
    m = re.fullmatch(r"\{([^{}]+)\}", v)
    if m and depth < 20:
        return resolve(tokens, m[1], depth + 1)
    return v


def colour(env: Env, t: str, name: str) -> str:
    v = resolve(theme(env, t), name).upper()
    if not re.fullmatch(r"#[0-9A-F]{6}", v):
        raise SystemExit(f"{name} does not resolve to a colour in {t}")
    return v


def primitive_names(env: Env) -> frozenset[str]:
    return frozenset(token_file(env, "primitives"))


def semantic_names(env: Env) -> frozenset[str]:
    return frozenset(token_file(env, "semantic-dark"))


# ---------------------------------------------------------------------------- calendar

CAL_START = re.compile(r"SPRINT01_START = datetime\.date\((\d+), (\d+), (\d+)\)")
CAL_DAYS = re.compile(r"SPRINT_DAYS = (\d+)")
DATE_KEYS = re.compile(r"(?:\{\{|<!--=)DATE:([^}>]+?)(?:\}\}|-->)")


def sprint_starts(env: Env) -> tuple[datetime.date, int]:
    cal = env.base(PATHS["CAL"])
    m, d = CAL_START.search(cal), CAL_DAYS.search(cal)
    if not m or not d:
        raise SystemExit("calendar_cv.py: no SPRINT01_START / SPRINT_DAYS at the base")
    return datetime.date(int(m[1]), int(m[2]), int(m[3])), int(d[1])


def sprint_date(env: Env, n: int) -> str:
    start, days = sprint_starts(env)
    return (start + datetime.timedelta(days=(n - 1) * days)).isoformat()


@lru_cache(maxsize=8)
def sprint_map(text: str) -> dict[str, str]:
    """The backlog JSON's ticket key -> sprint field (cached by text: read, never changed)."""
    data = json.loads(text)
    return {
        str(t.get("key")): str(t.get("sprint"))
        for t in (data if isinstance(data, list) else [])
        if isinstance(t, dict)
    }


def sprint_no(sprints: dict[str, str], key: str) -> int | None:
    m = re.search(r"(\d+)", sprints.get(key, ""))
    return int(m[1]) if m else None


def ticket_sprint(env: Env, key: str) -> int | None:
    return sprint_no(sprint_map(env.base(ALL_TICKETS)), key)


def date_value(env: Env, key: str) -> str | None:
    m = re.fullmatch(r"Sprint (\d+)", key)
    if m:
        return sprint_date(env, int(m[1]))
    n = ticket_sprint(env, key)
    return sprint_date(env, n) if n is not None else None


def date_keys(spec: str, hand: str) -> list[str]:
    """The keys of the pack's DATE values: a ticket key, or `Sprint N`."""
    return sorted(set(DATE_KEYS.findall(spec + "\n" + hand)))


def date_facts(env: Env, rev: str, keys: list[str]) -> dict[str, str]:
    """All that the DATE values read at `rev`: the calendar's sprint-1 start and its sprint length,
    and the sprint number of each ticket a DATE key names. A later commit to the calendar or the
    backlog JSON that changes none of these leaves the facts equal (content, never a commit)."""
    cal = env.show(rev, PATHS["CAL"]) or ""
    out: dict[str, str] = {}
    for label, rx in (("the calendar's sprint-1 start", CAL_START),
                      ("the calendar's sprint length", CAL_DAYS)):  # fmt: skip
        m = rx.search(cal)
        out[label] = m[0] if m else "unreadable"
    text = env.show(rev, ALL_TICKETS)
    try:
        sprints = sprint_map(text) if text else None
    except ValueError:
        sprints = None
    for key in keys:
        if not key.startswith("Sprint "):
            n = sprint_no(sprints, key) if sprints is not None else None
            out[f"{key}'s sprint in the backlog JSON"] = str(n) if n is not None else "none"
    return out


# ---------------------------------------------------------------------------- cites

CITE_KEY = (
    r"`(?:0[245]|1[24568]|2[024])`|D0[2-9][AH]?(?![\w-])|D1[02](?![\w-])"
    r"|S03|E12D09|README|CAL|TM|E09J"
)
CITE = re.compile(rf"(?<![\w`-])({CITE_KEY}):(\d+)(?:[–-](\d+))?((?:, :\d+(?:[–-]\d+)?)*)")
CONT = re.compile(r":(\d+)(?:[–-](\d+))?")


@dataclass(frozen=True)
class Cite:
    key: str
    lo: int
    hi: int
    line_no: int  # where in the text
    doc: str = "spec"


def cites_in(text: str, doc: str = "spec") -> list[Cite]:
    out: list[Cite] = []
    for i, ln in enumerate(text.split("\n"), 1):
        for m in CITE.finditer(strip_comments(ln)):
            key = m[1].strip("`")
            lo = int(m[2])
            out.append(Cite(key, lo, int(m[3]) if m[3] else lo, i, doc))
            for c in CONT.finditer(m[4] or ""):
                a = int(c[1])
                out.append(Cite(key, a, int(c[2]) if c[2] else a, i, doc))
    return out


# Load-bearing fragments: each must sit on the cited line at the base.
CITED: dict[tuple[str, int], tuple[str, ...]] = {
    ("15", 31): ("241–242, 244–247 unassigned",),
    ("15", 395): ("never contains the copied value",),
    ("15", 1068): ("`steps: {id, label, state:",),
    ("15", 1069): ("aria-disabled",),
    ("15", 1079): ("one-click extend",),
    ("15", 2595): ("## 7A.",),
    ("15", 2601): ("every pre-auth screen",),
    ("15", 2603): ("receives focus on appearance",),
    ("15", 2654): ("whose name contains its visible heading",),
    ("15", 2680): ('"Print"',),
    ("15", 3200): ("**247",),
    ("15", 3212): ("244–247 are held",),
    ("15", 3218): ("Decision",),
    ("16", 633): ("the catalogue itself if the catalogue was wrong",),
    ("14", 124): ("node name",),
    ("14", 200): ("100 ms",),
    ("22", 1404): ("shown exactly once",),
    ("22", 1721): ("authExtendSession",),
    ("22", 1831): ("authLock",),
    ("22", 1832): ('CMP-098 "Lock now"',),
    ("22", 13468): ("secret_base32",),
    ("22", 18427): ("otpauth_uri",),
    ("22", 23349): ("environment",),
    ("22", 23387): ("not_applicable",),
    ("22", 23388): ("reason",),
    ("22", 23389): ("unblock_at",),
    ("22", 24368): ("built_at",),
    ("D03", 158): ("Verification code",),
    ("D04", 73): ("untinted",),
    ("D04", 83): ("6-digit authentication code",),
    ("D04", 107): ("Download as .txt",),
    ("D05", 100): ("the wizard step",),
    ("D05", 186): ("focused field only",),
    ("D05", 258): ("the CMP-200 region",),
    ("D05", 550): ("the region for form-level failures only",),
    ("D05", 585): ("caps-lock string",),
    ("D06", 80): ("No library component modified",),
    ("D08", 79): ("CMP-098 is a modal on the chassis",),
    ("D08", 114): ("frame 0",),
    ("D08", 456): ("(G-2)", "Esc dismisses and extends nothing"),
    ("D09", 75): ("rbac.owner_only",),
    ("D10", 268): ("Two-factor code", "one-time-code"),
    ("D10", 930): ("the QR's accessible name",),
    ("D10", 947): ("whose name contains its visible heading",),
    ("D10", 948): ("before the admin token's end",),
    ("D12", 60): ("#190 takes §6 as its input",),
    ("D12", 252): ("not published",),
    ("D12", 424): ("Q-9",),
    ("D12", 425): ("Q-10",),
    ("D12", 488): ("`version: string`",),
    ("S03", 142): ("Stay signed in",),
    ("TM", 133): ("U26",),
}


def lines_of(text: str) -> list[str]:
    return text.split("\n")


def line_index(lines: list[str]) -> dict[str, list[int]]:
    """A line's text -> its 0-based positions."""
    out: dict[str, list[int]] = {}
    for i, ln in enumerate(lines):
        out.setdefault(ln, []).append(i)
    return out


def stands(lines: list[str], index: dict[str, list[int]], block: list[str]) -> list[int]:
    """Every 0-based line where `block` stands in `lines`, in order and contiguous."""
    n = len(block)
    return [p for p in index.get(block[0], ()) if lines[p : p + n] == block]


CONTEXT = 2  # lines before a repeated text that a moved copy must keep (G-VERSION)


def locate(
    base: list[str],
    head: list[str],
    bidx: dict[str, list[int]],
    hidx: dict[str, list[int]],
    lo: int,
    hi: int,
) -> int | None:
    """Where the cited base block (1-based `lo`..`hi`) stands in `head`, as a 0-based line: its own
    line when unchanged there, else the nearest line where it stands (a move). A text that repeats
    in either file proves nothing alone, so a moved copy must keep the CONTEXT lines before it.
    None when it stands nowhere (an edit)."""
    block, at = base[lo - 1 : hi], lo - 1
    if head[at : at + len(block)] == block:
        return at
    found = stands(head, hidx, block)
    if len(found) > 1 or len(stands(base, bidx, block)) > 1:
        k = min(CONTEXT, at)
        found = [p for p in found if p >= k and head[p - k : p] == base[at - k : at]]
    return min(found, key=lambda p: abs(p - at), default=None)


CiteHit = tuple[str, Cite]


def cite_problems(
    env: Env, cites: list[Cite], at_head: bool = True
) -> tuple[list[CiteHit], list[CiteHit], list[CiteHit]]:
    """(FAILs, edited, moved) for every cite. FAILs: a gone or blank line, a missing fragment, at
    the base. At `origin/main` (unless `at_head` is off): the range stands nowhere (edited) or at
    another line (moved)."""
    bad: list[CiteHit] = []
    edited: list[CiteHit] = []
    moved: list[CiteHit] = []
    head_ok = at_head and env.head_resolves()
    bases: dict[str, tuple[list[str], dict[str, list[int]]]] = {}
    heads: dict[str, tuple[list[str], dict[str, list[int]]] | None] = {}
    for c in cites:
        if c.key not in bases:
            lines = lines_of(env.base(PATHS[c.key]))
            bases[c.key] = (lines, line_index(lines))
        base, bidx = bases[c.key]
        if c.hi < c.lo or c.hi > len(base) or any(not base[n - 1].strip() for n in (c.lo, c.hi)):
            bad.append((f"{c.key}:{c.lo}-{c.hi} is gone or blank at {BASE}", c))
            continue
        span = "\n".join(base[c.lo - 1 : c.hi])
        for n in range(c.lo, c.hi + 1):
            for frag in CITED.get((c.key, n), ()):
                if frag not in span:
                    bad.append((f"{c.key}:{n} no longer holds {frag!r}", c))
        if head_ok:
            if c.key not in heads:
                text = env.show(HEAD_REF, PATHS[c.key])
                hl = None if text is None else lines_of(text)
                heads[c.key] = None if hl is None else (hl, line_index(hl))
            found = heads[c.key]
            if found is None:
                edited.append((f"{PATHS[c.key]} is gone at {HEAD_REF}", c))
                continue
            at = locate(base, found[0], bidx, found[1], c.lo, c.hi)
            if at is None:
                edited.append((f"{c.key}:{c.lo}-{c.hi} was edited at {HEAD_REF}", c))
            elif at != c.lo - 1:
                to = f"{at + 1}-{at + 1 + c.hi - c.lo}"
                moved.append((f"{c.key}:{c.lo}-{c.hi} moved to {to} at {HEAD_REF}", c))
    return bad, edited, moved


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


def new_of(spec: str, aid: str) -> str:
    r = a_row(spec, aid)
    return unescape(r[5]) if r and len(r) >= 6 else ""


BR = " <br> "
STORY_ROWS = {
    "CMP-097": "A-4",
    "CMP-098": "A-9",
    "CMP-201": "A-19",
    "CMP-202": "A-24",
    "CMP-203": "A-30",
    "CMP-204": "A-36",
    "CMP-206": "A-45",
    "CMP-207": "A-50",
}
STORY_BASE = {"CMP-200": 2605, "CMP-205": 2669}  # unchanged entries: `15` at the base


def parse_stories(line: str) -> list[str]:
    m = re.search(r"\*\*Storybook\*\*:\s*(.*?)(?: \((?:every|the)[^()]*\))?\.?$", line)
    if not m:
        return []
    body = re.sub(r"\([^()]*\)", "", m[1])
    return [x.strip() for x in body.split(",") if x.strip()]


def stories(env: Env, spec: str, cid: str) -> list[str]:
    if cid in STORY_ROWS:
        return parse_stories(new_of(spec, STORY_ROWS[cid]))
    return parse_stories(lines_of(env.base(CAT_REL))[STORY_BASE[cid] - 1])


def ledger_rows(spec: str) -> list[list[str]]:
    return table_after(sec(spec, "2"), "L")


def log_ids(spec: str) -> list[str]:
    ids: list[str] = []
    for r in table_after(sec(spec, "11"), "Ids"):
        ids += [x.strip() for x in r[0].split(",") if x.strip()]
    return ids


def walk_rows(spec: str) -> list[list[str]]:
    return table_after(sec(spec, "12"), "Date")


def no_dup_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    keys = [k for k, _ in pairs]
    dup = next((k for k in keys if keys.count(k) > 1), None)
    if dup is not None:
        raise ValueError(f"the key {dup!r} repeats in one object")
    return dict(pairs)


def comp_dups(text: str) -> str | None:
    """The first repeated key of any object of the map (json keeps the last silently)."""
    try:
        json.loads(text, object_pairs_hook=no_dup_keys)
    except ValueError as e:
        return str(e)
    return None


def comp_doc(text: str) -> dict[str, object]:
    try:
        d = json.loads(text)
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}


def comp_records(text: str) -> list[dict[str, object]]:
    recs = comp_doc(text).get("records", [])
    return [r for r in recs if isinstance(r, dict)] if isinstance(recs, list) else []


def render_comp(text: str) -> list[list[str]]:
    """The spec's §8 table, one row per screen, rendered from the map."""
    recs = comp_records(text)
    order = list(dict.fromkeys(str(r.get("screen")) for r in recs))
    rows: list[list[str]] = []
    for sc in order:
        rs = [r for r in recs if r.get("screen") == sc]
        auth = list(dict.fromkeys(str(r.get("auth")) for r in rs))
        comps: list[str] = []
        for c in dict.fromkeys(str(r.get("component")) for r in rs):
            vs: list[str] = []
            for r in rs:
                if r.get("component") == c:
                    for v in str(r.get("variant")).split(", "):
                        if v not in vs:
                            vs.append(v)
            comps.append(f"{c} {', '.join(vs)}")
        st = list(dict.fromkeys(str(r.get("status")) for r in rs))
        ev = [e for e in dict.fromkeys(str(r.get("event")) for r in rs) if e != "—"]
        rows.append(
            [sc, " / ".join(auth), " · ".join(comps), "; ".join(st),
             ", ".join(f"`{e}`" for e in ev) or "—"]
        )  # fmt: skip
    return rows


# ---------------------------------------------------------------------------- values

# §6: (pair id, foreground, background, kind) as each entry's Tokens line names them
PAIRS: tuple[tuple[str, str, str, str], ...] = (
    ("P-1", "color.text.primary", "color.surface.raised", "text"),
    ("P-2", "color.status.danger.strong", "color.status.danger.subtle", "text"),
    ("P-3", "color.text.link", "color.surface.raised", "text"),
    ("P-4", "color.text.tertiary", "color.surface.app", "non-text"),
    ("P-5", "color.focus.ring", "color.surface.app", "non-text"),
    ("P-6", "color.border.strong", "color.surface.raised", "non-text"),
    ("P-7", "color.text.secondary", "color.surface.raised", "text"),
    ("P-8", "color.status.success.strong", "color.surface.raised", "non-text"),
    ("P-9", "color.text.primary", "color.surface.sunken", "text"),
    ("P-10", "color.text.secondary", "color.surface.raised", "text"),
    ("P-11", "color.text.primary", "color.surface.overlay", "text"),
    ("P-12", "color.text.secondary", "color.surface.overlay", "text"),
    ("P-13", "color.text.secondary", "color.surface.raised", "text"),
)
CVD_PAIRS = (
    ("CR-1", "color.status.success.strong", "color.text.secondary"),
    ("CR-2", "color.status.danger.strong", "color.text.primary"),
)
# `05`:125 (text 4.5, dark and light), :130 (high contrast >= 7 for text), :126 (non-text 3)
BARS = {("text", "dark"): 4.5, ("text", "light"): 4.5, ("text", "hc"): 7.0}
NONTEXT_BAR = 3.0
THEME_WORD = {"dark": "dark", "light": "light", "hc": "high contrast"}


def pair_values(env: Env) -> dict[str, str]:
    v: dict[str, str] = {}
    for pid, fg, bg, kind in PAIRS:
        k = pid.lower().replace("-", "")
        below: list[str] = []
        for t in THEMES:
            r = contrast(colour(env, t, fg), colour(env, t, bg))
            v[f"CONTRAST:{k}.{t}"] = show_ratio(r)
            bar = BARS.get((kind, t), NONTEXT_BAR)
            if math.floor(r * 100 + 1e-9) / 100 < bar:
                below.append(THEME_WORD[t])
        v[f"PAIR:{k}"] = "`meets`" if not below else "`below: " + ", ".join(below) + "`"
    for cid, a, b in CVD_PAIRS:
        k = cid.lower().replace("-", "")
        greys: list[float] = []
        for t in THEMES:
            ca, cb = colour(env, t, a), colour(env, t, b)
            d = min(delta_e(simulate(ca, s), simulate(cb, s)) for s in SIMS)
            v[f"CVD:{k}.{t}"] = show_de(d)
            greys.append(contrast(ca, cb))
        v[f"CVD:{k}.grey"] = show_ratio(min(greys))
    return v


def token_number(env: Env, name: str) -> str:
    raw = resolve(theme(env, "dark"), name)
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(?:px)?", raw)
    if not m:
        raise SystemExit(f"{name} does not resolve to a number")
    return m[1]


def count_values(env: Env, spec: str, comp: str) -> dict[str, str]:
    out: dict[str, str] = {}
    led = ledger_rows(spec)
    out["COUNT:ledger"] = str(len(led))
    for key, word in (
        ("applied", "applied"),
        ("amended", "applied-as-amended"),
        ("closed", "closed-by-#4086"),
        ("held", "held (owner)"),
        ("routed", "routed"),
    ):
        out[f"COUNT:ledger.{key}"] = str(
            sum(1 for r in led if len(r) > 3 and disposition(r[3]) == word)
        )
    out["COUNT:arows"] = str(len(c_rows(spec)))
    out["COUNT:pairs"] = str(len(table_after(sec(spec, "6"), "P")))
    out["COUNT:log.ids"] = str(len(log_ids(spec)))
    walk = walk_rows(spec)
    out["COUNT:walk.rows"] = str(len(walk))
    for i, k in ((2, "needs"), (3, "found"), (4, "nf")):
        out[f"COUNT:walk.{k}"] = str(sum(int(r[i]) for r in walk if len(r) > i and r[i].isdigit()))
    out["COUNT:mutations"] = str(len(MUTATIONS))
    for cid in ("CMP-200", "CMP-201", "CMP-202", "CMP-203", "CMP-204", "CMP-205", "CMP-206",
                "CMP-207", "CMP-097", "CMP-098"):  # fmt: skip
        out[f"COUNT:stories.{cid.lower().replace('-', '')}"] = str(len(stories(env, spec, cid)))
    recs = comp_records(comp)
    out["COUNT:comp.records"] = str(len(recs))
    out["COUNT:comp.screens"] = str(len({str(r.get("screen")) for r in recs}))
    out["COUNT:comp.local"] = str(sum(1 for r in recs if r.get("status") == STATUS_LOCAL))
    out["COUNT:comp.held"] = str(sum(1 for r in recs if r.get("status") == STATUS_HELD))
    return out


def compute(env: Env, spec: str, hand: str, comp: str) -> dict[str, str]:
    v = pair_values(env)
    v.update(count_values(env, spec, comp))
    both = spec + "\n" + hand
    for key in date_keys(spec, hand):
        d = date_value(env, key)
        if d:
            v[f"DATE:{key}"] = d
    for key in set(re.findall(r"(?:\{\{|<!--=)TOKEN:([^}>]+?)(?:\}\}|-->)", both)):
        v[f"TOKEN:{key}"] = token_number(env, key)
    return v


def code_spans(line: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in CODE.finditer(line)]


def fill(text: str, values: dict[str, str]) -> tuple[str, list[str]]:
    """Write every placeholder outside a code span as `VALUE<!--=KEY-->`; re-fill anchors."""
    missing: list[str] = []
    out_lines = []
    for ln in text.split("\n"):
        spans = code_spans(ln)

        def ph(m: re.Match[str], spans: list[tuple[int, int]] = spans) -> str:
            if any(a <= m.start() < b for a, b in spans) or m[1] == "MUTLIST":
                return m[0]
            if m[1] not in values:
                missing.append(m[1])
                return m[0]
            return f"{values[m[1]]}<!--={m[1]}-->"

        out_lines.append(PLACEHOLDER.sub(ph, ln))
    text = "\n".join(out_lines)

    def refresh(m: re.Match[str]) -> str:
        key = m[2]
        return f"{values[key]}<!--={key}-->" if key in values else m[0]

    return ANCHORED.sub(refresh, text), missing


def unfill(text: str) -> str:
    """The text with every anchored value cut (the pins' form)."""
    return ANCHORED.sub(r"<!--=\2-->", text)


def anchored(text: str) -> list[tuple[str, str, int]]:
    """(value, key, line) of every anchor."""
    out = []
    for i, ln in enumerate(text.split("\n"), 1):
        for m in ANCHORED.finditer(ln):
            out.append((m[1], m[2], i))
    return out


# ---------------------------------------------------------------------------- pins

Unit = tuple[str, str, str]  # (region, location, normalised text)
FULL_STOP = re.compile(r"(?<=[.!?])\s+(?=[*`\"(A-Z0-9§])")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def pin_norm(text: str) -> str:
    """Whitespace collapsed, never NFKC: a compatibility character is a change (G-CHARSET too)."""
    return " ".join(text.split())


def line_form(line: str) -> str:
    if re.match(r"^\s*[-*+] ", line):
        return "b"
    if re.match(r"^\s*\d+\. ", line):
        return "n"
    return "p"


def units(text: str, doc: str) -> list[Unit]:
    """Every unit of a document: per region (the heading path, `#n` its occurrence), the heading,
    the line shape, each rule line, each table row by its lead cell and each prose sentence."""
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


def comp_units(comp: str) -> list[Unit]:
    d = comp_doc(comp)
    out: list[Unit] = [
        ("comp:head", key, json.dumps(d.get(key), ensure_ascii=False, sort_keys=True))
        for key in sorted(d)
        if key != "records"
    ]
    for r in comp_records(comp):
        out.append(
            ("comp:records", str(r.get("id")), json.dumps(r, ensure_ascii=False, sort_keys=True))
        )
    return out


def all_units(spec: str, hand: str, comp: str) -> list[Unit]:
    return units(spec, "spec") + units(hand, "hand") + comp_units(comp)


def write_pins(us: list[Unit]) -> str:
    head = (
        "# E09-D07 pins (every unit of the pack, the hand-off and the map): region, location, "
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


def pin_problems(pinned: list[Unit], current: list[Unit]) -> list[str]:
    """One message per region that differs."""
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
    level: str  # FAIL, WARN or NOTE
    gate: str
    msg: str


@dataclass
class Texts:
    spec: str
    hand: str
    comp: str
    pins: str | None
    tool: str
    values: dict[str, str]
    env: Env


def one(gate: str, problems: list[str], level: str = "FAIL") -> list[Finding]:
    """Each gate reports one line per level: its first problem and the count of the rest."""
    if not problems:
        return []
    more = f" (+{len(problems) - 1} more)" if len(problems) > 1 else ""
    return [Finding(level, gate, problems[0] + more)]


def docs(t: Texts) -> list[tuple[str, str]]:
    return [("spec", t.spec), ("hand", t.hand)]


QUOTED = re.compile(r'"([^"\n]*)"|“([^”\n]*)”')
NEG = re.compile(r"\b(?:no|never|not|nor|without|none|nothing|cannot|retired|dropped)\b")
CLAUSE_BREAK = re.compile(r"[,;:(—–·]|\bbut\b|\byet\b|\bthough\b|\balthough\b")


def corpus(env: Env) -> str:
    """Every merged text a quote may come from, read at the base; memoised (lower case)."""
    if "corpus" not in env.memo:
        texts = [env.show(BASE, rel) or "" for rel in sorted(set(PATHS.values()))]
        texts.append(env.show(BASE, ALL_TICKETS) or "")
        env.memo["corpus"] = norm("\n".join(texts)).lower()
    out = env.memo["corpus"]
    return out if isinstance(out, str) else ""


def live_plain(t: str, term: str) -> bool:
    """`term` asserted in `t` (already plain): a mention counts as negated only when a negation
    stands in its own clause, at most four words before it."""
    for m in re.finditer(term, t):
        head = t[: m.start()]
        cut = [b.end() for b in CLAUSE_BREAK.finditer(head)]
        clause = head[cut[-1] :] if cut else head
        before = clause.split()[-4:]
        if not any(NEG.fullmatch(w.strip(",;:()")) for w in before):
            return True
    return False


def disposition(cell: str) -> str:
    for word in ("applied-as-amended", "closed-by-#4086", "held (owner)", "routed", "applied"):
        if cell.startswith(word):
            return word
    return ""


# ---------------------------------------------------------------------------- the gates


def g_anchor(t: Texts) -> list[Finding]:
    bad = []
    for doc, text in docs(t):
        for val, key, n in anchored(text):
            if key not in t.values:
                bad.append(f"{doc}:{n}: anchor {key} is not a value the tool computes")
            elif val != t.values[key]:
                bad.append(f"{doc}:{n}: {key} reads {val!r}, the tool computes {t.values[key]!r}")
        for i, ln in enumerate(text.split("\n"), 1):
            m = PLACEHOLDER.search(without_code(ln))
            if m and m[1] != "MUTLIST":
                bad.append(f"{doc}:{i}: a placeholder is unfilled (run --fill)")
    return one("G-ANCHOR", bad)


LINKREF = re.compile(r"^ {0,3}\[[^\]\n]+\]:(?:\s|$)", re.MULTILINE)


def g_marker(t: Texts) -> list[Finding]:
    bad: list[str] = []
    for doc, text in docs(t):
        bad += [
            f"{doc}: a comment that is not a value anchor: {m[0][:40]!r}"
            for m in COMMENT.finditer(text)
            if not ANCHOR.fullmatch(m[0])
        ]
        bad += [f"{doc}: a link-reference definition hides text" for _ in LINKREF.finditer(text)]
    return one("G-MARKER", bad)


RATIO = re.compile(r"(?<![\w.])\d+(?:\.\d+)?:1\b")
HEX = re.compile(r"(?<![\w&])#[0-9A-Fa-f]{6}(?![0-9A-Za-z])")
BAR_FIGURES = frozenset({"4.5:1", "7:1", "3:1"})  # `05`:125, :130, :126: the bars, cited


def g_figure(t: Texts) -> list[Finding]:
    """A ratio or hex typed by hand (outside an anchor, a code span and §C's Old cells)."""
    bad = []
    for doc, text in docs(t):
        cut = ANCHORED.sub(" ", text)
        for i, ln in enumerate(cut.split("\n"), 1):
            body = without_code(ln)
            if ln.startswith("| A-"):
                cells = split_row(ln)
                body = without_code(unescape(cells[5])) if len(cells) >= 6 else body
            for m in list(RATIO.finditer(body)) + list(HEX.finditer(body)):
                if m[0] not in BAR_FIGURES:
                    bad.append(f"{doc}:{i}: {m[0]!r} is typed by hand (use a placeholder)")
    return one("G-FIGURE", bad)


COUNTED = r"(?:rows|records|pairs|mutations|stories|ids)"
NUMBER_WORDS = (
    r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen"
    r"|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty"
)


def g_wordcount(t: Texts) -> list[Finding]:
    bad = []
    n = t.spec.count("\n")
    if n > LINE_BUDGET:
        bad.append(f"the pack has {n} lines; the budget is {LINE_BUDGET}")
    for doc, text in docs(t):
        cut = ANCHORED.sub("#", text)
        for i, ln in enumerate(cut.split("\n"), 1):
            body = without_code(ln)
            for m in re.finditer(rf"(?<![\w.#<-])(\d+) {COUNTED}\b", body):
                bad.append(f"{doc}:{i}: {m[0]!r} is typed by hand (use a COUNT placeholder)")
            for m in re.finditer(
                rf"\b(?:{NUMBER_WORDS})(?:-\w+)? {COUNTED}\b", body, re.IGNORECASE
            ):
                bad.append(f"{doc}:{i}: {m[0]!r} is a count written as a word")
    return one("G-WORDCOUNT", bad)


def all_cites(t: Texts) -> list[Cite]:
    return cites_in(t.spec, "spec") + cites_in(t.hand, "hand")


NARROW = 26  # `22`:1828–1853, the authLock block, is the widest load-bearing cite


def g_cite(t: Texts) -> list[Finding]:
    cites = all_cites(t)
    bad, _, _ = cite_problems(t.env, cites, at_head=False)
    out = [f"{c.doc}:{c.line_no}: {m}" for m, c in bad]
    for key, n in CITED:  # a narrow cite (a block of at most NARROW lines) reaches each one
        if not any(c.key == key and c.lo <= n <= c.hi <= c.lo + NARROW for c in cites):
            out.append(f"{key}:{n} carries a load-bearing fragment and no cite reaches it")
    return one("G-CITE", out)


def version_line(spec: str) -> str:
    return next((ln for ln in spec.split("\n") if "**Version line**" in ln), "")


def g_version(t: Texts) -> list[Finding]:
    if not t.env.head_resolves():
        return one("G-VERSION", [f"{HEAD_REF} does not resolve: the drift check cannot run"])
    _, edited, moved = cite_problems(t.env, all_cites(t))
    bad = [f"{c.doc}:{c.line_no}: {m}" for m, c in edited]
    vline = version_line(t.spec)
    if f"**v1 at base `{BASE}`**" not in vline:
        bad.append(f"the version line does not read v1 at base `{BASE}`")
    # a pinned input is cited by range: its late change is an edit inside a cited range (above);
    # a commit elsewhere in it, or a move, is not (lens 2, n-2)
    for key, sha in VERSION_PINS.items():
        rel = PATHS[key]
        at_base = t.env.last_commit(BASE, rel)
        if not at_base.startswith(sha):
            bad.append(f"{key}'s last commit at the base is {at_base[:10]}, the line pins {sha}")
        if f"`{sha}`" not in vline:
            bad.append(f"the version line does not pin {key} at `{sha}`")
    for rel in DRIFT_INPUTS:
        if t.env.last_commit(HEAD_REF, rel) != t.env.last_commit(BASE, rel):
            bad.append(f"{rel} changed at {HEAD_REF} after the base: a late change (§0)")
    # the backlog JSON and the calendar feed only the DATE values: a late change is a change to
    # what those read, never a commit that moves none of it
    keys = date_keys(t.spec, t.hand)
    was, now = date_facts(t.env, BASE, keys), date_facts(t.env, HEAD_REF, keys)
    for fact, value in was.items():
        if now[fact] != value:
            bad.append(
                f"{fact} reads {value} at the base and {now[fact]} at {HEAD_REF}: "
                "a late change (§0)"
            )
    warn = [f"{c.doc}:{c.line_no}: {m}" for m, c in moved]
    return one("G-VERSION", bad) + one("G-VERSION", warn, "WARN")


# ---------------------------------------------------------------------------- PR 2: applying §C

OPS = ("replace", "insert bullet after", "insert bullets after")
APPLIED_BY = re.compile(r"\bapplied by (#\d+)$")
FIELD = re.compile(r"`15`:(\d+)")


def a_rows_export(spec: str, base15: str) -> list[dict[str, object]]:
    """§C as data for PR 2: anchors dropped, their values kept, escapes undone; each row carries
    its anchor (the target line at BASE) so PR 2 re-points it by content, and `applied_by` (the
    merged PR its source cell names, else None) so PR 2 skips a row that already stands."""
    out: list[dict[str, object]] = []
    lines = lines_of(base15)
    for r in c_rows(spec):
        if len(r) != 7:
            continue
        m = FIELD.fullmatch(r[2])
        n = int(m[1]) if m else 0
        new = re.sub(r"<!--=[A-Z]+:[^>]+?-->", "", unescape(r[5]))
        head = next((lines[i] for i in range(min(n, len(lines)) - 1, -1, -1)
                     if lines[i].startswith("### ")), "")  # fmt: skip
        out.append(
            {
                "id": r[0],
                "target": r[1],
                "file": CAT_REL,
                "line": n,
                "entry": head,
                "anchor": lines[n - 1] if 0 < n <= len(lines) else "",
                "op": r[3],
                "old": [] if r[4] == "—" else [unescape(r[4])],
                "new": new.split(BR),
                "from": r[6],
                "applied_by": applied_by(r[6]),
            }
        )
    return out


def applied_by(source: str) -> str | None:
    """The merged PR a §C row's source cell names as having applied it (`applied by #N`)."""
    m = APPLIED_BY.search(source)
    return m[1] if m else None


def apply_rows(
    text: str, rows: list[dict[str, object]], held: frozenset[str]
) -> tuple[str, list[str]]:
    """`text` with every row not in `held` and not already applied (`applied_by`) applied,
    re-pointed by content: its entry heading, then its anchor line inside that entry, each found
    once; (result, problems)."""
    lines = lines_of(text)
    bad: list[str] = []
    plan: list[tuple[int, int, dict[str, object]]] = []
    for k, r in enumerate(rows):
        if r["id"] in held or r.get("applied_by"):
            continue
        heads = [i for i, ln in enumerate(lines) if ln == r["entry"]]
        if len(heads) != 1:
            bad.append(f"{r['id']}: its entry heading stands {len(heads)} times in {CAT_REL}")
            continue
        end = next((i for i in range(heads[0] + 1, len(lines)) if lines[i].startswith("#")),
                   len(lines))  # fmt: skip
        hits = [i for i in range(heads[0], end) if lines[i] == r["anchor"]]
        if len(hits) != 1:
            bad.append(f"{r['id']}: its anchor stands {len(hits)} times in its entry")
            continue
        plan.append((hits[0], k, r))
    # bottom-up; on one line the replace (listed first) lands before the insert after it
    for i, _, r in sorted(plan, key=lambda p: (-p[0], -p[1])):
        new = [str(x) for x in r["new"]] if isinstance(r["new"], list) else []
        if r["op"] == "replace":
            lines[i : i + 1] = new
        else:
            lines[i + 1 : i + 1] = new
    return "\n".join(lines), bad


def pack_changed(paths: list[str]) -> bool:
    return any(p in OWN_PATHS for p in paths)


# PR 3 (the boards; the orchestrator's PR 3 answers): the board PNGs and their CVD renders, the
# board script's folder and the sheets MANIFEST it is listed in
PR3_IMG = re.compile(r"docs/design/E09/img/E09-D07-\d\d-[a-z0-9-]+\.png")
PR3_SHEETS = "docs/design/_tools/sheets/e09-d07/"
PR3_MANIFEST = "docs/design/_tools/sheets/MANIFEST.sha256"


def pr3_path(p: str) -> bool:
    return bool(PR3_IMG.fullmatch(p)) or p.startswith(PR3_SHEETS) or p == PR3_MANIFEST


def g_untouched(t: Texts) -> list[Finding]:
    mb = t.env.mb()
    if not mb:
        return one("G-UNTOUCHED", [f"`git merge-base HEAD {HEAD_REF}` does not resolve"])
    paths = t.env.changed_paths(mb)
    if paths is None:
        return one(
            "G-UNTOUCHED", ["cannot list the changed paths (`git diff` or `git status` failed)"]
        )
    bad: list[str] = []
    pr2 = not pack_changed(paths) and CAT_REL in paths
    for p in paths:
        if p in OWN_PATHS or pr3_path(p):
            continue
        if p == CAT_REL and pr2:
            at_mb = t.env.base(CAT_REL) if mb.startswith(BASE) else (t.env.show(mb, CAT_REL) or "")
            want, probs = apply_rows(at_mb, a_rows_export(t.spec, t.env.base(CAT_REL)), HELD)
            bad += probs
            got = t.env.current(CAT_REL) or ""
            if got != want:
                w, g = want.split("\n"), got.split("\n")
                n = next((i for i, (x, y) in enumerate(zip(w, g, strict=False), 1) if x != y),
                         min(len(w), len(g)) + 1)  # fmt: skip
                bad.append(f"{p} differs from §C applied to the merge-base (line {n})")
        elif p in UNTOUCHED or p.startswith(UNTOUCHED_PREFIX):
            bad.append(f"{p} changed against the merge-base: the standing rule keeps it untouched")
        else:
            bad.append(f"{p} changed against the merge-base: outside the pack's files")
    return one("G-UNTOUCHED", bad)


BAD_CHARS = re.compile(
    r"[\u0000-\u0008\u000b-\u001f\u007f\u00a0\u00ad\u200b-\u200f\u202a-\u202e\u2060-\u2069"
    r"\ufeff]"
)


# every non-ASCII character the files may hold (lens 2, m-1): a compatibility form (a superscript,
# a fullwidth digit), a homoglyph (Cyrillic, Greek), a filler or a line separator FAILs
ALLOWED = frozenset("§·×é–—…→←−≤≥")
ALLOWED_TOOL = ALLOWED | frozenset("“”›")


def g_charset(t: Texts) -> list[Finding]:
    bad = []
    for doc, text in (*docs(t), ("comp", t.comp), ("tool", t.tool)):
        ok = ALLOWED_TOOL if doc == "tool" else ALLOWED
        for i, ln in enumerate(text.split("\n"), 1):
            m = BAD_CHARS.search(ln.replace("\t", " ") if doc == "tool" else ln)
            if m:
                bad.append(f"{doc}:{i}: a control, invisible or bidi character U+{ord(m[0]):04X}")
            for ch in ln:
                if ord(ch) > 127 and ch not in ok:
                    bad.append(f"{doc}:{i}: U+{ord(ch):04X} is outside the allowed characters")
                    break
    return one("G-CHARSET", bad)


def g_cells(t: Texts) -> list[Finding]:
    bad = []
    for doc, text in docs(t):
        for tab in tables(text):
            width = len(tab[0])
            for row in tab:
                if len(row) != width:
                    bad.append(f"{doc}: a row of the {tab[0][0]!r} table has {len(row)} cells")
                elif any(not c for c in row):
                    bad.append(f"{doc}: a row of the {tab[0][0]!r} table has an empty cell")
    return one("G-CELLS", bad)


CLOSING = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b:?\s+(?:[\w.-]+/[\w.-]+)?#\d+", re.IGNORECASE
)


def g_close(t: Texts) -> list[Finding]:
    bad = [
        f"{doc}:{i}: a closing keyword: {m[0]!r} (a PR body carries it, never a file)"
        for doc, text in (*docs(t), ("comp", t.comp))
        for i, ln in enumerate(text.split("\n"), 1)
        for m in CLOSING.finditer(without_code(ln))
    ]
    return one("G-CLOSE", bad)


QUOTE_MIN = 12
# the ruling's own strings (comment 6505239981), quoted where no merged text holds them yet
RULED_QUOTES = frozenset(
    {
        "caps lock is on.",
        "qr code for your authenticator app. the setup key is shown below.",
        "emits no telemetry; the composition map records its screen-level event",
        "no extra byte",
    }
)


def g_quote(t: Texts) -> list[Finding]:
    bad = []
    body = corpus(t.env)
    for doc, text in docs(t):
        for i, ln in enumerate(text.split("\n"), 1):
            line = ln
            if ln.startswith("| A-"):
                cells = split_row(ln)
                line = cells[5] if len(cells) >= 6 else ln
            for m in QUOTED.finditer(without_code(strip_comments(line))):
                q = norm(m[1] if m[1] is not None else m[2]).lower()
                if len(q) < QUOTE_MIN or q in RULED_QUOTES:
                    continue
                parts = [p.strip() for p in re.split(r"…|\.\.\.", q) if p.strip()]
                if not all(p in body for p in parts):
                    bad.append(f"{doc}:{i}: the quote {q[:50]!r} stands in no merged text")
    return one("G-QUOTE", bad)


A2N = "RULED (orchestrator, 2026-10-29, #2701 ledger addendum A row A2{n})"
CAPS = "Caps Lock is on."
QR_NAME = "QR code for your authenticator app. The setup key is shown below."
CONFIRMED = ("BQ-1", "BQ-2", "BQ-3", "BQ-8", "BQ-10", "BQ-15", "BQ-20", "BQ-24", "BQ-28",
             "BQ-30", "BQ-33")  # fmt: skip
REQUIRED: tuple[tuple[str, str], ...] = (
    ("spec", "`Refs #190`"),
    ("spec", "`Partial: PR 1 of 3`"),
    ("spec", "All 38 defaults are RULED as proposed"),
    ("spec", "Scope `auth-rbac` on all three PRs"),
    ("spec", "`large-pr-approved` is pre-authorised for PR 1"),
    ("spec", f"`{PR1_TITLE}`"),
    ("spec", f"comment {RULING_ID}, on the BQ list {BQ_LIST_ID}"),
    ("spec", f'the caps-lock string "{CAPS}" — {A2N.format(n=0)}'),
    ("spec", f'the QR\'s accessible name "{QR_NAME}" — {A2N.format(n=1)}'),
    ("spec", f"CMP-098 a modal on the CMP-043 auth chassis — {A2N.format(n=2)}"),
    ("A-17", f'"{CAPS}" on the focused field only, {A2N.format(n=0)}'),
    ("A-40", f'named "{QR_NAME}" ({A2N.format(n=1)})'),
    ("A-8", f"(inherits CMP-043; {A2N.format(n=2)})"),
    ("spec", "**Nothing in the band is published.**"),
    ("A-34", "exposed as **one** input whose name contains its visible heading"),
)


def g_ruled(t: Texts) -> list[Finding]:
    bad = []
    for where, s in REQUIRED:
        text = t.spec if where == "spec" else new_of(t.spec, where)
        if s not in text:
            bad.append(f"{where}: the ruled text {s[:60]!r} is missing")
    for b in CONFIRMED:
        if f"- **{b} (confirmed).**" not in sec(t.spec, ruled_key(t.spec)):
            bad.append(f"{b} is not carried as confirmed")
    for doc, text in (*docs(t), ("comp", t.comp)):
        if re.search(r"owner approval pending", text, re.IGNORECASE):
            bad.append(f"{doc}: 'owner approval pending' remains (the ruling left none)")
    return one("G-RULED", bad)


def ruled_key(spec: str) -> str:
    return next((k for k in sections(spec) if k.startswith("The thirty-eight questions")), "")


# the ledger (BQ-8 as ruled): row -> (disposition, the A-rows that carry it)
LEDGER: dict[str, tuple[str, tuple[str, ...]]] = {
    "L-1": ("applied", ("A-18",)),
    "L-2": ("applied", ("A-23",)),
    "L-3": ("applied", ("A-28",)),
    "L-4": ("applied", ("A-29",)),
    "L-5": ("applied", ("A-26",)),
    "L-6": ("applied", ("A-22",)),
    "L-7": ("applied", ("A-19",)),
    "L-8": ("applied", ("A-24",)),
    "L-9": ("applied", ("A-30",)),
    "L-10": ("applied", ("A-17",)),
    "L-11": ("applied-as-amended", ("A-8",)),  # the motion clause in the A11y line (lens 1, M-2)
    "L-12": ("routed", ()),
    "L-13": ("routed", ()),
    "L-14": ("closed-by-#4086", ()),
    "L-15": ("applied-as-amended", ("A-48",)),
    "L-16": ("routed", ()),
    "L-17": ("applied", ("A-41", "A-43")),
    "L-18": ("applied", ("A-34",)),
    "L-19": ("applied", ("A-6",)),
    "L-20": ("applied", ("A-40",)),
    "L-21": ("applied", ("A-34",)),
    "L-22": ("applied", ("A-34",)),
    "L-23": ("applied", ("A-34", "A-38")),
    "L-24": ("applied", ("A-32", "A-38")),
    "L-25": ("applied", ("A-18",)),
    "L-26": ("applied", ("A-13", "A-14")),
    "L-27": ("applied", ("A-13",)),
}
LEDGER.update({f"L-{n}": ("routed", ()) for n in range(28, 37)})
# parent rows applied byte for byte: our A-row -> the parent's (doc, A id)
BYTE_FOR_BYTE = {
    "A-18": ("D05H", "A-9"),
    "A-23": ("D05H", "A-10"),
    "A-28": ("D05H", "A-11"),
    "A-29": ("D05H", "A-15"),
    "A-26": ("D05H", "A-16"),
}
THEN_ROW = ("A-22", "D05H", "A-17")  # "the same line, then: X" = Old + " " + X
# parent rows applied in part or as amended: our A-row -> words of the parent's New it carries
CARRIES = {
    "A-34": ("whose name contains its visible heading",),  # E09-D10 A-3
    "A-6": ("before the admin token's end, each with its frame",),  # E09-D10 A-4
    "A-48": ("`version: string`",),  # E09-D12 A-7
    "A-8": ("`motion.duration.normal`", "instant under reduce"),  # E09-D08 A-5, in the A11y line
}
STORY_ADDS = {"A-19": "CMP-201", "A-24": "CMP-202", "A-30": "CMP-203"}  # D05H §H


def parent_rows(env: Env, key: str) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for tab in tables(env.base(PATHS[key])):
        for r in tab[1:]:
            if r and re.fullmatch(r"A-\d+", r[0]):
                rows.setdefault(r[0], r)
    return rows


def g_ledger(t: Texts) -> list[Finding]:
    bad: list[str] = []
    rows = ledger_rows(t.spec)
    ids = [r[0] for r in rows]
    if ids != list(LEDGER):
        bad.append(f"the ledger's rows are {len(ids)}, not L-1 ... L-{len(LEDGER)} in order")
    have = {r[0] for r in c_rows(t.spec)}
    for r in rows:
        if len(r) != 5 or r[0] not in LEDGER:
            continue
        want, carriers = LEDGER[r[0]]
        if disposition(r[3]) != want:
            bad.append(f"{r[0]}: disposition {r[3][:30]!r}, ruled {want!r}")
        here = tuple(x.strip() for x in r[4].split(",")) if r[4] != "—" else ()
        if here != carriers or any(a not in have for a in here):
            bad.append(f"{r[0]}: carried by {r[4]!r}, ruled {', '.join(carriers) or '—'}")
    d05h = parent_rows(t.env, "D05H")
    for aid, (key, pid) in BYTE_FOR_BYTE.items():
        p = d05h.get(pid)
        if not p or unescape(p[4]) != new_of(t.spec, aid):
            bad.append(f"{aid}: New is not {key} {pid}'s New, byte for byte")
    aid, key, pid = THEN_ROW
    p = d05h.get(pid)
    then = re.match(r"the same line, then: (.*)$", unescape(p[4])) if p else None
    old = unescape((a_row(t.spec, aid) or ["", "", "", "", ""])[4])
    if not then or new_of(t.spec, aid) != f"{old} {then[1]}":
        bad.append(f"{aid}: New is not {key} {pid}'s 'the same line, then:' form")
    for aid, words in CARRIES.items():
        for w in words:
            if w not in new_of(t.spec, aid):
                bad.append(f"{aid}: the parent row's words {w!r} are not carried")
    d05h_tabs = [tab for tab in tables(t.env.base(PATHS["D05H"])) if tab[0][0] == "Component"]
    for aid, cid in STORY_ADDS.items():
        row = next((r for tab in d05h_tabs for r in tab if r[0].startswith(cid)), None)
        adds = re.findall(r"\+ (.*)$", row[1])[0].split(" · ") if row else []
        if not adds or not all(a in parse_stories(new_of(t.spec, aid)) for a in adds):
            bad.append(f"{aid}: D05H §H's stories for {cid} are not all carried")
    return one("G-LEDGER", bad)


def g_arow(t: Texts) -> list[Finding]:
    bad: list[str] = []
    base = lines_of(t.env.base(CAT_REL))
    for i, r in enumerate(c_rows(t.spec), 1):
        if len(r) != 7:
            bad.append(f"§C row {i} has {len(r)} cells, not 7")
            continue
        aid, _, fld, op, old, new, src = r
        if aid != f"A-{i}":
            bad.append(f"§C row {i} is {aid}: the ids run A-1 ... A-n in order")
        m = FIELD.fullmatch(fld)
        if not m or op not in OPS:
            bad.append(f"{aid}: field {fld!r} or op {op!r} does not parse")
            continue
        n = int(m[1])
        old_u, new_u = unescape(old), unescape(new)
        if not new_u.strip() or new_u == old_u or PLACEHOLDER.search(without_code(new_u)):
            bad.append(f"{aid}: New is empty, unchanged or unfilled")
        if CITE.search(new_u):
            bad.append(f"{aid}: New carries a line cite (it would rot in `15`)")
        if op != "replace" and applied_by(src):
            # an insert applied by another PR: its bullets stand right after its anchor line
            parts = new_u.split(BR)
            if old != "—" or base[n : n + len(parts)] != parts:
                bad.append(f"{aid}: New does not follow `15`:{n} at the base (applied)")
        elif op == "replace" and applied_by(src):
            # Old is left unchecked on purpose: the row was applied by another PR,
            # so its Old no longer stands at the base; its New must stand there.
            if n > len(base) or new_u != base[n - 1]:
                bad.append(f"{aid}: New is not `15`:{n} at the base, byte for byte (applied)")
        elif op == "replace":
            if n > len(base) or old_u != base[n - 1]:
                bad.append(f"{aid}: Old is not `15`:{n} at the base, byte for byte")
            elif new_u[:4] != old_u[:4]:
                bad.append(f"{aid}: New does not keep its line's form")
        else:
            if old != "—":
                bad.append(f"{aid}: an insert row's Old is `—`")
            parts = new_u.split(BR)
            if not all(p.startswith("- **") for p in parts) or (
                op == "insert bullet after" and len(parts) != 1
            ):
                bad.append(f"{aid}: an inserted bullet does not start with `- **`")
    return one("G-AROW", bad)


TOKEN_NAME = re.compile(
    r"`((?:color|space|radius|elevation|type|font|size|border|opacity|motion)\.[\w.-]+)`"
)
UNSHIPPED = ("font.mono", "color.surface.base", "color.text.muted", "color.status.success")
CARRIED_PRIMITIVES = {"A-23": frozenset({"radius.sm"})}  # D05H A-10, applied byte for byte


def token_lines(spec: str) -> list[tuple[str, str]]:
    """(A id, text) of every New Tokens bullet, its "(Replaces …)" note cut."""
    out: list[tuple[str, str]] = []
    for r in c_rows(spec):
        if len(r) < 6:
            continue
        for part in unescape(r[5]).split(BR):
            if part.startswith("- **Tokens**"):
                out.append((r[0], re.sub(r"\(Replaces [^()]*\)", "", part)))
    return out


def g_token(t: Texts) -> list[Finding]:
    bad: list[str] = []
    prims = primitive_names(t.env) - semantic_names(t.env)
    every = [set(theme(t.env, x)) for x in THEMES]
    for aid, text in token_lines(t.spec):
        for m in TOKEN_NAME.finditer(text):
            name = m[1]
            if name in UNSHIPPED or not all(name in s for s in every):
                bad.append(f"{aid}: `{name}` is not a shipped token in every theme")
            elif name in prims and name not in CARRIED_PRIMITIVES.get(aid, frozenset()):
                bad.append(f"{aid}: `{name}` is a primitive (bind the semantic name)")
    for pid, fg, bg, _ in PAIRS:
        for name in (fg, bg):
            if not all(name in s for s in every):
                bad.append(f"{pid}: `{name}` is not shipped in every theme")
    return one("G-TOKEN", bad)


def g_pairs(t: Texts) -> list[Finding]:
    bad: list[str] = []
    rows = table_after(sec(t.spec, "6"), "P")
    if [r[0] for r in rows] != [p[0] for p in PAIRS]:
        bad.append("the pair table's rows are not P-1 ... P-n as the tool lists them")
    for r, (pid, fg, bg, kind) in zip(rows, PAIRS, strict=False):
        if len(r) != 10:
            continue
        if (r[2], r[3], r[4]) != (f"`{fg}`", f"`{bg}`", kind):
            bad.append(f"{pid}: the pair's tokens or kind differ from the tool's")
        k = pid.lower().replace("-", "")
        if r[8] != f"{t.values.get(f'PAIR:{k}', '?')}<!--=PAIR:{k}-->":
            bad.append(f"{pid}: the reading cell is not the tool's anchored value alone")
        meets = t.values.get(f"PAIR:{k}") == "`meets`"
        if meets != (r[9] == "—"):
            bad.append(f"{pid}: a pair below its bar needs a route; one that meets it has none")
    cvd = table_after(sec(t.spec, "6"), "CR")
    if [r[0] for r in cvd] != [c[0] for c in CVD_PAIRS]:
        bad.append("the CVD table's rows are not the tool's")
    for r, (cid, a, b) in zip(cvd, CVD_PAIRS, strict=False):
        if f"`{a}` · `{b}`" not in r[1]:
            bad.append(f"{cid}: the pair differs from the tool's")
    return one("G-PAIRS", bad)


def g_cvd_src(t: Texts) -> list[Finding]:
    return one("G-CVD-SRC", cvd_src_problems(t.env))


# BQ-26 as ruled: the union, per component
RULED_STORIES: dict[str, tuple[str, ...]] = {
    "CMP-200": ("Default", "WithError", "Busy", "WithFooter"),
    "CMP-201": ("Default", "Revealed", "CapsLockOn", "WithError", "CurrentPassword",
                "NewPassword", "PerFieldReveal"),
    "CMP-202": ("Weak", "Fair", "Strong", "WithFeedback", "CappedWeak"),
    "CMP-203": ("NoneMet", "PartiallyMet", "AllMet", "CheckedWhenYouSubmit", "ServerNotMet"),
    "CMP-204": ("Empty", "PartiallyFilled", "Complete", "Error", "Disabled", "Pasted"),
    "CMP-205": ("Default", "LargeSize"),
    "CMP-206": ("Default", "Acknowledged"),
    "CMP-207": ("PreAuthVersionOnly", "SignedInDemo", "SignedInLive", "LongVersionLabel"),
    "CMP-097": ("Default", "PartiallyComplete", "RoleDisabledWithReason", "BlockedUntil", "Error"),
    "CMP-098": ("Default", "ExtendInProgress", "WithLockNow", "AdminToken"),
}  # fmt: skip
BAND = tuple(RULED_STORIES)


def g_stories(t: Texts) -> list[Finding]:
    bad = [
        f"{cid}: the stories {stories(t.env, t.spec, cid)} differ from BQ-26's"
        for cid, want in RULED_STORIES.items()
        if tuple(stories(t.env, t.spec, cid)) != want
    ]
    return one("G-STORIES", bad)


STATUS_PUB = "published at PR 3"
STATUS_LOCAL = "local with a dated plan"
STATUS_HELD = "held"
COMP_FIELDS = ("id", "screen", "auth", "state", "element", "component", "variant", "purpose",
               "source", "event", "status")  # fmt: skip
# registered audit names (E09-D12 §10.2; `auth.password_change` from E09-D05 hand-off A-5)
EVENTS = frozenset(
    {
        "auth.login", "auth.login_failed", "auth.mfa_verified", "auth.mfa_failed",
        "auth.mfa_enroll", "auth.mfa_enrolled", "auth.recovery_codes_regenerated",
        "auth.step_up_granted", "auth.idle_locked", "auth.session_unlocked",
        "auth.password_change", "users.invite_redeemed", "—",
    }
)  # fmt: skip
# declared in `22` and not yet registered: the record says so, in these words (lens 3, M-1)
DECLARED_EVENTS = {
    "auth.session_locked": "declared in `22` (authLock) by #4941; registered when #4743 ships "
    "the route",
}
SOURCE = re.compile(rf"^(?:{CITE_KEY}):\d+(?:–\d+)?$|^D\d\d §[\d.]+(?: \(\d+\))?$")
KEY_EXCEPTION = "**Recorded exception**"  # the §8 line that records a shared key (BQ-28)


def key_problems(t: Texts) -> list[str]:
    """BQ-28 asks one record per (screen · state · element) key. A key several records share must
    be recorded in §8's exception line, which names those records and no others."""
    keys: dict[tuple[str, str, str], list[str]] = {}
    for r in comp_records(t.comp):
        key = (str(r.get("screen")), str(r.get("state")), str(r.get("element")))
        keys.setdefault(key, []).append(str(r.get("id")))
    shared = {k: ids for k, ids in keys.items() if len(ids) > 1}
    note = next((ln for ln in sec(t.spec, "8").split("\n") if ln.startswith(KEY_EXCEPTION)), "")
    want = {i for ids in shared.values() for i in ids}
    named = set(re.findall(r"\bR-\d+\b", note))
    if named != want or not all(" · ".join(k) in note for k in shared):
        return [
            f"the records {sorted(want)} share a key and §8's exception line names {sorted(named)}"
        ]
    return []


def comp_problems(t: Texts) -> list[str]:
    bad: list[str] = []
    d = comp_doc(t.comp)
    if not d:
        return ["the composition map is not a JSON object"]
    dup = comp_dups(t.comp)
    if dup:
        bad.append(f"the map is ambiguous: {dup}")
    if d.get("statuses") != [STATUS_PUB, STATUS_LOCAL, STATUS_HELD]:
        bad.append("the map's statuses are not the ruled three")
    if "registered" in str(d.get("events")) and "not yet registered" not in str(d.get("events")):
        bad.append("the map's events line calls every name registered")
    for i, r in enumerate(comp_records(t.comp), 1):
        rid = str(r.get("id"))
        if rid != f"R-{i}" or any(not r.get(f) for f in COMP_FIELDS):
            bad.append(f"record {i}: id or a required field missing")
            continue
        cid = str(r["component"])
        if cid not in BAND:
            bad.append(f"{rid}: {cid} is not a band component")
            continue
        if any(v not in RULED_STORIES[cid] for v in str(r["variant"]).split(", ")):
            bad.append(f"{rid}: variant {r['variant']!r} is not a story of {cid}")
        if r["status"] not in (STATUS_PUB, STATUS_LOCAL, STATUS_HELD):
            bad.append(f"{rid}: status {r['status']!r} is not a ruled status")
        if r["status"] != STATUS_PUB and not str(r.get("plan", "")).startswith("holder "):
            bad.append(f"{rid}: a local or held record names no holder")
        if r["event"] in DECLARED_EVENTS:
            if r.get("event_status") != DECLARED_EVENTS[str(r["event"])]:
                bad.append(f"{rid}: {r['event']} is declared, not registered; say so")
        elif r["event"] not in EVENTS:
            bad.append(f"{rid}: event {r['event']!r} is not a registered name")
        elif "event_status" in r:
            bad.append(f"{rid}: a registered event carries an event_status")
        if not SOURCE.match(str(r["source"])):
            bad.append(f"{rid}: source {r['source']!r} is not a cite")
    bad += key_problems(t)
    rows = table_after(sec(t.spec, "8"), "Screen")
    if [[unescape(c) for c in r] for r in rows] != render_comp(t.comp):
        bad.append("§8's table is not the map rendered (re-render it from the JSON)")
    return bad


def g_comp(t: Texts) -> list[Finding]:
    return one("G-COMP", comp_problems(t))


BUSY_STATES = ("submitting", "verifying", "extending")


def g_consist(t: Texts) -> list[Finding]:
    bad: list[str] = []
    recs = comp_records(t.comp)

    def attrs(r: dict[str, object]) -> dict[str, object]:
        a = r.get("attrs", {})
        return a if isinstance(a, dict) else {}

    codes = [r for r in recs if r.get("component") == "CMP-204"]
    if {str(r.get("screen")) for r in codes} < {"SCR-002", "SCR-003", "SCR-006", "SCR-149"}:
        bad.append("CMP-204 does not cover SCR-002, 003, 006 and 149")
    for r in codes:
        if attrs(r).get("variant_set") != "one control":
            bad.append(f"{r.get('id')}: CMP-204 outside the one variant set")
        if attrs(r).get("autocomplete", "one-time-code") != "one-time-code":
            bad.append(f"{r.get('id')}: CMP-204's autocomplete is not one-time-code")
    for r in recs:
        a = attrs(r)
        if r.get("component") == "CMP-201":
            want = "new-password" if "new password" in str(r.get("element")) else "current-password"
            if a.get("autocomplete") != want:
                bad.append(f"{r.get('id')}: CMP-201's autocomplete is not {want}")
        if r.get("component") == "CMP-200" and r.get("auth") != "pre":
            bad.append(f"{r.get('id')}: CMP-200 on a signed-in host")
        if r.get("state") in BUSY_STATES and a.get("busy") != "aria-disabled":
            bad.append(f"{r.get('id')}: a busy record without `aria-disabled`")
        if r.get("component") == "CMP-207":
            pre = "PreAuthVersionOnly" in str(r.get("variant"))
            if (r.get("auth") == "pre") != (r.get("variant") == "PreAuthVersionOnly") and not (
                r.get("auth") == "either" and pre
            ):
                bad.append(f"{r.get('id')}: CMP-207's variant does not follow sign-in")
        if "t2" in a and r.get("component") != "CMP-097":
            bad.append(f"{r.get('id')}: T2 outside CMP-097")
    return one("G-CONSIST", bad)


def g_idband(t: Texts) -> list[Finding]:
    bad: list[str] = []
    for doc, text in (*docs(t), ("comp", t.comp)):
        for m in re.finditer(r"\bCMP-(\d{3})\b", text):
            if int(m[1]) > 253:
                bad.append(f"{doc}: CMP-{m[1]} is outside the catalogue's ids (no new id)")
    for r in c_rows(t.spec):
        if len(r) >= 6 and ("### CMP-" in r[5] or "CMP-247" in r[5]):
            bad.append(f"{r[0]}: a New cell adds an entry or an id")
        if len(r) >= 3 and r[2] in ("`15`:31", "`15`:3199", "`15`:3200"):
            bad.append(f"{r[0]}: the band row or the tally changes (it stays 247)")
    return one("G-IDBAND", bad)


AGENT_WORDS = re.compile(
    r"\b(?:agent|worker|lane|claude|session)\b|\b[a-z]{2,5}-(?:worker|lane)-\d+\b", re.IGNORECASE
)
ORCH_LANE = f"the orchestrator (ruling {RULING_ID})"


def g_log(t: Texts) -> list[Finding]:
    bad: list[str] = []
    rows = table_after(sec(t.spec, "11"), "Ids")
    seen: set[str] = set()
    for r in rows:
        if len(r) != 6:
            continue
        for x in (y.strip() for y in r[0].split(",")):
            if x in seen:
                bad.append(f"{x} appears twice in the log")
            seen.add(x)
        closed = r[2].startswith("closed here")
        lane = r[3]
        if not closed and (lane in ("—", "") or AGENT_WORDS.search(lane)):
            bad.append(f"{r[0]}: owner lane {lane!r} (a ticket or an owner, never an agent)")
        if "orchestrator" in lane and lane != ORCH_LANE:
            bad.append(f"{r[0]}: the orchestrator's lane is only the ruled plan gap")
        due_ok = r[5] == "at once" or re.fullmatch(r"\d{4}-\d\d-\d\d<!--=DATE:[^>]+-->", r[5])
        if not closed and not due_ok:
            bad.append(f"{r[0]}: due {r[5]!r} is neither 'at once' nor a computed date")
    return one("G-LOG", bad)


def g_crows(t: Texts) -> list[Finding]:
    rows = table_after(sec(t.spec, "10"), "C")
    bad = [f"C-row {i} is {r[0]}" for i, r in enumerate(rows, 1) if r[0] != f"C-{i}"]
    bad += [f"{r[0]}: {len(r)} cells" for r in rows if len(r) != 4]
    return one("G-CROWS", bad)


WALK_DATE = "2026-10-29"
WALK_ROLES = (
    "story: #2711 (SCR-002)",
    "story: #2110 frontend leg",
    'story: #4743 ("Lock now")',
    "story: #1022 (SCR-149)",
    "story: #1136 (CMP-097)",
    "frontend: typeability",
    "QA: E09-D11 (#291)",
)
WALK_ITEM = re.compile(r"^(W-\d+) (.+?) → (\S+(?: \S+)?)$")


def g_walk(t: Texts) -> list[Finding]:
    bad: list[str] = []
    rows = walk_rows(t.spec)
    if tuple(r[1] for r in rows) != WALK_ROLES:
        bad.append("the dry run's roles are not the ruled ones, in order")
    k = 0
    rest = t.spec.replace(sec(t.spec, "12"), "")
    if "\nNo session took place and none is claimed. " not in sec(t.spec, "12"):
        bad.append("§12 does not open with 'No session took place and none is claimed.'")
    for r in rows:
        if len(r) != 6:
            continue
        if r[0] != WALK_DATE or not all(x.isdigit() for x in r[2:5]):
            bad.append(f"{r[1]}: the date or a count does not parse")
            continue
        needs, found, nf = int(r[2]), int(r[3]), int(r[4])
        if needs != found + nf:
            bad.append(f"{r[1]}: needs {needs} != found {found} + not found {nf}")
        items = [] if r[5] == "—" else [x.strip() for x in r[5].split(" · ")]
        if len(items) != nf:
            bad.append(f"{r[1]}: {nf} not found, {len(items)} dispositions")
        for it in items:
            m = WALK_ITEM.match(it)
            k += 1
            if not m or m[1] != f"W-{k}":
                bad.append(f"{r[1]}: {it[:30]!r} is not W-{k} … → an id")
                continue
            if m[3] not in rest:
                bad.append(f"{m[1]}: {m[3]!r} names no row of the pack")
    return one("G-WALK", bad)


CHECK_LABELS = (
    "Final Penpot link", "Variants × States matrix", "Keyboard table",
    "Accessible name / role table", "Live data", "Motion pair", "Density notes",
    "Essential-exceptions log", "Tokens used", "Data contract confirmed", "Contrast and CVD",
    "Design QA checklist (16 §12)", "Sign-off",
)  # fmt: skip
HAND_TABLES = ("Table 1 — Variants × States", "Table 2 — Keyboard",
               "Table 3 — Accessible name / role", "Table 4 — Motion pair",
               "Table 5 — Live data", "Density", "Essential exceptions")  # fmt: skip
HAND_ORDER = ("CMP-200", "CMP-201", "CMP-202", "CMP-203", "CMP-204", "CMP-205", "CMP-206",
              "CMP-207", "CMP-097", "CMP-098")  # fmt: skip


# the security-bearing hand-off tables, fixed in the tool (lens 2, attacks 28 and 29): table 2
# (keyboard) and table 3 (name / role) of CMP-201, 204, 205, 206, 207 and 098, row by row
HAND_FIXED: dict[tuple[str, int], tuple[tuple[str, ...], ...]] = {
    ("CMP-201", 2): (
        ("Tab", "the field, then its reveal", "the reveal button", "none", "one reveal per field"),
        (
            "Enter / Space (reveal)",
            "toggles the field's reveal",
            "stays on the reveal",
            "none",
            '`aria-pressed` flips; the name stays "Show password"',
        ),
        (
            "Ctrl+V / paste",
            "pastes; never suppressed",
            "stays in the field",
            "none",
            "a security control",
        ),
    ),
    ("CMP-201", 3): (
        (
            '`<input type="password">`',
            "textbox",
            "the field's visible label (CMP-040)",
            "`autocomplete` per host; `aria-invalid` with `error`",
        ),
        ("reveal", "button", '"Show password" (constant)', "`aria-pressed`"),
        (
            "caps-lock warning",
            "status (polite)",
            '"Caps Lock is on." (A20)',
            "on the focused field only",
        ),
    ),
    ("CMP-204", 2): (
        ("Tab", "enters the one input", "the input", "none", "one Tab stop, never six"),
        ("digits", "fill the next cell", "stays in the input", "none", "no per-digit focus move"),
        (
            "Ctrl+V / paste",
            "fills the whole code; one submit",
            "stays in the input",
            "none",
            "a security control",
        ),
        (
            "← / → / Backspace",
            "move and delete within the one input",
            "stays in the input",
            "none",
            "no announcement per digit",
        ),
    ),
    ("CMP-204", 3): (
        (
            "`<input>`",
            "textbox",
            "`aria-labelledby` = the consumer's visible heading (`labelledBy`)",
            (
                '`inputmode="numeric"`, `autocomplete="one-time-code"`; `aria-describedby` = '
                "`describedBy`; `readOnly` + `aria-disabled` while verifying"
            ),
        ),
        ("cells", "presentation", "—", "drawn, never focusable"),
    ),
    ("CMP-205", 2): (("—", "not focusable", "—", "—", "the component has no Tab stop"),),
    ("CMP-205", 3): (
        (
            "QR image",
            "img",
            '"QR code for your authenticator app. The setup key is shown below." (A21)',
            "no secret, issuer, account or URI in a name, title or `alt`",
        ),
        (
            "manual secret (host)",
            "CMP-020 text + CMP-033 button",
            "the button's own label",
            "the copy announcement never contains the value",
        ),
    ),
    ("CMP-206", 2): (
        (
            "Tab",
            "each action button, then the acknowledgement, in reading order",
            "the next control",
            "none",
            "real buttons",
        ),
        (
            "Space",
            "toggles the acknowledgement",
            "stays on the checkbox",
            "none",
            "Continue is gated on it",
        ),
    ),
    ("CMP-206", 3): (
        ("codes", "list (ordered)", "—", "monospace; read in order"),
        ("Copy all / Download .txt / Print", "button", "the visible label", "—"),
        ("acknowledgement", "checkbox (CMP-005)", "its visible label", "states why it is required"),
    ),
    ("CMP-207", 2): (("—", "not focusable", "—", "—", "the component has no Tab stop"),),
    ("CMP-207", 3): (
        ("`<footer>`", "contentinfo", "—", "plain text"),
        ("commit", "text (selectable)", "—", "signed in only"),
    ),
    ("CMP-098", 2): (
        (
            "Tab / Shift+Tab",
            'cycles "Stay signed in" and "Lock now" inside the dialog',
            "the other action",
            "none",
            "focus trapped (CMP-043)",
        ),
        (
            "Enter / Space",
            "activates the focused action",
            'busy on "Stay signed in"; the lock card after "Lock now"',
            "none",
            "explicit server calls",
        ),
        (
            "Esc",
            "dismisses; extends nothing",
            "back to the page",
            "Esc untouched (05 §3.3)",
            "never an extend",
        ),
    ),
    ("CMP-098", 3): (
        ("dialog", "alertdialog", "its visible heading", "`aria-modal`; announced once on arrival"),
        ("countdown", "text", "—", '`aria-live="off"`'),
        (
            "Stay signed in",
            "button",
            "the visible label",
            "`aria-disabled`, focusable while `extending`",
        ),
        ("Lock now", "button", "the visible label", "rendered only with `authLock` wired"),
    ),
}
PR3_ONLY = ("Design QA checklist (16 §12)", "Sign-off")
# PR 3: a ticked Final Penpot link names the band page by name + id and a board PNG in the tree
BAND_PAGE = "page `E09-D07 auth band` (`e4de416d-a820-8072-8008-e06d290d694c`)"
BOARD_PNG = re.compile(r"\]\(img/(E09-D07-\d\d-[a-z0-9-]+\.png)\)")


def ledger_table(spec: str) -> list[list[str]]:
    """The hand-off's ledger table: per component, the L-rows its A-rows carry; then the rest."""
    target = {r[0]: r[1] for r in c_rows(spec) if len(r) >= 2}
    by: dict[str, tuple[set[str], set[str]]] = {}
    rest: list[str] = []
    for r in ledger_rows(spec):
        if len(r) != 5:
            continue
        aids = [x.strip() for x in r[4].split(",")] if r[4] != "—" else []
        if not aids:
            rest.append(r[0])
        for a in aids:
            ls, as_ = by.setdefault(target.get(a, "?"), (set(), set()))
            ls.add(r[0])
            as_.add(a)

    def num(x: str) -> int:
        return int(x.split("-")[1])

    rows = [
        [cid, ", ".join(sorted(by[cid][0], key=num)), ", ".join(sorted(by[cid][1], key=num))]
        for cid in HAND_ORDER
        if cid in by
    ]
    rows.append(["routed or closed (no A-row)", ", ".join(rest), "—"])
    return rows


def g_handoff(t: Texts) -> list[Finding]:
    bad: list[str] = []
    if table_after(t.hand, "Component") != ledger_table(t.spec):
        bad.append("the hand-off's ledger table is not the pack's §2 by component")
    parts = re.split(r"^## Handoff checklist — ", t.hand, flags=re.MULTILINE)[1:]
    if [p[:7] for p in parts] != list(HAND_ORDER):
        bad.append("the hand-off does not carry the ten checklists in order")
    for p in parts:
        cid = p[:7]
        checks = re.findall(r"^- \[([x ])\] \*\*(.+?)\*\* (.*)$", p, flags=re.MULTILINE)
        labels = tuple(c[1] for c in checks)
        if labels != CHECK_LABELS:
            bad.append(f"{cid}: the checklist lines differ from `16` §11.4's")
        for mark, label, rest in checks:
            if not re.match(r"(?:and the \*\*.+?\*\* )?— \S", rest):
                bad.append(f"{cid}: '{label}' has no evidence or reason")
            if label in PR3_ONLY and mark != " ":
                bad.append(f"{cid}: '{label}' is ticked; it lands with PR 3 (or after)")
            if label == "Final Penpot link" and mark == "x":
                pngs = BOARD_PNG.findall(rest)
                if BAND_PAGE not in rest or not pngs:
                    bad.append(f"{cid}: the ticked Final Penpot link names no band page or board")
                for png in pngs:
                    if not (ROOT / "docs/design/E09/img" / png).is_file():
                        bad.append(f"{cid}: the Final Penpot link's {png} is not in the tree")
        for n in (2, 3):
            if (cid, n) in HAND_FIXED:
                blk = re.search(rf"^### Table {n} — .*?(?=^### |\Z)", p, re.MULTILINE | re.DOTALL)
                rows = tables(blk[0])[0][1:] if blk and tables(blk[0]) else []
                if tuple(tuple(r) for r in rows) != HAND_FIXED[(cid, n)]:
                    bad.append(f"{cid}: table {n} differs from the ruled rows")
        for r in table_after(p, "Mode"):
            keys = re.findall(r"`size\.control\.height` \(\d+<!--=TOKEN:([\w.]+)-->", r[1])
            if keys != [f"size.control.{r[0]}"]:
                bad.append(f"{cid}: the {r[0]} height is not `size.control.{r[0]}`")
        heads = tuple(re.findall(r"^### (.+)$", p, flags=re.MULTILINE))
        if heads != HAND_TABLES:
            bad.append(f"{cid}: the tables differ from `16` §11.4's seven")
        t1 = table_after(p, "Variant")
        names = {x.strip() for r in t1 for x in r[3].split(",") if len(r) > 3}
        want = set(RULED_STORIES.get(cid, ()))
        if not want <= {re.sub(r" \(.*$", "", n) for n in names}:
            bad.append(f"{cid}: table 1 misses a ruled story")
    return one("G-HANDOFF", bad)


# S-22 / S-23: patterns only, never the literals they refuse
CITE_LIKE = re.compile(r"\b([A-Z][A-Z0-9]+) ?:\s*\d")
DECLARED = frozenset(k for k in PATHS if not k.isdigit()) | {"CONST", "AC", "WCAG"}
SERVER_PATH = re.compile(r"\bservices/[\w./-]*\w")
CODE_LINE = re.compile(r"\b(?:apps|services|packages)/[\w./-]+\.\w+:\d+")
EDGE_WORDS = re.compile(
    r"until (?:it|the server|the edge|the build) aligns|once the (?:server|edge|build) is "
    r"(?:aligned|fixed|corrected)|the shipped (?:code|build|server|edge) (?:answers|returns|still)"
    r"|today the (?:server|build|edge) (?:answers|returns)",
    re.IGNORECASE,
)


def edge_hit(text: str) -> str | None:
    for m in CITE_LIKE.finditer(text):
        if m[1] not in DECLARED:
            return m[0]
    for rx in (SERVER_PATH, CODE_LINE, EDGE_WORDS):
        w = rx.search(text)
        if w:
            return w[0]
    return None


def g_edge(t: Texts) -> list[Finding]:
    bad: list[str] = []
    for doc, text in (*docs(t), ("comp", t.comp)):
        for i, ln in enumerate(text.split("\n"), 1):
            hit = edge_hit(strip_comments(ln))
            if hit:
                bad.append(f"{doc}:{i}: a private-detail shape ({hit})")
    return one("G-EDGE", bad)


PENPOT = re.compile(
    r"\bhttps?://|\bwww\.[a-z]|penpot\.app|team-id|file-id|workspace\?|/home/|file://",
    re.IGNORECASE,
)


def g_penpot(t: Texts) -> list[Finding]:
    bad = [
        f"{doc}:{i}: a URL, host, Penpot id or local path"
        for doc, text in (*docs(t), ("comp", t.comp))
        for i, ln in enumerate(text.split("\n"), 1)
        if PENPOT.search(ln)
    ]
    return one("G-PENPOT", bad)


SECRETISH = re.compile(
    r'"([^"\n]*(?:key|token|secret|pass)[^"\n]*)"\s*:\s*"([^"\n]{12,})"', re.IGNORECASE
)


def entropy(s: str) -> float:
    return -sum(s.count(c) / len(s) * math.log2(s.count(c) / len(s)) for c in set(s))


def g_entropy(t: Texts) -> list[Finding]:
    bad = [
        f"{doc}: a high-entropy {m[1]!r} value"
        for doc, text in (*docs(t), ("comp", t.comp), ("tool", t.tool))
        for m in SECRETISH.finditer(text)
        if entropy(m[2]) >= 3.5
    ]
    return one("G-ENTROPY", bad)


def mutation_paragraph() -> str:
    by_gate: dict[str, list[str]] = {}
    for i, m in enumerate(MUTATIONS, 1):
        by_gate.setdefault(m.gate, []).append(f"M-{i} {m.what}")
    return " ".join(f"**{g}:** {'; '.join(xs)}." for g, xs in by_gate.items())


def g_mutlist(t: Texts) -> list[Finding]:
    s13 = sec(t.spec, "13")
    ok = mutation_paragraph() in s13.split("\n")
    return one("G-MUTLIST", [] if ok else ["§13 is not the tool's mutation list (run --fill)"])


# ---------------------------------------------------------------------------- the entry lines

# `15` §0.1 (`15`:18) at the base, plus the four optional fields A-1 declares (BQ-22/23/32 rider)
BASE_FIELDS = ("Tier", "Purpose", "Props", "Variants", "States", "A11y", "Tokens", "Storybook",
               "Tests", "API sketch", "Data contract")  # fmt: skip
NEW_FIELDS = ("Forbidden", "Security", "Performance", "Observability")
ENTRY_ROWS = {"CMP-097": "A-5", "CMP-098": "A-10", "CMP-200": "A-16", "CMP-201": "A-20",
              "CMP-202": "A-25", "CMP-203": "A-31", "CMP-204": "A-38", "CMP-205": "A-43",
              "CMP-206": "A-46", "CMP-207": "A-51"}  # fmt: skip
SECURITY_SET = ("CMP-200", "CMP-201", "CMP-204", "CMP-205", "CMP-206", "CMP-207")  # BQ-23
PERF_LINE = (
    "- **Performance**: no engine, no heavy animation library, no webfont beyond the core set."
)
PERF_205 = (
    "- **Performance**: QR generation ≤ 100 ms on the client, which bounds the frontend's "
    "library choice; no engine, no heavy animation library, no webfont beyond the core set."
)
OBS_LINE = (
    "- **Observability**: emits no telemetry; the composition map "
    "(`docs/design/E09/E09-D07-composition.json`) records its screen-level event."
)
CARVE_OUT = re.compile(
    r"\b(?:allowed|permitted|except|unless|only when|other than|as long as|provided)\b",
    re.IGNORECASE,
)


def g_entry(t: Texts) -> list[Finding]:
    """The entry lines as ruled (BQ-22, BQ-23, BQ-32): only declared fields; one Forbidden list
    per entry with no carve-out; BQ-32's Performance line; the one Observability line."""
    bad: list[str] = []
    a1 = new_of(t.spec, "A-1")
    tail = a1.split("the optional fields ", 1)[1].split(";")[0] if "optional fields " in a1 else ""
    if tuple(re.findall(r"\*\*(\w+)\*\*", tail)) != NEW_FIELDS:
        bad.append("A-1 does not declare the four optional fields, and only them")
    for r in c_rows(t.spec):
        if len(r) < 6 or r[0] == "A-1":
            continue
        for part in unescape(r[5]).split(BR):
            m = re.match(r"- \*\*([^*]+)\*\*", part)
            if m and m[1] not in BASE_FIELDS + NEW_FIELDS:
                bad.append(f"{r[0]}: the field **{m[1]}** is declared neither in §0.1 nor by A-1")
    for cid, aid in ENTRY_ROWS.items():
        parts = new_of(t.spec, aid).split(BR)
        got = {f: [p for p in parts if p.startswith(f"- **{f}**")] for f in NEW_FIELDS}
        for f in ("Forbidden", "Performance", "Observability"):
            if len(got[f]) != 1:
                bad.append(f"{aid}: {cid} carries {len(got[f])} {f} lines, not one")
        if (len(got["Security"]) == 1) != (cid in SECURITY_SET):
            bad.append(f"{aid}: {cid}'s Security line does not follow BQ-23")
        perf = PERF_205 if cid == "CMP-205" else PERF_LINE
        if got["Performance"] and got["Performance"][0] != perf:
            bad.append(f"{aid}: the Performance line is not BQ-32's")
        if got["Observability"] and got["Observability"][0] != OBS_LINE:
            bad.append(f"{aid}: the Observability line is not BQ-32's")
        for fb in got["Forbidden"]:
            body = re.sub(r"\([^()]*\)", "", fb)
            if not fb.endswith(".") or ". " in body or CARVE_OUT.search(fb):
                bad.append(f"{aid}: the Forbidden line is not one list (a claim or a carve-out)")
    return one("G-ENTRY", bad)


# §4 / §9: an operation a design-ahead consumer still builds is never "served" (lens 3, M-2)
SERVED = re.compile(r"\b(?:served|live|shipped) (?:since|as of|from) #\d+|\bserved by #(\d+)")
AHEAD_LOCK = "(`authLock`, `22`:1831, declared by #4941, to be served by #4743)"


def g_ahead(t: Texts) -> list[Finding]:
    bad: list[str] = []
    ahead = {m[1] for r in table_after(sec(t.spec, "9"), "Consumer")
             for m in [re.search(r"#(\d+)", r[0])] if m}  # fmt: skip
    for doc, text in (*docs(t), ("comp", t.comp)):
        for i, ln in enumerate(text.split("\n"), 1):
            for m in SERVED.finditer(ln):
                if m[1] is None or m[1] not in ahead:
                    bad.append(f"{doc}:{i}: {m[0]!r} claims a served operation")
    if AHEAD_LOCK not in sec(t.spec, "4"):
        bad.append("§4 does not read 'declared by #4941, to be served by #4743' for authLock")
    return one("G-AHEAD", bad)


# §14: a ticked box never names a later act (lens 1, m-2)
LATER = re.compile(r"\bat PR \d's merge\b|: PR \d\b|\bPR \d, on\b")


def g_dod(t: Texts) -> list[Finding]:
    bad: list[str] = []
    for ln in sec(t.spec, "14").split("\n"):
        for item in re.split(r"(?=\[[x ]\] )", ln):
            if item.startswith("[x] ") and LATER.search(item):
                bad.append(f"§14: a ticked box names a later act: {item[4:44]!r}")
    return one("G-DOD", bad)


# ---------------------------------------------------------------------------- the lexicon gates

# One gate per ruled behaviour: (gate, the A-rows it reads, the hand-off section, FORBIDDEN
# synonym patterns read as live claims, REQUIRED words per A-row). A **Forbidden** line lists its
# states on purpose and is not read; a negation in the mention's own clause removes a mention.
LEXICON: tuple[
    tuple[str, tuple[str, ...], str, tuple[str, ...], dict[str, tuple[str, ...]]], ...
] = (
    (
        "G-OTP",
        ("A-32", "A-33", "A-34", "A-35", "A-36", "A-37", "A-38"),
        "CMP-204",
        (
            r"six (?:separate |unlabelled |focusable )?(?:inputs|boxes|fields)",
            r"role=[\"']?group",
            r"per-digit (?:focus|announce)",
            r"\b(?:bullets?|dots|asterisks)\b",
            r"\b(?:cells?|digits?|boxes) (?:takes?|gets?|receives?|holds?) (?:the )?focus",
            r"\bfocus (?:moves|jumps|walks|advances|steps) (?:to|between|across|through)\b",
            r"\btabbable\b",
            r"\btab (?:advances|moves|steps)\b",
            r"\bmask(?:ed|s)?\b",
            r"six-digit authentication code",
            r"\bfocus (?:moves|jumps) (?:to|between) (?:the next )?cells?\b",
        ),
        {"A-34": ("one <input", "aria-labelledby"), "A-33": ("labelledby: string",)},
    ),
    (
        "G-PASTE",
        ("A-17", "A-18", "A-19", "A-20", "A-33", "A-34", "A-38"),
        "CMP-201",
        (
            r"(?:suppress|block|disabl|prevent)\w* (?:the )?paste",
            r"paste (?:is |are )?(?:suppressed|blocked|disabled|prevented)",
            r"autocomplete=\"?off",
            r"managers? (?:are |is )?(?:turned away|refused|rejected|blocked|disabled|suppressed)",
            r"(?:refus|reject|turn\w* away|block|disabl|suppress)\w* (?:the |password )+manager",
            r"autofill (?:is |are )?(?:switched off|turned off|off|disabled|suppressed|blocked)",
            r"(?:switch|turn)\w* off (?:the )?autofill",
            r"pasted (?:text|code|value)s? (?:is |are )?(?:discarded|dropped|ignored|cleared)",
        ),
        {"A-18": ("never suppresses paste",), "A-38": ("are never removed",)},
    ),
    (
        "G-QUIET",
        ("A-39", "A-40", "A-41", "A-42", "A-43"),
        "CMP-205",
        (
            r"\b(?:themed|tinted|theme-tinted|theme) (?:quiet zone|bitmap)",
            r"quiet zone (?:takes|uses) ",
            r"\b(?:in|for) (?:the )?(?:dark|light|high contrast)(?: theme)? only\b",
            r"\bonly in (?:the )?(?:dark|light|high contrast)\b",
            r"\b(?:takes?|uses?|adopts?) (?:the )?(?:surface|theme|accent|background)",
            (
                r"(?:description|name|title|alt|label)\b[^.;]*\b(?:spells?|reads?|states?|contains?"
                r"|includes?|carr(?:y|ies)) (?:out )?(?:the )?"
                r"(?:setup key|secret|uri|issuer|account)"
            ),
            r"(?:written|saved|stored|persisted|kept) (?:to|in) (?:the )?(?:session|local|browser)",
        ),
        {
            "A-41": ("untinted",),
            "A-40": ("no secret, issuer, account or uri",),
            "A-43": ("value never enters a route, query string or browser storage (tm u22)",),
        },
    ),
    (
        "G-LOCK",
        ("A-6", "A-7", "A-8", "A-9", "A-10"),
        "CMP-098",
        (
            r'"extend"',
            r"\(g-2\)",
            r"lock-on-request",
            r"esc (?:\w+ )?extends? the",
            r"keeps? (?:the )?session (?:alive|open|active)",
            r"\bkeystrokes?\b",
            r"\bkey ?press(?:es)?\b",
            r"\bany (?:key|input|activity)\b",
            r'focus (?:to|on|lands on|moves to|goes to) "?lock now',
        ),
        {
            "A-6": ('"stay signed in"',),
            "A-8": (
                '"lock now" calls authlock',
                "esc dismisses and extends nothing",
                'focus to "stay signed in"',
                "a fixed threshold (60 s remaining)",
            ),
            "A-7": ("onlocknow?",),
        },
    ),
    (
        "G-FOOTER",
        ("A-47", "A-48", "A-49", "A-50", "A-51"),
        "CMP-207",
        (
            r"node(?:-| )name",
            r"\bnode\b",
            r"\bhost ?(?:name|label)s?\b",
            r"\bserver'?s? (?:host|machine|name)\b",
            r"\bcommit\b[^.;]*\bbefore (?:and after )?sign-in",
        ),
        {
            "A-48": ("commit, builtat and environment only after sign-in",),
            "A-51": ("before sign-in the version label only",),
        },
    ),
    (
        "G-CODES",
        ("A-44", "A-45", "A-46"),
        "CMP-206",
        (
            r"\b(?:remaining|consumed) (?:count|codes?|number)\b(?![^.;]*\bheld\b)",
            r"\bcache[ds]?\b",
            r"\breload\w*",
            r"\brestor\w* from\b",
            r"\bmfaenrollresponse\b",
            r"(?:written|saved|stored|persisted|kept) (?:to|in) (?:the )?(?:session|local|browser)",
        ),
        {
            "A-46": (
                "never from storage",
                "excludes the subtree",
                "codes never enter a route param or browser storage (tm u23, sr-054)",
            ),
            "hand": ("the 10 codes of mfaenrollconfirmresponse",),
        },
    ),
    (
        "G-T2",
        tuple(f"A-{n}" for n in range(6, 52)),
        "",
        (r"\bt2\b",),
        {"A-5": ("e09-d09 §2.2 t2",)},
    ),
    (
        "G-BUSY",
        tuple(f"A-{n}" for n in range(1, 52)),
        "",
        (
            r"native disabled attribute",
            r"\bdisabled\b(?= while (?:busy|verifying))",
            r"(?:leaves?|left|removed from|out of|taken out of) (?:the )?tab order",
            r"skipped (?:by|in|on) tab",
            r"\bgreyed[- ]out\b",
        ),
        {"A-13": ("never the native disabled attribute",)},
    ),
)


# any mention FAILs, negated or not ("never unmasked" means masked): lens 2, m-5
ALWAYS: dict[str, tuple[str, ...]] = {"G-OTP": (r"\bunmask\w*",)}


# the arms §4's contract bullets are read for (their reconciliation quotes need no other)
PROSE: dict[str, tuple[str, ...]] = {
    "G-OTP": (r"\b(?:bullets?|asterisks)\b", r"\btabbable\b", r"\bunmask\w*"),
    "G-PASTE": (r"autofill (?:is |are )?(?:switched off|turned off|disabled)", r"turned away"),
    "G-QUIET": (r"\bin dark only\b", r"\b(?:takes?|uses?) (?:the )?(?:surface|theme|accent)"),
    "G-LOCK": (
        r"keeps? (?:the )?session (?:alive|open|active)",
        r"\bkeystrokes?\b",
        r"\bkey ?press(?:es)?\b",
        r'focus (?:to|on|lands on|moves to|goes to) "?lock now',
    ),
    "G-FOOTER": (r"\bhost ?(?:name|label)s?\b",),
    "G-CODES": (r"\bcache[ds]?\b", r"\breload\w*"),
}


def readable(cell: str) -> str:
    """A New cell as the lexicon reads it: its **Forbidden** part and "(Replaces …)" cut."""
    keep = [p for p in cell.split(BR) if not p.startswith("- **Forbidden**")]
    return re.sub(r"\(Replaces [^()]*\)", "", BR.join(keep))


def hand_section(hand: str, cid: str) -> str:
    if not cid:
        return ""
    m = re.search(rf"^## Handoff checklist — {cid} .*?(?=^## |\Z)", hand, re.MULTILINE | re.DOTALL)
    return m[0] if m else ""


def unquote(text: str, env: Env) -> str:
    """Drop a quote whose words stand in a merged text (an attributed quote is not a claim)."""
    body = corpus(env)

    def cut(m: re.Match[str]) -> str:
        q = norm(m[1] if m[1] is not None else m[2]).lower()
        return " " if len(q) >= QUOTE_MIN and q in body else m[0]

    return QUOTED.sub(cut, text)


def lexicon_gate(t: Texts, gate: str) -> list[Finding]:
    spec_rows = next(x for x in LEXICON if x[0] == gate)
    _, aids, cid, forbidden, required = spec_rows
    bad: list[str] = []
    texts = [(aid, readable(new_of(t.spec, aid))) for aid in aids]
    hand = hand_section(t.hand, cid)
    if hand:
        texts.append((f"hand {cid}", hand))
    for where, text in texts:
        p = plain(unquote(text, t.env))
        for rx in forbidden:
            if gate == "G-T2":
                if re.search(rx, p) and where not in ("A-2", "A-3", "A-4", "A-5"):
                    bad.append(f"{where}: T2 outside CMP-097's steps")
                continue
            for clause in re.split(r"(?<=[.;])\s|·", p):
                if live_plain(clause, rx):
                    bad.append(f"{where}: a live claim matching {rx[:30]!r}")
                    break
        for rx in ALWAYS.get(gate, ()):
            if re.search(rx, plain(text)):
                bad.append(f"{where}: {rx[:30]!r} stands (negated or not)")
    mutlist = set(sec(t.spec, "13").split("\n"))  # §13 names the planted violations
    for i, ln in enumerate(t.spec.split("\n"), 1) if gate in PROSE else []:
        if not ln.strip() or ln.startswith(("|", "#")) or ln in mutlist:
            continue
        # the pack's prose (the ruling's precisions, §0 ... §14): it also quotes the merged texts
        # it reconciles and lists forbidden states, so only the arms no summary needs are read
        kept = [s for s in FULL_STOP.split(ln) if not s.lstrip("-* ").startswith("Forbidden")]
        p = plain(unquote(" ".join(kept), t.env))
        hit = next((rx for rx in PROSE[gate] for c in re.split(r"(?<=[.;])\s|·", p)
                    if live_plain(c, rx)), None)  # fmt: skip
        if hit:
            bad.append(f"spec:{i}: a live claim matching {hit[:30]!r}")
    for aid, words in required.items():
        p = plain(hand if aid == "hand" else new_of(t.spec, aid))
        for w in words:
            if w not in p:
                bad.append(f"{aid}: the ruled words {w!r} are missing")
    return one(gate, bad)


def make_lexicon(gate: str) -> Callable[[Texts], list[Finding]]:
    def run(t: Texts) -> list[Finding]:
        return lexicon_gate(t, gate)

    run.__name__ = gate
    return run


# ---------------------------------------------------------------------------- the pins gate


def g_pins(t: Texts) -> list[Finding]:
    if t.pins is None:
        return one("G-RULED-PIN", [f"{PINS_REL} is missing (run --repin-ruled)"])
    probs = pin_problems(parse_pins(t.pins), all_units(t.spec, t.hand, t.comp))
    return [Finding("FAIL", "G-RULED-PIN", p) for p in probs]


GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_anchor, g_marker, g_figure, g_wordcount, g_cite, g_version, g_untouched, g_charset,
    g_cells, g_close, g_quote, g_ruled, g_ledger, g_arow, g_token, g_pairs, g_cvd_src,
    g_stories, g_comp, g_consist, g_idband, g_log, g_crows, g_walk, g_handoff, g_edge,
    g_penpot, g_entropy, g_mutlist, g_entry, g_ahead, g_dod,
    *(make_lexicon(x[0]) for x in LEXICON),
)  # fmt: skip


def audit(t: Texts) -> list[Finding]:
    found: list[Finding] = []
    for g in GATES:
        found += g(t)
    pins = g_pins(t)
    if any(f.level == "FAIL" for f in found):  # beside another FAIL a pin finding is a NOTE
        pins = [replace(f, level="NOTE") for f in pins]
    return found + pins


# ---------------------------------------------------------------------------- mutations


@dataclass(frozen=True)
class Mutation:
    gate: str
    what: str
    apply: Callable[[Texts], Texts]
    level: str = "FAIL"  # a WARN mutation adds exactly one WARN and no FAIL


def set_doc(t: Texts, doc: str, text: str) -> Texts:
    if doc == "hand":
        return replace(t, hand=text)
    if doc == "comp":
        return replace(t, comp=text)
    return replace(t, spec=text)


def flex(old: str) -> re.Pattern[str]:
    """`old` with each whitespace run matching any run (Prettier re-pads table rows)."""
    return re.compile(r"\s+".join(re.escape(p) for p in old.split(" ") if p != ""))


def subst(old: str, new: str, doc: str = "spec") -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        text = getattr(t, doc)
        m = flex(old).search(text) if old.strip() else None
        if not m:
            raise SystemExit(f"self-test: a mutation's target is gone: {old[:60]!r}")
        return set_doc(t, doc, text[: m.start()] + new + text[m.end() :])

    return f


def in_row(aid: str, old: str, new: str) -> Callable[[Texts], Texts]:
    """Edit one §C row's New cell (column 6) only."""

    def f(t: Texts) -> Texts:
        out = []
        done = False
        for ln in t.spec.split("\n"):
            if ln.startswith("| A-") and split_row(ln)[0] == aid and not done:
                cells = split_row(ln)
                if old not in cells[5]:
                    raise SystemExit(f"self-test: {aid}'s New lacks {old[:50]!r}")
                cells[5] = cells[5].replace(old, new, 1)
                ln = "| " + " | ".join(cells) + " |"
                done = True
            out.append(ln)
        if not done:
            raise SystemExit(f"self-test: no §C row {aid}")
        return replace(t, spec="\n".join(out))

    return f


def in_source(aid: str, suffix: str, drop: bool = False) -> Callable[[Texts], Texts]:
    """Append `suffix` to one §C row's source cell (column 7) only, or (`drop`) cut it off."""

    def f(t: Texts) -> Texts:
        out = []
        done = False
        for ln in t.spec.split("\n"):
            if ln.startswith("| A-") and split_row(ln)[0] == aid and not done:
                cells = split_row(ln)
                if drop and not cells[6].endswith(suffix):
                    raise SystemExit(f"self-test: {aid}'s source cell lacks {suffix!r}")
                cells[6] = cells[6].removesuffix(suffix) if drop else cells[6] + suffix
                ln = "| " + " | ".join(cells) + " |"
                done = True
            out.append(ln)
        if not done:
            raise SystemExit(f"self-test: no §C row {aid}")
        return replace(t, spec="\n".join(out))

    return f


def copy_env(e: Env) -> Env:
    return Env(
        base_cache=dict(e.base_cache),
        head_cache=dict(e.head_cache),
        merge_base=e.merge_base,
        changed=e.changed,
        head_override=dict(e.head_override),
        head_ok=e.head_ok,
        last_override=dict(e.last_override),
        cur_override=dict(e.cur_override),
        memo=dict(e.memo),
    )


def with_env(tweak: Callable[[Env], None]) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        e = copy_env(t.env)
        tweak(e)
        return replace(t, env=e)

    return f


def base_edit(rel: str, n: int, old: str, new: str) -> Callable[[Env], None]:
    """`rel` at the base with `old` replaced by `new` on line `n` only."""

    def f(e: Env) -> None:
        lines = lines_of(e.base(rel))
        if old not in lines[n - 1]:
            raise SystemExit(f"self-test: {rel}:{n} lacks {old[:50]!r}")
        lines[n - 1] = lines[n - 1].replace(old, new, 1)
        e.base_cache[rel] = e.head_override[rel] = "\n".join(lines)

    return f


def carry_new(t: Texts, t0: Texts) -> Texts:
    """`t` with every applied §C row whose New differs from `t0`'s planted in `15` at the base
    too: the row stands applied, so a mutation of its New tests the gate it names, never the
    lockstep G-AROW keeps between §C and `15` (a G-AROW mutation is never carried)."""
    was = {r[0]: r for r in c_rows(t0.spec) if len(r) == 7}
    plan: list[tuple[int, int, list[str]]] = []
    for r in c_rows(t.spec):
        w = was.get(r[0])
        m = FIELD.fullmatch(r[2]) if len(r) == 7 else None
        if not w or not m or not applied_by(r[6]) or r[5] == w[5]:
            continue
        n, k = int(m[1]), len(unescape(w[5]).split(BR))
        parts = unescape(r[5]).split(BR) if r[3] != "replace" else [unescape(r[5])]
        if len(parts) != k:  # line for line: no later `15` line moves
            parts = [*parts[: k - 1], BR.join(parts[k - 1 :])] if len(parts) > k else parts + [""]
        plan.append((n - 1, 1, parts) if r[3] == "replace" else (n, k, parts))
    if not plan:
        return t
    e = copy_env(t.env)
    lines = lines_of(e.base(CAT_REL))
    for i, k, parts in sorted(plan, key=lambda p: -p[0]):
        lines[i : i + k] = parts
    e.base_cache[CAT_REL] = e.head_override[CAT_REL] = "\n".join(lines)
    return replace(t, env=e)


def head_edit(key: str, n: int) -> Callable[[Env], None]:
    def f(e: Env) -> None:
        lines = lines_of(e.base(PATHS[key]))
        lines[n - 1] = lines[n - 1] + " (edited)"
        e.head_override[PATHS[key]] = "\n".join(lines)

    return f


def late(rel: str) -> Callable[[Env], None]:
    def f(e: Env) -> None:
        e.last_override[f"{HEAD_REF}:{rel}"] = "0" * 40

    return f


def no_head(e: Env) -> None:
    e.head_ok = False


def no_mb(e: Env) -> None:
    e.merge_base = lambda: None


def touched(path: str) -> Callable[[Env], None]:
    def f(e: Env) -> None:
        e.merge_base = lambda: BASE
        e.changed = lambda _mb: sorted({*OWN_PATHS, path})

    return f


def cvd_drift(e: Env) -> None:
    src = e.base(CVD_SRC)
    e.base_cache[CVD_SRC] = src.replace("17.8824", "17.8825", 1)


def frozen_head() -> Env:
    """The self-test's environment: `origin/main` reads as the base for every input G-VERSION
    compares, so a late change at the live head never hides a mutation (`--check` is the live
    gate)."""
    e = Env(head_ok=True)
    for rel in {*PATHS.values(), ALL_TICKETS}:
        e.head_override[rel] = e.base(rel)
    for rel in DRIFT_INPUTS:
        e.last_override[f"{HEAD_REF}:{rel}"] = e.last_commit(BASE, rel)
    return e


def backlog_edit(change: Callable[[list[dict[str, object]]], None]) -> Callable[[Env], None]:
    """The head's backlog JSON: the base's tickets with `change` applied."""

    def f(e: Env) -> None:
        tickets = json.loads(e.base(ALL_TICKETS))
        change(tickets)
        e.head_override[ALL_TICKETS] = json.dumps(tickets, ensure_ascii=False)

    return f


def sprint_moves(tickets: list[dict[str, object]]) -> None:
    """Move E42-S07 (a ticket §9 dates) one sprint on."""
    for t in tickets:
        if t.get("key") == "E42-S07":
            t["sprint"] = f"Sprint {int(str(t['sprint']).split()[-1]) + 1:02d}"


def title_edit(tickets: list[dict[str, object]]) -> None:
    """Edit a title only: no sprint moves."""
    tickets[0]["title"] = str(tickets[0].get("title")) + " (edited)"


def calendar_days(e: Env) -> None:
    """The head's calendar with a longer sprint."""
    e.head_override[PATHS["CAL"]] = CAL_DAYS.sub(
        lambda m: f"SPRINT_DAYS = {int(m[1]) + 1}", e.base(PATHS["CAL"]), count=1
    )


def head_front(key: str) -> Callable[[Env], None]:
    """`key`'s file at the head with one line added at its top: every cited range moves down."""

    def f(e: Env) -> None:
        e.head_override[PATHS[key]] = "added line\n" + e.base(PATHS[key])

    return f


def pr2(extra: str) -> Callable[[Texts], Texts]:
    """PR 2's tree: only `15` changed, holding §C applied (plus `extra`)."""

    def f(t: Texts) -> Texts:
        e = copy_env(t.env)
        want, _ = apply_rows(e.base(CAT_REL), a_rows_export(t.spec, e.base(CAT_REL)), HELD)
        e.merge_base = lambda: BASE
        e.changed = lambda _mb: [CAT_REL]
        e.cur_override[CAT_REL] = want + extra
        return replace(t, env=e)

    return f


def comp_edit(rid: str, key: str, value: object) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        d = json.loads(t.comp)
        for r in d["records"]:
            if r["id"] == rid:
                if key.startswith("attrs."):
                    r.setdefault("attrs", {})[key[6:]] = value
                else:
                    r[key] = value
        return replace(t, comp=json.dumps(d, ensure_ascii=False, indent=2) + "\n")

    return f


def comp_note(note: dict[str, str]) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        d = json.loads(t.comp)
        d["notes"].append(note)
        return replace(t, comp=json.dumps(d, ensure_ascii=False, indent=2) + "\n")

    return f


def drop_line(doc: str, prefix: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        lines = getattr(t, doc).split("\n")
        i = next(i for i, ln in enumerate(lines) if ln.startswith(prefix))
        return set_doc(t, doc, "\n".join(lines[:i] + lines[i + 1 :]))

    return f


def status_fails(e: Env) -> None:
    e.merge_base = lambda: BASE
    e.changed = lambda _mb: None


def comp_raw(old: str, new: str) -> Callable[[Texts], Texts]:
    """Edit the map's text as is (a repeated key survives no json round trip)."""

    def f(t: Texts) -> Texts:
        if t.comp.count(old) != 1:
            raise SystemExit(f"self-test: the map lacks one {old[:50]!r}")
        return replace(t, comp=t.comp.replace(old, new, 1))

    return f


def comp_drop(rid: str, key: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        d = json.loads(t.comp)
        for r in d["records"]:
            if r["id"] == rid:
                del r[key]
        return replace(t, comp=json.dumps(d, ensure_ascii=False, indent=2) + "\n")

    return f


def mut_para(t: Texts) -> Texts:
    return replace(t, spec=t.spec.replace("**G-ANCHOR:** M-1 ", "**G-ANCHOR:** M-01 ", 1))


SECRET_SHAPE = "Zq" + "8vT" + "rL2" + "wXy" + "Pn5" + "kJ"  # assembled: no literal in the file
M = Mutation
MUTATIONS: tuple[Mutation, ...] = (
    M(
        "G-ANCHOR",
        "hand-edit the ledger count's value",
        subst("36<!--=COUNT:ledger-->", "35<!--=COUNT:ledger-->"),
    ),
    M(
        "G-ANCHOR",
        "leave a placeholder unfilled in §6",
        subst("**Contrast in three themes**", "**Contrast in three themes** {{COUNT:pairs}}"),
    ),
    M(
        "G-MARKER",
        "hide a note in an HTML comment in §0",
        subst("## 0. Status", "## 0. Status<!-- a -->"),
    ),
    M(
        "G-MARKER",
        "hide a sentence in a link-reference definition",
        subst("## 1. Locked inputs", "[//]: # (hidden)\n\n## 1. Locked inputs"),
    ),
    M(
        "G-FIGURE",
        "type a contrast ratio by hand in §6",
        subst("**CVD and greyscale**", "**CVD and greyscale** (4.32:1)"),
    ),
    M(
        "G-WORDCOUNT",
        "type the ledger count by hand",
        subst("36<!--=COUNT:ledger--> rows", "36 rows"),
    ),
    M(
        "G-WORDCOUNT",
        "write a count as a word",
        subst("**The owner walkthrough**", "Seven rows. **The owner walkthrough**"),
    ),
    M(
        "G-CITE",
        "move a D05 cite past the end of D05",
        subst("(D05:186), its string", "(D05:9186), its string"),
    ),
    M(
        "G-VERSION",
        "simulate an edit inside a cited D05 range at origin/main",
        with_env(head_edit("D05", 186)),
    ),
    M("G-VERSION", "simulate an unresolvable origin/main", with_env(no_head)),
    M(
        "G-VERSION",
        "simulate a late commit to the dark token JSON",
        with_env(late(f"{DS_SRC}/semantic-dark.tokens.json")),
    ),
    M(
        "G-VERSION",
        "pin D08 at a wrong sha in the version line",
        subst("D08 at `c99ad48d78`", "D08 at `c99ad48d79`"),
    ),
    M("G-UNTOUCHED", "simulate an edit to `14` in PR 1", with_env(touched(PATHS["14"]))),
    M("G-UNTOUCHED", "simulate an edit to a merged E09 doc", with_env(touched(PATHS["D05"]))),
    M("G-UNTOUCHED", "simulate an unresolvable merge-base", with_env(no_mb)),
    M("G-UNTOUCHED", "simulate PR 2 with one byte more than §C", pr2("x")),
    M(
        "G-CHARSET",
        "plant a zero-width space in §3",
        subst("## 3. Candidates", "## 3. Candi\u200bdates"),
    ),
    M(
        "G-CELLS",
        "drop a cell from the acceptance-criteria trace",
        subst("| text done; published at PR 3 |", ""),
    ),
    M(
        "G-CLOSE",
        "write a closing keyword in §14",
        subst(
            "**Deviations, accepted as ruled.**", "Closes #190. **Deviations, accepted as ruled.**"
        ),
    ),
    M(
        "G-QUOTE",
        "quote copy no merged text holds in §4",
        subst(
            "hosts SCR-001, SCR-002, standalone",
            'hosts "Welcome back, trader", SCR-001, standalone',
        ),
    ),
    M(
        "G-RULED",
        "turn a stamp back into its pending form",
        subst(
            "— RULED (orchestrator, 2026-10-29, #2701 ledger addendum A row A21);", "— PROPOSED;"
        ),
    ),
    M(
        "G-RULED",
        "drop BQ-24's confirmation",
        subst("- **BQ-24 (confirmed).**", "- **BQ-24.**"),
    ),
    M(
        "G-LEDGER",
        "misspell L-5's disposition",
        subst("| CMP-203 Purpose (`15`:2640) | applied", "| CMP-203 Purpose (`15`:2640) | aplied"),
    ),
    M(
        "G-LEDGER",
        "change one word of D05H A-9's New in A-18",
        in_row("A-18", "the constant name", "the fixed name"),
    ),
    M(
        "G-AROW",
        "alter A-14's applied New in `15` at the base (the row no longer stands)",
        with_env(base_edit(CAT_REL, 2604, "**Tokens**", "**Token**")),
    ),
    M(
        "G-AROW",
        "give A-12 an op the tool does not know",
        subst("| `15`:2602 | replace |", "| `15`:2602 | swap |"),
    ),
    M(
        "G-TOKEN",
        "bind CMP-207's caption to a primitive",
        in_row("A-49", "`type.ui.caption`, ", "`font.size.xs`, "),
    ),
    M(
        "G-TOKEN",
        "bind an unshipped token in CMP-204",
        in_row("A-35", "digits `type.num.base`", "digits `color.text.muted`"),
    ),
    M("G-PAIRS", "drop P-3's route", subst("| G-3 (F-12) |", "| — |")),
    M(
        "G-CVD-SRC",
        "simulate a drifted RGB_TO_LMS constant in the research script",
        with_env(cvd_drift),
    ),
    M(
        "G-STORIES",
        "drop Pasted from CMP-204's stories",
        in_row("A-36", ", Pasted (every", " (every"),
    ),
    M(
        "G-COMP",
        "give a record a status the ruling does not know",
        comp_edit("R-6", "status", "maybe"),
    ),
    M(
        "G-COMP",
        "edit §8's rendered row for SCR-019",
        subst("| SCR-019 | in | CMP-097 PartiallyComplete,", "| SCR-019 | in | CMP-097 Default,"),
    ),
    M(
        "G-CONSIST",
        "move SCR-006's code control out of the one variant set",
        comp_edit("R-25", "attrs.variant_set", "cells"),
    ),
    M(
        "G-CONSIST",
        "give SCR-001's current password field `new-password`",
        comp_edit("R-4", "attrs.autocomplete", "new-password"),
    ),
    M(
        "G-IDBAND",
        "name a new id in §3",
        subst("| the lock card (SCR-005)", "| the lock card (SCR-005, CMP-254)"),
    ),
    M(
        "G-LOG",
        "give a log row an agent lane",
        subst(
            "| E05 (E05-D01's follow-up revision) | #2711 | at once |",
            "| a worker | #2711 | at once |",
        ),
    ),
    M("G-CROWS", "renumber C-5", subst("| C-5 |", "| C-55 |")),
    M(
        "G-WALK",
        "break #2711's needs = found + not found",
        subst("| story: #2711 (SCR-002) | 7 ", "| story: #2711 (SCR-002) | 8 "),
    ),
    M(
        "G-WALK",
        "point a not-found at a row the pack does not hold",
        subst("→ D12 G-2 ", "→ Q-99 "),
    ),
    M(
        "G-HANDOFF",
        "misname a checklist line of CMP-205's checklist",
        subst(
            "CMP-205 QrCode (E09-D07, #190)\n\n- [x] **Final Penpot link**",
            "CMP-205 QrCode (E09-D07, #190)\n\n- [x] **Final Penpot lnk**",
            doc="hand",
        ),
    ),
    M(
        "G-EDGE",
        "cite a server-tree path",
        subst("**Public repo**", "**Public repo** (`services/api/x.py`)"),
    ),
    M(
        "G-EDGE",
        "plant a fix-direction wording arm",
        subst("no line here states", "until the server aligns, no line here states"),
    ),
    M(
        "G-EDGE",
        "cite an undeclared key",
        subst("(D05:186), its string", "(D05:186; LOGIN:97), its string"),
    ),
    M(
        "G-PENPOT",
        "paste a Penpot workspace URL in §14",
        subst("**Deviations, accepted as ruled.**", "penpot.app/#/workspace **Deviations,"),
    ),
    M(
        "G-ENTROPY",
        "plant a high-entropy key-named value in the map",
        comp_note({"screen": "SCR-001", "api_key": SECRET_SHAPE + SECRET_SHAPE}),
    ),
    M("G-MUTLIST", "edit §13's mutation list", mut_para),
    M(
        "G-OTP",
        "make CMP-204 six boxes again",
        in_row("A-34", "not six unlabelled boxes", "as six unlabelled boxes"),
    ),
    M(
        "G-PASTE",
        "suppress paste in CMP-201's Security line",
        in_row("A-20", "paste and password managers are never suppressed", "paste is suppressed"),
    ),
    M(
        "G-QUIET",
        "theme CMP-205's quiet zone",
        in_row("A-41", "drawn untinted", "drawn on a themed quiet zone"),
    ),
    M(
        "G-LOCK",
        "let Esc extend the session",
        in_row("A-8", "Esc dismisses and extends nothing", "Esc extends the session"),
    ),
    M(
        "G-FOOTER",
        "show the node name on CMP-207",
        in_row("A-48", "`commit?: string`", "`commit?: string` · the node name"),
    ),
    M(
        "G-CODES",
        "show a remaining count on CMP-206",
        in_row("A-44", "`color.surface.sunken`.", "`color.surface.sunken`; the remaining count."),
    ),
    M(
        "G-T2",
        "draw a T2 reason on CMP-200's submit",
        in_row("A-15", "the busy submit stays focusable", "the busy submit is T2"),
    ),
    M(
        "G-BUSY",
        "put the native disabled attribute on CMP-200's busy submit",
        in_row("A-15", "the busy submit stays focusable", "the native `disabled` attribute"),
    ),
    M(
        "G-PAIRS",
        "garble P-3's reading cell around its anchored value",
        subst(
            "`below: high contrast`<!--=PAIR:p3-->",
            "below: `below: high contrast`<!--=PAIR:p3-->",
        ),
    ),
    M("G-UNTOUCHED", "simulate a failed `git status` (fail closed)", with_env(status_fails)),
    M(
        "G-CHARSET",
        "write A-8's 60 s with a superscript zero (NFKC reads 60)",
        in_row("A-8", "(60 s remaining)", "(6\u2070 s remaining)"),
    ),
    M(
        "G-CHARSET",
        "put a Cyrillic letter inside A-34's masked",
        in_row("A-34", "digits are never masked.", "digits are never m\u0430sked."),
    ),
    M(
        "G-CHARSET",
        "put a line separator for a space in §3",
        subst("A divergence is resolved", "A divergence\u2028is resolved"),
    ),
    M(
        "G-COMP",
        "repeat R-1's status key with another value",
        comp_raw('"id": "R-1",', '"id": "R-1",\n      "status": "published at PR 3",'),
    ),
    M(
        "G-COMP",
        "call auth.session_locked registered (drop R-23's event_status)",
        comp_drop("R-23", "event_status"),
    ),
    M(
        "G-CONSIST",
        "switch a CMP-204 record's autocomplete off",
        comp_edit("R-7", "attrs.autocomplete", "off"),
    ),
    M(
        "G-HANDOFF",
        "tick CMP-200's Sign-off in PR 1",
        subst(
            "- [ ] **Sign-off** — the orchestrator's design approval (BQ-34) on PR 1",
            "- [x] **Sign-off** — the orchestrator's design approval (BQ-34) on PR 1",
            doc="hand",
        ),
    ),
    M(
        "G-HANDOFF",
        "move focus to the next cell on a digit in CMP-204's keyboard table",
        subst(
            "| fill the next cell | stays in the input |",
            "| fill the next cell | the next cell |",
            doc="hand",
        ),
    ),
    M(
        "G-HANDOFF",
        "swap a density anchor key for one of equal value",
        subst(
            "(24<!--=TOKEN:size.control.compact--> px)",
            "(24<!--=TOKEN:size.target.min--> px)",
            doc="hand",
        ),
    ),
    M(
        "G-CITE",
        "re-point the owner-only cite to the next line",
        subst("(D09:75, :90)", "(D09:76, :90)"),
    ),
    M(
        "G-CITE",
        "re-point the caps-lock cite off its line (a wide range still spans it)",
        subst("(D05:186), its string", "(D05:187), its string"),
    ),
    M(
        "G-LOCK",
        "let Escape keep the session alive in BQ-20's precision",
        subst(
            "`22`:1828–1853); Esc dismisses and extends nothing;",
            "`22`:1828–1853); Esc dismisses and extends nothing; pressing Escape keeps the session "
            "alive;",
        ),
    ),
    M(
        "G-LOCK",
        "let Escape keep the session alive in §4's CMP-098 contract (prose is read)",
        subst(
            "(`authLock`, `22`:1831, declared by #4941, to be served by #4743); Esc dismisses and "
            "extends nothing;",
            "(`authLock`, `22`:1831, declared by #4941, to be served by #4743); Esc dismisses and "
            "extends nothing; pressing Escape keeps the session alive;",
        ),
    ),
    M(
        "G-OTP",
        "write 'never unmasked' in A-34",
        in_row("A-34", "digits are never masked.", "digits are never unmasked."),
    ),
    M(
        "G-OTP",
        "draw the digits as bullets in A-34",
        in_row("A-34", "digits are never masked.", "digits are shown as bullets."),
    ),
    M(
        "G-PASTE",
        "turn password managers away in A-20",
        in_row(
            "A-20",
            "paste and password managers are never suppressed",
            "paste is never suppressed but password managers are turned away",
        ),
    ),
    M(
        "G-QUIET",
        "tint the bitmap in dark only in A-41",
        in_row("A-41", "drawn untinted", "drawn untinted in dark only"),
    ),
    M(
        "G-QUIET",
        "drop A-43's route and storage clause",
        in_row(
            "A-43", "; `value` never enters a route, query string or browser storage (TM U22)", ""
        ),
    ),
    M(
        "G-LOCK",
        "let Escape keep the session alive in A-8",
        in_row(
            "A-8",
            "Esc dismisses and extends nothing;",
            "Esc dismisses and extends nothing; pressing Escape keeps the session alive;",
        ),
    ),
    M(
        "G-LOCK",
        "move the initial focus to Lock now in A-8",
        in_row("A-8", 'focus to "Stay signed in";', 'focus to "Lock now";'),
    ),
    M(
        "G-FOOTER",
        "add a hostLabel prop to CMP-207",
        in_row("A-48", "`commit?: string`", "`commit?: string` · `hostLabel?: string`"),
    ),
    M(
        "G-CODES",
        "reload the codes from a cache in A-46",
        in_row("A-46", "never from storage;", "never from storage; reloaded from the local cache;"),
    ),
    M(
        "G-CODES",
        "drop A-46's route and storage clause",
        in_row(
            "A-46", " `codes` never enter a route param or browser storage (TM U23, SR-054);", ""
        ),
    ),
    M(
        "G-CODES",
        "name the enrol response for the codes in the hand-off",
        subst(
            "the 10 codes of `MfaEnrollConfirmResponse`",
            "the 10 codes of `MfaEnrollResponse`",
            doc="hand",
        ),
    ),
    M(
        "G-BUSY",
        "take the busy submit out of the tab order in A-15",
        in_row("A-15", "the busy submit stays focusable", "the busy submit leaves the tab order"),
    ),
    M(
        "G-ENTRY",
        "give CMP-098 an undeclared Motion field again, in its Performance line's place",
        in_row("A-10", "- **Performance**: no engine", "- **Motion**: no engine"),
    ),
    M(
        "G-ENTRY",
        "claim the pre-auth route in CMP-097's Performance line",
        in_row(
            "A-5", "- **Performance**: no engine", "- **Performance**: usable pre-auth: no engine"
        ),
    ),
    M(
        "G-ENTRY",
        "carve an exception out of CMP-098's Forbidden list",
        in_row("A-10", "Esc extending;", "Esc extending (allowed under 10 s);"),
    ),
    M(
        "G-ENTRY",
        "add a claim after CMP-206's Forbidden list",
        in_row("A-46", "before the acknowledgement.", "before the acknowledgement. Shows a count."),
    ),
    M(
        "G-LEDGER",
        "drop D08 A-5's reduce clause from A-8",
        in_row("A-8", "instant under reduce; ", ""),
    ),
    M(
        "G-AHEAD",
        "call authLock served since its contract PR",
        subst("declared by #4941, to be served by #4743)", "served since #4941)"),
    ),
    M(
        "G-DOD",
        "tick the map-linked box before PR 3",
        subst("[ ] The map linked from #291 and #194", "[x] The map linked from #291 and #194"),
    ),
    M(
        "G-RULED",
        "reverse §0's status sentence",
        subst("**Nothing in the band is published.**", "**Everything in the band is published.**"),
    ),
    M(
        "G-RULED",
        "drop the emphasis on A-34's one input",
        in_row("A-34", "exposed as **one** input", "exposed as one input"),
    ),
    M(
        "G-WALK",
        "claim a session in §12",
        subst("No session took place and none is claimed.", "A session took place and is claimed."),
    ),
    M(
        "G-RULED-PIN",
        "reword a sentence of §8",
        subst(
            "A divergence is resolved in the pack or routed",
            "A divergence is settled in the pack or routed",
        ),
    ),
    M(
        "G-VERSION",
        "simulate a moved sprint of E42-S07 in the backlog JSON at origin/main",
        with_env(backlog_edit(sprint_moves)),
    ),
    M(
        "G-VERSION",
        "simulate a longer sprint in the calendar at origin/main",
        with_env(calendar_days),
    ),
    M(
        "G-VERSION",
        "edit a cited `15` line whose text repeats elsewhere, in place, at origin/main",
        with_env(head_edit("15", 1072)),
    ),
    M(
        "G-VERSION",
        "simulate every cited D05 range moved down at origin/main (a WARN, no FAIL)",
        with_env(head_front("D05")),
        "WARN",
    ),
    M(
        "G-COMP",
        "drop §8's recorded exception for a shared key",
        drop_line("spec", KEY_EXCEPTION),
    ),
    M(
        "G-COMP",
        "share the key of R-21 and R-23 with a third record",
        comp_edit("R-22", "state", "warning"),
    ),
    M(
        "G-AROW",
        "drop A-2's applied-by marker (its Old no longer stands at the base)",
        in_source("A-2", " · applied by #5058", drop=True),
    ),
    M(
        "G-AROW",
        "point A-5's field one line up (its applied bullets no longer follow it)",
        subst("| `15`:1072 | insert bullets after |", "| `15`:1071 | insert bullets after |"),
    ),
)


# ---------------------------------------------------------------------------- self-test and main


def read(rel: str) -> str:
    p = ROOT / rel
    return read_raw(p) if p.exists() else ""


def load(env: Env | None = None) -> Texts:
    env = env or Env()
    spec, hand, comp = read(SPEC_REL), read(HAND_REL), read(COMP_REL)
    pins_p = ROOT / PINS_REL
    pins = read_raw(pins_p) if pins_p.exists() else None
    return Texts(spec, hand, comp, pins, read(TOOL_REL), compute(env, spec, hand, comp), env)


def digest(t: Texts) -> list[str]:
    return [hashlib.sha256(x.encode()).hexdigest() for x in (t.spec, t.hand, t.comp, t.pins or "")]


def ascii_line(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = (
        s.replace("→", "->")
        .replace("›", ">")
        .replace("…", "...")
        .replace("—", "-")
        .replace("–", "-")
    )
    s = (
        s.replace("×", "x")
        .replace("§", "S")
        .replace("·", "|")
        .replace("≤", "<=")
        .replace("≥", ">=")
    )
    return s.encode("ascii", "replace").decode()[:100]


def render(found: list[Finding]) -> list[str]:
    return [ascii_line(f"{f.level} {f.gate}: {f.msg}") for f in found]


# negative controls: a tree that must add no FAIL (PR 2's exact catalogue; a later commit to the
# backlog JSON that moves no sprint)
NEGATIVES: tuple[tuple[str, Callable[[Texts], Texts]], ...] = (
    ("N-1 PR 2 with §C applied exactly", pr2("")),
    ("N-2 a backlog JSON commit that moves no sprint", with_env(backlog_edit(title_edit))),
)


def selftest() -> tuple[bool, list[str]]:
    base = load(frozen_head())
    disk = [hashlib.sha256(read(r).encode()).hexdigest() for r in OWN_PATHS]
    before = digest(base)
    base_found = [f for f in audit(base) if f.level == "FAIL"]
    out = [f"self-test: baseline {len(base_found)} FAIL"]
    ok = not base_found
    for f in base_found:
        out.append(ascii_line(f"  baseline {f.gate}: {f.msg}"))
    for i, m in enumerate(MUTATIONS, 1):
        planted = m.apply(base)
        found = audit(planted if m.gate == "G-AROW" else carry_new(planted, base))
        fails = [f for f in found if f.level == "FAIL"]
        hits = [f for f in found if f.level == m.level]
        gates = sorted({f.gate for f in hits})
        good = len(hits) == 1 and gates == [m.gate] and (m.level == "FAIL" or not fails)
        ok &= good
        mark = "ok  " if good else "FAIL"
        out.append(ascii_line(f"{mark} M-{i} {m.gate}: {m.what} -> {', '.join(gates) or 'none'}"))
    for name, scenario in NEGATIVES:
        extra = [f for f in audit(scenario(base)) if f.level == "FAIL"]
        ok &= not extra
        shown = ", ".join(sorted({f.gate for f in extra})) or "none"
        out.append(ascii_line(f"{'ok  ' if not extra else 'FAIL'} {name} -> {shown}"))
    restored = digest(base) == before and disk == [
        hashlib.sha256(read(r).encode()).hexdigest() for r in OWN_PATHS
    ]
    ok &= restored
    out.append(
        f"self-test: {len(MUTATIONS)} mutations, texts restored: {'yes' if restored else 'NO'}"
    )
    out.append(f"self-test: {'PASS' if ok else 'FAIL'}")
    return ok, out


def write_text(rel: str, text: str) -> None:
    with open(ROOT / rel, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def fill_mutlist(spec: str) -> str:
    """§13: the line after the mutation count is the tool's list."""
    lines = spec.split("\n")
    head = next(i for i, ln in enumerate(lines) if ln.startswith("## 13."))
    para = next(
        i for i in range(head + 1, len(lines)) if lines[i].startswith(("{{MUTLIST}}", "**G-"))
    )
    lines[para] = mutation_paragraph()
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else "")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--self-test", action="store_true")
    g.add_argument("--repin-ruled", action="store_true")
    g.add_argument("--a-rows", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fill", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        ok, lines = selftest()
        print("\n".join(lines))
        return 0 if ok else 1
    t = load()
    if a.a_rows:
        print(json.dumps(a_rows_export(t.spec, t.env.base(CAT_REL)), ensure_ascii=False, indent=2))
        return 0
    if a.repin_ruled:
        for doc, text in docs(t):
            if any(PLACEHOLDER.search(without_code(x)) for x in text.split("\n")):
                print(f"refused: {doc} has an unfilled placeholder (run --check --fill)")
                return 1
        other = [f for f in audit(t) if f.level == "FAIL" and f.gate != "G-RULED-PIN"]
        if other:
            print(f"refused: {len(other)} FAIL outside the pins (first: {other[0].gate}); fix them")
            return 1
        write_text(PINS_REL, write_pins(all_units(t.spec, t.hand, t.comp)))
        print(f"wrote {PINS_REL}")
        return 0
    if a.fill:
        spec, miss1 = fill(fill_mutlist(t.spec), t.values)
        hand, miss2 = fill(t.hand, t.values)
        write_text(SPEC_REL, spec)
        write_text(HAND_REL, hand)
        for m in miss1 + miss2:
            print(f"unfilled: {m}")
        t = load()
    found = audit(t)
    fails = [f for f in found if f.level == "FAIL"]
    if a.json:
        dump = {
            "base": BASE,
            "values": t.values,
            "findings": [{"level": f.level, "gate": f.gate, "msg": f.msg} for f in found],
        }
        print(json.dumps(dump, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for ln in render(found):
            print(ln)
        warns = [f for f in found if f.level == "WARN"]
        notes = len(found) - len(fails) - len(warns)
        print(f"{len(fails)} FAIL / {len(warns)} WARN / {notes} NOTE ({len(GATES) + 1} gates)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
