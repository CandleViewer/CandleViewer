"""E28-D03 hi-fi audit: the profile and trade-group surfaces in colour (#839).

Reads docs/design/E28/E28-D03.md, `14`, `15` and the token JSON in packages/ui/tokens; stdlib only,
offline, run as `python3 -I`. It writes nothing unless asked (`--write-matrix` refreshes the
spec's §11.1 rows between the matrix markers).

Gates, each FAIL led by its letter:
  A tokens        every backticked token resolves in dark, light and high contrast
  B matrix        §11.1 equals the tool's measurement, cell for cell; FAIL 0 among gated pairs
  C register      §0: at most 10 boards, light twins <= one third, every Status "to draw (PR 2)"
  D checklist     the 37 `14` sign-off items of the six screens quoted verbatim in §12, once each
  E contributions DS-A..DS-I each carry their fields; the PROPOSED ids are absent from `15`
  F pointers      the six `14` A-rows pending (PR 1) or all applied (PR 2); a mix FAILs
  G hygiene       no hex outside §11.1; the public-text word list; the stamped counts
  H T2            the read-only matrix cell stated once (§6.1), cited by every subsection showing a cell
  I `15` A-rows   each appended field's Old verbatim at the base; New pending (PR 1) or applied
  J copy          each new string (§13) verbatim where its row says it is used

usage: e28_d03_hifi_audit.py [--check | --self-test | --json | --matrix | --write-matrix]
"""

from __future__ import annotations

import codecs
import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
TOOLS = ROOT / "docs" / "design" / "_tools"
SPEC = ROOT / "docs" / "design" / "E28" / "E28-D03.md"
SCREENS = ROOT / "docs" / "plan" / "14-screens-catalogue.md"
E09D09 = ROOT / "docs" / "design" / "E09" / "E09-D09.md"
CATALOGUE = ROOT / "docs" / "plan" / "15-component-catalogue.md"
THEMES = ("dark", "light", "high-contrast")
BAR: dict[str, float | None] = {"text": 4.5, "non-text": 3.0, "reported": None, "rejected": 4.5}
GATED = {"text", "non-text"}
SCRS = ("SCR-130", "SCR-131", "SCR-132", "SCR-133", "SCR-062", "SCR-061")
MAX_BOARDS = 10
PENDING = "to draw (PR 2)"
MB, ME = "<!-- matrix:begin -->", "<!-- matrix:end -->"


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


# id | element | fg | bg | role
PAIRS = [
    [c.strip() for c in ln.split("|")]
    for ln in """P1|cell and field text, dialog body on the card|color.text.primary|color.surface.raised|text
P2|secondary cells, help, units, the "(v2)" version|color.text.secondary|color.surface.raised|text
P3|odd-row text|color.text.primary|color.surface.canvas|text
P4|odd-row secondary text|color.text.secondary|color.surface.canvas|text
P5|table header and sticky matrix headers|color.text.primary|color.surface.hover|text
P6|the not-allowed box outline, template placeholders, the 80 % tick|color.text.tertiary|color.surface.raised|text
P7|the allowed box, the leverage fill|color.action.primary.default|color.surface.raised|non-text
P8|the check glyph on the allowed box|color.text.on-action|color.action.primary.default|non-text
P9|the blocked close glyph and border, the danger glyph|color.status.danger.strong|color.surface.raised|non-text
P10|the CMP-158 note and other info callouts|color.text.primary|color.status.info.subtle|text
P11|the info glyph and start edge on its callout|color.status.info.strong|color.status.info.subtle|non-text
P12|the warning glyph, the not-ready segment outline|color.status.warning.strong|color.surface.raised|non-text
P13|warning rows, the relaxing and override pills|color.text.primary|color.status.warning.subtle|text
P14|the danger glyph and edge on its callout|color.status.danger.strong|color.status.danger.subtle|non-text
P15|refusal summaries|color.text.primary|color.status.danger.subtle|text
P16|the CMP-138 fill when ok, on its track|color.text.secondary|color.surface.sunken|non-text
P17|the focus ring on the card|color.focus.ring|color.surface.raised|non-text
P18|the focus ring on the canvas|color.focus.ring|color.surface.canvas|non-text
P19|selected-row text|color.text.primary|color.action.selected|text
P20|the worked example and field values, the gap callout|color.text.primary|color.surface.sunken|text
P21|the ready glyph and segment on the card|color.status.success.strong|color.surface.raised|non-text
P22|the ready glyph and segment on odd rows|color.status.success.strong|color.surface.canvas|non-text
P23|the danger glyph on odd rows|color.status.danger.strong|color.surface.canvas|non-text
P24|the CMP-138 track against the card|color.surface.sunken|color.surface.raised|reported
P25|the CMP-138 track outline, table rules|color.border.default|color.surface.raised|reported
P26|the LIVE glyph and 2 px border (E10-D03 §3.2)|color.env.live|color.surface.raised|non-text
P27|the DEMO glyph and 2 px border (E10-D03 §3.2)|color.env.demo|color.surface.raised|non-text
P28|white on the LIVE fill (rejected: E10-D03 :400, E30-D01 §3)|color.text.on-action|color.env.live|rejected
P29|the pill border on its fill|color.status.warning.strong|color.status.warning.subtle|non-text
P30|the CMP-138 fill near the cap, on its track|color.status.warning.strong|color.surface.sunken|non-text
P31|the CMP-138 fill at a lock, on its track|color.status.danger.strong|color.surface.sunken|non-text
P32|field placeholders; the CMP-138 unknown hatch|color.text.tertiary|color.surface.sunken|text
P33|dialog text on the overlay|color.text.primary|color.surface.overlay|text
P34|dialog secondary text on the overlay|color.text.secondary|color.surface.overlay|text
P35|the changed-cell start edge|color.border.selected|color.surface.raised|non-text
P36|links (symbol state, bound profile)|color.text.link|color.surface.raised|text
P37|the example label, the gap callout secondary text|color.text.secondary|color.surface.sunken|text""".splitlines()
]


