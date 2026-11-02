#!/usr/bin/env python3
"""E21-D04 (#504) audit: the design-system pack for SCR-050's seven components (text first).

Offline and default-deny. It reads, AS TEXT at a pinned commit (`git show`), the plan and design
texts the pack cites at the base and the E21-D02 spec at its PR head, and, from the working tree,
the pack `docs/design/E21/E21-D04.md`, its hand-off `docs/design/E21/E21-D04-handoff.md` and the
pins file. The only repo code it runs is the two measuring modules the pack names:
`contrast_ratio()` of `docs/design/_tools/contrast_check.py` and `simulate()` / `delta_e76()` of
`docs/research/_tools/cvd_simulate.py`, loaded by path.

Gates (one PASS or FAIL line each): G-CITE, G-QUOTE, G-VERSION, G-AC, G-ENTRY, G-AROWS, G-SPLIT,
G-TOKENS, G-CONTRAST, G-CVD, G-LABEL, G-T2, G-ENV, G-BOARDS, G-BQ, G-RULED, G-NOCLOSE, G-PUBLIC,
G-PENPOT, G-UNTOUCHED and G-MUTLIST (the pack's section 12.3 equals this tool's list).

Pins (G-RULED): every bullet of the BQ section is pinned by its sha256 in
`e21_d04_ruled_pins.txt`; `--repin-ruled` is the only writer.

--self-test applies every mutation (M-n) in memory; each must add exactly one FAIL, from the gate
it names, to a clean baseline; the files on disk are checked byte-identical afterwards (sha256).

Usage (from the repo root):
  python3 -I docs/design/_tools/e21_d04_ds_audit.py --check
  python3 -I docs/design/_tools/e21_d04_ds_audit.py --self-test
  python3 -I docs/design/_tools/e21_d04_ds_audit.py --repin-ruled
  python3 -I docs/design/_tools/e21_d04_ds_audit.py --fill   (writes section 12.3)
Exit 0 = no FAIL; 1 = at least one FAIL.
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
BASE = "9b77e6b83"  # origin/main when the pack was written; every plan cite is read here
D02_HEAD = "7e1040260"  # PR #5488 (E21-D02) head; re-pinned to its merge commit when it merges
D02_PR = "#5488"
BQ_LIST = "6579619019"  # the BQ list on #504; its ruling is pending

SPEC_REL = "docs/design/E21/E21-D04.md"
HANDOFF_REL = "docs/design/E21/E21-D04-handoff.md"
TOOL_REL = "docs/design/_tools/e21_d04_ds_audit.py"
PIN_REL = "docs/design/_tools/e21_d04_ruled_pins.txt"
OWN = (SPEC_REL, HANDOFF_REL, TOOL_REL, PIN_REL)
BACKLOG_REL = "docs/plan/backlog/E21.json"
CAT15 = "docs/plan/15-component-catalogue.md"

PLAN = {
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": CAT15,
    "16": "docs/plan/16-design-system-brief.md",
    "26": "docs/plan/26-chart-engine-design.md",
}
KEYED = {
    "D02": ("docs/design/E21/E21-D02.md", D02_HEAD),
    "M": ("docs/design/research/e21-dom-heatmap.md", BASE),
    "CVDS": ("docs/design/E05/E05-D04-a11y-cvd-signoff.md", BASE),
    "D09E09": ("docs/design/E09/E09-D09.md", BASE),
    "D07E09": ("docs/design/E09/E09-D07.md", BASE),
    "D05E11": ("docs/design/E11/E11-D05.md", BASE),
    "D06E14": ("docs/design/E14/E14-D06.md", BASE),
    "R32": (".claude/rules/32-design-specs.md", BASE),
    "README": ("docs/design/README.md", BASE),
}
_KEYS = "|".join(sorted(KEYED, key=len, reverse=True))
CITE_RE = re.compile(rf"(?:`(\d\d)`|(?<![A-Za-z0-9-])({_KEYS})):(\d+)")

COMPONENTS = ("CMP-108", "CMP-111", "CMP-113", "CMP-227", "CMP-228", "CMP-229", "CMP-230")
ENTRY_FIELDS = ("**Variants**", "**States**", "**Tokens**", "**A11y**", "**Storybook**")
THEMES = {
    "dark": ("semantic-dark",),
    "light": ("semantic-dark", "semantic-light"),
    "high-contrast": ("semantic-dark", "semantic-hc"),
}
DEFICIENCIES = ("deuteranopia", "protanopia", "tritanopia")
CANVAS = "color.surface.canvas"
PALETTES = {"standard": "color.heatmap", "cvd": "color.cvd.heatmap"}
JND = 5.0  # the gate's CVD floor (E09-D09 section 12.1; tools/contrast)
# Section 5.4, row by row: (foreground, background, floor).
PAIRS: tuple[tuple[str, str, float], ...] = (
    ("color.text.primary", "color.buy.subtle", 4.5),
    ("color.text.primary", "color.sell.subtle", 4.5),
    ("color.text.tertiary", "color.surface.raised", 4.5),
    ("color.text.secondary", "color.surface.raised", 4.5),
    ("color.focus.ring", CANVAS, 3.0),
    ("color.buy.default", CANVAS, 4.5),
    ("color.sell.default", CANVAS, 4.5),
    ("color.text.secondary", CANVAS, 4.5),
    ("color.text.primary", "color.data-confidence.stale.surface", 4.5),
    ("color.data-confidence.stale.text", "color.data-confidence.stale.surface", 4.5),
    ("color.text.primary", "color.surface.raised", 4.5),
)
# AC 3: no CMP-111 A-row may carry the rendering contract's words.
SPLIT_RE = re.compile(r"textur|upload|cadence|frame budget", re.IGNORECASE)
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
# Names the pack quotes from owner texts as NOT shipped (A-rows retire them); never bound.
UNSHIPPED = frozenset({"font.mono", "color.surface.ownorder", "color.buy", "color.sell"})

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
        )
    ),
    re.IGNORECASE,
)
PENPOT_RE = re.compile(
    "|".join(("pen" + r"pot\.[a-z]", "team" + "-id", "file" + "-id", r"#/" + "workspace")),
    re.IGNORECASE,
)
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
TOKEN_RE = re.compile(
    r"`((?:color|space|size|type|font|opacity|border|radius)\.[A-Za-z0-9.*\-]+?)(\.\.\d+)?(\[\])?`"
)
FENCE_RE = re.compile(r"```text\n(.*?)\n```", re.DOTALL)
AROW_RE = re.compile(
    r"^### (A-\d+) · (CMP-\d+) · `15`:(\d+) · (replace|insert after)\n(.*?)(?=^### A-|\Z)",
    re.MULTILINE | re.DOTALL,
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
    return tuple(git("show", f"{rev}:{rel}").split("\n"))


def changed() -> tuple[str, ...]:
    """Paths that differ from `git merge-base HEAD origin/main`, the base as the fallback."""
    merge = git_ok("merge-base", "HEAD", "origin/main")
    base = merge.strip() if merge else BASE
    names = set(git("diff", "--name-only", base).split())
    names |= set(git("ls-files", "--others", "--exclude-standard").split())
    return tuple(sorted(names))


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


def de(a: str, b: str, deficiency: str) -> float:
    _, cvd = measurers()
    return float(cvd.delta_e76(cvd.simulate(a, deficiency), cvd.simulate(b, deficiency)))


def stops(prefix: str) -> list[str]:
    return [f"{prefix}.{s}.{i}" for s in ("bid", "ask") for i in range(1, 6)]


def contrast_row(name: str) -> list[str]:
    """Section 5.2's row for one theme: every stop of both palettes on the canvas."""
    t = theme(name)
    bg = t[CANVAS]
    every = stops("color.heatmap") + stops("color.cvd.heatmap")
    passing = sum(1 for k in every if ratio(t[k], bg) >= 3.0)
    low = min(stops("color.heatmap"), key=lambda k: ratio(t[k], bg))
    twin = min(stops("color.cvd.heatmap"), key=lambda k: ratio(t[k], bg))
    return [
        name,
        f"{passing} of {len(every)}",
        f"`{low}`",
        f"{ratio(t[low], bg):.2f}",
        f"`{twin}`",
        f"{ratio(t[twin], bg):.2f}",
    ]


