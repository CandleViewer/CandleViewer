#!/usr/bin/env python3
"""E15-D12 (#366) audit: the responsive and reduced-capability layout pack.

Stdlib only, offline (`python3 -I -B`). It reads AS TEXT at the pinned base (`git show BASE:<path>`)
the plan texts and the merged E15 design texts, E15-D13's pack at PR #5055's head (D13_SHA), and
the token JSON; then the pack (`E15-D12.md`), its hand-off, the spec
(`docs/design/specs/e15-responsive-and-degraded.md`) and the pins from the working tree. It
imports, never copies, `contrast_check.contrast_ratio()` for every WCAG ratio and
`verify_tokens.merged_set()` / `resolve()` for the theme layering.

Values. Every `{{KIND:key}}` outside a code span is COMPUTED: BUDGET (a chrome or plot figure from
the tokens and E15-D03's anchored budget), CR (a WCAG ratio, two decimals), HOST (the darkest or
lightest hosted background of a theme) and COUNT (the documents' own rows). `--fill` writes
`VALUE<!--=KIND:key-->`; `--check` re-derives every anchored value. The gates, each FAIL led by
its code:

- [G-ANCHOR] every anchored value equals the tool's; no placeholder left unfilled.
- [G-CITE] every `KEY`:line cite (each end of a range) resolves to a non-blank line at the base
  (`D13` at D13_SHA), and each load-bearing cite (CITED) holds its words on that line: cites are
  pinned by their content, not by a number alone.
- [G-UNTOUCHED] PR 1: only the pack's five files differ from `git merge-base HEAD origin/main`.
  PR 2 (no pack document and not the tool differs): only `14`, `15` and `16` differ, each equal to
  the merge-base with every §C row applied, re-pointed by content, and the pins file may differ
  only as the tool's own byte-exact rewrite; no other byte. Fails closed when git cannot answer.
- [G-AROW] §C: rows A-1 ... A-n in order, each with its target (`14`, `15`, `16`), a known op and
  its Old equal to (or, for a fragment or a span, once in) its line at the base and unique in its
  scope; a row that DEPENDS on E15-D13's PR 2 finds its Old in E15-D13's CMP-251 text at D13_SHA,
  and in the merge-base `15` once that holds the entry (re-pinned by content).
- [G-LEDGER] §2: rows L-1 ... L-n in order, dispositions from the vocabulary, every A-n named in
  "Here" present in §C.
- [G-PARITY] the spec §4: five cells a row, a status from the vocabulary, a reason where the
  status needs one; the not-offered rows exactly the ruled set, each with the availability line;
  every E15-D04 operation and every E15-D07 panel-menu item (each re-read at the base) has a row.
- [G-BUDGET] the sweep recomputed from the tokens and E15-D03's budget: the reproductions equal
  E15-D03's anchors; the bands and the layout typed in the spec's table equal the computed ones;
  every collapse frame keeps a positive plot with every row that never yields.
- [G-CONTRAST] every gated pair meets its bar in three themes; the bars in the spec's table are
  the gate's.
- [G-NEVERSHED] the spec §6.4 lists exactly the never-shed set; §6.3 sheds exactly three items
  and names none of the never-shed set.
- [G-COPY] the spec §10: CP-1 ... CP-n in order; no subsystem word, no verdict and no "Trading
  is off" in a string; every degraded row's still-works sentence stands in its string; each kept
  string stands word for word on its parent's line.
- [G-AC1] no hex value in the documents; every px or ms value outside a code span, a quoted
  string, an anchor and a fenced block stands in the pack's §9 exception table, and no exception
  value is unused.
- [G-RULED] the stamps in their exact forms at their sites (every BQ covered once; BQ-04 also
  A41, BQ-08 also A42), and the ruled words (RULING_PINS) in the pack or the spec; with `--source
  NAME=FILE` each pin also stands in that saved copy.
- [G-RULED-PIN] a default-deny pin set over every unit of the three documents (each heading,
  table row by its lead cell, prose sentence and fenced block) in `e15_d12_ruled_pins.txt`,
  anchored values cut out. `--repin-ruled` is its only writer. When another gate FAILs, every
  G-RULED-PIN finding prints as a NOTE; the exit status stays 1.
- [G-PUBLIC] no word on the public-text list (matched by pattern), no local path, host, uuid, URL,
  agent or session name, or closing keyword.
- [G-CROWS] §10's C-rows C-1 ... C-19 in order, each with a reading and an owner.
- [G-DRYRUN] the dry run is not the author's: the spec §14 says who runs it and when and holds no
  result, the pack's DoD line for it is open, the AC trace names the deputy, and the appendix
  keeps the brief in a text fence.
- [G-MUTLIST] the pack's §12 lists the tool's mutations, one per gate, by name.

`--a-rows` prints §C as JSON, one record per row with its target file; `--self-test` applies one
mutation per gate (MUTATIONS) and the probes (PROBES) to an in-memory copy and passes only when each
adds exactly one new FAIL with its gate's code, each CLEAN case (a PR 2 that applies §C exactly)
adds none, a re-run reproduces the base result and no file on disk changed.

Usage (from the repo root):
  python3 -I -B docs/design/_tools/e15_d12_responsive_audit.py --check [--json] [--fill]
  python3 -I -B docs/design/_tools/e15_d12_responsive_audit.py --self-test
  python3 -I -B docs/design/_tools/e15_d12_responsive_audit.py --repin-ruled
  python3 -I -B docs/design/_tools/e15_d12_responsive_audit.py --a-rows
  python3 -I -B docs/design/_tools/e15_d12_responsive_audit.py --check --source R366=FILE \
      --source A4142=FILE
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import cache
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
BASE = "d7f9ca3557"  # `git merge-base HEAD origin/main` at writing (#5058's merge)
D13_SHA = "2282c6983c"  # E15-D13's pack at PR #5055's head (approved, not merged)
PACK_REL = "docs/design/E15/E15-D12.md"
HAND_REL = "docs/design/E15/E15-D12-handoff.md"
SPEC_REL = "docs/design/specs/e15-responsive-and-degraded.md"
TOOL_REL = "docs/design/_tools/e15_d12_responsive_audit.py"
PINS_REL = "docs/design/_tools/e15_d12_ruled_pins.txt"
OWN_PATHS = (PACK_REL, HAND_REL, SPEC_REL, TOOL_REL, PINS_REL)
TARGETS = {
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
}
RULING_ID = "6522684771"  # the #366 ruling of record
E15 = "docs/design/E15/E15-"
KEYS: dict[str, str] = {
    "05": "docs/plan/05-accessibility-standard.md",
    "06": "docs/plan/06-performance-and-load-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": TARGETS["14"],
    "15": TARGETS["15"],
    "16": TARGETS["16"],
    "23": "docs/plan/23-ws-protocol.md",
    "26": "docs/plan/26-chart-engine-design.md",
    "D02": E15 + "D02.md",
    "D03": E15 + "D03.md",
    "D04": E15 + "D04.md",
    "D07": E15 + "D07.md",
    "D13": E15 + "D13.md",
    "D15": E15 + "D15.md",
}
SHA_OF = {"D13": D13_SHA}  # every other key is read at BASE
TOKENS_DIR = "packages/ui/tokens"
THEMES = ("dark", "light", "high-contrast")
THEME_KEY = {"dark": "dark", "light": "light", "high-contrast": "hc"}
CMP251_HEAD = "### CMP-251 DockTabGroup (E15-D04 P6)"


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(ROOT / TOKENS_DIR / "tests"))
VERIFY = _load(ROOT / TOKENS_DIR / "tests" / "verify_tokens.py", "verify_tokens")
CONTRAST = _load(ROOT / "docs" / "design" / "_tools" / "contrast_check.py", "contrast_check")


# ---------------------------------------------------------------------------- git and text


def git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), *args], capture_output=True, check=False, timeout=60
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.decode("utf-8")


@cache
def at_sha(sha: str, rel: str) -> str | None:
    return git("show", f"{sha}:{rel}")


def at_key(key: str) -> str | None:
    return at_sha(SHA_OF.get(key, BASE), KEYS[key])


def read(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


def lines(text: str) -> list[str]:
    return text.split("\n")


HEADING = re.compile(r"^(#{1,6}) (.*)$")
RULE_ROW = re.compile(r"^\|(?:\s*:?-+:?\s*\|)+\s*$")
FENCE = re.compile(r"^```")
ANCHOR = re.compile(r"<!--=([A-Z]+:[^>]+?)-->")
PLACEHOLDER = re.compile(r"\{\{([A-Z]+:[^{}]+)\}\}")
ANCHORED = re.compile(r"([^\s|(/·]*?)<!--=([A-Z]+:[^>]+?)-->")


def split_row(line: str) -> list[str]:
    cells = re.split(r"(?<!\\)\|", line.strip())
    return [c.strip() for c in cells[1:-1]]


def unfence(text: str) -> str:
    """The text with fenced blocks blanked (line count kept)."""
    out, inside = [], False
    for ln in lines(text):
        if FENCE.match(ln):
            inside = not inside
            out.append("")
            continue
        out.append("" if inside else ln)
    return "\n".join(out)


def section(text: str, title: str, level: int = 2) -> str:
    """The body of the section at `level` whose heading starts with `title`."""
    out: list[str] = []
    on, fenced = False, False
    for ln in lines(text):
        if FENCE.match(ln):
            fenced = not fenced
        m = HEADING.match(ln)
        if m and not fenced and len(m.group(1)) <= level:
            on = len(m.group(1)) == level and m.group(2).startswith(title)
            continue
        if on:
            out.append(ln)
    return "\n".join(out)


def table_rows(block: str) -> list[list[str]]:
    rows = []
    for ln in lines(block):
        if ln.startswith("|") and not RULE_ROW.match(ln):
            rows.append(split_row(ln))
    return rows[1:] if rows else []


def norm(text: str) -> str:
    return " ".join(text.replace("`", "").replace("**", "").split())


def unquote(cell: str) -> str:
    return cell.replace("\\|", "|")


# ---------------------------------------------------------------------------- tokens and colour


@cache
def theme_set(theme: str) -> dict[str, Any]:
    files = [VERIFY.PRIMITIVES, *VERIFY.THEMES[theme]]
    merged: dict[str, Any] = VERIFY.merged_set(files)
    return merged


def value(name: str, theme: str = "dark") -> Any:
    t = theme_set(theme)
    return VERIFY.resolve(t[name]["$value"], t)


def px(name: str) -> int:
    return int(value(name))


def hexof(name: str, theme: str) -> str:
    return str(value(name, theme)).upper()


def rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def ratio(a: str, b: str) -> float:
    r: float = CONTRAST.contrast_ratio(rgb(a), rgb(b))
    return r


def lum(h: str) -> float:
    r: float = CONTRAST.relative_luminance(rgb(h))
    return r


def f2(x: float) -> str:
    return f"{x:.2f}"


SURFACES = (
    "color.surface.sunken",
    "color.surface.app",
    "color.surface.canvas",
    "color.surface.raised",
    "color.surface.overlay",
)
HEATMAP = ("color.heatmap.zero",) + tuple(
    f"color.heatmap.{s}.{i}" for s in ("bid", "ask") for i in range(1, 6)
)
HOSTED = SURFACES + HEATMAP  # a lower depth lights fewer rows: the same stops, more of the zero
BARS = {"text": 4.5, "non-text": 3.0}
# (key, foreground, its own fill, kind): chrome that carries its own fill over panel content.
PAIRS: tuple[tuple[str, str, str, str], ...] = (
    ("chip.word", "color.text.secondary", "color.neutral.subtle", "text"),
    ("row.message", "color.text.primary", "color.status.info.subtle", "text"),
    ("row.works", "color.text.secondary", "color.status.info.subtle", "text"),
    ("row.glyph", "color.status.info.strong", "color.status.info.subtle", "non-text"),
    ("caption", "color.text.secondary", "color.surface.overlay", "text"),
)
FOCUS = ("color.focus.ring", "color.surface.canvas")  # the carrier and its halo, over content


def extremes(theme: str) -> tuple[str, str]:
    ranked = sorted(HOSTED, key=lambda n: (lum(hexof(n, theme)), n))
    return ranked[0], ranked[-1]


def two_tone(theme: str) -> float:
    ring, halo = (hexof(n, theme) for n in FOCUS)
    return min(max(ratio(ring, hexof(b, theme)), ratio(halo, hexof(b, theme))) for b in HOSTED)


def measured() -> list[tuple[str, str, float, float]]:
    """(key, theme key, ratio, bar) for every gated pair."""
    out: list[tuple[str, str, float, float]] = []
    for th in THEMES:
        k = THEME_KEY[th]
        for key, fg, bg, kind in PAIRS:
            out.append((key, k, ratio(hexof(fg, th), hexof(bg, th)), BARS[kind]))
        out.append(("focus.twotone", k, two_tone(th), BARS["non-text"]))
    return out


def colour_values() -> dict[str, str]:
    v: dict[str, str] = {}
    for key, k, r, _ in measured():
        v[f"CR:{key}.{k}"] = f2(r)
    for th in THEMES:
        lo, hi = extremes(th)
        v[f"HOST:lo.{THEME_KEY[th]}"] = f"`{lo}`"
        v[f"HOST:hi.{THEME_KEY[th]}"] = f"`{hi}`"
    return v


# ---------------------------------------------------------------------------- the sweep

FRAMES: tuple[tuple[int, int], ...] = (
    (1920, 1080),
    (1440, 900),
    (1280, 800),
    (1100, 800),
    (1024, 640),
    (640, 400),
    (1280, 720),
    (1280, 640),
)
COLLAPSE_BELOW = 1280


def parent_anchor(doc: str, key: str) -> str | None:
    text = at_key(doc) or ""
    m = re.search(r"(\d[\d×.]*)<!--=" + re.escape(key) + r"-->", text)
    return m.group(1) if m else None


def band(w: int, h: int) -> str:
    bw = "W1" if w >= 1280 else "W2" if w >= 1024 else "W3" if w >= 640 else "W4"
    bh = "H1" if h >= 800 else "H2" if h >= 640 else "H3"
    return f"{bw} · {bh}"


def layout(w: int) -> str:
    return "collapse" if w < COLLAPSE_BELOW else "arrangement"


def chrome() -> dict[str, int]:
    c, f, s1 = px("size.control.compact"), px("size.control.comfortable"), px("space.1")
    a = {k: int(parent_anchor("D03", v) or 0) for k, v in PARENT_CHROME.items()}
    return {
        **a,
        "row.c": c,
        "row.f": f,
        "tabgroup.c": c,
        "tabgroup.f": f,
        "tabstrip.c": c + 2 * s1,
        "tabstrip.f": f + 2 * s1,
        "banner.c": c + 2 * s1,
        "banner.f": f + 2 * s1,
        "restore.c": c + 2 * s1,
        "restore.f": f + 2 * s1,
        "tray.c": c,
        "focus.axis": 2 * px("border.focus"),
    }


PARENT_CHROME = {
    "navrail": "BUDGET:h.navrail",
    "rightrail": "BUDGET:h.rightrail-strip",
    "topbar": "BUDGET:v.topbar",
    "statusbar": "BUDGET:v.statusbar",
}


def frame(w: int, h: int) -> dict[str, int | str]:
    ch = chrome()
    cw, cht = w - ch["navrail"] - ch["rightrail"], h - ch["topbar"] - ch["statusbar"]
    out: dict[str, int | str] = {"canvas": f"{cw}×{cht}"}
    for d in ("c", "f"):
        box = cht - ch[f"tabstrip.{d}"] - (ch[f"tabgroup.{d}"] if w < COLLAPSE_BELOW else 0)
        out[f"plot.{d}"] = box - 3 * ch[f"row.{d}"] - ch["focus.axis"]
    keep = ch["banner.c"] + (ch["restore.c"] + ch["tray.c"] if h >= 800 else 0)
    out["worst"] = int(out["plot.c"]) - keep
    return out


def budget_values() -> dict[str, str]:
    v = {f"BUDGET:{k}": str(n) for k, n in chrome().items()}
    for w, h in FRAMES:
        for k, n in frame(w, h).items():
            v[f"BUDGET:f.{w}x{h}.{k}"] = str(n)
    return v


# (my key, E15-D03's anchor): the reproductions, equal at the base.
REPRO = (
    ("tabstrip.c", "BUDGET:v.tabstrip.compact"),
    ("tabstrip.f", "BUDGET:v.tabstrip.comfortable"),
    ("banner.c", "BUDGET:v.banner.compact"),
    ("banner.f", "BUDGET:v.banner.comfortable"),
    ("restore.c", "BUDGET:v.restore.compact"),
    ("restore.f", "BUDGET:v.restore.comfortable"),
    ("tabgroup.c", "BUDGET:v.tabgroup.compact"),
    ("tabgroup.f", "BUDGET:v.tabgroup.comfortable"),
    ("row.c", "BUDGET:v.header.compact"),
    ("row.f", "BUDGET:v.header.comfortable"),
    ("tray.c", "BUDGET:v.tray.compact"),
    ("f.1280x800.canvas", "BUDGET:canvas.1280"),
    ("f.1920x1080.canvas", "BUDGET:canvas.1920"),
    ("f.1280x800.plot.c", "BUDGET:plot.full.1280.compact"),
    ("f.1280x800.plot.f", "BUDGET:plot.full.1280.comfortable"),
    ("f.1920x1080.plot.c", "BUDGET:plot.full.1920.compact"),
    ("f.1920x1080.plot.f", "BUDGET:plot.full.1920.comfortable"),
)
FRAME_CELL = re.compile(r"^(\d+) × (\d+)$")


def budget_problems(spec: str, values: dict[str, str]) -> list[str]:
    bad: list[str] = []
    for mine, theirs in REPRO:
        want = parent_anchor("D03", theirs)
        if want is None or values.get(f"BUDGET:{mine}") != want:
            bad.append(f"{mine} = {values.get(f'BUDGET:{mine}')}, E15-D03's {theirs} = {want}")
    seen: list[tuple[int, int]] = []
    for r in table_rows(section(spec, "2.")):
        m = FRAME_CELL.match(r[0]) if r else None
        if not m:
            continue
        w, h = int(m.group(1)), int(m.group(2))
        seen.append((w, h))
        if len(r) < 3 or r[1] != band(w, h) or r[2] != layout(w):
            bad.append(f"{r[0]}: typed {r[1:3]}, computed [{band(w, h)!r}, {layout(w)!r}]")
        if w < COLLAPSE_BELOW and int(frame(w, h)["worst"]) <= 0:
            bad.append(f"{r[0]}: no plot left with every row that never yields")
    if tuple(seen) != FRAMES:
        bad.append(f"the spec's sweep is {seen}, not the tool's frames")
    return bad


# ---------------------------------------------------------------------------- §C: the A-rows


@dataclass(frozen=True)
class ARow:
    aid: str
    entry: str
    fld: str
    file: str  # "14", "15" or "16"
    line: int  # 0 = a line E15-D13's PR 2 creates ("new")
    op: str
    src: str
    depends: str
    old: tuple[str, ...]  # the line, a fragment, the span's two ends, or the anchor
    new: str


OPS = ("replace", "replace fragment", "replace span", "insert after")
ROW_HEAD = re.compile(r"^#### (A-\d+) · (.+?) · (.+)$")
ROW_META = re.compile(r"^`(14|15|16)`:(\d+|new) · ([a-z ]+?) · from (.+?)(?: · DEPENDS on (.+))?$")


def a_rows(pack: str) -> tuple[list[ARow], list[str]]:
    """§C's rows and the parse problems."""
    ls = lines(section(pack, "§C"))
    rows: list[ARow] = []
    bad: list[str] = []
    i = 0
    while i < len(ls):
        m = ROW_HEAD.match(ls[i])
        if not m:
            i += 1
            continue
        aid, entry, fld = m.groups()
        meta = ROW_META.match(ls[i + 2]) if i + 2 < len(ls) else None
        blocks: list[tuple[str, list[str]]] = []
        j = i + 3
        while j < len(ls) and not ROW_HEAD.match(ls[j]) and len(blocks) < 2:
            if ls[j].startswith("```") and len(ls[j]) > 3:
                kind, k = ls[j][3:], j + 1
                buf: list[str] = []
                while k < len(ls) and ls[k] != "```":
                    buf.append(ls[k])
                    k += 1
                blocks.append((kind, buf))
                j = k
            j += 1
        if not meta or len(blocks) != 2:
            bad.append(f"{aid}: no meta line or not two fenced blocks")
            i = j
            continue
        file, line, op, src, dep = meta.groups()
        (k1, old), (k2, new) = blocks
        want = "anchor" if op == "insert after" else "old"
        size = 2 if op == "replace span" else 1
        if k1 != want or k2 != "new" or len(old) != size:
            bad.append(f"{aid}: the blocks are not ```{want} ({size} line(s)) then ```new")
        rows.append(
            ARow(
                aid,
                entry,
                fld,
                file,
                0 if line == "new" else int(line),
                op,
                src,
                dep or "",
                tuple(old),
                "\n".join(new),
            )
        )
        i = j
    return rows, bad