def fmt3(vals: list[float], bar: float | None) -> str:
    out = []
    for v in vals:
        near = bar is not None and round(v, 2) == bar and abs(v - bar) > 1e-9
        out.append(f"{v:.4f}" if near else f"{v:.2f}")
    return " / ".join(out)


def measure() -> list[dict[str, Any]]:
    rows = []
    for pid, element, fg, bg, role in PAIRS:
        bar = BAR[role]
        vals = [ratio(str(T[t][fg]), str(T[t][bg])) for t in THEMES]
        bad = [t for t, v in zip(THEMES, vals, strict=True) if bar is not None and v < bar]
        if role in GATED:
            verdict = "PASS" if not bad else "FAIL " + ", ".join(bad)
        elif role == "rejected":
            verdict = "rejected: fails " + ", ".join(bad) if bad else "rejected by design"
        else:
            verdict = "reported"
        rows.append(
            {
                "id": pid,
                "element": element,
                "fg": fg,
                "bg": bg,
                "role": role,
                "text": fmt3(vals, bar),
                "verdict": verdict,
                "bad": bad,
            }
        )
    return rows


def matrix_lines(rows: list[dict[str, Any]]) -> list[str]:
    head = [
        "| Id | Element | Foreground | Background | Role | Dark / light / high contrast | Verdict |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    return head + [
        f"| {r['id']} | {r['element']} | `{r['fg']}` | `{r['bg']}` | {r['role']} | "
        f"{r['text']} | {r['verdict']} |"
        for r in rows
    ]


class Texts(NamedTuple):
    spec: str
    screens: str
    catalogue: str
    base15: str  # `15` at the merge base with origin/main (the working copy when git has no base)
    e09: str  # E09-D09, the T2 rule §6.1 cites by line


def git_show_base(rel: str) -> str | None:
    def run(*a: str) -> str | None:
        r = subprocess.run(
            ["git", "-C", str(ROOT), *a], capture_output=True, text=True, check=False
        )
        return r.stdout if r.returncode == 0 else None

    base = run("merge-base", "HEAD", "origin/main")
    return run("show", f"{base.strip()}:{rel}") if base else None


def read_texts() -> Texts:
    spec, screens, cat = (p.read_text(encoding="utf-8") for p in (SPEC, SCREENS, CATALOGUE))
    base15 = git_show_base("docs/plan/15-component-catalogue.md") or cat
    return Texts(spec, screens, cat, base15, E09D09.read_text(encoding="utf-8"))


def section(spec: str, start: str, end: str) -> str:
    i = spec.find(start)
    if i < 0:
        return ""
    j = spec.find(end, i + len(start))
    return spec[i : j if j > 0 else len(spec)]


