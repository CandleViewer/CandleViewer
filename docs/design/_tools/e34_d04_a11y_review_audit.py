"""E34-D04 (#998) audit: the accessibility review of SCR-061 and SCR-062.

Stdlib only, offline (`python3 -I -B`). It reads the spec and the pins file from the working tree,
every merged owner AS TEXT at the base with `git show`, and the two unmerged specs under review at
their pushed PR heads (request rows RQ-1 and RQ-2), and the same specs with the A-rows applied by
content (their blobs at the PR heads, "RQ-n landed"). It imports, never copies: `contrast_check.py`'s
`contrast_ratio()`, `verify_tokens.py`'s resolver, `docs/research/_tools/cvd_simulate.py`'s
`simulate()` and `delta_e76()`, and the E30-D04 audit's `over()` and `grey()`. PR 2 adds the
drawn boards (RQ-5, RQ-6): their spec text and greyscale exports at their pushed heads, the PNGs
decoded here (zlib, one channel, no image library). Fourteen gates, A to N, each FAIL led by its
letter; the spec's section 15 describes each gate.

usage: e34_d04_a11y_review_audit.py [--check | --self-test | --json | --tables | --write-tables
                                     | --repin]
"""

from __future__ import annotations

import codecs
import hashlib
import importlib.util
import json
import re
import struct
import subprocess
import sys
import zlib
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "docs" / "design" / "_tools"
TOKENS = ROOT / "packages" / "ui" / "tokens"
SPEC = ROOT / "docs" / "design" / "E34" / "E34-D04.md"
PINS = TOOLS / "e34_d04_ruled_pins.txt"
BASE = "b81479ab01109ee1efc6cdedb411bd5f75ecdd66"  # main when the review was built
KM_PATH = "apps/web/src/keymap/keymap.json"
KEYS: dict[str, tuple[str, str]] = {
    "05": ("docs/plan/05-accessibility-standard.md", BASE),
    "14": ("docs/plan/14-screens-catalogue.md", BASE),
    "15": ("docs/plan/15-component-catalogue.md", BASE),
    "16": ("docs/plan/16-design-system-brief.md", BASE),
    "DS": (".claude/rules/32-design-specs.md", BASE),
    "E47-D04": ("docs/design/E47/E47-D04.md", BASE),
    "E47-D09": ("docs/design/E47/E47-D09.md", BASE),
    "KM": (KM_PATH, BASE),
}
# request rows: the unmerged specs under review, at their pushed PR heads (R-4)
RQ: dict[str, tuple[str, str]] = {
    "RQ-1": ("docs/design/E34/E34-D02.md", "b2159147c983f30dda31ec418a6346a6f1d48174"),  # #5621
    "RQ-2": ("docs/design/E34/E34-D03.md", "ba036fc5091808e0ab11cac2225d4f61e4e10998"),  # #5622
}
RQ3_HEAD = "78475be5063ecc6e553ce020f16ed2bc3bff9108"  # #5619, E28-D05
# the A-rows applied (BQ-2): each spec by content (its blob) at the PR head that carries it;
# a push changes the pushed head, never the blob
LANDED: dict[str, tuple[str, str]] = {
    "RQ-1": (
        "3dd5f17749dc2566d9ee4ea36c697e1ea6b88d57",
        "c547be2f532fca307ed9c9505b7ee21072623d5c",
    ),
    "RQ-2": (
        "438a046f617902dd450d315554fca388213699a8",
        "1108cc3d8c0a39a7f4e4857c153aed368843ba1d",
    ),
}
# each spec's own cite pins, read at its landed head: a cite inside a quoted New is the spec's own
RQ_PINS = {
    "RQ-1": "docs/design/_tools/e34_d02_ruled_pins.txt",
    "RQ-2": "docs/design/_tools/e34_d03_ruled_pins.txt",
}
# PR 2: the drawn boards, each spec by content at its pushed PR head (RQ-5, RQ-6)
BOARDS: dict[str, tuple[str, str, str, str]] = {
    "D02": (
        "#5728",
        "b9bf0a142b8ac655d38875a56e53ef5fe71242d7",
        "2ce1da817aad901022c2fd7d10c2a40bf1a0a81b",
        "docs/design/E34/E34-D02.md",
    ),
    "D03": (
        "#5729",
        "ce852b1ceb0daba0a25102a006555ea6f6714aa5",
        "b78e61ee3af04611b793421a5a12f445dfb55cf4",
        "docs/design/E34/E34-D03.md",
    ),
}
BOARD_RQ = {"D02": "RQ-1", "D03": "RQ-2"}  # the spec each boards PR draws
IMG = "docs/design/E34/img/"
FIX_FORWARD = "fix-forward slice after merge"
THEMES = ("dark", "light", "high-contrast")
BAR = {"text": 4.5, "non-text": 3.0}
SEVERITIES = ("Critical", "High", "Medium", "Low", "Info")
SCREENS = ("SCR-061", "SCR-062")
CT_B, CT_E = "<!-- ct:begin -->", "<!-- ct:end -->"
CV_B, CV_E = "<!-- cv:begin -->", "<!-- cv:end -->"
DG_B, DG_E = "<!-- dg:begin -->", "<!-- dg:end -->"
DATE = "by 2027-01-14"  # the end of Sprint 16, before E34-D05's sprint (R-2)


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
d04 = _load(TOOLS / "e30_d04_ds_motion_audit.py", "e30_d04_ds_motion_audit")


def resolve_theme(name: str) -> dict[str, Any]:
    allt: dict[str, Any] = dict(verify.load(verify.PRIMITIVES))
    allt.update(verify.merged_set(verify.THEMES[name]))
    out: dict[str, Any] = {}
    for k, v in allt.items():
        if isinstance(v, dict) and "$value" in v:
            raw = v["$value"]
            out[k] = verify.resolve(raw, allt) if isinstance(raw, str) else "composite"
    return out


T = {n: resolve_theme(n) for n in THEMES}


def rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def ratio(fg: str, bg: str) -> float:
    return float(contrast_check.contrast_ratio(rgb(fg), rgb(bg)))


