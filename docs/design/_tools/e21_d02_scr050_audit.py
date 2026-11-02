#!/usr/bin/env python3
"""E21-D02 (#440) audit: the SCR-050 Heatmap + DOM ladder hi-fi spec (text first; boards later).

Offline and default-deny. It reads, AS TEXT at a pinned commit (`git show`), the plan and design
texts the spec cites at the base and the E21-D01 memo at its PR head, and, from the working tree,
the spec `docs/design/E21/E21-D02.md` and the pins file. The only repo code it runs is the two
measuring modules the spec names: `contrast_ratio()` of `docs/design/_tools/contrast_check.py`
and `simulate()` / `delta_e76()` of `docs/research/_tools/cvd_simulate.py`, loaded by path.

Gates (one PASS or FAIL line each): G-CITE, G-QUOTE, G-VERSION, G-AC, G-CHECKLIST, G-STATES,
G-AD, G-T2, G-T2LEN, G-TOKENS, G-CONTRAST, G-CVD, G-DOM, G-ENV, G-BOARDS, G-PENDING, G-RULED,
G-NOCLOSE, G-PUBLIC, G-UNTOUCHED and G-MUTLIST (the spec's section 16.3 equals this tool's list).

Pins (G-RULED): every bullet of the BQ section is pinned by its sha256 in
`e21_d02_ruled_pins.txt`; `--repin-ruled` is the only writer.

--self-test applies every mutation (M-n) in memory; each must add exactly one FAIL, from the gate
it names, to a clean baseline; the files on disk are checked byte-identical afterwards (sha256).

Usage (from the repo root):
  python3 -I docs/design/_tools/e21_d02_scr050_audit.py --check
  python3 -I docs/design/_tools/e21_d02_scr050_audit.py --self-test
  python3 -I docs/design/_tools/e21_d02_scr050_audit.py --repin-ruled
  python3 -I docs/design/_tools/e21_d02_scr050_audit.py --fill   (writes section 16.3)
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
BASE = "67fe8b526"  # origin/main when the spec was written; every plan cite is read here
M_HEAD = "934a56142"  # PR #5382 (E21-D01) head; re-pinned to its merge commit when it merges
M_PR = "#5382"
RULING_PENDING = "6576276584"  # the BQ list on #440; the ruling will answer it

SPEC_REL = "docs/design/E21/E21-D02.md"
TOOL_REL = "docs/design/_tools/e21_d02_scr050_audit.py"
PIN_REL = "docs/design/_tools/e21_d02_ruled_pins.txt"
CAT_REL = "docs/plan/14-screens-catalogue.md"
IMG_PREFIX = "docs/design/E21/img/E21-D02-"
OWN = (SPEC_REL, TOOL_REL, PIN_REL)
BACKLOG_REL = "docs/plan/backlog/E21.json"

PLAN = {
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": CAT_REL,
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "23": "docs/plan/23-ws-protocol.md",
    "24": "docs/plan/24-internal-schemas.md",
    "26": "docs/plan/26-chart-engine-design.md",
}
KEYED = {
    "M": ("docs/design/research/e21-dom-heatmap.md", M_HEAD),
    "D09E09": ("docs/design/E09/E09-D09.md", BASE),
    "D01E17": ("docs/design/E17/E17-D01.md", BASE),
    "D02E17": ("docs/design/E17/E17-D02.md", BASE),
    "D03E17": ("docs/design/E17/E17-D03.md", BASE),
    "D02E30": ("docs/design/E30/E30-D02.md", BASE),
    "D04E11": ("docs/design/E11/E11-D04.md", BASE),
    "D05E16": ("docs/design/E16/E16-D05.md", BASE),
    "D10E08": ("docs/design/E08/E08-D10.md", BASE),
    "D11E08": ("docs/design/E08/E08-D11.md", BASE),
    "D02E06": ("docs/design/E06/E06-D02.md", BASE),
    "CVDS": ("docs/design/E05/E05-D04-a11y-cvd-signoff.md", BASE),
    "TM": ("docs/security/threat-models/e21-dom-heatmap.md", BASE),
    "K04": ("docs/plan/spikes/E06-K04.md", BASE),
    "M0R": ("docs/plan/spikes/E06-M0-report.md", BASE),
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
TEXT_TOKENS = ("color.text.primary", "color.text.secondary")
T2_LEN_ROWS = ("W-3", "W-20")
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

# Deny lists are assembled from fragments so this file never matches itself.
_KW = "|".join(("clo" + "se[sd]?", "fix" + "(?:e[sd])?", "resol" + "ve[sd]?"))
KEYWORD_RE = re.compile(rf"\b(?:{_KW}):?\s+#\d+", re.IGNORECASE)
HEADING_RE = re.compile(
    r"^#+\s*" + "What" + r" this\b[^\n]*\b" + "fix" + "es", re.IGNORECASE | re.MULTILINE
)
PUBLIC_RE = re.compile(
    "|".join(
        (
            "http" + r"s?://",
            r"\bwww" + r"\.",
            "/" + "home/",
            r"\.lo" + r"cal\b",
            "pen" + r"pot\.[a-z]",
            "scratch" + "-",
            "bas" + "iltt",
            r"\bhcl" + "-",
            r"\bhpe" + "-",
            r"\bwor" + r"ker\b",
        )
    ),
    re.IGNORECASE,
)
DOM_RE = re.compile(
    r"\b(?:each|every|per)\s+(?:heatmap\s+)?cell\b[^.|]*?\b(?:button|focusable|tabindex|DOM node)",
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


@functools.cache
def at(rev: str, rel: str) -> tuple[str, ...]:
    return tuple(git("show", f"{rev}:{rel}").split("\n"))


def changed() -> tuple[tuple[str, ...], str]:
    base = git("merge-base", "HEAD", "origin/main").strip()
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


def measured_row(name: str) -> list[str]:
    """The section 7.3 row this tool derives for one theme, cell by cell."""
    _, cvd = measurers()
    t = theme(name)
    bg = t[CANVAS]

    def lowest(prefix: str) -> tuple[str, float]:
        best = min(stops(prefix), key=lambda k: ratio(t[k], bg))
        return best, ratio(t[best], bg)

    def smallest(prefix: str, deficiency: str) -> float:
        return min(
            float(
                cvd.delta_e76(
                    cvd.simulate(t[f"{prefix}.bid.{i}"], deficiency),
                    cvd.simulate(t[f"{prefix}.ask.{i}"], deficiency),
                )
            )
            for i in range(1, 6)
        )

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
    for r in rows(section(t.spec, "## 12. Copy deck")):
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
    v = section(t.spec, "### 16.1 Version line")
    need = (BASE, M_HEAD, M_PR, "re-pinned to the merge commit")
    miss = [n for n in need if n not in v]
    if f"Base `origin/main` `{BASE}`" not in t.spec:
        miss.append("Inputs pinned base")
    return [("G-VERSION", f"missing: {', '.join(miss)}")] if miss else []


def g_ac(t: Texts) -> list[Finding]:
    tickets = json.loads("\n".join(at(BASE, BACKLOG_REL)))
    body = next(str(x.get("body", "")) for x in tickets if x.get("key") == "E21-D02")
    names = re.findall(r"Scenario: (.+)", body)
    trace = section(t.spec, "## Acceptance-criteria and DoD trace")
    miss = [n for n in names if f'AC "{n.strip()}"' not in trace]
    if len(names) != 3 or miss:
        return [("G-AC", f"scenario names not verbatim in the trace: {miss or names}")]
    return []


def g_checklist(t: Texts) -> list[Finding]:
    def items(line_no: int) -> list[str]:
        line = cite_line("14", None, line_no) or ""
        parts = [p.strip() for p in line.split("[ ]")[1:]]
        return [p.removesuffix(".").strip() for p in parts if p]

    tables = all_tables(section(t.spec, "### AC.1"))
    bad: list[str] = []
    for idx, (line_no, count) in enumerate(((1224, 7), (1221, 6))):
        want = items(line_no)
        got = tables[idx] if idx < len(tables) else []
        if len(want) != count or len(got) != count:
            bad.append(f"table {idx + 1}: {len(got)} rows for {len(want)} items")
            continue
        for item, r in zip(want, got, strict=True):
            if len(r) < 4 or r[1] != item or not r[2]:
                bad.append(f"item {r[0] if r else '?'}")
        if idx == 0 and "PENDING E21-K01 #603" not in got[6][3]:
            bad.append("item 7 not PENDING")
    return [("G-CHECKLIST", "; ".join(bad))] if bad else []


def state_rows(spec: str) -> list[list[str]]:
    return rows(section(spec, "## 4. States"))


def board_rows(spec: str) -> list[list[str]]:
    return rows(section(spec, "## 0. Status"))


def g_states(t: Texts) -> list[Finding]:
    boards = {r[0]: r[2] for r in board_rows(t.spec) if len(r) > 2}
    frames: set[str] = set()
    bad = []
    for r in state_rows(t.spec):
        m = re.search(r"`(SCR-050/[a-z0-9-]+)`", r[0])
        if not m or len(r) < 8:
            bad.append(r[0])
            continue
        frames.add(m.group(1))
        if m.group(1) not in boards.get(r[7], ""):
            bad.append(f"{m.group(1)} not on board {r[7]}")
    drawn = set(re.findall(r"SCR-050/[a-z0-9-]+", " ".join(boards.values())))
    bad += [f"{d} drawn, no state row" for d in sorted(drawn - frames)]
    return [("G-STATES", "; ".join(bad))] if bad else []


def g_ad(t: Texts) -> list[Finding]:
    got = rows(section(t.spec, "### 11.2"))
    ids = [r[0] for r in got]
    bad = [] if ids == [f"AD-{n}" for n in range(1, 11)] else [f"ids {ids}"]
    for r in got:
        if len(r) < 4 or not r[3].startswith(("satisfied", "routed")):
            bad.append(f"{r[0]} verdict")
        elif r[3].startswith("satisfied") and "board" not in r[2]:
            bad.append(f"{r[0]} has no frame")
    return [("G-AD", "; ".join(bad))] if bad else []


def g_t2(t: Texts) -> list[Finding]:
    r3 = next((ln for ln in t.spec.split("\n") if ln.startswith("- **R-3 ")), "")
    bad = [m for m in T2_MARKERS if m not in r3]
    if "never gated on the arm" not in t.spec:
        bad.append("R-4")
    bad += [f"{r[0]} T2 cell" for r in state_rows(t.spec) if len(r) < 7 or not r[6]]
    return [("G-T2", f"missing: {', '.join(bad)}")] if bad else []


def g_t2len(t: Texts) -> list[Finding]:
    bad = []
    for r in rows(section(t.spec, "## 12. Copy deck")):
        if r[0] in T2_LEN_ROWS:
            s = unquote(r[2])
            if len(s) > 60 or not s.endswith(".") or ". " in s or re.search(r"\d", s):
                bad.append(f"{r[0]} ({len(s)} chars)")
    return [("G-T2LEN", "; ".join(bad))] if bad else []


def g_tokens(t: Texts) -> list[Finding]:
    names = token_names()
    bad = []
    for m in TOKEN_RE.finditer(t.spec):
        name, rng, ramp = m.group(1), m.group(2), m.group(3)
        if ramp:
            continue  # the ticket's unshipped names, quoted for A-1
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


def table73(spec: str) -> list[list[str]]:
    return rows(section(spec, "### 7.3"))


def g_contrast(t: Texts) -> list[Finding]:
    bad = []
    got = {r[0]: r for r in table73(t.spec)}
    for name in THEMES:
        want = measured_row(name)
        r = got.get(name, [])
        if len(r) < 9 or [r[1], r[2], r[6], r[7]] != [want[1], want[2], want[6], want[7]]:
            bad.append(f"{name}: written {r[1:3] + r[6:8] if r else []}, measured {want[1:3]}")
        tt = theme(name)
        for tok in TEXT_TOKENS:
            if ratio(tt[tok], tt[CANVAS]) < 4.5:
                bad.append(f"{name} {tok} below 4.5")
        if ratio(tt["color.focus.ring"], tt[CANVAS]) < 3.0:
            bad.append(f"{name} focus ring below 3")
        if float(want[2]) < 3.0:
            bad.append(f"{name} heatmap stop below 3")
    return [("G-CONTRAST", "; ".join(bad))] if bad else []


def g_cvd(t: Texts) -> list[Finding]:
    bad = []
    got = {r[0]: r for r in table73(t.spec)}
    for name in THEMES:
        want = measured_row(name)
        r = got.get(name, [])
        if len(r) < 9 or [r[3], r[4], r[5], r[8]] != [want[3], want[4], want[5], want[8]]:
            bad.append(f"{name}: measured {want[3:6] + want[8:]}")
    return [("G-CVD", "; ".join(bad))] if bad else []


def g_dom(t: Texts) -> list[Finding]:
    hits = [m.group(0) for m in DOM_RE.finditer(t.spec)]
    return [("G-DOM", f"per-cell DOM affordance: {hits}")] if hits else []


def g_env(t: Texts) -> list[Finding]:
    s6 = section(t.spec, "## 6. DEMO and LIVE")
    need = ("C-2.11 is a hard constraint", "never the feed", "separate frames", "never shed")
    bad = [n for n in need if n not in s6]
    frames = " ".join(r[0] for r in state_rows(t.spec))
    bad += [f for f in ("SCR-050/demo", "SCR-050/live") if f not in frames]
    return [("G-ENV", f"missing: {', '.join(bad)}")] if bad else []


def g_boards(t: Texts) -> list[Finding]:
    got = board_rows(t.spec)
    bad = []
    twins = sum(1 for r in got if len(r) > 3 and "light" in r[3])
    if not 0 < len(got) <= 10:
        bad.append(f"{len(got)} boards")
    if twins * 3 > len(got):
        bad.append(f"{twins} light twins of {len(got)}")
    for r in got:
        if len(r) < 5 or r[4] != "PENDING" or not r[1].startswith(f"`E21-D02 / {r[0]} "):
            bad.append(f"board {r[0] if r else '?'}")
    if "**Not drawn — the text is binding**" not in t.spec:
        bad.append("not-drawn paragraph")
    if "page `E21-D02`" not in t.spec or "page id" not in t.spec:
        bad.append("page by name and id")
    return [("G-BOARDS", "; ".join(bad))] if bad else []


def g_pending(t: Texts) -> list[Finding]:
    head = (
        f"## The questions BQ-0 … BQ-15 — defaults built; ruling pending (comment {RULING_PENDING})"
    )
    bad = [] if head in t.spec.split("\n") else ["heading"]
    bullets = bq_bullets(t.spec)
    ids = [m.group(1) for b in bullets if (m := re.match(r"- \*\*(BQ-\d+)", b))]
    if ids != [f"BQ-{n}" for n in range(16)]:
        bad.append(f"ids {ids}")
    bad += [b[:12] for b in bullets if "Default built:" not in b or "RULED" in b]
    return [("G-PENDING", "; ".join(bad))] if bad else []


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
    if CAT_REL in t.paths and t.numstat.split()[:2] != ["1", "0"]:
        bad.append(f"{CAT_REL} is not one added line ({t.numstat})")
    return [("G-UNTOUCHED", f"outside the ticket: {', '.join(bad)}")] if bad else []


@dataclass(frozen=True)
class Mutation:
    mid: str
    gate: str
    what: str
    old: str
    new: str
    target: str = "spec"  # spec | pins | paths
    regex: bool = False


MUTATIONS: tuple[Mutation, ...] = (
    Mutation("M-1", "G-CITE", "a cite past the end of `26`", "`26`:448", "`26`:99999"),
    Mutation(
        "M-2",
        "G-QUOTE",
        "W-9 reworded off its line",
        'cancel and close still work."',
        'cancel and close work."',
    ),
    Mutation(
        "M-3",
        "G-VERSION",
        "the version line drops the re-pin",
        "re-pinned to the merge commit when #5382",
        "kept when #5382",
    ),
    Mutation("M-4", "G-AC", "a scenario name reworded", 'AC "Spike gate enforced"', 'AC "Spike'),
    Mutation(
        "M-5",
        "G-CHECKLIST",
        "item 7 ticked",
        "| PENDING E21-K01 #603",
        "| text done           ",
    ),
    Mutation(
        "M-6",
        "G-STATES",
        "board 06 stops drawing the resync frame",
        "`SCR-050/resyncing`, `SCR-050/depth-shed`",
        "`SCR-050/depth-shed`",
    ),
    Mutation("M-7", "G-AD", "AD-9 dropped from the conformance table", "| AD-9  |", "| AD-0  |"),
    Mutation(
        "M-8",
        "G-T2",
        "R-3 loses the opacity ban",
        "never `color.text.disabled`, never `opacity.disabled` (G-T2.2)",
        "never `color.text.disabled` (G-T2.2)",
    ),
    Mutation(
        "M-9",
        "G-T2LEN",
        "W-20 over 60 characters",
        '"Ladder trading comes later; cancel and close work as usual."',
        '"Ladder trading comes later in a later epic; cancel and close work as usual."',
    ),
    Mutation(
        "M-10",
        "G-TOKENS",
        "an unshipped focus token",
        "| `color.focus.ring`, outside",
        "| `color.focus.halo`, outside",
    ),
    Mutation("M-11", "G-CONTRAST", "a written ratio drifts", "| 3.34  |", "| 3.40  |"),
    Mutation("M-12", "G-CVD", "a written distance drifts", "| 1.9             |", "| 4.9  |"),
    Mutation(
        "M-13",
        "G-DOM",
        "a focusable button per heatmap cell",
        "No pointer affordance exists per cell (R-6);",
        "Each heatmap cell is a focusable button (R-6);",
    ),
    Mutation(
        "M-14",
        "G-ENV",
        "C-2.11 no longer stated as hard",
        "C-2.11 is a hard constraint here.",
        "C-2.11 applies.",
    ),
    Mutation(
        "M-15",
        "G-BOARDS",
        "a fourth light twin",
        r"(`E21-D02 / 03 densities`[^\n]*\| )dark( +\| PENDING)",
        r"\1light\2",
        regex=True,
    ),
    Mutation(
        "M-16",
        "G-PENDING",
        "the heading claims a ruling",
        "defaults built; ruling pending (comment 6576276584)",
        "RULED (comment 6576276584)",
    ),
    Mutation(
        "M-17",
        "G-RULED",
        "a BQ default edited without a re-pin",
        "Default built: 10 boards, 3 with a light twin",
        "Default built: 9 boards, 3 with a light twin",
    ),
    Mutation(
        "M-18",
        "G-NOCLOSE",
        "a closing keyword",
        "### 16.1 Version line\n",
        "### 16.1 Version line\n\n" + "Clo" + "ses #440.\n",
    ),
    Mutation(
        "M-19",
        "G-NOCLOSE",
        "a forbidden heading",
        "## 13. Heuristic evaluation",
        "## " + "What" + " this spec " + "fix" + "es\n\n## 13. Heuristic evaluation",
    ),
    Mutation(
        "M-20",
        "G-PUBLIC",
        "a URL",
        "Penpot: the file",
        "Penpot (" + "http" + "s://example.org): the file",
    ),
    Mutation(
        "M-21",
        "G-UNTOUCHED",
        "an owner document edited",
        "",
        "docs/plan/05-accessibility-standard.md",
        "paths",
    ),
    Mutation("M-22", "G-MUTLIST", "the list drifts", "| M-1  | G-CITE ", "| M-1  | G-AC   "),
)


def mutation_rows(ms: tuple[Mutation, ...] = MUTATIONS) -> str:
    head = "| M    | Gate        | Mutation                                    |\n| ---- | ----------- | ------------------------------------------- |\n"
    return head + "\n".join(f"| {m.mid:<4} | {m.gate:<11} | {m.what:<43} |" for m in ms)


def g_mutlist(t: Texts) -> list[Finding]:
    got = rows(section(t.spec, "### 16.3"))
    want = [[m.mid, m.gate, m.what] for m in MUTATIONS]
    return [] if got == want else [("G-MUTLIST", "section 16.3 differs from the tool")]


GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_cite,
    g_quote,
    g_version,
    g_ac,
    g_checklist,
    g_states,
    g_ad,
    g_t2,
    g_t2len,
    g_tokens,
    g_contrast,
    g_cvd,
    g_dom,
    g_env,
    g_boards,
    g_pending,
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
    for name in THEMES:
        print(ascii_out("MEASURED " + " | ".join(measured_row(name))))
    print(f"FAIL {len(found)}")
    return 1 if found else 0


def apply(t: Texts, m: Mutation) -> Texts:
    if m.target == "paths":
        return replace(t, paths=tuple(sorted((*t.paths, m.new))))
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
    head = "# E21-D02 ruled pins: sha256[:16] of each BQ bullet; written by --repin-ruled only\n"
    (ROOT / PIN_REL).write_text(head + "\n".join(pin_lines(spec)) + "\n", encoding="utf-8")
    print(f"pinned {len(pin_lines(spec))} BQ lines")
    return 0


def fill() -> int:
    p = ROOT / SPEC_REL
    spec = p.read_text(encoding="utf-8")
    start = spec.index("### 16.3")
    head_end = spec.index("\n", start) + 1
    p.write_text(spec[:head_end] + "\n" + mutation_rows() + "\n", encoding="utf-8")
    print("section 16.3 written")
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
