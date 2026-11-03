"""E28-D05 (#841) audit: the accessibility review of the six profile and trade-group surfaces.

Stdlib only, offline (`python3 -I -B`). It reads the spec and the pins file from the working tree
and every cited file AS TEXT at its pin with `git show`: the base on `main` (E28-D03's text is merged
as #5463), and the boards head of #5482, PENDING. It imports, never copies:
`contrast_check.py`'s `contrast_ratio()`, `verify_tokens.py`'s resolver,
`docs/research/_tools/cvd_simulate.py`'s `simulate()` and `delta_e76()`, and the E30-D04 audit's
`over()` and `grey()`. Eleven gates, A cites to K rulings, each FAIL led by its letter; the spec's
section 18 describes each gate.

usage: e28_d05_a11y_review_audit.py [--check | --self-test | --json | --tables | --write-tables
                                     | --repin]
"""

from __future__ import annotations

import codecs
import hashlib
import importlib.util
import json
import math
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "docs" / "design" / "_tools"
TOKENS = ROOT / "packages" / "ui" / "tokens"
SPEC = ROOT / "docs" / "design" / "E28" / "E28-D05.md"
PINS = TOOLS / "e28_d05_ruled_pins.txt"
BASE = "a7d659a5bee5d06a28950f324800f84dc3853e6f"  # main when the BQ rulings were folded
MERGED = "0af333fa0d"  # #5463, E28-D03 text, merged; read on main (BASE)
BOARDS = "3b23ab11a88e37cf76071fb99e3a74a320f0a30d"  # #5482, the boards head, PENDING
D03_PATH = "docs/design/E28/E28-D03.md"
KEYS: dict[str, tuple[str, str]] = {
    "05": ("docs/plan/05-accessibility-standard.md", BASE),
    "14": ("docs/plan/14-screens-catalogue.md", BASE),
    "15": ("docs/plan/15-component-catalogue.md", BASE),
    "15B": ("docs/plan/15-component-catalogue.md", BOARDS),
    "DS": (".claude/rules/32-design-specs.md", BASE),
    "D02": ("docs/design/E28/E28-D02.md", BASE),
    "D03": (D03_PATH, BASE),
    "D03B": (D03_PATH, BOARDS),
    "E09-D06": ("docs/design/E09/E09-D06.md", BASE),
    "E09-D09": ("docs/design/E09/E09-D09.md", BASE),
    "E47-D04": ("docs/design/E47/E47-D04.md", BASE),
    "E47-D09": ("docs/design/E47/E47-D09.md", BASE),
    "E27-D05": ("docs/design/E27/E27-D05.md", BASE),
    "E17-D01": ("docs/design/E17/E17-D01.md", BASE),
}
THEMES = ("dark", "light", "high-contrast")
BAR = {"text": 4.5, "non-text": 3.0}
SEVERITIES = ("Critical", "High", "Medium", "Low", "Info")
SCREENS = ("SCR-130", "SCR-131", "SCR-132", "SCR-133", "SCR-062", "SCR-061")
CT_B, CT_E = "<!-- ct:begin -->", "<!-- ct:end -->"
CV_B, CV_E = "<!-- cv:begin -->", "<!-- cv:end -->"
VIEWPORT_H = 800  # the minimum viewport height (E28-D03 §10.3, `16` §8)
OVERSCAN = 10  # rows drawn beyond the visible ones (PROPOSED here, §3)


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