# ------------------------------------------------------------------ section 9 -----------------
# id | state | fg | bg | opacity (1 or muted) | role | finding (as specified)
CT = [
    [c.strip() for c in ln.split("|")]
    for ln in """CT-01|ready glyph, raised row|status.success.strong|surface.raised|1|non-text|
CT-02|ready glyph, canvas row|status.success.strong|surface.canvas|1|non-text|
CT-03|ready glyph, hovered row|status.success.strong|surface.hover|1|non-text|
CT-04|WARN and waiting glyph, raised row|status.warning.strong|surface.raised|1|non-text|
CT-05|WARN and waiting glyph, canvas row|status.warning.strong|surface.canvas|1|non-text|
CT-06|WARN and waiting glyph, hovered row|status.warning.strong|surface.hover|1|non-text|
CT-07|rejected, blocked, stop-pending glyph, raised row|status.danger.strong|surface.raised|1|non-text|
CT-08|rejected glyph, canvas row|status.danger.strong|surface.canvas|1|non-text|
CT-09|rejected glyph, hovered row|status.danger.strong|surface.hover|1|non-text|
CT-10|unknown glyph, raised row|status.info.strong|surface.raised|1|non-text|
CT-11|unknown glyph, canvas row|status.info.strong|surface.canvas|1|non-text|
CT-12|unknown glyph, hovered row|status.info.strong|surface.hover|1|non-text|
CT-13|status word, hovered row|text.primary|surface.hover|1|text|
CT-14|queued, sent, skipped, flat word, hovered row|text.secondary|surface.hover|1|text|
CT-15|queued, sent, skipped word, canvas row|text.secondary|surface.canvas|1|text|
CT-16|waiting pill words and countdown|text.primary|status.warning.subtle|1|text|
CT-17|waiting pill glyph; summary edge and glyph|status.warning.strong|status.warning.subtle|1|non-text|
CT-18|unwind-incomplete banner text|text.primary|status.danger.subtle|1|text|
CT-19|banner edge and glyph; stop-pending line glyph|status.danger.strong|status.danger.subtle|1|non-text|
CT-20|T2 reason on the summary|text.secondary|status.warning.subtle|1|text|
CT-21|T2 reason on the banner|text.secondary|status.danger.subtle|1|text|
CT-22|T2 label of a ghost button on the summary (as specified)|text.tertiary|status.warning.subtle|1|text|F-02
CT-23|T2 label on the raised fill (as fixed)|text.tertiary|surface.raised|1|text|
CT-24|T2 menu item label|text.tertiary|surface.overlay|1|text|
CT-25|sort glyph in the header|text.tertiary|surface.hover|1|non-text|
CT-26|focus ring on the summary|focus.ring|status.warning.subtle|1|non-text|
CT-27|focus ring on the banner|focus.ring|status.danger.subtle|1|non-text|
CT-28|focus ring on a hovered row|focus.ring|surface.hover|1|non-text|
CT-29|focus ring in a confirm|focus.ring|surface.overlay|1|non-text|
CT-30|danger Confirm label|text.on-action|status.danger.default|1|text|
CT-31|muted last preview, secondary words (as specified)|text.secondary|surface.raised|muted|text|F-01
CT-32|muted last preview, ready glyph (as specified)|status.success.strong|surface.raised|muted|non-text|F-01
CT-33|muted last preview, WARN glyph (as specified)|status.warning.strong|surface.raised|muted|non-text|F-01""".splitlines()
]


def fmt(v: float, bar: float) -> str:
    return f"{v:.4f}" if round(v, 2) == bar and abs(v - bar) > 1e-9 else f"{v:.2f}"


def alpha(th: str, a: str) -> float:
    return float(T[th]["opacity.muted"]) if a == "muted" else float(a)


def measure_ct() -> list[list[str]]:
    rows = []
    for cid, state, fg, bg, a, role, fid in CT:
        bar, vals = BAR[role], []
        for th in THEMES:
            f, b, al = str(T[th]["color." + fg]), str(T[th]["color." + bg]), alpha(th, a)
            vals.append(ratio(d04.over(f, b, al) if al < 1 else f, b))
        bad = [th for th, v in zip(THEMES, vals, strict=True) if v < bar]
        verdict = "FAIL " + ", ".join(bad) + f" — {fid}" if bad else "PASS"
        op = "`opacity.muted`" if a == "muted" else "1"
        rows.append(
            [cid, state, f"`color.{fg}`", f"`color.{bg}`", op, role]
            + [fmt(v, bar) for v in vals]
            + [verdict]
        )
    return rows


# ------------------------------------------------------------------ section 10 ----------------
# id | states | a | b | channel
CV = [
    [c.strip() for c in ln.split("|")]
    for ln in """CV-01|accepted / rejected|status.success.strong|status.danger.strong|the words; tick against cross in the ring
CV-02|accepted / unknown|status.success.strong|status.info.strong|the words; tick against question in the ring
CV-03|unknown / rejected|status.info.strong|status.danger.strong|the words; question against cross in the ring
CV-04|WARN / blocked|status.warning.strong|status.danger.strong|the words; triangle against the blocked glyph
CV-05|waiting / unwinding|status.warning.strong|status.warning.strong|the words alone (one glyph, one tone)
CV-06|ready / WARN|status.success.strong|status.warning.strong|the words; check against triangle
CV-07|partial-failure summary / unwind-incomplete banner|status.warning.subtle|status.danger.subtle|the sentence; triangle against the danger glyph
CV-08|queued / sent|text.secondary|text.secondary|the words alone (one glyph, one tone)""".splitlines()
]
DEFS = ("deuteranopia", "protanopia", "tritanopia")


def compute_cv() -> list[list[str]]:
    rows = []
    for cid, states, a, b, channel in CV:
        for th in ("dark", "light"):
            x, y = str(T[th]["color." + a]), str(T[th]["color." + b])
            vals = [cvd.delta_e76(x, y)]
            vals += [cvd.delta_e76(cvd.simulate(x, d), cvd.simulate(y, d)) for d in DEFS]
            vals.append(cvd.delta_e76(d04.grey(x), d04.grey(y)))
            rows.append(
                [cid, states, f"`color.{a}` / `color.{b}`", th]
                + [f"{v:.1f}" for v in vals]
                + [channel]
            )
    return rows


CT_HEAD = "| Id | State | Foreground | Background | Opacity | Role | Dark | Light | High contrast | Verdict |"
CV_HEAD = "| Id | States | Pair | Theme | Normal | Deut. | Prot. | Trit. | Grey | Channel |"


def table_lines(head: str, rows: list[list[str]]) -> list[str]:
    sep = "| " + " | ".join("---" for _ in head.strip("|").split("|")) + " |"
    return [head, sep] + ["| " + " | ".join(r) + " |" for r in rows]


# ------------------------------------------------------------------ texts --------------------
class Texts(NamedTuple):
    spec: str
    pins: str
    files: dict[str, list[str]]  # KEY -> lines at the base
    rq: dict[str, str]  # RQ-n -> the text at its pushed head
    landed: dict[str, str]  # RQ-n -> the text with the A-rows applied, by content
    rq_pins: dict[str, str]  # RQ-n -> its own cite pins at its landed head
    boards: dict[str, str]  # D02 / D03 -> the boards spec text at its pushed head (RQ-5, RQ-6)
    board_blobs: dict[str, str]  # D02 / D03 -> that text's blob id, from git
    pngs: dict[str, bytes]  # greyscale PNG name -> its bytes at its boards head


def git_bytes(ref: str, rel: str) -> bytes:
    r = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{ref}:{rel}" if rel else ref],
        capture_output=True,
        check=False,
    )
    if r.returncode != 0:
        raise SystemExit(f"cannot read {rel} at {ref[:9]}: fetch it first")
    return r.stdout


def git_rev(spec: str) -> str:
    r = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", spec], capture_output=True, text=True, check=False
    )
    return r.stdout.strip() if r.returncode == 0 else ""


def git_show(ref: str, rel: str) -> str:
    return git_bytes(ref, rel).decode("utf-8")


G_ROW = re.compile(
    r"^\|\s*(G\d\d)\s*\|\s*`([^`]+\.png)`\s*\|[^|]+\|\s*`([0-9a-f]{64})`\s*\|", re.MULTILINE
)


def g_rows(board_text: str) -> dict[str, tuple[str, str]]:
    """The boards' section 0.1 greyscale rows: G-id -> (PNG name, sha256)."""
    return {g: (n, h) for g, n, h in G_ROW.findall(section(board_text, "### 0.1 ", "### 0.2 "))}