def cells(ln: str) -> list[str]:
    """A table row's cells; `\\|` is a pipe inside a cell, not a separator."""
    parts = re.split(r"(?<!\\)\|", ln.strip().strip("|"))
    return [c.strip().replace("\\|", "|") for c in parts]


# ------------------------------------------------------------------ the gates ----------------
TOKEN_RX = re.compile(
    r"`((?:color|type|space|size|radius|border|motion|opacity|font|elevation)\.[a-z0-9.-]+)`"
)
NOT_TOKENS = {"color.track", "color.meter.track"}  # DSR-1 names it as a request, not a token


def g_tokens(t: Texts, p: list[str]) -> dict[str, Any]:
    names = sorted(set(TOKEN_RX.findall(t.spec)) - NOT_TOKENS)
    for n in names:
        if not all(n in T[th] for th in THEMES):
            p.append(f"[A] token does not resolve: {n}")
    for n in NOT_TOKENS:
        if any(n in T[th] for th in THEMES):
            p.append(f"[A] requested token already exists: {n}")
    return {"named": len(names)}


def g_matrix(t: Texts, p: list[str]) -> dict[str, Any]:
    rows = measure()
    for r in rows:
        if r["role"] in GATED and r["bad"]:
            p.append(f"[B] contrast FAIL {r['id']} {r['element']}: {r['text']}")
    block = section(t.spec, MB, ME)
    got = [cells(ln) for ln in block.splitlines() if ln.startswith("|")][2:]  # prettier pads
    want = [cells(ln) for ln in matrix_lines(rows)][2:]
    if got != want:
        diff = next((w for g, w in zip(got, want, strict=False) if g != w), None)
        p.append(f"[B] §11.1 differs from the tool ({len(got)} vs {len(want)} lines): {diff!r}")
    gated = [r for r in rows if r["role"] in GATED]
    return {"pairs": len(rows), "gated": len(gated), "fail": sum(1 for r in gated if r["bad"])}


def g_register(t: Texts, p: list[str]) -> dict[str, Any]:
    s0 = section(t.spec, "## 0. ", "## 1. ")
    rows = [cells(ln) for ln in s0.splitlines() if re.match(r"^\|\s*\d\d\s*\|", ln)]
    if not rows or len(rows) > MAX_BOARDS:
        p.append(f"[C] {len(rows)} boards (1..{MAX_BOARDS})")
    twins = [r for r in rows if "twin" in r[1]]
    if len(twins) * 3 > len(rows):
        p.append(f"[C] {len(twins)} light twins of {len(rows)} boards (more than one third)")
    for r in rows:
        if len(r) != 5 or r[4] != PENDING:
            p.append(f"[C] board {r[0]}: Status is not {PENDING!r}")
        if not re.fullmatch(r"`[a-z0-9-]+`", r[1]):
            p.append(f"[C] board {r[0]}: slug {r[1]!r}")
        if "twin" in r[1] and not r[3].startswith("light"):
            p.append(f"[C] board {r[0]}: a twin that is not light")
    return {"boards": len(rows), "twins": len(twins)}


def checklist_items(screens: str) -> list[tuple[str, str]]:
    out, cur = [], None
    for ln in screens.splitlines():
        m = re.match(r"### (SCR-\d+) ", ln)
        if m:
            cur = m.group(1)
        if cur in SCRS and "Design sign-off acceptance checklist:**" in ln:
            out += [(cur, x.strip()) for x in ln.split("[ ]")[1:]]
    return out


def g_checklist(t: Texts, p: list[str]) -> dict[str, Any]:
    items = checklist_items(t.screens)
    s12 = section(t.spec, "## 12. ", "## 13. ")
    rows = [cells(ln) for ln in s12.splitlines() if re.match(r"^\|\s*SCR-\d+\s*\|", ln)]
    got = [(r[0], r[1]) for r in rows]
    for scr in SCRS:  # one FAIL per screen: a reworded item is one finding, not two
        want = [x for s, x in items if s == scr]
        have = [x for s, x in got if s == scr]
        lost = [x[:50] for x in want if have.count(x) != 1]
        extra = [x[:50] for x in have if x not in want]
        if lost or extra:
            p.append(f"[D] {scr}: not quoted once {lost}; not a `14` item {extra}")
    return {"items": len(items), "rows": len(rows)}