def cvd_row(name: str, palette: str) -> list[str]:
    """Section 5.3's row: the closest bid/ask pair per deficiency and the closest adjacent step."""
    t = theme(name)
    pre = PALETTES[palette]
    side = [
        f"{min(de(t[f'{pre}.bid.{i}'], t[f'{pre}.ask.{i}'], d) for i in range(1, 6)):.1f}"
        for d in DEFICIENCIES
    ]
    steps = [
        (de(t[f"{pre}.{s}.{i}"], t[f"{pre}.{s}.{i + 1}"], d), f"{s}.{i}/{s}.{i + 1} {d[:4]}.")
        for s in ("bid", "ask")
        for i in range(1, 5)
        for d in DEFICIENCIES
    ]
    worst = min(steps)
    return [name, palette, *side, f"{worst[0]:.1f}", worst[1]]


def pair_row(fg: str, bg: str, floor: float) -> list[str]:
    vals = [f"{ratio(theme(n)[fg], theme(n)[bg]):.2f}" for n in THEMES]
    return [f"`{fg}` on `{bg}`", f"{floor:g}", *vals]


# ------------------------------------------------------------------ markdown helpers --------------
@dataclass(frozen=True)
class Texts:
    spec: str
    handoff: str
    pins: str
    paths: tuple[str, ...]


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