def read_boards() -> tuple[dict[str, str], dict[str, str], dict[str, bytes]]:
    texts = {k: git_show(head, path) for k, (_, head, _, path) in BOARDS.items()}
    blobs = {k: git_rev(f"{head}:{path}") for k, (_, head, _, path) in BOARDS.items()}
    pngs = {
        n: git_bytes(BOARDS[k][1], IMG + n)
        for k, text in texts.items()
        for n, _ in g_rows(text).values()
    }
    return texts, blobs, pngs


def read_texts() -> Texts:
    return Texts(
        SPEC.read_text(encoding="utf-8"),
        PINS.read_text(encoding="utf-8"),
        {k: git_show(ref, p).splitlines() for k, (p, ref) in KEYS.items()},
        {k: git_show(ref, p) for k, (p, ref) in RQ.items()},
        {k: git_show(blob, "") for k, (blob, _) in LANDED.items()},
        {k: git_show(LANDED[k][1], p) for k, p in RQ_PINS.items()},
        *read_boards(),
    )


def section(spec: str, start: str, end: str) -> str:
    i = spec.find(start)
    if i < 0:
        return ""
    j = spec.find(end, i + len(start))
    return spec[i : j if j > 0 else len(spec)]


def cells(ln: str) -> list[str]:
    return [c.strip() for c in ln.strip().strip("|").split("|")]


def rows_of(text: str, rx: str) -> list[list[str]]:
    return [cells(ln) for ln in text.splitlines() if re.match(rx, ln)]


CITE = re.compile(r"`(05|14|15|16|DS|E47-D04|E47-D09|KM)`:(\d+)(?:–(\d+))?")


def cites(spec: str) -> set[tuple[str, int]]:
    """Every cite of this review; an A-row's quoted Old and New are the RQ text's, not cites."""
    own = spec.replace(section(spec, "### 13.1 ", "### 13.2 "), "")
    out: set[tuple[str, int]] = set()
    for key, a, b in CITE.findall(own):
        out.add((key, int(a)))
        if b:
            out.update((key, n) for n in range(int(a) + 1, int(b) + 1))
    return out


def pins_of(pins: str) -> dict[tuple[str, int], str]:
    out = {}
    for ln in pins.splitlines():
        if ln.startswith("#") or not ln.strip():
            continue
        key, line, words = ln.split("|", 2)
        out[(key, int(line))] = words
    return out


# ------------------------------------------------------------------ the gates ----------------
def g_cites(t: Texts, p: list[str]) -> dict[str, Any]:
    cs, pins = cites(t.spec), pins_of(t.pins)
    for key, n in sorted(cs):
        lines = t.files[key]
        if n < 1 or n > len(lines) or not lines[n - 1].strip():
            p.append(f"[A] {key}:{n} is not a non-blank line at the base")
        elif (key, n) not in pins:
            p.append(f"[A] {key}:{n} is cited but not pinned")
    for (key, n), words in sorted(pins.items()):
        if (key, n) not in cs:
            p.append(f"[A] pin {key}:{n} is not cited")
        elif words not in t.files[key][n - 1]:
            p.append(f"[A] pin {key}:{n}: its words are not on the line")
    return {"cites": len(cs), "pins": len(pins)}


def parse_rendered(spec: str, b: str, e: str) -> list[list[str]]:
    body = section(spec, b, e)
    return [cells(ln) for ln in body.splitlines() if re.match(r"^\|\s*C[TV]-\d+", ln)]


def f_rows(spec: str) -> list[list[str]]:
    return rows_of(section(spec, "## 12. ", "## 13. "), r"^\|\s*F-\d+\s*\|")


def high_ids(spec: str) -> set[str]:
    return {r[0] for r in f_rows(spec) if len(r) > 1 and r[1] in ("Critical", "High")}


def g_contrast(t: Texts, p: list[str]) -> dict[str, Any]:
    want, got = measure_ct(), parse_rendered(t.spec, CT_B, CT_E)
    if len(got) != len(want):
        p.append(f"[B] section 9 has {len(got)} rows, the measurement {len(want)}")
    highs = high_ids(t.spec)
    for w in want:
        if next((r for r in got if r and r[0] == w[0]), None) != w:
            p.append(f"[B] {w[0]} differs from the measurement")
        if w[-1].startswith("FAIL") and not any(h in w[-1] for h in highs):
            p.append(f"[B] {w[0]} fails without a High F row")
    stamp = re.search(r"<!-- audit:ct=(\d+) -->", t.spec)
    if not stamp or int(stamp.group(1)) != len(CT):
        p.append(f"[B] the ct stamp does not equal {len(CT)}")
    return {"rows": len(want), "fail": sum(1 for w in want if w[-1].startswith("FAIL"))}


def g_cvd(t: Texts, p: list[str]) -> dict[str, Any]:
    want, got = compute_cv(), parse_rendered(t.spec, CV_B, CV_E)
    if len(got) != len(want):
        p.append(f"[C] section 10 has {len(got)} rows, the computation {len(want)}")
    for w in want:
        if next((r for r in got if r[:4] == w[:4]), None) != w:
            p.append(f"[C] {w[0]} {w[3]} differs from the computation")
    for r in CV:
        if not r[4].startswith("the words") and not r[4].startswith("the sentence"):
            p.append(f"[C] {r[0]} has no word or sentence carrying the state")
    grey = sum(1 for w in want if float(w[8]) < 5.0)
    return {"rows": len(want), "grey_below_5": grey}


F_HEAD = re.compile(
    r"## 12\. Findings — F (\d+) \(Critical (\d+) · High (\d+) · Medium (\d+) · Low (\d+) · "
    r"Info (\d+)\) <!-- audit:f=([\d/]+) -->"
)


TICKET = re.compile(r"\b(E\d\d-[A-Z]\d\d) \(#(\d+)\)")


def a_rows(spec: str) -> list[list[str]]:
    return rows_of(section(spec, "### 13.1 ", "### 13.2 "), r"^\|\s*A-\d+\s*\|")


def g_findings(t: Texts, p: list[str]) -> dict[str, Any]:
    rows = f_rows(t.spec)
    counts = [sum(1 for r in rows if len(r) > 1 and r[1] == s) for s in SEVERITIES]
    want = [len(rows), *counts]
    m = F_HEAD.search(t.spec)
    if not m:
        p.append("[D] the findings heading or its stamp is missing")
    else:
        if [int(x) for x in m.groups()[:6]] != want:
            p.append(f"[D] the heading says {m.groups()[:6]}, the table {want}")
        if m.group(7) != "/".join(map(str, want)):
            p.append(f"[D] the stamp says {m.group(7)}, the table {want}")
    aids = {r[0]: r for r in a_rows(t.spec)}
    for r in rows:
        if len(r) != 8 or r[1] not in SEVERITIES:
            p.append(f"[D] {r[0]}: not eight cells with a severity")
            continue
        if not r[2] or not CITE.search(r[3]) or not r[5] or not r[6]:
            p.append(f"[D] {r[0]}: a criterion, a cited line, a fix or an owner is missing")
        if ";" in r[6]:
            p.append(f"[D] {r[0]}: more than one owner")
        named = re.findall(r"A-\d+", r[7])
        if r[1] in ("Critical", "High") and (
            not named or any(a not in aids or aids[a][2] != r[0] for a in named)
        ):
            p.append(f"[D] {r[0]}: a High row without its A-rows")
        if r[1] in ("Medium", "Low") and DATE not in r[6]:
            p.append(f"[D] {r[0]}: a {r[1]} row logged without its date")
    nums: dict[str, set[str]] = {}
    for key, num in TICKET.findall(t.spec):
        nums.setdefault(key, set()).add(num)
    for key, got in sorted(nums.items()):
        if len(got) > 1:
            p.append(f"[D] {key} is given {len(got)} issue numbers")
    ids = {r[0] for r in rows}
    for ref in sorted(set(re.findall(r"\bF-\d\d\b", t.spec)) - ids):
        p.append(f"[D] {ref} is cited but not in the table")
    return dict(zip(("rows", *SEVERITIES), want, strict=True))


