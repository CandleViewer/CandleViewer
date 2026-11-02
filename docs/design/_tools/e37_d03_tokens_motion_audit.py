"""E37-D03 tokens-and-motion audit: every number and gate the rule-graph primitives spec states, computed.

Standalone, offline, stdlib only (`python3 -I`). Themes resolve exactly as
`packages/ui/tokens/tests/verify_tokens.py` resolves them (light = `semantic-light` over dark,
high-contrast = `semantic-hc` over dark) and contrast is `contrast_ratio()` from
`docs/design/_tools/contrast_check.py` (both imported with one loader, never re-implemented).
Nothing here reads a fixture or a network.

Sections: A the tokens every binding names (a name that does not resolve in every theme is a FAIL,
except the six PROPOSED aliases, which must NOT exist yet and whose targets must resolve, and the
declined names, which must not exist); B the contrast matrix, every pair in dark / light /
high-contrast compared unrounded against its bar, decorative / reported / rejected rows reported,
never gated; C the token-proposal table (six rows: alias, target, fallback, owner, status); D the
motion-pair table (a reduce cell reading `instant` or `identical` on every row, 0 flashes, the
auto-layout row at 400 ms <= `motion.duration.slow` with stagger 0, no pulse, no line-draw); E the
two-axis tier table (three zoom bands, visibility only; no band hides the badge glyph + word or
the error outline, glyph and word the Security sentences keep); F the A-rows (today's text found
on the cited `15` / `16` line at the base, the field headings, the `14` pointer line A-47 in its
PR 2 form and `14` untouched in this PR); G the board plan (<= 10, light twins <= one third, the
Theme column against §0's convention) in the mode §0's Status cells name: every cell "to draw
(PR 2)" (pending; no export committed) or every cell the drawn form (a board id, its export, W x H
and sha256), a mix FAILs; drawn, the page id named, each export a PNG of that size and sha256, the
greyscale and deuteranopia renders of 01-08 with the sha256 §0 lists, no two boards sharing an id,
uuids only inside §0; and, in a git work tree, nothing outside the pack, its exports and the
amended `15` / `16` / `14` lines differing from the merge base with origin/main; H hygiene (no closing keyword, local path,
worker name, host or colour emoji); I the spec's own counts and the ruling stamp; J the rule ids;
K drift (every matrix row and count the tool prints is carried by the spec's text); L the
`pairs.mjs` column of §9.1 against `tools/contrast/pairs.mjs` and `exemptions.json`, read-only.

Usage: python3 -I docs/design/_tools/e37_d03_tokens_motion_audit.py [--json]
       python3 -I docs/design/_tools/e37_d03_tokens_motion_audit.py --check [SPEC]
       python3 -I docs/design/_tools/e37_d03_tokens_motion_audit.py --self-test [SPEC]
       python3 -I docs/design/_tools/e37_d03_tokens_motion_audit.py --matrix   (prints the §9.1 rows)
`--check` exits 1 on any FAIL. `--self-test` applies MUTATIONS to the spec in memory (the file is
never written): each must raise exactly one new FAIL, no two the same, and the clean spec must
pass before and after. Stdout is UTF-8.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
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
SPEC = ROOT / "docs" / "design" / "E37" / "E37-D03.md"
CATALOGUE = ROOT / "docs" / "plan" / "15-component-catalogue.md"
BRIEF = ROOT / "docs" / "plan" / "16-design-system-brief.md"
SCREENS = ROOT / "docs" / "plan" / "14-screens-catalogue.md"
PAIRS_MJS = ROOT / "tools" / "contrast" / "pairs.mjs"
EXEMPTIONS = ROOT / "tools" / "contrast" / "exemptions.json"
CONSTITUTION = ROOT / "CONSTITUTION.md"
THEMES = ("dark", "light", "high-contrast")
BAR: dict[str, float | None] = {"text": 4.5, "non-text": 3.0}
BAR.update({"decorative": None, "reported": None, "rejected-non-text": 3.0})
GATED = {"text", "non-text"}
MAX_BOARDS = 10


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


def rows_of(txt: str, sep: str = "|") -> list[list[str]]:
    return [[c.strip() for c in ln.split(sep)] for ln in txt.strip().splitlines()]


TOK: dict[str, str] = dict(rows_of("""canvas|color.surface.canvas
raised|color.surface.raised
hover|color.surface.hover
sunken|color.surface.sunken
t1|color.text.primary
t2|color.text.secondary
t3|color.text.tertiary
b.default|color.border.default
b.selected|color.border.selected
ring|color.focus.ring
a.selected|color.action.selected
grid|color.grid.line
danger|color.status.danger.default
danger.strong|color.status.danger.strong
danger.subtle|color.status.danger.subtle
warn|color.status.warning.default
warn.strong|color.status.warning.strong
warn.subtle|color.status.warning.subtle
n.trigger|color.node.trigger
n.condition|color.node.condition
n.action|color.node.action
n.logic|color.node.logic
n.comment|color.node.comment"""))


def rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def ratio(fg: str, bg: str) -> float:
    return float(contrast_check.contrast_ratio(rgb(fg), rgb(bg)))


def col(theme: str, short: str) -> str:
    return str(T[theme][TOK.get(short, short)])


def fmt3(vals: list[float], bar: float | None) -> str:
    """Two decimals; four where a value would round onto its bar (the unrounded compare)."""
    out = []
    shown = 3.0 if bar is None else bar
    for v in vals:
        if round(v, 2) == shown and abs(v - shown) > 1e-9:
            out.append(f"{v:.4f}")
        else:
            out.append(f"{v:.2f}")
    return " / ".join(out)


# ------------------------------------------------------------------ A. tokens -------------------
TOKEN_RX = re.compile(
    r"`((?:color|type|space|size|radius|border|motion|opacity|font|elevation)\.[a-z0-9.-]+)`"
)
PROPOSED: dict[str, str] = {
    "color.edge.default": "color.text.tertiary",
    "color.edge.selected": "color.border.selected",
    "color.edge.invalid": "color.status.danger.default",
    "color.port.ring": "color.text.tertiary",
    "color.port.compatible": "color.focus.ring",
    "color.port.incompatible": "color.status.danger.default",
}
DECLINED = (
    "color.node.border.default",
    "color.node.border.selected",
    "color.node.border.error",
    "color.node.border.warning",
    "color.port.in",
    "color.port.out",
    "color.accent.subtle",
    "radius.full",
    "radius.node",
)


def exists(name: str) -> bool:
    return all(name in T[t] for t in THEMES)


def tokens(spec: str, problems: list[str]) -> dict[str, Any]:
    names = sorted(set(TOKEN_RX.findall(spec)))
    missing = [n for n in names if n not in PROPOSED and n not in DECLINED and not exists(n)]
    problems += [f"token does not resolve: {n}" for n in missing]
    for alias, target in PROPOSED.items():
        if any(alias in T[t] for t in THEMES):
            problems.append(f"PROPOSED alias already exists in the tokens: {alias}")
        if not exists(target):
            problems.append(f"PROPOSED target does not resolve: {target}")
    for name in DECLINED:
        if any(name in T[t] for t in THEMES):
            problems.append(f"declined name exists in the tokens: {name}")
    return {"named": len(names), "missing": missing, "proposed": len(PROPOSED)}


# ------------------------------------------------------------------ B. the matrix ---------------
# id | element | fg | bg | role | pairs.mjs status
PAIRS = rows_of(
    """P1|node body text, the ED-4 pill text, palette entries, the zoom readout (t1 on the card)|t1|raised|text|registered