@dataclass(frozen=True)
class ARow:
    aid: str
    cmp: str
    line: int
    op: str
    old: str
    new: str


def arows(spec: str) -> list[ARow]:
    out: list[ARow] = []
    for m in AROW_RE.finditer(section(spec, "## §C Copy-ready A-rows")):
        blocks = FENCE_RE.findall(m.group(5))
        old, new = (blocks + ["", ""])[:2] if len(blocks) >= 2 else ("", "")
        out.append(ARow(m.group(1), m.group(2), int(m.group(3)), m.group(4), old, new))
    return out


def owner_text(t: Texts) -> str:
    """The pack without the Old blocks of section C, which quote owner text verbatim."""
    head, sep, tail = t.spec.partition("## §C Copy-ready A-rows")
    tail = re.sub(r"Old:\n\n```text\n.*?\n```", "Old: (quoted)", tail, flags=re.DOTALL)
    return head + sep + tail


# ------------------------------------------------------------------ gates -------------------------
Finding = tuple[str, str]  # (gate, message)


def g_cite(t: Texts) -> list[Finding]:
    bad = []
    for label, text in (("pack", t.spec), ("hand-off", t.handoff)):
        for m in CITE_RE.finditer(text):
            line = cite_line(m.group(1), m.group(2), int(m.group(3)))
            if line is None or not line.strip():
                bad.append(f"{label} {m.group(0)}")
    return [("G-CITE", f"unresolved cites: {', '.join(sorted(set(bad)))}")] if bad else []


def g_quote(t: Texts) -> list[Finding]:
    bad = []
    for r in rows(section(t.spec, "### 4.8 Copy")):
        if len(r) < 5 or not r[4].startswith("verbatim"):
            continue
        m = CITE_RE.search(r[3])
        line = cite_line(m.group(1), m.group(2), int(m.group(3))) if m else None
        if line is None or unquote(r[2]) not in line:
            bad.append(r[0])
    return [("G-QUOTE", f"not on the cited line: {', '.join(bad)}")] if bad else []


def g_version(t: Texts) -> list[Finding]:
    v = section(t.spec, "### 12.1 Version line")
    need = (BASE, D02_HEAD, D02_PR, "re-pinned to its merge commit", "if #440's PR 1 merges as is")
    miss = [n for n in need if n not in v]
    if f"Base `origin/main` `{BASE}`" not in t.spec:
        miss.append("Inputs pinned base")
    return [("G-VERSION", f"missing: {', '.join(miss)}")] if miss else []