DS_FIELDS = (
    "**Purpose:**",
    "**Props:**",
    "**Variants:**",
    "**States:**",
    "**Tokens:**",
    "**A11y:**",
    "**Storybook:**",
    "**Tests:**",
)
NEW_IDS = ("CMP-254", "CMP-255", "CMP-256")


def g_contrib(t: Texts, p: list[str]) -> dict[str, Any]:
    s9 = section(t.spec, "## 9. ", "## 10. ")
    heads = re.findall(r"^### 9\.\d (DS-[A-I]) ", s9, flags=re.MULTILINE)
    if heads != [f"DS-{c}" for c in "ABCDEFGHI"]:
        p.append(f"[E] the contributions are {heads}, not DS-A..DS-I")
    for i, ds in enumerate(("DS-A", "DS-B", "DS-C")):
        body = section(s9, f"### 9.{i + 1} {ds} ", "### 9.")
        for f in DS_FIELDS:
            if f not in body:
                p.append(f"[E] {ds} has no {f.strip('*:')} field")
    for cid in NEW_IDS:
        if re.search(rf"^### {cid}\b", t.catalogue, flags=re.MULTILINE):
            p.append(f"[E] {cid} is already an entry in 15 (re-allocate)")
    return {"contributions": len(heads)}


POINTER = "- **Hi-fi (E28-D03):** [E28-D03.md](../design/E28/E28-D03.md)"
D02 = "- **Wireframes (E28-D02):**"


def a14_rows(spec: str) -> list[list[str]]:
    s14 = section(spec, "## 14. ", "## 15. ")
    return [cells(ln) for ln in s14.splitlines() if re.match(r"^\|\s*A-\d+\s*\|\s*`14`", ln)]


def g_pointers(t: Texts, p: list[str]) -> dict[str, Any]:
    """The six `14` A-rows: pending in PR 1 (no line applied), all applied in PR 2; a mix FAILs."""
    rows, lines = a14_rows(t.spec), t.screens.splitlines()
    scrs = [r[1].split()[-1] for r in rows]
    if sorted(scrs) != sorted(SCRS):
        p.append(f"[F] the `14` A-rows name {scrs}, not the six screens")
    done: list[str] = []
    todo: list[str] = []
    for r in rows:
        scr, new = r[1].split()[-1], r[4].strip('"')
        m = re.match(r"after (\d+) ", r[2])
        k = int(m.group(1)) if m else 0
        if "boards drawn on page" not in new or "to draw" in new:
            p.append(f"[F] {r[0]}: the New text is not in its landed form (boards drawn)")
        if not new.startswith(POINTER) or r[3] != "— (no line)":
            p.append(f"[F] {r[0]}: not a pointer insertion")
            continue
        hits = [i for i, ln in enumerate(lines) if ln == new]
        if hits:
            ok = len(hits) == 1 and lines[hits[0] - 1].startswith(D02)
            (done if ok else todo).append(r[0] if ok else f"{r[0]} misplaced")
            continue
        todo.append(r[0])
        if not (0 < k <= len(lines) and lines[k - 1].startswith(D02)):
            p.append(f"[F] {r[0]}: `14`:{k} is not {scr}'s D02 line")
    stray = sum(1 for ln in lines if ln.startswith(POINTER)) - len(done)
    if (done and todo) or stray:
        p.append(f"[F] `14` A-rows: applied {done}, pending {todo}, stray lines {stray} (a mix)")
    return {"a14": len(rows), "mode": "applied" if done and not todo else "pending"}


T2_HEAD = "### 6.1 T2 on the matrix cells"
T2_NEEDS = (
    "CMP-079",
    'aria-disabled="true"',
    "aria-describedby",
    "G-T2.5",
    "`rbac.read_only`",
    "`rbac.view_as`",
    "`rbac.owner_only`",
    "D03-C9",
)
# §6.1's E09-D09 cites, pinned: the line number and the text that must stand on it
T2_PINS = {94: "`rbac.read_only`", 95: "`rbac.view_as`"}
CELL_RX = re.compile(r"DS-A|SymbolMatrixCell|matrix cell|cell states|three cell")