def holds(row: ARow, ln: str) -> bool:
    if row.op in ("replace", "insert after"):
        return ln == row.old[0]
    if row.op == "replace fragment":
        return ln.count(row.old[0]) == 1
    a, b = row.old
    return ln.count(a) == 1 and ln.count(b) == 1 and ln.index(a) < ln.index(b)


def scope_of(base_lines: list[str], row: ARow) -> str:
    if row.depends:
        return CMP251_HEAD
    for k in range(row.line - 1, -1, -1):
        if HEADING.match(base_lines[k]):
            return base_lines[k]
    return ""


def locate(cur: list[str], head: str, row: ARow) -> int | None:
    """Re-point a row by content: its scope heading, then the one line holding its Old there."""
    starts = [k for k, ln in enumerate(cur) if ln == head]
    if len(starts) != 1:
        return None
    hm = HEADING.match(head)
    level = len(hm.group(1)) if hm else 7
    hits: list[int] = []
    for k in range(starts[0] + 1, len(cur)):
        m = HEADING.match(cur[k])
        if m and len(m.group(1)) <= level:
            break
        if holds(row, cur[k]):
            hits.append(k)
    return hits[0] if len(hits) == 1 else None


def apply_rows(text: str, rows: list[ARow], file: str) -> str | None:
    """`text` with every row for `file` applied; None when a row cannot be re-pointed."""
    cur = lines(text)
    base_lines = lines(at_sha(BASE, TARGETS[file]) or "")
    edits: list[tuple[int, int, ARow]] = []
    for r in rows:
        if r.file != file:
            continue
        k = locate(cur, scope_of(base_lines, r), r)
        if k is None:
            return None
        edits.append((k, 0 if r.op == "insert after" else 1, r))
    for k, _, r in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        if r.op == "replace fragment":
            cur[k] = cur[k].replace(r.old[0], r.new, 1)
        elif r.op == "replace span":
            a, b = cur[k].index(r.old[0]), cur[k].index(r.old[1]) + len(r.old[1])
            cur[k] = cur[k][:a] + r.new + cur[k][b:]
        elif r.op == "replace":
            cur[k : k + 1] = lines(r.new)
        else:
            cur[k + 1 : k + 1] = lines(r.new)
    return "\n".join(cur)