def g_ac(t: Texts) -> list[Finding]:
    tickets = json.loads("\n".join(at(BASE, BACKLOG_REL)))
    body = next(str(x.get("body", "")) for x in tickets if x.get("key") == "E21-D04")
    names = re.findall(r"Scenario: (.+)", body)
    trace = section(t.spec, "## Acceptance-criteria and DoD trace")
    miss = [n for n in names if f'AC "{n.strip()}"' not in trace]
    dod = re.findall(r"- \[ \] (.+)", body)
    dod_rows = [r for r in rows(trace) if r and r[0].startswith("DoD ")]
    bad = []
    if len(names) != 3 or miss:
        bad.append(f"scenario names not verbatim in the trace: {miss or names}")
    if len(dod_rows) != len(dod):
        bad.append(f"{len(dod_rows)} DoD rows for {len(dod)} DoD items")
    return [("G-AC", "; ".join(bad))] if bad else []


def g_entry(t: Texts) -> list[Finding]:
    bad = []
    for c in COMPONENTS:
        m = re.search(rf"^### 4\.\d {c} ", t.spec, re.MULTILINE)
        if not m:
            bad.append(f"{c}: no section 4 entry")
            continue
        body = section(t.spec[m.start() :], t.spec[m.start() :].split("\n")[0])
        bad += [f"{c}: {f}" for f in ENTRY_FIELDS if f not in body]
        if f"## Handoff checklist — {c} " not in t.handoff:
            bad.append(f"{c}: no hand-off block")
    return [("G-ENTRY", "; ".join(bad))] if bad else []


def g_arows(t: Texts) -> list[Finding]:
    got = arows(t.spec)
    bad = [] if got else ["no A-rows"]
    for i, a in enumerate(got, 1):
        if a.aid != f"A-{i}":
            bad.append(f"{a.aid} out of order")
        line = cite_line("15", None, a.line)
        if a.op == "replace" and (line is None or a.old != line):
            bad.append(f"{a.aid}: Old is not `15`:{a.line} verbatim")
        if a.op == "insert after" and (line is None or a.old != "—"):
            bad.append(f"{a.aid}: insert row must quote no Old")
        if not a.new.strip() or a.new == a.old:
            bad.append(f"{a.aid}: empty or unchanged New")
    count = re.search(r"(\d+) rows\.", section(t.spec, "## §C Copy-ready A-rows"))
    if not count or int(count.group(1)) != len(got):
        bad.append(f"the row count is not {len(got)}")
    return [("G-AROWS", "; ".join(bad))] if bad else []


def g_split(t: Texts) -> list[Finding]:
    bad = [a.aid for a in arows(t.spec) if a.cmp == "CMP-111" and SPLIT_RE.search(a.new)]
    route = rows(section(t.spec, "## 6. The responsibility split"))
    if not any(
        "texture upload cost" in r[0] and "CMP-193" in r[1] and "#650" in r[1] for r in route
    ):
        bad.append("no routing row sends texture upload cost to CMP-193 / E21-T05 #650")
    return [("G-SPLIT", f"CMP-111 rows carry the rendering contract: {bad}")] if bad else []


def g_tokens(t: Texts) -> list[Finding]:
    names = token_names()
    bad = []
    for label, text in (("pack", owner_text(t)), ("hand-off", t.handoff)):
        for m in TOKEN_RE.finditer(text):
            name, rng, ramp = m.group(1), m.group(2), m.group(3)
            if ramp or name in UNSHIPPED:
                continue  # the owner texts' unshipped names, quoted for their A-rows
            if name.endswith(".*"):
                ok = any(n.startswith(name[:-1]) for n in names)
            elif rng:
                stem, first = name.rsplit(".", 1)
                span = range(int(first), int(rng[2:]) + 1) if first.isdigit() else range(0)
                ok = bool(span) and all(f"{stem}.{i}" in names for i in span)
            else:
                ok = name in names
            if not ok:
                bad.append(f"{label} {name}{rng or ''}")
    for a in arows(t.spec):
        bad += [f"{a.aid} binds {n}" for n in UNSHIPPED if f"`{n}`" in a.new]
    return [("G-TOKENS", f"unknown: {', '.join(sorted(set(bad)))}")] if bad else []