def g_t2(t: Texts, p: list[str]) -> dict[str, Any]:
    """T2 on the matrix cells: stated once (§6.1), cited by every section that shows a cell."""
    n = t.spec.count(T2_HEAD)
    if n != 1:
        p.append(f"[H] the T2 statement ({T2_HEAD!r}) appears {n} times, not once")
    body = section(t.spec, T2_HEAD, "\n## ")
    lost = [x for x in T2_NEEDS if x not in body]
    e09 = t.e09.splitlines()
    for n in sorted({int(x) for x in re.findall(r"E09-D09 :(\d+)", body)}):
        want = T2_PINS.get(n)
        got = e09[n - 1] if 0 < n <= len(e09) else ""
        if want is None or want not in got:
            p.append(
                f"[H] §6.1 cites E09-D09 :{n}, which is not a pinned line ({want or 'unpinned'})"
            )
    if lost:
        p.append(f"[H] §6.1 lacks {lost}")
    uncited = []
    for sec in re.split(r"\n(?=#{2,3} )", t.spec):  # every section and subsection on its own
        title = sec.splitlines()[0][:40]
        if not sec.startswith("#") or sec.startswith(T2_HEAD):
            continue
        if CELL_RX.search(sec) and "§6.1" not in sec:
            uncited.append(title)
    if uncited:
        p.append(f"[H] subsections that show a matrix cell without citing §6.1: {uncited}")
    return {"t2": n, "cited": not uncited}


FIELD_RX = re.compile(r"^(\w+) \((\d+)\)$")


def a15_rows(spec: str) -> list[list[str]]:
    s14 = section(spec, "## 14. ", "## 15. ")
    return [
        cells(ln) for ln in s14.splitlines() if re.match(r"^\|\s*A-\d+\s*\|\s*CMP-\d+\s*\|", ln)
    ]


def field_text(cat: str, cmp_: str, fname: str) -> str | None:
    """A CMP entry's own `- **Field**:` text, found by content inside its entry."""
    lines, inside = cat.splitlines(), False
    for ln in lines:
        if ln.startswith("### "):
            inside = ln.startswith(f"### {cmp_} ")
        elif inside and ln.startswith(f"- **{fname}**: "):
            return ln[len(f"- **{fname}**: ") :]
    return None


def g_a15(t: Texts, p: list[str]) -> dict[str, Any]:
    """The appended `15` A-rows: Old verbatim at the base, New pending (PR 1) or applied (PR 2)."""
    done: list[str] = []
    todo: list[str] = []
    for r in a15_rows(t.spec):
        m = FIELD_RX.match(r[2])
        old = re.fullmatch(r'"(.*)" \(\d+\)', r[3])
        new = re.fullmatch(r'keep; append: "(.*)"', r[4])
        if not (m and old and new) or "**E28-D03 —**" not in new.group(1):
            p.append(
                f'[I] {r[0]}: not a copy-ready append (Field (line), "Old" (line), keep; append)'
            )
            continue
        base = field_text(t.base15, r[1], m.group(1))
        if base is None or base != old.group(1):
            p.append(f"[I] {r[0]}: the Old text is not {r[1]}'s {m.group(1)} at the base")
            continue
        head = field_text(t.catalogue, r[1], m.group(1))
        if head == base + " " + new.group(1):
            done.append(r[0])
        elif head == base:
            todo.append(r[0])
        else:
            p.append(f"[I] {r[0]}: {r[1]}'s {m.group(1)} differs from both Old and Old + New")
    if done and todo:
        p.append(f"[I] `15` A-rows: applied {done}, pending {todo} (a mix)")
    return {"a15": len(done) + len(todo), "mode": "applied" if done and not todo else "pending"}


WHERE_RX = re.compile(r"§\d+(?:\.\d+)?|DS-[A-I]")


def where_text(spec: str, ref: str) -> str:
    if ref.startswith("DS-"):
        m = re.search(rf"^### 9\.\d {ref} ", spec, flags=re.MULTILINE)
        return section(spec, m.group(0), "\n### ") if m else ""
    head = ("### " if "." in ref else "## ") + ref[1:] + ("" if "." in ref else ".") + " "
    return section(spec, head, "\n### " if "." in ref else "\n## ")