def heading_span(text: str, sec: str) -> tuple[int, int]:
    """The character span of section `sec` ("2.2", "7") in a spec, to its next peer heading."""
    level = "###" if "." in sec else "##"
    m = re.search(rf"^{level} {re.escape(sec)}\.? ", text, flags=re.MULTILINE)
    if not m:
        return (-1, -1)
    nxt = re.compile(rf"^#{{2,{len(level)}}} ", flags=re.MULTILINE).search(text, m.end())
    return (m.start(), nxt.start() if nxt else len(text))


_NUM_WORDS = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty"
)
NUM = _NUM_WORDS.split()


def word(n: int) -> str:
    if n < len(NUM):
        return NUM[n]
    tens, one = divmod(n, 10)
    return ("twenty", "thirty", "forty")[tens - 2] + (f"-{NUM[one]}" if one else "")


def bounded(text: str, old: str) -> list[int]:
    """Where `old` stands whole: a word character at either end is not continued in the text."""
    rx = ("(?<!\\w)" if re.match(r"\w", old) else "") + re.escape(old)
    rx += "(?!\\w)" if re.search(r"\w$", old) else ""
    return [m.start() for m in re.finditer(rx, text)]


SPEC_CITE = re.compile(r"`([A-Za-z0-9-]+)`:(\d+(?:–\d+)?)")


def g_amend(t: Texts, p: list[str]) -> dict[str, Any]:
    rows = a_rows(t.spec)
    fids = {r[0] for r in f_rows(t.spec)}
    stamp = re.search(r"<!-- audit:a=(\d+) -->", t.spec)
    if not stamp or int(stamp.group(1)) != len(rows):
        p.append(f"[E] the A-row stamp does not equal {len(rows)}")
    per = {k: 0 for k in RQ}
    for r in rows:
        tm = re.fullmatch(r"(RQ-\d) §([\d.]+)", r[1]) if len(r) == 6 else None
        if not tm or tm.group(1) not in RQ or r[2] not in fids or not r[3].startswith('"'):
            p.append(f"[E] {r[0]}: a target, an F row or a quoted Old and New is missing")
            continue
        per[tm.group(1)] += 1
        text, old, new = t.rq[tm.group(1)], r[3][1:-1], r[4][1:-1]
        a, z = heading_span(text, tm.group(2))
        at = bounded(text, old)
        if len(at) != 1 or text.count(old) != 1 or not (a <= at[0] < z):
            p.append(f"[E] {r[0]}: the Old is not once in {tm.group(1)} under §{tm.group(2)}")
        if new in text:
            p.append(f"[E] {r[0]}: the New is already in {tm.group(1)}")
        own = {ln.split("\t", 1)[0] for ln in t.rq_pins[tm.group(1)].splitlines()}
        for key, n in SPEC_CITE.findall(new):
            if f"{key}:{n}" not in own:
                p.append(f"[E] {r[0]}: its New cites {key}:{n}, not in {tm.group(1)}'s own pins")
        lt = t.landed[tm.group(1)]
        if r[5] == f"{tm.group(1)} landed":
            if lt.count(new) != 1 or old in lt.replace(new, ""):
                p.append(f"[E] {r[0]}: not landed once at {tm.group(1)}'s content")
        elif r[5] != FIX_FORWARD or lt.count(old) != 1:
            p.append(f"[E] {r[0]}: its Landed cell is neither landed nor a fix-forward slice")
    n = len(rows)
    said = (
        f"{word(n).capitalize()} A-rows <!-- audit:a={n} -->: {word(per['RQ-1'])} to "
        f"E34-D02's text, {word(per['RQ-2'])} to E34-D03's."
    )
    if said not in section(t.spec, "### 13.1 ", "### 13.2 "):
        p.append(f"[E] section 13.1 does not say: {said}")
    return {"rows": n, **per}


def g_focus(t: Texts, p: list[str]) -> dict[str, Any]:
    subs = re.split(r"^### ", section(t.spec, "## 4. ", "## 5. "), flags=re.MULTILINE)[1:]
    seen, steps = set(), 0
    for sub in subs:
        head = sub.splitlines()[0]
        n = len(re.findall(r"^\|\s*FO-\d+\s*\|", sub, flags=re.MULTILINE))
        if "**Return:**" not in sub:
            p.append(f"[F] subsection {head!r} names no return target")
        if n == 0 and "dialog" not in head and "drawer" not in head:
            p.append(f"[F] subsection {head!r} has no FO steps")
        m = re.match(r"4\.\d+ (SCR-\d+) ", head)
        if m:
            seen.add(m.group(1))
        steps += n
    for s in SCREENS:
        if s not in seen:
            p.append(f"[F] {s} has no focus-order subsection")
    return {"subsections": len(subs), "steps": steps}


HEX = re.compile(r"#[0-9A-Fa-f]{6}\b")
# the lane's public-text word list, rot13-encoded so this file does not carry the words itself
DENY_ROT13 = (
    "yrnx rkcbfrq olcnff rkcybvg nggnpx benpyr erirny haobhaqrq sybbq fgnyy qbf nqivfbel tufn"
)
DENY = tuple(codecs.decode(w, "rot13") for w in (DENY_ROT13 + " cer-nhgu").split())
LOCAL = re.compile(
    "|".join(re.escape(codecs.decode(w, "rot13")) for w in ("/ubzr/", "/gzc/", "abgrf/"))
    + r"|https?:|www\.|\.local\b"
)
STAMPS = ("f", "a", "ct", "dg")


def g_hygiene(t: Texts, p: list[str]) -> dict[str, Any]:
    for name, text in (("spec", t.spec), ("pins", t.pins)):
        low = text.lower()
        for i, w in enumerate(DENY, 1):
            if w in low:  # named by its place in the list, so the output never carries it
                p.append(f"[G] {name}: public-text deny word no. {i} of the list")
        hit = LOCAL.search(text)
        if hit:
            p.append(f"[G] {name}: a local path, host or URL: {hit.group(0)}")
        if HEX.search(text):
            p.append(f"[G] {name}: a hex colour")
    for k in re.findall(r"<!-- audit:([a-z_]+)=", t.spec):
        if k not in STAMPS:
            p.append(f"[G] unknown stamp {k}")
    return {"deny_words": len(DENY)}


RATE = re.compile(r"^(\d+) per (\d+(?:\.\d+)?) s")
ASSERTIVE = ("LR-04", "LR-05", "LR-06", "LR-07", "LR-12")  # rejections and safety outcomes