def g_contrast(t: Texts) -> list[Finding]:
    bad = []
    got = {r[0]: r for r in rows(section(t.spec, "### 5.2 Contrast"))}
    for name in THEMES:
        want = contrast_row(name)
        if got.get(name, [])[:6] != want:
            bad.append(f"{name}: measured {want[1:]}")
        if not want[1].startswith("20 of"):
            bad.append(f"{name}: a stop below 3:1")
    pairs = {r[0]: r for r in rows(section(t.spec, "### 5.4 Other pairs"))}
    for fg, bg, floor in PAIRS:
        want = pair_row(fg, bg, floor)
        if pairs.get(want[0], [])[:5] != want:
            bad.append(f"pair {want[0]}: measured {want[1:]}")
        if min(float(v) for v in want[2:]) < floor:
            bad.append(f"pair {want[0]} below {floor:g}")
    if len(pairs) != len(PAIRS):
        bad.append(f"{len(pairs)} pair rows for {len(PAIRS)} pairs")
    hc_heat = [k for k in token_file("semantic-hc") if "heatmap" in k]
    if "`semantic-hc` overrides no heatmap token" not in t.spec or hc_heat:
        bad.append(f"the high-contrast resolution is not as stated ({hc_heat})")
    return [("G-CONTRAST", "; ".join(bad))] if bad else []


def g_cvd(t: Texts) -> list[Finding]:
    bad = []
    got = {(r[0], r[1]): r for r in rows(section(t.spec, "### 5.3 Colour vision"))}
    for name in THEMES:
        for palette in PALETTES:
            want = cvd_row(name, palette)
            if got.get((name, palette), [])[:7] != want:
                bad.append(f"{name}/{palette}: measured {want[2:]}")
    twins = [float(cvd_row(n, "cvd")[c]) for n in THEMES for c in (2, 3, 4)]
    if min(twins) < JND:
        bad.append("a CVD-twin bid/ask pair under the floor")
    return [("G-CVD", "; ".join(bad))] if bad else []


def render_label(template: str, values: dict[str, str], flags: frozenset[str]) -> str:
    def group(m: re.Match[str]) -> str:
        inner = m.group(1)
        keys = re.findall(r"\{(\w+)\}", inner)
        if keys:
            return inner if all(k in values for k in keys) else ""
        return inner if inner.strip("; ") in flags else ""

    body = re.sub(r"\[([^\]]*)\]", group, template)
    return re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), m.group(0)), body)


def g_label(t: Texts) -> list[Finding]:
    s41 = section(t.spec, "### 4.1 CMP-108")
    m = re.search(r"\*\*Template\*\*: `([^`]+)`", s41)
    tickets = json.loads("\n".join(at(BASE, BACKLOG_REL)))
    body = next(str(x.get("body", "")) for x in tickets if x.get("key") == "E21-D04")
    want = re.search(r'"(Price [^"]+)"', body)
    if not m or not want:
        return [("G-LABEL", "no template or no normative sentence")]
    tpl = m.group(1)
    values = {
        "price": "65,432",
        "bid": "1.2",
        "ask": "0.8",
        "own": "your buy order 0.5 at this price",
    }
    got = render_label(tpl, values, frozenset())
    bad = [] if got == want.group(1) else [f"renders {got!r}"]
    for clause in ("best bid", "best ask", "at the mark", "stale", "estimated"):
        if f"; {clause}]" not in tpl and f"{clause}" not in tpl:
            bad.append(f"no {clause} clause")
    if re.search(r"account", tpl, re.IGNORECASE):
        bad.append("the row label names an account")
    return [("G-LABEL", "; ".join(bad))] if bad else []


