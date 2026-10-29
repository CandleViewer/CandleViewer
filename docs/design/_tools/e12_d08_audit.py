#!/usr/bin/env python3
"""E12-D08 (#243) audit: the rebuild, partial-history, empty and error states (SCR-047, SCR-048).

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I` from a full
checkout. It reads AS TEXT at the pinned base (`git show BASE:<path>`) the plan texts it cites
(`02`, `05`, `11`, `13`, `14`, `15`, `22`, `23`), the merged design docs (E12-D02 ... D09, E11-D02,
E11-D04, E11-D05, E16-D05, E08-D04, E09-D09), the research findings, ADR-0033, the shipped bars
route, the token JSON (layered as `themes.json` says), `calendar_cv.py`, `E12.json` and the two
design helpers `contrast_check.py` (its WCAG formula) and `cvd_sim.py` (its Machado matrices), and
`docs/research/_tools/cvd_simulate.py` (its Machado 2009 tritan matrix); then the spec
(`docs/design/E12/E12-D08.md`), its hand-off (`E12-D08-handoff.md`, RULED BQ-3) and the pins from
the working tree.

1. **Values.** Every `VALUE<!--=KIND:key-->` anchor is derived: CITE (a number parsed from the
   cited line at the base), RULED (the ruling's numbers), COUNT (the spec's own tables and the
   `22` code registry), LADDER (`14`'s 1, 2, 4, 8 ... capped formula), DATE (a sprint start from
   `calendar_cv.py` and `E12.json`), SHA (`git log -1` at the base), CONTRAST (WCAG 2.x, truncated
   to two decimals), DE and DY (CIE76 and Rec. 601 luma differences under the `cvd_sim.py`
   matrices, one decimal, truncated). `--fill` writes them; `--check` re-derives and FAILs on a
   difference (G-ANCHOR) and on a hand-typed unit figure or hex (G-FIGURE).
2. **Cites.** Every `NN`:line and DOC:line cite (with `, :n` continuations and `n-m` ranges) must
   land on a non-blank line at the base (G-CITE); a cited line that differs at `origin/main`
   FAILs (G-VERSION).
3. **Gates.** One semantic gate per ruled class (§14 of the spec): each reads tables and prose
   after the comment strip, NFKC and whitespace normalised. They are default-deny: besides the
   phrases a ruling requires, every sentence and table cell is read as a claim (`claims`), and a
   claim that contradicts a ruled class FAILs that class's gate (`contra`) unless it is negated,
   so a paraphrase cannot pass on the pins alone. Six classes deny on their subject (`deny`, no
   negation escapes it); the subject is still found by a lexicon, widened by form in round 5 (a
   hyphen, a singular, any `record` word, the 4xx alone, any Cancel claim in §7-§8, a period read
   as a rate) and by the round-5 review's escapes in round 6 (control synonyms, every role and
   capture, status names and rejection, the total by another name, Cancel in any form, the
   keyboard position by another name, track, mirror, rewrite, follow and keep pace) and in
   round 7 (every registered 4xx status name, "denied", "declined", a total after "without
   an"), so a subject the lexicon misses is not read: a claim naming a §10.4 control (G-T2), a role beside a
   record CTA or button (G-ROLE), a 4xx with a process word (G-LADDER), what an unknown-total build
   shows (G-PROGRESS), when Cancel appears, focus after it and `Esc` (G-CANCEL), or a counter
   update (G-CADENCE) passes only with an approved ruled marker. A hidden comment and raw HTML
   (a `hidden` or `display:none` element) FAIL G-MARKER. The hand-off is gated too (G-HANDOFF, G-AROWS and the
   mechanical gates).
4. **Pins (G-RULED-PIN).** A whole-document default-deny pin set: every heading, table row (by its
   lead cell), rule line and prose sentence, by region (the heading path plus occurrence) and
   location, NFKC and whitespace normalised, anchored values cut out. `--repin-ruled` is the only
   writer. When any other gate FAILs, the pin finding prints as a NOTE (the exit status stays 1).
5. **--self-test** applies, in memory with the values frozen at the baseline, one M-n mutation
   per gate, the X-n contradiction and paraphrase probes, one P-n probe per pin class (only the
   pins catch it) and N-n probes (legitimate rewordings that, re-pinned, must trip nothing). Each
   M, X and P must produce exactly one FAIL, from the gate it names; the text is restored and
   checked byte for byte (sha256).

Usage (from the repo root):
  python3 -I docs/design/_tools/e12_d08_audit.py --check [--json]
  python3 -I docs/design/_tools/e12_d08_audit.py --fill
  python3 -I docs/design/_tools/e12_d08_audit.py --self-test
  python3 -I docs/design/_tools/e12_d08_audit.py --repin-ruled
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
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = "772f1f07cad1f7818151ffedf9f77720eaba399e"  # #4905's merge: every cite was re-read here
HEAD_REF = "origin/main"  # a cited line that differs here FAILs (G-VERSION)
SPEC_REL = "docs/design/E12/E12-D08.md"
TOOL_REL = "docs/design/_tools/e12_d08_audit.py"
PINS_REL = "docs/design/_tools/e12_d08_ruled_pins.txt"
HANDOFF_REL = (
    "docs/design/E12/E12-D08-handoff.md"  # RULED BQ-3: the hand-off with the A-rows
)
OWN_PATHS = (SPEC_REL, HANDOFF_REL, TOOL_REL, PINS_REL)
DS = "packages/ui/tokens"
CAL_REL = "docs/plan/backlog/_tools/calendar_cv.py"
E12J_REL = "docs/plan/backlog/E12.json"
CVD_REL = "docs/design/_tools/cvd_sim.py"
CVDR_REL = (
    "docs/research/_tools/cvd_simulate.py"  # Machado 2009 tritan (E33-D05's source)
)
CONTRAST_REL = "docs/design/_tools/contrast_check.py"

RULING_ID = "6475004920"  # the ruling of record
BQ_LIST_ID = "6473367744"  # the question list the ruling accepts "as proposed"
ALLOWED_IDS = frozenset({RULING_ID, BQ_LIST_ID})
OWNER_PENDING = "PROPOSED — owner approval pending (#2701)"
SPEC_LINE_BUDGET = 600
MAX_WALK = 10
UNMERGED = (
    "#242",
    "#245",
    "#312",
    "#313",
    "#4787",
)  # named only, never pinned or quoted
LATE_MERGED = {
    "D09": "#4853",
    "E16-D05": "#4501",
}  # rider (e): merged after the BQ list's base
REASONS = (
    "not_recorded",
    "no_data_in_range",
    "symbol_delisted",
)  # `14`:1100, kept at three
KINDS = ("engine", "data-feed", "backend")  # E11-D04:406, closed
CONSUMERS = ("E12-S06", "E12-S11", "E12-S12", "E12-Q03", "E12-Q07", "E12-D13")
CARRIED = ("E11-D04 G-1", "G-2", "G-10", "D02 OQ-14", "D05-G1")
TWINS = {"08": ("01", "light"), "09": ("06", "light"), "10": ("05", "hc")}  # RULED BQ-6

RULED_VALUES = {
    "RULED:cancel.ms": "600",  # BQ-21: Cancel from the strip's first moment
    "RULED:esc.ms": "0",  # BQ-21: `Esc` from the start
    "RULED:retry_after.cap": "30",  # BQ-14: max(ladder, retry_after_seconds) capped
    "RULED:cadence.hz": "2",  # BQ-20
    "RULED:waiver.target": "2026-11-06",  # BQ-31
    "RULED:lines.budget": str(SPEC_LINE_BUDGET),
}

# CITE values: key -> (cite, regex whose group 1 is the value at the base)
CITE_VALUES: dict[str, tuple[str, str]] = {
    "t.hz": ("E12J:235", r"coalesced \(≤(\d+) Hz\)"),
    "ref.w": ("D06:51", r"the (\d+)<!--=BUDGET:ref\.css-w-->"),
    "ref.h": ("D06:51", r"× (\d+)<!--=BUDGET:ref\.css-h-->"),
    "zoom": ("05:131", r"with (\d+)% browser"),
    "frame.w": ("E11-D04:854", r"(\d+) × \d+ window"),
    "frame.h": ("E11-D04:854", r"\d+ × (\d+) window"),
    "block.w": ("E16-D05:163", r"at most (\d+) <!--"),
    "ladder.cap": ("14:1111", r"capped (\d+)s\)"),
    "stop.context": ("14:1107", r"auto-retry ×(\d+)"),
    "stop.feed": ("E11-D04:381", r"sequences stop at (\w+) \(O-9\)"),
    "countdown.hz": ("E11-D04:381", r"updated at (\d+) Hz"),
    "strip.ms": ("D02:29", r"nothing for (\d+) ms"),
    "determinate.s": ("D02:29", r"after (\d+) s;"),
    "budget.s": ("11:935", r"in ≤(\d+) s\."),
    "d09.hz": ("D09:117", r"at most (\d+) Hz"),
    "rf.hz": ("RF:181", r"≤(\d+) Hz"),
    "cmp038.slow": ("15:444", r"from the (\d+) s slow path"),
    "cmp028.s": ("15:338", r"after (\d+) s CMP-023 determinate"),
    "min.text": ("05:125", r"≥(\d+(?:\.\d+)?):1"),
    "min.nontext": ("05:126", r"≥(\d+):1"),
}
WORDS = {"three": "3", "five": "5"}

SHA_PATHS = {
    "D02": "docs/design/E12/E12-D02.md",
    "D06": "docs/design/E12/E12-D06.md",
    "D09": "docs/design/E12/E12-D09.md",
    "E16-D05": "docs/design/E16/E16-D05.md",
    "E11-D04": "docs/design/E11/E11-D04.md",
    "E08-D04": "docs/design/E08/E08-D04.md",
    "ADR33": "docs/plan/27-adrs/ADR-0033-renko-brick-sizing-and-series-rebuild.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "23": "docs/plan/23-ws-protocol.md",
    "tokens": DS,
    "E12J": E12J_REL,
    "CAL": CAL_REL,
    "cvd": CVD_REL,
    "contrast": CONTRAST_REL,
    "cvdr": CVDR_REL,
    "18": "docs/plan/18-traceability-matrix.md",
}

DOC_PATHS = {
    "RF": "docs/research/findings/E12-bar-modes.md",
    "ADR33": SHA_PATHS["ADR33"],
    "MR": "services/api/candleviewer/api/market_response.py",
    "MB": "services/api/candleviewer/api/market_bars.py",
    "VAL": "docs/plan/backlog/_tools/validate.py",
    "E12J": E12J_REL,
    "README": "docs/design/README.md",
}

CVD_PAIRS = {  # §12.2: where colour joins the words
    "card-strip": ("color.status.danger.strong", "color.status.warning.strong"),
    "boundary-up": ("color.text.tertiary", "color.candle.up"),
    "boundary-down": ("color.text.tertiary", "color.candle.down"),
}
THEMES = ("dark", "light", "hc")
FLOORS = {"text": 4.5, "non-text": 3.0}  # `05`:125-126 (CITE min.text / min.nontext)


# ---------------------------------------------------------------------------- environment


@dataclass
class Env:
    """Every git read goes through here, so the self-test can simulate drift and diffs."""

    memo: dict[str, object] = field(default_factory=dict)
    handoff: str = ""  # the hand-off from the working tree (the self-test may swap it)
    head_override: dict[str, str] = field(default_factory=dict)
    changed_override: list[str] | None = None

    def show(self, rev: str, rel: str) -> str | None:
        key = f"show:{rev}:{rel}"
        if key not in self.memo:
            res = subprocess.run(
                ["git", "show", f"{rev}:{rel}"],
                cwd=ROOT,
                capture_output=True,
                check=False,
            )
            self.memo[key] = res.stdout.decode("utf-8") if res.returncode == 0 else None
        out = self.memo[key]
        return out if isinstance(out, str) else None

    def base(self, rel: str) -> str:
        return self.show(BASE, rel) or ""

    def head(self, rel: str) -> str | None:
        if rel in self.head_override:
            return self.head_override[rel]
        return self.show(HEAD_REF, rel)

    def git(self, *args: str) -> str:
        key = "git:" + "\x00".join(args)
        if key not in self.memo:
            res = subprocess.run(
                ["git", *args], cwd=ROOT, capture_output=True, check=False
            )
            self.memo[key] = res.stdout.decode("utf-8") if res.returncode == 0 else ""
        out = self.memo[key]
        return out if isinstance(out, str) else ""

    def changed(self) -> list[str]:
        if self.changed_override is not None:
            return list(self.changed_override)
        mb = self.git("merge-base", "HEAD", HEAD_REF).strip()
        if not mb:
            return ["<merge-base unresolved>"]
        names = set(self.git("diff", "--name-only", mb).split())
        names |= set(self.git("ls-files", "--others", "--exclude-standard").split())
        return sorted(names)


def plan_rel(env: Env, nn: str) -> str | None:
    key = f"plan:{nn}"
    if key not in env.memo:
        listing = env.git("ls-tree", "--name-only", BASE, "docs/plan/").split()
        hit = [p for p in listing if Path(p).name.startswith(f"{nn}-")]
        env.memo[key] = hit[0] if hit else None
    out = env.memo[key]
    return out if isinstance(out, str) else None


def doc_rel(env: Env, doc: str) -> str | None:
    if re.fullmatch(r"\d\d", doc):
        return plan_rel(env, doc)
    if re.fullmatch(r"D0\d", doc):
        return f"docs/design/E12/E12-{doc}.md"
    if re.fullmatch(r"E\d\d-D\d\d", doc):
        return f"docs/design/{doc[:3]}/{doc}.md"
    return DOC_PATHS.get(doc)


def base_line(env: Env, doc: str, n: int) -> str | None:
    rel = doc_rel(env, doc)
    if rel is None:
        return None
    lines = env.base(rel).split("\n")
    return lines[n - 1] if 0 < n <= len(lines) else None


# ---------------------------------------------------------------------------- text


ANCHOR = re.compile(
    r"(#[0-9A-Fa-f]{6}|\d{4}-\d{2}-\d{2}|[0-9a-f]{10}|\d+(?:\.\d+)?)<!--=([A-Z]+):([^>]+?)-->"
)
ANCHOR_TAG = re.compile(r"<!--=([A-Z]+):([^>]+?)-->")
COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)
HIDDEN_CHARS = re.compile("[\u00ad\u200b-\u200d\u2060\ufeff]")
HEADING = re.compile(r"^(#{1,6}) (.*)$")
CODE = re.compile(r"`[^`\n]*`")
QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”')
CITE = re.compile(
    r"(?:`(?P<nn>\d\d)`|(?<![\w-])(?P<doc>D0[2-9]|E\d\d-D\d\d|RF|ADR33|MR|MB|VAL|E12J|README))"
    r":(?P<a>\d+)(?:[–-](?P<b>\d+))?(?P<more>(?:,\s*:\d+(?:[–-]\d+)?)*)"
)


def nfkc(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


def visible(text: str) -> str:
    """The text a reader sees: anchors keep their values, every other comment is cut."""
    keep = ANCHOR.sub(lambda m: m[1], text)
    keep = ANCHOR_TAG.sub("", keep)
    return COMMENT.sub("", keep)


def pin_text(text: str) -> str:
    """The pinned form of a unit: anchored values cut, the tag kept, NFKC + whitespace."""
    return nfkc(ANCHOR.sub(lambda m: f"<!--={m[2]}:{m[3]}-->", text))


def headings(text: str) -> list[tuple[int, int, str]]:
    out: list[tuple[int, int, str]] = []
    fence = False
    for i, line in enumerate(text.split("\n")):
        if line.startswith("```"):
            fence = not fence
        m = HEADING.match(line)
        if m and not fence:
            out.append((i, len(m[1]), m[2].strip()))
    return out


def section(text: str, prefix: str) -> str:
    """The body under the first heading whose title starts with `prefix`, to its next peer."""
    lines = text.split("\n")
    hs = headings(text)
    for k, (i, lvl, title) in enumerate(hs):
        if visible(title).startswith(prefix):
            end = len(lines)
            for j, lvl2, _ in hs[k + 1 :]:
                if lvl2 <= lvl:
                    end = j
                    break
            return "\n".join(lines[i + 1 : end])
    return ""


def split_row(line: str) -> list[str]:
    body = line.strip()
    body = body.removeprefix("|")
    body = body[:-1] if body.endswith("|") and not body.endswith("\\|") else body
    cells = re.split(r"(?<!\\)\|", body)
    return [c.strip().replace("\\|", "|") for c in cells]


def is_rule(line: str) -> bool:
    return (
        re.fullmatch(r"\|?(\s*:?-{3,}:?\s*\|)+\s*:?-*:?\s*\|?", line.strip())
        is not None
    )


def table(block: str) -> list[list[str]]:
    """The data rows of the first table in `block` (header and rule line dropped)."""
    rows: list[list[str]] = []
    seen_rule = False
    started = False
    for line in block.split("\n"):
        if line.lstrip().startswith("|"):
            started = True
            if is_rule(line):
                seen_rule = True
                continue
            if seen_rule:
                rows.append(split_row(line))
        elif started:
            break
    return rows


def quotes(cell: str) -> list[str]:
    return [q[1:-1] for q in QUOTED.findall(cell)]


def strip_md(text: str) -> str:
    return nfkc(re.sub(r"\*\*|__", "", text))


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z*`(\"“0-9])", text)
    return [p.strip() for p in parts if p.strip()]


def spans(text: str) -> list[tuple[str, int, int]]:
    """Every cited span (doc, first line, last line); a reversed or oversized range is (doc, -1, -1)."""
    out: list[tuple[str, int, int]] = []
    for m in CITE.finditer(visible(text)):
        doc = m["nn"] or m["doc"]
        parts = [(m["a"], m["b"])]
        parts += re.findall(r":(\d+)(?:[–-](\d+))?", m["more"] or "")
        for a, b in parts:
            lo, hi = int(a), int(b) if b else int(a)
            out.append((doc, lo, hi) if lo <= hi <= lo + 400 else (doc, -1, -1))
    return out


def cites(text: str) -> list[tuple[str, int]]:
    return [
        (d, n)
        for d, lo, hi in spans(text)
        for n in (range(lo, hi + 1) if lo > 0 else [-1])
    ]


# ---------------------------------------------------------------------------- colour


def contrast_threshold(env: Env) -> float:
    """The sRGB linearisation threshold of `contrast_check.py` at the base (its formula reused)."""
    m = re.search(r"c <= (0\.\d+)", env.base(CONTRAST_REL))
    return float(m[1]) if m else 0.03928


def rgb(hex6: str) -> tuple[int, int, int]:
    h = hex6.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def luminance(hex6: str, thr: float) -> float:
    def lin(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= thr else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(c) for c in rgb(hex6))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str, thr: float) -> float:
    la, lb = luminance(a, thr), luminance(b, thr)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def trunc(x: float, places: int) -> str:
    f = 10**places
    return f"{math.floor(x * f + 1e-9) / f:.{places}f}"


def cvd_matrices(env: Env) -> dict[str, tuple[tuple[float, ...], ...]]:
    """The deuteranopia and protanopia matrices of `cvd_sim.py` at the base."""
    src = env.base(CVD_REL)
    out: dict[str, tuple[tuple[float, ...], ...]] = {}
    for sim, name in (
        ("deutan", "DEUTERANOPIA_MATRIX"),
        ("protan", "PROTANOPIA_MATRIX"),
    ):
        m = re.search(rf"{name} = np\.array\(\s*\[(.*?)\]\s*\)", src, re.DOTALL)
        rows = re.findall(r"\[([^\[\]]+)\]", m[1]) if m else []
        out[sim] = tuple(
            tuple(float(x) for x in r.split(",") if x.strip()) for r in rows
        )
    return out


def simulate(hex6: str, matrix: tuple[tuple[float, ...], ...]) -> tuple[int, int, int]:
    """As `cvd_sim.py` does: the matrix on sRGB 0-255 values, clipped, then truncated to uint8."""
    v = rgb(hex6)
    out = []
    for row in matrix:
        s = sum(row[i] * v[i] for i in range(3))
        out.append(int(max(0.0, min(255.0, s))))
    return out[0], out[1], out[2]


def tritan_matrix(env: Env) -> tuple[float, ...]:
    """Machado 2009 tritanopia (severity 1.0) as `cvd_simulate.py` holds it at the base."""
    m = re.search(r"TRITAN_MACHADO = \(([^()]*)\)", env.base(CVDR_REL))
    vals = (
        tuple(float(x) for x in m[1].replace("\n", " ").split(",") if x.strip())
        if m
        else ()
    )
    return vals if len(vals) == 9 else ()


def simulate_tritan(hex6: str, mat: tuple[float, ...]) -> tuple[int, int, int]:
    """As `cvd_simulate.py` does: the matrix on linear RGB, back to sRGB, rounded and clipped."""

    def lin(x: int) -> float:
        v = x / 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    def srgb(c: float) -> int:
        v = c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055
        return max(0, min(255, round(max(0.0, min(1.0, v)) * 255.0)))

    li = [lin(x) for x in rgb(hex6)]
    out = [srgb(sum(mat[3 * r + i] * li[i] for i in range(3))) for r in range(3)]
    return out[0], out[1], out[2]


def lab(c: tuple[int, int, int]) -> tuple[float, float, float]:
    def lin(x: int) -> float:
        v = x / 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(x) for x in c)
    x = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else (7.787 * t) + (16 / 116)

    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def luma(c: tuple[int, int, int]) -> float:
    """`cvd_sim.py`'s greyscale: Rec. 601 weights."""
    return c[0] * 0.299 + c[1] * 0.587 + c[2] * 0.114