def g_copy(t: Texts, p: list[str]) -> dict[str, Any]:
    """Each new string (§13) stands verbatim where its row says it is used."""
    s13 = section(t.spec, "## 13. ", "## 14. ")
    n = 0
    for r in (cells(ln) for ln in s13.splitlines() if re.match(r"^\|\s*H-\d+\s*\|", ln)):
        refs = WHERE_RX.findall(r[2])
        places = [where_text(t.spec, x) for x in refs]
        for frag in re.findall(r'"([^"]+)"', r[1]):
            n += 1
            if not refs or not any(frag in pl for pl in places):
                p.append(f"[J] {r[0]}: {frag!r} is not at {r[2]}")
    return {"strings": n}


HEX = re.compile(r"#[0-9A-Fa-f]{6}\b")
# the public-text word list, kept rot13-encoded so this file does not carry the words itself
DENY = tuple(
    codecs.decode(w, "rot13")
    for w in [
        "yrnx",
        "rkcbfrq",
        "olcnff",
        "rkcybvg",
        "nggnpx",
        "benpyr",
        "erirny",
        "haobhaqrq",
        "sybbq",
        "fgnyy",
        "qbf",
        "nqivfbel",
        "tufn",
        "cer-nhgu",
    ]
)
STAMP = re.compile(r"<!-- audit:([a-z_]+)=(\d+) -->")


def g_hygiene(t: Texts, p: list[str], counts: dict[str, int]) -> dict[str, Any]:
    outside = t.spec.replace(section(t.spec, MB, ME), "")
    stray = HEX.search(outside)
    if stray:
        p.append(f"[G] a hex outside §11.1: {stray.group(0)}")
    low = t.spec.lower()
    for w in DENY:
        if re.search(rf"(?<![a-z]){re.escape(w)}" if len(w) == 3 else re.escape(w), low):
            p.append(f"[G] a public-text deny word: {w}")
    for k, v in STAMP.findall(t.spec):
        if k not in counts:
            p.append(f"[G] unknown count stamp {k}")
        elif counts[k] != int(v):
            p.append(f"[G] stamp {k}={v} but the text has {counts[k]}")
    return {"stamps": len(STAMP.findall(t.spec))}


def counted(t: Texts) -> dict[str, int]:
    s0 = section(t.spec, "## 0. ", "## 1. ")
    boards = [ln for ln in s0.splitlines() if re.match(r"^\|\s*\d\d\s*\|", ln)]

    def rows(sec: tuple[str, str], rx: str) -> int:
        return sum(1 for ln in section(t.spec, *sec).splitlines() if re.match(rx, ln))

    return {
        "boards": len(boards),
        "twins": sum(1 for ln in boards if "twin" in cells(ln)[1]),
        "ds": rows(("## 9. ", "### 9.1 "), r"^\|\s*DS-[A-I]\s*\|"),
        "checklist": rows(("## 12. ", "## 13. "), r"^\|\s*SCR-\d+\s*\|"),
        "copy": rows(("## 13. ", "## 14. "), r"^\|\s*H-\d+\s*\|"),
        "arows": rows(("## 14. ", "## 15. "), r"^\|\s*A-\d+\s*\|"),
        "c_rows": rows(("## 16. ", "## 17. "), r"^\|\s*D03-C\d+\s*\|"),
    }


def evaluate(t: Texts | None = None) -> tuple[list[str], dict[str, Any]]:
    t = read_texts() if t is None else t
    p: list[str] = []
    out = {
        "A": g_tokens(t, p),
        "B": g_matrix(t, p),
        "C": g_register(t, p),
        "D": g_checklist(t, p),
        "E": g_contrib(t, p),
        "F": g_pointers(t, p),
        "H": g_t2(t, p),
        "I": g_a15(t, p),
        "J": g_copy(t, p),
    }
    c = counted(t)
    out["G"] = g_hygiene(t, p, c)
    out["counts"] = c
    return p, out