def g_t2(t: Texts) -> list[Finding]:
    r3 = next((ln for ln in t.spec.split("\n") if ln.startswith("- **R-3 ")), "")
    bad = [m for m in T2_MARKERS if m not in r3]
    if "never gated on the arm" not in t.spec:
        bad.append("R-4")
    for c in ("CMP-108", "CMP-229", "CMP-230"):
        m = re.search(rf"^### 4\.\d {c} .*$", t.spec, re.MULTILINE)
        body = section(t.spec[m.start() :], m.group(0)) if m else ""
        if "R-3" not in body:
            bad.append(f"{c} does not cite R-3")
    return [("G-T2", f"missing: {', '.join(bad)}")] if bad else []


def g_env(t: Texts) -> list[Finding]:
    s8 = section(t.spec, "## 8. C-2.11")
    need = ("C-2.11 is a hard constraint", "never mixes environments", "synthetic accounts")
    bad = [n for n in need if n not in s8]
    a230 = " ".join(a.new for a in arows(t.spec) if a.cmp == "CMP-230")
    if "never mixes environments" not in a230 or "already filtered" not in a230:
        bad.append("CMP-230 A-rows")
    return [("G-ENV", f"missing: {', '.join(bad)}")] if bad else []


def g_boards(t: Texts) -> list[Finding]:
    got = rows(section(t.spec, "## 0. Status"))
    bad = []
    twins = sum(1 for r in got if len(r) > 3 and "light" in r[3])
    if not 0 < len(got) <= 10:
        bad.append(f"{len(got)} boards")
    if twins * 3 > len(got):
        bad.append(f"{twins} light twins of {len(got)}")
    for r in got:
        if len(r) < 5 or r[4] != "PENDING" or not r[1].startswith(f"`E21-D04 / {r[0]} "):
            bad.append(f"board {r[0] if r else '?'}")
    if "**Not drawn — the text is binding**" not in t.spec:
        bad.append("not-drawn paragraph")
    if "page `E21-D04`" not in t.spec or "page id" not in t.spec:
        bad.append("page by name and id")
    return [("G-BOARDS", "; ".join(bad))] if bad else []


def g_bq(t: Texts) -> list[Finding]:
    head = "## The questions BQ-0 … BQ-15 — defaults built; ruling pending " f"(comment {BQ_LIST})"
    bad = [] if head in t.spec.split("\n") else ["heading"]
    bullets = bq_bullets(t.spec)
    ids = [m.group(1) for b in bullets if (m := re.match(r"- \*\*(BQ-\d+)", b))]
    if ids != [f"BQ-{n}" for n in range(16)]:
        bad.append(f"ids {ids}")
    bad += [b[:10] for b in bullets if "Default built:" not in b or "RULED" in b]
    return [("G-BQ", "; ".join(bad))] if bad else []


def g_ruled(t: Texts) -> list[Finding]:
    want = [ln for ln in t.pins.split("\n") if ln and not ln.startswith("#")]
    got = pin_lines(t.spec)
    if want != got:
        diff = sorted(set(want) ^ set(got))
        return [("G-RULED", f"BQ lines differ from the pins: {[d.split()[0] for d in diff]}")]
    return []


def g_noclose(t: Texts) -> list[Finding]:
    bad = []
    for label, text in (("pack", t.spec), ("hand-off", t.handoff), ("pins", t.pins)):
        bad += [f"{label}: {m.group(0)}" for m in KEYWORD_RE.finditer(text)]
        bad += [f"{label}: heading" for _ in HEADING_RE.finditer(text)]
    return [("G-NOCLOSE", "; ".join(bad))] if bad else []


def g_public(t: Texts) -> list[Finding]:
    bad = []
    for label, text in (("pack", t.spec), ("hand-off", t.handoff), ("pins", t.pins)):
        bad += [f"{label}: {m.group(0)}" for m in PUBLIC_RE.finditer(text)]
        bad += [f"{label}: stray comment" for _ in COMMENT_RE.finditer(text)]
    return [("G-PUBLIC", "; ".join(bad))] if bad else []