def g_live(t: Texts, p: list[str]) -> dict[str, Any]:
    rows = rows_of(section(t.spec, "## 7. ", "## 8. "), r"^\|\s*LR-\d+\s*\|")
    for r in rows:
        if len(r) != 5 or r[2] not in ("polite", "assertive", "off") or not r[3]:
            p.append(f"[H] {r[0]}: no politeness or no rate")
            continue
        m = RATE.match(r[3])
        if m and int(m.group(1)) / float(m.group(2)) > 0.5:
            p.append(f"[H] {r[0]}: a rate above `05`'s one update per 2 s")
        if r[0] in ASSERTIVE and (r[2] != "assertive" or not r[3].startswith("once")):
            p.append(f"[H] {r[0]}: a rejection or safety outcome not said once, assertively")
        if r[2] == "assertive" and RATE.match(r[3]):
            p.append(f"[H] {r[0]}: an assertive row throttled")
    return {"rows": len(rows)}


def keymap(t: Texts) -> dict[str, list[str]]:
    data = json.loads("\n".join(t.files["KM"]))
    out: dict[str, list[str]] = {}
    for c in data["commands"]:
        out.setdefault(str(c.get("defaultBinding", "")), []).append(str(c["id"]))
    return {k: sorted(v) for k, v in out.items()}


def g_keys(t: Texts, p: list[str]) -> dict[str, Any]:
    km = keymap(t)
    rows = rows_of(section(t.spec, "## 5. ", "## 6. "), r"^\|\s*KB-\d+\s*\|")
    for r in rows:
        key = r[2].strip("`")
        want = ", ".join(f"`{c}`" for c in km.get(key, [])) or "none"
        if r[4] != want:
            p.append(f"[I] {r[0]}: the keymap binds {key} to {want}")
        if r[5].startswith("non-compliant") and not any(h in r[5] for h in high_ids(t.spec)):
            p.append(f"[I] {r[0]}: non-compliant without a High F row")
    if "Ctrl+Shift+Enter" in km:
        p.append("[I] the keymap now binds Ctrl+Shift+Enter: re-read KB-01 and G-1")
    return {"rows": len(rows), "chords": len(km)}


def words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", s.lower())


def label_in_name(label: str, name: str) -> bool:
    lw, nw = words(label), words(name)
    return any(nw[i : i + len(lw)] == lw for i in range(len(nw) - len(lw) + 1))


# the name forms F-03 replaced (AN-01, AN-02, A-08); none may stand in a landed spec
OLD_NAMES = (
    '"Send group …7c1e to 5 accounts: …"',
    "accepted legs of group …7c1e…",
    'accessible name with "…"',
)


def g_names(t: Texts, p: list[str]) -> dict[str, Any]:
    rows = rows_of(section(t.spec, "## 6. ", "## 7. "), r"^\|\s*AN-\d+\s*\|")
    fails = 0
    for r in rows:
        if len(r) != 6:
            p.append(f"[J] {r[0]}: not six cells")
            continue
        if r[2].startswith("("):
            continue
        got = "pass" if label_in_name(r[2], r[3]) else "FAIL"
        fails += got == "FAIL"
        if r[4] != got:
            p.append(f"[J] {r[0]}: the label check says {got}")
        if not label_in_name(r[2], r[5]) or words(r[5])[: len(words(r[2]))] != words(r[2]):
            p.append(f"[J] {r[0]}: the fixed name does not begin with its visible label")
        if "…" in r[5]:
            p.append(f"[J] {r[0]}: the fixed name keeps an ellipsis")
    for k, lt in t.landed.items():
        for i, form in enumerate(OLD_NAMES, 1):
            if form in lt:
                p.append(f"[J] {k} landed still gives the old name form no. {i} (F-03)")
    if fails and "F-03" not in high_ids(t.spec):
        p.append("[J] a 2.5.3 FAIL without its High F row")
    return {"rows": len(rows), "fail": fails}


MOMENTS = ("Moment 1 — the preview is ready", "Moment 2 — the partial failure is announced")
MOMENT3 = "Moment 3 — the destructive confirmation"
ORDER = ("sub_002 rejected", "sub_004 rejected", "are open and protected")


def g_rulings(t: Texts, p: list[str]) -> dict[str, Any]:
    s14 = section(t.spec, "### 1.4 ", "## 2. ")
    for k, (_, head) in RQ.items():
        if f"`{head}`" not in s14:
            p.append(f"[K] {k}'s pushed head is not pinned in section 1.4")
    if f"`{RQ3_HEAD}`" not in s14:
        p.append("[K] RQ-3's head is not pinned in section 1.4")
    for k, (blob, head) in LANDED.items():
        if f"content `{blob}` at head `{head}`" not in s14:
            p.append(f"[K] {k}'s landed content is not pinned in section 1.4")
    if re.search(r"`(D02|D03|E34-D02|E34-D03)`:\d", t.spec):
        p.append("[K] a line cite into an unmerged spec (request rows only)")
    s8 = section(t.spec, "## 8. ", "## 9. ")
    for name in (*MOMENTS, MOMENT3):
        sub = section(s8, name, "### ")
        n = len(re.findall(r"^\|\s*SR-\d+\s*\|", sub, flags=re.MULTILINE))
        if n < 3:
            p.append(f"[K] section 8 lacks {name!r} with three steps")
    m2 = section(s8, MOMENTS[1], "### ")
    pos = [m2.find(w) for w in ORDER]
    if -1 in pos or pos != sorted(pos):
        p.append("[K] moment 2 does not say each rejection before the protection sentence")
    m3 = section(s8, MOMENT3, "## ")
    first = rows_of(m3, r"^\|\s*SR-\d+\s*\|")
    if not first or "Cancel" not in first[0][3]:
        p.append("[K] moment 3 does not open on Cancel")
    return {"request_rows": len(RQ) + 1}


ONE_SHOT = 'one-shot `role="alert"` node'
ATOMIC = '`role="alert"` is implicitly `aria-atomic="true"`'
GROUP_ID = re.compile(r"group …[0-9a-f]{4}")


BARE_ALERT = re.compile(r'`role="alert"`,? once')
# the single-message summaries stay one alert (A-24): refused whole, all failed, all-or-none unwound
WHOLE = ("| S061-11 ", "| S061-22 ", "| S061-23 ")
EXEMPT = ("one-shot", "all-failed", "unwind-incomplete")


def bare_summary_alerts(text: str) -> list[int]:
    """Lines that still call a growing summary a bare `role="alert"` once (BQ-7)."""
    out = []
    for i, ln in enumerate(text.splitlines(), 1):
        if "summary" not in ln or ln.startswith(WHOLE):
            continue
        for c in re.split(r"[|;]", ln):
            if BARE_ALERT.search(c) and not any(w in c for w in EXEMPT):
                out.append(i)
                break
    return out