P2|type word, the action's second line, T2 reason (t2 on the card)|t2|raised|text|registered
P3|T2 kept label on the card; the PT-1 ring on the card side (t3 on the card)|t3|raised|text|registered
P4|body text on the hover fill (N-2)|t1|hover|text|registered
P5|type word on the hover fill (N-2)|t2|hover|text|registered
P6|tertiary text on the hover fill (N-2)|t3|hover|text|registered
P7|node-list rows (t1 on the sunken pane)|t1|sunken|text|PROPOSED
P8|the empty-canvas hint "Start from a trigger" (t1 on the canvas)|t1|canvas|text|registered
P9|edge default ink ED-1 / ED-8 and the PT-1 ring on the canvas side (TP-1, TP-4)|t3|canvas|non-text|PROPOSED
P10|focus ring on the canvas (N-4, PT-14, ED-7)|ring|canvas|non-text|registered
P11|focus ring on the card; the PT-2 halo on the card side (TP-5)|ring|raised|non-text|registered
P12|focus ring on the hover fill|ring|hover|non-text|PROPOSED
P13|focus ring on the sunken pane (node-list rows, minimap controls)|ring|sunken|non-text|registered
P14|focus ring adjacent to the graph-only badge fill|ring|warn.subtle|non-text|PROPOSED
P15|focus ring adjacent to the mismatch badge fill|ring|danger.subtle|non-text|PROPOSED
P16|selected outline outer side (N-3), ED-2, ED-5, PT-4 source ring, marquee boundary on the canvas (TP-2)|b.selected|canvas|non-text|PROPOSED
P17|selected outline inner side (N-3) and the PT-4 ring on the card|b.selected|raised|non-text|PROPOSED
P18|minimap viewport rectangle on the well|b.selected|sunken|non-text|PROPOSED
P19|marquee boundary on its own tint|b.selected|a.selected|non-text|PROPOSED
P20|selected outline inner side on a hovered node (N-2 + N-3)|b.selected|hover|non-text|PROPOSED
P21|trigger port fill, card side (PT-5); the inset stripe D02 rejected — the canvas side is P26|n.trigger|raised|reported|never (D03 §3.1)
P22|condition port fill, card side (PT-5)|n.condition|raised|non-text|PROPOSED
P23|action port fill, card side (PT-5)|n.action|raised|non-text|PROPOSED
P24|logic port fill, card side (PT-5)|n.logic|raised|non-text|PROPOSED
P25|comment stripe inset into the body — rejected (D02 §16 item 3; the comment node has no ports)|n.comment|raised|rejected-non-text|never (D03 §3.1)
P26|trigger stripe and port fill on the canvas|n.trigger|canvas|non-text|registered
P27|condition stripe and port fill on the canvas|n.condition|canvas|non-text|registered
P28|action stripe and port fill on the canvas|n.action|canvas|non-text|registered
P29|logic stripe and port fill on the canvas|n.logic|canvas|non-text|registered
P30|comment stripe on the canvas|n.comment|canvas|non-text|registered
P31|error outline outer side (N-7), ED-3, ED-9, the PT-3 mark on the canvas side (TP-3, TP-6)|danger|canvas|non-text|PROPOSED
P32|error outline inner side (N-7), the PT-3 mark on the card side|danger|raised|non-text|PROPOSED
P33|warning outline outer side (N-8), the PT-13 ring on the canvas side|warn|canvas|non-text|PROPOSED
P34|warning outline inner side (N-8), the PT-13 ring on the card side — reported: the glyph and word carry|warn|raised|reported|never (D03 §3.2)
P35|graph-only badge glyph on its fill|warn.strong|warn.subtle|non-text|registered
P36|mismatch badge glyph on its fill|danger.strong|danger.subtle|non-text|registered
P37|graph-only badge word|t1|warn.subtle|text|registered
P38|mismatch badge word|t1|danger.subtle|text|registered
P39|error glyph on the card (N-7)|danger.strong|raised|non-text|PROPOSED
P40|warning glyph on the card (N-8, PT-13)|warn.strong|raised|non-text|registered
P41|hovered edge ED-6 (t2 on the canvas, graded at the text bar it is registered under)|t2|canvas|text|registered
P42|node-list secondary text (t2 on the sunken pane)|t2|sunken|text|registered
P43|dot grid on the canvas — decorative (16 §6 rule 7; exempted pair, E05-T01)|grid|canvas|decorative|registered, exempted
P44|marquee tint on the canvas — the selection tint, decorative by design|a.selected|canvas|decorative|never (CHANGELOG 0.1.1)
P45|minimap viewport tint on the well — decorative|a.selected|sunken|decorative|never
P46|card hairline outer side on the canvas — decorative|b.default|canvas|decorative|never
P47|hairline on the ED-4 pill and the ED-2 disc — decorative|b.default|raised|decorative|never
P48|hover fill against the card fill — a fill step, reported|hover|raised|reported|never
P49|card fill against the canvas — the stripe and elevation.card define the card, reported|raised|canvas|reported|never
P50|minimap trigger rect and the warning severity dot on the well (aria-hidden, reported)|n.trigger|sunken|reported|never
P51|minimap condition rect on the well (reported)|n.condition|sunken|reported|never
P52|minimap action rect on the well (reported)|n.action|sunken|reported|never
P53|minimap logic rect on the well (reported)|n.logic|sunken|reported|never
P54|minimap comment rect on the well (reported)|n.comment|sunken|reported|never
P55|minimap danger severity dot on the well (reported)|danger|sunken|reported|never
P56|focus ring vs the action port fill — not adjacent (the fill sits >= 6 px inside the ring), reported|ring|n.action|reported|never"""
)

# values D02 §16 and E25-D03 §8 print for the same pairs — reproduced, never re-typed
REPRO: dict[str, str] = {
    "P1": "14.35 / 15.62 / 16.25",
    "P3": "5.62 / 5.92 / 11.21",
    "P9": "5.96 / 6.36 / 11.87",
    "P10": "7.05 / 6.30 / 18.32",
    "P11": "6.66 / 5.86 / 17.30",
    "P16": "5.18 / 4.44 / 7.05",
    "P18": "5.94 / 3.39 / 8.08",
    "P21": "7.98 / 2.9992 / 7.98",
    "P25": "2.86 / 3.74 / 2.86",
    "P26": "8.45 / 3.22 / 8.45",
    "P27": "6.57 / 3.74 / 6.57",
    "P28": "7.45 / 5.03 / 7.45",
    "P29": "4.33 / 5.60 / 4.33",
    "P30": "3.03 / 4.02 / 3.03",
    "P31": "3.63 / 9.62 / 4.30",
    "P35": "7.56 / 4.90 / 7.56",  # re-pinned at PR 2's base: the light status inks moved (#5140; D03-C15)
}


def matrix(problems: list[str]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    fails = gated = repro_ok = 0
    for pid, element, fg, bg, role, reg in PAIRS:
        bar = BAR[role]
        vals = [ratio(col(t, fg), col(t, bg)) for t in THEMES]
        text = fmt3(vals, bar)
        if role in GATED:
            gated += 1
            bad = [t for t, v in zip(THEMES, vals, strict=True) if v < (bar or 0)]
            verdict = "PASS" if not bad else "FAIL " + ", ".join(bad)
            if bad:
                fails += 1
                problems.append(f"contrast FAIL {pid} {element}: {text}")
        elif role.startswith("rejected"):
            bad = [t for t, v in zip(THEMES, vals, strict=True) if v < (bar or 0)]
            verdict = "rejected: fails " + ", ".join(bad) if bad else "rejected by design"
        else:
            verdict = role
        if pid in REPRO:
            repro_ok += int(REPRO[pid] == text)
            if REPRO[pid] != text:
                problems.append(f"reproduction lost {pid}: {text} vs {REPRO[pid]}")
        rows.append(
            {
                "id": pid,
                "element": element,
                "fg": TOK.get(fg, fg),
                "bg": TOK.get(bg, bg),
                "role": role,
                "text": text,
                "verdict": verdict,
                "pairs_mjs": reg,
            }
        )
    return {
        "pairs": len(rows),
        "gated": gated,
        "fail": fails,
        "repro_ok": repro_ok,
        "repro_n": len(REPRO),
        "rows": rows,
    }


def matrix_lines(mx: dict[str, Any]) -> list[str]:
    """The §9.1 rows exactly as the spec carries them."""
    out = []
    for r in mx["rows"]:
        out.append(
            f"| {r['id']} | {r['element']} | `{r['fg']}` | `{r['bg']}` | {r['role']} | "
            f"{r['text']} | {r['verdict']} | {r['pairs_mjs']} |"
        )
    return out


# ------------------------------------------------------------------ helpers ---------------------
def cells(ln: str) -> list[str]:
    return [c.strip() for c in ln.strip().strip("|").split("|")]


def table(spec: str, prefix: str) -> list[list[str]]:
    rx = re.compile(rf"^\| {re.escape(prefix)}\d+ +\|")
    return [cells(ln) for ln in spec.splitlines() if rx.match(ln)]


def section(spec: str, start: str, end: str) -> str:
    i = spec.find(start)
    j = spec.find(end, i + len(start)) if i >= 0 else -1
    return spec[i:j] if i >= 0 and j > i else ""


def quoted(cell: str) -> list[str]:
    return re.findall(r"\u201c([^\u201d]+)\u201d|\"([^\"]+)\"", cell) and [
        a or b for a, b in re.findall(r"\u201c([^\u201d]+)\u201d|\"([^\"]+)\"", cell)
    ]


# ------------------------------------------------------------------ C. the proposals ------------
def proposals(spec: str, problems: list[str]) -> dict[str, Any]:
    rows = table(spec, "TP-")
    if len(rows) != len(PROPOSED):
        problems.append(f"token-proposal table: {len(rows)} rows, {len(PROPOSED)} aliases proposed")
    seen: set[str] = set()
    for r in rows:
        if len(r) < 10:
            problems.append(f"token-proposal row {r[0]} lacks a column")
            continue
        alias = re.findall(r"`([a-z.]+)`", r[1])
        name = alias[0] if alias else ""
        if name not in PROPOSED:
            problems.append(f"token-proposal row {r[0]} names an alias not proposed: {name!r}")
            continue
        seen.add(name)
        if "{" + PROPOSED[name] + "}" not in r[2]:
            problems.append(f"token-proposal {name}: target is not {{{PROPOSED[name]}}}")
        fb = re.findall(r"`([a-z.]+)`", r[7])
        if not fb or not exists(fb[0]):
            problems.append(f"token-proposal {name}: fallback does not resolve ({r[7]!r})")
        if "E37-S01" not in r[8] or "feat(design-system)" not in r[8]:
            problems.append(f"token-proposal {name}: owner is not E37-S01's feat(design-system) PR")
        if r[9] != "PROPOSED":
            problems.append(f"token-proposal {name}: status {r[9]!r} is not PROPOSED")
    lost = sorted(set(PROPOSED) - seen)
    problems += [f"token-proposal table lacks {n}" for n in lost]
    return {"rows": len(rows), "aliases": sorted(seen)}


# ------------------------------------------------------------------ D. the motion pairs ---------
def motion(spec: str, problems: list[str]) -> dict[str, Any]:
    rows = table(spec, "M-")
    out: dict[str, Any] = {"rows": len(rows), "timed": []}
    if len(rows) < 15:
        problems.append(f"motion table: {len(rows)} rows, the ticket's eight motions need more")
    for r in rows:
        if len(r) < 6:
            problems.append(f"motion row {r[0]} lacks a column")
            continue
        safe, reduce = r[2], r[3]
        flash = "flash" in r[1].lower()
        if flash:
            if not safe.startswith("0 flashes") or reduce != "0":
                problems.append("motion table: the flash row does not read 0 flashes / 0")
        elif reduce not in ("instant", "identical"):
            problems.append(f"motion table: {r[0]} reduce cell {reduce!r} is not instant|identical")
        if not flash and re.search(r"motion\.duration\.|`(fast|normal|slow)`", safe):
            out["timed"].append(r[0])
        if "auto-layout" in r[1].lower():
            slow = int(str(T["dark"]["motion.duration.slow"]).rstrip("ms"))
            ms = re.search(r"(\d+) ms", safe)
            if "`motion.duration.slow`" not in safe or "stagger 0" not in safe:
                problems.append("motion table: auto-layout is not slow / stagger 0")
            if not ms or int(ms.group(1)) > slow or int(ms.group(1)) != 400:
                problems.append(f"motion table: auto-layout exceeds motion.duration.slow {slow} ms")
            if reduce != "instant":
                problems.append("motion table: auto-layout reduce is not instant")
        if "source port" in r[1].lower() and "no pulse" not in safe:
            problems.append("motion table: the active-connect source port pulses")
        if "connection made" in r[1].lower():
            if "opacity" not in safe or "never a line-draw" not in safe:
                problems.append("motion table: connection-made is not the opacity fade")
            if reduce != "instant":
                problems.append("motion table: connection-made reduce is not instant")
    if not any("flash" in r[1].lower() for r in rows):
        problems.append("motion table: no flash row")
    timed = out["timed"]
    if timed and f"the timed transitions are {', '.join(timed[:-1])} and {timed[-1]}" not in spec:
        problems.append(f"motion table: the spec does not name the timed transitions {timed}")
    return out


# ------------------------------------------------------------------ E. the tiers ----------------
KEPT_BY_BAND = ("badge (glyph + word)", "error / warning outline, glyph and word kept")
SECURITY_RX = re.compile(r"badge|error|outline")


def tiers(spec: str, problems: list[str]) -> dict[str, Any]:
    rows = table(spec, "Z-")
    sec = section(spec, "\n## 8.", "\n## 9.")
    zooms = " ".join(r[1] for r in rows)
    if "75" not in zooms or "50" not in zooms:
        problems.append("tier table: the 75 % / 50 % bands are missing")
    for r in rows:
        # the Security sentences of §11.2: no band hides the badge glyph + word or the error
        # outline, glyph and word — the Nodes cell lists what it hides before "hidden"
        nodes = r[2] if len(r) > 2 else ""
        hidden = nodes.split("hidden")[0] if "hidden" in nodes else ""
        keeps = all(k in nodes for k in KEPT_BY_BAND)
        if SECURITY_RX.search(hidden) or ("hidden" in nodes and not keeps):
            problems.append(f"tier table: {r[0]} hides a badge or error treatment")
    for needle in ("re-lays out nothing", "visibility", "Tier A", "Tier B", "Tier C"):
        if needle not in sec:
            problems.append(f"tier section lacks {needle!r}")
    if "no density variant" not in sec:
        problems.append("tier section: node chrome density rule missing")
    return {"bands": len(rows)}


# ------------------------------------------------------------------ F. the A-rows ---------------
CMPS = tuple(f"CMP-{n}" for n in (146, 147, 148, 149, 150, 151, 152, 153, 236, 237, 238))
FIELDS = ("Tokens", "Motion", "Storybook", "Usage")
POINTER_14 = "Design-system tokens and motion (E37-D03)"
ANCHOR_14 = "- **Design (wireframe → hi-fi, E37-D02):**"
# A-47 in the form PR 2 applies (BQ-02 RULED as proposed: the `14` line rides with the boards)
A47_HEAD = (
    '"- **Design-system tokens and motion (E37-D03):** [E37-D03.md](../design/E37/E37-D03.md) '
    "(E37-D03; owner approval pending;"
)
A47_TAIL = (
    "; nine Penpot boards planned on page `E37-D03 Tokens and motion`, "
    'exports in `docs/design/E37/img/`)"'
)
LINE_RX = re.compile(r"\((\d+)\)\s*$")


def cited_line(today: str, lines: list[str]) -> tuple[str, str]:
    """The `(NNNN)` line number a today-cell cites and that line of the file ('' if none)."""
    m = LINE_RX.search(today)
    if not m:
        return "", ""
    n = int(m.group(1))
    return m.group(1), lines[n - 1] if 0 < n <= len(lines) else ""


def amendments(spec: str, problems: list[str], screens: str | None = None) -> dict[str, Any]:
    rows = table(spec, "A-")
    cat = CATALOGUE.read_text(encoding="utf-8")
    cat_lines = cat.splitlines()
    brief = BRIEF.read_text(encoding="utf-8")
    brief_lines = brief.splitlines()
    screens = SCREENS.read_text(encoding="utf-8") if screens is None else screens
    per_cmp: dict[str, set[str]] = {c: set() for c in CMPS}
    saw16 = saw14 = False
    for r in rows:
        if len(r) < 5:
            problems.append(f"A-row {r[0]} lacks a column")
            continue
        entry, field, today, proposed = r[1], r[2], r[3], r[4]
        cmp_ = next((c for c in CMPS if c in entry), None)
        if cmp_:
            fname = next((f for f in FIELDS if field.startswith(f)), None)
            if fname is None:
                problems.append(
                    f"A-row {r[0]} field {field!r} is not Tokens|Motion|Storybook|Usage"
                )
                continue
            per_cmp[cmp_].add(fname)
            if fname in ("Tokens", "Storybook"):
                block = section(cat, f"### {cmp_} ", "\n### ")
                # a line check: the quoted text sits on the cited `15` line, which is that
                # entry's field line — not merely somewhere in the entry's block
                no, line = cited_line(today, cat_lines)
                on_line = (
                    bool(no)
                    and line.startswith(f"- **{fname}**:")
                    and line in block
                    and all(q in line for q in quoted(today))
                )
                if not on_line:
                    problems.append(
                        f"A-row {r[0]}: today's text is not on 15 line {no or '?'} "
                        f"({cmp_} {fname})"
                    )
                if f"- **{fname}**:" not in block:
                    problems.append(f"A-row {r[0]}: 15 {cmp_} has no {fname} field")
                if "**E37-D03 —**" not in proposed:
                    problems.append(f"A-row {r[0]}: proposed text lacks the E37-D03 lead-in")
            else:
                if not proposed.lstrip('"').startswith(f"**{fname} (E37-D03)**:"):
                    problems.append(f"A-row {r[0]}: {fname} text lacks its heading string")
        elif "`16`" in entry:
            saw16 = True
            no, line = cited_line(today, brief_lines)
            for q in quoted(today):
                if q not in (line if no else brief):
                    problems.append(f"A-row {r[0]}: today's text not on 16 line {no or '?'}: {q!r}")
            if "§7 recipe" in field:  # A-46: E05-D03 A-7 owns the recipe (merged as #4990)
                if "E05-D03 (#162)" not in proposed:
                    problems.append(f"A-row {r[0]}: the §7 recipe row does not point at #162")
                if "does not touch `16`" not in proposed:
                    problems.append(
                        f"A-row {r[0]}: the §7 recipe row must say PR 2 does not touch 16"
                    )
        elif "`14`" in entry:
            saw14 = True
            if not (proposed.startswith(A47_HEAD) and proposed.endswith(A47_TAIL)):
                problems.append(f"A-row {r[0]}: the 14 pointer line is not in its PR 2 form")
        else:
            problems.append(f"A-row {r[0]} names no known entry: {entry!r}")
    if POINTER_14 in screens:
        problems.append("14: the SCR-082 pointer line is applied in this PR (BQ-02: PR 2)")
    if ANCHOR_14 not in screens:
        problems.append("14: the SCR-082 D02 pointer line A-47 follows is missing")
    if not saw14:
        problems.append("A-rows: no 14 row")
    for c, fields in per_cmp.items():
        lost = [f for f in FIELDS if f not in fields]
        if lost:
            problems.append(f"A-rows: {c} lacks {lost}")
    if not saw16:
        problems.append("A-rows: no 16 row")
    return {"rows": len(rows)}


# ------------------------------------------------------------------ G. the boards ---------------
BOARD_RX = re.compile(r"^\| 0\d +\| `")
STATUS_PENDING = "to draw (PR 2)"  # §0's Status cell before the draw
IMG_REL = "docs/design/E37/img"
CVD_BOARDS = ("01", "02", "03", "04", "05", "06", "07", "08")  # §0: board 09 is the swatch board
CVD_KINDS = ("greyscale", "deuteranopia")
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
DRAWN = re.compile(
    rf"drawn \((r\d+)(?:, (light))?\): board id `({UUID})`, "
    r"`(docs/design/E37/img/E37-D03-(\d\d)-([a-z0-9-]+)\.png)` \((\d+) × (\d+), sha256 `([0-9a-f]{64})`\)"
)
PAGE_ID = re.compile(rf"page id `({UUID})`")
RENDER_SHA = re.compile(
    r"`(E37-D03-\d\d-[a-z0-9-]+-(?:greyscale|deuteranopia)\.png)` \(sha256 `([0-9a-f]{64})`\)"
)
Files = dict[str, bytes]


class Repo(NamedTuple):
    """The committed exports (path -> bytes) and the changed lines against the merge base."""

    files: Files
    diff: (
        dict[str, list[str]] | None
    )  # None: not a git work tree (an archive), the scope gate skips


def git(*args: str) -> str | None:
    try:
        run = subprocess.run(
            ["git", "-C", str(ROOT), *args], check=False, capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return run.stdout if run.returncode == 0 else None


SCOPE_PACK = {
    "docs/design/E37/E37-D03.md",
    "docs/design/_tools/e37_d03_tokens_motion_audit.py",
}
SCOPE_AMENDED = {
    "docs/plan/15-component-catalogue.md",
    "docs/plan/16-design-system-brief.md",
    "docs/plan/14-screens-catalogue.md",
}


def read_repo() -> Repo:
    img = ROOT / IMG_REL
    files = (
        {f"{IMG_REL}/{f.name}": f.read_bytes() for f in sorted(img.glob("E37-D03-*.png"))}
        if img.is_dir()
        else {}
    )
    if git("rev-parse", "--is-inside-work-tree") is None:
        return Repo(files, None)
    base = git("merge-base", "HEAD", "origin/main")
    names = git("diff", "--name-only", base.strip()) if base else None
    if base is None or names is None:
        return Repo(files, {"?": ["no merge base with origin/main"]})
    diff: dict[str, list[str]] = {}
    for path in names.split():
        diff[path] = []
        if path in SCOPE_AMENDED:
            body = git("diff", "-U0", base.strip(), "--", path) or ""
            diff[path] = [
                ln
                for ln in body.splitlines()
                if ln[:1] in "+-" and not ln.startswith(("+++", "---"))
            ]
    return Repo(files, diff)


def png_size(data: bytes | None) -> tuple[int, int] | None:
    if data is None or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def board_rows(spec: str) -> list[list[str]]:
    return [cells(ln) for ln in spec.splitlines() if BOARD_RX.match(ln)]


def board_mode(spec: str) -> str:
    rows = board_rows(spec)
    return "pending" if all(len(r) > 4 and r[4] == STATUS_PENDING for r in rows) else "drawn"


def board_exports(spec: str) -> list[str]:
    out: list[str] = []
    for r in board_rows(spec):
        m = DRAWN.fullmatch(r[4]) if len(r) > 4 else None
        if m:
            out.append(m[4])
            if r[0] in CVD_BOARDS:
                out += [m[4][: -len(".png")] + f"-{k}.png" for k in CVD_KINDS]
    return out


def boards_drawn(spec: str, files: Files, problems: list[str]) -> int:
    rows = board_rows(spec)
    statuses = [r[4] if len(r) > 4 else "" for r in rows]
    if STATUS_PENDING in statuses:
        problems.append(
            f"board plan: §0 mixes pending and drawn rows ({statuses.count(STATUS_PENDING)} pending)"
        )
        return 0
    s0 = section(spec, "\n## 0.", "\n## 1.")
    if not PAGE_ID.search(s0):
        problems.append("board plan: §0 does not name the page id")
    listed = dict(RENDER_SHA.findall(s0))
    ids: list[str] = []
    bad_sha: list[str] = []
    for r in rows:
        m = DRAWN.fullmatch(r[4]) if len(r) > 4 else None
        if not m:
            problems.append(f"board {r[0]}: the Status cell is not the drawn form")
            continue
        _, theme, bid, rel, nn, slug, w, h, sha = m.groups()
        ids.append(bid)
        if nn != r[0] or slug != r[1].strip("`"):
            problems.append(
                f"board {r[0]}: the export {rel} is not E37-D03-{r[0]}-{r[1].strip('`')}.png"
            )
        if (theme == "light") != r[3].lower().startswith("light"):
            problems.append(f"board {r[0]}: the theme word {theme!r} is not the Theme cell's")
        data = files.get(rel)
        size = png_size(data)
        if data is None or size is None:
            problems.append(f"board {r[0]}: {rel} is missing or not a PNG")
            continue
        if size != (int(w), int(h)):
            problems.append(
                f"board {r[0]}: {rel} is {size[0]} × {size[1]}, the cell says {w} × {h}"
            )
        elif hashlib.sha256(data).hexdigest() != sha:
            bad_sha.append(r[0])
        if r[0] in CVD_BOARDS:
            for k in CVD_KINDS:
                rr = rel[: -len(".png")] + f"-{k}.png"
                rd = files.get(rr)
                want = listed.get(rr.rsplit("/", 1)[1])
                if png_size(rd) is None or rd is None:
                    problems.append(f"board {r[0]}: the {k} render is missing")
                elif want is None:
                    problems.append(
                        f"board {r[0]}: §0 does not list the {k} render with its sha256"
                    )
                elif hashlib.sha256(rd).hexdigest() != want:
                    problems.append(f"board {r[0]}: the {k} render's sha256 is not §0's")
    if bad_sha:  # one finding: a byte swap between two same-size exports is one defect
        problems.append(
            f"board plan: the export sha256 of board(s) {', '.join(bad_sha)} is not the cell's"
        )
    if len(set(ids)) != len(ids):
        problems.append("board plan: two boards share an id")
    stray = sorted(set(files) - set(board_exports(spec))) if len(ids) == len(rows) else []
    if stray:
        problems.append(f"board plan: exports committed but not in §0: {stray}")
    return len(ids)


def boards(spec: str, problems: list[str], files: Files | None = None) -> dict[str, Any]:
    rows = board_rows(spec)
    slugs = [r[1] for r in rows]
    twins = sum(1 for r in rows if r[3].lower().startswith("light"))
    # the Theme column against §0's convention paragraph (light twins, the hc cells' board)
    sec0 = section(spec, "\n## 0.", "\n## 1.")
    m_light = re.search(r"light on (\d\d) and (\d\d) through", sec0)
    m_hc = re.search(r"high-contrast as literal cells on (\d\d)[;,]", sec0)
    light_ids = set(m_light.groups()) if m_light else set()
    hc_ids = {m_hc.group(1)} if m_hc else set()
    for r in rows:
        theme = r[3].lower() if len(r) > 3 else ""
        if theme.startswith("light") != (r[0] in light_ids) or ("hc" in theme) != (r[0] in hc_ids):
            problems.append(f"board plan: board {r[0]} theme {r[3]!r} disagrees with §0")
    mode = board_mode(spec)
    out: dict[str, Any] = {"boards": len(rows), "light_twins": twins, "slugs": slugs, "mode": mode}
    if len(rows) > MAX_BOARDS:
        problems.append(f"board plan: {len(rows)} boards, over {MAX_BOARDS}")
        return out
    if twins > len(rows) // 3:
        problems.append(f"board plan: {twins} light twins of {len(rows)}, over one third")
    if len(set(slugs)) != len(slugs):
        problems.append("board plan: a slug repeats")
    if any(len(r) != 5 for r in rows):
        problems.append("board plan: a register row is not # · Board · Shows · Theme · Status")
    if f"{len(rows)} boards" not in spec or f"{twins} light twins" not in spec:
        problems.append("board plan: the spec does not state its board and twin counts")
    files = {} if files is None else files
    if mode == "drawn":
        out["exports"] = boards_drawn(spec, files, problems)
    else:
        if re.search(UUID, sec0):
            problems.append("board plan: a page id or uuid in a pending §0")
        if files:
            problems.append(
                f"board plan: {len(files)} E37-D03 export(s) committed while §0 is pending"
            )
        out["exports"] = 0
    return out


def scope(repo: Repo, problems: list[str]) -> str:
    """Only the pack, its exports and the amended `15` / `16` / `14` lines differ (C-4.9)."""
    if repo.diff is None:
        return "skipped (no git work tree)"
    out = sorted(
        p
        for p in repo.diff
        if p not in SCOPE_PACK
        and p not in SCOPE_AMENDED
        and not re.fullmatch(r"docs/design/E37/img/E37-D03-[a-z0-9-]+\.png", p)
    )
    if out:
        problems.append(f"scope: outside E37-D03's set, differs from the merge base: {out}")
    if any(
        not ln[1:].startswith("- **Design-system tokens and motion (E37-D03):**")
        for ln in repo.diff.get("docs/plan/14-screens-catalogue.md", [])
    ):
        problems.append("scope: `14` changes a line other than the A-47 pointer line")
    heads = (
        "- **Tokens**:",
        "- **Storybook**:",
        "- **Motion (E37-D03)**:",
        "- **Usage (E37-D03)**:",
    )
    if any(
        not ln[1:].startswith(heads)
        for ln in repo.diff.get("docs/plan/15-component-catalogue.md", [])
    ):
        problems.append("scope: `15` changes a line other than a CMP field the A-rows name")
    if any(ln[0] == "-" for ln in repo.diff.get("docs/plan/16-design-system-brief.md", [])):
        problems.append("scope: `16` loses a line (A-45 only adds the §7.2 pointer subsection)")
    return f"{len(repo.diff)} file(s) differ, all in E37-D03's set" if not out else "outside"


# ------------------------------------------------------------------ H. hygiene ------------------
# assembled so that this file does not itself carry the words it forbids
FORBIDDEN = {
    "closing keyword": re.compile(r"(?i)\b(clos" + r"es|fix" + r"es|resol" + r"ves)\s+#\d+"),
    "local path": re.compile("/ho" + r"me/\w+|/Us" + r"ers/\w+|C:\\\\"),
    "worker name": re.compile(r"\b[a-z]{2,5}-wor" + r"ker-\d+\b|wt-no" + r"tes|\bAgent [A-C]\b"),
    "host or url": re.compile(r"https?://|pen" + r"pot\.[a-z]|\.candle" + r"viewer\.com"),
    "16:184 contingency": re.compile(
        r"(?i)if #162 has not merged|applies A-46|whichever lands first|if #162 is not merged"
    ),
    "colour emoji": re.compile("[\U0001f300-\U0001faff\u2600-\u26ff]"),
    "page id or uuid": re.compile(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
    ),
}
RULE_RX = re.compile(r"\bC-\d+\.\d+\b")
STAMP = "RULED (orchestrator, 2026-10-29, #876 ruling of record"
AUDIT_RX = re.compile(r"<!-- audit:([a-z_]+)=(\d+) -->")


def hygiene(spec: str, problems: list[str]) -> dict[str, Any]:
    outside_s0 = spec.replace(section(spec, "\n## 0.", "\n## 1."), "")  # §0 alone names ids
    for name, rx in FORBIDDEN.items():
        if rx.search(outside_s0 if name == "page id or uuid" else spec):
            problems.append(f"hygiene: {name}")
    constitution = CONSTITUTION.read_text(encoding="utf-8")
    ids = sorted(set(RULE_RX.findall(spec)))
    problems += [
        f"{i} not in CONSTITUTION.md"
        for i in ids
        if not re.search(rf"\b{re.escape(i)}\b", constitution)
    ]
    return {"rule_ids": len(ids)}


# ------------------------------------------------------------------ I. counts -------------------
PREFIXES = (
    "N-",
    "PT-",
    "ED-",
    "Z-",
    "TP-",
    "M-",
    "A-",
    "HO-",
    "D03-C",
    "D03-G",
    "H-",
    "GL-",
    "EN-",
    "BQ-",
)


def counts(spec: str, problems: list[str]) -> dict[str, Any]:
    """Every count the spec states as an `<!-- audit:key=n -->` mark is re-derived from its rows."""
    out: dict[str, Any] = {}
    for prefix in PREFIXES:
        out[prefix] = len(table(spec, prefix))
    lost = [c for c in CMPS if c not in spec]
    problems += [f"entry missing from the spec: {c}" for c in lost]
    if STAMP not in spec:
        problems.append("the ruling stamp is missing")
    marks = {k: int(v) for k, v in AUDIT_RX.findall(spec)}
    computed = {
        "tp_rows": out["TP-"],
        "node_states": out["N-"],
        "port_rows": out["PT-"],
        "edge_rows": out["ED-"],
        "motion_rows": out["M-"],
        "zoom_bands": out["Z-"],
        "a_rows": out["A-"],
        "c_rows": out["D03-C"],
        "g_rows": out["D03-G"],
        "ho_rows": out["HO-"],
        "glyph_rows": out["GL-"],
    }
    for k, v in computed.items():
        if k not in marks:
            problems.append(f"audit mark {k} is missing from the spec")
        elif marks[k] != v:
            problems.append(f"audit mark {k}={marks[k]} but the spec carries {v}")
    out["marks"] = len(marks)
    return out


# ------------------------------------------------------------------ L. pairs.mjs ----------------
PAIR_RX = re.compile(r'fg:\s*"([a-z0-9.-]+)",\s*bg:\s*"([a-z0-9.-]+)"')


def registry() -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """`pairs.mjs` PAIRS as (fg, bg) and the `exemptions.json` pairs exempted in every theme."""
    pairs = set(PAIR_RX.findall(PAIRS_MJS.read_text(encoding="utf-8")))
    themes: dict[tuple[str, str], set[str]] = {}
    for e in json.loads(EXEMPTIONS.read_text(encoding="utf-8"))["exemptions"]:
        m = re.fullmatch(r"([a-z-]+):(\S+) on (\S+)", str(e.get("pair", "")))
        if m:
            themes.setdefault((m.group(2), m.group(3)), set()).add(m.group(1))
    exempt = {k for k, v in themes.items() if v >= set(THEMES)}
    return pairs, exempt


def registrations(spec: str, problems: list[str]) -> dict[str, Any]:
    """Every `pairs.mjs` claim of §9.1 (the spec's cell) against the registry at the base."""
    pairs, exempt = registry()
    tool = {r[0]: r[5] for r in PAIRS}
    # the PROPOSED tally comes from the tool's column (kept equal to the spec's by the stale check)
    proposed = sum(1 for v in tool.values() if v == "PROPOSED")
    registered = 0
    for r in table(spec, "P"):
        if len(r) < 8:
            continue
        pid, pair, claim = r[0], (r[2].strip("`"), r[3].strip("`")), r[7]
        wants_reg = claim.startswith("registered")
        wants_ex = "exempted" in claim
        registered += int(wants_reg)
        if (pair in pairs) != wants_reg or (pair in exempt) != wants_ex:
            problems.append(f"pairs.mjs: {pid} claims {claim!r}, the registry disagrees")
        elif tool.get(pid) != claim:
            problems.append(f"pairs.mjs: the tool's {pid} status {tool.get(pid)!r} is stale")
    return {"registered": registered, "proposed": proposed, "in_registry": len(pairs)}


# ------------------------------------------------------------------ K. drift --------------------
def drift(spec: str, mx: dict[str, Any], reg: dict[str, Any]) -> list[str]:
    """Every §9.1 row (all cells but the pairs.mjs claim, which L owns) and every count."""
    have = {r[0]: r[:7] for r in table(spec, "P")}
    lost = []
    for r in mx["rows"]:
        want = [r["id"], r["element"], f"`{r['fg']}`", f"`{r['bg']}`", r["role"]]
        want += [r["text"], r["verdict"]]
        if have.get(r["id"]) != want:
            lost.append(f"matrix row {r['id']}")
    need = [f"{mx['pairs']} pairs × 3 themes", f"{mx['gated']} gated", f"FAIL {mx['fail']}"]
    need.append(f"{mx['repro_ok']} of {mx['repro_n']} reproductions")
    need.append(f"the {reg['proposed']} PROPOSED rows of §9.1")
    need.append(f"{reg['proposed']} `pairs.mjs` rows")
    need.append(str(T["dark"]["motion.duration.slow"]).replace("ms", " ms"))
    return lost + [n for n in need if n not in spec]


def evaluate(
    spec: str, screens: str | None = None, repo: Repo | None = None
) -> tuple[list[str], dict[str, Any]]:
    problems: list[str] = []
    out: dict[str, Any] = {}
    out["tokens"] = tokens(spec, problems)
    out["matrix"] = matrix(problems)
    out["proposals"] = proposals(spec, problems)
    out["motion"] = motion(spec, problems)
    out["tiers"] = tiers(spec, problems)
    out["amendments"] = amendments(spec, problems, screens)
    repo = read_repo() if repo is None else repo
    out["boards"] = boards(spec, problems, repo.files)
    out["boards"]["scope"] = scope(repo, problems)
    out["hygiene"] = hygiene(spec, problems)
    out["counts"] = counts(spec, problems)
    out["registrations"] = registrations(spec, problems)
    out["drift"] = drift(spec, out["matrix"], out["registrations"])
    problems += [f"drift: the spec does not carry {n!r}" for n in out["drift"]]
    out["problems"] = problems
    return problems, out


# ------------------------------------------------------------------ self-test -------------------
MUTATIONS: tuple[tuple[str, ...], ...] = (  # (name, old, new[, occurrences])
    ("a contrast value drifts", "| 4.79 / 4.86 / 9.54 ", "| 4.79 / 4.87 / 9.54 "),
    ("a token name is invented", "`color.surface.hover` fill", "`color.surface.hovered` fill"),
    (
        "an alias target changes",
        "| `{color.text.tertiary}` in all three |",
        "| `{color.text.disabled}` in all three |",
    ),
    (
        "an alias loses its owner",
        "E37-S01 `feat(design-system)` PR | PROPOSED",
        "the design lane | PROPOSED",
    ),
    (
        "a reduce cell animates",
        "| instant       | the drawer + focus",
        "| `fast` slide  | the drawer + focus",
    ),
    ("a flash appears", "| 0 flashes (", "| 1 flash ("),
    (
        "auto-layout accumulates a stagger",
        "**stagger 0** — all nodes start",
        "stagger 20 ms per node — all nodes start",
    ),
    (
        "the source port pulses",
        "**static** ring + fill; **no pulse**",
        "a 1 Hz opacity pulse on the ring",
    ),
    (
        "connection-made becomes a line-draw",
        "**never a line-draw** (a stroke-dash",
        "a `fast` stroke-dash line-draw (a stroke-dash",
    ),
    ("a zoom band is lost", "| Z-3  | < 50 %", "| Z-3x | < 50 %"),
    (
        "an A-row today-text is invented",
        '"`color.edge.default/selected`" (1866)',
        '"`color.edge.default/strong`" (1866)',
    ),
    (
        "the 16:184 row forgets #162",
        "none — E05-D03 (#162) A-7",
        "none — E05-D03 (issue one-six-two) A-7",
    ),
    (
        "the 16:184 contingency returns",
        "## 20. Summary",
        "## 20. Summary (if #162 has not merged, PR 2 applies A-46)",
    ),
    (
        "A-46 stops saying PR 2 leaves 16:184 alone",
        "PR 2 cites A-7 and does not touch `16` for it",
        "PR 2 cites A-7 and edits `16` for it",
    ),
    ("a closing keyword leaks", "## 20. Summary", "## 20. Summary (Clo" + "ses #876)"),
    ("a local path leaks", "## 19. Deviations", "## 19. Deviations (/ho" + "me/someone/notes)"),
    ("a dangling rule cite", "C-2.13", "C-9.99"),
    ("a node state is lost", "| N-10 |", "| N-10x |"),
    ("the ruling stamp is lost", STAMP, "RULED (someone, 2026-10-29)", "3"),
    ("a port row is lost", "| PT-16 |", "| PT-16x |"),
    (
        "the 14 line loses its PR 2 form",
        'exports in `docs/design/E37/img/`)"',
        'exports in `docs/design/E37/img/`)" — applied in this PR',
    ),
    (
        "a zoom band hides the badge word",
        "stripe, badge (glyph + word) and the error / warning outline, glyph and word kept; the card",
        "stripe, badge glyph only and the error / warning outline, glyph and word kept; the card",
    ),
    (
        "a pairs.mjs claim is wrong",
        "| non-text          | 5.96 / 6.36 / 11.87   | PASS                                | PROPOSED ",
        "| non-text          | 5.96 / 6.36 / 11.87   | PASS                                | registered ",
    ),
    (
        "an A-row cites the wrong 15 line",
        '"`color.node.trigger`" (1824)',
        '"`color.node.trigger`" (1825)',
    ),
    ("a matrix row drifts", "| P1  | node body text", "| P1  | node body text (bold)"),
    (
        "the PROPOSED-row count drifts",
        "the 17 PROPOSED rows of §9.1",
        "the 25 PROPOSED rows of §9.1",
    ),
)
# applied to `14` in memory: the pointer line lands in PR 2, never in this PR
MUTATIONS_14: tuple[tuple[str, str, str], ...] = (
    (
        "the 14 line is applied in PR 1",
        ANCHOR_14,
        f"- **{POINTER_14}:** [E37-D03.md](../design/E37/E37-D03.md) (…)\n{ANCHOR_14}",
    ),
)


View = tuple[str, str, Repo]  # (spec, `14`, repo)
Mut = tuple[str, bool, Callable[[View], View | None]]  # (name, on the drawn view, apply)


def literal(
    old: str, new: str, times: int = 1, target: str = "spec"
) -> Callable[[View], View | None]:
    def apply(v: View) -> View | None:
        spec, screens, repo = v
        text = spec if target == "spec" else screens
        if text.count(old) < times:
            return None
        text = text.replace(old, new, times)
        return (text, screens, repo) if target == "spec" else (spec, text, repo)

    return apply


def row_cell(n: str, col: int, value: str) -> Callable[[View], View | None]:
    def apply(v: View) -> View | None:
        ls = v[0].split("\n")
        for i, ln in enumerate(ls):
            if BOARD_RX.match(ln) and cells(ln)[0] == n:
                c = cells(ln)
                c[col] = value
                ls[i] = "| " + " | ".join(c) + " |"
                return "\n".join(ls), v[1], v[2]
        return None

    return apply


def extra_board(v: View) -> View | None:
    ls = v[0].split("\n")
    k = max(i for i, ln in enumerate(ls) if BOARD_RX.match(ln))
    ls.insert(k, f"| 00 | `extra` | x | dark | {cells(ls[k])[4]} |")
    return "\n".join(ls), v[1], v[2]


def fake_png(w: int, h: int, tag: str) -> bytes:
    """A PNG signature and IHDR of w x h, then the tag (the gate reads the size and the sha256)."""
    return (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + w.to_bytes(4, "big")
            + h.to_bytes(4, "big") + b"\x08\x06\x00\x00\x00" + tag.encode())  # fmt: skip


def drawn_view(v: View) -> tuple[View, bool]:
    """The drawn state: the committed one, or (§0 pending) one synthesised in memory — every Status
    cell drawn with a made-up id, every export and render a fake PNG of 2032 x 1800."""
    spec, screens, repo = v
    if board_mode(spec) == "drawn":
        return (
            spec,
            screens,
            repo._replace(diff=repo.diff if repo.diff is not None else {}),
        ), False
    files: Files = {}
    renders: list[str] = []
    ls = spec.split("\n")
    for i, ln in enumerate(ls):
        if not BOARD_RX.match(ln):
            continue
        c = cells(ln)
        rel = f"{IMG_REL}/E37-D03-{c[0]}-{c[1].strip('`')}.png"
        files[rel] = fake_png(2032, 1800, "board " + c[0])
        sha = hashlib.sha256(files[rel]).hexdigest()
        th = ", light" if c[3].lower().startswith("light") else ""
        bid = f"00000000-0000-4000-8000-0000000000{c[0]}"
        c[4] = f"drawn (r2{th}): board id `{bid}`, `{rel}` (2032 × 1800, sha256 `{sha}`)"
        ls[i] = "| " + " | ".join(c) + " |"
        if c[0] in CVD_BOARDS:
            for k in CVD_KINDS:
                rr = rel[: -len(".png")] + f"-{k}.png"
                files[rr] = fake_png(2032, 1800, f"render {c[0]} {k}")
                renders.append(
                    f"`{rr.rsplit('/', 1)[1]}` (sha256 `{hashlib.sha256(files[rr]).hexdigest()}`)"
                )
    last = max(i for i, ln in enumerate(ls) if BOARD_RX.match(ln))
    ls.insert(
        last + 1,
        "\nDrawn on page id `00000000-0000-4000-8000-000000000000`; the renders: "
        + "; ".join(renders)
        + ".",
    )
    return ("\n".join(ls), screens, Repo(files, {})), True


def swap_exports(v: View) -> View | None:
    """Swap the bytes of two same-size exports: the size holds, the sha256 catches it."""
    a, b = (
        f"{IMG_REL}/E37-D03-01-node-token-sheet.png",
        f"{IMG_REL}/E37-D03-02-port-edge-token-sheet.png",
    )
    fl = dict(v[2].files)
    if a not in fl or b not in fl or png_size(fl[a]) != png_size(fl[b]):
        return None
    fl[a], fl[b] = fl[b], fl[a]
    return v[0], v[1], v[2]._replace(files=fl)


def render_missing(v: View) -> View | None:
    gone = next((k for k in sorted(v[2].files) if k.endswith("-deuteranopia.png")), None)
    if gone is None:
        return None
    return v[0], v[1], v[2]._replace(files={k: d for k, d in v[2].files.items() if k != gone})


def first_drawn(v: View, fn: Callable[[re.Match[str]], str]) -> View | None:
    ls = v[0].split("\n")
    for i, ln in enumerate(ls):
        if BOARD_RX.match(ln):
            c = cells(ln)
            m = DRAWN.fullmatch(c[4])
            if m:
                c[4] = fn(m)
                ls[i] = "| " + " | ".join(c) + " |"
                return "\n".join(ls), v[1], v[2]
    return None


def size_drifts(v: View) -> View | None:
    return first_drawn(
        v, lambda m: m[0].replace(f"({m[7]} × {m[8]},", f"({m[7]} × {int(m[8]) + 1},")
    )


def outside_file(v: View) -> View | None:
    d = dict(v[2].diff or {})
    d["docs/plan/05-accessibility-standard.md"] = []
    return v[0], v[1], v[2]._replace(diff=d)


def uuid_outside(v: View) -> View | None:
    old = "## 20. Summary"
    return (
        None
        if old not in v[0]
        else (v[0].replace(old, old + " (`00000000-0000-4000-8000-00000000abcd`)", 1), v[1], v[2])
    )


def plan() -> list[Mut]:
    lits: list[Mut] = [
        (m[0], False, literal(m[1], m[2], int(m[3]) if len(m) > 3 else 1)) for m in MUTATIONS
    ]
    lits += [(name, False, literal(old, new, 1, "14")) for name, old, new in MUTATIONS_14]
    return lits + [
        ("a tenth board", False, extra_board),
        ("a board theme drifts from §0", False, row_cell("06", 3, "dark (+ hc cells)")),
        (
            "a pending row among drawn ones (a mix; the drawn view)",
            True,
            row_cell("02", 4, STATUS_PENDING),
        ),
        ("a drawn Status cell loses its form (the drawn view)", True, row_cell("03", 4, "drawn")),
        ("an export's size cell drifts (the drawn view)", True, size_drifts),
        ("two same-size exports swap bytes (the drawn view)", True, swap_exports),
        ("a greyscale / deuteranopia render is missing (the drawn view)", True, render_missing),
        ("a uuid outside §0 (the drawn view)", True, uuid_outside),
        ("a file outside the pack differs (the drawn view)", True, outside_file),
    ]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def self_test(spec_path: Path) -> int:
    spec = read(spec_path)
    screens = read(SCREENS)
    before = spec_path.read_bytes()
    repo = read_repo()
    base, _ = evaluate(spec, screens, repo)
    ok = not base
    print(f"clean spec: rc {1 if base else 0} ({len(base)} problem(s))")
    for p in base:
        print(f"  {p}")
    dview, synth = drawn_view((spec, screens, repo))
    dbase, _ = evaluate(*dview)
    ok = ok and not dbase
    print(
        f"drawn view, {'synthesised in memory (§0 pending)' if synth else 'the committed state'}: rc {1 if dbase else 0}"
    )
    for p in dbase:
        print(f"  {p}")
    seen: dict[str, str] = {}
    muts = plan()
    for no, (name, on_drawn, apply) in enumerate(muts, start=1):
        start, ref = (dview, dbase) if on_drawn else ((spec, screens, repo), base)
        view = apply(start)
        if view is None:
            ok = False
            print(f"mutation {no:02d} {name}: DOES NOT APPLY (the text to mutate is gone)")
            continue
        got, _ = evaluate(*view)
        fresh = [p for p in got if p not in ref]
        rc = 1 if got else 0
        dup = [p for p in fresh if p in seen]
        caught = rc == 1 and len(fresh) == 1 and not dup
        ok = ok and caught
        flag = "" if caught else (" - DUPLICATE FAIL" if dup else " - NOT CAUGHT EXACTLY ONCE")
        print(f"mutation {no:02d} {name}: rc {rc}, {len(fresh)} new FAIL{flag}")
        for p in fresh:
            print(f"  {p}")
            seen.setdefault(p, name)
    restored, _ = evaluate(spec, screens, read_repo())
    same = spec_path.read_bytes() == before and read(SCREENS) == screens
    ok = ok and not restored and same
    print(
        f"restore: rc {1 if restored else 0}; spec and 14 byte-identical: {same}; "
        f"--self-test: {'ok' if ok else 'FAIL'} - {len(muts)} mutations in memory, "
        f"{len(seen)} distinct FAILs"
    )
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    argv = sys.argv[1:] if argv is None else argv
    spec_path = SPEC
    for flag in ("--check", "--self-test"):
        if flag in argv:
            i = argv.index(flag)
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                spec_path = Path(argv[i + 1])
    if "--self-test" in argv:
        return self_test(spec_path)
    if "--matrix" in argv:
        mx = matrix([])
        print("\n".join(matrix_lines(mx)))
        print(
            f"{mx['pairs']} pairs, {mx['gated']} gated, FAIL {mx['fail']}, {mx['repro_ok']} of {mx['repro_n']} reproductions"
        )
        return 0
    spec = read(spec_path) if spec_path.exists() else ""
    problems, out = evaluate(spec)
    if "--json" in argv:
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    else:
        mx = out["matrix"]
        print(
            f"A. tokens named {out['tokens']['named']}, missing {out['tokens']['missing']}, proposed {out['tokens']['proposed']}"
        )
        print(
            f"B. matrix: {mx['pairs']} pairs × 3 themes, {mx['gated']} gated, FAIL {mx['fail']}, "
            f"{mx['repro_ok']} of {mx['repro_n']} reproductions"
        )
        for r in mx["rows"]:
            print(
                f"   {r['id']:<4} {r['role']:<17} {r['text']:<24} {r['verdict']:<24} {r['element']}"
            )
        print(f"C. proposals {out['proposals']}")
        print(f"D. motion {out['motion']}")
        print(
            f"E. tiers {out['tiers']}; F. A-rows {out['amendments']}; L. pairs.mjs {out['registrations']}"
        )
        bd = out["boards"]
        print(
            f"G. boards {bd['boards']}, light twins {bd['light_twins']}, §0 {bd['mode']}, "
            f"exports {bd.get('exports', 0)}, scope {bd['scope']}"
        )
        print(f"H. hygiene {out['hygiene']}; I. counts {out['counts']}")
        print(f"K. drift {len(out['drift'])}")
        for p in problems:
            print(f"FAIL {p}")
        print(f"rc {1 if problems else 0}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