def export(rows: list[ARow]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for r in rows:
        rec: dict[str, object] = {
            "id": r.aid,
            "target_file": TARGETS[r.file],
            "line_at_base": r.line or None,
            "op": r.op,
            "entry": r.entry,
            "field": r.fld,
            "from": r.src,
            "depends_on": r.depends or None,
        }
        if r.op == "insert after":
            rec["anchor"] = r.old[0]
        elif r.op == "replace span":
            rec["span_from"], rec["span_to"] = r.old
        else:
            rec["old"] = r.old[0]
        rec["new"] = r.new
        out.append(rec)
    return out


def d13_entry() -> list[str]:
    """CMP-251's lines as E15-D13's A-3 writes them (D13_SHA)."""
    ls = lines(at_key("D13") or "")
    if CMP251_HEAD not in ls:
        return []
    k = ls.index(CMP251_HEAD)
    out = [ls[k]]
    for ln in ls[k + 1 :]:
        if ln.startswith("#"):
            break
        out.append(ln)
    return out


def arow_problems(rows: list[ARow], parse_bad: list[str], mbase15: str) -> list[str]:
    bad = list(parse_bad)
    for n, r in enumerate(rows, 1):
        if r.aid != f"A-{n}":
            bad.append(f"{r.aid}: out of order (expected A-{n})")
        if r.op not in OPS:
            bad.append(f"{r.aid}: unknown op {r.op!r}")
            continue
        if r.depends:
            entry = d13_entry()
            if r.file != "15" or r.line or locate(entry, CMP251_HEAD, r) is None:
                bad.append(f"{r.aid}: the Old is not once in E15-D13's CMP-251 at {D13_SHA}")
            mb = lines(mbase15)
            if CMP251_HEAD in mb and locate(mb, CMP251_HEAD, r) is None:
                bad.append(f"{r.aid}: the Old is not once in the merge-base's CMP-251 (re-pin)")
            continue
        base = at_sha(BASE, TARGETS[r.file])
        if base is None:
            bad.append(f"{r.aid}: `{r.file}` unreadable at {BASE}")
            continue
        bl = lines(base)
        at = bl[r.line - 1] if 1 <= r.line <= len(bl) else ""
        if not holds(r, at):
            bad.append(f"{r.aid}: the Old is not on `{r.file}`:{r.line} at the base")
        elif locate(bl, scope_of(bl, r), r) != r.line - 1:
            bad.append(f"{r.aid}: the Old is not unique in its scope")
    return bad


# ---------------------------------------------------------------------------- ledger and C-rows

DISPOSITIONS = ("applied as amended", "applied", "routed", "closed")


def ledger(pack: str) -> list[list[str]]:
    return [r for r in table_rows(section(pack, "2.")) if re.fullmatch(r"L-\d+", r[0])]


def disposition(cell: str) -> str:
    for d in DISPOSITIONS:
        if cell.startswith(d):
            return d
    return ""


def ledger_problems(pack: str, rows: list[ARow]) -> list[str]:
    bad: list[str] = []
    ids = {r.aid for r in rows}
    for n, r in enumerate(ledger(pack), 1):
        if r[0] != f"L-{n}" or len(r) != 4:
            bad.append(f"{r[0]}: out of order or not four cells")
            continue
        if not disposition(r[2]):
            bad.append(f"{r[0]}: disposition {r[2][:30]!r} is not in the vocabulary")
        for a in re.findall(r"A-\d+", r[3]):
            if a not in ids:
                bad.append(f"{r[0]}: names {a}, which §C does not hold")
        span = re.search(r"A-(\d+) … A-(\d+)", r[3])
        if span and not {f"A-{k}" for k in range(int(span[1]), int(span[2]) + 1)} <= ids:
            bad.append(f"{r[0]}: names a range §C does not hold")
    return bad


def ledger_counts(pack: str) -> dict[str, str]:
    ds = [disposition(r[2]) for r in ledger(pack)]
    return {
        "COUNT:ledger": str(len(ds)),
        "COUNT:ledger.applied": str(ds.count("applied")),
        "COUNT:ledger.amended": str(ds.count("applied as amended")),
        "COUNT:ledger.routed": str(ds.count("routed")),
        "COUNT:ledger.closed": str(ds.count("closed")),
    }


def crows(pack: str) -> list[list[str]]:
    return [r for r in table_rows(section(pack, "10.")) if re.fullmatch(r"C-\d+", r[0])]


def crow_problems(pack: str) -> list[str]:
    bad: list[str] = []
    rows = crows(pack)
    if len(rows) != 19:
        bad.append(f"{len(rows)} C-rows (the ruling's nineteen)")
    for n, r in enumerate(rows, 1):
        if r[0] != f"C-{n}" or len(r) != 4 or not r[2].strip() or not r[3].strip():
            bad.append(f"{r[0]}: out of order, or no reading or owner")
    if rows and len(rows) >= 4 and "A41" not in rows[3][2]:
        bad.append("C-4 does not cite A41")
    return bad


# ---------------------------------------------------------------------------- parity (BQ-07)

STATUSES = ("same", "moved", "equivalent", "not offered")
AVAIL = "Widen the window to arrange panels."
NOT_OFFERED = (  # the ruling's four; the handle is drag docking's origin
    "Header handle (drag origin)",
    "Drag docking and its drop zones (CMP-214)",
    "Splitters and their keys",
    "Move panel (move mode K1 … K6)",
    "Maximise and restore",
)
# Each stands as the lead of a row of E15-D04's operations table, re-read at the base.
D04_OPS = (
    "Move",
    "Split",
    "Tabify",
    "Resize",
    "Pop out",
    "Return to workspace",
    "Close",
    "Maximise and restore",
    "Minimise and restore",
    "Equal sizes",
    "Undo a layout change",
)
# Each stands in E15-D07 §5.1's fixed order, re-read at the base.
D07_ITEMS = (
    "Undo move",
    "Settings…",
    "Duplicate",
    "Move panel",
    "Move to",
    "Equal sizes",
    "Maximise",
    "Minimise",
    "Pop out",
    "Sync group",
    "Copy panel link",
    "Reset settings…",
    "Close",
)


def parity(spec: str) -> list[list[str]]:
    return table_rows(section(spec, "4."))


def parity_problems(spec: str) -> list[str]:
    bad: list[str] = []
    rows = parity(spec)
    off = [r[0] for r in rows if len(r) == 5 and r[3] == "not offered"]
    for r in rows:
        if len(r) != 5:
            bad.append(f"{r[0][:30]!r}: {len(r)} cells, not five")
            continue
        ctl, _, narrow, status, why = r
        if status not in STATUSES:
            bad.append(f"{ctl[:30]!r}: status {status!r} is not in the vocabulary")
        elif status == "not offered" and AVAIL not in why:
            bad.append(f"{ctl[:30]!r}: not offered without the availability line")
        elif status in ("moved", "equivalent") and why in ("", "—"):
            bad.append(f"{ctl[:30]!r}: {status} with no equivalent or reason")
        elif status != "not offered" and narrow in ("", "—"):
            bad.append(f"{ctl[:30]!r}: no narrow location")
    if tuple(off) != NOT_OFFERED:
        bad.append(f"the not-offered rows are {off}, not the ruled set")
    d04 = lines(at_key("D04") or "")[194:207]
    menu = section(at_key("D07") or "", "5.1 ", 3)
    for name in D04_OPS:
        if not any(ln.startswith(f"| {name}") for ln in d04):
            bad.append(f"E15-D04's operation {name!r} is not in its table at the base")
        if not any(r[0].lower().startswith(name.lower()) for r in rows if r):
            bad.append(f"E15-D04's operation {name!r} has no parity row")
    for name in D07_ITEMS:
        if name not in menu:
            bad.append(f"E15-D07's item {name!r} is not in §5.1 at the base")
        if not any(r[0].lower().startswith(name.lower()) for r in rows if r):
            bad.append(f"E15-D07's item {name!r} has no parity row")
    return bad


def parity_counts(spec: str) -> dict[str, str]:
    st = [r[3] for r in parity(spec) if len(r) == 5]
    return {
        "COUNT:parity": str(len(st)),
        "COUNT:parity.same": str(st.count("same")),
        "COUNT:parity.moved": str(st.count("moved")),
        "COUNT:parity.equivalent": str(st.count("equivalent")),
        "COUNT:parity.notoffered": str(st.count("not offered")),
    }


# ---------------------------------------------------------------------------- never shed (BQ-12)

NEVER = (
    "the environment badge",
    "the arm state",
    "positions and orders",
    "every error state",
    "the Safety cluster",
    "the SCR-152 region",
    "every SCR-153 row",
    "the protection states",
    "the stale and disconnected marks",
    "alerts and fills",
    "the focus affordance",
    "the announcement rates",
)
SHEDS = ("heatmap depth", "panels you aren't using", "new panels")


def nevershed_problems(spec: str) -> list[str]:
    bad: list[str] = []
    body = section(spec, "6.4 ", 3)
    bullets = [ln[2:] for ln in lines(body) if ln.startswith("- ")]
    if len(bullets) != len(NEVER):
        bad.append(f"§6.4 lists {len(bullets)} items, the never-shed set has {len(NEVER)}")
    for phrase in NEVER:
        if sum(b.startswith(phrase) for b in bullets) != 1:
            bad.append(f"§6.4 does not list {phrase!r} once")
    sheds = table_rows(section(spec, "6.3 ", 3))
    if tuple(r[0] for r in sheds) != SHEDS:
        bad.append(f"§6.3 sheds {[r[0] for r in sheds]}, not the three")
    for r in sheds:
        for phrase in NEVER:
            key = phrase.removeprefix("the ").removeprefix("every ")
            if key.lower() in r[0].lower():
                bad.append(f"§6.3 sheds {r[0]!r}, which is on the never-shed list")
    return bad


# ---------------------------------------------------------------------------- the copy (BQ-16)

SUBSYSTEM = re.compile(
    r"\b(?:GPU|WebGL|renderer|engine|LOD|worker|shader|graphics)\b", re.IGNORECASE
)
VERDICT = re.compile(r"\b(?:weak|underpowered|too slow|bad|poor)\b|Trading is off", re.IGNORECASE)
DEGRADED = ("CP-1", "CP-3", "CP-4", "CP-5", "CP-8", "CP-18", "CP-20")
MEASURED = ("CP-1", "CP-3", "CP-5", "CP-9")  # the measurement with its window: "p95" or 95th
KEPT = {"CP-4": ("D02", 545), "CP-6": ("D02", 547), "CP-12": ("D02", 548), "CP-21": ("D03", 460)}
QUOTE = re.compile(r'"([^"]+)"')


def copy_rows(spec: str) -> list[list[str]]:
    return [r for r in table_rows(section(spec, "10.")) if re.fullmatch(r"CP-\d+", r[0])]


def copy_problems(spec: str) -> list[str]:
    bad: list[str] = []
    for n, r in enumerate(copy_rows(spec), 1):
        if r[0] != f"CP-{n}" or len(r) != 5:
            bad.append(f"{r[0]}: out of order or not five cells")
            continue
        cid, _, text, works, _ = r
        strings = " ".join(QUOTE.findall(text))
        sub, ver = SUBSYSTEM.search(strings), VERDICT.search(strings)
        if sub:
            bad.append(f"{cid}: names a part of the app ({sub[0]!r})")
        if ver:
            bad.append(f"{cid}: a verdict or an alarm ({ver[0]!r})")
        if cid in DEGRADED:
            w = QUOTE.findall(works)
            if len(w) != 1 or w[0] not in strings:
                bad.append(f"{cid}: no still-works sentence standing in its string")
        if cid in MEASURED and "p95" not in strings and "95th" not in strings:
            bad.append(f"{cid}: the measurement without its percentile")
        if cid in KEPT:
            key, n_line = KEPT[cid]
            first = QUOTE.findall(text)[:1]
            parent = (lines(at_key(key) or "") + [""] * n_line)[n_line - 1]
            if not first or first[0] not in parent:
                bad.append(f"{cid}: the kept string is not on `{key}`:{n_line} word for word")
    return bad


# ---------------------------------------------------------------------------- AC1 (BQ-17)

UNIT = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s?(px|ms)\b")
HEX = re.compile(r"#[0-9A-Fa-f]{6}\b")
QUOTED = re.compile(r'"[^"\n]*"')


def ac1_rows(pack: str) -> list[list[str]]:
    return [r for r in table_rows(section(pack, "9.")) if re.fullmatch(r"X-\d+", r[0])]


def ac1_allowed(pack: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {"px": set(), "ms": set()}
    for r in ac1_rows(pack):
        if len(r) == 4 and r[2] in out:
            out[r[2]] |= {x.strip() for x in r[1].split(",")}
    return out


def ac1_scan(name: str, text: str) -> list[tuple[str, str, str]]:
    """(doc, value, unit) for every px or ms value AC1 must explain."""
    out: list[tuple[str, str, str]] = []
    for ln in lines(unfence(text)):
        if re.fullmatch(r"\| X-\d+ .*", ln):
            continue
        plain = QUOTED.sub("", re.sub(r"`[^`\n]*`", "", ANCHORED.sub("", ln)))
        out += [(name, m.group(1), m.group(2)) for m in UNIT.finditer(plain)]
    return out


def ac1_problems(t: Texts) -> list[str]:
    bad: list[str] = []
    allowed = ac1_allowed(t.pack)
    used: dict[str, set[str]] = {"px": set(), "ms": set()}
    for name, text in docs(t):
        for m in HEX.finditer(text):
            bad.append(f"{name}: a hex value ({m.group(0)})")
        for doc, val, unit in ac1_scan(name, text):
            used[unit].add(val)
            if val not in allowed[unit]:
                bad.append(f"{doc}: {val} {unit} is neither anchored, a token nor an exception")
    flat = "\n".join(re.sub(r"\| X-\d+ .*", "", text) for _, text in docs(t))
    for unit, vals in allowed.items():
        for v in sorted(vals):
            if not re.search(r"(?<![\w.])" + re.escape(v) + r"(?![\w.]\d)", flat):
                bad.append(f"the exception {v} {unit} is not used (stale)")
    return bad


def ac1_counts(pack: str) -> dict[str, str]:
    a = ac1_allowed(pack)
    return {
        "COUNT:ac1.values": str(len(a["px"]) + len(a["ms"])),
        "COUNT:ac1.rows": str(len(ac1_rows(pack))),
    }


# ---------------------------------------------------------------------------- texts and values


@dataclass(frozen=True)
class Texts:
    pack: str
    hand: str
    spec: str
    pins: str
    changed: tuple[str, ...] | None  # paths differing from the merge-base; None = git failed
    now: tuple[tuple[str, str], ...]  # ("14" | "15" | "16", working-tree text)
    mbase: tuple[tuple[str, str], ...]  # ("14" | "15" | "16", merge-base text)
    sources: tuple[tuple[str, str], ...] = ()


def docs(t: Texts) -> list[tuple[str, str]]:
    return [("pack", t.pack), ("hand", t.hand), ("spec", t.spec)]


def count_values(t: Texts) -> dict[str, str]:
    rows, _ = a_rows(t.pack)
    v = {
        "COUNT:arows": str(len(rows)),
        "COUNT:arows.14": str(sum(r.file == "14" for r in rows)),
        "COUNT:arows.15": str(sum(r.file == "15" for r in rows)),
        "COUNT:arows.16": str(sum(r.file == "16" for r in rows)),
        "COUNT:arows.depends": str(sum(bool(r.depends) for r in rows)),
        "COUNT:crows": str(len(crows(t.pack))),
        "COUNT:mutations": str(len(MUTATIONS)),
        "COUNT:probes": str(len(PROBES)),
        "COUNT:clean": str(len(CLEAN)),
        "COUNT:gates": str(len(GATES)),
        "COUNT:sweep": str(len(FRAMES)),
        "COUNT:pairs": str(len(PAIRS) + 1),
    }
    v.update(ledger_counts(t.pack))
    v.update(parity_counts(t.spec))
    v.update(ac1_counts(t.pack))
    return v


@cache
def fixed_values() -> tuple[tuple[str, str], ...]:
    v = colour_values()
    v.update(budget_values())
    return tuple(sorted(v.items()))


def compute(t: Texts) -> dict[str, str]:
    v = dict(fixed_values())
    v.update(count_values(t))
    return v


def code_spans(line: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in re.finditer(r"`[^`\n]*`", line)]


def fill(text: str, values: dict[str, str]) -> tuple[str, list[str]]:
    missing: list[str] = []
    out = []
    for ln in lines(text):
        spans = code_spans(ln)
        pieces, last = [], 0
        for m in PLACEHOLDER.finditer(ln):
            if any(a <= m.start() < b for a, b in spans):
                continue
            key = m.group(1)
            pieces.append(ln[last : m.start()])
            if key in values:
                pieces.append(f"{values[key]}<!--={key}-->")
            else:
                missing.append(key)
                pieces.append(m.group(0))
            last = m.end()
        pieces.append(ln[last:])
        out.append("".join(pieces))
    return "\n".join(out), missing


def anchored(text: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(2)) for m in ANCHORED.finditer(unfence(text))]


def unfill(text: str) -> str:
    """The text with each anchored value cut out (the pins never see a value)."""
    return ANCHORED.sub(lambda m: f"<!--={m.group(2)}-->", text)


# ---------------------------------------------------------------------------- findings


@dataclass(frozen=True)
class Finding:
    gate: str
    level: str
    msg: str


def fails(gate: str, problems: list[str]) -> list[Finding]:
    return [Finding(gate, "FAIL", p) for p in problems]


def g_anchor(t: Texts) -> list[Finding]:
    v = compute(t)
    bad: list[str] = []
    for name, text in docs(t):
        for m in PLACEHOLDER.finditer(re.sub(r"`[^`\n]*`", "", unfence(text))):
            bad.append(f"{name}: {{{{{m.group(1)}}}}} is not filled (run --fill)")
        for got, key in anchored(text):
            want = v.get(key)
            if want is None:
                bad.append(f"{name}: {key} is not a value the tool computes")
            elif got != want:
                bad.append(f"{name}: {key} reads {got!r}, the tool computes {want!r}")
    return fails("G-ANCHOR", bad)


CITE = re.compile(
    r"`("
    + "|".join(sorted((re.escape(k) for k in KEYS), key=len, reverse=True))
    + r")`:(\d+)(?:[–-](\d+))?((?:, :\d+(?:[–-]\d+)?)*)"
)
CONT = re.compile(r":(\d+)(?:[–-](\d+))?")
# Load-bearing cites: the words stand on the line the cite names (BASE; `D13` at D13_SHA).
CITED: dict[tuple[str, int], str] = {
    ("16", 241): "increase window size",
    ("D03", 684): "inputs, not chrome values",
    ("D02", 632): "1024×640 CSS px",
    ("D02", 544): "This device is slow to draw",
    ("D02", 545): "Order entry and positions are unaffected.",
    ("D02", 548): "Narrow window: panels are shown as tabs.",
    ("D02", 549): "Under 800 px tall two conditional rows yield",
    ("D02", 624): "One-click trading disarmed",
    ("D02", 152): "under 1280 px wide the dock is shown as one tab group",
    ("D02", 744): "deferred → E15-D12 with E10, E08 and E17",
    ("D02", 827): "| A-14 |",
    ("D02", 829): "| A-16 |",
    ("D03", 156): "**Close**",
    ("D03", 325): '"Reduced" chip (CMP-011 neutral)',
    ("D03", 460): "`error-delisted`",
    ("D15", 285): "the reduced panel",
    ("D15", 561): "| G-01 |",
    ("D15", 339): "| SR-45 |",
    ("D15", 340): "| SR-46 |",
    ("D13", 152): "CMP-011 `neutral`",
    ("D13", 310): "| C-14 |",
    ("D13", 417): CMP251_HEAD,
    ("11", 2754): "≥55 fps with four active order-flow panes",
    ("11", 2774): "restore to interactive in ≤3 s",
    ("11", 2885): "panels collapse into a tabbed arrangement",
    ("11", 2893): "measured frame time, not on user-agent strings",
    ("23", 1491): "private (`orders`, `positions`, `executions`, `wallet`)",
    ("14", 2435): "known-issue list",
    ("14", 2996): "a cancel/reload option after 15 s",
    ("14", 3046): "CMP-227 EstimatedBadge",
    ("15", 1004): "reappears while the condition persists",
    ("06", 89): "toward 250ms",
    ("D04", 195): "| Operation",
    ("D07", 269): "### 5.1 The fixed order",
}


def cites_in(text: str) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []
    for m in CITE.finditer(text):
        key, a, b, rest = m.group(1), int(m.group(2)), int(m.group(3) or m.group(2)), m.group(4)
        out.append((key, a, b))
        for c in CONT.finditer(rest or ""):
            out.append((key, int(c.group(1)), int(c.group(2) or c.group(1))))
    return out


def g_cite(t: Texts) -> list[Finding]:
    bad: list[str] = []
    seen: set[tuple[str, int]] = set()
    for name, text in docs(t):
        for key, a, b in cites_in(unfence(text)):
            src = at_key(key)
            if src is None:
                bad.append(f"{name}: `{key}` is unreadable")
                continue
            bl = lines(src)
            seen.update((key, n) for n in range(a, b + 1))
            for n in sorted({a, b}):
                if not 1 <= n <= len(bl) or not bl[n - 1].strip() or b < a:
                    bad.append(f"{name}: `{key}`:{n} is past the end or blank")
    for (key, n), words in CITED.items():
        bl = lines(at_key(key) or "")
        if (key, n) not in seen:
            bad.append(f"the load-bearing cite `{key}`:{n} is not in the documents")
        elif not 1 <= n <= len(bl) or words not in bl[n - 1]:
            bad.append(f"`{key}`:{n} no longer holds {words!r}")
    return fails("G-CITE", bad)


def g_untouched(t: Texts) -> list[Finding]:
    if t.changed is None:
        return fails("G-UNTOUCHED", ["git cannot name the changed paths (fail closed)"])
    docs_changed = [p for p in t.changed if p in OWN_PATHS and p != PINS_REL]
    other = [p for p in t.changed if p not in OWN_PATHS]
    if docs_changed:  # PR 1: only the pack's five files
        return fails(
            "G-UNTOUCHED", [f"PR 1 changes {p}, not one of the pack's five" for p in other]
        )
    bad = [f"PR 2 changes {p}, not `14`, `15` or `16`" for p in other if p not in TARGETS.values()]
    if PINS_REL in t.changed and t.pins != write_pins(all_units(t)):
        bad.append("PR 2 changes the pins file other than as the tool's byte-exact rewrite")
    rows, _ = a_rows(t.pack)
    now, mb = dict(t.now), dict(t.mbase)
    for key, rel in TARGETS.items():
        if rel not in t.changed:
            continue
        want = apply_rows(mb.get(key, ""), rows, key)
        if want is None:
            bad.append(f"PR 2: a §C row for `{key}` cannot be re-pointed at the merge-base")
        elif now.get(key) != want:
            bad.append(f"PR 2: `{key}` is not the merge-base with §C applied, byte for byte")
    return fails("G-UNTOUCHED", bad)


def g_arow(t: Texts) -> list[Finding]:
    rows, bad = a_rows(t.pack)
    return fails("G-AROW", arow_problems(rows, bad, dict(t.mbase).get("15", "")))


def g_ledger(t: Texts) -> list[Finding]:
    return fails("G-LEDGER", ledger_problems(t.pack, a_rows(t.pack)[0]))


def g_parity(t: Texts) -> list[Finding]:
    return fails("G-PARITY", parity_problems(t.spec))


def g_budget(t: Texts) -> list[Finding]:
    return fails("G-BUDGET", budget_problems(t.spec, budget_values()))


def contrast_problems(spec: str) -> list[str]:
    bad = [f"{key} ({k}) {f2(r)} under {b:g}:1" for key, k, r, b in measured() if r < b]
    want = {key: f"{BARS[kind]:g}:1" for key, _, _, kind in PAIRS}
    want["focus.twotone"] = f"{BARS['non-text']:g}:1"
    for r in table_rows(section(spec, "11.")):
        keys = [m.group(1) for m in re.finditer(r"CR:([a-z.]+)\.dark", " ".join(r))]
        if keys and len(r) > 1 and r[1] != want.get(keys[0]):
            bad.append(f"{keys[0]}: the spec's bar {r[1]}, the gate's {want.get(keys[0])}")
    return bad


def g_contrast(t: Texts) -> list[Finding]:
    return fails("G-CONTRAST", contrast_problems(t.spec))


def g_nevershed(t: Texts) -> list[Finding]:
    return fails("G-NEVERSHED", nevershed_problems(t.spec))


def g_copy(t: Texts) -> list[Finding]:
    return fails("G-COPY", copy_problems(t.spec))


def g_ac1(t: Texts) -> list[Finding]:
    return fails("G-AC1", ac1_problems(t))


STAMP_R366 = f"RULED (orchestrator, 2026-10-30, #366 ruling of record — {RULING_ID})"
STAMP_A41 = "RULED (orchestrator, 2026-10-30, #2701 ledger addendum A row A41)"
STAMP_A42 = "RULED (orchestrator, 2026-10-30, #2701 ledger addendum A row A42)"
STAMPS = (STAMP_R366, STAMP_A41, STAMP_A42)
STAMP_ANY = re.compile(r"RULED \(orchestrator[^)]*\)")
EXTRA_STAMP = {"BQ-04": STAMP_A41, "BQ-08": STAMP_A42}
# The ruled words, by source (R366 = the ruling of record; A4142 = #2701 ledger addendum A rows
# A41 / A42, 6522671326): each stands in the pack or the spec, and in the saved copy given.
RULING_PINS: dict[str, tuple[str, ...]] = {
    "R366": (
        "in the `15` queue after E15-D13's PR 2",
        "The scrolling tab row is rejected as proposed.",
        "Widen the window to arrange panels.",
        "Move to ▸ and Equal sizes kept as equivalents on the stored tree (the Move exit stays T1)",
        (
            "the hidden armed panel is disarmed on the server's answer, announced once in A30's form;"
            " hotkeys never reach a hidden tab"
        ),
        (
            "the trigger p95 frame time over a rolling 60 s window above 18.2 ms, sampled only while"
            " visible and focused, a 10 s warm-up after boot / restore / layout change, a single"
            " frame over 200 ms dropped"
        ),
        "PROPOSED until E15-K01 (#371) calibrates, then an A-row",
        "never a change without a click; Not now = none this session",
        "Don't ask again = none on this device",
        "Display quality on this device ▸ Full · Reduced",
        (
            "the server never reads it, no risk limit changes, the panel cap is a client display"
            " limit, stored locally without a user id"
        ),
        (
            "shell → private account state → the focused panel → the remaining charts → order-flow"
            " panels → auxiliary"
        ),
        "Workspace ready: 3 of 4 panels. 1 panel couldn't load: Chart, ABCUSDT.",
        "the shimmer stop at 5 s, no spinner over the canvas, [Retry] after 10 s (PROPOSED)",
        'never "Trading is off" where cancel and close remain',
        "file `E15-D12 boards`, page `E15-D12 responsive and degraded`",
        "the dry run by a reader outside E15",
        "requested when PR 1 is READY",
        (
            "contrast re-measured under reduced settings by the lo / hi method with the chrome"
            " revised, never the bar"
        ),
    ),
    "A4142": (
        "a display transform that never changes the stored layout",
        (
            "under 800 px tall the arrangement is kept, two conditional rows yield and one"
            " dismissible line explains the height"
        ),
        'never a blocking "increase window size" state',
        "One-click trading disarmed: {Kind} hidden in a tab.",
        "the design never arms or disarms by itself",
        "an armed one-click surface the user cannot see is the hazard A30 exists for",
    ),
}
BQ_LEAD = re.compile(r"^- \*\*(BQ-\d\d(?: / BQ-\d\d)?)")


def ruled_problems(t: Texts) -> list[str]:
    bad: list[str] = []
    covered: dict[str, int] = {}
    for ln in lines(t.pack):
        m = BQ_LEAD.match(ln)
        if m:
            for bq in m.group(1).split(" / "):
                covered[bq] = covered.get(bq, 0) + 1
                if STAMP_R366 not in ln:
                    bad.append(f"{bq}: the stamp is not {STAMP_R366!r}")
                if bq in EXTRA_STAMP and EXTRA_STAMP[bq] not in ln:
                    bad.append(f"{bq}: the stamp {EXTRA_STAMP[bq]!r} is missing")
        for s in STAMP_ANY.finditer(ln):
            if s.group(0) not in STAMPS:
                bad.append(f"a stamp in no ruled form: {s.group(0)!r}")
    for n in range(1, 22):
        if covered.get(f"BQ-{n:02d}") != 1:
            bad.append(f"BQ-{n:02d}: {covered.get(f'BQ-{n:02d}', 0)} ruled sites (want 1)")
    src = dict(t.sources)
    flat = norm(t.pack + "\n" + t.spec)
    for name, pins in RULING_PINS.items():
        for pin in pins:
            if norm(pin) not in flat:
                bad.append(f"{name}: the ruled words {pin!r} are not in the pack or the spec")
            if name in src and norm(pin) not in norm(src[name]):
                bad.append(f"{name}: {pin!r} is not in the saved copy")
    return bad


def g_ruled(t: Texts) -> list[Finding]:
    return fails("G-RULED", ruled_problems(t))


# ---------------------------------------------------------------------------- the pins

Unit = tuple[str, str, str]
FULL_STOP = re.compile(r"(?<=[.!?])\s+(?=[*`\"(A-Z0-9§])")


def pin_norm(text: str) -> str:
    return " ".join(text.split())


def units(text: str, doc: str) -> list[Unit]:
    out: list[Unit] = []
    path: list[tuple[int, str]] = []
    seen: dict[str, int] = {}
    region, k, fence = f"{doc}:(top)#1", 0, -1
    rows: dict[str, int] = {}
    buf: list[str] = []
    for raw in lines(unfill(text)):
        if fence >= 0:
            if raw == "```":
                digest = hashlib.sha256("\n".join(buf).encode("utf-8")).hexdigest()[:16]
                out.append((region, f"fence {fence}", f"{len(buf)} lines sha256:{digest}"))
                fence, buf = -1, []
            else:
                buf.append(raw)
            continue
        if FENCE.match(raw):
            k += 1
            fence = k
            continue
        m = HEADING.match(raw)
        if m:
            level = len(m.group(1))
            path = [p for p in path if p[0] < level] + [(level, pin_norm(m.group(2)))]
            key = f"{doc}:" + " › ".join(p[1] for p in path)
            seen[key] = seen.get(key, 0) + 1
            region, k, rows = f"{key}#{seen[key]}", 0, {}
            out.append((region, "heading", pin_norm(raw)))
            continue
        if not raw.strip() or RULE_ROW.match(raw):
            continue
        if raw.lstrip().startswith("|"):
            cells = split_row(raw)
            lead = pin_norm(cells[0]) if cells else "(blank)"
            rows[lead] = rows.get(lead, 0) + 1
            loc = f"row {lead}" + (f"#{rows[lead]}" if rows[lead] > 1 else "")
            out.append((region, loc, " | ".join(pin_norm(c) for c in cells)))
            continue
        for x in FULL_STOP.split(raw.strip()):
            if x.strip():
                k += 1
                out.append((region, f"s{k}", pin_norm(x)))
    return out


def all_units(t: Texts) -> list[Unit]:
    return units(t.pack, "pack") + units(t.hand, "hand") + units(t.spec, "spec")


def write_pins(us: list[Unit]) -> str:
    head = (
        "# E15-D12 pins (every unit of the pack, the hand-off and the spec): region, location, "
        f"the exact normalised text; {len(us)} units.\n# Written by `--repin-ruled` only; "
        "`--check` reads it (never hand-edit; see the tool's G-RULED-PIN).\n"
    )
    return head + "".join("\t".join(u) + "\n" for u in us)


def parse_pins(text: str) -> list[Unit]:
    out: list[Unit] = []
    for ln in lines(text):
        parts = ln.split("\t")
        if ln and not ln.startswith("#") and len(parts) == 3:
            out.append((parts[0], parts[1], parts[2]))
    return out


def pin_problems(pinned: list[Unit], current: list[Unit]) -> list[str]:
    """One message per region that differs."""
    if not pinned:
        return ["the pins file is empty or missing (run --repin-ruled)"]
    bad: list[str] = []
    by_old: dict[str, list[tuple[str, str]]] = {}
    by_new: dict[str, list[tuple[str, str]]] = {}
    for r, loc, txt in pinned:
        by_old.setdefault(r, []).append((loc, txt))
    for r, loc, txt in current:
        by_new.setdefault(r, []).append((loc, txt))
    for r in by_new:
        if r not in by_old:
            bad.append(f"region '{r[-60:]}' is unpinned (new)")
    for r in by_old:
        if r not in by_new:
            bad.append(f"region '{r[-60:]}' deleted or renamed")
    for r, now_units in by_new.items():
        if r in by_old and now_units != by_old[r]:
            was = dict(by_old[r])
            what = "units moved or reordered"
            for loc, txt in now_units:
                if was.get(loc) != txt:
                    what = f"{loc} changed: {txt[:40]!r}"
                    break
            bad.append(f"'{r[-48:]}' {what}")
    return bad


def g_ruled_pin(t: Texts) -> list[Finding]:
    return fails("G-RULED-PIN", pin_problems(parse_pins(t.pins), all_units(t)))


# ---------------------------------------------------------------------------- public text

# The lane's public-text list, held reversed so this file never spells a word it forbids.
_HIDDEN = (
    "kael",
    "desopxe",
    "ssapyb",
    "tiolpxe",
    "kcatta",
    "elcaro",
    "laever",
    "dednuobnu",
    "doolf",
    "llats",
    "yrosivda",
    "ashg",
    "htua-erp",
    "sod",
)
BANNED = re.compile("|".join(re.escape(w[::-1]) for w in _HIDDEN), re.IGNORECASE)
LOCAL_PATH = re.compile("/" + "(?:home|Users|mnt|tmp)" + r"/[^\s`)]+")
HOSTNAME = re.compile(r"\b[a-z0-9-]+\.(?:com|net|org|io)\b|\bpenpot\.[a-z0-9-]+\.", re.IGNORECASE)
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
URL = re.compile(r"https?://", re.IGNORECASE)
CLOSING = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s*(?:[\w-]+/[\w-]+)?#\d+", re.IGNORECASE
)
AGENTS = re.compile(r"\b(?:hpe|hcl)-worker-\d\b|\bsession [0-9a-f]{8}", re.IGNORECASE)