def theme_tokens(env: Env, theme: str) -> dict[str, str]:
    key = f"theme:{theme}"
    if key not in env.memo:
        themes = json.loads(env.base(f"{DS}/themes.json") or "{}")
        name = {"hc": "high-contrast"}.get(theme, theme)
        sets: list[str] = []
        for th in themes.get("themes", []):
            if isinstance(th, dict) and th.get("name") == name:
                sets = [str(s) for s in th.get("sets", [])]
        merged: dict[str, str] = {}
        for s in sets:
            data = json.loads(env.base(f"{DS}/{s}.tokens.json") or "{}")
            for k, v in data.items():
                if isinstance(v, dict) and isinstance(v.get("$value"), str):
                    merged[k] = str(v["$value"])
        env.memo[key] = merged
    out = env.memo[key]
    return dict(out) if isinstance(out, dict) else {}


def resolve(env: Env, theme: str, name: str) -> str:
    toks = theme_tokens(env, theme)
    v = toks.get(name, "")
    for _ in range(20):
        m = re.fullmatch(r"\{([^{}]+)\}", v)
        if not m:
            break
        v = toks.get(m[1], "")
    return v.upper() if re.fullmatch(r"#[0-9A-Fa-f]{6}", v) else ""


# ---------------------------------------------------------------------------- values


def sprint_start(env: Env, key: str) -> str:
    cal = env.base(CAL_REL)
    m = re.search(r"SPRINT01_START = datetime\.date\((\d+), (\d+), (\d+)\)", cal)
    d = re.search(r"SPRINT_DAYS = (\d+)", cal)
    tickets = json.loads(env.base(E12J_REL) or "[]")
    sprint = next((t.get("sprint") for t in tickets if t.get("key") == key), None)
    n = re.search(r"(\d+)", str(sprint or ""))
    if not (m and d and n):
        return "?"
    start = datetime.date(int(m[1]), int(m[2]), int(m[3]))
    return (start + datetime.timedelta(days=(int(n[1]) - 1) * int(d[1]))).isoformat()


def cite_value(env: Env, key: str) -> str:
    ref, pattern = CITE_VALUES[key]
    doc, n = ref.rsplit(":", 1)
    line = base_line(env, doc, int(n)) or ""
    m = re.search(pattern, line)
    if not m:
        return "?"
    return WORDS.get(m[1], m[1])


def registry(env: Env) -> list[str]:
    """Every code of `x-error-codes` and `x-error-codes-ws` in `22` at the base."""
    text = env.base(plan_rel(env, "22") or "")
    codes: list[str] = []
    for head in ("x-error-codes:", "x-error-codes-ws:"):
        i = text.find("\n" + head)
        if i < 0:
            continue
        for line in text[i + 1 :].split("\n")[1:]:
            if line and not line.startswith((" ", "#")):
                break
            m = re.match(r"\s*- code:\s*([a-z_]+)", line)
            if m:
                codes.append(m[1])
    return codes


def map_codes(spec: str, env: Env) -> tuple[list[str], list[str]]:
    """(codes named in §3's Signal cells, codes named in the outside paragraph)."""
    reg = set(registry(env))
    sec = visible(section(spec, "3. "))
    mapped = [
        c for row in table(sec) for c in CODE.findall(row[0]) if c.strip("`") in reg
    ]
    para = next(
        (ln for ln in sec.split("\n") if ln.startswith("**Outside the chart")), ""
    )
    outside = [c for c in CODE.findall(para) if c.strip("`") in reg]
    return [c.strip("`") for c in mapped], [c.strip("`") for c in outside]


NOT_FOUND = "(not found first)"


def depth0_split(text: str, sep: str) -> list[str]:
    out, depth, cur, i = [], 0, "", 0
    while i < len(text):
        ch = text[i]
        depth += ch in "(["
        depth -= ch in ")]"
        if depth == 0 and text.startswith(sep, i):
            out.append(cur)
            cur, i = "", i + len(sep)
            continue
        cur += ch
        i += 1
    return [x.strip() for x in out + [cur] if x.strip()]


def dry_items(spec: str) -> dict[str, list[str]]:
    """§16's needs, item by item, per consumer short key (S06, S11, S12, Q03, Q07, D13)."""
    line = next(
        (
            ln
            for ln in visible(section(spec, "16. ")).split("\n")
            if "item by item: " in ln
        ),
        "",
    )
    body = nfkc(line.split("item by item: ", 1)[-1]).rstrip(".")
    out: dict[str, list[str]] = {}
    for part in re.split(r"; (?=[SQD]\d\d — )", body) if line else []:
        key, _, items = part.partition(" — ")
        out[key] = depth0_split(items, ", ")
    return out


def contrast_rows(spec: str) -> list[list[str]]:
    return table(visible(section(spec, "12.1 ")))


def compute(spec: str, env: Env) -> dict[str, str]:
    vals: dict[str, str] = dict(RULED_VALUES)
    for key in CITE_VALUES:
        vals[f"CITE:{key}"] = cite_value(env, key)
    cap = int(vals["CITE:ladder.cap"]) if vals["CITE:ladder.cap"].isdigit() else 0
    for n in range(1, 7):
        vals[f"LADDER:{n}"] = str(min(2 ** (n - 1), cap))
    boards = table(visible(section(spec, "0. ")))
    vals["COUNT:boards"] = str(len(boards))
    vals["COUNT:boards.dark"] = str(
        sum(1 for r in boards if len(r) > 3 and r[3] == "dark")
    )
    vals["COUNT:boards.twins"] = str(
        sum(1 for r in boards if len(r) > 4 and r[4] != "—")
    )
    mapped, outside = map_codes(spec, env)
    vals["COUNT:codes.total"] = str(len(set(registry(env))))
    vals["COUNT:codes.mapped"] = str(len(set(mapped)))
    vals["COUNT:codes.outside"] = str(len(set(outside)))
    for key in CONSUMERS:
        vals[f"DATE:{key}"] = sprint_start(env, key)
    for key, items in dry_items(spec).items():
        miss = sum(1 for x in items if NOT_FOUND in x)
        vals[f"COUNT:dryrun.{key}.needs"] = str(len(items))
        vals[f"COUNT:dryrun.{key}.found"] = str(len(items) - miss)
        vals[f"COUNT:dryrun.{key}.missing"] = str(miss)
    for key, rel in SHA_PATHS.items():
        vals[f"SHA:{key}"] = env.git(
            "log", "-1", "--format=%H", BASE, "--", rel
        ).strip()[:10]
    thr = contrast_threshold(env)
    for row in contrast_rows(spec):
        if len(row) < 4:
            continue
        slot, fg, bg = row[0], row[1].strip("`"), row[2].strip("`")
        for th in THEMES:
            a, b = resolve(env, th, fg), resolve(env, th, bg)
            vals[f"CONTRAST:{slot}.{th}"] = (
                trunc(contrast(a, b, thr), 2) if a and b else "?"
            )
    mats = cvd_matrices(env)
    tri = tritan_matrix(env)
    for pair, (ta, tb) in CVD_PAIRS.items():
        for th in THEMES:
            a, b = resolve(env, th, ta), resolve(env, th, tb)
            if not (a and b):
                continue
            ca, cb = rgb(a), rgb(b)
            vals[f"DE:{pair}.{th}.normal"] = trunc(math.dist(lab(ca), lab(cb)), 1)
            for sim, mat in mats.items():
                sa, sb = simulate(a, mat), simulate(b, mat)
                vals[f"DE:{pair}.{th}.{sim}"] = trunc(math.dist(lab(sa), lab(sb)), 1)
            if tri:
                ta_, tb_ = simulate_tritan(a, tri), simulate_tritan(b, tri)
                vals[f"DE:{pair}.{th}.tritan"] = trunc(math.dist(lab(ta_), lab(tb_)), 1)
            vals[f"DY:{pair}.{th}"] = trunc(abs(luma(ca) - luma(cb)), 1)
    return vals


def fill(spec: str, vals: dict[str, str]) -> str:
    def sub(m: re.Match[str]) -> str:
        key = f"{m[2]}:{m[3]}"
        return f"{vals.get(key, m[1])}<!--={m[2]}:{m[3]}-->"

    return ANCHOR.sub(sub, spec)


# ---------------------------------------------------------------------------- findings and pins


@dataclass(frozen=True)
class Finding:
    gate: str
    level: str  # FAIL | WARN | NOTE
    msg: str


@dataclass(frozen=True)
class Unit:
    region: str
    loc: str
    text: str


def units(spec: str, prefix: str = "") -> list[Unit]:
    """Every pinned unit: heading, table row by lead cell, rule line, prose sentence."""
    out: list[Unit] = []
    path: list[tuple[int, str]] = [(0, prefix)] if prefix else []
    occ: dict[str, int] = {}
    region = f"{prefix} › (top)#1" if prefix else "(top)#1"
    counters: dict[str, int] = {}
    fence = False
    for raw in spec.split("\n"):
        line = raw.rstrip()
        if line.startswith("```"):
            fence = not fence
        m = HEADING.match(line)
        if m and not fence:
            lvl = len(m[1])
            path = [p for p in path if p[0] < lvl] + [(lvl, pin_text(m[2]))]
            name = " › ".join(t for _, t in path)
            occ[name] = occ.get(name, 0) + 1
            region = f"{name}#{occ[name]}"
            counters = {}
            out.append(Unit(region, "heading", pin_text(line)))
            continue
        if not line.strip():
            continue
        if line.lstrip().startswith("|"):
            if is_rule(line):
                counters["rule"] = counters.get("rule", 0) + 1
                out.append(Unit(region, f"rule {counters['rule']}", "rule"))
            else:
                lead = pin_text(split_row(line)[0])
                out.append(
                    Unit(region, f"row {lead}", pin_text(" | ".join(split_row(line))))
                )
            continue
        for s in sentences(pin_text(line)):
            counters["s"] = counters.get("s", 0) + 1
            out.append(Unit(region, f"s{counters['s']}", s))
    return out


def all_units(spec: str, handoff: str) -> list[Unit]:
    """The spec's units, then the hand-off's under the region prefix `hand-off`."""
    return units(spec) + units(handoff, "hand-off")


def pin_lines(spec: str, handoff: str) -> list[str]:
    us = all_units(spec, handoff)
    head = [
        f"# E12-D08 pins (every unit of the spec and the hand-off): region, location, normalised text; {len(us)} units.",
        "# Written by `--repin-ruled` only; `--check` reads it (never hand-edit; G-RULED-PIN).",
    ]
    return head + [f"{u.region}\t{u.loc}\t{u.text}" for u in us]


def pins_gate(spec: str, handoff: str, pins: str) -> list[str]:
    want: dict[str, set[tuple[str, str]]] = {}
    for line in pins.split("\n"):
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) == 3:
            want.setdefault(parts[0], set()).add((parts[1], parts[2]))
    have: dict[str, set[tuple[str, str]]] = {}
    for u in all_units(spec, handoff):
        have.setdefault(u.region, set()).add((u.loc, u.text))
    bad: list[str] = []
    for region in sorted(set(want) | set(have)):
        if want.get(region) != have.get(region):
            delta = have.get(region, set()) ^ want.get(region, set())
            locs = sorted({loc for loc, _ in delta})[:4]
            bad.append(f"region {region[:70]!r} changed at {', '.join(locs)}")
    return bad


# ---------------------------------------------------------------------------- gate helpers


Gate = Callable[[str, Env, dict[str, str]], list[str]]


def need(sec: str, phrases: tuple[str, ...], where: str) -> list[str]:
    text = nfkc(visible(sec))
    return [f"{where}: missing {p!r}" for p in phrases if nfkc(p) not in text]


def deck(spec: str) -> dict[str, list[str]]:
    rows = table(visible(section(spec, "11. ")))
    return {r[0]: r for r in rows if len(r) >= 5}


def form(text: str) -> str:
    t = nfkc(text)
    t = re.sub(r"\{[a-z_ ]+\}", "V", t)
    t = re.sub(r"\d{4}-\d\d-\d\d \d\d:\d\d", "T", t)
    t = re.sub(r"\b\d\d:\d\d\b", "T", t)
    return re.sub(r"\b\d+[smhdw]\b", "V", t)


SKIP_CLAIMS = (
    "14. ",
    "18.4 ",
)  # the gate table names the violations it FAILs, and the version line narrates the review
# history in the gates' own words: neither is a claim (G-UNMERGED and G-ANCHOR read the latter)
NEG = re.compile(
    r"\b(?:no|not|never|nor|none|without|would|cannot)\b|n't\b", re.IGNORECASE
)
WITHOUT = re.compile(r"\bwithout\b", re.IGNORECASE)
# "without" negates a trigger only when it governs it: at most three words before it, no comma
# ("answered without an automatic retry"); a leading condition clause ("Without a pause, a 403
# is re-sent") negates nothing
GOVERNS = re.compile(r"\bwithout(?:\s+[\w`'-]+){0,3}\s*$", re.IGNORECASE)


def claims(spec: str) -> list[str]:
    """Every sentence and table cell a reader sees, quoted copy cut (copy is G-COPY's)."""
    text = spec
    for head in SKIP_CLAIMS:
        body = section(text, head)
        if body:
            text = text.replace(body, "")
    out: list[str] = []
    for line in visible(text).split("\n"):
        if HEADING.match(line) or not line.strip():
            continue
        bare = QUOTED.sub(" ", line)
        if bare.lstrip().startswith("|"):
            if not is_rule(bare):
                out += [strip_md(c) for c in split_row(bare) if c.strip()]
        else:
            out += [strip_md(x) for x in sentences(nfkc(bare))]
    return out


def contra(
    spec: str,
    trigger: re.Pattern[str],
    also: re.Pattern[str] | None = None,
    allow: Callable[[str], bool] | None = None,
    what: str = "a claim",
) -> list[str]:
    """Default-deny for a ruled class: a claim that matches `trigger` (and `also`) FAILs unless,
    with the trigger cut, it is negated, or `allow` accepts it. A paraphrase is read, not a pin."""
    bad: list[str] = []
    for c in claims(spec):
        hit = trigger.search(c)
        if not hit or (also is not None and not also.search(c)):
            continue
        # "without" negates only before the trigger: "re-sends a 400, without asking the user"
        # is a claim, "a 4xx is answered without an automatic retry" is not
        cut = trigger.sub(" ", c)
        negated = NEG.search(WITHOUT.sub(" ", cut)) or GOVERNS.search(c[: hit.start()])
        if negated or (allow is not None and allow(c)):
            continue
        bad.append(f"{what} contradicts the ruling: {c[:90]!r}")
    return bad


def deny(
    spec: str,
    trigger: re.Pattern[str],
    also: re.Pattern[str],
    allow: Callable[[str], bool],
    what: str,
) -> list[str]:
    """Default-deny by structure: a claim that names a gated object (`trigger`) beside a role or
    a visibility word (`also`) FAILs unless it carries an approved marker (`allow`). No negation
    escapes it: "never see" and "who is not the Owner" are the hiding they would excuse."""
    return [
        f"{what} contradicts the ruling: {c[:90]!r}"
        for c in claims(spec)
        if trigger.search(c) and also.search(c) and not allow(c)
    ]


def actions(spec: str) -> list[tuple[str, str]]:
    """(row, cell) of every action, destination and retry column the ruled tables carry."""
    out: list[tuple[str, str]] = []
    for prefix, cols in (("2.2 ", (5,)), ("3. ", (2, 5)), ("4.1 ", (5,))):
        for r in table(visible(section(spec, prefix))):
            out += [(r[0], r[c]) for c in cols if len(r) > c]
    return out


# ---------------------------------------------------------------------------- the gates


