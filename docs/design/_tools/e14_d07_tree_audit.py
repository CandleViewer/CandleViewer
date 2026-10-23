"""E14-D07 object-tree drawings-branch audit: every number the hi-fi spec, the boards and the PR
draft quote, computed from the repo. Standalone, offline, stdlib only (``python3 -I``).

Sections, each row labelled with its source: (1) template coverage — ``22``'s ``DrawingTool`` enum
and point counts against the spec's section 2 table, the examples rendered by the ``template()`` the
board script copies, the label budget at the shell's width x density pairings from section 3.1's
redline (one geometry source, shared with the board script), the tag-collapse rule, the
fragment-drop level per example (every fragment a substring of the accessible name), the
collision check over the 500-row distribution; (2) the tree model — D02 board 09's 20 rows, seeded
200 / 500 rows, the virtualised window at a 728 px stack per density (the sync row and the wrapped
bulk bar counted), ``aria-setsize`` per group, the keystroke bound (the filter path under the stated
strategy with the shell's keys, and with C-20; the group path, worst case), the 200-row threshold;
(3) the measured matrix — every pair the drawings rows add in dark / light / high-contrast, resolved
as ``packages/ui/tokens/tests/verify_tokens.py`` does and measured with ``contrast_ratio()`` from
``docs/design/_tools/contrast_check.py`` (imported, never re-implemented), the ``pairs.mjs`` status
per row as a text scan, the reproductions of E13-D02 §13, E13-D03 row 95, E09-D09 §11 and E30-D02;
(4) the CVD rows — ``docs/research/_tools/cvd_simulate.py``, CIE76 at a 5.0 JND, the greyscale luma
of every fill; (5) the hotkey lint — ``scripts/keymap_lint.py`` over the shipped keymap plus E13-D02
D25's PROPOSED Objects commands in memory (the file is never written) and the gate that the spec
binds no key beyond D25 and E14-D02 §5.3; (6) token bindings; (7) string gates over the committed
files and the optional PR draft (generic hygiene patterns, no host named); (8) the counts.

Usage: python3 -I docs/design/_tools/e14_d07_tree_audit.py [--json] [--check] [--draft <draft.md>]
A plain run prints every section and exits 0; ``--check`` exits 1 on drift (a gated FAIL or a failed
string gate); ``--json`` prints the counts and numbers the board check-nums consumes. Stdout is
UTF-8. Nothing else in the repo is executed: ``22``, the keymap, ``pairs.mjs``, E14-D02's audit tool
(its registry literal), the spec, the handoff and the draft are read as text.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
DESIGN = ROOT / "docs" / "design"
SPEC = DESIGN / "E14" / "E14-D07.md"
HANDOFF = DESIGN / "E14" / "E14-D07-handoff.md"
THEMES = ("dark", "light", "high-contrast")
FAILS: list[str] = []
OUT: list[str] = []


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(TOKENS / "tests"))
verify = _load(TOKENS / "tests" / "verify_tokens.py", "verify_tokens")
contrast = _load(DESIGN / "_tools" / "contrast_check.py", "contrast_check")
keymap_lint = _load(ROOT / "scripts" / "keymap_lint.py", "keymap_lint")
cvd = _load(ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py", "cvd_simulate")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def p(line: str = "") -> None:
    OUT.append(line)


def row(*cells: object) -> None:
    p("| " + " | ".join(str(c) for c in cells) + " |")


def rows(table: str) -> list[list[str]]:
    return [[c.strip() for c in ln.split("|")] for ln in table.strip().splitlines()]


def resolve_theme(name: str) -> dict[str, Any]:
    allt: dict[str, Any] = dict(verify.load(verify.PRIMITIVES))
    allt.update(verify.merged_set(verify.THEMES[name]))
    return {k: verify.resolve(v["$value"], allt) for k, v in allt.items()}


T = {n: resolve_theme(n) for n in THEMES}
C = "color."


def hx(theme: str, token: str) -> str:
    v = T[theme][token]
    if not isinstance(v, str):
        raise TypeError(f"{token} is not a colour in {theme}")
    return v.upper()


def rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def ratio(fg: str, bg: str) -> float:
    return float(contrast.contrast_ratio(rgb(fg), rgb(bg)))


def fmt(x: float) -> str:
    return f"{x:.2f}"


def table_rows(text: str, start: str, end: str) -> list[list[str]]:
    sec = text[text.index(start) : text.index(end)]
    out = [
        [c.strip() for c in s.strip("|").split("|")]
        for s in (ln.strip() for ln in sec.splitlines())
        if s.startswith("|") and not re.match(r"^\|\s*-", s)
    ]
    return out[1:]


# --- 1. the label templates (spec section 2) -----------------------------------------------------
NAME_OVERRIDE = {"fib_retracement": "Fib retracement", "fib_timezone": "Fib time zones"}
NAME_OVERRIDE["anchored_vwap"] = "Anchored VWAP"
# PROPOSED (spec section 2.3): the API-only overflow tools join a family by what they draw
OVERFLOW_FAMILY = {"brush": "annotation", "pitchfork": "fibonacci", "gann_fan": "fibonacci"}
OVERFLOW_FAMILY.update({"price_range": "analysis", "date_range": "analysis"})
SUBGROUP = {"lines": "Lines", "shapes": "Shapes", "fibonacci": "Fibonacci"}
SUBGROUP.update({"analysis": "Analysis", "annotation": "Annotations"})
FIB = ("fib_retracement", "fib_extension", "fib_timezone")
TIME_RE = re.compile(r"\b\d{2}:\d{2}\b ?")
# compact / comfortable row geometry from the spec's section 3.1 redline (E13-D02 §2; E13-D03 §2
# row 95), shared with the board script: (row height, indent step, the px before the label without
# the indent — 8 + grip 16 + 4 + tile 16 + 8, the px after it — 8 + three buttons + 2 gaps + 8)
ROW = {"compact": (24, 16, 52, 96), "comfortable": (32, 20, 52, 120)}
# the shell's width x density pairings (E13-D02 §2 line 66: 320 compact, 360 comfortable) and the
# 240 px narrow mode in either density — "360 compact" and "320 comfortable" never occur
PAIRINGS = ((320, "compact"), (360, "comfortable"), (240, "compact"), (240, "comfortable"))
LABEL_PX, AVG_EM, TICK = 12.0, 0.56, "0.5"
# the shared pill-label width rule (the board script's PILL_EM): an upper bound per glyph class
PILL_EM = {"upper": 0.84, "wideLower": 0.95, "lower": 0.56, "digit": 0.68, "thin": 0.34}
# D03 §2.2 (at f6e2a7ca): the API-only overflow tools have no glyph, so their type word is never
# dropped from the visible label (the tile would carry nothing)
GLYPHLESS = frozenset({"brush", "pitchfork", "gann_fan", "price_range", "date_range"})
# the tags (spec section 4): label -> has a glyph; a tag collapses to its glyph when the label
# beside its full form would keep less than one price (section 2.4)
TAGS = {"this pane only": True, "off-screen": True, "restored": False, "approximate": False}
TAGS.update({"not saved": True, "changed elsewhere": True})
TAG_PX, TAG_PAD, TAG_GLYPH, TAG_GAP, TAG_COLLAPSED = 11, 12, 14, 6, 20


def tool_name(tool: str) -> str:
    return NAME_OVERRIDE.get(tool, tool.replace("_", " ").capitalize())


def price(s: str) -> str:
    """Comma thousands; a whole tick prints without decimals (D02 §8.2: '64,200')."""
    neg = s.startswith("-")
    whole, _, frac = s.lstrip("-").partition(".")
    frac = frac.rstrip("0")[: len(TICK.partition(".")[2])]
    return ("-" if neg else "") + f"{int(whole):,}" + (f".{frac}" if frac else "")


def template(tool: str, rec: dict[str, Any]) -> str:
    """The row label (= the accessible name before the state words): type + anchors + label."""
    name, ts = tool_name(tool), list(rec.get("t", []))
    ps = [price(x) for x in rec.get("p", [])]
    tp = [f"{t} {pp}" for t, pp in zip(ts, ps, strict=False)]
    text = rec.get("text")
    quoted = f"'{text[:24] + ('…' if len(text) > 24 else '')}'" if text else ""
    if tool == "horizontal_line":
        core = f"{name} {ps[0]}"
    elif tool == "vertical_line":
        core = f"{name} {ts[0]}"
    elif tool == "text":
        core = f"{name} {quoted} {tp[0]}"
    elif tool == "anchored_vwap":
        bands = " ".join(f"{b}\u03c3" for b in rec.get("bands", []))  # sigma
        core = f"{name} {tp[0]}" + (f" · {bands}" if bands else "")
    elif tool == "callout":
        core = f"{name} {quoted} {tp[0]} → {tp[1]}"
    elif tool in ("long_position", "short_position"):
        core = f"{name} entry {ps[0]} · stop {ps[1]} · target {ps[2]}"
    elif tool == "parallel_channel":
        width = price(str(abs(float(rec["p"][2]) - float(rec["p"][1]))))
        core = f"{name} {tp[0]} → {tp[1]} · width {width}"
    elif tool in ("brush", "polyline"):
        core = f"{name} {ts[0]} → {ts[-1]} · {len(ts)} points"
    elif len(ts) >= 3:
        core = f"{name} {tp[0]} → {tp[1]} → {tp[2]}"
    else:
        core = f"{name} {tp[0]} → {tp[1]}"
    if rec.get("levels"):
        core += f" · {len(rec['levels'])} levels"
    return core + (f" · {rec['label']}" if rec.get("label") else "")


def pill_text_w(label: str, size: float) -> float:
    """The label box a pill needs (the board script's pillTextW, per glyph class)."""
    em = 0.0
    for ch in label:
        if ch.isupper():
            em += PILL_EM["upper"]
        elif ch in "mw":
            em += PILL_EM["wideLower"]
        elif ch.islower():
            em += PILL_EM["lower"]
        elif ch.isdigit():
            em += PILL_EM["digit"]
        elif ch in " .,:;\u00b7'\u2019|-":
            em += PILL_EM["thin"]
        else:
            em += 1.0
    return em * size


PRICE_PX = pill_text_w("64,120.5", LABEL_PX)  # one price: the floor the label keeps beside a tag


def tag_px(label: str, collapsed: bool = False) -> int:
    """The tag slot's width incl. its 6 px gap: the pill rule at 11 px, or the glyph-only form."""
    if collapsed:
        return TAG_COLLAPSED + TAG_GAP
    return round(pill_text_w(label, TAG_PX) + TAG_PAD + (TAG_GLYPH if TAGS[label] else 0)) + TAG_GAP


def fragments(tool: str, label: str, user_label: str | None) -> list[str]:
    """The visible label's fragment-drop ladder (spec section 2.4; E30-D02 D3's precedent): (1) the
    type word — the tile glyph and the sub-group carry it, never for a glyph-less tool; (2) the user
    label; (3) the end ellipsis. Every fragment is a contiguous part of the accessible name (WCAG
    2.5.3), which the gate asserts."""
    l0 = label[: -len(f" · {user_label}")] if user_label else label
    name = tool_name(tool)
    l1 = label if tool in GLYPHLESS else label[len(name) + 1 :]
    l2 = l0 if tool in GLYPHLESS else l0[len(name) + 1 :]
    out = [label, l1, l2]
    if any(f not in label for f in out):
        FAILS.append(f"section 2.4: a fragment of `{tool}` is not part of its accessible name")
    return out


def budget_px(
    width: int, density: str, lock: bool, tag: str | None, collapsed: bool = False
) -> int:
    _, indent, left, right = ROW[density]
    tag_w = tag_px(tag, collapsed) if tag else 0
    return width - left - 2 * indent - right - (16 if lock else 0) - tag_w


def chars(px: int) -> int:
    return max(0, int(px // (LABEL_PX * AVG_EM)))


def tag_collapses(width: int, density: str, tag: str) -> bool:
    """PROPOSED (spec section 2.4): a tag with a glyph keeps its words only while the label beside
    it keeps one price; otherwise it collapses to its glyph (the words stay in the name and the
    tooltip). A tag without a glyph never collapses — its words are its only carrier."""
    return TAGS[tag] and budget_px(width, density, False, tag) < PRICE_PX


# One example per tool at D02's numbers (13:40 / 14:05 / 14:10 / 13:52 / 14:30 / 12:00; 64,120.5 /
# 64,200 / 64,210.5 / 64,000 / 63,900 / 64,420 / 64,010 / 64,400); the spec's section 2 examples
# must equal template() over these records (gated). Form: tool | times | prices | extra
EXAMPLES_TXT = """
trendline | 13:40 14:05 | 63900 64420 | label=weekly support
horizontal_line | 13:40 | 64120.5 | label=key level
vertical_line | 14:10 | 64000 |
ray | 13:52 14:10 | 64000 64210.5 |
extended_line | 13:40 14:30 | 63900 64400 |
parallel_channel | 13:40 14:05 14:05 | 63900 64420 64300 |
rectangle | 13:40 14:05 | 64000 64200 |
ellipse | 13:52 14:30 | 64000 64210.5 |
triangle | 13:40 14:05 14:30 | 63900 64420 64300 |
fib_retracement | 13:40 14:05 | 63900 64420 | levels=7
fib_extension | 13:40 14:05 14:30 | 63900 64420 64300 | levels=5
fib_timezone | 13:40 14:05 | 63900 64420 | levels=5
pitchfork | 12:00 13:40 14:05 | 64010 63900 64420 |
gann_fan | 13:40 14:30 | 63900 64400 |
text | 14:30 | 64200 | text=FOMC
arrow | 13:52 14:10 | 64000 64210.5 |
callout | 14:05 14:30 | 64120 64200 | text=retest
measure | 13:40 14:05 | 63900 64420 |
long_position | 13:40 13:40 13:40 | 64000 63900 64400 |
short_position | 14:05 14:05 14:05 | 64200 64300 64000 |
price_range | 13:40 14:05 | 63900 64420 |
date_range | 13:40 14:30 | 64000 64000 |
brush | 48 | 64000 |
polyline | 13:40 13:52 14:05 14:10 14:20 14:30 | 64000 |
anchored_vwap | 12:00 | 64010 | bands=1 2
"""


def example_rec(t: str, p_: str, extra: str) -> dict[str, Any]:
    ts = [f"13:{40 + i % 20:02d}" for i in range(48)] if t == "48" else t.split()
    ps = p_.split()
    rec: dict[str, Any] = {"t": ts, "p": ps * len(ts) if len(ps) == 1 else ps}
    if extra:
        k, _, v = extra.partition("=")
        rec[k] = v.split() if k == "bands" else (list(range(int(v))) if k == "levels" else v)
    return rec


EXAMPLES = {r[0]: example_rec(r[1], r[2], r[3]) for r in rows(EXAMPLES_TXT)}


def api_tools() -> tuple[list[str], dict[str, str]]:
    """The 25 ``DrawingTool`` values and the point-count class per tool, from ``22`` as text."""
    text = read(ROOT / "docs" / "plan" / "22-api-openapi.yaml")
    block = text[text.index("    DrawingTool:") : text.index("    DrawingPoint:")]
    arity: dict[str, str] = {}
    for n, names in re.findall(r"exactly (\d): ([^\n]+(?:\n\s+`[^\n]+)*)", block):
        arity.update({t: n for t in re.findall(r"`(\w+)`", names)})
    arity.update({t: "n" for t in re.findall(r"2\.\.\d+: `(\w+)`", block)})
    return re.findall(r"^\s+- (\w+)$", block, re.MULTILINE), arity


def d02_groups() -> dict[str, str]:
    """D02 §2.2's rail group per tool, read from E14-D02's audit tool's registry literal."""
    text = read(DESIGN / "_tools" / "e14_d02_interaction_audit.py")
    start = text.index('REG_TXT = """') + 12
    reg = rows(text[start : text.index('"""', start)])
    return {r[2]: r[4] for r in reg if len(r) >= 5 and r[2] not in ("-", "")}


GROUPS = d02_groups()


def family(tool: str) -> str:
    return OVERFLOW_FAMILY.get(tool, GROUPS.get(tool, "lines"))


def check_spec_templates(
    spec: str, enum: list[str], arity: dict[str, str], ex: dict[str, str]
) -> int:
    srows = {r[1].strip("`"): r for r in table_rows(spec, "## 2.", "## 3.") if len(r) >= 6}
    covered = 0
    for t in enum:
        r = srows.get(t)
        if r is None:
            FAILS.append(f"section 2: no template row for `{t}`")
            continue
        covered += 1
        if r[4] != arity[t]:
            FAILS.append(f"section 2: `{t}` arity {r[4]} differs from `22` {arity[t]}")
        if r[3].strip('`"') != ex[t]:
            FAILS.append(f"section 2: `{t}` example differs from template(): {r[3]!r}")
        if ("levels" in r[5]) != (t in FIB) or ("bands" in r[5]) != (t == "anchored_vwap"):
            FAILS.append(f"section 2: `{t}` levels / bands extra")
        if ("text" in r[5]) != (t in ("text", "callout")):
            FAILS.append(f"section 2: `{t}` text extra")
    FAILS.extend(f"section 2: `{t}` is not a `DrawingTool` value" for t in srows if t not in enum)
    return covered


def templates_report(spec: str | None) -> dict[str, Any]:
    enum, arity = api_tools()
    p("## 1. Template coverage (spec section 2 vs `22` `DrawingTool`; the examples rendered)")
    p()
    row("tool", "sub-group", "arity (`22`)", "example (template() at D02's numbers)")
    row("---", "---", "---", "---")
    ex = {t: template(t, EXAMPLES[t]) for t in enum}
    for t in enum:
        row(f"`{t}`", SUBGROUP[family(t)], arity[t], ex[t])
    cls = " / ".join(str(sum(a == k for a in arity.values())) for k in ("1", "2", "3", "n"))
    p()
    p(f"Enum values: {len(enum)}; arity classes 1 / 2 / 3 / n: {cls}.")
    covered = check_spec_templates(spec, enum, arity, ex) if spec is not None else 0
    if spec is not None:
        p(f"Spec section 2: {covered} / {len(enum)} tools covered.")
    p()
    p(f"Label budget (`type.ui.label` {LABEL_PX:g} px at Inter's average advance {AVG_EM} em, an")
    p("estimate; the accessible name is never truncated) from the section 3.1 redline at the")
    p("shell's pairings (E13-D02 §2 line 66): px → characters before the ellipsis")
    p()
    row(
        "drawer width",
        "density",
        "plain row",
        "with the lock glyph",
        "with the 'this pane only' tag",
    )
    row("---", "---", "---", "---", "---")
    budgets: dict[str, list[int]] = {}
    for w, d in PAIRINGS:
        a, b = budget_px(w, d, False, None), budget_px(w, d, True, None)
        col = tag_collapses(w, d, "this pane only")
        c = budget_px(w, d, False, "this pane only", col)
        budgets[f"{w}/{d}"] = [a, chars(a), chars(b), chars(c) if w > 240 else -1]
        tagcell = "the tag moves into the tooltip (D20)" if w == 240 else f"{c} px → {chars(c)}"
        row(
            w,
            d,
            f"{a} px → {chars(a)}",
            f"{b} px → {chars(b)}",
            tagcell + (" (glyph only)" if col and w > 240 else ""),
        )
    p()
    p(f"Tag collapse (PROPOSED, section 2.4; the floor is one price, {PRICE_PX:.0f} px): a tag")
    p("whose full form would leave less than that collapses to its glyph (its words stay in the")
    p("name)")
    p()
    row("tag", "full px", *[f"{w} {d}" for w, d in PAIRINGS[:2]])
    row("---", "---", "---", "---")
    collapse: dict[str, list[bool]] = {}
    for tg, has_glyph in TAGS.items():
        collapse[tg] = [tag_collapses(w, d, tg) for w, d in PAIRINGS[:2]]
        kind = "" if has_glyph else "glyph-less"
        row(
            tg,
            tag_px(tg) - TAG_GAP,
            *[
                ("collapses to its glyph" if c else "keeps its words")
                + (f" ({kind})" if kind else "")
                for c in collapse[tg]
            ],
        )
    p()
    p("Fragment-drop level per example (plain row): 0 = full label, 1 = the type word dropped")
    p("(never for a glyph-less tool), 2 = the user label dropped too, 3 = ellipsis")
    p()
    row("tool", *[f"{w} {d}" for w, d in PAIRINGS])
    row("---", *["---"] * len(PAIRINGS))
    levels: dict[str, list[int]] = {}
    for t in enum:
        frags = fragments(t, ex[t], EXAMPLES[t].get("label"))
        fit = [chars(budget_px(w, d, False, None)) for w, d in PAIRINGS]
        levels[t] = [next((i for i, f in enumerate(frags) if len(f) <= n), 3) for n in fit]
        row(f"`{t}`", *levels[t])
    hl = fragments(
        "horizontal_line", ex["horizontal_line"], EXAMPLES["horizontal_line"].get("label")
    )
    keeps = [len(hl[2]) <= chars(budget_px(w, d, False, None)) for w, d in PAIRINGS[:3]]
    p()
    p(f"A horizontal line keeps its full price ({hl[2]!r}) at 320 compact, 360 comfortable and")
    p(f"240 compact: {keeps}.")
    if not all(keeps):
        FAILS.append("section 2.4: a horizontal line loses its price at a real width")
    fam = {t: SUBGROUP[family(t)] for t in enum}
    out = {"enum": enum, "arity": arity, "examples": ex, "covered": covered, "family": fam}
    return {**out, "budgets": budgets, "levels": levels, "tag_collapse": collapse}


# --- 2. the tree model (spec section 5) ----------------------------------------------------------
# D02 board 09's 20 rows (the tools per sub-group, z-order top-most first)
DIST20 = {
    "lines": "horizontal_line horizontal_line trendline ray extended_line vertical_line",
    "shapes": "rectangle ellipse parallel_channel",
    "fibonacci": "fib_retracement fib_extension",
    "analysis": "anchored_vwap measure long_position short_position",
    "annotation": "text callout arrow polyline",
}
DIST20["lines"] += " horizontal_line"
# the seeded distributions' tool weights (a literal; printed, drawn, never typed)
WEIGHTS_TXT = (
    "horizontal_line 34, trendline 14, ray 5, extended_line 4, vertical_line 5, rectangle 8, "
    "ellipse 3, triangle 1, parallel_channel 2, fib_retracement 4, fib_extension 1, "
    "fib_timezone 1, anchored_vwap 3, measure 2, long_position 2, short_position 2, text 4, "
    "callout 2, arrow 2, polyline 1"
)
WEIGHTS = [(w.split()[0], int(w.split()[1])) for w in WEIGHTS_TXT.split(", ")]
THRESHOLD, STACK_PX = 200, 728  # E13-D02 G-1's "above 200 items" (Q13); the 1280x800 pane stack
TIMES = [f"{h:02d}:{m:02d}" for h in range(9, 16) for m in range(0, 60, 5)]
LCG = (9301, 49297, 233280)


def seeded(n: int, seed: int) -> list[dict[str, Any]]:
    """A deterministic distribution of n drawings (the LCG the board script also uses)."""
    s, total, out = seed, sum(w for _, w in WEIGHTS), []

    def nxt() -> int:
        nonlocal s
        s = (s * LCG[0] + LCG[1]) % LCG[2]
        return s

    for i in range(n):
        pick, acc, tool = (nxt() / LCG[2]) * total, 0, WEIGHTS[-1][0]
        for name, w in WEIGHTS:
            acc += w
            if pick < acc:
                tool = name
                break
        t0 = TIMES[nxt() % len(TIMES)]
        p0 = 61000 + (nxt() % 12000) * 0.5
        t1 = TIMES[min(len(TIMES) - 1, TIMES.index(t0) + 1 + nxt() % 12)]
        p1 = p0 + ((nxt() % 800) - 400) * 0.5
        rec: dict[str, Any] = {"tool": tool, "z": n - i, "t": [t0, t1, t1]}
        rec["p"] = [str(p0), str(p1), str((p0 + p1) / 2)]
        if tool in ("text", "callout"):
            rec["text"] = ("FOMC", "CPI", "open", "retest", "NY close")[i % 5]
        if tool in FIB:
            rec["levels"] = [0, 0.382, 0.5, 0.618, 1]
        if tool == "anchored_vwap":
            rec["bands"] = [1, 2]
        if tool == "polyline":
            rec["t"] = [t0, t1, TIMES[min(len(TIMES) - 1, TIMES.index(t1) + 2)]]
        out.append(rec)
    return out


# the filter path's fixed keys with the shell's keys (E13-D02 D25, §11.1): Shift+Tab to the filter
# 1, Tab back into the tree 1 (the roving stop is the item focus left — the first group row), ↓ x2
# past Overlays and Sub-panes to Drawings, ↓ x7 past the sync row (the group's first child, spec
# section 6.1) and the five sub-group rows to the first match (worst: in the last sub-group), Enter
# 1; with C-20 (↓ / Enter from the filter focuses it) 3
FIXED_SHELL, FIXED_C20 = 1 + 1 + 2 + 7 + 1, 1 + 1 + 1
TIME_ONLY = frozenset({"vertical_line", "brush", "polyline"})


def match_key(s: str) -> str:
    """The separator-insensitive, case-insensitive match (PROPOSED, spec section 5.3)."""
    return s.lower().replace(",", "").replace(" ", "")


def typed_for(rec: dict[str, Any], with_type_word: bool) -> str:
    """What the stated strategy types: the first price of a priced tool, or the time of a time-only
    tool — preceded by the type word's last word when the strategy says so (a bare minute is shared
    by every object anchored at that bar)."""
    if rec["tool"] in TIME_ONLY:
        word = tool_name(rec["tool"]).split()[-1] + " " if with_type_word else ""
        return str(word + rec["t"][0])
    return price(rec["p"][0])


def filter_bound(recs: list[dict[str, Any]], with_type_word: bool) -> dict[str, Any]:
    """The filter path's worst case under the stated strategy: per object, the typed characters
    (separators dropped) + the extra ↓ for the other objects whose label matches the same text;
    the maximum over the seeded rows. Every typed text is a real part of its label (gated)."""
    labels = [template(r["tool"], r) for r in recs]
    keys = [match_key(s) for s in labels]
    worst: tuple[int, int, int, str] = (0, 0, 0, "")
    for r, lab, key in zip(recs, labels, keys, strict=True):
        typed = match_key(typed_for(r, with_type_word))
        if typed not in key:
            FAILS.append(f"section 5.3: the typed text {typed!r} is not in its label {lab!r}")
        extra = sum(1 for k in keys if typed in k) - 1
        if len(typed) + extra > worst[0]:
            worst = (len(typed) + extra, len(typed), extra, lab)
    cost, typed_n, extra_n, lab = worst
    return {"cost": cost, "typed": typed_n, "extra": extra_n, "label": lab}


def bar_rows(width: int) -> int:
    """The bulk bar's rows at a drawer width (the board script's wrap, estimated with the pill
    rule at 11 px): the count box 70, the pills with 14 px padding and 4 px gaps, the separator
    between two 12 px gaps, the trash glyph 14 before Delete, the 12 px gap before Clear selection.
    """
    items = [("Hide", 0), ("Show", 0), ("Lock", 0), ("Unlock", 0), ("|", 0), ("Delete", 14)]
    items.append(("Clear selection", 0))
    avail, rows = width - 20, 1
    x: float = 70.0
    for label, glyph in items:
        need = 25 if label == "|" else pill_text_w(label, 11) + 14 + glyph
        if x + need > avail:
            x, rows = 0, rows + 1
        x += need + (12 if label == "Delete" else 0 if label == "|" else 4)
    return rows


def window(density: str, bulk: bool) -> tuple[int, int]:
    """(fixed px, visible rows) of one expanded sub-group at the stack: the drawer header and the
    filter at the row height, the footer 40 / 48, the four group rows, the sync row, the five
    sub-group rows, the bulk bar 32 / 40 per wrapped row when shown (bar_rows at the pairing's
    width); the other three groups collapsed."""
    rh = ROW[density][0]
    width = 320 if density == "compact" else 360
    bar = (32 if rh == 24 else 40) * bar_rows(width) if bulk else 0
    fixed = 2 * rh + (40 if rh == 24 else 48) + 10 * rh + bar
    return fixed, (STACK_PX - fixed) // rh


def dist(rs: list[dict[str, Any]]) -> dict[str, int]:
    d = dict.fromkeys(SUBGROUP, 0)
    for r in rs:
        d[family(r["tool"])] += 1
    return d


def tree_report() -> dict[str, Any]:
    p()
    p("## 2. The tree model (spec section 5): rows per sub-group, the window, the keystroke bound")
    p()
    d20 = {g: len(v.split()) for g, v in DIST20.items()}
    r500 = seeded(500, 7)
    d200, d500 = dist(seeded(200, 7)), dist(r500)
    row("rows", *SUBGROUP.values(), "total", "sub-groups collapsed by default")
    row(*["---"] * (len(SUBGROUP) + 3))
    for n, d in ((20, d20), (200, d200), (500, d500)):
        row(n, *d.values(), sum(d.values()), "yes" if n > THRESHOLD else "no")
    labels = [template(r["tool"], r) for r in r500]
    dup = len(labels) - len(set(labels))
    shared = sum(1 for s in labels if labels.count(s) > 1)
    win = {d_: [window(d_, False), window(d_, True)] for d_ in ROW}
    fb, bare = filter_bound(r500, True), filter_bound(r500, False)
    above = 1 + 3 + 1 + 2 + 2  # Overlays (3 items) and Sub-panes (2 panes, 2 indicators) expanded
    biggest = max(d500.values())
    worst_group = 1 + above + 1 + 1 + len(SUBGROUP) + 1 + (biggest - 1)  # + the sync row
    lines = [r for r in r500 if family(r["tool"]) == "lines"]
    pos = next(i for i, r in enumerate(lines) if r["tool"] == "horizontal_line") + 1
    example = template(lines[pos - 1]["tool"], lines[pos - 1])
    p()
    p(f"Collisions over the 500 labels (full anchors, no user label): {dup} — the ordinal '(2)'")
    p(f"triggers {dup} times; {shared} labels share their text with another.")
    for d_, (plain, bulk) in win.items():
        wd = 320 if d_ == "compact" else 360
        p(f"Visible window ({d_}, {STACK_PX} px stack; the sync row counted): fixed {plain[0]} px")
        rows_ = f"with the bulk bar on {bar_rows(wd)} rows fixed {bulk[0]} px → {bulk[1]}."
        p(f"→ {plain[1]} rows; {rows_}")
    cost, bnd, c20 = fb["cost"], FIXED_SHELL + fb["cost"], FIXED_C20 + fb["cost"]
    p("Keystroke bound, filter path at 500 (the stated strategy — the first price, or the type")
    p(f"word + the time of a time-only tool; separator-insensitive): typed + extra ↓ = {cost}")
    p(f"at worst ({fb['typed']} characters + {fb['extra']} ↓ for {fb['label']!r}); with the")
    p(f"shell's {FIXED_SHELL} fixed keys (Shift+Tab, Tab, ↓ x2 to Drawings, ↓ x7 past the sync")
    p(f"row and the five sub-group rows to the first match, Enter) = {bnd}; with C-20")
    p(f"({FIXED_C20} fixed keys) {c20}.")
    bare_sum = f"{bare['typed']} + {bare['extra']}"
    p(f"A bare minute typed for a time-only tool: {bare['cost']} ({bare_sum}")
    p(f"↓ for {bare['label']!r}) → {FIXED_SHELL + bare['cost']} — why the strategy names the type")
    p("word.")
    p(f"The group path, worst at 500: Tab 1 + ↓ x{above} to Drawings + → 1 + ↓ past the sync row")
    p(f"1 + ↓ x{len(SUBGROUP)} to the sub-group + → 1 + ↓ x{biggest - 1} inside it")
    p(f"= {worst_group}.")
    setsize = {SUBGROUP[g]: d500[g] for g in SUBGROUP}
    p(f"`aria-setsize` per sub-group at 500: {setsize}; the first horizontal line in Lines:")
    p(f"item {pos} of {d500['lines']} — {example}.")
    bounds = {"typed": fb["typed"], "extra": fb["extra"], "cost": fb["cost"]}
    bounds.update({"bound": FIXED_SHELL + fb["cost"], "bound_c20": FIXED_C20 + fb["cost"]})
    bounds.update({"bare_minute": FIXED_SHELL + bare["cost"], "group_worst": worst_group})
    out = {"dist20": d20, "dist200": d200, "dist500": d500, "collisions": dup, "shared": shared}
    out.update({"window": win, "threshold": THRESHOLD, "bounds": bounds, "setsize500": setsize})
    out["bar_rows"] = {"320": bar_rows(320), "360": bar_rows(360)}
    return {**out, "example": [pos, d500["lines"], example]}


# --- 3. the measured matrix (spec section 10.1) ---------------------------------------------------
# fg | bg | role | element — roles: text 4.5, non-text 3.0, decorative and rejected (reported)
PAIRS = rows("""
text.primary | surface.overlay | text | row label, default; the drawer is overlay (E13-D02 §13)
text.primary | surface.hover | text | row label hovered; sub-group header; bulk bar (E13-D02 §13)
text.primary | surface.selected | text | row label selected; the check glyph (E13-D02 §13)
text.tertiary | surface.overlay | text | hidden row label (E13-D03 row 95)
text.tertiary | surface.hover | text | hidden row label, hovered
text.secondary | surface.selected | text | hidden-and-selected label (E13-D03 row 95 reproduced)
text.tertiary | surface.selected | rejected | REJECTED: text.tertiary on the selected fill (E13-D02)
text.secondary | surface.hover | text | neutral tag text (this pane only, off-screen, restored)
text.primary | status.warning.subtle | text | warning tag text (not saved, changed elsewhere)
status.warning.strong | status.warning.subtle | non-text | warning tag glyph on its fill
text.secondary | surface.overlay | text | the sync row; the T2 notice; a locked item's second line
text.primary | surface.raised | text | toast text (type.ui.label, E13-D03 row 101)
text.primary | action.secondary.default | text | CMP-001 secondary: the bar, the confirms, the Undo
status.danger.default | surface.hover | rejected | REJECTED: the Delete word in danger.default ink
text.inverse | status.danger.default | rejected | REJECTED: a red button face (inverse on danger)
text.tertiary | surface.raised | text | T2 label and lock glyph on the control fill (E09-D09 §11)
text.disabled | surface.raised | rejected | REJECTED: text.disabled on the control fill (E09-D09)
text.secondary | surface.canvas | non-text | type glyph on its 16 x 10 canvas tile (E13-D03 row 95)
text.tertiary | surface.canvas | non-text | type glyph, hidden row
text.secondary | surface.overlay | non-text | lock glyph after the label; eye / lock / menu; grip
text.secondary | surface.selected | non-text | eye / lock / menu glyphs on a selected row
status.danger.strong | action.secondary.default | non-text | trash glyph on the secondary face
status.danger.strong | surface.overlay | non-text | danger glyph in the row menu (E13-D02 §13)
text.tertiary | surface.selected | non-text | selected outline 1 px vs the selected fill (E13-D02)
text.tertiary | surface.hover | non-text | bulk bar edge 1 px vs the bar fill (E13-D02 §13)
focus.ring | surface.overlay | non-text | focus ring on the drawer (E13-D02 §13: 6.15 at its base)
focus.ring | surface.hover | non-text | focus ring on a hovered row
focus.ring | surface.selected | non-text | focus ring on a selected row (E13-D02 §13: 4.72)
focus.ring | surface.raised | non-text | focus ring on a T2 control and the toast (E30-D02 361)
border.default | surface.overlay | decorative | decorative: the T2 control's and the tag's hairline
surface.raised | surface.overlay | decorative | decorative: the T2 control fill vs the drawer
surface.selected | surface.overlay | decorative | decorative: the selection fill; the restore flash
surface.hover | surface.overlay | decorative | decorative: the hover fill and the neutral tag fill
surface.canvas | surface.overlay | decorative | decorative: the canvas tile vs the drawer
status.warning.subtle | surface.overlay | decorative | decorative: the warning tag fill vs drawer
""")
BAR = {"text": 4.5, "non-text": 3.0}
THR = {"text": "THRESHOLD.TEXT", "non-text": "THRESHOLD.NON_TEXT"}


def verdict(role: str, vals: list[float]) -> tuple[str, bool]:
    if role in BAR:
        bad = [t for t, v in zip(THEMES, vals, strict=True) if v < BAR[role]]
        return ("PASS" if not bad else "FAIL: " + ", ".join(bad)), bool(bad)
    if role == "rejected":
        bad = [t for t, v in zip(THEMES, vals, strict=True) if v < 4.5]
        return ("rejected by design; would FAIL: " + ", ".join(bad)) if bad else "rejected", False
    return "decorative (not gated)", False


def matrix_report() -> dict[str, Any]:
    p()
    p("## 3. The measured matrix (unrounded compare; the bar per role; dark / light / hc)")
    p()
    row("element", "fg", "bg", "role", "dark", "light", "hc", "verdict", "pairs.mjs")
    row(*["---"] * 9)
    pairs_mjs = read(ROOT / "tools" / "contrast" / "pairs.mjs")
    reg = set(re.findall(r'fg:\s*"([^"]+)",\s*bg:\s*"([^"]+)"', pairs_mjs))
    mx = dict.fromkeys(("rows", "gated", "fail", "registered"), 0)
    proposed: dict[tuple[str, str], str] = {}
    cells: list[list[str]] = []
    for fg, bg, role, element in PAIRS:
        vals = [ratio(hx(t, C + fg), hx(t, C + bg)) for t in THEMES]
        v, bad = verdict(role, vals)
        gated = role in BAR
        status = "registered" if (C + fg, C + bg) in reg else ("PROPOSED" if gated else "-")
        if status == "PROPOSED" and proposed.get((fg, bg)) != "text":
            proposed[(fg, bg)] = role
        for k, inc in (
            ("rows", 1),
            ("gated", gated),
            ("fail", bad),
            ("registered", status[0] == "r"),
        ):
            mx[k] += int(inc)
        if bad:
            FAILS.append(f"matrix: {element} — {v}")
        cells.append([element, f"`{C}{fg}`", f"`{C}{bg}`", role, *map(fmt, vals), v, status])
        row(*cells[-1])
    mx["proposed"] = len(proposed)
    lines = [
        f'{{ fg: "{C}{a}", bg: "{C}{b}", threshold: {THR[r]} }},'
        for (a, b), r in sorted(proposed.items())
    ]
    p()
    p(f"Matrix: {mx['rows']} rows, {mx['gated']} gated, FAIL {mx['fail']}, {mx['registered']}")
    p(f"registered in pairs.mjs, {mx['proposed']} PROPOSED pairs (copy-ready for E13-D04 / E05):")
    p()
    OUT.extend("    " + ln for ln in lines)
    hc = verify.load("semantic-hc.tokens.json")
    no_hc = sorted({C + x for fg, bg, _, _ in PAIRS for x in (fg, bg)} - set(hc))
    p()
    p(f"No high-contrast override (the dark value stands under hc): {', '.join(no_hc)}.")
    return {"counts": mx, "proposed": lines, "no_hc": no_hc, "rows": cells}


# --- 4. the CVD rows (spec section 10.3) ---------------------------------------------------------
DEFICIENCIES, JND = ("protanopia", "deuteranopia", "tritanopia"), 5.0
CVD_PAIRS = rows("""
status.warning.strong | status.danger.strong | the tag glyph vs the trash glyph (both amber tokens)
status.info.default | status.warning.default | status.info.default vs status.warning.default
status.info.default | status.danger.default | status.info.default vs status.danger.default
status.warning.default | status.danger.default | status.warning.default vs status.danger.default
status.danger.strong | text.secondary | the trash glyph vs the words beside it
status.warning.subtle | surface.overlay | the warning tag fill vs the drawer
status.warning.subtle | surface.hover | the warning tag fill vs the neutral tag fill
text.link | text.primary | the toast's Undo link vs the toast text
surface.selected | surface.hover | the selected fill vs the hover fill
surface.selected | surface.overlay | the selected fill vs the drawer
surface.hover | surface.overlay | the hover fill vs the drawer
""")
FILLS = ("surface.overlay", "surface.hover", "surface.selected", "surface.raised", "surface.canvas")


def luma_hex(h: str) -> str:
    r, g, b = rgb(h)
    y = round(0.299 * r + 0.587 * g + 0.114 * b)
    return f"#{y:02X}{y:02X}{y:02X}"


def cvd_report() -> dict[str, Any]:
    p()
    p(f"## 4. CVD rows (CIE76 under each dichromacy; JND {JND:g}) and the greyscale luma of fills")
    p()
    row("pair", "theme", "normal", *DEFICIENCIES, "under the JND")
    row(*["---"] * (4 + len(DEFICIENCIES)))
    n, collapses = 0, []
    for a, b, label in CVD_PAIRS:
        for t in THEMES:
            ha, hb = hx(t, C + a), hx(t, C + b)
            vals = [cvd.delta_e76(ha, hb)]
            vals += [cvd.delta_e76(cvd.simulate(ha, d), cvd.simulate(hb, d)) for d in DEFICIENCIES]
            under = [d for d, v in zip(("normal", *DEFICIENCIES), vals, strict=True) if v < JND]
            n += 1
            if under:
                collapses.append(f"{label} ({t}): {', '.join(under)}")
            row(label, t, *map(fmt, vals), ", ".join(under) or "-")
    p()
    p(f"CVD rows: {n}; pairs under the JND: {len(collapses)} — every marker, state and action is")
    p("carried by text + glyph, so no pair above is relied on alone.")
    OUT.extend("- " + c for c in collapses)
    p()
    row("fill", *THEMES, "Rec. 601 luma (dark)")
    row(*["---"] * (len(THEMES) + 2))
    for f in (*FILLS, "status.warning.subtle"):
        row(f"`{C}{f}`", *[hx(t, C + f) for t in THEMES], luma_hex(hx("dark", C + f)))
    return {"rows": n, "collapses": collapses}


# --- 5. the hotkey lint (E13-D02 D25 reproduced; the spec adds no key) ---------------------------
# E13-D02 D25's PROPOSED Objects-context registrations (OQ-G), never written to the file:
# id | label | binding | declared shadows | destructive | validWhen
OBJECTS_TXT = """
objects.toggle_visibility | Toggle visibility | Space | dom.recentre replay.play_pause | no | always
objects.toggle_selection | Toggle selection | Ctrl+Space | | no | always
objects.select_all | Select the focused group | Ctrl+A | rules.select_all | no | always
objects.delete | Remove | Del | chart.delete_drawing rules.delete | yes | object selected
objects.rename | Rename | F2 | rules.rename | no | always
objects.move_up | Move up | Alt+↑ | rules.move_up | no | always
objects.move_down | Move down | Alt+↓ | rules.move_down | no | always
"""
RATIONALE = "contexts are never co-active"
OBJECTS: list[dict[str, Any]] = [
    {
        "id": r[0],
        "label": r[1],
        "context": "Objects",
        "defaultBinding": r[2],
        "validWhen": r[5],
        "destructive": r[4] == "yes",
        "visibleControl": True,
        "shadows": [{"command": s, "rationale": RATIONALE} for s in r[3].split()],
    }
    for r in rows(OBJECTS_TXT)
]
# D25's rows and D02 §5.3's (`Del`, `Backspace`, `Ctrl+Z`, `Ctrl+Y`), spelled as the spec draws them
ALLOWED_TXT = (
    "↑ ↓ ← → Home End type-ahead Enter Space Ctrl+Space Shift+↑ Shift+↓ Shift+Space Ctrl+A Del "
    "Backspace F2 Alt+↑ Alt+↓ Shift+F10 Menu Ctrl+Z Ctrl+Y Esc Tab Shift+Tab"
)
ALLOWED_KEYS = frozenset(ALLOWED_TXT.split())


def spec_keys(text: str) -> set[str]:
    """Every key the spec's section 9.1 key table binds (the first column's code spans)."""
    keys: set[str] = set()
    for r in table_rows(text, "### 9.1", "### 9.2"):
        for k in re.findall(r"`([^`]+)`", r[0]):
            keys.update(x.strip() for x in k.split(" / "))
    return keys


def lint_report(spec: str | None) -> dict[str, Any]:
    p()
    p("## 5. Hotkey lint (`scripts/keymap_lint.py`): the shipped keymap, then D25's Objects set")
    p()
    km = json.loads(read(ROOT / "apps" / "web" / "src" / "keymap" / "keymap.json"))
    base = keymap_lint.lint_keymap(km)
    verdict_ = "OK" if not base else "ERRORS " + "; ".join(base)
    p(f"- shipped keymap: {verdict_} ({len(km['commands'])} commands)")
    objs = keymap_lint.lint_keymap(dict(km, commands=list(km["commands"]) + OBJECTS))
    caveat = any("unknown context" in e for e in objs)
    p(
        f"- plus D25's {len(OBJECTS)} Objects commands: {len(objs)} finding(s)"
        + "; ".join(["", *objs])
    )
    if caveat:
        p("  D25's OQ-G caveat, verbatim: the lint knows no Objects context yet; E13-S01 registers")
        p("  the context with the bindings and their shadows; every finding above is that one gap.")
    extra: list[str] = []
    if spec is not None:
        keys = spec_keys(spec)
        extra = sorted(keys - ALLOWED_KEYS)
        FAILS.extend(f"section 9.1 binds a key outside D25 / D02 §5.3: `{k}`" for k in extra)
        p(f"- the spec's key table: {len(keys)} keys, {len(extra)} outside D25 and D02 §5.3.")
    out = {"baseline": len(km["commands"]), "baseline_errors": len(base), "objects": len(OBJECTS)}
    return {
        **out,
        "objects_findings": len(objs),
        "objects_context_caveat": caveat,
        "extra_keys": extra,
    }


# --- 6. token bindings; 7. string gates; 8. counts -----------------------------------------------
TOKEN_RE = re.compile(
    r"`((?:color|space|size|radius|border|type|elevation|opacity|motion)\.[A-Za-z0-9.\-]+)`"
)
PROPOSED_FAMILY = re.compile(r"^color\.(chip|sync)\.")
HYGIENE = {
    "a local path": re.compile(r"/(?:home|Users)/[^/\s]+/"),
    "a Penpot host": re.compile(r"penpot\.[a-z0-9-]+\.[a-z]{2,}", re.IGNORECASE),
    "pageLink": re.compile(r"pageLink"),
    "a workspace url or id": re.compile(r"team[-_]id=|file[-_]id=|#/work[s]pace"),
    "a closing keyword before an issue ref": re.compile(
        r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b\s*:?\s*#\d+", re.IGNORECASE
    ),
    "SET-ME / TODO / TBD": re.compile(r"\bSET-ME\b|\bTODO\b|\bTBD\b"),
    "same as dark": re.compile(r"same as dark", re.IGNORECASE),
}
TRADE_WORDS = re.compile(r"\b(Buy|Sell|Place|Order)\b")


def bindings_report(spec: str, handoff: str) -> dict[str, Any]:
    p()
    p("## 6. Token bindings (every name the spec and the handoff bind)")
    p()
    both = spec + "\n" + handoff
    names = sorted({n for n in TOKEN_RE.findall(both) if not n.endswith((".*", "."))})
    missing = [n for n in names if n not in T["dark"]]
    for n in missing:
        where = [ln for ln in both.splitlines() if f"`{n}`" in ln]
        if not PROPOSED_FAMILY.match(n) or not all("G-" in ln and "PROPOSED" in ln for ln in where):
            FAILS.append(f"binding `{n}` is MISSING and not a PROPOSED name in a G-row")
    p(f"- {len(names)} names bound; MISSING (PROPOSED in G-rows): {', '.join(missing) or 'none'}")
    for r in table_rows(spec, "## 4.", "## 5."):
        j = " ".join(r)
        if "T2" in j and ("color.text.disabled" in j or "opacity.disabled" in j):
            FAILS.append(f"section 4: a T2 row binds a disabled token: {r[0][:60]}")
    if any("color.drawing." in ln and "CMP-191" not in ln for ln in both.splitlines()):
        FAILS.append("color.drawing.* appears outside its CMP-191 attribution")
    return {"bound": len(names), "missing": missing}


def strings_report(spec: str, handoff: str, draft: str | None) -> dict[str, Any]:
    p()
    p("## 7. String gates")
    p()
    both = spec + "\n" + handoff
    lines = both.splitlines()

    def only_in(word: str, *marks: str) -> bool:
        return all(any(m in ln for m in marks) for ln in lines if word in ln)

    gated = gated_rows(spec)
    boards = table_rows(spec, "## 0.", "## 1.")
    ids = sorted(set(re.findall(r"\bC-\d+\.\d+\b", both)))
    cons = read(ROOT / "CONSTITUTION.md")
    blocks = len(re.findall(r"^## Handoff checklist", handoff, re.MULTILINE))
    blank = re.findall(r"^- \[[ x~]\]\s*(?:\*\*[^*\n]+\*\*)?\s*$", handoff, re.MULTILINE)
    t2_once = spec.count("never the `disabled` attribute") == 1 and "full label" in spec
    t2_rows = all("T2" in " ".join(r) for r in gated)
    empty_ok = not re.search(r"No drawings on BTCUSDT\. (?:Your role|Read-only)", both)
    apply_ok = only_in("Apply template", "absent", "C-23", "D02 §8.3", "deferred")
    locked_ok = only_in('"Locked."', "C-7")
    clone_ok = "Duplicate" in spec and all(
        "C-" in ln for ln in lines if re.search(r"\bClone\b", ln)
    )
    trade_ok = not any(
        TRADE_WORDS.search(" ".join(r)) for r in table_rows(spec, "### 12.2", "## 13.")
    )
    slips_ok = only_in("CMP-042", "C-", "eviation") and only_in("CMP-217", "C-", "eviation")
    pending_ok = bool(boards) and all(r[-1] == "PENDING" for r in boards)
    checks = [
        ("the T2 rule stated once (full label; never the `disabled` attribute)", t2_once),
        (f"'T2' in every gated state row ({len(gated)} rows)", t2_rows),
        ("the view-as leg named first", "view-as leg first" in spec),
        ("the sentence-form empty line carries no second copy of the reason", empty_ok),
        ("'Apply template' only as the absent entry (C-23) or D02's quoted clause", apply_ok),
        ('D02\'s "Locked." only in a C-7 line', locked_ok),
        ("the locked state leg named with its PROPOSED key", "`drawing.locked`" in spec),
        ("the never-cross-symbols sentence", "Sync never crosses symbols" in spec),
        ("'this pane only'", "this pane only" in spec),
        ("'Trendline #3' only in a C-row", only_in("Trendline #3", "C-")),
        ("'Duplicate' is the menu item; 'Clone' only in a C-row", clone_ok),
        ("no trading word in the copy-deck delta", trade_ok),
        ("CMP-042 and CMP-217 only in Deviation or C-rows", slips_ok),
        ("`drawing.removed` only in a C-row", only_in("drawing.removed", "C-")),
        (f"every section 0 board row ends in PENDING ({len(boards)} rows)", pending_ok),
        (f"every Constitution id cited exists ({len(ids)})", all(f"**{i}" in cons for i in ids)),
        (
            f"the handoff has three blocks ({blocks}), no blank checklist line",
            blocks == 3 and not blank,
        ),
    ]
    for label, rx in HYGIENE.items():
        checks.append((f"no {label} in the committed files", not rx.search(both)))
        if draft is not None:
            checks.append((f"no {label} in the draft", not rx.search(draft)))
    if draft is not None:
        partial = "Refs #351" in draft and "\nPartial:" in draft
        checks.append(("the draft carries `Refs #351` and a `Partial:` line", partial))
    OUT.extend(f"- [{'x' if ok else ' '}] {label}" for label, ok in checks)
    FAILS.extend(f"string gate: {label}" for label, ok in checks if not ok)
    failed = sum(not ok for _, ok in checks)
    return {"checks": len(checks), "failed": failed, "gated_rows": len(gated), "ids": ids}


def gated_rows(spec: str) -> list[list[str]]:
    """The section 4 rows that show a gated control: a T2 leg or the locked state leg."""
    return [r for r in table_rows(spec, "## 4.", "## 5.") if re.search(r"T2|locked", r[0])]


def counts_report(spec: str, handoff: str) -> dict[str, Any]:
    states = table_rows(spec, "## 4.", "## 5.")
    parity = table_rows(spec, "### 9.2", "### 9.3")
    sec16 = spec[spec.index("## 16.") :]

    def n16(prefix: str) -> int:
        return len(re.findall(rf"^\| {prefix}\d+ ", sec16, re.MULTILINE))

    counts = {"boards": len(table_rows(spec, "## 0.", "## 1.")), "states": len(states)}
    counts["t2_rows"] = len(gated_rows(spec))  # the same list the string gate checks
    counts["matrix_rows_in_spec"] = len(table_rows(spec, "### 10.1", "### 10.2"))
    counts["parity_rows"] = len(parity)
    counts["parity_gaps"] = sum(r[-1].lower().startswith("gap") for r in parity)
    counts["stories"] = len(table_rows(spec, "### 12.1", "### 12.2"))
    counts.update({"A": n16("A-"), "C": n16("C-"), "G": n16("G-"), "Q": n16("Q")})
    counts["handoff_blocks"] = len(re.findall(r"^## Handoff checklist", handoff, re.MULTILINE))
    counts["handoff_lines"], counts["spec_lines"] = handoff.count("\n") + 1, spec.count("\n") + 1
    if counts["matrix_rows_in_spec"] != len(PAIRS):
        FAILS.append(
            f"section 10.1 has {counts['matrix_rows_in_spec']} rows, the tool {len(PAIRS)}"
        )
    if counts["parity_gaps"]:
        FAILS.append("section 9.2: a parity row reads gap (AC 1: a blocking defect)")
    p()
    p("## 8. Counts (the boards and the draft quote these)")
    p()
    OUT.extend(f"- {k}: {v}" for k, v in counts.items())
    return counts


# the TOK keys the board script paints; the check-nums proves its literal equals this section
SCRIPT_TOKENS = dict(r for r in rows("""
app | surface.app
canvas | surface.canvas
raised | surface.raised
overlay | surface.overlay
hover | surface.hover
selected | surface.selected
sunken | surface.sunken
text | text.primary
text2 | text.secondary
text3 | text.tertiary
link | text.link
border | border.default
borderStrong | border.strong
ring | focus.ring
warnSubtle | status.warning.subtle
warnStrong | status.warning.strong
dangerStrong | status.danger.strong
secondary | action.secondary.default
"""))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="E14-D07 object-tree drawings-branch audit")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--draft", type=Path, default=None)
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    spec = read(SPEC) if SPEC.exists() else None
    handoff = read(HANDOFF) if HANDOFF.exists() else None
    out: dict[str, Any] = {"templates": templates_report(spec), "tree": tree_report()}
    out["matrix"], out["cvd"], out["lint"] = matrix_report(), cvd_report(), lint_report(spec)
    if spec is not None and handoff is not None:
        out["bindings"] = bindings_report(spec, handoff)
        out["strings"] = strings_report(spec, handoff, read(a.draft) if a.draft else None)
        out["counts"] = counts_report(spec, handoff)
    elif a.check:
        FAILS.append("the spec or the handoff is missing")
    out["tokens"] = {t: {k: hx(t, C + v) for k, v in SCRIPT_TOKENS.items()} for t in THEMES}
    out["fails"] = FAILS
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print("\n".join(OUT) + "\n\nFAILS: " + (", ".join(FAILS) if FAILS else "none"))
    return 1 if (a.check and FAILS) else 0


if __name__ == "__main__":
    raise SystemExit(main())