def public_problems(name: str, text: str) -> list[str]:
    bad: list[str] = []
    for rx, what in (
        (BANNED, "a word on the public-text list"),
        (LOCAL_PATH, "a local path"),
        (HOSTNAME, "a host name"),
        (UUID, "a uuid"),
        (URL, "a URL"),
        (CLOSING, "a closing keyword"),
        (AGENTS, "an agent or session name"),
    ):
        for m in rx.finditer(text):
            bad.append(f"{name}: {what} ({m.group(0)[:3]}…, offset {m.start()})")
    return bad


def g_public(t: Texts) -> list[Finding]:
    bad: list[str] = []
    for name, text in docs(t):
        bad += public_problems(name, text)
    return fails("G-PUBLIC", bad)


def g_crows(t: Texts) -> list[Finding]:
    return fails("G-CROWS", crow_problems(t.pack))


# ---------------------------------------------------------------------------- the dry run

DRY_WORDS = "To be run by the orchestrator's deputy (a reader outside E15), requested at READY"
DRY_DOD = "- [ ] The hand-off dry run"
DRY_TRACE = ("| T:83 item 9", "to be run by the orchestrator's deputy")
DRY_BRIEF = "Read ONLY this one file, in full: docs/design/specs/e15-responsive-and-degraded.md"