def g_ruled(t: Texts, p: list[str]) -> dict[str, Any]:
    """The #998 ruling: BQ-7 as amended (one-shot nodes) and BQ-6 ("group ending 7c1e")."""
    s7 = section(t.spec, "## 7. ", "## 8. ")
    lr = {r[0]: r for r in rows_of(s7, r"^\|\s*LR-\d+\s*\|")}
    if ONE_SHOT not in " ".join(lr.get("LR-04", [])):
        p.append("[L] LR-04: a rejection is not its own one-shot alert node (BQ-7)")
    if "one-shot" not in " ".join(lr.get("LR-05", [])):
        p.append("[L] LR-05: the protection sentence is not its own one-shot (BQ-7)")
    if "never a rejection" not in " ".join(lr.get("LR-03", [])):
        p.append("[L] LR-03: the polite progress line may carry a rejection (BQ-7)")
    callout = [r for r in lr.values() if "summary, visible" in r[1]]
    if len(callout) != 1 or callout[0][2] != "off":
        p.append('[L] the visible summary is not one aria-live="off" row (BQ-7)')
    if ATOMIC not in s7:
        p.append("[L] section 7 does not state the implicit aria-atomic behaviour (BQ-7)")
    for k, lt in t.landed.items():
        for i in bare_summary_alerts(lt):
            p.append(f'[L] {k} landed line {i}: a summary still a bare role="alert" once (BQ-7)')
    named = [(r[0], r[5]) for r in rows_of(section(t.spec, "## 6. ", "## 7. "), r"^\|\s*AN-")]
    named += [(r[0], r[4]) for r in a_rows(t.spec)]
    s8 = section(t.spec, "## 8. ", "## 9. ")
    named += [(r[0], r[2]) for r in rows_of(s8, r"^\|\s*SR-\d+") if r[3] != "Confirm"]
    for rid, cell in named:
        if GROUP_ID.search(cell):
            p.append(f'[L] {rid}: a group read with an ellipsis, not "group ending" (BQ-6)')
    return {"names": len(named)}


