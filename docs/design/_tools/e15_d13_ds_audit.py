#!/usr/bin/env python3
"""E15-D13 (#367) audit: the design-system pack for the dock and panel-chrome band.

Stdlib only, offline (`python3 -I -B`). It reads AS TEXT at the pinned base (`git show BASE:<path>`)
the plan texts (`05`, `15`, `16`), the merged E15 design texts (E15-D02 ... E15-D09, E15-D15 and
the D03 ... D07 hand-offs) and the token JSON; then the pack (`E15-D13.md`), its hand-off, the
usage-rules document and the pins from the working tree. It imports, never copies, the shared
functions: `contrast_check.contrast_ratio()` for every WCAG ratio, the research CVD script's
`simulate()` and `delta_e76()` for colour vision, and `verify_tokens.merged_set()` / `resolve()`
for the theme layering (dark = primitives + semantic-dark; light and high contrast layer on it).

Values. Every `{{KIND:key}}` outside a code span is COMPUTED: CR (a WCAG ratio, two decimals), CVD
(the least CIE76 distance between the three sync hues under a simulation, one decimal), HOST (the
darkest or lightest hosted content of a theme), BUDGET (a density figure from the tokens) and COUNT
(the pack's own rows). `--fill` writes `VALUE<!--=KIND:key-->`; `--check` re-derives every
anchored value. The gates, each FAIL led by its code:

- [G-ANCHOR] every anchored value equals the tool's; no placeholder left unfilled.
- [G-FIGURE] no ratio or colour distance typed by hand outside an anchor (the bars 3:1, 4.5:1 and
  7:1 excepted); §C's carried figures are gated by G-PARENT instead.
- [G-CITE] every `KEY`:line cite (each end of a range) resolves at the base to a non-blank line,
  and each load-bearing
  fragment (CITED) stands on the line its cite names.
- [G-UNTOUCHED] PR 1: only the pack's five files differ from `git merge-base HEAD origin/main`.
  PR 2 (none of the five differs, `15` or `16` does): `15` and `16` equal the merge-base with every
  §C row not in HELD applied, each re-pointed by content, and no other byte. Fails closed when git
  cannot answer.
- [G-AROW] §C: rows A-1 ... A-n in order, each with its target file (`15` or `16`), its line, a
  known op and its Old (or anchor) equal to the base line and unique in its file; a table row keeps
  every column's width (prettier would re-pad the table otherwise).
- [G-HELD] the HELD set is exactly CMP-215's Props and Tokens rows (E15-D10, #364); its
  environment rule is applied.
- [G-PARENT] the rows of record copied byte for byte: E15-D15 A-3 ... A-5 (Old fragment in Old, New
  fragment in New), E15-D07 Table A (anchors dropped, `\\|` read as `|`, "spec" named E15-D07); the
  letter rule on `color.sync.*` and in CMP-218 and CMP-082.
- [G-LEDGER] §2: dispositions from the vocabulary, the counts, every "Here" row present in §C.
- [G-TOKEN] §5 (post-2T mode, by content: the ten tokens already ship at the base, so each is
  asserted present with the pack's alias, and the token files may change under G-UNTOUCHED; a
  token missing from one theme is a FAIL line, never a crash; the hc theme inherits the dark
  file's sync lines, so its sync lines are asserted equal to dark's through the merged set):
  each addition aliases a primitive that exists at the base and is itself new; no `e15.*` name;
  each confirmation exists; each retirement is absent from the token source; no document carries
  a name R19 rejected (the frame's old name, a tab-strip row token); every token named in a §C Tokens line is shipped, added here, or retired with "(Replaces".
- [G-CONTRAST] the gated pairs meet their bars in three themes (sync edges on the header and the
  canvas, the drop-zone two-tone over every hosted content, the focus frame, the environment rule
  and word in focused and unfocused chrome), and the reproductions equal E15-D03, E15-D04 and
  E15-D06 to the hundredth.
- [G-DENSITY] the allowance and ceiling recomputed from the new tokens equal E15-D03 §3's budget;
  the four-panel 1280x800 compact case fits every column's framed minimum; the `16` §3 table in §C
  equals the computed rows, the tab strip's row carrying R19's derivation rule (DERIVATION).
- [G-AC1] the token audit over the merged E15 texts: every hex anywhere and every px or ms value in
  a token, treatment or redline column (or under a token or redline heading) is anchored by its
  parent's tool, names a token in its clause, or stands in §9's exception table; no exception row
  is stale.
- [G-RULED] the stamps in their exact forms at their sites, the ruled words (RULING_PINS) and the
  ruled sweep's note in both CMP-039's and CMP-080's rows (SWEEP_SITES); the dry run of record
  (the outside reader's, DRYRUN_ID) named in the usage rules §9 and cited by AC3, the DoD line and
  D3; the usage rules naming the sync badge's renderer (R-8) and how a kind is registered (§6);
  with `--source NAME=FILE` each pin also stands in that saved copy of the ruling.
- [G-RULED-PIN] a default-deny pin set over every unit of the three documents (each heading, table
  row by its lead cell, prose sentence and fenced block) in `e15_d13_ruled_pins.txt`, anchored
  values cut out. `--repin-ruled` is its only writer. When another gate FAILs, every G-RULED-PIN
  finding prints as a NOTE; the exit status stays 1.
- [G-PUBLIC] no word on the public-text list (matched by pattern), no local path, host, uuid, URL
  or closing keyword.
- [G-CROWS] §10's C-rows C-1 ... C-16 in order, each with a reading and an owner.
- [G-ENTRY] the four new entries carry every §0.1 field plus Forbidden, Performance, Motion spec and
  "Why a new entry, not a variant", and a Storybook tree `Organisms/Dock/<Name>`.
- [G-MUTLIST] §12 lists the tool's mutations, one per gate, by name.

`--a-rows` prints §C as JSON, one record per row with its target file; `--self-test` applies one
mutation per gate (MUTATIONS) and the probes (PROBES) to an in-memory copy and passes only when each
adds exactly one new FAIL with its gate's code, a re-run reproduces the base result and no file on
disk changed. The `--json` dump carries values and findings only.

Usage (from the repo root):
  python3 -I -B docs/design/_tools/e15_d13_ds_audit.py --check [--json] [--fill]
  python3 -I -B docs/design/_tools/e15_d13_ds_audit.py --self-test
  python3 -I -B docs/design/_tools/e15_d13_ds_audit.py --repin-ruled
  python3 -I -B docs/design/_tools/e15_d13_ds_audit.py --a-rows
  python3 -I -B docs/design/_tools/e15_d13_ds_audit.py --check --source R367=FILE --source A3940=FILE
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
from functools import cache, lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
BASE = "1bb750e725"  # `git merge-base HEAD origin/main` at writing (#5026's merge)
SPEC_REL = "docs/design/E15/E15-D13.md"
HAND_REL = "docs/design/E15/E15-D13-handoff.md"
RULES_REL = "docs/design/specs/e15-design-system-contributions.md"
TOOL_REL = "docs/design/_tools/e15_d13_ds_audit.py"
PINS_REL = "docs/design/_tools/e15_d13_ruled_pins.txt"
OWN_PATHS = (SPEC_REL, HAND_REL, RULES_REL, TOOL_REL, PINS_REL)
CAT_REL = "docs/plan/15-component-catalogue.md"
BRIEF_REL = "docs/plan/16-design-system-brief.md"
TARGETS = {"15": CAT_REL, "16": BRIEF_REL}
RULING_ID = "6519042539"
R19_ID = "6521896277"  # the #367 comment mirroring the lane ruling R19
DRYRUN_ID = "6521699455"  # the #367 comment recording the dry run by a reader outside E15
E15 = "docs/design/E15/E15-"
KEYS: dict[str, str] = {
    "05": "docs/plan/05-accessibility-standard.md",
    "15": CAT_REL,
    "16": BRIEF_REL,
    "D02": E15 + "D02.md",
    "D03": E15 + "D03.md",
    "D03h": E15 + "D03-handoff.md",
    "D04": E15 + "D04.md",
    "D04h": E15 + "D04-handoff.md",
    "D05": E15 + "D05.md",
    "D05h": E15 + "D05-handoff.md",
    "D06": E15 + "D06.md",
    "D06h": E15 + "D06-handoff.md",
    "D07": E15 + "D07.md",
    "D07h": E15 + "D07-handoff.md",
    "D08": E15 + "D08.md",
    "D09": E15 + "D09.md",
    "D15": E15 + "D15.md",
    "E05D03": "docs/design/E05/E05-D03.md",
    "E09D07": "docs/design/E09/E09-D07.md",
}
AC1_DOCS = (
    "D03",
    "D03h",
    "D04",
    "D04h",
    "D05",
    "D05h",
    "D06",
    "D06h",
    "D07",
    "D07h",
    "D08",
    "D09",
    "D15",
)
TOKENS_DIR = "packages/ui/tokens"
THEMES = ("dark", "light", "high-contrast")
THEME_KEY = {"dark": "dark", "light": "light", "high-contrast": "hc"}


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
CVD = _load(ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py", "cvd_simulate")


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
def at_base(rel: str) -> str | None:
    return git("show", f"{BASE}:{rel}")


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


def section(text: str, title: str) -> str:
    """The body of the `## ` section whose heading starts with `title`."""
    out: list[str] = []
    on, fenced = False, False
    for ln in lines(text):
        if FENCE.match(ln):
            fenced = not fenced
        elif ln.startswith("## ") and not fenced:
            on = ln[3:].startswith(title)
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


# ---------------------------------------------------------------------------- tokens and colour


HIDE: dict[str, str] = {"color.sync.a": ""}  # the self-test hides a token in one theme


@cache
def _merged(theme: str) -> dict[str, Any]:
    files = [VERIFY.PRIMITIVES, *VERIFY.THEMES[theme]]
    merged: dict[str, Any] = VERIFY.merged_set(files)
    return merged


def theme_set(theme: str) -> dict[str, Any]:
    return {k: v for k, v in _merged(theme).items() if HIDE.get(k) != theme}


def token_names() -> frozenset[str]:
    out: set[str] = set()
    for t in THEMES:
        out |= set(theme_set(t))
    return frozenset(out)


def primitive_names() -> frozenset[str]:
    return frozenset(VERIFY.load(VERIFY.PRIMITIVES))


def value(name: str, theme: str = "dark") -> Any:
    t = theme_set(theme)
    return VERIFY.resolve(t[name]["$value"], t)


def px(name: str) -> int:
    return int(value(name))


# The sync hues (BQ-08): palette references per theme, never a semantic-to-semantic alias. The
# references equal what E15-D06's stand-in aliases resolve to at the base (G-TOKEN checks it).
SYNC_REF: dict[str, dict[str, str]] = {
    "a": {"dark": "palette.cyan.300", "light": "palette.light.cyan.300"},
    "b": {"dark": "palette.amber.300", "light": "palette.light.amber.300"},
    "c": {"dark": "palette.purple.500", "light": "palette.purple.600"},
}
SYNC_STANDIN = {
    "a": "color.status.info.strong",
    "b": "color.status.warning.strong",
    "c": "color.node.logic",
}


def sync_hex(letter: str, theme: str) -> str:
    ref = SYNC_REF[letter]["light" if theme == "light" else "dark"]
    return str(value(ref, theme)).upper()


def hexof(name: str, theme: str) -> str:
    if name.startswith("color.sync."):
        return sync_hex(name.rsplit(".", 1)[1], theme)
    return str(value(name, theme)).upper()


def rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def ratio(a: str, b: str) -> float:
    r: float = CONTRAST.contrast_ratio(rgb(a), rgb(b))
    return r


def grey(h: str) -> str:
    r, g, b = rgb(h)
    y = round(0.299 * r + 0.587 * g + 0.114 * b)
    return f"#{y:02X}{y:02X}{y:02X}"


def de(a: str, b: str) -> float:
    d: float = CVD.delta_e76(a, b)
    return d


def sim(h: str, kind: str) -> str:
    s: str = CVD.simulate(h, kind)
    return s.upper()


def f2(x: float) -> str:
    return f"{x:.2f}"


def f1(x: float) -> str:
    return f"{x:.1f}"


# E15-D03 §11.2's lo / hi: the extremes over the panel surfaces; BQ-08 adds a dense footprint.
SURFACES = (
    "color.surface.sunken",
    "color.surface.app",
    "color.surface.canvas",
    "color.surface.raised",
    "color.surface.overlay",
)
FOOTPRINT = ("color.footprint.bid", "color.footprint.ask", "color.footprint.imbalance")
HOSTED = SURFACES + FOOTPRINT
CHROME = {"header": "color.surface.raised", "canvas": "color.surface.canvas"}  # the badge's hosts
SELECTED = "color.surface.selected"  # the focused panel bar: the badge's host, reported only
WINDOW = {"focused": "color.surface.raised", "unfocused": "color.surface.app"}  # CMP-215's chrome
BARS = {"text": 4.5, "non-text": 3.0}


def lum(h: str) -> float:
    r: float = CONTRAST.relative_luminance(rgb(h))
    return r


def extremes(theme: str) -> tuple[str, str]:
    """(darkest, lightest) hosted content of a theme, by relative luminance."""
    ranked = sorted(HOSTED, key=lambda n: (lum(hexof(n, theme)), n))
    return ranked[0], ranked[-1]


def two_tone(fg: str, halo: str, bg: str) -> float:
    """The better of the two tones against the background (the carrier's rescue)."""
    return max(ratio(fg, bg), ratio(halo, bg))


def colour_values() -> dict[str, str]:
    v: dict[str, str] = {}
    for th in THEMES:
        k = THEME_KEY[th]
        lo, hi = extremes(th)
        v[f"HOST:lo.{k}"] = f"`{lo}`"
        v[f"HOST:hi.{k}"] = f"`{hi}`"
        for s in "abc":
            h = sync_hex(s, th)
            for where, bg in CHROME.items():
                v[f"CR:sync.{s}.{where}.{k}"] = f2(ratio(h, hexof(bg, th)))
            v[f"CR:sync.{s}.selected.{k}"] = f2(ratio(h, hexof(SELECTED, th)))
            v[f"CR:sync.{s}.lo.{k}"] = f2(ratio(h, hexof(lo, th)))
            v[f"CR:sync.{s}.hi.{k}"] = f2(ratio(h, hexof(hi, th)))
        ring, halo = hexof("color.focus.ring", th), hexof("color.surface.canvas", th)
        v[f"CR:drop.twotone.{k}"] = f2(min(two_tone(ring, halo, hexof(b, th)) for b in HOSTED))
        v[f"CR:drop.ringhalo.{k}"] = f2(ratio(ring, halo))
        v[f"CR:drop.ringalone.{k}"] = f2(ratio(ring, hexof("color.text.primary", th)))
        surf = sorted(SURFACES, key=lambda n: lum(hexof(n, th)))
        v[f"CR:focus.lo.{k}"] = f2(ratio(ring, hexof(surf[0], th)))
        v[f"CR:focus.hi.{k}"] = f2(ratio(ring, hexof(surf[-1], th)))
        for where, bg in WINDOW.items():
            b = hexof(bg, th)
            v[f"CR:env.live.{where}.{k}"] = f2(ratio(hexof("color.env.live", th), b))
            v[f"CR:env.demo.{where}.{k}"] = f2(ratio(hexof("color.env.demo", th), b))
            v[f"CR:env.word.{where}.{k}"] = f2(ratio(hexof("color.text.primary", th), b))
        hues = {s: sync_hex(s, th) for s in "abc"}
        for kind in ("protanopia", "deuteranopia", "tritanopia", "greyscale"):
            simd = {s: (grey(h) if kind == "greyscale" else sim(h, kind)) for s, h in hues.items()}
            least = min(de(simd[a], simd[b]) for a, b in (("a", "b"), ("a", "c"), ("b", "c")))
            v[f"CVD:sync.{kind}.{k}"] = f1(least)
    return v


def gated_pairs() -> list[tuple[str, float, float]]:
    """(name, measured, bar) for every gated pair, three themes."""
    out: list[tuple[str, float, float]] = []
    for th in THEMES:
        ring, halo = hexof("color.focus.ring", th), hexof("color.surface.canvas", th)
        for s in "abc":
            for where, bg in CHROME.items():
                out.append(
                    (
                        f"sync.{s} on {where} ({th})",
                        ratio(sync_hex(s, th), hexof(bg, th)),
                        BARS["non-text"],
                    )
                )
        for b in HOSTED:
            out.append(
                (
                    f"drop zone two-tone over {b} ({th})",
                    two_tone(ring, halo, hexof(b, th)),
                    BARS["non-text"],
                )
            )
        out.append((f"drop zone ring against its halo ({th})", ratio(ring, halo), BARS["non-text"]))
        for b in SURFACES:
            out.append((f"focus frame on {b} ({th})", ratio(ring, hexof(b, th)), BARS["non-text"]))
        for where, bg in WINDOW.items():
            b = hexof(bg, th)
            for env in ("live", "demo"):
                out.append(
                    (
                        f"env {env} rule, {where} chrome ({th})",
                        ratio(hexof(f"color.env.{env}", th), b),
                        BARS["non-text"],
                    )
                )
            out.append(
                (
                    f"env word, {where} chrome ({th})",
                    ratio(hexof("color.text.primary", th), b),
                    BARS["text"],
                )
            )
    return out


# ---------------------------------------------------------------------------- density (BQ-10)


def parent_anchor(doc: str, key: str) -> str | None:
    """A value E15-D03 (or another parent) anchors at the base, read from its text."""
    text = at_base(KEYS[doc]) or ""
    m = re.search(r"(\d[\d×.]*(?: / \d[\d×.]*)*)<!--=" + re.escape(key) + r"-->", text)
    return m.group(1) if m else None


def budget_values() -> dict[str, str]:
    c, f = px("size.control.compact"), px("size.control.comfortable")
    s1, hl, th, fo = px("space.1"), px("border.hairline"), px("border.thick"), px("border.focus")
    hit = px("size.target.min")
    tabs = (c + 2 * s1, f + 2 * s1)  # DERIVATION (R19): no token holds the tab strip's row
    v = {
        "BUDGET:gutter": str(s1),
        "BUDGET:header.compact": str(c),
        "BUDGET:header.comfortable": str(f),
        "BUDGET:tabs.compact": str(tabs[0]),
        "BUDGET:tabs.comfortable": str(tabs[1]),
        "BUDGET:tray.compact": str(c),
        "BUDGET:tray.comfortable": str(f),
        "BUDGET:badge.compact": str(c - s1),
        "BUDGET:badge.comfortable": str(f - s1),
        "BUDGET:hit": str(hit),
        "BUDGET:frame": str(fo),
        "BUDGET:bar": str(th + hl),
        "BUDGET:line.rest": str(hl),
        "BUDGET:line.active": str(th),
    }
    top = int(parent_anchor("D03", "BUDGET:v.topbar") or 0)
    bottom = int(parent_anchor("D03", "BUDGET:v.statusbar") or 0)
    for dens, (ctl, tab) in {"compact": (c, tabs[0]), "comfortable": (f, tabs[1])}.items():
        allowance = top + tab + ctl + ctl + ctl + bottom  # tab strip, header, status, time strip
        conditional = tab + tab + ctl + ctl  # banner, restore notice, tab-group row, tray
        v[f"BUDGET:allowance.{dens}"] = str(allowance)
        v[f"BUDGET:ceiling.{dens}"] = str(allowance + conditional)
    canvas = (parent_anchor("D03", "BUDGET:canvas.1280") or "0×0").split("×")
    width, height = int(canvas[0]), int(canvas[1]) - tabs[0]
    v["BUDGET:dock.1280"] = f"{width}×{height}"
    split = [
        int(x)
        for x in re.findall(r"\d+", parent_anchor("D03", "BUDGET:dense.split.1280.compact") or "")
    ]
    v["BUDGET:split.sum"] = str(sum(split) + 2 * s1)
    frame2 = 2 * fo
    mins = {
        "chart": int(parent_anchor("D03", "BUDGET:hdr.chart.min") or 0) + frame2,
        "dom": int(parent_anchor("D03", "BUDGET:hdr.dom.s7.framed") or 0),
        "tape": int(parent_anchor("D03", "BUDGET:hdr.tape.min") or 0) + frame2,
        "positions": int(parent_anchor("D03", "BUDGET:hdr.positions.min") or 0) + frame2,
    }
    for k, m in mins.items():
        v[f"BUDGET:min.{k}"] = str(m)
    return v


def density_problems() -> list[str]:
    v = budget_values()
    bad: list[str] = []
    for dens in ("compact", "comfortable"):
        for kind in ("allowance", "ceiling"):
            mine = v[f"BUDGET:{kind}.{dens}"]
            parent = parent_anchor("D03", f"BUDGET:v.{kind}.{dens}")
            if mine != parent:
                bad.append(f"the {dens} {kind} {mine} is not E15-D03's budget {parent}")
    dock = v["BUDGET:dock.1280"]
    if dock != parent_anchor("D03", "BUDGET:dock.1280.compact"):
        bad.append(f"the 1280 compact dock area {dock} is not E15-D03's")
    width = int(dock.split("×")[0])
    if int(v["BUDGET:split.sum"]) != width:
        bad.append("the four-panel columns and gutters do not fill the dock's width")
    split = [
        int(x)
        for x in re.findall(r"\d+", parent_anchor("D03", "BUDGET:dense.split.1280.compact") or "")
    ]
    for col, kind in zip([*split, width], ("chart", "dom", "tape", "positions")):
        if col < int(v[f"BUDGET:min.{kind}"]):
            bad.append(f"the {kind} column {col} is below its framed minimum")
    return bad


def density_table() -> list[list[str]]:
    v = budget_values()
    g = v.__getitem__
    return [
        ["Gutter", g("BUDGET:gutter"), g("BUDGET:gutter"), "`space.dockgrid.gutter`"],
        [
            "Panel header row, tab-group row",
            g("BUDGET:header.compact"),
            g("BUDGET:header.comfortable"),
            "`space.panelheader.height.*`",
        ],
        [
            "Workspace tab strip, MoveModeBar",
            g("BUDGET:tabs.compact"),
            g("BUDGET:tabs.comfortable"),
            DERIVATION,
        ],
        [
            "Minimised tray",
            g("BUDGET:tray.compact"),
            g("BUDGET:tray.comfortable"),
            "`space.dock.tray.height.*`",
        ],
        [
            "Sync badge pill (its hit box the row)",
            g("BUDGET:badge.compact"),
            g("BUDGET:badge.comfortable"),
            "`size.control.*` less `space.1`",
        ],
        [
            "Splitter line, rest / active",
            f"{g('BUDGET:line.rest')} / {g('BUDGET:line.active')}",
            f"{g('BUDGET:line.rest')} / {g('BUDGET:line.active')}",
            "`border.hairline` / `border.thick`",
        ],
        ["Splitter hit band", g("BUDGET:hit"), g("BUDGET:hit"), "`size.dock.splitter.hit`"],
        [
            "Focus frame / header bar",
            f"{g('BUDGET:frame')} / {g('BUDGET:bar')}",
            f"{g('BUDGET:frame')} / {g('BUDGET:bar')}",
            "`border.panel.focus` / `border.thick` + `border.hairline`",
        ],
    ]


# ---------------------------------------------------------------------------- §C: the A-rows


@dataclass(frozen=True)
class ARow:
    aid: str
    entry: str
    fld: str
    file: str  # "15" or "16"
    line: int
    op: str
    src: str
    held: str
    old: str  # the base line (replace), a fragment of it (replace fragment) or the anchor line
    new: str


OPS = ("replace", "replace fragment", "insert after")
ROW_HEAD = re.compile(r"^#### (A-\d+) · (.+?) · (.+)$")
ROW_META = re.compile(r"^`(15|16)`:(\d+) · ([a-z ]+?) · from (.+?)" r"(?: · HELD for (.+))?$")


def a_rows(spec: str) -> tuple[list[ARow], list[str]]:
    """§C's rows and the parse problems."""
    body = section(spec, "§C")
    rows: list[ARow] = []
    bad: list[str] = []
    ls = lines(body)
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
        file, line, op, src, held = meta.groups()
        (k1, old), (k2, new) = blocks
        want = "anchor" if op == "insert after" else "old"
        if k1 != want or k2 != "new" or len(old) != 1:
            bad.append(f"{aid}: the blocks are not ```{want} (one line) then ```new")
        rows.append(
            ARow(
                aid,
                entry,
                fld,
                file,
                int(line),
                op,
                src,
                held or "",
                old[0] if old else "",
                "\n".join(new),
            )
        )
        i = j
    return rows, bad


def scope_heading(base_lines: list[str], idx: int) -> str:
    for k in range(idx, -1, -1):
        if HEADING.match(base_lines[k]):
            return base_lines[k]
    return ""


def locate(cur: list[str], base_lines: list[str], row: ARow) -> int | None:
    """Re-point a row by content: its scope heading (the heading above it at the base), then the
    one line equal to its Old inside that scope. A heading row is found directly."""
    frag = row.op == "replace fragment"
    if HEADING.match(row.old) and not frag:
        same = [k for k, ln in enumerate(cur) if ln == row.old]
        return same[0] if len(same) == 1 else None
    head = scope_heading(base_lines, row.line - 1)
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
        if (row.old in cur[k]) if frag else (cur[k] == row.old):
            hits.append(k)
    return hits[0] if len(hits) == 1 else None


def apply_rows(text: str, base_text: str, rows: list[ARow], file: str) -> str | None:
    """`text` with every non-HELD row for `file` applied; None when a row cannot be re-pointed."""
    cur, base_lines = lines(text), lines(base_text)
    edits: list[tuple[int, int, ARow]] = []
    for r in rows:
        if r.file != file or r.held:
            continue
        k = locate(cur, base_lines, r)
        if k is None:
            return None
        edits.append((k, 0 if r.op == "insert after" else 1, r))
    for k, _, r in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        if r.op == "replace fragment":
            cur[k] = cur[k].replace(r.old, r.new, 1)
        elif r.op == "replace":
            cur[k : k + 1] = lines(r.new)
        else:
            cur[k + 1 : k + 1] = lines(r.new)
    return "\n".join(cur)


def export(rows: list[ARow]) -> list[dict[str, object]]:
    return [
        {
            "id": r.aid,
            "target_file": TARGETS[r.file],
            "line": r.line,
            "op": r.op,
            "entry": r.entry,
            "field": r.fld,
            "from": r.src,
            "held": r.held or None,
            "anchor" if r.op == "insert after" else "old": r.old,
            "new": r.new,
        }
        for r in rows
    ]


def table_widths(base_lines: list[str], idx: int) -> list[int]:
    j = idx
    while j > 0 and base_lines[j - 1].startswith("|"):
        j -= 1
    k = idx
    while k + 1 < len(base_lines) and base_lines[k + 1].startswith("|"):
        k += 1
    rows = [split_row(x) for x in base_lines[j : k + 1] if not RULE_ROW.match(x)]
    return [max(len(r[c]) for r in rows) for c in range(len(rows[0]))]


def arow_problems(rows: list[ARow], parse_bad: list[str]) -> list[str]:
    bad = list(parse_bad)
    for n, r in enumerate(rows, 1):
        if r.aid != f"A-{n}":
            bad.append(f"{r.aid}: out of order (expected A-{n})")
        if r.op not in OPS:
            bad.append(f"{r.aid}: unknown op {r.op!r}")
            continue
        base = at_base(TARGETS[r.file])
        if base is None:
            bad.append(f"{r.aid}: `{r.file}` unreadable at {BASE}")
            continue
        bl = lines(base)
        at = bl[r.line - 1] if 1 <= r.line <= len(bl) else ""
        if (at.count(r.old) != 1) if r.op == "replace fragment" else (at != r.old):
            bad.append(f"{r.aid}: the Old is not `{r.file}`:{r.line} (or once in it) at the base")
            continue
        if locate(bl, bl, r) != r.line - 1:
            bad.append(f"{r.aid}: the Old is not unique in its scope")
        if r.old.startswith("|") and r.op == "replace":
            w = table_widths(bl, r.line - 1)
            old_c, new_c = split_row(r.old), split_row(r.new)
            for c, (o, nw, ww) in enumerate(zip(old_c, new_c, w)):
                if len(nw) > ww or (len(o) == ww and len(nw) != ww):
                    bad.append(f"{r.aid}: cell {c} changes its column's width (prettier re-pads)")
    return bad


HELD_WANT = {("CMP-215", "Props"), ("CMP-215", "Tokens")}


def held_problems(rows: list[ARow]) -> list[str]:
    held = {(r.entry, r.fld) for r in rows if r.held}
    bad = [f"HELD has {e} {f}, which is not CMP-215's" for e, f in sorted(held - HELD_WANT)]
    bad += [f"HELD lacks {e} {f}" for e, f in sorted(HELD_WANT - held)]
    for r in rows:
        if r.held and r.held != "E15-D10 (#364)":
            bad.append(f"{r.aid}: held for {r.held!r}, not E15-D10 (#364)")
        if r.entry == "CMP-215" and r.fld == "A11y" and r.held:
            bad.append("CMP-215's environment rule is held; it is applied (BQ-12)")
    if not any(r.entry == "CMP-215" and r.fld == "A11y" for r in rows):
        bad.append("CMP-215's environment rule has no row")
    return bad


# ---------------------------------------------------------------------------- rows of record


def unquote_cell(cell: str) -> str:
    c = cell.strip()
    if len(c) >= 2 and c[0] == '"' and c[-1] == '"':
        c = c[1:-1]
    return c.replace('\\"', '"')


def d15_rows() -> dict[str, tuple[str, str]]:
    """E15-D15 A-3 ... A-5 (`D15`:581–583): (old fragment, new fragment)."""
    out: dict[str, tuple[str, str]] = {}
    for ln in lines(at_base(KEYS["D15"]) or "")[580:583]:
        c = split_row(ln)
        if len(c) >= 4 and c[0] in ("A-3", "A-4", "A-5"):
            out[c[0]] = (unquote_cell(c[2]), unquote_cell(c[3]))
    return out


def d07_text(cell: str) -> str:
    """E15-D07's Table A text as `15` takes it: anchors dropped, `\\|` read as `|`, its "spec"
    named E15-D07 (applied as amended, §2)."""
    t = ANCHOR.sub("", cell).replace("\\|", "|")
    return re.sub(r"\bspec ([§D])", r"E15-D07 \1", t)


def d07_rows() -> dict[str, tuple[str, str]]:
    """E15-D07 Table A (`D07h`:29–38) and Table S (`D07h`:44–45): (old, new)."""
    hand = lines(at_base(KEYS["D07h"]) or "")
    stories = {split_row(hand[k])[0]: split_row(hand[k])[1] for k in (43, 44)}
    out: dict[str, tuple[str, str]] = {}
    for ln in hand[28:38]:
        c = split_row(ln)
        if len(c) < 5 or not c[0].startswith("A-15."):
            continue
        new = c[4]
        if new == "Table S":
            new = stories["CMP-213 FuzzyList" if c[1] == "CMP-213" else "CMP-216 PanelMenu"]
        new = new.removeprefix("add `static`: ")
        out[c[0]] = (d07_text(c[3]), d07_text(new))
    return out


D07_OLD_CHECKED = ("A-15.1", "A-15.2", "A-15.3", "A-15.4", "A-15.5", "A-15.6", "A-15.7")
LETTER = "a group colour is never used without the group letter; the hue only repeats the letter"
LETTER_SITES = (("CMP-218", "A11y"), ("CMP-218", "Tokens"), ("CMP-082", "A11y"), ("§2.1b", ""))


def parent_problems(rows: list[ARow]) -> list[str]:
    bad: list[str] = []
    d15 = d15_rows()
    if len(d15) != 3:
        bad.append("E15-D15 A-3 ... A-5 are not at `D15`:581–583")
    for aid, (old, new) in sorted(d15.items()):
        hits = [r for r in rows if f"E15-D15 {aid}" in r.src]
        if len(hits) != 1:
            bad.append(f"E15-D15 {aid}: {len(hits)} §C rows name it (want 1)")
            continue
        if old not in hits[0].old or new not in hits[0].new:
            bad.append(f"E15-D15 {aid}: not byte for byte in {hits[0].aid}")
    d07 = d07_rows()
    if len(d07) != 10:
        bad.append("E15-D07 Table A is not at `D07h`:29–38")
    for aid, (old, new) in sorted(d07.items()):
        hits = [r for r in rows if f"E15-D07 {aid} " in r.src + " "]
        if len(hits) != 1:
            bad.append(f"E15-D07 {aid}: {len(hits)} §C rows name it (want 1)")
            continue
        if new not in hits[0].new:
            bad.append(f"E15-D07 {aid}: its New is not in {hits[0].aid}")
        if aid in D07_OLD_CHECKED and old not in hits[0].old:
            bad.append(f"E15-D07 {aid}: its Old is not in {hits[0].aid}")
    for entry, fld in LETTER_SITES:
        hits = [r for r in rows if r.entry == entry and (not fld or r.fld == fld)]
        if not hits or not any(LETTER in r.new.lower() for r in hits):
            bad.append(f"the letter rule is missing from {entry} {fld}".rstrip())
    return bad


# ---------------------------------------------------------------------------- the ledger (§2)

DISPOSITIONS = ("applied as amended", "applied", "held", "routed", "closed")


def disposition(cell: str) -> str:
    for d in DISPOSITIONS:
        if cell.startswith(d):
            return d
    return ""


def ledger(spec: str) -> list[list[str]]:
    return [r for r in table_rows(section(spec, "2.")) if re.fullmatch(r"L-\d+", r[0])]


def ledger_problems(spec: str, rows: list[ARow]) -> list[str]:
    bad: list[str] = []
    ids = {r.aid for r in rows}
    led = ledger(spec)
    for n, r in enumerate(led, 1):
        if r[0] != f"L-{n}" or len(r) != 5:
            bad.append(f"{r[0]}: out of order or not five cells")
            continue
        d = disposition(r[3])
        if not d:
            bad.append(f"{r[0]}: disposition {r[3][:30]!r} is not in the vocabulary")
        here = re.findall(r"A-\d+", r[4])
        for a in here:
            if a not in ids:
                bad.append(f"{r[0]}: {a} is not a §C row")
        if d.startswith("applied") and not here:
            bad.append(f"{r[0]}: applied, but names no §C row")
    return bad


def ledger_counts(spec: str) -> dict[str, str]:
    led = ledger(spec)
    out = {"COUNT:ledger": str(len(led))}
    for d in DISPOSITIONS:
        key = "amended" if d == "applied as amended" else d
        out[f"COUNT:ledger.{key}"] = str(sum(1 for r in led if disposition(r[3]) == d))
    return out


# ---------------------------------------------------------------------------- tokens (§5)

ADDED = (
    "space.dockgrid.gutter",
    "space.panelheader.height.compact",
    "space.panelheader.height.comfortable",
    "space.dock.tray.height.compact",
    "space.dock.tray.height.comfortable",
    "size.dock.splitter.hit",
    "border.panel.focus",
    "color.sync.a",
    "color.sync.b",
    "color.sync.c",
)
# R19: the tab strip's row is a derivation rule stated once in `16` §3 (A-76), never a token; the
# frame's token is a child of a new `border.panel` group (a shipped value never becomes a group).
DERIVATION = "control height + 2 × `space.1`"
REJECTED = ("border." + "focus.panel", "space." + "workspacetabs")
ALIAS = {
    "space.dockgrid.gutter": "space.1",
    "space.panelheader.height.compact": "size.control.compact",
    "space.panelheader.height.comfortable": "size.control.comfortable",
    "space.dock.tray.height.compact": "size.control.compact",
    "space.dock.tray.height.comfortable": "size.control.comfortable",
    "size.dock.splitter.hit": "size.target.min",
    "border.panel.focus": "border.focus",
}
CONFIRMED = (
    "color.border.default",
    "elevation.card",
    "radius.card",
    "color.focus.ring",
    "color.env.demo",
    "color.env.live",
)
RETIRED = (
    "color.border.panel",
    "color.accent.subtle",
    "color.surface.base",
    "motion.fast",
    "motion.toast",
)
TOKEN_RE = re.compile(
    r"`((?:color|space|size|border|radius|elevation|motion|type|font|opacity)\.[a-z0-9.*-]+)`"
)


def post_2t() -> bool:
    """Post-2T mode, by content: the ten tokens already ship at the base (PR 2T, #5075)."""
    return set(ADDED) <= token_names()


def post_2t_problems() -> list[str]:
    bad: list[str] = []
    dark = theme_set("dark")
    for n, a in ALIAS.items():
        got = dark.get(n, {}).get("$value")
        if got is None:
            bad.append(f"{n} is missing in dark (post-2T)")
        elif got != "{" + a + "}":
            bad.append(f"{n} is {got}, not {{{a}}} (post-2T)")
    for s, refs in SYNC_REF.items():
        for th in THEMES:  # hc has no lines of its own: the merged set inherits dark's (T-7)
            want = "{" + refs["light" if th == "light" else "dark"] + "}"
            got = theme_set(th).get(f"color.sync.{s}", {}).get("$value")
            if got is None:
                bad.append(f"color.sync.{s} is missing in {th} (post-2T)")
            elif got != want:
                bad.append(f"color.sync.{s} ({th}) is {got}, not {want} (post-2T)")
    return bad


def token_problems(spec: str, rows: list[ARow], others: tuple[str, ...] = ()) -> list[str]:
    bad: list[str] = []
    for k, text in enumerate((spec, *others)):
        for name in REJECTED:
            if name in text:
                bad.append(f"document {k}: the rejected name {name} (R19)")
    names, prims = token_names(), primitive_names()
    post = post_2t()
    if post:
        bad.extend(post_2t_problems())
    for n in ADDED:
        if n in names and not post:
            bad.append(f"{n} already exists at the base (not an addition)")
        if n.startswith("e15.") or ".e15." in n:
            bad.append(f"{n}: an e15.* name")
    for n, a in ALIAS.items():
        if a not in prims:
            bad.append(f"{n}'s alias {a} is not a primitive at the base")
    for s, refs in SYNC_REF.items():
        for th in () if post else THEMES:
            ref = refs["light" if th == "light" else "dark"]
            if ref not in prims:
                bad.append(f"color.sync.{s}: {ref} is not a primitive")
            got = theme_set(th).get(SYNC_STANDIN[s], {}).get("$value")
            if got != "{" + ref + "}":
                bad.append(f"color.sync.{s} ({th}): {ref} is not E15-D06's hue ({got})")
    for n in CONFIRMED:
        if n not in names:
            bad.append(f"confirmed {n} is not shipped")
    for n in RETIRED:
        if n in names:
            bad.append(f"retired {n} is shipped (a retirement is a name never shipped)")
    t5 = section(spec, "5.")
    for n in ADDED + CONFIRMED + RETIRED:
        if f"`{n}`" not in t5 and f"`{n.rsplit('.', 1)[0]}." not in t5:
            bad.append(f"{n} is not in §5")
    for r in rows:
        for ln in lines(r.new):
            if "**Tokens**" not in ln and r.fld != "the new section":
                continue
            for tok in TOKEN_RE.findall(ln):
                if tok in names or tok in ADDED:
                    continue
                if tok.endswith(".*") and any(x.startswith(tok[:-1]) for x in (*names, *ADDED)):
                    continue
                if tok in RETIRED and ("(Replaces" in ln or "etired" in ln):
                    continue
                if f"`{tok}` does not exist" in ln:
                    continue
                if tok.startswith("palette.") or tok in ("type.ui.label",):
                    continue
                bad.append(f"{r.aid}: {tok} is neither shipped, added nor retired")
    return bad


# ---------------------------------------------------------------------------- the AC1 audit (§9)

AC1_VALUE = re.compile(
    r"(?<![\w.#-])(\d+(?:\.\d+)?)(<!--=[^>]*-->)?\s?(px|ms)\b(<!--=[^>]*-->)?"
    r"|(?<![\w&])(#[0-9A-Fa-f]{6})\b"
)
AC1_TOKEN = re.compile(r"`([a-z][a-z0-9-]*(?:\.[a-z0-9-]+)+)`")
AC1_COLUMN = re.compile(r"token|treatment|redline", re.IGNORECASE)
AC1_HEADING = re.compile(r"redline|token", re.IGNORECASE)


@dataclass(frozen=True)
class Ac1Hit:
    doc: str
    line: int
    value: str
    kind: str  # "anchored", "token", "residual"


def ac1_scan(doc: str, text: str, names: frozenset[str]) -> list[Ac1Hit]:
    """Every hex in the text, and every px / ms value in a token, treatment or redline column or
    under a token or redline heading, classified."""
    out: list[Ac1Hit] = []
    heading, cols, header_seen = "", [], False
    for i, ln in enumerate(lines(text), 1):
        if ln.startswith("#"):
            heading, header_seen = ln, False
            continue
        in_head = bool(AC1_HEADING.search(heading))
        cells: list[str] = []
        if ln.startswith("|"):
            if RULE_ROW.match(ln):
                continue
            row = split_row(ln)
            if not header_seen:
                cols = [j for j, h in enumerate(row) if AC1_COLUMN.search(h)]
                header_seen = True
                continue
            cells = row if in_head else [row[j] for j in cols if j < len(row)]
        else:
            header_seen = False
            cells = [ln] if in_head else []
        hexes_only = [] if cells else [ln]
        for c, hex_only in [(x, False) for x in cells] + [(x, True) for x in hexes_only]:
            for clause in re.split(r";|·|(?<=[.!?])\s", c):
                for m in AC1_VALUE.finditer(clause):
                    if hex_only and not m.group(5):
                        continue
                    if not m.group(5) and clause[: m.start()].count("`") % 2:
                        continue
                    val = m.group(5) or f"{m.group(1)} {m.group(3)}"
                    if m.group(2) or m.group(4):
                        kind = "anchored"
                    elif any(t in names for t in AC1_TOKEN.findall(clause)):
                        kind = "token"
                    else:
                        kind = "residual"
                    out.append(Ac1Hit(doc, i, val, kind))
    return out


@lru_cache(maxsize=1)
def ac1_hits_cached() -> tuple[Ac1Hit, ...]:
    names = token_names()
    out: list[Ac1Hit] = []
    for d in AC1_DOCS:
        out += ac1_scan(d, at_base(KEYS[d]) or "", names)
    return tuple(out)


def ac1_hits() -> list[Ac1Hit]:
    return list(ac1_hits_cached())


EXC_CITE = re.compile(r"`(D\d\dh?)`:(\d+)")


def ac1_exceptions(spec: str) -> list[list[str]]:
    return [r for r in table_rows(section(spec, "9.")) if re.fullmatch(r"X-\d+", r[0])]


def ac1_problems(spec: str, hits: list[Ac1Hit]) -> list[str]:
    bad: list[str] = []
    residual = {(h.doc, h.line) for h in hits if h.kind == "residual"}
    covered: set[tuple[str, int]] = set()
    for n, r in enumerate(ac1_exceptions(spec), 1):
        if r[0] != f"X-{n}" or len(r) != 4 or not r[3].strip():
            bad.append(f"{r[0]}: out of order, not four cells, or no reason")
            continue
        sites = {(d, int(ln)) for d, ln in EXC_CITE.findall(r[1])}
        if not sites:
            bad.append(f"{r[0]}: names no `Dnn`:line site")
        for s in sites:
            if s not in residual:
                bad.append(f"{r[0]}: `{s[0]}`:{s[1]} holds no residual value (a stale exception)")
        covered |= sites
    for d, ln in sorted(residual - covered):
        bad.append(f"`{d}`:{ln}: a raw value with no token and no exception row")
    return bad


def ac1_counts(hits: list[Ac1Hit], spec: str) -> dict[str, str]:
    return {
        "COUNT:ac1.docs": str(len(AC1_DOCS)),
        "COUNT:ac1.values": str(len(hits)),
        "COUNT:ac1.anchored": str(sum(h.kind == "anchored" for h in hits)),
        "COUNT:ac1.token": str(sum(h.kind == "token" for h in hits)),
        "COUNT:ac1.residual": str(sum(h.kind == "residual" for h in hits)),
        "COUNT:ac1.exceptions": str(len(ac1_exceptions(spec))),
    }


# ---------------------------------------------------------------------------- the texts and values


@dataclass(frozen=True)
class Texts:
    spec: str
    hand: str
    rules: str
    pins: str
    changed: tuple[str, ...] | None  # paths differing from the merge-base; None = git failed
    now: tuple[tuple[str, str], ...]  # ("15" | "16", working-tree text)
    mbase: tuple[tuple[str, str], ...]  # ("15" | "16", merge-base text)
    sources: tuple[tuple[str, str], ...] = ()


def docs(t: Texts) -> list[tuple[str, str]]:
    return [("spec", t.spec), ("hand", t.hand), ("rules", t.rules)]


def count_values(t: Texts) -> dict[str, str]:
    rows, _ = a_rows(t.spec)
    v = {
        "COUNT:arows": str(len(rows)),
        "COUNT:arows.15": str(sum(r.file == "15" for r in rows)),
        "COUNT:arows.16": str(sum(r.file == "16" for r in rows)),
        "COUNT:arows.held": str(sum(bool(r.held) for r in rows)),
        "COUNT:crows": str(len(crows(t.spec))),
        "COUNT:mutations": str(len(MUTATIONS)),
        "COUNT:probes": str(len(PROBES)),
        "COUNT:gates": str(len(GATES)),
    }
    v.update(ledger_counts(t.spec))
    walk = [r for r in table_rows(section(t.rules, "9.")) if re.fullmatch(r"N\d+", r[0])]
    v["COUNT:walk.needs"] = str(len(walk))
    v["COUNT:walk.nf"] = str(sum(r[2] == "not found" for r in walk))
    v["COUNT:walk.found"] = str(len(walk) - int(v["COUNT:walk.nf"]))
    v.update(ac1_counts(ac1_hits(), t.spec))
    return v


@lru_cache(maxsize=1)
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

    def sub(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in values:
            missing.append(key)
            return m.group(0)
        return f"{values[key]}<!--={key}-->"

    out = []
    for ln in lines(text):
        spans = code_spans(ln)
        pieces, last = [], 0
        for m in PLACEHOLDER.finditer(ln):
            if any(a <= m.start() < b for a, b in spans):
                continue
            pieces.append(ln[last : m.start()])
            pieces.append(sub(m))
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


RATIO = re.compile(r"(?<![\w.])\d+\.\d+:1\b")
DE_TYPED = re.compile(r"ΔE(?:76)?\s*(?:≥\s*)?\d+\.\d")
BAR_FIGURES = ("3:1", "4.5:1", "7:1")


def g_figure(t: Texts) -> list[Finding]:
    bad: list[str] = []
    for name, text in docs(t):
        plain = ANCHOR.sub("", ANCHORED.sub("", unfence(text)))
        for m in RATIO.finditer(plain):
            if m.group(0) not in BAR_FIGURES:
                bad.append(f"{name}: the ratio {m.group(0)} is typed by hand (anchor it)")
        for m in DE_TYPED.finditer(plain):
            bad.append(f"{name}: the colour distance {m.group(0)!r} is typed by hand")
    return fails("G-FIGURE", bad)


CITE = re.compile(
    r"`("
    + "|".join(sorted((re.escape(k) for k in KEYS), key=len, reverse=True))
    + r")`:(\d+)(?:[–-](\d+))?((?:, :\d+(?:[–-]\d+)?)*)"
)
CONT = re.compile(r":(\d+)(?:[–-](\d+))?")
# Load-bearing words: each stands on the line its cite names at the base.
CITED: dict[tuple[str, int], str | tuple[str, ...]] = {
    ("15", 31): "241–242 and 244–247 unassigned",
    ("15", 459): "`inset` drawing the ring inside the element",
    ("15", 892): "`Ctrl+Shift+Arrow` moves/swaps dock position",
    ("15", 893): "`color.border.panel`",
    ("15", 2704): "`color.accent.subtle`, `motion.fast`",
    ("15", 2713): "`color.surface.base`",
    ("15", 3044): "**242",
    ("15", 3058): "Decision — final count was locked at 238",
    ("16", 244): "binary split-tree",
    ("16", 248): "elevation step-up + accent border",
    ("D02", 203): "replaces `16` §8 rule 1",
    ("D03", 166): "The focus affordance is drawn inside a constant frame.",
    ("D03", 715): "`lo` = against the darkest",
    ("D04", 109): "The MoveModeBar",
    ("D04", 228): "Minimised panels",
    ("D04", 105): ("Two-tone carriers", "a 2 px halo at comfortable density is left to E15-D13"),
    ("D06", 119): "the final hues are its call",
    ("D15", 517): "F-05",
    ("D15", 521): "F-09",
    ("D07h", 3): "Table A is copy-ready for E15-D13",
    ("D04h", 110): "two lines 56 / 72",
    ("D04h", 111): "`size.row.compact` / `size.row.comfortable`",
    ("D06", 507): "| A-14 | `15` CMP-043 Dialog (Modal)",
    ("D06", 559): "A-14 to CMP-043's owner",
    ("15", 505): "reflow (at 200 % zoom the dialog fills the viewport)",
    ("16", 126): "Density changes spacing-token resolution only",
    ("16", 129): "reflow toward a card/stacked layout",
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
            base = at_base(KEYS[key])
            if base is None:
                bad.append(f"{name}: `{key}` is unreadable at {BASE}")
                continue
            bl = lines(base)
            seen.update((key, n) for n in range(a, b + 1))
            for n in sorted({a, b}):
                if not 1 <= n <= len(bl) or not bl[n - 1].strip() or b < a:
                    bad.append(f"{name}: `{key}`:{n} is past the end or blank at {BASE}")
    for (key, n), words in CITED.items():
        bl = lines(at_base(KEYS[key]) or "")
        if (key, n) not in seen:
            bad.append(f"the load-bearing cite `{key}`:{n} is not in the documents")
        elif not 1 <= n <= len(bl) or any(
            w not in bl[n - 1] for w in ((words,) if isinstance(words, str) else words)
        ):
            bad.append(f"`{key}`:{n} no longer holds {words!r}")
    return fails("G-CITE", bad)


def g_untouched(t: Texts) -> list[Finding]:
    if t.changed is None:
        return fails("G-UNTOUCHED", ["git cannot name the changed paths (fail closed)"])
    own = [p for p in t.changed if p in OWN_PATHS]
    other = [p for p in t.changed if p not in OWN_PATHS]
    if own:  # PR 1: only the pack's five files
        return fails(
            "G-UNTOUCHED", [f"PR 1 changes {p}, not one of the pack's five" for p in other]
        )
    ok = set(TARGETS.values())
    if post_2t():  # the token files carry the pack's tokens at the base: they may change too
        ok |= {p for p in other if p.startswith(TOKENS_DIR + "/") or p.endswith("pairs.mjs")}
    bad = [f"PR 2 changes {p}, not `15` or `16`" for p in other if p not in ok]
    rows, _ = a_rows(t.spec)
    now, mb = dict(t.now), dict(t.mbase)
    for key, rel in TARGETS.items():
        if rel not in t.changed:
            continue
        want = apply_rows(mb.get(key, ""), at_base(rel) or "", rows, key)
        if want is None:
            bad.append(f"PR 2: a §C row for `{key}` cannot be re-pointed at the merge-base")
        elif now.get(key) != want:
            bad.append(f"PR 2: `{key}` is not the merge-base with §C applied, byte for byte")
    return fails("G-UNTOUCHED", bad)


def g_arow(t: Texts) -> list[Finding]:
    rows, bad = a_rows(t.spec)
    return fails("G-AROW", arow_problems(rows, bad))


def g_held(t: Texts) -> list[Finding]:
    return fails("G-HELD", held_problems(a_rows(t.spec)[0]))


def g_parent(t: Texts) -> list[Finding]:
    return fails("G-PARENT", parent_problems(a_rows(t.spec)[0]))


def g_ledger(t: Texts) -> list[Finding]:
    return fails("G-LEDGER", ledger_problems(t.spec, a_rows(t.spec)[0]))


def g_token(t: Texts) -> list[Finding]:
    return fails("G-TOKEN", token_problems(t.spec, a_rows(t.spec)[0], (t.hand, t.rules)))


REPRO = (  # (my key, parent, parent's anchor): equal to the hundredth
    ("CR:focus.lo.dark", "D03", "CR:focus-fill:dark:lo"),
    ("CR:focus.hi.dark", "D03", "CR:focus-fill:dark:hi"),
    ("CR:focus.lo.light", "D03", "CR:focus-fill:light:lo"),
    ("CR:focus.hi.light", "D03", "CR:focus-fill:light:hi"),
    ("CR:focus.lo.hc", "D03", "CR:focus-fill:hc:lo"),
    ("CR:focus.hi.hc", "D03", "CR:focus-fill:hc:hi"),
)
D06_EDGES = {  # `D06`:440–448: the measured edges E15-D13 re-runs (446–448 reported only)
    440: ("a", "header"),
    441: ("b", "header"),
    442: ("c", "header"),
    443: ("a", "canvas"),
    444: ("b", "canvas"),
    445: ("c", "canvas"),
    446: ("a", "selected"),
    447: ("b", "selected"),
    448: ("c", "selected"),
}
D04_RING_ALONE = {"dark": "2.16:1 there in dark", "light": "2.66:1 in light"}  # `D04`:105


def contrast_problems() -> list[str]:
    bad = [f"{n}: {f2(r)} below {b}" for n, r, b in gated_pairs() if r < b]
    v = dict(fixed_values())
    for key, doc, pkey in REPRO:
        if v[key] != parent_anchor(doc, pkey):
            bad.append(f"{key} {v[key]} does not reproduce `{doc}`'s {pkey}")
    d06 = lines(at_base(KEYS["D06"]) or "")
    for n, (s, where) in D06_EDGES.items():
        got = re.findall(r"\| (\d+\.\d\d) \(grey", d06[n - 1]) if n <= len(d06) else []
        want = [v[f"CR:sync.{s}.{where}.{k}"] for k in ("dark", "light", "hc")]
        if got != want:
            bad.append(f"sync.{s} on {where} does not reproduce `D06`:{n} ({got} vs {want})")
    d04 = lines(at_base(KEYS["D04"]) or "")[104] if at_base(KEYS["D04"]) else ""
    for th, words in D04_RING_ALONE.items():
        if not words.startswith(v["CR:drop.ringalone." + th] + ":1") or words not in d04:
            bad.append(f"the ring alone ({th}) does not reproduce `D04`:105")
    return bad


def g_contrast(t: Texts) -> list[Finding]:
    return fails("G-CONTRAST", contrast_problems())


def g_density(t: Texts) -> list[Finding]:
    bad = density_problems()
    rows, _ = a_rows(t.spec)
    s3 = [r for r in rows if r.file == "16" and r.entry == "§3"]
    want = density_table()
    got = (
        [
            split_row(ln)
            for ln in lines(s3[0].new)
            if ln.startswith("| ") and not RULE_ROW.match(ln)
        ][1:]
        if s3
        else []
    )
    if got != want:
        bad.append("the `16` §3 dock-surface table in §C is not the computed one")
    return fails("G-DENSITY", bad)


def g_ac1(t: Texts) -> list[Finding]:
    return fails("G-AC1", ac1_problems(t.spec, ac1_hits()))


# ---------------------------------------------------------------------------- the rulings

STAMP_A39 = "RULED (orchestrator, 2026-10-30, #2701 ledger addendum A row A39)"
STAMP_A40 = "RULED (orchestrator, 2026-10-30, #2701 ledger addendum A row A40)"
STAMP_R367 = f"RULED (orchestrator, 2026-10-30, #367 ruling of record — {RULING_ID})"
STAMP_R19 = f"RULED (orchestrator, 2026-10-30, #367 lane ruling R19 — {R19_ID})"
# Every stamp site: a line of the pack opening with these words carries that stamp.
STAMP_SITES: dict[str, str] = {
    "- **BQ-04 (A39)": STAMP_A39,
    "- **BQ-09 (A40)": STAMP_A40,
    "- **BQ-06 (reading)": STAMP_R367,
    "- **BQ-19 (reading)": STAMP_R367,
    "- **R19 (lane ruling)": STAMP_R19,
}
STAMP_ANY = re.compile(r"RULED \(orchestrator[^)]*\)")
# The ruled words, by source (R367 = the ruling of record 6519042539; A3940 = #2701 ledger
# addendum A rows A39 / A40, 6519011494): each stands in the pack, and in the saved copy given
# with --source.
RULING_PINS: dict[str, tuple[str, ...]] = {
    "R367": (
        "PR 3 closes the ticket; the unmerged surfaces' AC1 check moves to their own tickets",
        "semantic Tier-2 aliases only, no new primitive",
        "the density pairs through `themes.json`'s alias indirection",
        "a failing value is revised, never the budget",
        "MinimisedPanelTray with no restore chord (PROPOSED)",
        "CMP-215's rows HELD for E15-D10 (#364) except the environment rule",
        "a composed organism, not a Tabs variant",
        "the `.c` / `color.chart.line` shared primitive a C row (accepted — the edge sits on chrome)",
        "CMP-039 `inset` vs the panel frame — different responsibility, a note in both",
    ),
    "A3940": (
        "241–242 and 244–247 stay unused",
        "no elevation step and never a change of the content box",
        "(not a binary split-tree)",
        "no second tablist implementation",
    ),
}


# The ruled sweep (BQ-12 / BQ-13): CMP-039 `inset` vs the panel frame, "a note in both".
SWEEP_NOTE = "a different responsibility"
SWEEP_SITES = (("CMP-039", ""), ("CMP-080", "A11y"))


# BQ-19 as the text lens ruled it (#5055, round 1): the dry run of record is the outside reader's,
# cited where the pack claims AC3 and the DoD line; the usage rules answer the run's two new needs
# (N9, the sync badge's renderer; N10, registering a kind) by name.
DRYRUN_SITES = (
    "| AC3 ",
    "- [x] The usage-rules document written",
    "**Deviations, recorded.**",
)
BADGE_RULE: tuple[str, tuple[str, ...]] = (
    "| R-8 ",
    ("`syncBadge`", "CMP-011 `interactive`", "CMP-218"),
)
KIND_LIST: tuple[str, tuple[str, ...]] = (
    "**Registering a new panel kind**",
    ("`PaneKind`", "SCR-024", "`type`", "`15`"),
)


def dryrun_problems(t: Texts) -> list[str]:
    bad: list[str] = []
    if DRYRUN_ID not in section(t.rules, "9."):
        bad.append(f"the usage rules §9 does not name the outside run ({DRYRUN_ID})")
    for lead in DRYRUN_SITES:
        hit = [ln for ln in lines(t.spec) if ln.startswith(lead)]
        if len(hit) != 1 or DRYRUN_ID not in hit[0]:
            bad.append(f"{lead.strip('|-[x]* ')!r}: does not cite the outside run ({DRYRUN_ID})")
    lead, words = BADGE_RULE
    row = [ln for ln in lines(section(t.rules, "2.")) if ln.startswith(lead)]
    if len(row) != 1 or any(w not in row[0] for w in words):
        bad.append("the usage rules §2 names no renderer, slot and menu for the sync badge (R-8)")
    lead, words = KIND_LIST
    body = section(t.rules, "6.")
    at = body.find(lead)
    if at < 0 or any(w not in body[at:] for w in words):
        bad.append("the usage rules §6 has no list for registering a new panel kind")
    return bad


def ruled_problems(t: Texts) -> list[str]:
    bad: list[str] = dryrun_problems(t)
    seen: dict[str, int] = {}
    for ln in lines(t.spec):
        for lead, stamp in STAMP_SITES.items():
            if ln.startswith(lead):
                seen[lead] = seen.get(lead, 0) + 1
                if stamp not in ln:
                    bad.append(f"{lead.strip('- *')}: the stamp is not {stamp!r}")
        for m in STAMP_ANY.finditer(ln):
            if m.group(0) not in (STAMP_A39, STAMP_A40, STAMP_R367, STAMP_R19):
                bad.append(f"a stamp in no ruled form: {m.group(0)!r}")
    for lead in STAMP_SITES:
        if seen.get(lead) != 1:
            bad.append(f"{lead.strip('- *')}: {seen.get(lead, 0)} sites (want 1)")
    rows = a_rows(t.spec)[0]
    for entry, fld in SWEEP_SITES:
        hits = [r for r in rows if r.entry == entry and (not fld or r.fld == fld)]
        if not any(SWEEP_NOTE in r.new for r in hits):
            bad.append(f"the sweep's note ({SWEEP_NOTE!r}) is not in {entry} {fld}".rstrip())
    src = dict(t.sources)
    flat = norm(t.spec)
    for name, pins in RULING_PINS.items():
        for pin in pins:
            if norm(pin) not in flat:
                bad.append(f"{name}: the ruled words {pin!r} are not in the pack")
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
    return units(t.spec, "spec") + units(t.hand, "hand") + units(t.rules, "rules")


def write_pins(us: list[Unit]) -> str:
    head = (
        "# E15-D13 pins (every unit of the pack, the hand-off and the usage rules): region, "
        f"location, the exact normalised text; {len(us)} units.\n# Written by `--repin-ruled` "
        "only; `--check` reads it (never hand-edit; see the tool's G-RULED-PIN).\n"
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
)
BANNED = re.compile(
    "|".join(re.escape(w[::-1]) for w in _HIDDEN) + r"|\b" + "sod"[::-1] + r"\b", re.IGNORECASE
)
LOCAL_PATH = re.compile("/" + "(?:home|Users|mnt|tmp)" + r"/[^\s`)]+")
HOSTNAME = re.compile(r"\b[a-z0-9-]+\.(?:com|net|org)\b|\bpenpot\.[a-z0-9-]+\.", re.IGNORECASE)
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


# ---------------------------------------------------------------------------- C-rows, entries, list


def crows(spec: str) -> list[list[str]]:
    return [r for r in table_rows(section(spec, "10.")) if re.fullmatch(r"C-\d+", r[0])]


def g_crows(t: Texts) -> list[Finding]:
    bad: list[str] = []
    rows = crows(t.spec)
    if len(rows) != 16:
        bad.append(f"{len(rows)} C-rows (BQ-20's twelve, the ruling's two, C-15 and C-16)")
    for n, r in enumerate(rows, 1):
        if r[0] != f"C-{n}" or len(r) != 4 or not r[2].strip() or not r[3].strip():
            bad.append(f"{r[0]}: out of order, or no reading or owner")
    return fails("G-CROWS", bad)


NEW_IDS = {
    "CMP-249": "MoveModeBar",
    "CMP-250": "MinimisedPanelTray",
    "CMP-251": "DockTabGroup",
    "CMP-252": "WorkspaceTabStrip",
}
ENTRY_FIELDS = (
    "**Tier**",
    "**Purpose**",
    "**Props**",
    "**Variants**",
    "**States**",
    "**A11y**",
    "**Tokens**",
    "**Storybook**",
    "**Tests**",
    "**Forbidden**",
    "**Performance**",
    "**Motion spec**",
    "**Why a new entry, not a variant**",
)


def g_entry(t: Texts) -> list[Finding]:
    bad: list[str] = []
    rows = [r for r in a_rows(t.spec)[0] if r.entry == "CMP-249..252"]
    if len(rows) != 1:
        return fails("G-ENTRY", ["no single §C row holds the four new entries"])
    blocks = re.split(r"^### ", rows[0].new, flags=re.MULTILINE)[1:]
    got = [b.split(" ", 2)[:2] for b in blocks]
    if [(a, b) for a, b in got] != list(NEW_IDS.items()):
        bad.append(f"the new entries are {got}, not A39's four")
    for b in blocks:
        cid = b.split(" ", 1)[0]
        for f in ENTRY_FIELDS:
            if f not in b:
                bad.append(f"{cid}: no {f.strip('*')} field")
        if f"`Organisms/Dock/{NEW_IDS.get(cid, '?')}`" not in b:
            bad.append(f"{cid}: its Storybook tree is not `Organisms/Dock/<Name>`")
    return fails("G-ENTRY", bad)


def mutation_paragraph() -> str:
    parts = [f"**{g}:** M-{n} {d}" for n, (g, d, _) in enumerate(MUTATIONS, 1)]
    return "; ".join(parts) + "."


def g_mutlist(t: Texts) -> list[Finding]:
    ok = mutation_paragraph() in t.spec
    return fails("G-MUTLIST", [] if ok else ["§12 is not the tool's mutation list (run --fill)"])


# ---------------------------------------------------------------------------- the run

GATES: tuple[tuple[str, Callable[[Texts], list[Finding]]], ...] = (
    ("G-ANCHOR", g_anchor),
    ("G-FIGURE", g_figure),
    ("G-CITE", g_cite),
    ("G-UNTOUCHED", g_untouched),
    ("G-AROW", g_arow),
    ("G-HELD", g_held),
    ("G-PARENT", g_parent),
    ("G-LEDGER", g_ledger),
    ("G-TOKEN", g_token),
    ("G-CONTRAST", g_contrast),
    ("G-DENSITY", g_density),
    ("G-AC1", g_ac1),
    ("G-RULED", g_ruled),
    ("G-RULED-PIN", g_ruled_pin),
    ("G-PUBLIC", g_public),
    ("G-CROWS", g_crows),
    ("G-ENTRY", g_entry),
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
    mbase = (
        tuple((k, git("show", f"{mb.strip()}:{rel}") or "") for k, rel in TARGETS.items())
        if mb
        else ()
    )
    return Texts(
        spec=read(SPEC_REL),
        hand=read(HAND_REL),
        rules=read(RULES_REL),
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
        if text.count(old) < 1:
            raise SystemExit(f"self-test: {old[:50]!r} not found in {field_name}")
        return replace(t, **{field_name: text.replace(old, new, 1)})

    return f


def _patch(target: dict[str, str], key: str, val: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        _PATCHES.append((target, key, target[key]))
        target[key] = val
        return t

    return f


_PATCHES: list[tuple[dict[str, str], str, str]] = []
_TMP = "/" + "tmp" + "/scratch"
_WORD = "kael"[::-1]
_CLOSE = "Clo" + "ses #367"

MUTATIONS: tuple[tuple[str, str, Callable[[Texts], Texts]], ...] = (
    (
        "G-ANCHOR",
        "hand-edit sync A's header ratio in dark",
        _sub("spec", "<!--=CR:sync.a.header.dark-->", "1<!--=CR:sync.a.header.dark-->"),
    ),
    (
        "G-FIGURE",
        "type a ratio by hand in §6's prose",
        _sub("spec", "The measurement method.", "The measurement method (2.50:1 typed)."),
    ),
    (
        "G-CITE",
        "move the CMP-217 ledger cite past the end of E15-D05",
        _sub("spec", "CMP-217 (`D05`:545)", "CMP-217 (`D05`:99545)"),
    ),
    (
        "G-UNTOUCHED",
        "simulate an edit to `14` in PR 1",
        lambda t: replace(t, changed=(t.changed or ()) + ("docs/plan/14-screens-catalogue.md",)),
    ),
    (
        "G-AROW",
        "alter one byte of the §7A heading row's Old",
        _sub(
            "spec",
            "& editor-chrome components (CMP-200..248)",
            "& editor-chrome components (CMP-200..249)",
        ),
    ),
    (
        "G-HELD",
        "hold CMP-215's Props row for another ticket",
        _sub(
            "spec",
            "from E15-D02 §12 · HELD for E15-D10 (#364)",
            "from E15-D02 §12 · HELD for E15-D11 (#365)",
        ),
    ),
    (
        "G-PARENT",
        "change one word of E15-D15 A-5's New in §C",
        _sub(
            "spec",
            "then its side or the centre (E15-D04 §5)",
            "then its side or the middle (E15-D04 §5)",
        ),
    ),
    (
        "G-LEDGER",
        "point a ledger row at a §C row that does not exist",
        _sub("spec", "A-1, A-2, A-3, A-4, A-5, A-6", "A-1, A-2, A-3, A-4, A-5, A-999"),
    ),
    (
        "G-TOKEN",
        "bind an unshipped token in CMP-081's Tokens row",
        _sub(
            "spec",
            "`space.dockgrid.gutter` (the gutter, both densities)",
            "`color.dock.mystery` (the gutter, both densities)",
        ),
    ),
    (
        "G-CONTRAST",
        "misread E15-D04's ring-alone figure in dark",
        _patch(D04_RING_ALONE, "dark", "2.17:1 there in dark"),
    ),
    (
        "G-DENSITY",
        "type the gutter's compact value as 5 in the `16` §3 table",
        _sub(
            "spec",
            "| Gutter                                | 4 ",
            "| Gutter                                | 5 ",
        ),
    ),
    (
        "G-AC1",
        "name a stale site in exception X-3",
        _sub("spec", "| X-3 | `D04`:164", "| X-3 | `D04`:164, `D04`:105"),
    ),
    (
        "G-RULED",
        "drop the second half of the density ruling's words",
        _sub("spec", "a failing value is revised, never the budget", "a failing value is revised"),
    ),
    (
        "G-RULED-PIN",
        "reword a sentence of the usage rules' scope",
        _sub(
            "rules",
            "This document binds every later panel epic.",
            "This document guides every later panel epic.",
        ),
    ),
    (
        "G-PUBLIC",
        "paste a local path into the hand-off",
        _sub("hand", "## Table K", f"## Table K ({_TMP})"),
    ),
    ("G-CROWS", "renumber C-15", _sub("spec", "| C-15 |", "| C-16 |")),
    (
        "G-ENTRY",
        "drop CMP-251's Motion spec field name",
        _sub(
            "spec",
            "- **Motion spec**: [E15-D04.md](../design/E15/E15-D04.md) (E15-D04 §16 item 6, which",
            "- Motion: [E15-D04.md](../design/E15/E15-D04.md) (E15-D04 §16 item 6, which",
        ),
    ),
    (
        "G-MUTLIST",
        "edit §12's list",
        _sub("spec", "**G-CROWS:** M-16 renumber C-15", "**G-CROWS:** M-16 renumber C-12"),
    ),
)


def _pr2_extra(t: Texts) -> Texts:
    now = dict(t.now)
    want = apply_rows(
        dict(t.mbase).get("16", ""), at_base(BRIEF_REL) or "", a_rows(t.spec)[0], "16"
    )
    now["16"] = (want or "") + " "
    return replace(t, changed=(BRIEF_REL,), now=tuple(now.items()))


def _source_short(t: Texts) -> Texts:
    return replace(t, sources=(("A3940", " ".join(RULING_PINS["A3940"][:-1])),))


PROBES: tuple[tuple[str, str, Callable[[Texts], Texts]], ...] = (
    ("G-UNTOUCHED", "PR 2 with one byte more than §C in `16`", _pr2_extra),
    ("G-UNTOUCHED", "git cannot name the changed paths", lambda t: replace(t, changed=None)),
    (
        "G-PUBLIC",
        "a word on the list in the usage rules",
        _sub("rules", "## 1.", f"## 1. ({_WORD})"),
    ),
    ("G-PUBLIC", "a closing keyword in §13", _sub("spec", "## 13.", f"## 13. ({_CLOSE})")),
    ("G-ANCHOR", "an unfilled placeholder in §7", _sub("spec", "## 7.", "## 7. {{COUNT:arows}}")),
    ("G-RULED", "a saved copy of A39 / A40 lacking one ruled phrase", _source_short),
    (
        "G-TOKEN",
        "the frame's rejected token name (R19) back in the hand-off",
        _sub("hand", "`border.panel.focus`", "`border." + "focus.panel`"),
    ),
    (
        "G-DENSITY",
        "the tab strip's derivation rule dropped from `16` §3's table (A-76)",
        _sub(
            "spec",
            "| 32      | 40          | control height + 2 × `space.1`",
            "| 32      | 40          | (a token)",
        ),
    ),
    (
        "G-RULED",
        "drop the sweep's note from CMP-039's row (A-80)",
        _sub(
            "spec",
            "inside a constant box; `16` §8 rule 5) — a different",
            "inside a constant box; `16` §8 rule 5) — another",
        ),
    ),
    (
        "G-RULED",
        "the usage rules §9 no longer names the outside run",
        _sub("rules", f"#367 comment {DRYRUN_ID} (the orchestrator's deputy", "(the deputy"),
    ),
    (
        "G-RULED",
        "AC3 claimed with no outside run cited",
        _sub("spec", f"reader outside E15, #367 comment {DRYRUN_ID} (the usage rules §9) |", "|"),
    ),
    (
        "G-RULED",
        "the sync badge's renderer dropped from the usage rules (N9)",
        _sub("rules", "from its `syncBadge` prop as a CMP-011", "as a CMP-011"),
    ),
    (
        "G-RULED",
        "the list for registering a kind dropped from the usage rules (N10)",
        _sub("rules", "**Registering a new panel kind**", "**New kinds**"),
    ),
    (
        "G-AROW",
        "the band row's id cell wider than its column",
        _sub("spec", "| CMP-200..252 | Auth", "| CMP-200..2520 | Auth"),
    ),
)


# Post-2T mutation, kept out of PROBES: the pack's text pins that tuple's length (COUNT:probes).
POST_2T_PROBES: tuple[tuple[str, str, Callable[[Texts], Texts]], ...] = (
    (
        "G-TOKEN",
        "post-2T: the splitter's alias expected as another primitive",
        _patch(ALIAS, "size.dock.splitter.hit", "size.control.compact"),
    ),
    (
        "G-TOKEN",
        "post-2T: color.sync.a removed from the light theme alone (a FAIL line, no crash)",
        _patch(HIDE, "color.sync.a", "light"),
    ),
)


def fail_keys(fs: list[Finding]) -> list[tuple[str, str]]:
    return [(f.gate, f.msg) for f in fs if f.level == "FAIL"]


def digests() -> dict[str, str]:
    return {p: hashlib.sha256(read(p).encode("utf-8")).hexdigest() for p in OWN_PATHS}


def self_test(t: Texts) -> list[str]:
    before = digests()
    base = fail_keys(run(t))
    bad: list[str] = []
    for label, items in (("M", MUTATIONS), ("P", PROBES), ("T", POST_2T_PROBES)):
        for n, (gate, desc, fn) in enumerate(items, 1):
            try:
                mt = fn(t)
                got = fail_keys(run(mt))
            finally:
                while _PATCHES:
                    target, key, old = _PATCHES.pop()
                    target[key] = old
            new = [k for k in got if k not in base]
            if len(new) != 1 or new[0][0] != gate:
                shown = ", ".join(f"{g}: {m[:60]}" for g, m in new[:4]) or "none"
                bad.append(f"{label}-{n} ({gate}, {desc}): {len(new)} new FAIL(s) [{shown}]")
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
    if any(at_base(rel) is None for rel in KEYS.values()):
        print(f"FAIL [G-CITE] the inputs are unreadable at {BASE} (fetch first)")
        return 1
    t = load(parse_sources(args.source))
    if args.a_rows:
        print(json.dumps(export(a_rows(t.spec)[0]), ensure_ascii=False, indent=1))
        return 0
    if args.fill:
        v = compute(t)
        for rel in (SPEC_REL, HAND_REL, RULES_REL):
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
        rows = a_rows(t.spec)[0]
        out.append(
            f"gates: {len(GATES)}; FAIL {n_fail}, WARN {n_warn}; §C rows {len(rows)} "
            f"({sum(r.file == '15' for r in rows)} to `15`, {sum(r.file == '16' for r in rows)} "
            f"to `16`, {sum(bool(r.held) for r in rows)} HELD)"
        )
        if args.self_test:
            out += [f"FAIL [self-test] {x}" for x in st]
            out.append(
                f"self-test: {'ok' if not st else 'FAILED'}: {len(MUTATIONS)} mutations (one per "
                f"gate), {len(PROBES)} probes and {len(POST_2T_PROBES)} post-2T mutations, each "
                "one new FAIL from its gate; a re-run reproduces the base result; files on "
                "disk unchanged"
            )
        print("\n".join(out))
    failed = any(f.level == "FAIL" for f in found) or bool(st)
    return 1 if failed and (args.check or args.self_test) else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