def dryrun_problems(t: Texts) -> list[str]:
    bad: list[str] = []
    body = section(t.spec, "14.")
    if DRY_WORDS not in body:
        bad.append("the spec §14 does not say the deputy runs it, at READY")
    if any(ln.startswith("| N") for ln in lines(body)):
        bad.append("the spec §14 holds a result although no outside run is recorded")
    dod = [
        ln
        for ln in lines(t.pack)
        if ln.startswith(("- [ ] The hand-off dry run", "- [x] The hand-off dry run"))
    ]
    if dod != [ln for ln in dod if ln.startswith(DRY_DOD)] or len(dod) != 1:
        bad.append("the DoD's dry-run line is not one open `[ ]` line")
    trace = [ln for ln in lines(t.pack) if ln.startswith(DRY_TRACE[0])]
    if len(trace) != 1 or DRY_TRACE[1] not in trace[0]:
        bad.append("the AC trace does not name the deputy for the dry run")
    app = section(t.pack, "Appendix — the dry-run brief")
    if "```text" not in app or DRY_BRIEF not in app:
        bad.append("the appendix does not keep the brief in a text fence")
    return bad


def g_dryrun(t: Texts) -> list[Finding]:
    return fails("G-DRYRUN", dryrun_problems(t))


def mutation_paragraph() -> str:
    parts = [f"**{g}:** M-{n} {d}" for n, (g, d, _) in enumerate(MUTATIONS, 1)]
    return "; ".join(parts) + "."