# ------------------------------------------------------------------ PR 2: drawn greyscale -----
class GreyPng:
    """An 8-bit RGB, non-interlaced PNG, decoded row by row on demand, channel 0 only.

    The PNG filters work per channel (left, up and up-left of the same channel), so one channel
    decodes alone; a greyscale export carries R = G = B.
    """

    def __init__(self, data: bytes) -> None:
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError("not a PNG")
        i, idat, head = 8, [], b""
        while i < len(data):
            (n,) = struct.unpack(">I", data[i : i + 4])
            kind = data[i + 4 : i + 8]
            if kind == b"IHDR":
                head = data[i + 8 : i + 8 + n]
            elif kind == b"IDAT":
                idat.append(data[i + 8 : i + 8 + n])
            i += 12 + n
        self.w, self.h, depth, colour, _, _, lace = struct.unpack(">IIBBBBB", head)
        if (depth, colour, lace) != (8, 2, 0):
            raise ValueError("not 8-bit RGB, non-interlaced")
        self.raw = zlib.decompress(b"".join(idat))
        self.rows: list[bytes] = []

    def level(self, x: int, y: int) -> int | None:
        if not (0 <= x < self.w and 0 <= y < self.h):
            return None
        st, w = 3 * self.w + 1, self.w
        while len(self.rows) <= y:
            k = len(self.rows)
            f, cur = self.raw[k * st], list(self.raw[k * st + 1 : (k + 1) * st : 3])
            prev = self.rows[-1] if self.rows else bytes(w)
            if f == 1:
                for j in range(1, w):
                    cur[j] = (cur[j] + cur[j - 1]) & 255
            elif f == 2:
                cur = [(a + b) & 255 for a, b in zip(cur, prev, strict=True)]
            elif f == 3:
                for j in range(w):
                    cur[j] = (cur[j] + ((cur[j - 1] if j else 0) + prev[j]) // 2) & 255
            elif f == 4:
                for j in range(w):
                    a, b, c = (cur[j - 1], prev[j], prev[j - 1]) if j else (0, prev[j], 0)
                    pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                    cur[j] = (cur[j] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
            self.rows.append(bytes(cur))
        return self.rows[y][x]


_PNG: dict[int, GreyPng] = {}


def png_level(data: bytes, x: int, y: int) -> int | None:
    key = id(data)
    if key not in _PNG:
        _PNG[key] = GreyPng(data)
    return _PNG[key].level(x, y)


def grey_de(a: int, b: int) -> float:
    return float(cvd.delta_e76("#" + f"{a:02X}" * 3, "#" + f"{b:02X}" * 3))


DASH = "—"
XY = re.compile(r"^(\d+), (\d+)$")
LEVELS = re.compile(r"^(\d+) / (\d+)$")
EXPORT = re.compile(r"^(D02|D03) (G\d\d)$")


def dg_rows(spec: str) -> list[list[str]]:
    return rows_of(section(spec, DG_B, DG_E), r"^\|\s*DG-\d+\s*\|")


def export_shas(spec: str) -> dict[str, str]:
    s16 = section(spec, "### 16.1 ", "### 16.2 ")
    return {r[0]: r[4].strip("`") for r in rows_of(s16, r"^\|\s*D0[23] G\d\d\s*\|") if len(r) == 5}


def g_drawn(t: Texts, p: list[str]) -> dict[str, Any]:
    s16 = section(t.spec, "## 16. ", "## 17. ")
    for k, (pr, head, blob, _) in BOARDS.items():
        if f"{pr} at head `{head}`, if {pr} merges as is" not in s16:
            p.append(f"[M] {k}'s boards head is not pinned in section 16 (R-4)")
        if f"content `{blob}` at head `{head}`, if {pr} merges as is" not in t.spec:
            p.append(f"[M] {k}'s boards content is not pinned in section 1.4")
        if t.board_blobs[k] != blob:
            p.append(f"[M] {k}'s boards text is not the pinned content")
    listed = export_shas(t.spec)
    for k, text in t.boards.items():
        for g, (name, sha) in g_rows(text).items():
            got = hashlib.sha256(t.pngs.get(name, b"")).hexdigest()
            if got != sha:
                p.append(f"[M] {k} {g}: the export's bytes are not its section 0.1 sha256")
            if listed.get(f"{k} {g}") != sha:
                p.append(f"[M] {k} {g}: section 16.1 does not give its sha256")
    want = {(w[0], w[3]): w for w in compute_cv()}
    chans = {r[0]: r[4] for r in CV}
    covered, measured = set(), 0
    for r in dg_rows(t.spec):
        if len(r) != 12 or (r[1], r[2]) not in want:
            p.append(f"[M] {r[0]}: not twelve cells with a CV pair and theme")
            continue
        covered.add((r[1], r[2]))
        if r[9] != want[(r[1], r[2])][8]:
            p.append(f"[M] {r[0]}: the computed cell is not section 10's")
        if r[3] == DASH:
            if any(c != DASH for c in (r[4], r[6], r[7], r[8], r[10])) or not r[11].startswith(
                "not drawn"
            ):
                p.append(f"[M] {r[0]}: a pair not drawn carries a reading")
            continue
        measured += 1
        m, a, b, lv = EXPORT.match(r[3]), XY.match(r[6]), XY.match(r[7]), LEVELS.match(r[8])
        if not (m and a and b and lv):
            p.append(f"[M] {r[0]}: an export, a place or a level is not readable")
            continue
        text = t.boards[m.group(1)]
        name = g_rows(text).get(m.group(2), ("", ""))[0]
        for fr in re.findall(r"`([^`]+)`", r[4]) or [""]:
            if not fr or f"`{fr}`" not in text:
                p.append(f"[M] {r[0]}: the frame {fr!r} is not in the boards' text")
        read = [
            png_level(t.pngs[name], int(xy.group(1)), int(xy.group(2))) if name else None
            for xy in (a, b)
        ]
        levels = [int(lv.group(1)), int(lv.group(2))]
        if read != levels:
            p.append(f"[M] {r[0]}: the export reads {read}, not {levels}")
        drawn = grey_de(*levels)
        if r[10] != f"{drawn:.1f}":
            p.append(f"[M] {r[0]}: the drawn cell is not the ΔE76 of its levels")
        grade = f"Info (F-17): {chans[r[1]]}" if drawn < 5 else "compliant (5 or more)"
        if r[11] != grade:
            p.append(f"[M] {r[0]}: graded {r[11]!r}, the drawn value gives {grade!r}")
    for key in sorted(set(want) - covered):
        p.append(f"[M] {key[0]} {key[1]} has no section 16 row")
    stamp = re.search(r"<!-- audit:dg=(\d+) -->", t.spec)
    if not stamp or int(stamp.group(1)) != measured:
        p.append(f"[M] the dg stamp does not equal {measured}")
    return {"rows": len(covered), "drawn": measured, "exports": len(t.pngs)}


SIGN_OPEN = "**Owner sign-off (C-10.1):** open"


def g_signoff(t: Texts, p: list[str]) -> dict[str, Any]:
    s17 = section(t.spec, "## 17. ", "\n## 18. ")
    t1 = {r[0]: r for r in rows_of(section(s17, "### 17.1 ", "### 17.2 "), r"^\|\s*F-\d+\s*\|")}
    t2 = {r[0]: r for r in rows_of(section(s17, "### 17.2 ", "### 17.3 "), r"^\|\s*F-\d+\s*\|")}
    targets = {r[0]: r[1].split(" ")[0] for r in a_rows(t.spec) if len(r) == 6}
    news = {r[0]: r[4][1:-1] for r in a_rows(t.spec) if len(r) == 6}
    rq_board = {v: k for k, v in BOARD_RQ.items()}
    for f in f_rows(t.spec):
        if len(f) != 8:
            continue
        sev, arows = f[1], re.findall(r"A-\d+", f[7])
        if sev in ("Critical", "High"):
            row = t1.get(f[0])
            if not row or re.findall(r"A-\d+", row[2]) != arows or row[4] != "applied":
                p.append(f"[N] {f[0]}: a blocker not recorded applied with its own A-rows")
                continue
            for aid in arows:
                rq, new = targets.get(aid, ""), news.get(aid, "")
                if not rq or t.landed[rq].count(new) != 1:
                    p.append(f"[N] {aid}: its New is not once in {rq} landed")
                if not rq or t.boards[rq_board[rq]].count(new) != 1:
                    p.append(f"[N] {aid}: its New is not once in the boards' content")
        elif sev in ("Medium", "Low"):
            row = t2.get(f[0])
            owner = f[6].split(";")[0].replace(" · " + DATE, "")  # two owners are gate D's
            if not row or len(row) != 6 or re.findall(r"A-\d+", row[2]) != arows:
                p.append(f"[N] {f[0]}: a {sev} row not logged with its A-rows")
            elif row[3] != owner or row[4] != DATE.removeprefix("by "):
                p.append(f"[N] {f[0]}: logged without its owner or its date")
    extra = (set(t1) | set(t2)) - {f[0] for f in f_rows(t.spec) if f[1] != "Info"}
    for fid in sorted(extra):
        p.append(f"[N] {fid}: recorded but not a Critical to Low row")
    if SIGN_OPEN not in s17 or re.search(r"approved by|signed by", s17, flags=re.IGNORECASE):
        p.append("[N] the owner's sign-off line is not left open")
    return {"blockers": len(t1), "logged": len(t2)}


GATES: list[tuple[str, Callable[[Texts, list[str]], dict[str, Any]]]] = [
    ("A", g_cites),
    ("B", g_contrast),
    ("C", g_cvd),
    ("D", g_findings),
    ("E", g_amend),
    ("F", g_focus),
    ("G", g_hygiene),
    ("H", g_live),
    ("I", g_keys),
    ("J", g_names),
    ("K", g_rulings),
    ("L", g_ruled),
    ("M", g_drawn),
    ("N", g_signoff),
]


def evaluate(t: Texts | None = None) -> tuple[list[str], dict[str, Any]]:
    t = read_texts() if t is None else t
    p: list[str] = []
    return p, {k: g(t, p) for k, g in GATES}


# ------------------------------------------------------------------ self-test ----------------
def sp(old: str, new: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        if old not in t.spec:
            raise SystemExit(f"self-test: the anchor {old!r} is not in the spec")
        return t._replace(spec=t.spec.replace(old, new, 1))

    return f


def row_sub(rid: str, old: str, new: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        row = next(ln for ln in t.spec.splitlines() if re.match(rf"^\|\s*{rid}\s*\|", ln))
        if old not in row:
            raise SystemExit(f"self-test: {old!r} is not in {rid}")
        return t._replace(spec=t.spec.replace(row, row.replace(old, new, 1), 1))

    return f


def pin_words_off(t: Texts) -> Texts:
    ln = next(x for x in t.pins.splitlines() if x.startswith("05|"))
    return t._replace(pins=t.pins.replace(ln, ln + " (moved)", 1))


def deny_in_prose(t: Texts) -> Texts:
    return sp(
        "## 15. The audit tool", f"## 15. The audit tool ({codecs.decode('sybbq', 'rot13')})"
    )(t)


def rq_moved(t: Texts) -> Texts:
    old = "a re-preview: the last table stays, muted;"
    return t._replace(rq={**t.rq, "RQ-1": t.rq["RQ-1"].replace(old, old + " " + old, 1)})


def landed_back(t: Texts) -> Texts:
    new = 'protection "—", its text "no position" for assistive technology'
    return t._replace(landed={**t.landed, "RQ-2": t.landed["RQ-2"].replace(new, 'protection "—"')})


def old_name_back(t: Texts) -> Texts:
    extra = '\nIts accessible name with "…" again.\n'
    return t._replace(landed={**t.landed, "RQ-2": t.landed["RQ-2"] + extra})


def bare_alert_back(t: Texts) -> Texts:
    extra = '\n| M62-99 | x | the summary `role="alert"` once |\n'
    return t._replace(landed={**t.landed, "RQ-2": t.landed["RQ-2"] + extra})


def sec_row_sub(head: str, rid: str, old: str, new: str) -> Callable[[Texts], Texts]:
    """row_sub inside one section, for an id that also stands in an earlier table."""

    def f(t: Texts) -> Texts:
        body = section(t.spec, head, "\n## ")
        row = next(ln for ln in body.splitlines() if re.match(rf"^\|\s*{rid}\s*\|", ln))
        if old not in row:
            raise SystemExit(f"self-test: {old!r} is not in {rid} under {head!r}")
        return t._replace(spec=t.spec.replace(body, body.replace(row, row.replace(old, new, 1))))

    return f


def drop_row(rid: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        row = next(ln for ln in t.spec.splitlines() if re.match(rf"^\|\s*{rid}\s*\|", ln))
        return t._replace(spec=t.spec.replace(row + "\n", "", 1))

    return f


def board_new_gone(t: Texts) -> Texts:
    new = "the table holds the last preview at full opacity"
    return t._replace(boards={**t.boards, "D02": t.boards["D02"].replace(new, "the table", 1)})


MUTATIONS: list[tuple[str, Callable[[Texts], Texts]]] = [
    ("A: a pin's words no longer on its line", pin_words_off),
    ("B: a measured contrast cell retyped", row_sub("CT-13", "PASS", "PASS?")),
    ("C: a computed greyscale cell retyped", row_sub("CV-07", "dark", "dusk")),
    ("D: the findings stamp off by one", sp("f=19/0/5/9/2/3", "f=19/0/5/9/2/2")),
    ("D: a finding with two owners", row_sub("F-11", "E34-D03 (#997)", "E34-D03 (#997); E34-D02")),
    ("D: a Medium row logged without its date", row_sub("F-13", " · by 2027-01-14", "")),
    ("D: a ticket key given two issue numbers", row_sub("F-19", "(#1179)", "(#1145)")),
    ("E: an Old not in its target", sp('"a re-preview: the last', '"a re-preview, the last')),
    ("E: an Old found twice in its target", rq_moved),
    ("E: a per-target A count retyped", sp("seventeen to E34-D03's", "ten to E34-D03's")),
    ("E: an Old truncated mid-word", row_sub("A-21", 'boxes gated"', 'boxes gate"')),
    (
        "E: a New's cite not in its target's pins",
        row_sub("A-14", "before Send (`14`:1503)", "before Send (`14`:1502)"),
    ),
    ("E: an A-row not landed at its content", landed_back),
    (
        "F: a subsection loses its return",
        sp("**Return:** the menu returns", "Then the menu returns"),
    ),
    ("G: a deny word in prose", deny_in_prose),
    ("H: a rejection said politely", row_sub("LR-04", "| assertive", "| polite")),
    ("H: progress said once a second", row_sub("LR-08", "1 per 2 s", "1 per 1 s")),
    ("I: a keymap column retyped", row_sub("KB-07", "`positions.close`", "none")),
    ("J: a label check retyped", row_sub("AN-06", "| FAIL", "| pass")),
    ("J: a fixed name loses its label", row_sub("AN-06", "| Close group: all", "| Close all")),
    ("J: an old name form back in a landed spec", old_name_back),
    ("K: a line cite into an unmerged spec", sp("RQ-1 §7 names a", "`D02`:277 names a")),
    ("K: a landed content pin retyped", sp("content `3dd5f1774", "content `3dd5f1775")),
    ("L: the visible summary made assertive", row_sub("LR-15", "| off ", "| assertive ")),
    ("L: a rejection back on the growing summary", row_sub("LR-04", "its own one-shot", "the")),
    ("L: a landed summary a bare alert again", bare_alert_back),
    (
        "L: a heard name reads the group id with an ellipsis",
        row_sub("SR-10", "ending 7c1e", "…7c1e"),
    ),
    (
        "K: the protection sentence said first",
        sp("| SR-06 |", "| SR-06 | are open and protected |"),
    ),
    ("M: a drawn level retyped", row_sub("DG-01", "172 / 184", "172 / 183")),
    ("M: a place moved off its element", row_sub("DG-09", "563, 1455", "563, 1440")),
    ("M: a drawn ΔE retyped", row_sub("DG-09", "| 9.9 ", "| 6.5 ")),
    ("M: a computed cell retyped", row_sub("DG-18", "| 1.7 ", "| 1.8 ")),
    ("M: a pair below 5 graded compliant", row_sub("DG-15", "Info (F-17): the words;", "x")),
    ("M: a frame not on the boards", row_sub("DG-05", "/leg-unknown`", "/leg-lost`")),
    ("M: an export's sha256 retyped", row_sub("D03 G07", "`eb4517b88", "`eb4517b89")),
    ("M: a pair and theme left out", drop_row("DG-22")),
    ("M: the dg stamp off by one", sp("audit:dg=17", "audit:dg=16")),
    ("M: a boards head no longer as is", sp("if #5729 merges as is (", "if #5729 merges (")),
    ("N: a blocker loses an A-row", sec_row_sub("### 17.1 ", "F-01", "A-01, A-02, ", "A-01, ")),
    ("N: a blocker not applied", sec_row_sub("### 17.1 ", "F-04", "| applied", "| pending")),
    ("N: a Medium row logged without its date", sec_row_sub("### 17.2 ", "F-12", "2027-", "2028-")),
    (
        "N: a Low row with another owner",
        sec_row_sub("### 17.2 ", "F-16", "D03 (#997)", "Q05 (#1179)"),
    ),
    ("N: a New gone from the boards' content", board_new_gone),
    ("N: the owner's line signed", sp("C-10.1):** open", "C-10.1):** approved by the owner")),
]


def self_test() -> int:
    base = read_texts()
    p0, _ = evaluate(base)
    bad = int(bool(p0))
    if p0:
        print(f"FAIL the base itself has {len(p0)} FAIL")
    for name, m in MUTATIONS:
        p1, _ = evaluate(m(base))
        new = [x for x in p1 if x not in p0]
        ok = len(new) >= 1 and all(x.startswith("[" + name[0] + "]") for x in new)
        bad += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {name}: {len(new)} new FAIL {new[:2]}")
    again, _ = evaluate(read_texts())
    if again != p0:
        bad += 1
        print("FAIL a re-run differs from the base result")
    print(f"--self-test: {'ok' if not bad else 'FAIL'} - {len(MUTATIONS)} mutations in memory")
    return int(bad > 0)


def write_tables() -> None:
    s = SPEC.read_text(encoding="utf-8")
    for b, e, head, rows in (
        (CT_B, CT_E, CT_HEAD, measure_ct()),
        (CV_B, CV_E, CV_HEAD, compute_cv()),
    ):
        i, j = s.index(b) + len(b), s.index(e)
        s = s[:i] + "\n\n" + "\n".join(table_lines(head, rows)) + "\n\n" + s[j:]
    SPEC.write_text(s, encoding="utf-8")


def repin() -> None:
    t = read_texts()
    old = pins_of(t.pins) if PINS.exists() else {}
    out = [
        "# E34-D04 pins: KEY|line|words that stand on that line at the base (gate A).",
        "# `--repin` keeps every pin still cited and adds the opening words of a new cite.",
    ]
    for key, n in sorted(cites(t.spec), key=lambda c: (list(KEYS).index(c[0]), c[1])):
        words_ = old.get((key, n)) or t.files[key][n - 1].strip()[:60].rstrip()
        out.append(f"{key}|{n}|{words_}")
    PINS.write_text("\n".join(out) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    arg = argv[1] if len(argv) > 1 else "--check"
    if arg == "--tables":
        print("\n".join(table_lines(CT_HEAD, measure_ct())))
        print("\n".join(table_lines(CV_HEAD, compute_cv())))
        return 0
    if arg == "--write-tables":
        write_tables()
        return 0
    if arg == "--repin":
        repin()
        return 0
    if arg == "--self-test":
        return self_test()
    problems, out = evaluate()
    if arg == "--json":
        print(json.dumps({"gates": out, "fail": problems}, indent=1))
        return int(bool(problems))
    for k, _ in GATES:
        print(f"{k}. {out[k]}")
    for x in problems:
        print("FAIL", x)
    print(f"rc {int(bool(problems))}")
    return int(bool(problems))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