# ------------------------------------------------------------------ section 10 ----------------
# id | state | fg | bg | opacity | role | finding (as specified; board 07 does not draw it)
CT = [
    [c.strip() for c in ln.split("|")]
    for ln in """CT-01|allowed box on the card|action.primary.default|surface.raised|1|non-text|
CT-02|allowed box on an odd row|action.primary.default|surface.canvas|1|non-text|
CT-03|allowed box under hover|action.primary.default|surface.hover|1|non-text|
CT-04|check glyph on the allowed box|text.on-action|action.primary.default|1|non-text|
CT-05|blocked border and close glyph, card|status.danger.strong|surface.raised|1|non-text|
CT-06|blocked, odd row; excluded glyph|status.danger.strong|surface.canvas|1|non-text|
CT-07|not-allowed outline, card|text.tertiary|surface.raised|1|non-text|
CT-08|not-allowed outline, odd row|text.tertiary|surface.canvas|1|non-text|
CT-09|cell word, allowed or blocked|text.primary|surface.raised|1|text|
CT-10|cell word, not allowed|text.secondary|surface.raised|1|text|
CT-11|cell word, not allowed, odd row|text.secondary|surface.canvas|1|text|
CT-12|changed edge, card|border.selected|surface.raised|1|non-text|
CT-13|changed edge, odd row|border.selected|surface.canvas|1|non-text|
CT-14|T2 cell word|text.tertiary|surface.raised|1|text|
CT-15|T2 notice reason|text.secondary|surface.raised|1|text|
CT-16|sticky header text|text.primary|surface.hover|1|text|
CT-17|ready segment, card|status.success.strong|surface.raised|1|non-text|
CT-18|ready segment, odd row|status.success.strong|surface.canvas|1|non-text|
CT-19|not-ready outline, card; WARN glyph|status.warning.strong|surface.raised|1|non-text|
CT-20|not-ready outline, odd row; WARN glyph|status.warning.strong|surface.canvas|1|non-text|
CT-21|unknown outline, card|text.tertiary|surface.raised|1|non-text|
CT-22|readiness text|text.primary|surface.raised|1|text|
CT-23|WARN word and reason row, odd row|text.primary|surface.canvas|1|text|
CT-24|excluded reason, secondary words|text.secondary|surface.canvas|1|text|
CT-25|ready glyph, odd row|status.success.strong|surface.canvas|1|non-text|
CT-26|override and relaxing pill word|text.primary|status.warning.subtle|1|text|
CT-27|override pill border|status.warning.strong|status.warning.subtle|1|non-text|
CT-28|refusal summary text|text.primary|status.danger.subtle|1|text|
CT-29|footer bar text|text.primary|surface.overlay|1|text|
CT-30|focus ring on the card|focus.ring|surface.raised|1|non-text|
CT-31|focus ring on the canvas|focus.ring|surface.canvas|1|non-text|
CT-32|focus ring on a sticky header or hovered cell|focus.ring|surface.hover|1|non-text|
CT-33|focus ring in a dialog and the footer|focus.ring|surface.overlay|1|non-text|
CT-34|focus ring on a selected row|focus.ring|action.selected|1|non-text|
CT-35|focus ring on a field|focus.ring|surface.sunken|1|non-text|
CT-36|focus ring on a warning row|focus.ring|status.warning.subtle|1|non-text|
CT-37|focus ring on the refusal summary|focus.ring|status.danger.subtle|1|non-text|
CT-38|muted table, secondary text (as specified, not drawn on board 07)|text.secondary|surface.raised|0.7|text|F-01
CT-39|muted table, primary text (as specified, not drawn on board 07)|text.primary|surface.raised|0.7|text|F-01
CT-40|muted table, LIVE border (as specified, not drawn on board 07)|env.live|surface.raised|0.7|non-text|F-01
CT-41|muted table, DEMO border (as specified, not drawn on board 07)|env.demo|surface.raised|0.7|non-text|F-01
CT-42|muted table, ready glyph (as specified, not drawn on board 07)|status.success.strong|surface.raised|0.7|non-text|F-01
CT-43|muted table, WARN glyph (as specified, not drawn on board 07)|status.warning.strong|surface.raised|0.7|non-text|F-01""".splitlines()
]


def fmt(v: float, bar: float) -> str:
    return f"{v:.4f}" if round(v, 2) == bar and abs(v - bar) > 1e-9 else f"{v:.2f}"


def measure_ct() -> list[list[str]]:
    rows = []
    for cid, state, fg, bg, alpha, role, fid in CT:
        a, bar = float(alpha), BAR[role]
        vals = []
        for th in THEMES:
            f, b = str(T[th]["color." + fg]), str(T[th]["color." + bg])
            vals.append(ratio(d04.over(f, b, a) if a < 1 else f, b))
        bad = [th for th, v in zip(THEMES[:2], vals[:2], strict=True) if v < bar]
        hc = " (hc fails)" if vals[2] < bar else ""
        verdict = ("FAIL " + ", ".join(bad) + f" — {fid}" if bad else "PASS") + hc
        rows.append(
            [cid, state, f"`color.{fg}`", f"`color.{bg}`", alpha, role]
            + [fmt(v, bar) for v in vals]
            + [verdict]
        )
    return rows