def g_mutlist(t: Texts) -> list[Finding]:
    ok = mutation_paragraph() in t.pack
    return fails("G-MUTLIST", [] if ok else ["§12 is not the tool's mutation list (run --fill)"])


# ---------------------------------------------------------------------------- the run

GATES: tuple[tuple[str, Callable[[Texts], list[Finding]]], ...] = (
    ("G-ANCHOR", g_anchor),
    ("G-CITE", g_cite),
    ("G-UNTOUCHED", g_untouched),
    ("G-AROW", g_arow),
    ("G-LEDGER", g_ledger),
    ("G-PARITY", g_parity),
    ("G-BUDGET", g_budget),
    ("G-CONTRAST", g_contrast),
    ("G-NEVERSHED", g_nevershed),
    ("G-COPY", g_copy),
    ("G-AC1", g_ac1),
    ("G-RULED", g_ruled),
    ("G-RULED-PIN", g_ruled_pin),
    ("G-PUBLIC", g_public),
    ("G-CROWS", g_crows),
    ("G-DRYRUN", g_dryrun),
    ("G-MUTLIST", g_mutlist),
)


def run(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for _, fn in GATES:
        out += fn(t)
    if any(f.level == "FAIL" and f.gate != "G-RULED-PIN" for f in out):
        out = [replace(f, level="NOTE") if f.gate == "G-RULED-PIN" else f for f in out]
    return out


def changed_paths() -> tuple[str, ...] | None:
    mb = git("merge-base", "HEAD", "origin/main")
    if mb is None:
        return None
    committed = git("diff", "--name-only", mb.strip(), "--")
    status = git("status", "--porcelain", "--untracked-files=all")
    if committed is None or status is None:
        return None
    paths = {p for p in committed.split("\n") if p}
    for ln in status.split("\n"):
        if ln.strip():
            paths.add(ln[3:].split(" -> ")[-1].strip('"'))
    return tuple(sorted(paths))


def load(sources: tuple[tuple[str, str], ...] = ()) -> Texts:
    mb = git("merge-base", "HEAD", "origin/main")
    mbase = tuple((k, at_sha(mb.strip(), rel) or "") for k, rel in TARGETS.items()) if mb else ()
    return Texts(
        pack=read(PACK_REL),
        hand=read(HAND_REL),
        spec=read(SPEC_REL),
        pins=read(PINS_REL),
        changed=changed_paths(),
        now=tuple((k, read(rel)) for k, rel in TARGETS.items()),
        mbase=mbase,
        sources=sources,
    )


# ---------------------------------------------------------------------------- the self-test


def _sub(field_name: str, old: str, new: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        text = getattr(t, field_name)
        if old not in text:
            raise SystemExit(f"self-test: {old[:50]!r} not found in {field_name}")
        kw: dict[str, Any] = {field_name: text.replace(old, new, 1)}
        return replace(t, **kw)

    return f


def _resub(field_name: str, pattern: str, new: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        text, n = re.subn(pattern, new, getattr(t, field_name), count=1, flags=re.MULTILINE)
        if n != 1:
            raise SystemExit(f"self-test: {pattern[:50]!r} not found in {field_name}")
        kw: dict[str, Any] = {field_name: text}
        return replace(t, **kw)

    return f


_TMP = "/" + "tmp" + "/scratch"
_CLOSE = "Clo" + "ses #366"

MUTATIONS: tuple[tuple[str, str, Callable[[Texts], Texts]], ...] = (
    (
        "G-ANCHOR",
        "hand-edit the chip word's ratio in dark",
        _sub("spec", "<!--=CR:chip.word.dark-->", "1<!--=CR:chip.word.dark-->"),
    ),
    (
        "G-CITE",
        "move the screen-size cite past the end of E15-D03",
        _sub("pack", "screen sizes as inputs (`D03`:684)", "screen sizes as inputs (`D03`:99684)"),
    ),
    (
        "G-UNTOUCHED",
        "simulate an edit to `14` in PR 1",
        lambda t: replace(t, changed=(t.changed or ()) + (TARGETS["14"],)),
    ),
    (
        "G-AROW",
        "alter one byte of A-11's Old",
        _sub("pack", "DismissedReappears, HighContrast.\n", "DismissedReappears, Highcontrast.\n"),
    ),
    (
        "G-LEDGER",
        "point a ledger row at a §C row that does not exist",
        _sub("pack", "the spec §9; A-1, A-2, A-3", "the spec §9; A-1, A-2, A-99"),
    ),
    (
        "G-PARITY",
        "drop the availability line from the splitters' row",
        _sub(
            "spec",
            'no visible boundary between panels; "Widen the window to arrange panels."',
            "no visible boundary between panels",
        ),
    ),
    (
        "G-BUDGET",
        "type the 1100-wide frame's band as W1",
        _resub("spec", r"(\| 1100 × 800\s*\| )W2", r"\g<1>W1"),
    ),
    (
        "G-CONTRAST",
        "type the glyph's bar as 2:1 in the spec",
        _resub("spec", r"(on `color\.status\.info\.subtle`\)\s*\|\s*)3:1", r"\g<1>2:1"),
    ),
    (
        "G-NEVERSHED",
        "rename the focus affordance in the never-shed list",
        _sub("spec", "- the focus affordance", "- the focus ring"),
    ),
    (
        "G-COPY",
        "name a part of the app in the overflow button's string",
        _sub("spec", '"{n} more panels" ·', '"{n} more GPU panels" ·'),
    ),
    (
        "G-AC1",
        "type a chrome height by hand in §3",
        _sub("pack", "**D-4 The height rule**", "**D-4 The height rule** (12 px)"),
    ),
    (
        "G-RULED",
        "split BQ-11's ruled words",
        _sub(
            "pack",
            "the panel cap is a client display limit, stored locally",
            "the panel cap is a client display limit; stored locally",
        ),
    ),
    (
        "G-RULED-PIN",
        "reword a sentence of the spec's scope",
        _sub("spec", "It states each rule once with its reason.", "It states each rule once."),
    ),
    (
        "G-PUBLIC",
        "paste a local path into the hand-off",
        _sub("hand", "## Table K — keyboard", f"## Table K — keyboard ({_TMP})"),
    ),
    ("G-CROWS", "renumber C-15", _sub("pack", "| C-15 |", "| C-16 |")),
    (
        "G-DRYRUN",
        "claim the dry run for the author in the spec",
        _sub("spec", f"**{DRY_WORDS}.**", "**Run by the author.**"),
    ),
    (
        "G-MUTLIST",
        "edit §12's list",
        _sub("pack", "**G-CROWS:** M-15 renumber C-15", "**G-CROWS:** M-15 renumber C-12"),
    ),
)


def _pr2(t: Texts, extra: str = "", pins: str | None = None) -> Texts:
    """PR 2's working tree: `14` and `16` with §C applied (`16` plus `extra`), pins as given."""
    rows, mb = a_rows(t.pack)[0], dict(t.mbase)
    now = dict(t.now)
    now["14"] = apply_rows(mb.get("14", ""), rows, "14") or ""
    now["16"] = (apply_rows(mb.get("16", ""), rows, "16") or "") + extra
    changed = (TARGETS["14"], TARGETS["16"], PINS_REL)
    return replace(
        t, changed=changed, now=tuple(now.items()), pins=t.pins if pins is None else pins
    )


def _source_short(t: Texts) -> Texts:
    return replace(t, sources=(("A4142", " ".join(RULING_PINS["A4142"][:-1])),))


PROBES: tuple[tuple[str, str, Callable[[Texts], Texts]], ...] = (
    ("G-UNTOUCHED", "PR 2 with one byte more than §C in `16`", lambda t: _pr2(t, " ")),
    ("G-UNTOUCHED", "git cannot name the changed paths", lambda t: replace(t, changed=None)),
    (
        "G-UNTOUCHED",
        "PR 2 with a pins file that is not the tool's rewrite",
        lambda t: _pr2(t, "", t.pins + "# a hand edit\n"),
    ),
    ("G-PUBLIC", "a closing keyword in the pack", _sub("pack", "## 13.", f"## 13. ({_CLOSE})")),
    ("G-RULED", "a saved copy of A41 / A42 lacking one ruled phrase", _source_short),
    (
        "G-AROW",
        "a byte of a CMP-251 row's Old (A-15, DEPENDS)",
        _sub("pack", "LongLabel (every story in dark", "LongLabel  (every story in dark"),
    ),
    ("G-DRYRUN", "the DoD claims the dry run", _sub("pack", DRY_DOD, "- [x] The hand-off dry run")),
    ("G-ANCHOR", "an unfilled placeholder in §7", _sub("pack", "## 7.", "## 7. {{COUNT:arows}}")),
    (
        "G-COPY",
        "a kept string reworded (CP-4, SR-45)",
        _sub(
            "spec",
            '"Reduced quality: lower heatmap depth;',
            '"Reduced quality: less heatmap depth;',
        ),
    ),
    ("G-BUDGET", "a sweep frame dropped", _resub("spec", r"^\| 1280 × 640 .*\n", "")),
)
# A PR 2 that applies §C exactly, with the tool's own pins rewrite: no new FAIL (lesson 1).
CLEAN: tuple[tuple[str, Callable[[Texts], Texts]], ...] = (
    ("PR 2: `14` and `16` with §C applied, pins rewritten by the tool", lambda t: _pr2(t)),
)


def fail_keys(fs: list[Finding]) -> list[tuple[str, str]]:
    return [(f.gate, f.msg) for f in fs if f.level == "FAIL"]


def digests() -> dict[str, str]:
    return {p: hashlib.sha256(read(p).encode("utf-8")).hexdigest() for p in OWN_PATHS}


def self_test(t: Texts) -> list[str]:
    before = digests()
    base = fail_keys(run(t))
    bad: list[str] = []
    for label, items in (("M", MUTATIONS), ("P", PROBES)):
        for n, (gate, desc, fn) in enumerate(items, 1):
            got = fail_keys(run(fn(t)))
            new = [k for k in got if k not in base]
            if len(new) != 1 or new[0][0] != gate:
                shown = ", ".join(f"{g}: {m[:60]}" for g, m in new[:4]) or "none"
                bad.append(f"{label}-{n} ({gate}, {desc}): {len(new)} new FAIL(s) [{shown}]")
    for n, (desc, fn) in enumerate(CLEAN, 1):
        new = [k for k in fail_keys(run(fn(t))) if k not in base]
        if new:
            bad.append(f"CL-{n} ({desc}): {len(new)} new FAIL(s) [{new[0][0]}: {new[0][1][:60]}]")
    if fail_keys(run(t)) != base:
        bad.append("self-test: a re-run does not reproduce the base result")
    if digests() != before:
        bad.append("self-test: a file on disk changed")
    return bad


# ---------------------------------------------------------------------------- main


def parse_sources(items: list[str]) -> tuple[tuple[str, str], ...]:
    out: list[tuple[str, str]] = []
    for item in items:
        name, _, path = item.partition("=")
        if name not in RULING_PINS or not path:
            raise SystemExit(f"--source takes NAME=FILE with NAME one of {sorted(RULING_PINS)}")
        out.append((name, Path(path).read_text(encoding="utf-8")))
    return tuple(out)


def write_if_changed(rel: str, text: str) -> bool:
    if read(rel) == text:
        return False
    (ROOT / rel).write_text(text, encoding="utf-8")
    return True


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 on any FAIL")
    ap.add_argument("--json", action="store_true", help="print the values and findings as JSON")
    ap.add_argument("--fill", action="store_true", help="fill the placeholders and §12's list")
    ap.add_argument("--self-test", action="store_true", help="one mutation per gate, the probes")
    ap.add_argument("--repin-ruled", action="store_true", help="rewrite the pins file")
    ap.add_argument("--a-rows", action="store_true", help="print §C as JSON, a target per row")
    ap.add_argument("--source", action="append", default=[], help="NAME=FILE, a saved ruling")
    args = ap.parse_args(argv)
    if any(at_key(k) is None for k in KEYS):
        print(f"FAIL [G-CITE] the inputs are unreadable at {BASE} / {D13_SHA} (fetch first)")
        return 1
    t = load(parse_sources(args.source))
    if args.a_rows:
        print(json.dumps(export(a_rows(t.pack)[0]), ensure_ascii=False, indent=1))
        return 0
    if args.fill:
        v = compute(t)
        for rel in (PACK_REL, HAND_REL, SPEC_REL):
            text, missing = fill(ANCHORED.sub(lambda m: "{{" + m.group(2) + "}}", read(rel)), v)
            text = re.sub(r"(?m)^\*\*G-ANCHOR:\*\* M-1 .*$", mutation_paragraph(), text)
            for key in missing:
                print(f"no value for {key} in {rel}")
            write_if_changed(rel, text)
        t = load(t.sources)
    if args.repin_ruled:
        if any(PLACEHOLDER.search(re.sub(r"`[^`\n]*`", "", unfence(x))) for _, x in docs(t)):
            print("refused: a placeholder is unfilled (run --fill first)")
            return 1
        write_if_changed(PINS_REL, write_pins(all_units(t)))
        t = load(t.sources)
    found = run(t)
    st = self_test(t) if args.self_test else []
    if args.json:
        payload: dict[str, object] = {
            "values": compute(t),
            "findings": [f"{f.level} [{f.gate}] {f.msg}" for f in found],
        }
        if args.self_test:
            payload["self_test"] = st
        print(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True))
    else:
        out = [f"{f.level} [{f.gate}] {f.msg}" for f in found]
        n_fail = sum(f.level == "FAIL" for f in found)
        n_warn = sum(f.level == "WARN" for f in found)
        rows = a_rows(t.pack)[0]
        by = {k: sum(r.file == k for r in rows) for k in TARGETS}
        out.append(
            f"gates: {len(GATES)}; FAIL {n_fail}, WARN {n_warn}; §C rows {len(rows)} "
            f"({by['14']} to `14`, {by['15']} to `15`, {by['16']} to `16`, "
            f"{sum(bool(r.depends) for r in rows)} depending on E15-D13's PR 2)"
        )
        if args.self_test:
            out += [f"FAIL [self-test] {x}" for x in st]
            out.append(
                f"self-test: {'ok' if not st else 'FAILED'}: {len(MUTATIONS)} mutations (one per "
                f"gate) and {len(PROBES)} probes, each one new FAIL from its gate; {len(CLEAN)} "
                "clean PR 2 case with none; a re-run reproduces the base result; files on disk "
                "unchanged"
            )
        print("\n".join(out))
    failed = any(f.level == "FAIL" for f in found) or bool(st)
    return 1 if failed and (args.check or args.self_test) else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