def g_ruled(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    bad: list[str] = []
    heads = [t for _, _, t in headings(spec) if "RULED" in t and "BQ-1" in t]
    if not heads or RULING_ID not in heads[0] or BQ_LIST_ID not in heads[0]:
        bad.append(
            f"the RULED heading must cite comment {RULING_ID} on the list {BQ_LIST_ID}"
        )
    for m in re.finditer(r"(?<![\w-])(\d{10})(?![\w-])", visible(spec)):
        if m[1] not in ALLOWED_IDS:
            bad.append(f"comment id {m[1]} is not on the allow-list")
    return bad


def g_boards(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    sec = visible(section(spec, "0. "))
    rows = table(sec)
    bad: list[str] = []
    if len(rows) != 10:
        bad.append(f"{len(rows)} boards, ruled ten")
    dark = [r for r in rows if len(r) > 4 and r[3] == "dark" and r[4] == "—"]
    if len(dark) != 7:
        bad.append(f"{len(dark)} dark boards, ruled seven")
    twins = {r[0]: (r[4], r[3]) for r in rows if len(r) > 4 and r[4] != "—"}
    if twins != TWINS:
        bad.append(f"the twins are {twins}, ruled {TWINS}")
    if rows and 3 * len(twins) > len(rows):
        bad.append("twins over a third of the boards")
    bad += need(sec, ("**Specified (drawn on request)**",), "§0")
    bad += need(
        sec, ("The error-mapping table (§3) is a spec table, not a board.",), "§0"
    )
    return bad


def g_scr047(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    rows = table(visible(section(spec, "2.2 ")))
    bad: list[str] = []
    if len(rows) != 5:
        bad.append(f"{len(rows)} SCR-047 frames, ruled five")
    reasons = [r[2].strip("`") for r in rows if len(r) > 3]
    if any(x not in REASONS for x in reasons) or set(reasons) != set(REASONS):
        bad.append(f"the `reason` values {reasons} are not the three of `14`:1100")
    heads = [tuple(quotes(r[3])) for r in rows if len(r) > 3]
    for i, a in enumerate(heads):
        for b in heads[i + 1 :]:
            if a == b:
                bad.append(f"two frames share the heading {a}")
    for r in rows:
        if len(r) > 6 and "exchange-no-bars" in r[0] and "new, PROPOSED" not in r[6]:
            bad.append("the exchange-no-bars cause is not marked new, PROPOSED")
    # RULED BQ-7 (ruling 6475004920: distinct heading and cause): five distinct headings AND five
    # distinct causes, no exception; E16-D05:167's shared history-start cause is a C-row, not
    # followed (D08-C4)
    ids = [r[0].strip("`").split("/")[-1] for r in rows if len(r) > 4]
    causes = [tuple(quotes(r[4])) for r in rows if len(r) > 4]
    for i in range(len(causes)):
        if not causes[i]:
            bad.append(f"{ids[i]} has no quoted cause")
        for j in range(i + 1, len(causes)):
            if causes[i] == causes[j]:
                bad.append(f"{ids[i]} and {ids[j]} share a cause (ruled distinct)")
    for r in rows:
        if len(r) > 6 and "before-start" in r[0] and "new, PROPOSED" not in r[6]:
            bad.append("the before-start cause is not marked new, PROPOSED")
    sec = visible(section(spec, "2.2 "))
    bad += need(sec, ("(D08-C4)", "BQ-7 of ruling 6475004920"), "§2.2")
    crow = next(
        (r for r in table(visible(section(spec, "15.2 "))) if r[0] == "D08-C4"), []
    )
    if len(crow) < 3 or "E16-D05:167" not in crow[1] or "not followed" not in crow[2]:
        bad.append("D08-C4 does not record E16-D05:167 as not followed")
    never = next((r for r in rows if "never-recorded" in r[0]), [])
    act = nfkc(never[5]) if len(never) > 5 else ""
    if "`Record this symbol`" in act and not act.startswith(
        "the Owner: `Record this symbol`"
    ):
        bad.append("the never-recorded CTA is not the Owner's (S-10)")
    return bad


def g_map(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    reg = registry(env)
    mapped, outside = map_codes(spec, env)
    bad: list[str] = []
    if not reg:
        bad.append("no code registry read from `22`")
    for code in reg:
        if code not in mapped and code not in outside:
            bad.append(f"`{code}` is unmapped (T Test: a blocking finding)")
        if code in mapped and code in outside:
            bad.append(f"`{code}` is both mapped and outside")
    dupes = {c for c in outside if outside.count(c) > 1}
    bad += [f"`{c}` listed twice outside" for c in sorted(dupes)]
    sec = visible(section(spec, "3. "))
    rows = {nfkc(r[0]): r for r in table(sec)}

    def row(start: str) -> list[str]:
        return next((r for k, r in rows.items() if k.startswith(nfkc(start))), [])

    checks = (
        ("`no_data_recorded` (422), the window straddling", 2, "never SCR-047"),
        ("`no_data_recorded` (422), the window wholly before", 2, "`e12-before-start`"),
        ("`200` with zero rows, time bars", 2, "`e12-exchange-no-bars`"),
        ("`200` with zero rows, non-time bars", 2, "never SCR-047"),
        ("`validation_failed`", 2, "`forbidden` drawn as the failed state"),
    )
    for start, col, phrase in checks:
        r = row(start)
        if len(r) <= col or nfkc(phrase) not in nfkc(r[col]):
            bad.append(
                f"the BQ-11 reading {phrase!r} is missing from the row {start!r}"
            )
    bad += need(
        sec,
        ("With a previous series, every failure is the strip's inline notice",),
        "§3",
    )
    # BQ-11 upheld (2026-10-29): the five WS refusals `23` marks retryable ride the ladder on the
    # data-feed card, the card's line reading its state; the §3 Retry cell and the §4.1 sentence
    ws_row = row("WS refusals:")
    ws_cell = ws_row[5] if len(ws_row) > 5 else ""
    if not ws_cell.startswith(
        "the ladder for the five `23` marks retryable"
    ) or not all(f"`{c}`" in ws_cell for c in WS_RETRYABLE):
        bad.append("§3: the WS refusals' Retry cell does not give the five the ladder")
    bad += need(
        section(spec, "4.1 "),
        (
            "**The refusals `23` marks retryable**",
            "stay on the data-feed card with no carve-out",
            '"Retrying in N s" (W-14)',
        ),
        "§4.1",
    )
    for r in table(sec):
        statuses = set(re.findall(r"\((4\d\d)\)", r[0])) - {"429"}
        if statuses and len(r) > 5 and re.search(r"ladder|automatic", r[5]):
            bad.append(f"the row {r[0][:40]!r} retries a {sorted(statuses)} on its own")
    return bad


def g_scr048(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    sec = visible(section(spec, "4.1 "))
    rows = table(sec)
    bad: list[str] = []
    if len(rows) != 3:
        bad.append(f"{len(rows)} SCR-048 classes, ruled three")
    for r in rows:
        kinds = [k.strip("`") for k in CODE.findall(r[2])] if len(r) > 2 else []
        if not kinds or any(k not in KINDS for k in kinds):
            bad.append(f"the class {r[0]!r} has `kind` {kinds}, outside {KINDS}")
    heads = [set(quotes(r[3])) for r in rows if len(r) > 3]
    for i, a in enumerate(heads):
        for b in heads[i + 1 :]:
            if a & b:
                bad.append(f"two classes share a heading {sorted(a & b)}")
    if not any(len(r) > 6 and r[0] == "recompute" and "PROPOSED" in r[6] for r in rows):
        bad.append("the recompute heading is not marked new, PROPOSED")
    bad += need(
        sec,
        ("WebGL2 unavailable keeps E11-D04's own card, cited, not redrawn",),
        "§4.1",
    )
    return bad


RETRY_LINE = re.compile(r"next try in \d|Retrying in \d|Automatic retries stopped")
AUTO_RETRY = re.compile(
    r"\bautomatic(?:ally)?\s+retr\w*|\bretr\w*\s+(?:\w+\s+)?automatically|\bauto-retr\w*"
    r"|\btried again\b|\bre-?sen[dt]\w*|\bre-?submit\w*|\bre-?issu\w*|\bre-?attempt\w*"
    r"|\b(?:second|another|further) (?:attempt|try)\b|\bby itself\b|\bon (?:its|their) own\b",
    re.IGNORECASE,
)
# default-deny: any repeat word beside a 4xx is a retry claim, unless negated or the 429 carve-out;
# the user's own `Retry` is a control, named in backticks, so a code span is not a repeat word
REPEAT = re.compile(
    r"\bretr(?:y|ies|ied|ying)\b(?! button)|\bre-tr\w*|\brepeat\w*|\bagain\b|\bonce more\b"
    r"|\bone more\b|\banother (?:attempt|try|request|round|go|call)\b|\bre-[a-z]\w*"
    r"|\bre(?:play(?:s|ed|ing)|run\w*|fire\w*|queue\w*|dispatch\w*|post\w*)\b",
    re.IGNORECASE,
)
# a 4xx by any name (M-1r5): the class, a number, a series, a status name, a refusal or a rejection;
# round 7 (m-2) closes the status names over every registered 4xx reason phrase (400-431, 451,
# their older names included) and adds "denied" and "declined" to the refusal words
# (423's name is read capitalised, so the spec's "locked inputs" is not a status)
_FOUR_XX_WORDS = (
    r"\b4xx\b|\b4-?series\b|\bfour-hundreds?\b|\bvalidation\b|\bforbidden\b|\brefus\w*"
    r"|\bclient errors?\b|\bbad request\b|\bunauthori[sz]ed\b|\bnot found\b|\bconflict\w*"
    r"|\bunprocessable\b|\bgone\b|\bpayload too large\b|\breject\w*|\bdenied\b|\bdeclined\b"
    r"|\bpayment required\b|\bmethod not allowed\b|\bnot acceptable\b"
    r"|\bproxy authentication required\b|\brequest time-?out\b|\blength required\b"
    r"|\bprecondition (?:failed|required)\b|\b(?:content|request entity) too large\b"
    r"|\b(?:uri|request-uri) too long\b|\bunsupported media type\b"
    r"|\b(?:requested )?range not satisfiable\b|\bexpectation failed\b|\bteapot\b"
    r"|\bmisdirected request\b|(?-i:\bLocked\b)|\bfailed dependency\b|\btoo early\b"
    r"|\bupgrade required\b|\brequest header fields too large\b"
    r"|\bunavailable for legal reasons\b"
)
_NAME_429 = (
    r"\btoo many requests\b"  # 429's own name: the carve-out reads it as the number
)
FOUR_XX = re.compile(rf"{_FOUR_XX_WORDS}|{_NAME_429}|\b4\d\d\b", re.IGNORECASE)
# subject deny (M-1r3): a claim whose subject is a 4xx may carry an action verb only beside the ruled
# marker (a negation such as "no automatic retry"), the user's own `Retry` control or the 429
# carve-out; a pure refusal description carries no such verb. Every send, fire, queue, try, loop
# or repeat verb is an action, so a new paraphrase needs no new word in a blacklist of retries
ACT = re.compile(
    rf"{AUTO_RETRY.pattern}|{REPEAT.pattern}"
    r"|\bsen[dt]s?\b|\bsending\b|\bfir(?:e|es|ed|ing)\b|\bqueu\w*|\btr(?:y|ies|ied|ying)\b"
    r"|\battempt\w*|\bloop\w*|\bcycl\w*|\bsecond (?:time|go|pass)\b|\btwice\b|\bback off\w*"
    r"|\bschedul\w*|\bcall(?:s|ed|ing)? (?:it |them |the [\w-]+ )?(?:again|back)\b|\bpoll\w*"
    r"|\bgo(?:es)? (?:out|back)\b|\bfurther go\b|\b(?:hand|pass|feed|push)\w* (?:it |them )?back\b",
    re.IGNORECASE,
)


def g_ladder(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    sec = visible(section(spec, "5. "))
    bad = need(
        sec,
        (
            "**No automatic retry on a 4xx**",
            "max(the ladder step, the server's `retry_after_seconds`)",
            '`aria-live="off"`',
            '"Automatic retries stopped"',
        ),
        "§5",
    )
    rule = next((s for s in sentences(nfkc(sec)) if "max(the ladder step" in s), "")
    if rule and "PROPOSED" not in rule:
        bad.append("the Retry-After rule is not marked PROPOSED")
    bad += need(
        sec,
        ('beside the stop sentence "Automatic retries stopped" (W-15; D08-C22)',),
        "§5",
    )
    for w, r in deck(spec).items():
        if r[4] == "retry" and not all(RETRY_LINE.search(q) for q in quotes(r[2])):
            bad.append(
                f"{w} is a retry line with no next-attempt time or stop sentence"
            )

    def only_429(c: str) -> bool:
        other = re.search(_FOUR_XX_WORDS, c, re.IGNORECASE)
        codes = set(re.findall(r"\b4\d\d\b", c))
        if re.search(_NAME_429, c, re.IGNORECASE):
            codes.add("429")
        return codes == {"429"} and not other

    bad += contra(
        spec,
        AUTO_RETRY,
        FOUR_XX,
        lambda c: only_429(c) or ws_retryable(c),
        "an automatic retry on a 4xx",
    )
    bad += contra(
        spec,
        ACT,
        FOUR_XX,
        lambda c: only_429(c) or ws_retryable(c) or not ACT.search(CODE.sub(" ", c)),
        "an action on a 4xx without the ruled marker",
    )
    # M-1r4: the subject is the 4xx alone. A claim naming a 4xx, a refusal or a validation error
    # FAILs unless it carries the ruled marker, is the 429 carve-out, or is a mapping statement:
    # one with no process word. The process class is open by form, not a verb list: any `re`
    # verb (the vocabulary below lists the `re` words that are not repeats), any ladder, rung,
    # step, interval, schedule or background word, and every verb ACT already reads
    for c in claims(spec):
        if not FOUR_XX.search(CITE.sub(" ", ISSUE.sub(" ", c))):
            continue
        body = CODE.sub(" ", c)
        if (
            only_429(c)
            or ws_retryable(c)
            or LADDER_MARK.search(body)
            or not PROCESS.search(body)
        ):
            continue
        bad.append(
            f"a 4xx claim without the ruled marker contradicts the ruling: {c[:90]!r}"
        )
    return bad


ISSUE = re.compile(r"#\d+")
# a `re` word that is not a repeat: this spec's own vocabulary of nouns and non-repeat verbs
_RE_NOT_REPEAT = (
    r"ason|ference|cord|ad|view|ady|stor|quest|plac|fus|turn|duc|nder|gion|fs?\b|nko|gist"
    r"|lativ|tention|port|alis|aliz|st|sponse|siz|search|quir|al\b|wording|vert|vers|solv"
    r"|curren|cover|cogni|ceiv|ach|flow|pin|lat|lev|main|sult|ly|move|veal|lease|tain|serv"
    r"|cent|spect|gard|pair|build|comput|draw"
)
PROCESS = re.compile(
    rf"{ACT.pattern}|\bre-?(?!{_RE_NOT_REPEAT})[a-z]{{3,}}"
    r"|\bladders?\b|\brungs?\b|\bsteps?\b|\bintervals?\b|\bperiodic\w*|\bbackground\b"
    r"|\brounds?\b|\bknock\w*|\bhammer\w*|\btrigger\w*|\btransmit\w*|\bkeeps? \w+ing\b"
    # M-1r5: the backoff as one word, a pass through the ladder, a second chance, and a 4xx
    # treated as a 5xx is
    r"|\bbackoffs?\b|\bback-off\w*|\bgo(?:es|ing)? through\b|\bpass\w* through\b"
    r"|\bsecond (?:chance|attempt|try|round)\b|\bjoins?\b|\bfollows? the same\b"
    r"|\b(?:like|as|same as) (?:a |an |any )?(?:5xx|5\d\d|server[- ]errors?|transient)\b"
    r"|\b(?:treated|handled|dealt with|processed) (?:\w+ )?(?:like|as)\b"
    r"|\bnext (?:attempt|try|step|rung|round|tick|pass)\b|\buntil (?:it|they) (?:pass|succeed)\w*",
    re.IGNORECASE,
)
# the ruled marker on a 4xx claim: a negated retry ("no automatic retry", "without a retry"), or a
# conditional that names the harm ("would repeat a refusal"), or the 429s' "every other 4xx does not"
LADDER_MARK = re.compile(
    r"\b(?:no|never|not|without)\b(?:\s+[\w-]+){0,3}?\s+(?:automatic(?:ally)?\s+)?retr\w*"
    r"|\bretr\w* automatically would\b|\bevery other 4xx does not\b",
    re.IGNORECASE,
)


# BQ-11 as the orchestrator upheld it (2026-10-29): the WS refusals `23` marks retryable stay on
# the data-feed card and the transport's ladder runs for them (`23`:1626-1632). The allowed marker
# is the phrase "refusals `23` marks retryable"; it excuses a claim only when every code the claim
# names is one of the five and no HTTP 4xx is named beside them, by number, class or name. The
# refusal words are the subject itself, so they are cut before the 4xx lexicon is read (the
# conformance delta's MJ-1: the marker no longer excuses a bad request or a validation error)
WS_RETRYABLE = (
    "subscription_limit",
    "too_many_topics",
    "resync_rate_limited",
    "client_rate_limited",
    "slow_consumer",
)
WS_MARK = re.compile(r"\brefusals `23` marks retryable\b", re.IGNORECASE)


def ws_retryable(c: str) -> bool:
    if not WS_MARK.search(c) or re.search(r"\b4\d\d\b|\b4xx\b", CITE.sub(" ", c)):
        return False
    rest = re.sub(
        r"\brefus\w*", " ", CODE.sub(" ", WS_MARK.sub(" ", c)), flags=re.IGNORECASE
    )
    if re.search(rf"{_FOUR_XX_WORDS}|{_NAME_429}", rest, re.IGNORECASE):
        return False
    named = {x.strip("`") for x in CODE.findall(c)} - {"23"}
    return named <= set(WS_RETRYABLE)


def g_edge(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    sec = visible(section(spec, "6.3 "))
    bad = need(
        sec,
        (
            '"History begins off-view at {ts} ←" (W-27, new, PROPOSED)',
            "**not verifiable at the base**",
            "**Finding (heuristic):**",
            "(D08-A10)",
            "It yields to the loading band",
        ),
        "§6.3",
    )
    arow = next((r for r in arow_table(env) if r[0] == "D08-A10"), [])
    if not arow or "History begins off-view at {ts} ←" not in " ".join(arow):
        bad.append("the edge tag's catalogue-home A-row (D08-A10) is missing")
    return bad


def g_progress(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    sec = visible(section(spec, "7.1 "))
    bad = need(
        sec,
        (
            "**only when D08-G1's progress frame carries both prints done and prints total**",
            "**never a percentage or a time left**",
        ),
        "§7.1",
    )
    rows = {r[0]: r for r in table(sec)}
    known, unknown = rows.get("total-known", []), rows.get("total-unknown", [])
    if len(known) < 2 or "D08-G1" not in known[1]:
        bad.append("the determinate phase is not tied to D08-G1")
    words = deck(spec)
    if not unknown:
        bad.append("the total-unknown phase is missing")

    def shares(row: list[str]) -> list[str]:
        return [
            w
            for w in re.findall(r"W-\d+", row[4] if len(row) > 4 else "")
            for q in quotes(words.get(w, ["", "", ""])[2])
            if shows_progress(q)
        ]

    # M-1 of the orchestrator's round 1: bound per phase, not per string. A phase named `*-unknown`
    # shows no share and no time left; any other phase whose strings show one is total-known only
    # (its When names D08-G1) and has its `-unknown` twin, the ruled default with the elapsed time
    for name, r in rows.items():
        if name.endswith("unknown"):
            bad += [
                f"{w} shows a percentage or a time left in {name}" for w in shares(r)
            ]
            # the conformance delta's MJ-2: the phase's own Shows cell is read too, with the
            # ruled marker and the elapsed figure cut, by the gate's full PCT and LEFT lexicons
            shows = r[2] if len(r) > 2 else ""
            if not progress_ruled(shows) or shows_progress(
                PROGRESS_RULED.sub(" ", shows)
            ):
                bad.append(
                    f"the {name} phase's Shows cell shows a percentage or a time left"
                )
        elif name != "total-known" and shares(r):
            if len(r) < 2 or "D08-G1" not in r[1]:
                bad.append(f"{name} shows a percentage without tying it to D08-G1")
            if f"{name}-unknown" not in rows:
                bad.append(f"{name} shows a percentage and has no {name}-unknown form")
    bad += contra(spec, NO_TOTAL, PCT, what="a percentage or a time left with no total")
    # subject deny (M-1r3): a claim about what an unknown-total build shows carries the ruled marker
    # or names counts done only; anything else it says it shows is denied, however worded
    bad += deny(
        spec,
        NO_TOTAL,
        SHOWS,
        progress_ruled,
        "an unknown-total claim without the ruled marker",
    )
    return bad


_UNKNOWN = (
    r"(?:unknown|undetermined|indeterminate|unavailable|missing|absent|unset"
    r"|not (?:yet )?(?:known|available|determined)|cannot be (?:known|determined|computed)"
    r"|can't be (?:known|determined))"
)
# the total by any name (M-1r5): the total, the end or print count, the size or number of prints
_TOTAL = (
    r"(?:total|(?:end|final|print|prints?) count|count of prints|size|number of prints"
    r"|prints? to come|how many prints)"
)
NO_TOTAL = re.compile(
    rf"\bno (?:known )?{_TOTAL}\b|\bwithout (?:a|an|the|any)(?: [\w-]+){{0,2}} {_TOTAL}\b"
    r"|\b(?:lack\w*|wanting|short of|minus|missing|absen\w*|before|until|pending|unknown|no sign)"
    rf"(?: [\w-]+){{0,3}} {_TOTAL}\b"
    rf"|\b{_TOTAL}[- ]unknown\b|\b(?:unknown|undetermined|indeterminate|missing|absent) {_TOTAL}\b"
    rf"|\b{_TOTAL}\b(?: [\w-]+){{0,4}}? {_UNKNOWN}\b"
    # the phase named for it: "the indeterminate phase", "the unknown-total state"
    r"|\b(?:indeterminate|unknown-total|total-unknown)(?: [\w-]+){0,1} (?:phase|state|mode|stage"
    r"|stretch|period)\b",
    re.IGNORECASE,
)
# a progress figure: a share, a time left, or any time or count figure other than a phase start
PCT = re.compile(
    r"percent|%|\b(?:time|seconds?|minutes?|hours?) (?:left|to go)\b|\btime to\b|\bremaining\b|\bETA\b|\bestimated time\b"
    r"|\bshare of\b|\bfraction\b|\bproportion\b|\bratio\b|\bfills?\b|\bcomplet(?:e|ion)\b"
    r"|\bfinish\w*|\bdone by\b|\bend(?:ing)? time\b|\bwhen\b[^.;]{0,30}\bwill (?:end|finish|be done)\b"
    r"|(?<!from )(?<!after )\b\d+(?:\.\d+)?\s?(?:ms|s|secs?|seconds?|min|minutes?)\b"
    # the delta's MJ-2: a share as a fraction in words, and a time to go without a unit
    r"|\bto go\b|\bof the way\b|\b(?:halves|thirds|quarters|fifths|sixths|eighths|tenths)\b"
    r"|\b(?:a|one|two|three|four) (?:half|third|quarter|fifth|tenth)\b|\bhalf(?:way| done| built)\b",
    re.IGNORECASE,
)


# the ruled elapsed figure ("2 min 10 s elapsed", "0:14 elapsed", "after {2 min 10 s}"): cut
# before a deck string or a Shows cell is read for a share or a time left (the delta's MJ-2)
ELAPSED_FIG = re.compile(
    r"\bafter \{?(?:\d+ min )?\d+ (?:min|s)\b\}?(?: elapsed\b)?"
    r"|\b(?:\d+ min )?\d+ (?:min|s) elapsed\b|\b\d+:\d\d elapsed\b",
    re.IGNORECASE,
)


def shows_progress(q: str) -> bool:
    t = ELAPSED_FIG.sub(" ", q)
    return bool(PCT.search(t) or LEFT.search(t))


# what a claim says the strip shows: any display or content verb makes it a claim, not a label
SHOWS = re.compile(
    r"\b(?:show\w*|shown|display\w*|read\w*|carr\w*|fill\w*|estimat\w*|count\w*|give\w*|gets?"
    r"|present\w*|tell\w*|say\w*|report\w*|render\w*|draw\w*|indicat\w*|state\w*|label\w*"
    r"|includ\w*|offer\w*|add\w*|put\w*|print\w*|reveal\w*|expos\w*|surfac\w*|is|are|has|have"
    r"|becomes?|turns?|switch\w*|let\w*|lets?|project\w*|predict\w*|forecast\w*|guess\w*"
    r"|extrapolat\w*|foresee\w*|anticipat\w*)\b",
    re.IGNORECASE,
)
# the ruled marker (BQ-19: "never a percentage or a time left") and its negated forms
PROGRESS_RULED = re.compile(
    r"\bnever a percentage or a time left\b|\bno percentage(?:,| and| or) no time left\b"
    r"|\b(?:never|no)\b(?: [\w-]+){0,3} percentage\b",
    re.IGNORECASE,
)
# counts done only: the elapsed time or the prints done, with no figure PCT reads as progress
COUNTS_DONE = re.compile(r"\belapsed\b|\bprints done\b", re.IGNORECASE)


def progress_ruled(c: str) -> bool:
    if PROGRESS_RULED.search(c):
        return True
    return bool(COUNTS_DONE.search(c)) and not PCT.search(c) and not LEFT.search(c)


LEFT = re.compile(
    r"\bleft\b|\bremain\w*|\bhow (?:much|long|far)\b|\bto go\b|\brest of\b"
    r"|\buntil (?:done|the end)\b",
    re.IGNORECASE,
)


def g_cancel(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    bad = need(
        section(spec, "8.1 "),
        (
            (
                "Cancel is a CMP-001 `ghost` button on the strip from the moment the strip appears, "
                "600 ms, and `Esc` cancels from 0 ms"
            ),
            "**Cancel is never CMP-038's:**",
        ),
        "§8.1",
    )
    bad += need(section(spec, "8.2 "), ("D02:270's form",), "§8.2")
    bad += need(section(spec, "8.3 "), ("(D08-C12)",), "§8.3")
    crows = {r[0] for r in table(visible(section(spec, "15.2 ")))}
    arows = {r[0] for r in arow_table(env)}
    bad += [f"{c} missing" for c in ("D08-C10", "D08-C11", "D08-C12") if c not in crows]
    bad += [f"{a} missing" for a in ("D08-A6", "D08-A7", "D08-A8") if a not in arows]
    bad += contra(
        spec,
        FOCUS_TO_TRIGGER,
        allow=lambda c: "D08-C12" in c,
        what="focus to the trigger",
    )
    bad += contra(spec, ESC_DISMISS, what="`Esc` dismissing the outcome")
    bad += contra(spec, CANCEL_LATE, allow=cancel_ruled, what="a late Cancel")
    # subject deny (M-1r3): when Cancel appears, focus after Cancel and `Esc` are ruled subjects; a
    # claim on any of them carries the ruled marker or FAILs, negated or not
    bad += deny(
        spec, CANCEL_WHEN, CANCEL_WHEN, cancel_when_ok, "a Cancel timing off the ruling"
    )
    # M-1r4: the subject is Cancel itself: in §7 and §8, where the strip's Cancel is ruled, any
    # claim naming Cancel carries the ruled marker, whatever it says about when
    for c in claims_in(spec, ("7. ", "8. ")):
        if CANCEL_WORD.search(c) and not cancel_when_ok(c):
            bad.append(
                f"a Cancel claim off the ruling contradicts the ruling: {c[:90]!r}"
            )
    bad += deny(spec, FOCUS_WORD, FOCUS_CTX, focus_ok, "a focus claim off the ruling")
    bad += deny(spec, ESC_WORD, ESC_WORD, esc_ok, "an `Esc` claim off the ruling")
    return bad


# when Cancel appears: Cancel, then (same clause, no bracket) a timing or appearance word
CANCEL_WHEN = re.compile(
    r"\bCancel\w*`?[^.;()]{0,40}?\b(?:appear\w*|show\w*|shown|visib\w*|reveal\w*|held|hold\w*"
    r"|wait\w*|delay\w*|brief\w*|later|soon|immediate\w*|after|before|from|until|once|when"
    r"|turn\w* up|pops?\b|popp\w*|time\w*|moment|second\w*|withheld|kept back|comes?|arriv\w*"
    r"|\d+(?:\.\d+)?\s?(?:ms|s)\b)",
    re.IGNORECASE,
)
CANCEL_MARK = re.compile(
    r"from the moment the strip appears|\bfrom 600 ms\b|strip's first moment|\bthroughout\b"
    r"|\bstays\b|until the build ends|\bD-5\b|\bD-11\b|D02:29|CMP-038|\bno `?Cancel\b|\bTab\b"
    r"|`?Esc`? cancels from 0 ms",
)


# M-1r5: the control in any form (Cancel, Cancelling, Cancellation, a cancel button) and by
# another name (stop, abort, halt). The lowercase verb is an act, not the control ("`Esc` cancels",
# "a disconnect cancels the build", "may cancel"); CANCEL_WHEN and CANCEL_LATE read it in any case
CANCEL_WORD = re.compile(
    r"\bCancel\b|(?i:\bcancel(?:l?ing|l?ation)\b|\bcancel (?:control|button|action|link)\b"
    r"|\babort\w*|\bhalt\w*|\bstop (?:control|button|action|link)\b)",
)


def claims_in(spec: str, prefixes: tuple[str, ...]) -> list[str]:
    """The claims of the sections `prefixes` open, read as claims() reads the whole spec."""
    keep = {c for p in prefixes for c in claims("## " + p + "x\n" + section(spec, p))}
    return [c for c in claims(spec) if c in keep]


def cancel_when_ok(c: str) -> bool:
    return bool(CANCEL_MARK.search(c))


# focus after Cancel or a build: the ruled destinations are D-11's and F-BAR-3's
# M-1r4: the keyboard position by any name: focus, the cursor or the caret ("plot cursor" is a
# ruled destination, FOCUS_MARK)
FOCUS_WORD = re.compile(
    r"\bfocus\w*|\bcursor\b|\bcaret\b|\bkeyboard (?:attention|position|point|place)\b"
    r"|\bactive element\b|\btab (?:position|stop|order position|place)\b|\bselection point\b",
    re.IGNORECASE,
)
FOCUS_CTX = re.compile(
    r"\bCancel\b|\bcancel\w*|\brebuil\w*|\bbuild\b|\bcompletion\b|\btrigger\b|\bbutton\b"
    r"|\bpill\b",
    re.IGNORECASE,
)
FOCUS_MARK = re.compile(
    r"\bplot cursor\b|\bnever moves focus\b|\bnever returns\b|\bD-11\b|\bD08-C12\b|→ §8\b",
)


def focus_ok(c: str) -> bool:
    return bool(FOCUS_MARK.search(c))


# `Esc`: it cancels, from 0 ms, in D-11's order; on SCR-048 it goes to the view switch
# M-1r5: any case, and "the Escape key"
ESC_WORD = re.compile(r"\bEsc(?:ape)?\b(?: key)?", re.IGNORECASE)
ESC_MARK = re.compile(
    r"\bEsc(?:ape)?`?(?: key)? cancels\b|`?Esc`? from 0 ms|\bD-11\b|\bD-5\b|\bview switch\b"
    r"|\bnever dismisses\b",
    re.IGNORECASE,
)


def esc_ok(c: str) -> bool:
    return bool(ESC_MARK.search(c))


_TARGET = r"(?:the )?(?:[`\w'-]+ ){0,3}?(?:control|trigger|button|field|pill|editor|interval|picker|menu)\b"
_PUT = r"(?:moved|returned|sent|placed|put|set|given|handed|parked)"
FOCUS_TO_TRIGGER = re.compile(
    rf"\bfocus (?:returns|moves|goes|is {_PUT}|gets {_PUT}|{_PUT}|lands|jumps|snaps)(?: back)?"
    rf" (?:to|on|onto|in|into) {_TARGET}"
    rf"|\b(?:returns|moves|sends|places|puts|sets|gives|parks) (?:the )?focus (?:back )?"
    rf"(?:to|on|onto|in|into) {_TARGET}",
    re.IGNORECASE,
)
_SPAN = r"(?:(?!\b(?:never|not|no|nor)\b)[^.;])"  # a span that holds no negation
# default-deny: `Esc` with any verb before the outcome noun is a claim about the outcome
ESC_DISMISS = re.compile(
    rf"\bEsc(?:ape)?\b{_SPAN}{{0,60}}\bdismiss\w*"
    rf"|\bEsc(?:ape)?\b{_SPAN}{{0,60}}\b(?:outcome|notice|message)\b"
    rf"|\bEsc(?:ape)?\b{_SPAN}{{0,30}}\b(?:clos|clear|hid|remov)\w*{_SPAN}{{0,25}}\bline\b",
    re.IGNORECASE,
)
# default-deny: any duration or delay word near Cancel, either side, is a timed Cancel unless it
# is the ruled 600 ms (cancel_ruled) or a cite of D-5's original clause
_DUR = (
    r"(?:\b\d+(?:\.\d+)?\s?(?:ms|milliseconds?|s|secs?|seconds?)\b"
    r"|\b(?:one|two|three|four|five|a few|several|half a) (?:milli)?seconds?\b"
    r"|\ba (?:second|moment|beat|short (?:delay|pause|while))\b|\bdelay(?:ed|s)?\b|\blater\b)"
)
CANCEL_LATE = re.compile(
    rf"\bCancel\w*{_SPAN}{{0,50}}\b(?:only )?(?:after|once|when) (?:the )?(?:progress )?bar\b"
    rf"|\bCancel\w*{_SPAN}{{0,30}}\bonly (?:after|once|when|from)\b"
    rf"|\bCancel\w*{_SPAN}{{0,50}}{_DUR}|{_DUR}{_SPAN}{{0,40}}\bCancel\w*",
    re.IGNORECASE,
)
# the ruled figures (RULED cancel.ms, esc.ms) and how the spec words them
RULED_CANCEL = re.compile(
    r"from the moment the strip appears, 600 ms|\bCancel`? from 600 ms|`?Esc`?(?: cancels)? from 0 ms",
    re.IGNORECASE,
)


def cancel_ruled(c: str) -> bool:
    """A Cancel claim whose only figures are the ruled ones, or a cite of D-5 as written."""
    if "D-5" in c or "D02:29" in c:
        return True
    return not CANCEL_LATE.search(RULED_CANCEL.sub(" ", c))


def wins_of(env: Env, n: int) -> str:
    line = base_line(env, "14", n) or ""
    cells = split_row(line) if line.startswith("|") else []
    return nfkc(cells[1]).lower() if len(cells) > 1 else ""


def g_matrix(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    rows = table(visible(section(spec, "9.1 ")))
    bad: list[str] = []
    four = [r for r in rows if "four-way" in r[0]]
    if len(four) != 1:
        bad.append("the four-way row is missing")
    else:
        named = [
            s
            for s in ("rebuilding", "partial-history", "stale", "lod")
            if s in four[0][1].lower()
        ]
        if len(named) != 1 or "(strip)" not in four[0][1]:
            bad.append(f"the four-way row names {named} as primary, ruled exactly one")
    for r in rows:
        refs = [int(n) for d, n in cites(r[3]) if d == "14"] if len(r) > 3 else []
        if len(refs) != 1 or not 743 <= refs[0] <= 762:
            bad.append(f"{r[0]!r} cites {refs}, not one `14` line of 743-762 (BQ-22)")
            continue
        n, wins, other = refs[0], nfkc(r[1]).lower(), nfkc(r[2]).lower()
        line = nfkc(base_line(env, "14", n) or "").lower()
        if 748 <= n <= 758 and wins != wins_of(env, n):
            bad.append(f"{r[0]!r} wins {r[1]!r}, `14`:{n} says {wins_of(env, n)!r}")
        elif n == 760 and wins != "both shown":
            bad.append(f"{r[0]!r} must read 'both shown' (`14`:760)")
        elif n == 743 and not wins.startswith(line.split("shows one line: ")[-1][:10]):
            bad.append(f"{r[0]!r}: `14`:743's first strip state is not its primary")
        elif n == 762:
            # `14`:762, the E08 line: disconnected wins and cancels the build; stale marks text
            if "disconnected" in r[0]:
                ok = (
                    "disconnected and reconnecting win" in line
                    and wins.startswith("disconnected")
                    and "cancelled" in other
                    and "previous series stays" in other
                )
            elif "stale" in r[0]:
                ok = "a stale feed marks the forming bar stale in text" in line and (
                    "stale" in other and "forming bar" in other
                )
            else:
                ok = False
            if not ok:
                bad.append(f"{r[0]!r} does not carry `14`:762's reading")
    return bad


def g_owner(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    row = next(
        (r for r in table(visible(section(spec, "15.4 "))) if r[0] == "D08-Q1"), []
    )
    text = nfkc(" ".join(row))
    want = (OWNER_PENDING, "#395", "#451", "#450", RULED_VALUES["RULED:waiver.target"])
    bad = [f"D08-Q1 lacks {w!r}" for w in want if nfkc(w) not in text]
    if "**Alternative reading:**" not in " ".join(row):
        bad.append("D08-Q1 lacks the alternative reading")
    return bad


def g_heuristic(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    bad = [
        f"{r[0]} has no (heuristic) mark"
        for r in table(visible(section(spec, "17.3 ")))
        if len(r) > 2 and "(heuristic)" not in r[2]
    ]
    bad += need(
        section(spec, "1.2 "),
        ("an agent lens run with the `22-exchange-adapter` rule set",),
        "§1.2",
    )
    bad += need(section(spec, "12.2 "), ("**Finding H-1 (heuristic):**",), "§12.2")
    return bad


def g_ledger(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    sec = visible(section(spec, "15.3 "))
    rows = table(sec)
    bad: list[str] = []
    ids = [r[0] for r in rows]
    if ids != ["D08-G1", "D08-G2", "D08-G3", "D08-G4"]:
        bad.append(f"the G-ledger rows are {ids}, ruled D08-G1 ... D08-G4")
    for r in rows:
        if len(r) < 5:
            continue
        if re.search(r"\bagent\b", r[2], re.IGNORECASE):
            bad.append(f"{r[0]}'s owner lane names an agent")
        consumer = re.search(r"E12-[A-Z]\d\d", r[3])
        if not consumer or vals.get(f"DATE:{consumer[0]}") not in r[4]:
            bad.append(f"{r[0]}'s due date is not its consumer's sprint start")
    bad += need(sec, tuple(f"{c}" for c in CARRIED), "§15.3 carried")
    return bad


def g_risk(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    row = next(
        (r for r in table(visible(section(spec, "15.2 "))) if r[0] == "D08-C17"), []
    )
    bad = (
        []
        if row and "R7" in row[1] and "R8" in row[1]
        else ["the R7 / R8 C-row is missing"]
    )
    if any(d == "32" for d, _ in cites(spec)):
        bad.append("`32` is cited for the rule (rider (c) forbids it)")
    return bad


def g_dryrun(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    rows = table(visible(section(spec, "16. ")))
    bad: list[str] = []
    roles = " ".join(r[1] for r in rows if len(r) > 1)
    bad += [f"no dry-run row for {c}" for c in CONSUMERS if c not in roles]
    for role in ("frontend:", "QA:"):
        if role not in roles:
            bad.append(f"no {role} pass")
    for r in rows:
        if len(r) < 7:
            continue
        try:
            needs, found, missing = int(r[2]), int(r[3]), int(r[4])
        except ValueError:
            bad.append(f"{r[1]}: counts are not numbers")
            continue
        if needs != found + missing:
            bad.append(f"{r[1]}: {needs} needs != {found} found + {missing} not found")
        key = re.search(r"E12-([SQD]\d\d)", r[1])
        items = dry_items(spec).get(key[1] if key else "", [])
        marked = sum(1 for x in items if NOT_FOUND in x)
        if (needs, missing) != (len(items), marked):
            bad.append(
                f"{r[1]}: the row says {needs} / {missing}, the itemised list {len(items)} / {marked}"
            )
        if missing and (r[5] in ("", "—") or r[6] in ("", "—")):
            bad.append(f"{r[1]}: a 'not found' with no synonym search or disposition")
    walk = re.findall(r"^\d+\. ", section(spec, "17.4 "), re.MULTILINE)
    if len(walk) > MAX_WALK:
        bad.append(f"{len(walk)} walkthrough items, at most {MAX_WALK}")
    return bad


def g_unmerged(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    text = visible(spec)
    bad: list[str] = []
    for pr in UNMERGED:
        for m in re.finditer(re.escape(pr) + r"(?!\d)[^\n]{0,24}", text):
            if re.search(r"\b[0-9a-f]{10}\b|\"", m[0]):
                bad.append(f"{pr} carries a sha or a quote")
    version = visible(section(spec, "18.4 "))
    for key, pr in LATE_MERGED.items():
        if f"{vals.get('SHA:' + key, '?')} ({pr}" not in version:
            bad.append(f"the version line does not record {pr}'s merge sha (rider (e))")
    return bad


def g_t2(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    e09 = "\n".join(base_line(env, "E09-D09", n) or "" for n in range(89, 96))
    keys = set(re.findall(r"`(rbac\.[a-z_]+)`", e09))
    bad = [
        f"`{k}` is not an E09-D09 reason key"
        for k in sorted(set(re.findall(r"`(rbac\.[a-z_]+)`", visible(spec))) - keys)
    ]
    bad += need(
        section(spec, "10.4 "),
        (
            '`aria-disabled="true"`, never the `disabled` attribute',
            "CMP-079 RbacGate",
            "the CMP-019 `lock` glyph",
            "linked by `aria-describedby`",
            "never `color.text.disabled` and never `opacity.disabled`",
            "**its full label**",
        ),
        "§10.4",
    )
    bad += deny(
        spec, GATED, ROLE_OR_SEEN, t2_marked, "a §10.4 control not stated as T2"
    )
    # subject deny (M-1r3): a claim naming a §10.4 control, or its stem, says T2 (2a, aria-disabled,
    # never hidden, presentational) or is a pure action or destination statement: no role but the
    # Owner's, no word of seeing, hiding or existing
    bad += deny(
        spec,
        T2_STEM,
        T2_STEM,
        lambda c: t2_marked(c) or pure_action(c),
        "a §10.4 control stated off T2",
    )
    return bad


# stems tolerate a hyphen, a missing space and a singular (M-1r4): "Volume-75", "earlier-bars",
# "the diagnostic panel"
# M-1r5: and each control by a synonym the lexicon names (troubleshooting or debug panel, Vol 75,
# older, prior or back history); the subject is still found by this lexicon (§14 G-T2)
T2_STEM = re.compile(
    r"\bdiagnostics?\b|\btroubleshoot\w*|\bdebug\w*|\bVol(?:ume|\.)?[- ]?75\b"
    r"|\b(?:earlier|older|prior|previous|back)[- ](?:bars?|history|histories)\b",
    re.IGNORECASE,
)
EXIST = re.compile(
    r"\bexist\w*|\bthere\b|\bpresent\b|\bonly\b(?! exits\b)|\breserved\b|\bprivileg\w*"
    r"|\blimited to\b|\bno ?(?:one|body)\b|\bavailab\w*|\bunavailab\w*|\bgon(?:e|ne)\b"
    r"|\bdisappear\w*|\bvanish\w*|\bexclu\w*|\bwithheld\b|\bkept from\b|\bstripp\w*"
    r"|\bdisabl\w*|\bgrey\w*|\bgray\w*|\bfaded\b|\bdimm\w*|\boffered\b",
    re.IGNORECASE,
)


# the one way a pure action names a role: what the control does, "for the Owner"
OWNER_ACTION = re.compile(
    r"\b(?:opens?|goes|leads?|links?|pans?|starts?|builds?|retries|loads?)\b[^.;]{0,40}?"
    r"\bfor the Owner\b",
    re.IGNORECASE,
)
OWNER_WORD = re.compile(r"\bowner\w*", re.IGNORECASE)


def pure_action(c: str) -> bool:
    rest = OWNER_ACTION.sub(" ", c)
    return not (
        ROLE.search(rest)
        or OWNER_WORD.search(rest)
        or SEEN.search(rest)
        or EXIST.search(rest)
    )


# §10.4's gated controls are never hidden (E09-D09:44; `14`:85): T2 2a, or the sentence form
# default-deny: a claim naming one beside a role or a visibility word FAILs unless it says T2
GATED = re.compile(r"`?\b(?:Open diagnostics|Retry Volume 75|Build earlier bars)\b`?")

LEAK = re.compile(
    r"approximat|unfortunately|sorry|apolog|https?:|\bSELECT\b|stack trace|ret_msg|\.com\b"
    r"|account id|session token",
    re.IGNORECASE,
)


def g_copy(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    bad: list[str] = []
    for w, r in deck(spec).items():
        src, strings = r[3], quotes(r[2])
        if not strings:
            bad.append(f"{w} has no quoted string")
        for q in strings:
            if LEAK.search(q):
                bad.append(
                    f"{w} leaks an internal or offers an approximate path: {q!r}"
                )
        if src.startswith("new"):
            if "PROPOSED" not in src:
                bad.append(f"{w} is new and not marked PROPOSED")
            continue
        m = re.match(r"(`\d\d`|[A-Z0-9-]+):(\d+) (verbatim|form)$", src)
        if not m:
            bad.append(f"{w}'s source {src!r} is not 'DOC:line verbatim|form' or new")
            continue
        line = strip_md(base_line(env, m[1].strip("`"), int(m[2])) or "")
        for q in strings:
            ok = nfkc(q) in line if m[3] == "verbatim" else form(q) in form(line)
            if not ok:
                bad.append(f"{w} {q!r} is not {m[3]} on {m[1]}:{m[2]} at the base")
    return bad


def arow_table(env: Env) -> list[list[str]]:
    """The hand-off's §C table: the copy-ready A-rows (RULED BQ-3)."""
    return table(visible(section(env.handoff, "§C ")))


def g_arows(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    bad: list[str] = []
    for r in arow_table(env):
        if len(r) < 5 or r[3] == "—":
            continue
        refs = cites(r[1])
        if not refs:
            bad.append(f"{r[0]}'s target has no cite")
            continue
        line = base_line(env, refs[0][0], refs[0][1]) or ""
        if nfkc(r[3]) not in nfkc(line):
            bad.append(f"{r[0]}'s Old is not verbatim on its target at the base")
    return bad


def g_contrast(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    bad: list[str] = []
    for r in contrast_rows(spec):
        if len(r) < 7:
            continue
        floor = FLOORS.get(r[3])
        if floor is None:
            bad.append(f"{r[0]}: kind {r[3]!r} is neither text nor non-text")
            continue
        for th in THEMES:
            v = vals.get(f"CONTRAST:{r[0]}.{th}", "?")
            if v == "?" or float(v) < floor:
                bad.append(f"{r[0]} {th}: {v}:1 under the {r[3]} floor {floor}:1")
    return bad


ROLE = re.compile(
    r"\b(?:managers?|viewers?|non-?owners?|(?:every|any) other role|other roles?"
    r"|roles? other than|every role but|(?:any|every)(?:one|body)? (?:but|except|other than)"
    r"|(?:who|that) (?:is|are)(?: not|n't) (?:the|an?) owner|not the owner|other than the owner"
    r"|except the owner|(?:any|every|no|some)(?:one|body) else|guests?|read-only users?"
    r"|the others|others"
    # M-1r5: every role at once is a non-owner too
    r"|every (?:role|seat|user)|all (?:roles|seats|users)|(?:any|every) (?:signed-in )?user"
    r"|any(?:one|body)|every(?:one|body)|signed-in users?)\b",
    re.IGNORECASE,
)
SEEN = re.compile(
    r"\b(?:see|sees|seen|saw|shown|shows?|showing|visib\w*|invisib\w*|hid(?:den|e|es|ing)"
    r"|suppress\w*|left out|leav\w* out|omit\w*|remov\w*|dropp?\w*|display\w*|draw\w*"
    r"|render\w*|offered|appear\w*|absent|missing|greyed|grayed|dimmed|menu|available)\b",
    re.IGNORECASE,
)
ROLE_OR_SEEN = re.compile(f"{ROLE.pattern}|{SEEN.pattern}", re.IGNORECASE)
T2_MARK = re.compile(
    r"\bT2\b|\b2a\b|aria-disabled|\b(?:never|not) hidden\b|\bpresentational\b",
    re.IGNORECASE,
)


def t2_marked(c: str) -> bool:
    return bool(T2_MARK.search(c))


CTA = re.compile(
    r"`Record this symbol`|\bRecord this symbol\b|\b(?:the|a|its|that|this) (?:\w+ )?CTA\b"
    r"|\brecord(?:ing)? (?:button|control|action|CTA|link)\b"
    r"|\brecord\w*|\bbuttons?\b|\bCTAs?\b|\bcaptur\w*",
    re.IGNORECASE,
)
LOCK = re.compile(r"\b(?:pad)?lock(?:ed)?\b", re.IGNORECASE)
SENTENCE_FORM = re.compile(r"\bsentence form\b", re.IGNORECASE)


# the ticket's AC1, verbatim, and a pointer into §2.3 (where the sentence form is ruled) are not
# claims about what a non-owner sees; everything else must say "sentence form"
AC1_VERBATIM = "the owner CTA variant and the manager or viewer variant"


def role_ok(c: str) -> bool:
    if SENTENCE_FORM.search(c) or "presentational" in c:
        return True
    return AC1_VERBATIM in c or bool(re.search(r"→ §2\.3\b", c))


def g_role(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    """S-10: a role-gated CTA is never drawn for a non-owner; a sentence form has no lock."""
    bad = deny(
        spec,
        CTA,
        ROLE,
        role_ok,
        "a role-gated CTA for a non-owner",
    )
    bad += contra(spec, LOCK, SENTENCE_FORM, what="a lock on a sentence form")
    bad += need(
        section(spec, "2.3 "),
        ("The sentence form has no button and no lock glyph",),
        "§2.3",
    )
    return bad


REF_SOURCES = (
    "`Problem.instance`",
    "the `X-Correlation-Id` response header",
    "a WS `err` frame's `request_id`",
    "a client-minted `urn:cv:ui:{uuid4}`",
)
REF_WORD = re.compile(r"\breference\b|\bcorrelation[ -]?id\b|urn:cv:ui:", re.IGNORECASE)
REF_DATA = re.compile(
    r"\b(?:account|symbol|user|session|timestamp|time|hash|email|order|price|position)\b",
    re.IGNORECASE,
)
REF_VERB = re.compile(
    r"\b(?:buil\w*|deriv\w*|made|mak\w*|compos\w*|contain\w*|includ\w*|hold\w*|carr\w*"
    r"|encod\w*|embed\w*|mint\w* from|form\w* from|plus|join\w*|concat\w*|combin\w*"
    r"|equals?|(?:is|are) (?:just |simply )?(?:the|an?) (?:[\w-]+ ){0,2}(?:ids?|symbols?|times?"
    r"|timestamps?|hash|emails?|names?))\b",
    re.IGNORECASE,
)


def g_ref(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    """BQ-15: the reference comes from the four sources, in order, and from nothing else."""
    sec = nfkc(visible(section(spec, "4.2 ")))
    order = next((x for x in sentences(sec) if x.startswith("Source order:")), "")
    bad = [
        f"§4.2: the source {src!r} is missing"
        for src in REF_SOURCES
        if src not in order
    ]
    pos = [order.find(src) for src in REF_SOURCES]
    if all(p >= 0 for p in pos) and pos != sorted(pos):
        bad.append("§4.2: the four sources are out of order")
    if order.count("; else ") != 3:
        bad.append(f"§4.2: {order.count('; else ') + 1} sources, ruled four")
    bad += need(
        section(spec, "4.2 "), ("**The reference is opaque by construction:**",), "§4.2"
    )
    bad += contra(
        spec,
        REF_WORD,
        REF_DATA,
        lambda c: not REF_VERB.search(c),
        "a reference built from data",
    )
    return bad


HZ = re.compile(r"(\d+(?:\.\d+)?)\s?Hz\b")
PERIOD = re.compile(
    r"\b(?:every|per|each|once (?:a|per|every))\s+(\d+(?:\.\d+)?)\s?"
    r"(ms|milliseconds?|s|secs?|seconds?)\b",
    re.IGNORECASE,
)
PER_SECOND = re.compile(r"\b([\w-]+) times (?:a|per|each) second\b", re.IGNORECASE)
SLOW = {"once", "twice", "one", "two", "three", "four", "1", "2", "3", "4"}
PER_EVENT = re.compile(
    r"\b(?:updat\w*|refresh\w*|announc\w*|redraw\w*|tick\w*)\b"
    r"(?:(?!\b(?:never|not|no|nor)\b)[^.;]){0,40}"
    r"\b(?:per|every|each|on each|on every) (?:animation )?(?:frame|tick|print|message|delta)\b",
    re.IGNORECASE,
)
PER_FRAME = re.compile(
    r"\brequestAnimationFrame\b|\brAF\b|\b(?:each|every|per) (?:repaint|paint|vsync)\b"
    r"|\bscreen refresh\b",
    re.IGNORECASE,
)
FPS = re.compile(r"(\d+(?:\.\d+)?)\s?(?:fps|frames? (?:a|per) second)\b", re.IGNORECASE)


def g_cadence(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    """T Perf: no progress or text update above 4 Hz, in figures or in words."""
    text = visible(spec)
    for head in SKIP_CLAIMS:
        body = section(text, head)
        if body:
            text = text.replace(body, "")
    bad = [
        f"a cadence of {m[0]} is above 4 Hz"
        for m in HZ.finditer(text)
        if float(m[1]) > 4
    ]
    bad += [
        f"a cadence {m[0]!r} is above 4 Hz"
        for m in PER_SECOND.finditer(text)
        if m[1].lower() not in SLOW
    ]
    bad += [
        f"a cadence of {m[0]} is above 4 Hz"
        for m in FPS.finditer(text)
        if float(m[1]) > 4
    ]
    # M-1r4: a period is a cadence too: "every 100 ms" is 10 Hz
    for m in PERIOD.finditer(text):
        ms = float(m[1]) * (1 if m[2].lower().startswith("m") else 1000)
        if ms > 0 and 1000 / ms > 4:
            bad.append(f"a cadence of {m[0]!r} ({1000 / ms:g} Hz) is above 4 Hz")
    bad += contra(spec, PER_EVENT, what="an update per event")
    bad += contra(spec, PER_FRAME, what="an update per animation frame")
    # subject deny (M-1r3): a claim that a counter, the progress or the strip's text updates carries
    # the ruled cadence (a figure in Hz, at most four times a second) or FAILs, however worded;
    # "redraw" is left out: in this spec it is the boards' word ("cited, never redrawn"), and a
    # redraw per frame is PER_FRAME's
    bad += deny(
        spec, UPDATE_VERB, COUNTER_NOUN, cadence_ok, "a counter update off the cadence"
    )
    return bad


UPDATE_VERB = re.compile(
    r"\b(?:updat\w*|tick(?:s|ed|ing)?|repaint\w*|re-paint\w*|re-?render\w*|refresh\w*|increment\w*"
    r"|advanc\w*|continuous\w*|constant\w*|animat\w*|count(?:s|ed|ing)? up|climb\w*"
    r"|roll\w* (?:up|on)"
    r"|keeps? (?:changing|moving|counting)|(?<!late )(?<!merged )(?<!\ba )(?<!\bthe )(?<!\bno )chang(?:e|es|ed|ing)"
    r"|mov(?:e|es|ed|ing) (?:with|as|on|in step)"
    r"|(?:kept|keeps?|stays?) (?:current|up to date|in step))\b"
    # M-1r5: tracking, mirroring, rewriting, following and keeping pace are updates too
    # ("live" is left out: here it is the live-data sentence and a live neighbour panel; a claim
    # that a counter is live says how it moves, and the words above read that)
    r"|\b(?:track(?:s|ed|ing)?|mirror(?:s|ed|ing)|rewrit\w*|re-writ\w*|keeps? pace|kept pace"
    r"|follow(?:s|ed|ing)? (?:each|every|the (?:feed|stream))|in lockstep)\b",
    re.IGNORECASE,
)
COUNTER_NOUN = re.compile(
    r"\b(?:counter|count|countdown|progress|figures?|numbers?|text|bar|strip|readout|percentage"
    r"|elapsed|prints)\b",
    re.IGNORECASE,
)
CADENCE_MARK = re.compile(
    r"(?<![\d.])[0-4](?:\.\d+)? ?Hz\b|≤ ?[0-4] ?Hz|\bat most (?:4|four|2|two) times a second\b"
    r"|\btwice a second\b|\bonce a second\b",
    re.IGNORECASE,
)


def cadence_ok(c: str) -> bool:
    return bool(CADENCE_MARK.search(c))


APPROX = re.compile(
    r"approximat\w*|\bestimated? (?:bars?|series|candles?|bricks?)\b|\bsynthe\w* (?:bars?|series)"
    r"|\bbuil\w* (?:non-time )?bars? from klines\b",
    re.IGNORECASE,
)


def g_approx(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    """BQ-28: never approximate, in prose, in a table and in every action label."""
    bad = [
        f"{row[:30]!r} offers an approximate path: {cell[:50]!r}"
        for row, cell in actions(spec)
        if re.search(r"approximat|estimat", cell, re.IGNORECASE)
    ]
    bad += contra(spec, APPROX, what="an approximate path")
    bad += need(section(spec, "1.4 "), ("**R-1 Never approximate (BQ-28).**",), "§1.4")
    return bad


def g_frames(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    """R4: the frame register reconciles with §0's boards and with the state tables."""
    boards = {r[0] for r in table(visible(section(spec, "0. ")))}
    reg = table(visible(section(spec, "0.1 ")))
    bad: list[str] = [] if reg else ["§0.1: the frame register is missing"]
    drawn = " ".join(
        r[0] for r in reg if len(r) > 2 and not r[2].startswith("specified")
    )
    used: set[str] = set()
    for r in reg:
        if len(r) < 3:
            continue
        if r[2].startswith("specified"):
            if r[2] != "specified (drawn on request)":
                bad.append(f"{r[0][:40]!r}: {r[2]!r}")
            continue
        nums = re.findall(r"\b\d\d\b", r[2])
        if not nums or not re.fullmatch(
            r"(?:inset on )?\d\d(?:; (?:inset on )?\d\d)*", r[2]
        ):
            bad.append(f"{r[0][:40]!r}: the board cell {r[2]!r} is not a board list")
        for n in nums:
            used.add(n)
            if n not in boards:
                bad.append(f"{r[0][:40]!r} names board {n}, not on §0")
    bad += [f"board {b} has no register row" for b in sorted(boards - used)]
    want = [
        r[0].strip("`").split("/")[-1] for r in table(visible(section(spec, "2.2 ")))
    ]
    want += [r[0].split(" /")[0] for r in table(visible(section(spec, "4.1 ")))]
    want += [r[0] for r in table(visible(section(spec, "7.1 ")))]
    bad += [
        f"the state {w!r} has no drawn frame in §0.1" for w in want if w not in drawn
    ]
    return bad


HANDOFF_ITEMS = (
    "Final Penpot link",
    "Variants × states",
    "Keyboard table",
    "Accessible name and role",
    "Live data",
    "Motion pair",
    "Density notes",
    "Essential exceptions",
    "Tokens used",
    "Data contract",
    "Contrast and CVD",
    "Design QA and `05` §10",
    "Storybook",
    "Sign-off",
)
HANDOFF_COMPONENTS = ("CMP-027", "CMP-028", "CMP-023", "CMP-038", "CMP-248")


def g_handoff(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    """BQ-3 and README Rules item 4: the hand-off exists, its checklist is complete, its §C
    carries the A-rows and its §D the story lists."""
    hand = env.handoff
    if not hand.strip():
        return [f"{HANDOFF_REL} is missing"]
    rows = table(visible(section(hand, "§A ")))
    bad = [
        f"§A lacks the item {i!r}"
        for i in HANDOFF_ITEMS
        if i not in [r[0] for r in rows]
    ]
    for r in rows:
        for cell in r[1:]:
            if not re.match(r"\[[x ]\] \S", cell):
                bad.append(
                    f"§A {r[0]!r}: a cell that is not '[x] evidence' or '[ ] reason'"
                )
    ids = [r[0] for r in arow_table(env)]
    if ids != [f"D08-A{n}" for n in range(1, len(ids) + 1)] or len(ids) < 13:
        bad.append(f"§C carries {ids}, not D08-A1 … A13 in order")
    stories = " ".join(r[0] for r in table(visible(section(hand, "§D "))))
    bad += [
        f"§D has no story list for {c}" for c in HANDOFF_COMPONENTS if c not in stories
    ]
    if "E12-D08-handoff.md" not in visible(spec):
        bad.append("the spec does not name its hand-off")
    return bad


# ---------------------------------------------------------------------------- mechanical gates


UNIT = re.compile(r"(?<![\w.#/-])\d+(?:[.,]\d+)?\s?(?:ms|s|Hz|px|%)(?!\w)")
RATIO = re.compile(r"(?<![\w.])\d+(?:\.\d+)?:1(?!\d)")
HEXLIT = re.compile(r"(?<![\w&])#[0-9A-Fa-f]{6}(?![0-9A-Za-z])")
EXEMPT = ("11. ",)  # copy cells: verbatim text, gated by G-COPY instead
HANDOFF_EXEMPT = ("§C ",)  # the A-rows: Old verbatim (G-AROWS), New the text to apply


def g_anchor(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    bad: list[str] = []
    tags = ANCHOR_TAG.findall(spec)
    hits = ANCHOR.findall(spec)
    if len(tags) != len(hits):
        bad.append(f"{len(tags) - len(hits)} anchor(s) with no value before them")
    for value, kind, key in hits:
        want = vals.get(f"{kind}:{key}")
        if want is None:
            bad.append(f"unknown anchor {kind}:{key}")
        elif value != want:
            bad.append(f"{kind}:{key} reads {value}, derived {want}")
    return bad


def both(spec: str, env: Env) -> str:
    """The spec and the hand-off, for the gates that read every committed word."""
    return spec + "\n" + env.handoff


def g_figure(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    text = spec
    for head in EXEMPT:
        body = section(text, head)
        if body:
            text = text.replace(body, "")
    hand = env.handoff
    for head in HANDOFF_EXEMPT:
        body = section(hand, head)
        if body:
            hand = hand.replace(body, "")
    text += "\n" + hand
    bad: list[str] = []
    for line in text.split("\n"):
        clean = ANCHOR.sub(" ", line)
        clean = COMMENT.sub(" ", clean)
        clean = CODE.sub(" ", clean)
        clean = QUOTED.sub(" ", clean)
        clean = CITE.sub(" ", clean)
        for rx in (UNIT, RATIO, HEXLIT):
            for m in rx.finditer(clean):
                bad.append(f"a hand-typed figure {m[0]!r}: {nfkc(clean)[:60]!r}")
    return bad


def g_cite(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    """Every cited line exists at the base; a single line and a range's two ends are non-blank."""
    bad: list[str] = []
    for doc, lo, hi in sorted(set(spans(both(spec, env)))):
        if lo < 0:
            bad.append(f"{doc}: a reversed or oversized range")
            continue
        for n in range(lo, hi + 1):
            line = base_line(env, doc, n)
            if line is None or (n in (lo, hi) and not line.strip()):
                bad.append(f"{doc}:{n} is missing or blank at the base")
    return bad


def g_version(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    bad: list[str] = []
    seen: dict[str, list[str] | None] = {}
    for doc, n in sorted(set(cites(both(spec, env)))):
        rel = doc_rel(env, doc)
        if rel is None or n < 0:
            continue
        if rel not in seen:
            head = env.head(rel)
            seen[rel] = head.split("\n") if head is not None else None
        lines = seen[rel]
        if lines is None:
            bad.append(f"{rel} does not resolve at {HEAD_REF}")
            continue
        if base_line(env, doc, n) != (lines[n - 1] if 0 < n <= len(lines) else None):
            bad.append(f"{doc}:{n} differs at {HEAD_REF}: re-pin by content")
    return bad


RAW_HTML = re.compile(r"<\s*/?\s*[A-Za-z][\w-]*(?:\s[^<>]*)?/?>")


def g_marker(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    """A hidden comment, raw HTML (a `hidden` or `display:none` element is unseen text) or an
    invisible character FAILs; markup inside a code span is shown as text and passes."""
    text = both(spec, env)
    bad = [
        f"a hidden comment {c[:40]!r}"
        for c in COMMENT.findall(text)
        if not ANCHOR_TAG.fullmatch(c)
    ]
    bare = CODE.sub(" ", ANCHOR_TAG.sub("", text))
    bad += [f"raw HTML {m[0][:40]!r}" for m in RAW_HTML.finditer(bare)]
    if HIDDEN_CHARS.search(text):
        bad.append("an invisible character")
    return bad


PUBLIC = re.compile(
    r"https?://|\bwww\.|(?<![\w.])\d{1,3}(?:\.\d{1,3}){3}(?![\w.])|/home/|/tmp/|/Users/"
    r"|\b[A-Z]:\\\\|GHSA-|\bCVE-\d|[\w.-]+@[\w-]+\.[a-z]{2,}"
)


def g_public(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    return [f"public-repo leak {m[0]!r}" for m in PUBLIC.finditer(both(spec, env))]


def g_close(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    rx = re.compile(
        r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE
    )
    return [
        f"a closing keyword {m[0]!r} (PR 1 is Refs only)"
        for m in rx.finditer(both(spec, env))
    ]


def g_untouched(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    return [
        f"{p} is touched; this ticket owns only {OWN_PATHS}"
        for p in env.changed()
        if p not in OWN_PATHS
    ]


def g_budget(spec: str, env: Env, vals: dict[str, str]) -> list[str]:
    n = len(spec.rstrip("\n").split("\n"))
    return (
        [f"{n} lines, over the {SPEC_LINE_BUDGET}-line budget"]
        if n > SPEC_LINE_BUDGET
        else []
    )


GATES: tuple[tuple[str, Gate], ...] = (
    ("G-RULED", g_ruled),
    ("G-BOARDS", g_boards),
    ("G-SCR047", g_scr047),
    ("G-MAP", g_map),
    ("G-SCR048", g_scr048),
    ("G-LADDER", g_ladder),
    ("G-EDGE", g_edge),
    ("G-PROGRESS", g_progress),
    ("G-CANCEL", g_cancel),
    ("G-MATRIX", g_matrix),
    ("G-OWNER", g_owner),
    ("G-HEURISTIC", g_heuristic),
    ("G-LEDGER", g_ledger),
    ("G-RISK", g_risk),
    ("G-DRYRUN", g_dryrun),
    ("G-UNMERGED", g_unmerged),
    ("G-T2", g_t2),
    ("G-ROLE", g_role),
    ("G-REF", g_ref),
    ("G-CADENCE", g_cadence),
    ("G-APPROX", g_approx),
    ("G-FRAMES", g_frames),
    ("G-HANDOFF", g_handoff),
    ("G-COPY", g_copy),
    ("G-AROWS", g_arows),
    ("G-CONTRAST", g_contrast),
    ("G-ANCHOR", g_anchor),
    ("G-FIGURE", g_figure),
    ("G-CITE", g_cite),
    ("G-VERSION", g_version),
    ("G-MARKER", g_marker),
    ("G-PUBLIC", g_public),
    ("G-CLOSE", g_close),
    ("G-UNTOUCHED", g_untouched),
    ("G-BUDGET", g_budget),
)


def run_check(spec: str, pins: str, env: Env, vals: dict[str, str]) -> list[Finding]:
    out: list[Finding] = []
    for name, gate in GATES:
        try:
            msgs = gate(spec, env, vals)
        except (
            LookupError,
            ValueError,
            TypeError,
            AttributeError,
        ) as exc:  # a FAIL, never a pass
            msgs = [f"the gate raised {type(exc).__name__}: {exc}"]
        if msgs:
            out.append(
                Finding(
                    name, "FAIL", "; ".join(msgs[:6]) + (" …" if len(msgs) > 6 else "")
                )
            )
    drift = pins_gate(spec, env.handoff, pins)
    if drift:
        level = "NOTE" if any(f.level == "FAIL" for f in out) else "FAIL"
        out.append(
            Finding(
                "G-RULED-PIN",
                level,
                "; ".join(drift[:4]) + (" …" if len(drift) > 4 else ""),
            )
        )
    return out


# ---------------------------------------------------------------------------- self-test


def swap(old: str, new: str) -> Callable[[str], str]:
    def f(spec: str) -> str:
        if old not in spec:
            raise LookupError(f"mutation target missing: {old[:50]!r}")
        return spec.replace(old, new, 1)

    return f


def row_cell(prefix: str, lead: str, col: int, new: str) -> Callable[[str], str]:
    """Set one cell of the row whose lead cell (or, for a shared lead, any cell) is `lead`."""

    def f(spec: str) -> str:
        body = section(spec, prefix)
        for line in body.split("\n"):
            cells = split_row(line) if line.lstrip().startswith("|") else []
            if cells and (
                cells[0] == lead or (lead.startswith("~") and lead[1:] in line)
            ):
                cells[col] = new
                return spec.replace(
                    line,
                    "| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |",
                    1,
                )
        raise LookupError(f"mutation row missing: {prefix} {lead}")

    return f


def append(extra: str) -> Callable[[str], str]:
    return lambda spec: spec + extra


@dataclass(frozen=True)
class Mutation:
    gate: (
        str  # the one gate that must FAIL; "" for an N-n probe, which must trip nothing
    )
    what: str
    apply: Callable[[str], str]
    env: Callable[[Env], None] | None = None
    tag: str = (
        "M"  # M one per gate; X a contradiction or paraphrase; P a pin class; N no-trip
    )


def in_handoff(edit: Callable[[str], str]) -> Callable[[Env], None]:
    """Apply a text edit to the hand-off held in the environment."""

    def f(env: Env) -> None:
        env.handoff = edit(env.handoff)

    return f


def say_in(prefix: str, sentence: str) -> Callable[[str], str]:
    """Append a sentence as its own paragraph at the end of the section `prefix` opens."""

    def f(spec: str) -> str:
        body = section(spec, prefix)
        if not body:
            raise LookupError(f"mutation section missing: {prefix}")
        return spec.replace(body, body.rstrip("\n") + "\n\n" + sentence + "\n", 1)

    return f


def drift_14(env: Env) -> None:
    rel = plan_rel(env, "14") or ""
    lines = env.base(rel).split("\n")
    lines[1110] = lines[1110] + " (moved)"
    env.head_override[rel] = "\n".join(lines)


def touch_14(env: Env) -> None:
    env.changed_override = [*OWN_PATHS, "docs/plan/14-screens-catalogue.md"]


HIDE = (
    "The interval-too-fine and exchange-no-bars headings take the two reason-2 heading forms of "
    "the merged decks (E16-D05:218, E11-D04:344), so no two of the five headings match."
)
MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        "G-RULED",
        "cite another comment in the RULED heading",
        swap("comment 6475004920, on", "comment 6475004921, on"),
    ),
    Mutation(
        "G-BOARDS", "make board 10 the twin of 04", row_cell("0. ", "10", 4, "04")
    ),
    Mutation(
        "G-SCR047",
        "give the interval-too-fine frame the exchange-no-bars heading",
        row_cell(
            "2.2 ",
            "`SCR-047/e12-interval-too-fine`",
            3,
            '"No bars for BTCUSDT 1h between 2020-03-18 00:00 and 2020-03-25 00:00 UTC."',
        ),
    ),
    Mutation(
        "G-MAP",
        "drop `degraded_data` from the mapping table",
        swap("`degraded_data` (503)", "(503)"),
    ),
    Mutation(
        "G-SCR048",
        "give the recompute class a fourth `kind`",
        row_cell("4.1 ", "recompute", 2, "`recompute`"),
    ),
    Mutation(
        "G-LADDER",
        "reverse the 4xx rule",
        swap("**No automatic retry on a 4xx**", "**Automatic retries on a 4xx**"),
    ),
    Mutation(
        "G-EDGE",
        "claim the US-CHART-013 pattern verified",
        swap("**not verifiable at the base**", "**verified at the base**"),
    ),
    Mutation(
        "G-PROGRESS",
        "allow a percentage with no total",
        swap(
            "**never a percentage or a time left**",
            "**a percentage where one is known**",
        ),
    ),
    Mutation(
        "G-CANCEL",
        "give Cancel to CMP-038",
        swap("**Cancel is never CMP-038's:**", "**Cancel is CMP-038's:**"),
    ),
    Mutation(
        "G-MATRIX",
        "let partial history win over cache-loading",
        row_cell(
            "9.1 ", "cache-loading + partial-history", 1, "partial-history (strip line)"
        ),
    ),
    Mutation(
        "G-OWNER",
        "drop the owner marker from the waiver",
        swap("PROPOSED — owner approval pending (#2701).** Waive", "PROPOSED.** Waive"),
    ),
    Mutation(
        "G-HEURISTIC",
        "drop the (heuristic) mark from H-2",
        swap("`(heuristic)` a total-unknown build", "a total-unknown build"),
    ),
    Mutation(
        "G-LEDGER",
        "give D08-G2 to an agent",
        row_cell("15.3 ", "D08-G2", 2, "an agent lane"),
    ),
    Mutation(
        "G-RISK",
        "cite `32` for the R7 / R8 rule",
        swap("(VAL:55–56, backlog tags)", "(VAL:55–56, backlog tags; `32`:1103)"),
    ),
    Mutation(
        "G-DRYRUN",
        "break the S06 row's arithmetic",
        row_cell("16. ", "~frontend: E12-S06", 3, "5"),
    ),
    Mutation(
        "G-UNMERGED",
        "pin #242 at a sha",
        swap("E12-D07 (#242), E12-D10", "E12-D07 (#242 at a1b2c3d4e5), E12-D10"),
    ),
    Mutation(
        "G-T2",
        "invent a reason key",
        swap("while viewing as: `rbac.view_as`", "while viewing as: `rbac.viewing_as`"),
    ),
    Mutation(
        "G-COPY",
        "change a verbatim string by one word",
        row_cell(
            "11. ",
            "W-2",
            2,
            '"Nothing is missing or broken: CandleViewer keeps only what it stores."',
        ),
    ),
    Mutation(
        "G-AROWS",
        "change D08-A4's Old in the hand-off",
        lambda s: s,
        in_handoff(row_cell("§C ", "D08-A4", 3, "CMP-029 Skeleton placeholder.")),
    ),
    Mutation(
        "G-CONTRAST",
        "hold the card's rule to the text floor",
        row_cell("12.1 ", "card-rule", 3, "text"),
    ),
    Mutation(
        "G-ANCHOR",
        "hand-edit a contrast value",
        swap(
            "15.20<!--=CONTRAST:heading.dark-->", "15.21<!--=CONTRAST:heading.dark-->"
        ),
    ),
    Mutation(
        "G-FIGURE",
        "type a figure by hand",
        swap(
            "It re-decides nothing the locked inputs fix",
            "It waits 2.5 s and re-decides nothing the locked inputs fix",
        ),
    ),
    Mutation(
        "G-CITE", "point a cite past the end of D06", swap("D06:289", "D06:99999")
    ),
    Mutation("G-VERSION", "move `14`:1111 at origin/main", lambda s: s, drift_14),
    Mutation(
        "G-MARKER",
        "hide an ungated sentence in a comment",
        swap(HIDE, f"<!-- {HIDE} -->"),
    ),
    Mutation(
        "G-PUBLIC",
        "write a local path",
        swap("Desk work at the base", "Desk work in /tmp/x at the base"),
    ),
    Mutation(
        "G-CLOSE",
        "write a closing keyword",
        swap("PR 2 completes #243.", "PR 2 closes #243."),
    ),
    Mutation("G-UNTOUCHED", "touch `14` in the tree", lambda s: s, touch_14),
    Mutation(
        "G-BUDGET",
        "append lines past the budget",
        append("\n" + "\n".join(["Filler."] * 60) + "\n"),
    ),
    Mutation(
        "G-RULED-PIN",
        "change one ungated word",
        swap("Desk work at the base", "Desk work at base"),
    ),
    Mutation(
        "G-ROLE",
        "give the sentence form a lock (drop its denial)",
        swap(
            "The sentence form has no button and no lock glyph (E16-D05:109).",
            "The sentence form has no button (E16-D05:109).",
        ),
    ),
    Mutation(
        "G-REF",
        "drop a reference source",
        swap("; else a WS `err` frame's `request_id`", ""),
    ),
    Mutation(
        "G-CADENCE",
        "update progress ten times a second",
        say_in("7.2 ", "Progress text updates ten times a second."),
    ),
    Mutation(
        "G-APPROX",
        "offer an approximate action on a frame",
        row_cell(
            "2.2 ",
            "`SCR-047/e12-exchange-no-bars`",
            5,
            "`Approximate from klines` (CMP-001 primary) · `Switch symbol` (CMP-021)",
        ),
    ),
    Mutation(
        "G-FRAMES",
        "leave the rebuild phases undrawn",
        row_cell("0.1 ", "~the phases `pending`", 2, "specified (drawn on request)"),
    ),
    Mutation(
        "G-HANDOFF",
        "blank one hand-off checklist cell",
        lambda s: s,
        in_handoff(swap("[x] none animated", "none animated")),
    ),
    # X-n: contradictions and paraphrases of the ruled classes, each FAILing its own gate
    *(
        Mutation(gate, what, say_in(sec, sentence), tag="X")
        for gate, sec, sentence, what in (
            (
                "G-LADDER",
                "5. ",
                "A 400 is retried automatically once.",
                "review: a 4xx retried",
            ),
            (
                "G-LADDER",
                "5. ",
                "Validation failures are retried automatically.",
                "paraphrase",
            ),
            (
                "G-ROLE",
                "2.3 ",
                "A Manager sees `Record this symbol` with the lock glyph.",
                "review",
            ),
            (
                "G-ROLE",
                "2.3 ",
                "The sentence form carries the lock glyph.",
                "a locked sentence",
            ),
            (
                "G-PROGRESS",
                "7.1 ",
                "With no total the strip shows an estimated percentage.",
                "review",
            ),
            (
                "G-PROGRESS",
                "7.2 ",
                "A total-unknown build shows the time left.",
                "paraphrase",
            ),
            (
                "G-CANCEL",
                "8.3 ",
                "After Cancel, focus returns to the control that started the rebuild.",
                "review",
            ),
            ("G-CANCEL", "8.3 ", "Completion returns focus to the pill.", "paraphrase"),
            (
                "G-CANCEL",
                "8.1 ",
                "Cancel appears only after the progress bar shows.",
                "a late Cancel",
            ),
            (
                "G-CANCEL",
                "10.2 ",
                "`Esc` dismisses the outcome notice.",
                "Esc dismisses",
            ),
            (
                "G-MARKER",
                "1.2 ",
                "<div hidden>Focus moves to Retry.</div>",
                "review: hidden HTML",
            ),
            (
                "G-MARKER",
                "1.2 ",
                '<span style="display:none">Retries are automatic.</span>',
                "display:none",
            ),
            (
                "G-APPROX",
                "1.4 ",
                "An `Approximate from klines` action is offered on the non-time frames.",
                "review",
            ),
            (
                "G-APPROX",
                "6.1 ",
                "Earlier non-time bars are estimated bars until recorded.",
                "paraphrase",
            ),
            (
                "G-REF",
                "4.2 ",
                "The reference is built from the account id and the request time.",
                "data in the ref",
            ),
            ("G-REF", "13.3 ", "The reference includes the symbol.", "paraphrase"),
            ("G-CADENCE", "7.2 ", "The strip updates on every print.", "per event"),
            (
                "G-LADDER",
                "5. ",
                "A 422 is tried again by itself after two seconds.",
                "review r2: tried again",
            ),
            (
                "G-LADDER",
                "5. ",
                "The client re-sends a 400 once, without asking the user.",
                "review r2: a trailing without",
            ),
            (
                "G-ROLE",
                "2.3 ",
                "A Manager is shown the record button, greyed, with a padlock.",
                "review r2: a button",
            ),
            (
                "G-ROLE",
                "2.3 ",
                "Roles other than the Owner get `Record this symbol` too, drawn T2.",
                "review r2: roles other than",
            ),
            (
                "G-PROGRESS",
                "7.1 ",
                "When the total is unknown the strip shows the prints done plus an ETA.",
                "review r2: an ETA",
            ),
            (
                "G-PROGRESS",
                "7.1 ",
                "With an unknown total the bar fills to show progress as a share of the work.",
                "review r2: a share",
            ),
            (
                "G-CANCEL",
                "8.1 ",
                "Cancel appears two seconds after the strip.",
                "review r2: a timed Cancel",
            ),
            (
                "G-CANCEL",
                "8.3 ",
                "After Cancel, focus goes back to the Rebuild button.",
                "review r2: a labelled button",
            ),
            (
                "G-CANCEL",
                "8.3 ",
                "Pressing Escape closes the outcome line.",
                "review r2: Escape closes",
            ),
            ("G-CADENCE", "7.1 ", "The counter updates at 30 fps.", "review r2: fps"),
            (
                "G-CADENCE",
                "7.1 ",
                "The counter refreshes on every animation frame.",
                "review r2: animation frame",
            ),
            (
                "G-REF",
                "4.2 ",
                "The reference is the user id plus the symbol.",
                "review r2: is … plus",
            ),
            (
                "G-T2",
                "4.1 ",
                "`Open diagnostics` is hidden for a Manager.",
                "review r2: hidden",
            ),
            (
                "G-LADDER",
                "5. ",
                "Forbidden responses get a second attempt on their own.",
                "fresh",
            ),
            (
                "G-T2",
                "10.4 ",
                "A Viewer does not see `Open diagnostics` at all.",
                "fresh",
            ),
            ("G-CANCEL", "8.3 ", "Hitting Escape clears the outcome notice.", "fresh"),
            ("G-ROLE", "2.3 ", "Non-owners see a disabled record button.", "fresh"),
            (
                "G-LADDER",
                "5. ",
                "A 403 is retried once more after a short pause.",
                "review r3: retried once more",
            ),
            (
                "G-LADDER",
                "5. ",
                "The client repeats a 400 request after two seconds.",
                "review r3: repeats",
            ),
            (
                "G-LADDER",
                "5. ",
                "Validation errors are re-tried in the background.",
                "review r3: re-tried",
            ),
            (
                "G-LADDER",
                "5. ",
                "A 422 triggers one more attempt.",
                "review r3: one more attempt",
            ),
            (
                "G-ROLE",
                "2.3 ",
                "Anyone who is not the Owner sees `Record this symbol` greyed out.",
                "review r3: who is not the Owner",
            ),
            (
                "G-ROLE",
                "2.3 ",
                "Non-owner roles see the record CTA with a disabled look.",
                "review r3: the record CTA",
            ),
            (
                "G-PROGRESS",
                "7.1 ",
                "When the total cannot be known the bar shows the time to completion.",
                "review r3: cannot be known",
            ),
            (
                "G-PROGRESS",
                "7.1 ",
                "If the total is undetermined the strip shows the percentage complete.",
                "review r3: undetermined",
            ),
            (
                "G-PROGRESS",
                "7.1 ",
                "Without a known total the strip shows the percentage done.",
                "review r3: without a known total",
            ),
            (
                "G-CANCEL",
                "8.1 ",
                "Cancel shows up half a second after the strip.",
                "review r3: half a second",
            ),
            (
                "G-CANCEL",
                "8.1 ",
                "Cancel is revealed after a short delay.",
                "review r3: a delay",
            ),
            (
                "G-CANCEL",
                "8.3 ",
                "On Cancel, focus is placed on the Rebuild button.",
                "review r3: placed on",
            ),
            (
                "G-CANCEL",
                "8.3 ",
                "Escape makes the outcome line go away.",
                "review r3: any verb",
            ),
            (
                "G-CADENCE",
                "7.1 ",
                "The counter updates on each requestAnimationFrame.",
                "review r3: rAF",
            ),
            (
                "G-T2",
                "10.4 ",
                "Managers never see `Open diagnostics`.",
                "review r3: never see",
            ),
            (
                "G-T2",
                "10.4 ",
                "`Retry Volume 75` is suppressed for a Viewer.",
                "review r3: suppressed",
            ),
            (
                "G-T2",
                "4.1 ",
                "`Open diagnostics` is left out of the Manager's menu.",
                "review r3: left out",
            ),
            (
                "G-T2",
                "10.4 ",
                "`Build earlier bars` is invisible to non-owners.",
                "review r3: invisible",
            ),
            (
                "G-LADDER",
                "5. ",
                "Without a pause, a 403 is re-sent.",
                "fresh r3: a condition-clause without",
            ),
            (
                "G-LADDER",
                "5. ",
                "On a 409 the client tries the call again.",
                "fresh r3: again",
            ),
            (
                "G-LADDER",
                "5. ",
                "Refused requests are replayed after the backoff.",
                "fresh r3: replayed",
            ),
            (
                "G-ROLE",
                "2.3 ",
                "Everyone except the Owner gets a faded record button.",
                "fresh r3: everyone except",
            ),
            (
                "G-PROGRESS",
                "7.1 ",
                "With the total still unavailable, the bar estimates the minutes left.",
                "fresh r3: minutes left",
            ),
            (
                "G-CANCEL",
                "8.3 ",
                "Focus is handed to the Rebuild button after Cancel.",
                "fresh r3: handed",
            ),
            (
                "G-CANCEL",
                "8.1 ",
                "Cancel turns up a moment after the strip.",
                "fresh r3: a moment",
            ),
            (
                "G-CADENCE",
                "7.1 ",
                "The counter is redrawn with every vsync.",
                "fresh r3: vsync",
            ),
            (
                "G-T2",
                "10.4 ",
                "`Build earlier bars` is not offered to Viewers.",
                "fresh r3: not offered",
            ),
            (
                "G-T2",
                "4.1 ",
                "`Open diagnostics` disappears for Managers.",
                "fresh r3: disappears",
            ),
            (
                "G-T2",
                "10.4 ",
                "The diagnostics link is not shown to Managers.",
                "M-1r3: a stem, not shown",
            ),
            (
                "G-T2",
                "10.4 ",
                "Retry Volume 75 exists only in the Owner's build of the panel.",
                "M-1r3: exists only",
            ),
            (
                "G-T2",
                "6.1 ",
                "For anyone else, Build earlier bars is simply not there.",
                "M-1r3: not there",
            ),
            (
                "G-LADDER",
                "5. ",
                "The client tries the 400 call a second time.",
                "M-1r3: tries",
            ),
            (
                "G-LADDER",
                "5. ",
                "A 4xx loops back into the send queue.",
                "M-1r3: the send queue",
            ),
            (
                "G-ROLE",
                "2.3 ",
                "Viewers can press Record, which then refuses.",
                "M-1r3: press Record",
            ),
            (
                "G-PROGRESS",
                "7.1 ",
                "Lacking a total, the strip shows how much is left.",
                "M-1r3: lacking a total",
            ),
            (
                "G-CANCEL",
                "8.1 ",
                "Cancel is held back briefly so it is not hit by accident.",
                "M-1r3: held back",
            ),
            (
                "G-CANCEL",
                "8.3 ",
                "After Cancel, the Rebuild button takes focus.",
                "M-1r3: takes focus",
            ),
            (
                "G-CANCEL",
                "10.2 ",
                "Esc wipes the result text.",
                "M-1r3: Esc wipes",
            ),
            (
                "G-CADENCE",
                "7.2 ",
                "The count ticks with each trade.",
                "M-1r3: ticks",
            ),
            (
                "G-CADENCE",
                "7.2 ",
                "The counter is repainted continuously.",
                "M-1r3: continuously",
            ),
            (
                "G-T2",
                "10.4 ",
                "The diagnostics entry is an Owner privilege.",
                "fresh r4: a privilege",
            ),
            (
                "G-LADDER",
                "5. ",
                "The 422 is handed back to the transport for a further go.",
                "fresh r4: handed back",
            ),
            (
                "G-PROGRESS",
                "7.1 ",
                "In the absence of a total the strip estimates the remainder.",
                "fresh r4: the absence of a total",
            ),
            (
                "G-CANCEL",
                "8.3 ",
                "Once cancelled, focus lands on the pill.",
                "fresh r4: lands on",
            ),
            (
                "G-T2",
                "10.4 ",
                "Diagnostics stay a privilege of the Owner seat.",
                "r5: a privilege of the seat",
            ),
            (
                "G-T2",
                "10.4 ",
                "Retry for Volume 75 is kept off the strip for anyone below the Owner.",
                "r5: below the Owner",
            ),
            (
                "G-T2",
                "10.4 ",
                "Only an Owner can reach diagnostics from this card.",
                "r5: only an Owner can reach",
            ),
            (
                "G-T2",
                "10.4 ",
                "A Manager gets no diagnostics link on this card.",
                "r5: no link",
            ),
            (
                "G-T2",
                "10.4 ",
                "The diagnostics entry point sits out of reach for a Manager.",
                "r5: out of reach",
            ),
            (
                "G-T2",
                "10.4 ",
                "The earlier-bars build is something a Manager simply never encounters.",
                "r5: a hyphenated stem",
            ),
            (
                "G-T2",
                "10.4 ",
                "The Volume-75 retry is not offered to a Manager.",
                "r5: Volume-75",
            ),
            (
                "G-T2",
                "10.4 ",
                "A Viewer finds no way into the diagnostic panel.",
                "r5: the singular stem",
            ),
            (
                "G-LADDER",
                "5. ",
                "A 400 is pushed through once more after the ladder step.",
                "r5: pushed through",
            ),
            (
                "G-LADDER",
                "5. ",
                "The transport replays a 409 when the socket recovers.",
                "r5: replays",
            ),
            (
                "G-LADDER",
                "5. ",
                "The client re-requests after a 422 at the next step.",
                "r5: re-requests",
            ),
            (
                "G-LADDER",
                "5. ",
                "A 403 is periodically re-checked in the background.",
                "r5: re-checked",
            ),
            (
                "G-LADDER",
                "5. ",
                "A 422 is retransmitted at the next ladder step.",
                "r5: retransmitted",
            ),
            (
                "G-LADDER",
                "5. ",
                "After a 403 the client keeps knocking at intervals.",
                "r5: keeps knocking",
            ),
            (
                "G-LADDER",
                "5. ",
                "A 400 goes round the ladder like any other failure.",
                "r5: round the ladder",
            ),
            (
                "G-LADDER",
                "5. ",
                "A validation error triggers the next rung of the ladder.",
                "r5: the next rung",
            ),
            (
                "G-ROLE",
                "2.3 ",
                "A Viewer is handed the Record this symbol control as well.",
                "r5: handed the control",
            ),
            (
                "G-ROLE",
                "2.3 ",
                "Managers get the CTA too, just without the lock.",
                "r5: without the lock",
            ),
            (
                "G-ROLE",
                "2.3 ",
                "For anyone else the record button stays on the panel.",
                "r5: stays on the panel",
            ),
            (
                "G-ROLE",
                "2.3 ",
                "Managers can start a recording from this panel.",
                "r5: start a recording",
            ),
            (
                "G-ROLE",
                "2.3 ",
                "A Viewer may begin recording the symbol straight from the empty state.",
                "r5: begin recording",
            ),
            (
                "G-PROGRESS",
                "7.1 ",
                "Pending a total, the strip offers a rough share done.",
                "r5: pending a total",
            ),
            (
                "G-PROGRESS",
                "7.1 ",
                "Absent any total, the bar paints how far along the build is.",
                "r5: how far along",
            ),
            (
                "G-PROGRESS",
                "7.1 ",
                "While the total is still unknown, the strip guesses the minutes outstanding.",
                "r5: guesses",
            ),
            (
                "G-PROGRESS",
                "7.1 ",
                "With the total unknown, the strip reads 3 of roughly 10 chunks.",
                "r5: 3 of roughly 10",
            ),
            (
                "G-PROGRESS",
                "7.1 ",
                "Lacking a total, the strip projects when the build will finish.",
                "r5: projects the finish",
            ),
            (
                "G-CANCEL",
                "8.3 ",
                "After Cancel, focus goes to the strip's header.",
                "r5: the strip's header",
            ),
            (
                "G-CANCEL",
                "10.2 ",
                "Pressing Esc closes the strip and keeps the build running.",
                "r5: Esc closes the strip",
            ),
            (
                "G-CANCEL",
                "8.3 ",
                "When the rebuild ends, focus is placed on the interval pill.",
                "r5: placed on the pill",
            ),
            (
                "G-CANCEL",
                "8.1 ",
                "Cancel is deferred until the first bar draws.",
                "r5: deferred",
            ),
            (
                "G-CANCEL",
                "8.1 ",
                "Cancel comes into view once the build has warmed up.",
                "r5: warmed up",
            ),
            (
                "G-CANCEL",
                "10.2 ",
                "Hitting Escape leaves the build running.",
                "r5: Escape leaves it running",
            ),
            (
                "G-CANCEL",
                "8.1 ",
                "The Cancel control materialises a little into the build.",
                "r5: materialises",
            ),
            (
                "G-CANCEL",
                "8.3 ",
                "Once cancelled, the cursor lands on the header of the strip.",
                "r5: the cursor",
            ),
            (
                "G-CADENCE",
                "7.2 ",
                "The elapsed counter refreshes on every print it receives.",
                "r5: every print",
            ),
            (
                "G-CADENCE",
                "7.2 ",
                "The strip's text animates smoothly as the build runs.",
                "r5: animates",
            ),
            (
                "G-CADENCE",
                "7.2 ",
                "The progress bar advances in real time.",
                "r5: real time",
            ),
            (
                "G-CADENCE",
                "7.2 ",
                "The prints counter climbs ten times a second.",
                "r5: ten times a second",
            ),
            (
                "G-CADENCE",
                "7.2 ",
                "The elapsed figure changes every 100 milliseconds.",
                "r5: a period, 10 Hz",
            ),
            (
                "G-CADENCE",
                "7.2 ",
                "The prints-done number moves with each chunk that arrives.",
                "r5: moves with each chunk",
            ),
            (
                "G-CADENCE",
                "7.2 ",
                "The strip's wording is kept current as fast as prints arrive.",
                "r5: kept current",
            ),
            # r6 (M-1r5): the round-5 review's escapes, each now FAILing its own gate
            (
                "G-T2",
                "10.4 ",
                "A Manager never sees the troubleshooting panel link on this card.",
                "r6: troubleshooting panel",
            ),
            (
                "G-T2",
                "10.4 ",
                "The older-bars build stays out of a Viewer's reach.",
                "r6: older bars",
            ),
            (
                "G-T2",
                "10.4 ",
                "The Vol 75 retry is hidden from a Manager.",
                "r6: Vol 75",
            ),
            (
                "G-T2",
                "10.4 ",
                "Back-history loading is withheld from a Viewer.",
                "r6: back history",
            ),
            (
                "G-T2",
                "10.4 ",
                "The debug view is reserved for the Owner.",
                "r6: debug view",
            ),
            (
                "G-T2",
                "10.4 ",
                "The prior-bar build is dropped from the strip for a Manager.",
                "r6: prior bar",
            ),
            (
                "G-ROLE",
                "2.3 ",
                "Every role can start capturing this symbol from the empty state.",
                "r6: every role, capturing",
            ),
            (
                "G-ROLE",
                "2.3 ",
                "A Manager may kick off a capture of the symbol here.",
                "r6: a capture",
            ),
            (
                "G-ROLE",
                "2.3 ",
                "The start-capture link is offered to all users.",
                "r6: all users",
            ),
            (
                "G-ROLE",
                "2.3 ",
                "Record this symbol is drawn for every role.",
                "r6: every role",
            ),
            (
                "G-ROLE",
                "2.3 ",
                "Any signed-in user gets the record control.",
                "r6: any signed-in user",
            ),
            (
                "G-ROLE",
                "2.3 ",
                "A Viewer can begin a capture from the panel's link.",
                "r6: begin a capture",
            ),
            (
                "G-ROLE",
                "2.3 ",
                "Managers also get the capture link, unlocked.",
                "r6: capture link",
            ),
            (
                "G-LADDER",
                "5. ",
                "A rejected request is sent once more on the next ladder step.",
                "r6: rejected",
            ),
            (
                "G-LADDER",
                "5. ",
                "A Bad Request follows the same backoff as a 503.",
                "r6: Bad Request, backoff",
            ),
            (
                "G-LADDER",
                "5. ",
                "A conflict response is retried like any server error.",
                "r6: conflict",
            ),
            (
                "G-LADDER",
                "5. ",
                "A 409 joins the backoff like a 503.",
                "r6: joins the backoff",
            ),
            (
                "G-LADDER",
                "5. ",
                "An Unprocessable Entity response goes through the ladder.",
                "r6: goes through",
            ),
            (
                "G-LADDER",
                "5. ",
                "A 422 is handled exactly like a 503.",
                "r6: handled like a 503",
            ),
            (
                "G-LADDER",
                "5. ",
                "The server's rejection of a 4-series request is retried automatically.",
                "r6: 4-series rejection",
            ),
            (
                "G-LADDER",
                "5. ",
                "A 400 gets a second chance after the delay.",
                "r6: second chance",
            ),
            (
                "G-PROGRESS",
                "7.1 ",
                "When the size of the build is not known, the bar shows a share of the work done.",
                "r6: size not known",
            ),
            (
                "G-PROGRESS",
                "7.1 ",
                "While the end count is unknown, the strip shows a percentage.",
                "r6: end count unknown",
            ),
            (
                "G-PROGRESS",
                "7.1 ",
                "In the indeterminate phase the strip shows how long is left.",
                "r6: indeterminate phase",
            ),
            (
                "G-PROGRESS",
                "7.1 ",
                "With no count of prints to go by, the bar fills part way.",
                "r6: no count of prints",
            ),
            (
                "G-PROGRESS",
                "7.1 ",
                "Before the print count arrives, the strip predicts the minutes to go.",
                "r6: before the print count",
            ),
            (
                "G-CANCEL",
                "8.1 ",
                "Cancelling is only possible after two seconds.",
                "r6: Cancelling",
            ),
            (
                "G-CANCEL",
                "8.1 ",
                "The stop control appears only after the first bar draws.",
                "r6: stop control",
            ),
            (
                "G-CANCEL",
                "8.3 ",
                "After cancelling, keyboard attention returns to the interval pill.",
                "r6: keyboard attention",
            ),
            (
                "G-CANCEL",
                "8.3 ",
                "Once the rebuild is aborted, the active element is the interval pill.",
                "r6: active element",
            ),
            (
                "G-CANCEL",
                "8.1 ",
                "Pressing escape leaves the build running.",
                "r6: lowercase escape",
            ),
            (
                "G-CANCEL",
                "8.1 ",
                "Cancellation is offered once the build is well under way.",
                "r6: Cancellation",
            ),
            (
                "G-CANCEL",
                "8.1 ",
                "The abort button is held back for the first stretch.",
                "r6: abort button",
            ),
            (
                "G-CANCEL",
                "10.2 ",
                "After a cancel, the tab position goes back to the trigger.",
                "r6: tab position",
            ),
            (
                "G-CADENCE",
                "7.2 ",
                "The prints-done figure mirrors each delta that arrives.",
                "r6: mirrors",
            ),
            (
                "G-CADENCE",
                "7.2 ",
                "The strip's text tracks the stream live.",
                "r6: tracks",
            ),
            (
                "G-CADENCE",
                "7.2 ",
                "The elapsed readout is rewritten with every chunk.",
                "r6: rewritten",
            ),
            (
                "G-CADENCE",
                "7.2 ",
                "The counter keeps pace with the feed.",
                "r6: keeps pace",
            ),
            (
                "G-CADENCE",
                "7.2 ",
                "The elapsed counter is live, following every print.",
                "r6: following every print",
            ),
            # r7 (m-1, m-2): "without an", and the 4xx names and refusal words the r6 review found open
            (
                "G-PROGRESS",
                "7.1 ",
                "Without an expected total, the strip shows a percentage.",
                "r7: without an",
            ),
            (
                "G-LADDER",
                "5. ",
                "A Payment Required response is sent once more on the next ladder step.",
                "r7: Payment Required",
            ),
            (
                "G-LADDER",
                "5. ",
                "A Method Not Allowed response goes through the ladder.",
                "r7: Method Not Allowed",
            ),
            (
                "G-LADDER",
                "5. ",
                "A Precondition Failed answer joins the backoff like a 503.",
                "r7: Precondition Failed",
            ),
            (
                "G-LADDER",
                "5. ",
                "A denied request waits for the next rung.",
                "r7: denied",
            ),
            (
                "G-LADDER",
                "5. ",
                "A declined request is queued behind the backoff.",
                "r7: declined",
            ),
            (
                "G-LADDER",
                "4.1 ",
                "A `validation_failed` refusal `23` marks retryable is sent again on the ladder.",
                "orch r1: the BQ-11 marker on a code outside the five",
            ),
            (
                "G-LADDER",
                "5. ",
                "The refusals `23` marks retryable and a bad request from the bars endpoint go through the same backoff.",
                "orch r1 delta MJ-1: the BQ-11 marker beside a bad request",
            ),
            (
                "G-LADDER",
                "5. ",
                "The refusals `23` marks retryable, validation errors included, rerun on the transport's ladder.",
                "orch r1 delta MJ-1: the BQ-11 marker beside a validation error",
            ),
            (
                "G-LADDER",
                "5. ",
                "The refusals `23` marks retryable, and an unprocessable bars request too, are re-sent after the next step.",
                "orch r1 delta MJ-1: the BQ-11 marker beside an unprocessable request",
            ),
            (
                "G-LADDER",
                "5. ",
                "The refusals `23` marks retryable and a forbidden topic follow the same schedule.",
                "orch r1 delta MJ-1: the BQ-11 marker beside a forbidden topic",
            ),
        )
    ),
    Mutation(
        "G-SCR047",
        "give the before-start frame the never-recorded cause (BQ-7 of 6475004920)",
        row_cell(
            "2.2 ",
            "`SCR-047/e12-before-start`",
            4,
            '"Nothing is missing or broken: CandleViewer keeps only what it records."',
        ),
        tag="X",
    ),
    Mutation(
        "G-SCR047",
        "give the interval-too-fine frame the history-start cause",
        row_cell(
            "2.2 ",
            "`SCR-047/e12-interval-too-fine`",
            4,
            '"Nothing is missing or broken: CandleViewer keeps only what it records."',
        ),
        tag="X",
    ),
    Mutation(
        "G-MATRIX",
        "drop `14`:762's stale reading from its row",
        row_cell("9.1 ", "rebuilding + stale", 2, "the strip line only"),
        tag="X",
    ),
    Mutation(
        "G-MAP",
        "put a 400 on the ladder",
        row_cell("3. ", "~`invalid_cursor` (400)", 5, "the ladder, five attempts"),
        tag="X",
    ),
    Mutation(
        "G-REF",
        "add a fifth source built from data",
        swap(
            "; else a client-minted",
            "; else a hash of the symbol and time; else a client-minted",
        ),
        tag="X",
    ),
    # P-n: one per pin class; only the pins catch these
    Mutation(
        "G-RULED-PIN",
        "a heading",
        swap("### 1.1 What this spec fixes", "### 1.1 What this spec settles"),
        tag="P",
    ),
    Mutation(
        "G-RULED-PIN",
        "a row",
        row_cell("1.3 ", "~D02 — D-1 the held frame", 2, "§6 … §8"),
        tag="P",
    ),
    Mutation("G-RULED-PIN", "a rule line", lambda s: drop_rule(s, "1.3 "), tag="P"),
    Mutation(
        "G-RULED-PIN",
        "a sentence",
        swap("The tool reads `22`'s", "The tool reads all of `22`'s"),
        tag="P",
    ),
    Mutation(
        "G-RULED-PIN",
        "a hand-off unit",
        lambda s: s,
        in_handoff(swap("Rule: every line is", "Rule: each line is")),
        tag="P",
    ),
    Mutation(
        "G-MAP",
        "orch r1: drop the BQ-11 sentence from §4.1",
        lambda s: re.sub(
            r" \*\*The refusals `23` marks retryable\*\*[^\n]*?the ladder ends\.",
            "",
            s,
            count=1,
        ),
        tag="X",
    ),
    Mutation(
        "G-MAP",
        "orch r1: give the five WS refusals no ladder in §3",
        row_cell("3. ", "~`resync_rate_limited`", 5, "none: `Retry` (D02:326)"),
        tag="X",
    ),
    Mutation(
        "G-PROGRESS",
        "orch r1 M-1: give the outcome-unknown phase the percentage notice",
        row_cell("7.1 ", "outcome-unknown", 4, "W-35, W-36, W-38"),
        tag="X",
    ),
    Mutation(
        "G-PROGRESS",
        "orch r1 M-1: drop the over-budget-unknown phase",
        lambda s: drop_row(s, "7.1 ", "over-budget-unknown"),
        tag="X",
    ),
    Mutation(
        "G-PROGRESS",
        "orch r1 M-1: untie the over-budget phase from D08-G1",
        row_cell(
            "7.1 ",
            "over-budget",
            1,
            "elapsed past the estimate, or past 10<!--=CITE:budget.s--> s per 1 M prints",
        ),
        tag="X",
    ),
    Mutation(
        "G-PROGRESS",
        "orch r1 delta MJ-2: the over-budget-unknown Shows cell words a share done",
        row_cell(
            "7.1 ",
            "over-budget-unknown",
            2,
            '"taking longer than estimated" with the share of prints built so far beside the '
            "elapsed time; `Cancel` stays; no auto-cancel",
        ),
        tag="X",
    ),
    Mutation(
        "G-PROGRESS",
        "orch r1 delta MJ-2: W-45 gains a time to go",
        swap(
            '2 min 10 s elapsed · total unknown · taking longer than estimated"',
            '2 min 10 s elapsed · total unknown · about 3 min to go"',
        ),
        tag="X",
    ),
    Mutation(
        "G-PROGRESS",
        "orch r1 delta MJ-2: W-46 words the share as a fraction",
        swap(
            '"Build cancelled after 2 min 10 s elapsed. Still showing Volume 50 BTC."',
            '"Build cancelled two fifths of the way through. Still showing Volume 50 BTC."',
        ),
        tag="X",
    ),
    # N-n: legitimate rewordings; re-pinned, they must trip nothing
    *(
        Mutation("", what, say_in(sec, sentence), tag="N")
        for sec, sentence, what in (
            ("5. ", "A 400 is never retried automatically.", "a negated 4xx retry"),
            (
                "4.1 ",
                "The refusals `23` marks retryable are sent again until the ladder ends.",
                "orch r1: the BQ-11 marker on the five",
            ),
            (
                "7.1 ",
                "With no total the strip shows no percentage and no time left.",
                "no total",
            ),
            (
                "8.3 ",
                "Focus never returns to the control that started the rebuild.",
                "focus",
            ),
            ("4.2 ", "The reference holds no symbol and no time.", "the reference"),
            (
                "5. ",
                "A 400 is answered without an automatic retry.",
                "a leading without",
            ),
            (
                "8.1 ",
                "`Esc` cancels the build; it never closes the outcome notice.",
                "Esc negated",
            ),
            (
                "10.4 ",
                "A Manager reads `Open diagnostics` in T2 2a, never hidden.",
                "T2 never hidden",
            ),
            (
                "7.1 ",
                "The counter updates at most 4 times a second, never per animation frame.",
                "a capped cadence",
            ),
            (
                "13.1 ",
                "The 429 codes are retried automatically, as `22` marks them.",
                "a 429 retry",
            ),
            (
                "5. ",
                "A 404 shows `Retry` for the user to press.",
                "a user's `Retry` on a 4xx",
            ),
            (
                "4.1 ",
                "`Open diagnostics` opens SCR-046 for the Owner.",
                "the Owner's control",
            ),
            (
                "8.1 ",
                "Cancel stays on the strip until the build ends.",
                "Cancel throughout",
            ),
            ("10.4 ", "A Manager reads `Retry Volume 75` in rendering 2a.", "2a"),
            (
                "7.1 ",
                "Without a total, the strip never shows a percentage.",
                "a condition without, negated",
            ),
            (
                "5. ",
                "Without a retry of its own, a 400 waits for the user.",
                "a governing without",
            ),
        )
    ),
    Mutation(
        "",
        "a hand-off rewording",
        lambda s: s,
        in_handoff(swap("Rule: every line is", "Rule: each line is")),
        tag="N",
    ),
)


def drop_row(spec: str, prefix: str, lead: str) -> str:
    """Remove the table row whose lead cell is `lead` under the section `prefix` opens."""
    body = section(spec, prefix)
    for line in body.split("\n"):
        cells = split_row(line) if line.lstrip().startswith("|") else []
        if cells and cells[0] == lead:
            return spec.replace(body, body.replace(line + "\n", "", 1), 1)
    raise LookupError(f"mutation row missing: {prefix} {lead}")


def drop_rule(spec: str, prefix: str) -> str:
    """Remove the first table rule line under the section `prefix` opens."""
    body = section(spec, prefix)
    rule = next((ln for ln in body.split("\n") if is_rule(ln)), None)
    if rule is None:
        raise LookupError(f"mutation rule line missing: {prefix}")
    return spec.replace(body, body.replace(rule + "\n", "", 1), 1)


def self_test(spec: str, pins: str, handoff: str) -> int:
    digest = hashlib.sha256((spec + handoff).encode()).hexdigest()
    base_env = Env(handoff=handoff)
    vals = compute(spec, base_env)
    base = [f for f in run_check(spec, pins, base_env, vals) if f.level == "FAIL"]
    ok = True
    if base:
        print(
            f"SELF-TEST baseline is not clean: {[(f.gate, f.msg[:80]) for f in base]}"
        )
        ok = False
    gates = {name for name, _ in GATES} | {"G-RULED-PIN"}
    covered = {m.gate for m in MUTATIONS if m.tag == "M"}
    if covered != gates:
        print(f"SELF-TEST gates without a mutation: {sorted(gates - covered)}")
        ok = False
    seen: dict[str, int] = {}
    for m in MUTATIONS:
        seen[m.tag] = seen.get(m.tag, 0) + 1
        label = f"{m.tag}-{seen[m.tag]:02d}"
        env = Env(memo=dict(base_env.memo), handoff=handoff)
        try:
            if m.env:
                m.env(env)
            mutated = m.apply(spec)
        except LookupError as exc:
            print(f"{label} {m.gate}: {exc}")
            ok = False
            continue
        # an N-n probe is a legitimate rewording: re-pinned, it must trip nothing
        use = "\n".join(pin_lines(mutated, env.handoff)) if m.tag == "N" else pins
        fails = [f for f in run_check(mutated, use, env, vals) if f.level == "FAIL"]
        got = [f.gate for f in fails]
        want = [m.gate] if m.gate else []
        status = "ok" if got == want else "BAD"
        ok = ok and status == "ok"
        print(f"{label} {status:3s} {m.gate or '(none)':12s} {m.what} -> {got}")
    if hashlib.sha256((spec + handoff).encode()).hexdigest() != digest:
        print("SELF-TEST the text changed in memory")
        ok = False
    counts = ", ".join(f"{n} {t}" for t, n in seen.items())
    print(
        f"self-test: {len(MUTATIONS)} mutations ({counts}), {'PASS' if ok else 'FAIL'}"
    )
    return 0 if ok else 1


# ---------------------------------------------------------------------------- main


def read(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument(
        "--check", action="store_true", help="re-derive and gate; writes nothing"
    )
    ap.add_argument(
        "--json", action="store_true", help="print the derived values and findings"
    )
    ap.add_argument(
        "--fill", action="store_true", help="write the derived values into the spec"
    )
    ap.add_argument("--self-test", action="store_true", help="one mutation per gate")
    ap.add_argument(
        "--repin-ruled", action="store_true", help="rewrite the pins (the only writer)"
    )
    args = ap.parse_args(argv)
    spec, pins, handoff = read(SPEC_REL), read(PINS_REL), read(HANDOFF_REL)
    if args.self_test:
        return self_test(spec, pins, handoff)
    env = Env(handoff=handoff)
    vals = compute(spec, env)
    if args.fill:
        (ROOT / SPEC_REL).write_text(fill(spec, vals), encoding="utf-8")
        print(f"filled {len(ANCHOR.findall(spec))} anchors")
        return 0
    if args.repin_ruled:
        (ROOT / PINS_REL).write_text(
            "\n".join(pin_lines(spec, handoff)) + "\n", encoding="utf-8"
        )
        print(f"pinned {len(all_units(spec, handoff))} units")
        return 0
    findings = run_check(spec, pins, env, vals)
    fails = sum(1 for f in findings if f.level == "FAIL")
    warns = sum(1 for f in findings if f.level == "WARN")
    if args.json:
        counts = {
            "spec_lines": len(spec.rstrip("\n").split("\n")),
            "units": len(all_units(spec, handoff)),
            "handoff_lines": len(handoff.rstrip("\n").split("\n")),
            "anchors": len(ANCHOR.findall(spec)),
            "cites": len(set(cites(spec))),
            "gates": len(GATES) + 1,
            "fail": fails,
            "warn": warns,
        }
        out = {
            "base": BASE,
            "values": vals,
            "counts": counts,
            "findings": [f.__dict__ for f in findings],
        }
        print(json.dumps(out, indent=1, ensure_ascii=True))
    else:
        for f in findings:
            print(f"{f.level} {f.gate}: {f.msg}".encode("ascii", "replace").decode())
        print(
            f"check: {fails} FAIL, {warns} WARN, {len(GATES) + 1} gates, base {BASE[:10]}"
        )
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