# ------------------------------------------------------------------ section 11 ----------------
# id | states | a | b | channel
CV = [
    [c.strip() for c in ln.split("|")]
    for ln in """CV-01|allowed / blocked|action.primary.default|status.danger.strong|fill against border; check against close; the words
CV-02|allowed / not allowed|action.primary.default|text.tertiary|fill against hollow; check against none; the words
CV-03|blocked / not allowed|status.danger.strong|text.tertiary|close against none; the words
CV-04|ready / not ready|status.success.strong|status.warning.strong|filled against hollow; the words
CV-05|not ready / unknown|status.warning.strong|text.tertiary|none as drawn (F-04): the strip-end `help` glyph marks the strip, not a segment; dashed after A-07
CV-06|ready / unknown|status.success.strong|text.tertiary|filled against hollow; the words
CV-07|warn / blocked (preview)|status.warning.strong|status.danger.strong|warning against danger glyph; the words
CV-08|ready / blocked (preview)|status.success.strong|status.danger.strong|check against danger glyph; the words
CV-09|LIVE / DEMO|env.live|env.demo|the word; filled against outline dot""".splitlines()
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
    files: dict[str, list[str]]  # KEY -> lines at its pin
    merged: list[str]  # E28-D03 on main (#5463, merged)


def git_show(ref: str, rel: str) -> str:
    r = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{ref}:{rel}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        raise SystemExit(f"cannot read {rel} at {ref[:9]}: fetch it first")
    return r.stdout


def read_texts() -> Texts:
    files = {k: git_show(ref, p).splitlines() for k, (p, ref) in KEYS.items()}
    return Texts(
        SPEC.read_text(encoding="utf-8"),
        PINS.read_text(encoding="utf-8"),
        files,
        git_show(BASE, D03_PATH).splitlines(),
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


CITE = re.compile(
    r"`(05|14|15B|15|DS|D02|D03B|D03|E09-D06|E09-D09|E47-D04|E47-D09|E27-D05|E17-D01)`"
    r":(\d+)(?:–(\d+))?"
)


def cites(spec: str) -> set[tuple[str, int]]:
    out: set[tuple[str, int]] = set()
    for key, a, b in CITE.findall(spec):
        out.add((key, int(a)))
        if b:
            out.add((key, int(b)))
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
    merged = set(t.merged)
    for key, n in sorted(cs):
        lines = t.files[key]
        if n < 1 or n > len(lines) or not lines[n - 1].strip():
            p.append(f"[A] {key}:{n} is not a non-blank line at its pin")
            continue
        if key == "D03B" and lines[n - 1] in merged:
            p.append(f"[A] D03B:{n} stands verbatim on main (cite it as D03)")
        if (key, n) not in pins:
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


def high_ids(spec: str) -> set[str]:
    rows = rows_of(section(spec, "## 15. ", "## 16. "), r"^\|\s*F-\d+\s*\|")
    return {r[0] for r in rows if r[1] in ("Critical", "High")}


def g_contrast(t: Texts, p: list[str]) -> dict[str, Any]:
    want, got = measure_ct(), parse_rendered(t.spec, CT_B, CT_E)
    if len(got) != len(want):
        p.append(f"[B] section 10 has {len(got)} rows, the measurement {len(want)}")
    highs = high_ids(t.spec)
    for w in want:
        g = next((r for r in got if r and r[0] == w[0]), None)
        if g != w:
            p.append(f"[B] {w[0]} differs from the measurement")
        if w[-1].startswith("FAIL") and not any(h in w[-1] for h in highs):
            p.append(f"[B] {w[0]} fails without a High F row")
    fails = sum(1 for w in want if w[-1].startswith("FAIL"))
    said = as_fixed_sentence()
    if said not in section(t.spec, "## 10. ", "## 11. "):
        p.append(f"[B] section 10 does not say: {said}")
    return {"rows": len(want), "as_specified_fail": fails}


def as_fixed_sentence() -> str:
    low: dict[str, tuple[float, str, str]] = {}
    for r in measure_ct():
        if r[4] != "1":
            continue
        for th, v in zip(THEMES[:2], r[6:8], strict=True):
            if r[5] not in low or float(v) < low[r[5]][0]:
                low[r[5]] = (float(v), r[0], th)
    t, n = low["text"], low["non-text"]
    return (
        f"**As fixed:** every full-opacity row passes in dark and light; the lowest text ratio is "
        f"{t[0]:.2f} ({t[1]}, {t[2]}) and the lowest non-text {n[0]:.2f} ({n[1]}, {n[2]})."
    )


def g_cvd(t: Texts, p: list[str]) -> dict[str, Any]:
    want, got = compute_cv(), parse_rendered(t.spec, CV_B, CV_E)
    if len(got) != len(want):
        p.append(f"[C] section 11 has {len(got)} rows, the computation {len(want)}")
    highs = high_ids(t.spec)
    for w in want:
        g = next((r for r in got if r[:4] == w[:4]), None)
        if g != w:
            p.append(f"[C] {w[0]} {w[3]} differs from the computation")
    for r in CV:
        if r[4].startswith("none") and not any(h in r[4] for h in highs):
            p.append(f"[C] {r[0]} has no non-colour channel and no High F row")
    below = sum(1 for w in want if min(float(x) for x in w[4:9]) < 5.0)
    return {"rows": len(want), "below_5": below}


F_HEAD = re.compile(
    r"## 15\. Findings — F (\d+) \(Critical (\d+) · High (\d+) · Medium (\d+) · Low (\d+) · "
    r"Info (\d+)\) <!-- audit:f=([\d/]+) -->"
)


def a_rows(spec: str) -> list[list[str]]:
    return rows_of(section(spec, "### 16.1 ", "### 16.2 "), r"^\|\s*A-\d+\s*\|")


def g_findings(t: Texts, p: list[str]) -> dict[str, Any]:
    rows = rows_of(section(t.spec, "## 15. ", "## 16. "), r"^\|\s*F-\d+\s*\|")
    counts = [sum(1 for r in rows if r[1] == s) for s in SEVERITIES]
    m = F_HEAD.search(t.spec)
    want = [len(rows), *counts]
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
        if r[1] in ("Critical", "High"):
            named = re.findall(r"A-\d+", r[7])
            if not named or any(a not in aids or aids[a][2] != r[0] for a in named):
                p.append(f"[D] {r[0]}: a High row without its A-rows")
    ids = {r[0] for r in rows}
    for ref in sorted(set(re.findall(r"\bF-\d\d\b", t.spec)) - ids):
        p.append(f"[D] {ref} is cited but not in the table")
    return dict(zip(("rows", *SEVERITIES), want, strict=True))


def g_amend(t: Texts, p: list[str]) -> dict[str, Any]:
    rows = a_rows(t.spec)
    fids = set(
        re.findall(r"^\|\s*(F-\d+)\s*\|", section(t.spec, "## 15. ", "## 16. "), re.MULTILINE)
    )
    stamp = re.search(r"<!-- audit:a=(\d+) -->", t.spec)
    if not stamp or int(stamp.group(1)) != len(rows):
        p.append(f"[E] the A-row stamp does not equal {len(rows)}")
    for r in rows:
        m = CITE.fullmatch(r[1])
        old, new = r[3][1:-1], r[4][1:-1]
        if not m or r[2] not in fids or not (r[3].startswith('"') and r[4].startswith('"')):
            p.append(f"[E] {r[0]}: a target, an F row or a quoted Old and New is missing")
            continue
        key, n = m.group(1), int(m.group(2))
        text = "\n".join(t.files[key])
        if text.count(old) != 1 or old not in t.files[key][n - 1]:
            p.append(f"[E] {r[0]}: the Old is not once in {key} and on line {n}")
        if new in text:
            p.append(f"[E] {r[0]}: the New is already in {key}")
    said = a_counts_sentence(rows)
    if said is None:
        p.append("[E] an A-row targets a file outside E28-D03, its `15` entries and E28-D02")
    elif said not in section(t.spec, "### 16.1 ", "### 16.2 "):
        p.append(f"[E] section 16.1 does not say: {said}")
    return {"rows": len(rows)}


_NUM_WORDS = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty"
)
NUM = _NUM_WORDS.split()
FAMILY = {"D03": "D03", "D03B": "D03", "15B": "15", "15": "15", "D02": "D02"}


def word(n: int) -> str:
    if n < len(NUM):
        return NUM[n]
    tens, one = divmod(n, 10)
    return ("twenty", "thirty", "forty")[tens - 2] + (f"-{NUM[one]}" if one else "")


def a_counts_sentence(rows: list[list[str]]) -> str | None:
    fam: dict[str, int] = {"D03": 0, "15": 0, "D02": 0}
    for r in rows:
        m = CITE.fullmatch(r[1])
        if not m or m.group(1) not in FAMILY:
            return None
        fam[FAMILY[m.group(1)]] += 1
    n = len(rows)
    return (
        f"{word(n).capitalize()} A-rows <!-- audit:a={n} -->: {word(fam['D03'])} to E28-D03's text, "
        f"{word(fam['15'])} to its applied `15` entries, {word(fam['D02'])} to E28-D02."
    )


def g_focus(t: Texts, p: list[str]) -> dict[str, Any]:
    s4 = section(t.spec, "## 4. ", "## 5. ")
    subs = re.split(r"^### ", s4, flags=re.MULTILINE)[1:]
    seen, steps = [], 0
    for sub in subs:
        head = sub.splitlines()[0]
        n = len(re.findall(r"^\|\s*FO-\d+\s*\|", sub, flags=re.MULTILINE))
        if n == 0:
            p.append(f"[F] subsection {head!r} has no FO steps")
        if not re.search(r"\breturn", sub, flags=re.IGNORECASE):
            p.append(f"[F] subsection {head!r} names no return target")
        m = re.match(r"4\.\d+ (SCR-\d+) ", head)
        if m and m.group(1) in SCREENS:
            seen.append(m.group(1))
        steps += n
    for s in SCREENS:
        if s not in seen:
            p.append(f"[F] {s} has no focus-order table")
    return {"screens": len(seen), "steps": steps}


HEX = re.compile(r"#[0-9A-Fa-f]{6}\b")
# the lane's public-text word list, rot13-encoded so this file does not carry the words itself
DENY_ROT13 = (
    "yrnx rkcbfrq olcnff rkcybvg nggnpx benpyr erirny haobhaqrq sybbq fgnyy qbf nqivfbel tufn"
)
DENY = tuple(codecs.decode(w, "rot13") for w in (DENY_ROT13 + " cer-nhgu").split())
# local roots, rot13-encoded so this file names none of them itself
LOCAL = re.compile(
    "|".join(re.escape(codecs.decode(w, "rot13")) for w in ("/ubzr/", "/gzc/", "abgrf/"))
    + r"|https?:|www\.|\.local\b"
)
STAMPS = ("f", "a", "ct", "window")


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
    ct = re.search(r"<!-- audit:ct=(\d+) -->", t.spec)
    if not ct or int(ct.group(1)) != len(CT):
        p.append(f"[G] the ct stamp does not equal {len(CT)}")
    return {"deny_words": len(DENY)}


RATE = re.compile(r"^(\d+) per (\d+(?:\.\d+)?) s")
# the refused-whole summary that answers no press is said in the assertive region (section 4.6, F-05)
POLITENESS = {"LR-04": "assertive"}


def g_live(t: Texts, p: list[str]) -> dict[str, Any]:
    rows = rows_of(section(t.spec, "## 9. ", "## 10. "), r"^\|\s*LR-\d+\s*\|")
    for r in rows:
        if r[2] not in ("polite", "assertive", "none (not live)") or not r[3]:
            p.append(f"[H] {r[0]}: no politeness or no rate")
    for lid, want in POLITENESS.items():
        hit = next((x for x in rows if x[0] == lid), None)
        if hit is None or hit[2] != want:
            p.append(f"[H] {lid}: its politeness is not {want}")
    lr1 = next((r for r in rows if r[0] == "LR-01"), None)
    if not lr1 or not RATE.match(lr1[3]):
        p.append("[H] LR-01: the preview has no rate")
    for r in rows:
        m = RATE.match(r[3])
        if m and int(m.group(1)) / float(m.group(2)) > 0.5:
            p.append(f"[H] {r[0]}: a rate above `05`'s one update per 2 s")
    return {"rows": len(rows)}


def matrix_figure(t: Texts) -> dict[str, int]:
    line = t.files["14"][2808 - 1]
    acc = re.search(r"with (\d+) accounts", line)
    sym = re.search(r"~(\d+) symbols", line)
    row_h = int(str(T["dark"]["size.row.compact"]).removesuffix("px"))
    if not acc or not sym:
        raise SystemExit("matrix figure: `14`:2808 no longer states the accounts and symbols")
    rows = math.ceil(VIEWPORT_H / row_h) + OVERSCAN
    a, s = int(acc.group(1)), int(sym.group(1))
    return {"rows": rows, "accounts": a, "window": rows * a, "whole": s * a}


def g_matrix(t: Texts, p: list[str]) -> dict[str, Any]:
    f = matrix_figure(t)
    s3 = section(t.spec, "## 3. ", "## 4. ")
    stamp = re.search(r"<!-- audit:window=(\d+) -->", s3)
    if not stamp or int(stamp.group(1)) != f["window"]:
        p.append(f"[I] the window stamp does not equal {f['window']}")
    said = f"**{f['window']} cells** ({f['rows']} rows × {f['accounts']} accounts)"
    if said not in s3 or f"**{f['whole']}**" not in s3:
        p.append(f"[I] section 3 does not say {said} and **{f['whole']}**")
    for prose in (
        f"minimum viewport of {VIEWPORT_H} px",
        f"overscan of {OVERSCAN} rows (PROPOSED)",
    ):
        if prose not in s3:
            p.append(f"[I] section 3 does not say: {prose}")
    return f


T2_RULES = ("G-T2.1d", "G-T2.6")
T2_KEYS = ("`rbac.read_only`", "`rbac.view_as`", "`rbac.owner_only`")


def ds_rule(t: Texts, rid: str) -> str:
    lines = t.files["DS"]
    i = next((k for k, x in enumerate(lines) if x.startswith(f"- **{rid}** ")), None)
    if i is None:
        raise SystemExit(f"t2: `DS` no longer carries {rid}")
    out = [lines[i]]
    for x in lines[i + 1 :]:
        if not x.startswith("  "):
            break
        out.append(x.strip())
    return re.sub(r"^- \*\*[^*]+\*\* \([^)]*\): ", "", " ".join(out))


def g_t2(t: Texts, p: list[str]) -> dict[str, Any]:
    s7 = section(t.spec, "## 7. ", "## 8. ")
    for rid in T2_RULES:
        if f'"{ds_rule(t, rid)}"' not in s7:
            p.append(f"[J] section 7 does not quote {rid} verbatim")
    rows = rows_of(s7, r"^\|\s*DR-\d+\s*\|")
    t2 = [r for r in rows if len(r) == 7 and r[3].startswith("T2")]
    if not t2:
        p.append("[J] section 7 has no T2 row with a Wrapper column")
    for r in t2:
        if "CMP-079" not in r[5] or "`lock`" not in r[5]:
            p.append(f"[J] {r[0]}: a T2 row whose Wrapper lacks CMP-079 or the `lock`")
        whole = " ".join(r)
        if "read-only" in r[1] and (
            "PROPOSED" not in whole or any(k not in whole for k in T2_KEYS)
        ):
            p.append(f"[J] {r[0]}: a read-only row without PROPOSED and its three reason keys")
    return {"t2_rows": len(t2)}


RULING = "6601763457"
JOINT_SHA = "0f6f2a95fc688dbc81f1e001a18bd0896bf1546b29dd4376ecbb4bee4b2d86d2"  # the joint sentence, the same in #840, #841, #842
JOINT_RX = re.compile(r"\*\*Stale preview \(joint ruling: .*?#5550\.")
STATE_STRINGS = ("DR-03", "DR-04", "DR-05", "DR-08")
ACCT = re.compile(r"[{]|\b[a-z]{2,5}_\d")  # a fill or an account token
PINNED_WORDS = (  # the removed-row order and the step-up's one first field (E47-D04)
    ("### 4.1 ", "### 4.2 ", "else the previous row, else the grid's empty-state stop"),
    ("### 4.6 ", "## 5. ", "else the previous, else the table's empty-state stop"),
    ("### 4.2 ", "### 4.3 ", "the first credential field (the password field"),
)
DATE = "by 2026-12-31"


def g_rulings(t: Texts, p: list[str]) -> dict[str, Any]:
    if RULING not in section(t.spec, "### 1.4 ", "## 2. "):
        p.append(f"[K] section 1.4 does not name the ruling {RULING}")
    hit = JOINT_RX.search(section(t.spec, "## 10. ", "## 11. "))
    if not hit or hashlib.sha256(hit.group(0).encode()).hexdigest() != JOINT_SHA:
        p.append("[K] section 10 does not carry the joint stale-preview sentence verbatim")
    if re.search(r"merges? as is", t.spec):
        p.append("[K] pre-stage 'merge as is' wording is left")
    for r in rows_of(section(t.spec, "## 7. ", "## 8. "), r"^\|\s*DR-\d+\s*\|"):
        if r[0] not in STATE_STRINGS:
            continue
        s = re.match(r'"([^"]*)"', r[2])
        word = s.group(1) if s else ""
        if not s or ACCT.search(word) or len(word) > 60 or not word.endswith(".") or ". " in word:
            p.append(
                f"[K] {r[0]}: its reason is not one data-free sentence of at most 60 characters"
            )
    for r in rows_of(section(t.spec, "## 15. ", "## 16. "), r"^\|\s*F-\d+\s*\|"):
        if len(r) == 8 and r[1] in ("Medium", "Low") and DATE not in r[6]:
            p.append(f"[K] {r[0]}: a {r[1]} row logged without its date")
    if "`E47-D04`:285" not in section(t.spec, "## 4. ", "## 5. "):
        p.append("[K] section 4 does not cite E47-D04's removed-row move")
    for a, z, w in PINNED_WORDS:
        if w not in section(t.spec, a, z):
            p.append(f"[K] {a.strip('# ')} lacks the ruled words {w!r}")
    return {"state_strings": len(STATE_STRINGS)}


GATES: list[tuple[str, Callable[[Texts, list[str]], dict[str, Any]]]] = [
    ("A", g_cites),
    ("B", g_contrast),
    ("C", g_cvd),
    ("D", g_findings),
    ("E", g_amend),
    ("F", g_focus),
    ("G", g_hygiene),
    ("H", g_live),
    ("I", g_matrix),
    ("J", g_t2),
    ("K", g_rulings),
]


def evaluate(t: Texts | None = None) -> tuple[list[str], dict[str, Any]]:
    t = read_texts() if t is None else t
    p: list[str] = []
    return p, {k: g(t, p) for k, g in GATES}


# ------------------------------------------------------------------ self-test ----------------
def sub(field: str, old: str, new: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        s = getattr(t, field)
        if old not in s:
            raise SystemExit(f"self-test: the anchor {old!r} is not in {field}")
        return t._replace(**{field: s.replace(old, new, 1)})

    return f


def pin_words_off(t: Texts) -> Texts:
    ln = next(x for x in t.pins.splitlines() if x.startswith("05|"))
    return t._replace(pins=t.pins.replace(ln, ln + " (moved)", 1))


def ct_cell_off(t: Texts) -> Texts:
    row = next(ln for ln in section(t.spec, CT_B, CT_E).splitlines() if ln.startswith("| CT-09"))
    return t._replace(spec=t.spec.replace(row, row.replace("PASS", "PASS?"), 1))


def cv_cell_off(t: Texts) -> Texts:
    row = next(ln for ln in section(t.spec, CV_B, CV_E).splitlines() if ln.startswith("| CV-01"))
    c = cells(row)
    c[4] = f"{float(c[4]) + 0.1:.1f}"
    return t._replace(spec=t.spec.replace(row, "| " + " | ".join(c) + " |", 1))


def lr01_twice(t: Texts) -> Texts:
    row = next(ln for ln in t.spec.splitlines() if ln.startswith("| LR-01"))
    return t._replace(spec=t.spec.replace(row, row.replace("1 per 2 s", "1 per 1 s", 1), 1))


def f09_two_owners(t: Texts) -> Texts:
    row = next(ln for ln in t.spec.splitlines() if ln.startswith("| F-09"))
    new = row.replace("E28-D03 (#839) · accounts-admin", "E28-D03 (#839); E34-D02", 1)
    return t._replace(spec=t.spec.replace(row, new, 1))


def lr08_fast(t: Texts) -> Texts:
    row = next(ln for ln in t.spec.splitlines() if ln.startswith("| LR-08"))
    return t._replace(spec=t.spec.replace(row, row.replace("1 per 2 s", "1 per 1 s", 1), 1))


def f14_undated(t: Texts) -> Texts:
    row = next(ln for ln in t.spec.splitlines() if ln.startswith("| F-14"))
    return t._replace(spec=t.spec.replace(row, row.replace(" · by 2026-12-31", "", 1), 1))


def lr04_polite(t: Texts) -> Texts:
    row = next(ln for ln in t.spec.splitlines() if ln.startswith("| LR-04"))
    return t._replace(spec=t.spec.replace(row, row.replace("| assertive", "| polite", 1), 1))


def deny_in_prose(t: Texts) -> Texts:
    word = codecs.decode("sybbq", "rot13")
    return sub("spec", "## 19. Summary for #841", f"## 19. Summary for #841 ({word})")(t)


def sp(old: str, new: str) -> Callable[[Texts], Texts]:
    return sub("spec", old, new)


MUTATIONS: list[tuple[str, Callable[[Texts], Texts]]] = [
    ("A: a pin's words no longer on its line", pin_words_off),
    ("B: a measured contrast cell retyped", ct_cell_off),
    ("C: a computed colour-vision cell retyped", cv_cell_off),
    ("D: the findings stamp off by one", sp("f=19/0/5/8/4/2", "f=19/0/5/8/4/1")),
    ("D: a finding with two owners", f09_two_owners),
    ("E: an Old not in its target", sp('"The table takes `opacity', '"The table took `opacity')),
    ("E: a per-target A count retyped", sp("nine to E28-D02.", "eight to E28-D02.")),
    ("F: a screen loses its focus-order table", sp("### 4.5 SCR-062", "### 4.5 SCR-999")),
    ("G: a deny word in prose", deny_in_prose),
    ("H: the preview announces once a second", lr01_twice),
    ("H: the staged-bulk line back to once a second", lr08_fast),
    ("H: the unpressed refusal turned polite", lr04_polite),
    ("I: the window figure retyped", sp("**264 cells**", "**260 cells**")),
    ("I: the overscan prose retyped", sp("overscan of 10 rows", "overscan of 12 rows")),
    ("J: a T2 row loses the `lock`", sp("cell; the CMP-019 `lock` (", "cell; the CMP-019 glyph (")),
    ("J: the G-T2.1d quote loses a word", sp("the full label (in 2b", "the label (in 2b")),
    ("K: the joint stale sentence loses a word", sp("decoration only, never", "decoration, never")),
    ("K: a T2 reason fills data", sp('"Blocked: use the cell', '"Blocked on {a}: use the cell')),
    ("K: a T2 reason names an account", sp("Nothing can be", "Nothing sub_001 can be")),
    (
        "K: the removed-row order retyped",
        sp("else the previous row, else", "else the first row, else"),
    ),
    (
        "K: the step-up's first field retyped",
        sp("initial the first credential", "initial Cancel, the first"),
    ),
    ("K: a Low row logged without its date", f14_undated),
    ("K: pre-stage wording comes back", sp("## 19. Summary", "## 19. (if #5482 merges as is)")),
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
        ok = len(new) == 1 and new[0].startswith("[" + name[0] + "]")
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
    old = pins_of(t.pins)
    out = [
        "# E28-D05 pins: KEY|line|words that stand on that line at its pin (gate A).",
        "# `--repin` keeps every pin still cited and adds the opening words of a new cite.",
    ]
    for key, n in sorted(cites(t.spec), key=lambda c: (list(KEYS).index(c[0]), c[1])):
        line = t.files[key][n - 1].strip()
        words = old.get((key, n)) or line[:60].rstrip()
        out.append(f"{key}|{n}|{words}")
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