def g_penpot(t: Texts) -> list[Finding]:
    bad = []
    for label, text in (("pack", t.spec), ("hand-off", t.handoff), ("pins", t.pins)):
        bad += [f"{label}: {m.group(0)}" for m in PENPOT_RE.finditer(text)]
    return [("G-PENPOT", f"Penpot instance reference: {bad}")] if bad else []


def g_untouched(t: Texts) -> list[Finding]:
    bad = [p for p in t.paths if p not in OWN]
    return [("G-UNTOUCHED", f"outside the ticket: {', '.join(bad)}")] if bad else []


@dataclass(frozen=True)
class Mutation:
    mid: str
    gate: str
    what: str
    old: str
    new: str
    target: str = "spec"  # spec | handoff | pins | paths


MUTATIONS: tuple[Mutation, ...] = (
    Mutation("M-1", "G-CITE", "a cite past the end of `26`", "`26`:391", "`26`:99999"),
    Mutation(
        "M-2",
        "G-QUOTE",
        "W-3 reworded off its line",
        '"3 orders · buy 1.2 BTC"',
        '"4 orders · buy 1.2 BTC"',
    ),
    Mutation(
        "M-3",
        "G-VERSION",
        "the version line drops the re-pin",
        "re-pinned to its merge commit",
        "kept at its head",
    ),
    Mutation("M-4", "G-AC", "a scenario name reworded", 'AC "Ramp contrast holds"', 'AC "Ramp'),
    Mutation(
        "M-5",
        "G-ENTRY",
        "CMP-228 loses its hand-off block",
        "Handoff checklist — CMP-228 ",
        "x ",
        "handoff",
    ),
    Mutation(
        "M-6",
        "G-AROWS",
        "an Old drifts from its line",
        "- **Tokens**: `color.buy/sell`",
        "- **Tokens**: `color.buy`",
    ),
    Mutation(
        "M-7",
        "G-SPLIT",
        "a CMP-111 row takes the upload budget",
        "LowDensity (a static frame)",
        "LowDensity (a static frame; texture upload budget)",
    ),
    Mutation(
        "M-8",
        "G-TOKENS",
        "an A-row binds an unshipped token",
        "`color.buy.subtle` / `color.sell.subtle` (the size bars)",
        "`color.surface.ownorder` (the size bars)",
    ),
    Mutation(
        "M-9",
        "G-CONTRAST",
        "a written ratio drifts",
        "| dark          | 20 of 20",
        "| dark          | 19 of 20",
    ),
    Mutation(
        "M-10",
        "G-CVD",
        "a written distance drifts",
        "| dark          | standard |",
        "| dark          | standrd  |",
    ),
    Mutation(
        "M-11",
        "G-LABEL",
        "the template reorders bid and ask",
        "`Price {price}; bid size {bid}; ask size {ask}",
        "`Price {price}; ask size {ask}; bid size {bid}",
    ),
    Mutation(
        "M-12",
        "G-T2",
        "R-3 loses the opacity ban",
        ", never `opacity.disabled` (G-T2.2)",
        " (G-T2.2)",
    ),
    Mutation(
        "M-13",
        "G-ENV",
        "C-2.11 no longer stated as hard",
        "C-2.11 is a hard constraint",
        "C-2.11 applies",
    ),
    Mutation(
        "M-14",
        "G-BOARDS",
        "a fourth light twin",
        "| dark         | PENDING |",
        "| dark + light | PENDING |",
    ),
    Mutation(
        "M-15", "G-BQ", "the heading claims a ruling", "defaults built; ruling pending", "RULED"
    ),
    Mutation(
        "M-16", "G-RULED", "a BQ default edited without a re-pin", "no new id;", "one new id;"
    ),
    Mutation("M-17", "G-NOCLOSE", "a closing keyword", "Refs #504", "Clo" + "ses #504"),
    Mutation("M-18", "G-NOCLOSE", "a closing keyword with no space", "Refs #504", "fix" + "es#504"),
    Mutation(
        "M-19",
        "G-PUBLIC",
        "a URL",
        "(the size bars)",
        "(the size bars, " + "http" + "s://x.example)",
    ),
    Mutation(
        "M-20", "G-PENPOT", "a Penpot file id", "page `E21-D04`", "page `E21-D04` " + "file" + "-id"
    ),
    Mutation(
        "M-21",
        "G-UNTOUCHED",
        "an owner document edited",
        "",
        "docs/plan/15-component-catalogue.md",
        "paths",
    ),
    Mutation("M-22", "G-MUTLIST", "the list drifts", "| M-22 | G-MUTLIST", "| M-99 | G-MUTLIST"),
    Mutation("M-23", "G-RULED", "a pin edited, its BQ line unchanged", "BQ-0 ", "BQ-0 0", "pins"),
)