# ------------------------------------------------------------------ self-test ----------------
def sub(field: str, old: str, new: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        s = getattr(t, field)
        if old not in s:
            raise SystemExit(f"self-test: the anchor {old!r} is not in {field}")
        return t._replace(**{field: s.replace(old, new, 1)})

    return f


def apply_last(t: Texts) -> Texts:
    """Apply the `14` A-row whose anchor is last in `14`, so no other row's cite moves."""
    rows = a14_rows(t.spec)
    last = max(rows, key=lambda r: int(r[2].split()[1]))
    lines = t.screens.splitlines()
    lines.insert(int(last[2].split()[1]), last[4].strip('"'))
    return t._replace(screens="\n".join(lines))


def drop_cite_91(t: Texts) -> Texts:
    """§9.1 loses its §6.1 cites while §9 keeps others (a per-subsection gate must notice)."""
    m = re.search(r"^### 9\.1 [^\n]*", t.spec, flags=re.MULTILINE)
    if not m:
        raise SystemExit("self-test: no §9.1")
    i = m.start()
    j = t.spec.index("\n### ", i + 1)
    return t._replace(spec=t.spec[:i] + t.spec[i:j].replace("§6.1", "§6") + t.spec[j:])


def apply_one_15(t: Texts) -> Texts:
    """Apply the first appended `15` A-row alone (a mix)."""
    r = a15_rows(t.spec)[0]
    fname = r[2].split()[0]
    new = re.fullmatch(r'keep; append: "(.*)"', r[4])
    base = field_text(t.catalogue, r[1], fname)
    if not new or base is None:
        raise SystemExit("self-test: A-row not appendable")
    line = f"- **{fname}**: {base}"
    return t._replace(catalogue=t.catalogue.replace(line, line + " " + new.group(1), 1))


MUTATIONS: list[tuple[str, Callable[[Texts], Texts]]] = [
    ("A: an invented token", sub("spec", "`color.surface.canvas`", "`color.surface.bogus`")),
    ("B: a measured cell retyped", sub("spec", "14.35 / 15.62 / 16.25", "14.35 / 15.62 / 16.24")),
    ("C: a board drawn early", sub("spec", "to draw (PR 2)", "drawn")),
    ("D: a checklist item reworded", sub("spec", "search/filter", "search")),
    ("E: a contribution loses its Tests", sub("spec", "- **Tests:** unit (never", "- unit (never")),
    ("F: one pointer line applied early (A-13, the last in `14`)", apply_last),
    (
        "H: the T2 statement loses G-T2.5",
        sub("spec", "One notice, many pointers (G-T2.5)", "One notice, many pointers"),
    ),
    ("H: §9.1 loses its §6.1 cite", drop_cite_91),
    ("H: a §6.1 E09-D09 cite moves to another line", sub("spec", "(E09-D09 :95)", "(E09-D09 :93)")),
    (
        "F: a `14` A-row back to its pre-draw wording",
        sub("spec", "(ten boards drawn on page", "(boards to draw in PR 2 on page"),
    ),
    (
        "I: an Old cell retyped",
        sub("spec", '"`title?` · `actions?: ReactNode`', '"`title` · `actions?: ReactNode`'),
    ),
    ("I: one `15` A-row applied early", apply_one_15),
    (
        "J: a new string reworded where it is used",
        sub("spec", "the example needs this account's equity.", "the example needs the equity."),
    ),
    ("G: a hex typed in prose", sub("spec", "## 19. Deviations", "## 19. Deviations (#123456)")),
]


def self_test() -> int:
    base = read_texts()
    p0, _ = evaluate(base)
    bad = 0
    for name, m in MUTATIONS:
        p1, _ = evaluate(m(base))
        new = [x for x in p1 if x not in p0]
        ok = len(new) == 1 and new[0].startswith("[" + name[0] + "]")
        bad += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {name}: {len(new)} new FAIL {new[:2]}")
    print(f"--self-test: {'ok' if not bad else 'FAIL'} - {len(MUTATIONS)} mutations in memory")
    return int(bad > 0)


def main(argv: list[str]) -> int:
    arg = argv[1] if len(argv) > 1 else "--check"
    if arg == "--matrix":
        print("\n".join(matrix_lines(measure())))
        return 0
    if arg == "--write-matrix":
        s = SPEC.read_text(encoding="utf-8")
        i, j = s.index(MB) + len(MB), s.index(ME)
        SPEC.write_text(
            s[:i] + "\n" + "\n".join(matrix_lines(measure())) + "\n" + s[j:], encoding="utf-8"
        )
        return 0
    if arg == "--self-test":
        return self_test()
    problems, out = evaluate()
    if arg == "--json":
        print(json.dumps(out, indent=1))
        return 0
    for k in "ABCDEFGHIJ":
        print(f"{k}. {out[k]}")
    print(f"counts {out['counts']}")
    for x in problems:
        print("FAIL", x)
    print(f"rc {int(bool(problems))}")
    return int(bool(problems))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
