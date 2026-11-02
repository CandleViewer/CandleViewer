#!/usr/bin/env python3
"""E21-D03 (#503) audit: the SCR-051 settings dialog and SCR-153 depth-shed hi-fi spec (text first).

Offline and default-deny. It reads, AS TEXT at a pinned commit (`git show`), the plan and design
texts the spec cites at the base, and E21-D02's spec at its PR head, and, from the working tree,
the spec `docs/design/E21/E21-D03.md` and the pins file. The only repo code it runs is the two
measuring modules the spec names: `contrast_ratio()` of `docs/design/_tools/contrast_check.py`
and `simulate()` / `delta_e76()` of `docs/research/_tools/cvd_simulate.py`, loaded by path.

Gates (one PASS or FAIL line each): G-CITE, G-QUOTE, G-VERSION, G-AC, G-CHECKLIST, G-TABS,
G-VALID, G-COST, G-STATES, G-AD, G-T2, G-T2LEN, G-ENV, G-SHED, G-TOKENS, G-CONTRAST, G-CVD,
G-BOARDS, G-PENPOT, G-RULING, G-RULED, G-NOCLOSE, G-PUBLIC, G-UNTOUCHED and G-MUTLIST (the spec's
section 19.3 equals this tool's list).

Pins (G-RULED): every bullet of the BQ section is pinned by its sha256 in
`e21_d03_ruled_pins.txt`; `--repin-ruled` is the only writer. The section is pending a ruling
(comment 6579618328); when it is ruled, the section and RULING below change together.

--self-test applies every mutation (M-n) in memory; each must add exactly one FAIL, from the gate
it names, to a clean baseline; the files on disk are checked byte-identical afterwards (sha256).

Usage (from the repo root):
  python3 -I docs/design/_tools/e21_d03_scr051_audit.py --check
  python3 -I docs/design/_tools/e21_d03_scr051_audit.py --self-test
  python3 -I docs/design/_tools/e21_d03_scr051_audit.py --repin-ruled
  python3 -I docs/design/_tools/e21_d03_scr051_audit.py --fill   (writes sections 12 and 19.3)
Exit 0 = no FAIL; 1 = at least one FAIL. Run it on a rebased branch or a committed merge: on an
uncommitted merge the merge-base is still the old one and G-UNTOUCHED reports main's own changes.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
BASE = "9b77e6b83"  # origin/main when the spec was written; every plan cite is read here
D02_HEAD = (
    "7e1040260"  # PR #5488 (E21-D02, #440) head; re-pinned to its merge commit when it merges
)
D02_PR = "#5488"
BQ_LIST = "6579618328"  # the BQ list on #503; no ruling yet

SPEC_REL = "docs/design/E21/E21-D03.md"
TOOL_REL = "docs/design/_tools/e21_d03_scr051_audit.py"
PIN_REL = "docs/design/_tools/e21_d03_ruled_pins.txt"
CAT_REL = "docs/plan/14-screens-catalogue.md"
IMG_PREFIX = "docs/design/E21/img/E21-D03-"
OWN = (SPEC_REL, TOOL_REL, PIN_REL)
BACKLOG_REL = "docs/plan/backlog/E21.json"
POINTER_LINES = 2  # one under SCR-051, one under SCR-153 (BQ-2)

PLAN = {
    "05": "docs/plan/05-accessibility-standard.md",
    "06": "docs/plan/06-performance-and-load-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": CAT_REL,
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "23": "docs/plan/23-ws-protocol.md",
    "24": "docs/plan/24-internal-schemas.md",
}
KEYED = {
    "M": ("docs/design/research/e21-dom-heatmap.md", BASE),
    "D02": ("docs/design/E21/E21-D02.md", D02_HEAD),
    "D09E09": ("docs/design/E09/E09-D09.md", BASE),
    "D03E17": ("docs/design/E17/E17-D03.md", BASE),
    "D12E15": ("docs/design/E15/E15-D12.md", BASE),
    "K04": ("docs/plan/spikes/E06-K04.md", BASE),
    "R32": (".claude/rules/32-design-specs.md", BASE),
    "README": ("docs/design/README.md", BASE),
}
_KEYS = "|".join(sorted(KEYED, key=len, reverse=True))
CITE_RE = re.compile(rf"(?:`(\d\d)`|(?<![A-Za-z0-9-])({_KEYS})):(\d+)")

THEMES = {
    "dark": ("semantic-dark",),
    "light": ("semantic-dark", "semantic-light"),
    "high-contrast": ("semantic-dark", "semantic-hc"),
}
DEFICIENCIES = ("deuteranopia", "protanopia", "tritanopia")
CANVAS = "color.surface.canvas"
OVERLAY = "color.surface.overlay"
INFO = "color.status.info.subtle"
RAISED = "color.surface.raised"
SUNKEN = "color.surface.sunken"
STOPS = "color.heatmap.*"  # in PAIRS: the lowest of the ten standard stops
CVD_STOPS = "color.cvd.heatmap.*"  # in PAIRS: the lowest of the ten CVD-safe stops
# Section 12.2's table, row by row: (foreground, background, floor).
PAIRS: tuple[tuple[str, str, float], ...] = (
    ("color.text.primary", OVERLAY, 4.5),
    ("color.text.secondary", OVERLAY, 4.5),
    ("color.text.tertiary", OVERLAY, 4.5),
    ("color.focus.ring", OVERLAY, 3.0),
    ("color.status.danger.strong", OVERLAY, 3.0),
    ("color.text.primary", "color.status.warning.subtle", 4.5),
    ("color.status.warning.strong", "color.status.warning.subtle", 3.0),
    ("color.text.primary", INFO, 4.5),
    ("color.text.secondary", INFO, 4.5),
    ("color.status.info.strong", INFO, 3.0),
    ("color.focus.ring", INFO, 3.0),
    ("color.env.demo", OVERLAY, 3.0),
    ("color.env.live", OVERLAY, 3.0),
    ("color.text.primary", RAISED, 4.5),
    ("color.env.demo", RAISED, 3.0),
    ("color.env.live", RAISED, 3.0),
    ("color.text.secondary", RAISED, 4.5),
    ("color.text.tertiary", RAISED, 4.5),
    ("color.focus.ring", RAISED, 3.0),
    ("color.border.selected", OVERLAY, 3.0),
    ("color.text.primary", SUNKEN, 4.5),
    ("color.border.default", OVERLAY, 3.0),
    ("color.border.default", RAISED, 3.0),
    (STOPS, "color.heatmap.zero", 3.0),
    (CVD_STOPS, "color.heatmap.zero", 3.0),
)
# Pairs written and measured but not gated: a non-essential edge (section 12.2 says why; the
# shared finding is E05-D04 F-03). Their floor cell reads "3, reported".
REPORTED: frozenset[tuple[str, str]] = frozenset(
    {("color.border.default", OVERLAY), ("color.border.default", RAISED)}
)
TABS = ("Depth & scale", "Colour", "Ladder", "Trading", "Detectors")
TAB_ITEMS = (1, 2, 3, 4, 5, 6, 7, 8, 10)  # section AC.1 items that live on a tab row
T2_LEN_ROWS = ("W-3",)
COST_ROWS = ("W-6", "W-7", "W-8")
NAME_RE = re.compile(r"\b(?:SCR-\d+|E\d\d(?:-[A-Z]\d+)?|heatmap|ladder|DOM)\b", re.IGNORECASE)
T2_MARKERS = (
    "G-T2.1a",
    "G-T2.1b",
    "G-T2.1c",
    "G-T2.1d",
    "G-T2.2",
    "G-T2.3",
    "G-T2.4",
    "G-T2.5",
    'aria-disabled="true"',
    "never `disabled`",
    "aria-describedby",
    "CMP-079",
    "CMP-019",
    "never `opacity.disabled`",
)
SHED_MARKERS = (
    "**Cause and loss**",
    "**What still works**",
    "**The pin**",
    "**Restore**",
    "**Greyscale.**",
    "`degraded.exited",
    "**One announcement per state change.**",
)

# Deny lists are assembled from fragments so this file never matches itself.
_KW = "|".join(("clo" + "se[sd]?", "fix" + "(?:e[sd])?", "resol" + "ve[sd]?"))
KEYWORD_RE = re.compile(rf"\b(?:{_KW}):?\s*#\d+", re.IGNORECASE)
HEADING_RE = re.compile(
    r"^#+\s*" + "What" + r" this\b[^\n]*\b" + "fix" + "es", re.IGNORECASE | re.MULTILINE
)
PUBLIC_RE = re.compile(
    "|".join(
        (
            "http" + r"s?://",
            r"\bwww" + r"\.",
            "/" + "home/",
            "/" + "tmp/",
            r"\.lo" + r"cal\b",
            "scratch" + "-",
            "bas" + "iltt",
            r"\bhcl" + "-",
            r"\bhpe" + "-",
            r"\bwor" + r"ker\b",
            r"\bAn" + r"vil\b",
        )
    ),
    re.IGNORECASE,
)
PENPOT_RE = re.compile(
    "|".join(
        (
            "pen" + r"pot\.[a-z]",
            "file" + r"[-_]id\s*=",
            "team" + r"[-_]id\s*=",
            r"#/" + "work" + "space",
            "/" + "view/",
        )
    ),
    re.IGNORECASE,
)
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
TOKEN_RE = re.compile(
    r"`((?:color|space|size|type|font|opacity|border)\.[A-Za-z0-9.*\-]+?)(\.\.\d+)?(\[\])?`"
)


# ------------------------------------------------------------------ git and files -----------------
def git(*args: str) -> str:
    res = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if res.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {res.stderr.strip()}")
    return res.stdout


def git_ok(*args: str) -> str | None:
    res = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return res.stdout if res.returncode == 0 else None


@functools.cache
def at(rev: str, rel: str) -> tuple[str, ...]:
    out = git_ok("show", f"{rev}:{rel}")
    if out is None:
        raise SystemExit(
            f"cannot read {rel} at {rev}: the commit is missing here "
            f"(try `git fetch origin {rev}`; D02's pin lives on {D02_PR}'s branch until it merges)"
        )
    return tuple(out.split("\n"))


def diff_base() -> str:
    """The merge-base with origin/main; the pinned base when that cannot be computed."""
    mb = git_ok("merge-base", "HEAD", "origin/main")
    return mb.strip() if mb and mb.strip() else BASE


def changed() -> tuple[tuple[str, ...], str]:
    base = diff_base()
    names = set(git("diff", "--name-only", base).split())
    names |= set(git("ls-files", "--others", "--exclude-standard").split())
    numstat = git("diff", "--numstat", base, "--", CAT_REL).strip()
    return tuple(sorted(names)), numstat


def load_module(rel: str, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {rel}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@functools.lru_cache(maxsize=1)
def measurers() -> tuple[ModuleType, ModuleType]:
    return (
        load_module("docs/design/_tools/contrast_check.py", "contrast_check"),
        load_module("docs/research/_tools/cvd_simulate.py", "cvd_simulate"),
    )


# ------------------------------------------------------------------ tokens ------------------------
def token_file(name: str) -> dict[str, dict[str, object]]:
    raw = json.loads("\n".join(at(BASE, f"packages/ui/tokens/{name}.tokens.json")))
    return {k: v for k, v in raw.items() if not k.startswith("$") and isinstance(v, dict)}


@functools.cache
def theme(name: str) -> dict[str, str]:
    allt = dict(token_file("primitives"))
    for part in THEMES[name]:
        allt.update(token_file(part))

    def res(value: object, seen: frozenset[str]) -> object:
        if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
            ref = value[1:-1]
            if ref in seen or ref not in allt:
                return None
            return res(allt[ref].get("$value"), seen | {ref})
        return value

    out: dict[str, str] = {}
    for key, tok in allt.items():
        val = res(tok.get("$value"), frozenset({key}))
        out[key] = val if isinstance(val, str) else ""
    return out


@functools.lru_cache(maxsize=1)
def token_names() -> frozenset[str]:
    names: set[str] = set()
    for part in ("primitives", "semantic-dark", "semantic-light", "semantic-hc"):
        names |= set(token_file(part))
    return frozenset(names)


def rgb(hexv: str) -> tuple[int, int, int]:
    h = hexv.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def ratio(fg: str, bg: str) -> float:
    cc, _ = measurers()
    return float(cc.contrast_ratio(rgb(fg), rgb(bg)))


def stops(prefix: str) -> list[str]:
    return [f"{prefix}.{s}.{i}" for s in ("bid", "ask") for i in range(1, 6)]


def pair_de(t: dict[str, str], prefix: str, i: int, deficiency: str) -> float:
    _, cvd = measurers()
    return float(
        cvd.delta_e76(
            cvd.simulate(t[f"{prefix}.bid.{i}"], deficiency),
            cvd.simulate(t[f"{prefix}.ask.{i}"], deficiency),
        )
    )


def measured_row(name: str) -> list[str]:
    """The section 12.1 row this tool derives for one theme, cell by cell."""
    t = theme(name)
    bg = t[CANVAS]

    def lowest(prefix: str) -> tuple[str, float]:
        best = min(stops(prefix), key=lambda k: ratio(t[k], bg))
        return best, ratio(t[best], bg)

    def smallest(prefix: str, deficiency: str) -> float:
        return min(pair_de(t, prefix, i, deficiency) for i in range(1, 6))

    low, low_r = lowest("color.heatmap")
    twin, twin_r = lowest("color.cvd.heatmap")
    twin_de = min(smallest("color.cvd.heatmap", d) for d in DEFICIENCIES)
    return [
        name,
        f"`{low}`",
        f"{low_r:.2f}",
        *(f"{smallest('color.heatmap', d):.1f}" for d in DEFICIENCIES),
        f"`{twin}`",
        f"{twin_r:.2f}",
        f"{twin_de:.1f}",
    ]


def closest_level(name: str, deficiency: str) -> int:
    t = theme(name)
    return min(range(1, 6), key=lambda i: pair_de(t, "color.heatmap", i, deficiency))


def pair_label(fg: str, bg: str) -> str:
    return f"`{fg}` on `{bg}`"


def pair_ratio(name: str, fg: str, bg: str) -> float:
    t = theme(name)
    if fg == STOPS:
        return min(ratio(t[k], t[bg]) for k in stops("color.heatmap"))
    if fg == CVD_STOPS:
        return min(ratio(t[k], t[bg]) for k in stops("color.cvd.heatmap"))
    return ratio(t[fg], t[bg])


def measured_pair(fg: str, bg: str, floor: float) -> list[str]:
    cell = f"{floor:g}, reported" if (fg, bg) in REPORTED else f"{floor:g}"
    return [pair_label(fg, bg), cell, *(f"{pair_ratio(n, fg, bg):.2f}" for n in THEMES)]


# ------------------------------------------------------------------ markdown helpers --------------
@dataclass(frozen=True)
class Texts:
    spec: str
    pins: str
    paths: tuple[str, ...]
    numstat: str


def section(text: str, prefix: str) -> str:
    lines = text.split("\n")
    level = len(prefix) - len(prefix.lstrip("#"))
    out: list[str] = []
    inside = False
    for line in lines:
        if line.startswith(prefix):
            inside = True
            continue
        if inside and re.match(rf"^#{{1,{level}}} ", line):
            break
        if inside:
            out.append(line)
    return "\n".join(out)


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def rows(block: str) -> list[list[str]]:
    out: list[list[str]] = []
    seen_rule = False
    for line in block.split("\n"):
        if not line.startswith("|"):
            if seen_rule and out:
                break
            continue
        if re.match(r"^\|[\s:|-]+\|$", line.strip()):
            seen_rule = True
            continue
        if seen_rule:
            out.append(cells(line))
    return out


def all_tables(block: str) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    current: list[list[str]] = []
    for line in block.split("\n") + [""]:
        if line.startswith("|"):
            if not re.match(r"^\|[\s:|-]+\|$", line.strip()):
                current.append(cells(line))
        elif current:
            tables.append(current[1:])
            current = []
    return tables


def unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    return s


def cite_line(key_plan: str | None, key: str | None, line: int) -> str | None:
    if key_plan:
        rel, rev = PLAN.get(key_plan, ""), BASE
        if not rel:
            return None
    else:
        assert key is not None
        rel, rev = KEYED[key]
    text = at(rev, rel)
    if line < 1 or line > len(text):
        return None
    return text[line - 1]


def copy_deck(spec: str) -> dict[str, list[str]]:
    return {r[0]: r for r in rows(section(spec, "## 15. Copy deck"))}


def bq_bullets(spec: str) -> list[str]:
    body = section(spec, "## The questions BQ-0")
    return [ln for ln in body.split("\n") if ln.startswith("- **BQ-")]


def pin_lines(spec: str) -> list[str]:
    out = []
    for ln in bq_bullets(spec):
        m = re.match(r"- \*\*(BQ-\d+)", ln)
        if m:
            out.append(f"{m.group(1)} {hashlib.sha256(ln.encode('utf-8')).hexdigest()[:16]}")
    return out


def checklist_items(line_no: int) -> list[list[str]]:
    """The boxes of a `14` checklist line, each split into its items."""
    line = cite_line("14", None, line_no) or ""
    boxes = [p.strip().removesuffix(".").strip() for p in line.split("[ ]")[1:]]
    out = []
    for box in boxes:
        if box.endswith(" all drawn"):
            body = box.removesuffix(" all drawn")
            out.append([p.strip() for p in re.split(r", (?![^()]*\))| and ", body)])
        else:
            out.append([box])
    return out


# ------------------------------------------------------------------ gates -------------------------
Finding = tuple[str, str]  # (gate, message)


def g_cite(t: Texts) -> list[Finding]:
    bad = []
    for m in CITE_RE.finditer(t.spec):
        line = cite_line(m.group(1), m.group(2), int(m.group(3)))
        if line is None or not line.strip():
            bad.append(m.group(0))
    return [("G-CITE", f"unresolved cites: {', '.join(sorted(set(bad)))}")] if bad else []


def g_quote(t: Texts) -> list[Finding]:
    bad = []
    for r in copy_deck(t.spec).values():
        if len(r) < 5 or not r[4].startswith("verbatim"):
            continue
        m = CITE_RE.search(r[3])
        line = cite_line(m.group(1), m.group(2), int(m.group(3))) if m else None
        if line is None or unquote(r[2]) not in line:
            bad.append(r[0])
    quote = re.search(r'M OQ-4 words it: "(.*?)" \(M:292\)', t.spec, re.DOTALL)
    m292 = cite_line(None, "M", 292) or ""
    if quote is None or quote.group(1) not in m292:
        bad.append("M OQ-4 quote")
    return [("G-QUOTE", f"not on the cited line: {', '.join(bad)}")] if bad else []


def g_version(t: Texts) -> list[Finding]:
    v = section(t.spec, "### 19.1 Version line")
    need = (BASE, D02_HEAD, D02_PR, "re-pinned to the merge commit")
    miss = [n for n in need if n not in v]
    if f"Base `origin/main` `{BASE}`" not in t.spec:
        miss.append("Inputs pinned base")
    if f"read at the PR head `{D02_HEAD}`" not in t.spec:
        miss.append("Start D02 pin")
    return [("G-VERSION", f"missing: {', '.join(miss)}")] if miss else []


def g_ac(t: Texts) -> list[Finding]:
    tickets = json.loads("\n".join(at(BASE, BACKLOG_REL)))
    body = next(str(x.get("body", "")) for x in tickets if x.get("key") == "E21-D03")
    names = re.findall(r"Scenario: (.+)", body)
    trace = section(t.spec, "## Acceptance-criteria and DoD trace")
    miss = [n for n in names if f'AC "{n.strip()}"' not in trace]
    if len(names) != 3 or miss:
        return [("G-AC", f"scenario names not verbatim in the trace: {miss or names}")]
    return []


def g_checklist(t: Texts) -> list[Finding]:
    tables = all_tables(section(t.spec, "### AC.1"))
    scr051 = checklist_items(1255)
    scr153 = [i for box in checklist_items(3120) for i in box]
    want = [scr051[0] if scr051 else [], [i for box in scr051[1:] for i in box], scr153]
    counts = (8, 3, 6)
    bad: list[str] = []
    for idx, items in enumerate(want):
        got = tables[idx] if idx < len(tables) else []
        if len(items) != counts[idx] or len(got) != counts[idx]:
            bad.append(f"table {idx + 1}: {len(got)} rows for {len(items)} items")
            continue
        for item, r in zip(items, got, strict=True):
            if len(r) < 4 or r[1] != item:
                bad.append(f"table {idx + 1} item {r[0] if r else '?'}")
            elif "board" not in r[2] and not r[3].startswith("N/A"):
                bad.append(f"table {idx + 1} item {r[0]} has no frame")
    return [("G-CHECKLIST", "; ".join(bad))] if bad else []


def g_tabs(t: Texts) -> list[Finding]:
    line = cite_line("14", None, 1230) or ""
    cat = tuple(p.strip().removesuffix(".") for p in line.split("tabs:", 1)[-1].split("·"))
    bad = [] if cat == TABS else [f"`14`:1230 lists {cat}"]
    got = rows(section(t.spec, "### 2.2"))
    order: list[str] = []
    for r in got:
        if r and r[0] not in order:
            order.append(r[0])
    if tuple(order) != TABS:
        bad.append(f"tab order {order}")
    seen: list[int] = []
    for r in got:
        m = re.match(r"(\d+)", r[3]) if len(r) > 3 else None
        if m:
            seen.append(int(m.group(1)))
    if sorted(set(seen)) != list(TAB_ITEMS):
        bad.append(f"checklist items on tab rows {sorted(set(seen))}")
    return [("G-TABS", "; ".join(bad))] if bad else []


def g_valid(t: Texts) -> list[Finding]:
    cat = cite_line("14", None, 1248) or ""
    bad = []
    got = {r[0]: r for r in rows(section(t.spec, "### 9.1"))}
    trail = got.get("Trail length", [])
    m = re.search(r"trail (\d+)–(\d+) s", cat)
    if not m or len(trail) < 3 or trail[1] != f"{m.group(1)}–{m.group(2)} s":
        bad.append("trail range differs from `14`:1248")
    elif f"`{{min}}` {m.group(1)}" not in trail[2] or f"`{{max}}` {m.group(2)}" not in trail[2]:
        bad.append("trail copy fills")
    row = got.get("Row height", [])
    if "row height 10–40 px" not in cat or len(row) < 4 or row[1] != "24–40 px":
        bad.append("row height not 24–40 px against the catalogue's 10–40")
    elif "C-2" not in row[3]:
        bad.append("row height not tied to C-2")
    if "at least one qty preset" not in cat or got.get("Qty presets", ["", ""])[1] != (
        "at least one filled"
    ):
        bad.append("qty presets")
    deck = copy_deck(t.spec)
    for wid in ("W-10", "W-11"):
        if "{min}–{max}" not in (deck.get(wid, ["", "", ""])[2]):
            bad.append(f"{wid} not keyed on {{min}}–{{max}}")
    return [("G-VALID", "; ".join(bad))] if bad else []


def g_cost(t: Texts) -> list[Finding]:
    deck = copy_deck(t.spec)
    bad = []
    for wid in COST_ROWS:
        s = re.sub(r"\{[^}]*\}|\bp95\b", "", deck.get(wid, ["", "", ""])[2])
        if re.search(r"\d", s) or not deck.get(wid):
            bad.append(f"{wid} carries a figure")
    s34 = section(t.spec, "### 3.4")
    if 'labelled "illustrative, seeded synthetic book"' not in s34:
        bad.append("illustrative label")
    if "never an estimate" not in s34 or "R-6" not in s34:
        bad.append("measured only (R-6)")
    return [("G-COST", "; ".join(bad))] if bad else []


def state_rows(spec: str) -> list[list[str]]:
    return rows(section(spec, "## 10. States"))


def board_rows(spec: str) -> list[list[str]]:
    return rows(section(spec, "## 0. Status"))


def g_states(t: Texts) -> list[Finding]:
    boards = {r[0]: r[2] for r in board_rows(t.spec) if len(r) > 2}
    frames: set[str] = set()
    bad = []
    for r in state_rows(t.spec):
        m = re.search(r"`(SCR-(?:051|153)/[a-z0-9-]+)`", r[0])
        if not m or len(r) < 8:
            bad.append(r[0])
            continue
        frames.add(m.group(1))
        if f"`{m.group(1)}`" not in boards.get(r[7], ""):
            bad.append(f"{m.group(1)} not on board {r[7]}")
    drawn = set(re.findall(r"SCR-(?:051|153)/[a-z0-9-]+", " ".join(boards.values())))
    bad += [f"{d} drawn, no state row" for d in sorted(drawn - frames)]
    return [("G-STATES", "; ".join(bad))] if bad else []


def g_ad(t: Texts) -> list[Finding]:
    got = rows(section(t.spec, "### 14.2"))
    ids = [r[0] for r in got]
    bad = [] if ids == ["AD-7", "AD-8"] else [f"ids {ids}"]
    for r in got:
        if len(r) < 4 or r[3] != "satisfied" or "board" not in r[2]:
            bad.append(f"{r[0]} verdict or frame")
    return [("G-AD", "; ".join(bad))] if bad else []


def g_t2(t: Texts) -> list[Finding]:
    r3 = next((ln for ln in t.spec.split("\n") if ln.startswith("- **R-3 ")), "")
    bad = [m for m in T2_MARKERS if m not in r3]
    srows = state_rows(t.spec)
    bad += [f"{r[0]} T2 cell" for r in srows if len(r) < 7 or not r[6]]
    t2cells = " ".join(r[6] for r in srows if len(r) > 6)
    bad += [w for w in ("the 500 option", "Save, 2a") if w not in t2cells]
    return [("G-T2", f"missing: {', '.join(bad)}")] if bad else []


def g_t2len(t: Texts) -> list[Finding]:
    bad = []
    deck = copy_deck(t.spec)
    for wid in T2_LEN_ROWS:
        s = unquote(deck.get(wid, ["", "", ""])[2])
        if len(s) > 60 or not s.endswith(".") or ". " in s or re.search(r"\d", s):
            bad.append(f"{wid} ({len(s)} chars)")
        elif NAME_RE.search(s):
            bad.append(f"{wid} names a screen or ticket")
    return [("G-T2LEN", "; ".join(bad))] if bad else []


def g_env(t: Texts) -> list[Finding]:
    s6 = section(t.spec, "## 6. The Trading tab")
    need = (
        "C-2.11 is a hard constraint",
        "never the feed",
        "separate frames",
        "never one toggle across environments",
    )
    bad = [n for n in need if n not in s6]
    frames = " ".join(r[0] for r in state_rows(t.spec))
    bad += [f for f in ("SCR-051/trading-demo", "SCR-051/trading-live") if f not in frames]
    return [("G-ENV", f"missing: {', '.join(bad)}")] if bad else []


def g_shed(t: Texts) -> list[Finding]:
    s11 = section(t.spec, "## 11. SCR-153")
    bad = [m for m in SHED_MARKERS if m not in s11]
    deck = copy_deck(t.spec)
    w22 = deck.get("W-22", ["", "", ""])[2]
    w23 = deck.get("W-23", ["", "", ""])[2]
    if "fell behind" not in w22 or "hidden" not in w22:
        bad.append("W-22 cause and loss")
    if not all(w in w23 for w in ("Orders", "positions", "environment badge")):
        bad.append("W-23 never-shed list")
    if unquote(deck.get("W-25", ["", "", ""])[2]) != "Pin depth 200":
        bad.append("W-25 pin")
    return [("G-SHED", f"missing: {', '.join(bad)}")] if bad else []


def g_tokens(t: Texts) -> list[Finding]:
    names = token_names()
    bad = []
    for m in TOKEN_RE.finditer(t.spec):
        name, rng, ramp = m.group(1), m.group(2), m.group(3)
        if ramp:
            continue
        if name.endswith(".*"):
            ok = any(n.startswith(name[:-1]) for n in names)
        elif rng:
            stem, first = name.rsplit(".", 1)
            span = range(int(first), int(rng[2:]) + 1) if first.isdigit() else range(0)
            ok = bool(span) and all(f"{stem}.{i}" in names for i in span)
        else:
            ok = name in names
        if not ok:
            bad.append(name + (rng or ""))
    return [("G-TOKENS", f"unknown: {', '.join(sorted(set(bad)))}")] if bad else []


def g_contrast(t: Texts) -> list[Finding]:
    bad = []
    got = {r[0]: r for r in rows(section(t.spec, "### 12.1"))}
    for name in THEMES:
        want = measured_row(name)
        r = got.get(name, [])
        if len(r) < 9 or [r[1], r[2], r[6], r[7]] != [want[1], want[2], want[6], want[7]]:
            bad.append(f"{name}: written {r[1:3] + r[6:8] if r else []}, measured {want[1:3]}")
        if float(want[2]) < 3.0 or float(want[7]) < 3.0:
            bad.append(f"{name} heatmap stop below 3")
    written = {r[0]: r for r in rows(section(t.spec, "### 12.2"))}
    for fg, bg, floor in PAIRS:
        want_pair = measured_pair(fg, bg, floor)
        if written.get(want_pair[0], [])[:5] != want_pair:
            bad.append(f"pair {want_pair[0]}: measured {want_pair[1:]}")
        if (fg, bg) not in REPORTED and min(float(v) for v in want_pair[2:]) < floor:
            bad.append(f"pair {want_pair[0]} below {floor:g}")
    if len(written) != len(PAIRS):
        bad.append(f"{len(written)} pair rows for {len(PAIRS)} pairs")
    return [("G-CONTRAST", "; ".join(bad))] if bad else []


def g_cvd(t: Texts) -> list[Finding]:
    bad = []
    got = {r[0]: r for r in rows(section(t.spec, "### 12.1"))}
    for name in THEMES:
        want = measured_row(name)
        r = got.get(name, [])
        if len(r) < 9 or [r[3], r[4], r[5], r[8]] != [want[3], want[4], want[5], want[8]]:
            bad.append(f"{name}: measured {want[3:6] + want[8:]}")
    lvl = closest_level("dark", "deuteranopia")
    named = re.search(r"closest standard pair in dark is level (\d) \(`bid\.(\d)`", t.spec)
    if named is None or {named.group(1), named.group(2)} != {str(lvl)}:
        bad.append(f"closest deuteranopia level is {lvl}")
    return [("G-CVD", "; ".join(bad))] if bad else []


def g_boards(t: Texts) -> list[Finding]:
    got = board_rows(t.spec)
    bad = []
    twins = sum(1 for r in got if len(r) > 3 and "light" in r[3])
    if not 0 < len(got) <= 10:
        bad.append(f"{len(got)} boards")
    if twins * 3 > len(got):
        bad.append(f"{twins} light twins of {len(got)}")
    for r in got:
        if len(r) < 5 or r[4] != "PENDING" or not r[1].startswith(f"`E21-D03 / {r[0]} "):
            bad.append(f"board {r[0] if r else '?'}")
    if "**Not drawn — the text is binding**" not in t.spec:
        bad.append("not-drawn paragraph")
    return [("G-BOARDS", "; ".join(bad))] if bad else []


def g_penpot(t: Texts) -> list[Finding]:
    s0 = section(t.spec, "## 0. Status")
    bad = []
    if "page `E21-D03`" not in s0 or "page id" not in s0:
        bad.append("page by name and id")
    for label, text in (("spec", t.spec), ("pins", t.pins)):
        bad += [f"{label}: {m.group(0)}" for m in PENPOT_RE.finditer(text)]
    return [("G-PENPOT", "; ".join(bad))] if bad else []


def g_ruling(t: Texts) -> list[Finding]:
    head = f"## The questions BQ-0 … BQ-15 — defaults built; ruling pending (comment {BQ_LIST})"
    bad = [] if head in t.spec.split("\n") else ["heading"]
    bullets = bq_bullets(t.spec)
    ids = [m.group(1) for b in bullets if (m := re.match(r"- \*\*(BQ-\d+)", b))]
    if ids != [f"BQ-{n}" for n in range(16)]:
        bad.append(f"ids {ids}")
    for b, bid in zip(bullets, ids):
        if "Default built:" not in b or "RULED" in b:
            bad.append(bid)
    return [("G-RULING", "; ".join(bad))] if bad else []


def g_ruled(t: Texts) -> list[Finding]:
    want = [ln for ln in t.pins.split("\n") if ln and not ln.startswith("#")]
    got = pin_lines(t.spec)
    if want != got:
        diff = sorted(set(want) ^ set(got))
        return [("G-RULED", f"BQ lines differ from the pins: {[d.split()[0] for d in diff]}")]
    return []


def g_noclose(t: Texts) -> list[Finding]:
    bad = []
    for label, text in (("spec", t.spec), ("pins", t.pins)):
        bad += [f"{label}: {m.group(0)}" for m in KEYWORD_RE.finditer(text)]
        bad += [f"{label}: heading" for _ in HEADING_RE.finditer(text)]
    return [("G-NOCLOSE", "; ".join(bad))] if bad else []


def g_public(t: Texts) -> list[Finding]:
    bad = []
    for label, text in (("spec", t.spec), ("pins", t.pins)):
        bad += [f"{label}: {m.group(0)}" for m in PUBLIC_RE.finditer(text)]
    bad += [f"spec: stray comment {m.group(0)[:20]}" for m in COMMENT_RE.finditer(t.spec)]
    return [("G-PUBLIC", "; ".join(bad))] if bad else []


def g_untouched(t: Texts) -> list[Finding]:
    bad = [
        p
        for p in t.paths
        if p not in OWN and p != CAT_REL and not (p.startswith(IMG_PREFIX) and p.endswith(".png"))
    ]
    if CAT_REL in t.paths and t.numstat.split()[:2] != [str(POINTER_LINES), "0"]:
        bad.append(f"{CAT_REL} is not {POINTER_LINES} added lines ({t.numstat})")
    return [("G-UNTOUCHED", f"outside the ticket: {', '.join(bad)}")] if bad else []


@dataclass(frozen=True)
class Mutation:
    mid: str
    gate: str
    what: str
    old: str
    new: str
    target: str = "spec"  # spec | pins | paths | numstat
    regex: bool = False


MUTATIONS: tuple[Mutation, ...] = (
    Mutation("M-1", "G-CITE", "a cite past the end of `23`", "`23`:731", "`23`:99999"),
    Mutation(
        "M-2",
        "G-QUOTE",
        "W-5 reworded off its line",
        '"Depth 200 → 500 · rebuilding"',
        '"Depth 200 → 500 · reloading"',
    ),
    Mutation(
        "M-3",
        "G-VERSION",
        "the version line drops the re-pin",
        "re-pinned to the merge commit when #5488 merges; M",
        "kept when #5488 merges; M",
    ),
    Mutation(
        "M-4",
        "G-AC",
        "a scenario name reworded",
        'AC "Shedding is explained, not hidden"',
        'AC "Shedding is explained"',
    ),
    Mutation(
        "M-5",
        "G-CHECKLIST",
        "a SCR-051 item reworded",
        "| 3   | heatmap trail length ",
        "| 3   | trail length         ",
    ),
    Mutation(
        "M-6",
        "G-CHECKLIST",
        "a SCR-153 item loses its frame",
        "W-22, W-23 on board 09 (§11)",
        "W-22, W-23 (§11)",
    ),
    Mutation(
        "M-7",
        "G-TABS",
        "a Ladder row moved to Detectors",
        "| Ladder        | Show:",
        "| Detectors     | Show:",
    ),
    Mutation(
        "M-8",
        "G-VALID",
        "the trail range drifts",
        "| Trail length | 5–600 s",
        "| Trail length | 5–900 s",
    ),
    Mutation(
        "M-9",
        "G-COST",
        "a cost figure in the copy",
        '"{tier}: not yet measured on this device"',
        '"{tier}: about 40 ms on this device"',
    ),
    Mutation(
        "M-10",
        "G-COST",
        "the illustrative label dropped",
        'labelled "illustrative, seeded synthetic book"',
        "labelled as a sample",
    ),
    Mutation(
        "M-11",
        "G-STATES",
        "board 05 stops drawing a state",
        "`SCR-051/trading-live`, `SCR-051/live-confirm-off`",
        "`SCR-051/trading-live`",
    ),
    Mutation(
        "M-12",
        "G-AD",
        "AD-8 dropped from the table",
        "| AD-8 | §5 Centring",
        "| AD-9 | §5 Centring",
    ),
    Mutation(
        "M-13",
        "G-T2",
        "R-3 loses the opacity ban",
        "never `color.text.disabled`, never `opacity.disabled` (G-T2.2)",
        "never `color.text.disabled` (G-T2.2)",
    ),
    Mutation(
        "M-14",
        "G-T2LEN",
        "W-3 names the screen",
        r'"The deepest book tier isn\'t available here\."( *\| D02:431 *\| )verbatim',
        r'"The deepest book tier isn\'t on the ladder."\1PROPOSED',
        regex=True,
    ),
    Mutation(
        "M-15",
        "G-ENV",
        "one toggle across environments",
        "never one toggle across environments:",
        "one toggle for both environments:",
    ),
    Mutation(
        "M-16",
        "G-SHED",
        "the still-works line dropped",
        "- **What still works** (W-23)",
        "- **Also** (W-23)",
    ),
    Mutation(
        "M-17",
        "G-TOKENS",
        "an unshipped focus token",
        "`color.focus.ring`, 2 px outside the control",
        "`color.focus.halo`, 2 px outside the control",
    ),
    Mutation(
        "M-18",
        "G-CONTRAST",
        "a written pair ratio drifts",
        r"(`color\.env\.live` on `color\.surface\.overlay` *\| 3 *\| )\d+\.\d\d",
        r"\g<1>4.19",
        regex=True,
    ),
    Mutation(
        "M-19",
        "G-CVD",
        "a written distance drifts",
        "| 1.9             | 19.2",
        "| 2.9             | 19.2",
    ),
    Mutation(
        "M-20",
        "G-BOARDS",
        "a fourth light twin",
        r"(`E21-D03 / 02 tier-rebuild-500`[^\n]*\| )dark( +\| PENDING)",
        r"\1light\2",
        regex=True,
    ),
    Mutation(
        "M-21",
        "G-PENPOT",
        "a Penpot file id",
        "page `E21-D03`, cited",
        "page `E21-D03` (" + "file" + "-id=0), cited",
    ),
    Mutation(
        "M-22",
        "G-RULING",
        "the heading claims a ruling",
        "defaults built; ruling pending (comment 6579618328)",
        "RULED (orchestrator, comment 6579618328)",
    ),
    Mutation(
        "M-23",
        "G-RULED",
        "a BQ default edited without a re-pin",
        "Default built: 10 boards, 3 with a light twin",
        "Default built: 9 boards, 3 with a light twin",
    ),
    Mutation(
        "M-24",
        "G-NOCLOSE",
        "a closing keyword",
        "### 19.1 Version line\n",
        "### 19.1 Version line\n\n" + "Clo" + "ses #503.\n",
    ),
    Mutation(
        "M-25",
        "G-NOCLOSE",
        "a closing keyword with no space",
        "### 19.1 Version line\n",
        "### 19.1 Version line\n\n" + "Fix" + "es#503.\n",
    ),
    Mutation(
        "M-26",
        "G-NOCLOSE",
        "a forbidden heading",
        "## 16. Heuristic evaluation",
        "## " + "What" + " this spec " + "fix" + "es\n\n## 16. Heuristic evaluation",
    ),
    Mutation(
        "M-27",
        "G-PUBLIC",
        "a URL",
        "Penpot: the file",
        "Penpot (" + "http" + "s://example.org): the file",
    ),
    Mutation(
        "M-28",
        "G-PUBLIC",
        "a local path",
        "the file `E21-D03 boards` (README:14)",
        "the file `E21-D03 boards` (" + "/" + "home/x/README:14)",
    ),
    Mutation(
        "M-29",
        "G-UNTOUCHED",
        "an owner document edited",
        "",
        "docs/plan/05-accessibility-standard.md",
        "paths",
    ),
    Mutation(
        "M-30",
        "G-UNTOUCHED",
        "a third catalogue line",
        "",
        "3\t0\tdocs/plan/14-screens-catalogue.md",
        "numstat",
    ),
    Mutation("M-31", "G-MUTLIST", "the list drifts", "| M-1  | G-CITE ", "| M-1  | G-AC   "),
)


def mutation_rows(ms: tuple[Mutation, ...] | None = None) -> str:
    ms = MUTATIONS if ms is None else ms
    head = (
        "| M    | Gate        | Mutation                                     |\n"
        "| ---- | ----------- | -------------------------------------------- |\n"
    )
    return head + "\n".join(f"| {m.mid:<4} | {m.gate:<11} | {m.what:<44} |" for m in ms)


def g_mutlist(t: Texts) -> list[Finding]:
    got = rows(section(t.spec, "### 19.3"))
    want = [[m.mid, m.gate, m.what] for m in MUTATIONS]
    return [] if got == want else [("G-MUTLIST", "section 19.3 differs from the tool")]


GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_cite,
    g_quote,
    g_version,
    g_ac,
    g_checklist,
    g_tabs,
    g_valid,
    g_cost,
    g_states,
    g_ad,
    g_t2,
    g_t2len,
    g_env,
    g_shed,
    g_tokens,
    g_contrast,
    g_cvd,
    g_boards,
    g_penpot,
    g_ruling,
    g_ruled,
    g_noclose,
    g_public,
    g_untouched,
    g_mutlist,
)


def gate_name(fn: Callable[[Texts], list[Finding]]) -> str:
    return "G-" + fn.__name__[2:].upper()


def run(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for fn in GATES:
        out += fn(t)
    return out


# ------------------------------------------------------------------ modes -------------------------
def read_texts() -> Texts:
    spec = (ROOT / SPEC_REL).read_text(encoding="utf-8")
    pin_path = ROOT / PIN_REL
    pins = pin_path.read_text(encoding="utf-8") if pin_path.exists() else ""
    paths, numstat = changed()
    return Texts(spec=spec, pins=pins, paths=paths, numstat=numstat)


def ascii_out(s: str) -> str:
    return s.encode("ascii", "backslashreplace").decode("ascii")


def check() -> int:
    t = read_texts()
    found = run(t)
    failed = {g for g, _ in found}
    for fn in GATES:
        name = gate_name(fn)
        if name not in failed:
            print(f"PASS {name}")
    for g, msg in found:
        print(ascii_out(f"FAIL {g}: {msg}"))
    print(f"FAIL {len(found)}")
    return 1 if found else 0


def apply(t: Texts, m: Mutation) -> Texts:
    if m.target == "paths":
        return replace(t, paths=tuple(sorted((*t.paths, m.new))))
    if m.target == "numstat":
        return replace(t, paths=tuple(sorted({*t.paths, CAT_REL})), numstat=m.new)
    text = t.spec if m.target == "spec" else t.pins
    if m.regex:
        new, n = re.subn(m.old, m.new, text, count=1)
    else:
        n = text.count(m.old)
        new = text.replace(m.old, m.new, 1)
    if n < 1:
        raise SystemExit(f"{m.mid}: anchor not found")
    return replace(t, spec=new) if m.target == "spec" else replace(t, pins=new)


def digest() -> str:
    h = hashlib.sha256()
    for rel in OWN:
        p = ROOT / rel
        h.update(p.read_bytes() if p.exists() else b"")
    return h.hexdigest()


def self_test() -> int:
    before = digest()
    t = read_texts()
    base = run(t)
    if base:
        print(ascii_out(f"self-test: baseline not clean: {base}"))
        return 1
    bad = 0
    for m in MUTATIONS:
        found = run(apply(t, m))
        gates = [g for g, _ in found]
        ok = gates == [m.gate]
        bad += 0 if ok else 1
        print(ascii_out(f"{'ok ' if ok else 'BAD'} {m.mid} {m.gate}: {m.what} -> {gates}"))
    if digest() != before:
        print("self-test: files on disk changed")
        return 1
    print(f"self-test: {len(MUTATIONS) - bad} of {len(MUTATIONS)} mutations caught by their gate")
    return 1 if bad else 0


def repin() -> int:
    spec = (ROOT / SPEC_REL).read_text(encoding="utf-8")
    head = "# E21-D03 ruled pins: sha256[:16] of each BQ bullet; written by --repin-ruled only\n"
    (ROOT / PIN_REL).write_text(head + "\n".join(pin_lines(spec)) + "\n", encoding="utf-8")
    print(f"pinned {len(pin_lines(spec))} BQ lines")
    return 0


def table_121() -> str:
    head = (
        "| Theme | Lowest stop | Ratio | Deuteranopia ΔE | Protanopia ΔE | Tritanopia ΔE "
        "| CVD set lowest stop | Ratio | Set smallest ΔE |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
    )
    return head + "\n".join("| " + " | ".join(measured_row(n)) + " |" for n in THEMES)


def table_122() -> str:
    head = "| Pair | Floor | dark | light | high-contrast |\n| --- | --- | --- | --- | --- |\n"
    return head + "\n".join(
        "| " + " | ".join(measured_pair(fg, bg, fl)) + " |" for fg, bg, fl in PAIRS
    )


def replace_table(spec: str, heading: str, table: str) -> str:
    start = spec.index(heading)
    t0 = spec.index("\n|", start) + 1
    end = t0
    lines = spec[t0:].split("\n")
    for line in lines:
        if not line.startswith("|"):
            break
        end += len(line) + 1
    return spec[:t0] + table + "\n" + spec[end:]


def fill() -> int:
    p = ROOT / SPEC_REL
    spec = p.read_text(encoding="utf-8")
    spec = replace_table(spec, "### 12.1", table_121())
    spec = replace_table(spec, "### 12.2", table_122())
    lvl = closest_level("dark", "deuteranopia")
    spec = re.sub(
        r"closest standard pair in dark is level \S+ \(`bid\.\S+` / `ask\.\S+`\)",
        f"closest standard pair in dark is level {lvl} (`bid.{lvl}` / `ask.{lvl}`)",
        spec,
    )
    start = spec.index("### 19.3")
    head_end = spec.index("\n", start) + 1
    p.write_text(spec[:head_end] + "\n" + mutation_rows() + "\n", encoding="utf-8")
    print("sections 12.1, 12.2 and 19.3 written")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--repin-ruled", action="store_true")
    mode.add_argument("--fill", action="store_true")
    args = ap.parse_args(argv)
    if args.check:
        return check()
    if args.self_test:
        return self_test()
    if args.repin_ruled:
        return repin()
    return fill()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