def mutation_rows(ms: tuple[Mutation, ...] = MUTATIONS) -> str:
    head = (
        "| M    | Gate        | Mutation                                 |\n"
        "| ---- | ----------- | ---------------------------------------- |\n"
    )
    return head + "\n".join(f"| {m.mid:<4} | {m.gate:<11} | {m.what:<40} |" for m in ms)


def g_mutlist(t: Texts) -> list[Finding]:
    got = rows(section(t.spec, "### 12.3"))
    want = [[m.mid, m.gate, m.what] for m in MUTATIONS]
    return [] if got == want else [("G-MUTLIST", "section 12.3 differs from the tool")]


GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_cite,
    g_quote,
    g_version,
    g_ac,
    g_entry,
    g_arows,
    g_split,
    g_tokens,
    g_contrast,
    g_cvd,
    g_label,
    g_t2,
    g_env,
    g_boards,
    g_bq,
    g_ruled,
    g_noclose,
    g_public,
    g_penpot,
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
    def read(rel: str) -> str:
        p = ROOT / rel
        return p.read_text(encoding="utf-8") if p.exists() else ""

    return Texts(
        spec=read(SPEC_REL), handoff=read(HANDOFF_REL), pins=read(PIN_REL), paths=changed()
    )


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
    for name in THEMES:
        print(ascii_out("MEASURED contrast " + " | ".join(contrast_row(name))))
        for palette in PALETTES:
            print(ascii_out("MEASURED cvd " + " | ".join(cvd_row(name, palette))))
    for fg, bg, floor in PAIRS:
        print(ascii_out("MEASURED pair " + " | ".join(pair_row(fg, bg, floor))))
    print(f"FAIL {len(found)}")
    return 1 if found else 0


def apply(t: Texts, m: Mutation) -> Texts:
    if m.target == "paths":
        return replace(t, paths=tuple(sorted((*t.paths, m.new))))
    text = {"spec": t.spec, "handoff": t.handoff, "pins": t.pins}[m.target]
    if m.old not in text:
        raise SystemExit(f"{m.mid}: anchor not found")
    new = text.replace(m.old, m.new, 1)
    if m.target == "spec":
        return replace(t, spec=new)
    if m.target == "handoff":
        return replace(t, handoff=new)
    return replace(t, pins=new)


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
    head = "# E21-D04 ruled pins: sha256[:16] of each BQ bullet; written by --repin-ruled only\n"
    (ROOT / PIN_REL).write_text(head + "\n".join(pin_lines(spec)) + "\n", encoding="utf-8")
    print(f"pinned {len(pin_lines(spec))} BQ lines")
    return 0


def fill() -> int:
    p = ROOT / SPEC_REL
    spec = p.read_text(encoding="utf-8")
    start = spec.index("### 12.3")
    head_end = spec.index("\n", start) + 1
    nxt = spec.find("\n## ", head_end)
    tail = spec[nxt:] if nxt >= 0 else "\n"
    p.write_text(spec[:head_end] + "\n" + mutation_rows() + "\n" + tail, encoding="utf-8")
    print("section 12.3 written")
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
