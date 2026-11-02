"""E19-D03 hi-fi spec audit: default-deny gates over `docs/design/E19/E19-D03.md`.

Standalone, offline, stdlib only (`python3 -I`). Every gate reads the spec, its hand-off, the
ruled-pins sidecar, the plan documents and token JSON at the pinned base, the E19-D02 spec at its
pinned PR head and the E19-D01 memo at its pinned PR head through `git show`; nothing is fetched.
A gate passes only when its positive evidence is found (default-deny): a missing section, table
or anchor is a FAIL, never a skip. The contrast, greyscale, token-alias, TPO-arithmetic and
footprint-family gates recompute their numbers from the token JSON instead of trusting the text.

Usage:
  python3 -I docs/design/_tools/e19_d03_hifi_audit.py --check        exit 1 on any FAIL
  python3 -I docs/design/_tools/e19_d03_hifi_audit.py --json         the report as JSON
  python3 -I docs/design/_tools/e19_d03_hifi_audit.py --self-test    every mutation must FAIL its gate
  python3 -I docs/design/_tools/e19_d03_hifi_audit.py --repin-ruled  rewrite the BQ-section pins

The D02 pin (D02_HEAD) re-pins to its PR's merge commit when it merges; the memo pin (MEMO_HEAD) is
already the E19-D01 memo's merge commit; BASE moves with a rebase. The BQ list (BQ_LIST_ID) is not
yet ruled (RULING_ID is None): the spec's BQ heading reads "defaults built; ruling pending" and
every bullet states its ORCH-default; once ruled, set RULING_ID and RULED_OVERRIDES and run
`--repin-ruled`. BQ-2's default lets this ticket rewrite the CMP-110, CMP-183 and CMP-184 entries of
`15` in place and add one pointer line under SCR-038 and one under SCR-039 in `14`; G-UNTOUCHED
checks both diffs line by line against the merge-base with origin/main (BASE when that is absent).
"""

from __future__ import annotations

import argparse
import difflib
import json
import math
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC_REL = "docs/design/E19/E19-D03.md"
HANDOFF_REL = "docs/design/E19/E19-D03-handoff.md"
TOOL_REL = "docs/design/_tools/e19_d03_hifi_audit.py"
PIN_REL = "docs/design/_tools/e19_d03_ruled_pins.txt"
OWN_PATHS = (SPEC_REL, HANDOFF_REL, TOOL_REL, PIN_REL)
POINTER_REL = "docs/plan/14-screens-catalogue.md"
POINTER_LINE = re.compile(
    r"^- \*\*Hi-fi \(E19-D03\):\*\* \[E19-D03\.md\]\(\.\./design/E19/E19-D03\.md\) "
)
POINTER_SCREENS = ("### SCR-038 ", "### SCR-039 ")
CATALOGUE_REL = "docs/plan/15-component-catalogue.md"
OWNED_ENTRIES = ("### CMP-110 ", "### CMP-183 ", "### CMP-184 ")
BASE = "9b77e6b83"
D02_HEAD = "bed73afaa"
D02_REL = "docs/design/E19/E19-D02.md"
MEMO_HEAD = "b005ce610"
MEMO_REL = "docs/design/research/e19-profiles.md"
TOKENS = "packages/ui/tokens/"
BQ_LIST_ID = "6579617671"
RULING_ID: str | None = None
RULED_OVERRIDES: frozenset[int] = frozenset()
BQ_COUNT = 14
BOARD_CAP = 10
WALK_CAP = 10
TICKET_KEY = "E19-D03"
CHECKLIST_LINES = (1017, 1028)  # `14`: the SCR-038 and SCR-039 design sign-off checklists
MEANINGS = (
    "Bar magnitude",
    "Buy / sell split",
    "POC",
    "Value-area membership",
    "HVN",
    "LVN",
    "Naked POC",
    "Single print",
    "Developing / final",
    "Initial balance",
    "Zero delta vs untraded",
    "Estimated (bar-approximated)",
    "Tested naked POC",
    "Per-period identity",
)
COST_CLASSES = ("cheap", "moderate", "+1 draw per pane", "very expensive")
REGISTERED = {"`pattern.hatch.estimated`": 12, "`pattern.dashed.tested`": 13}
THRESHOLD = {"text": 4.5, "non-text": 3.0}
THEMES = ("dark", "light", "high-contrast")
# The TPO worst case: 30-minute periods over a UTC day, the docked width, the gutters (spec §6.1).
TPO_PERIOD_MIN = 30
TPO_LETTERS = 24 * 60 // TPO_PERIOD_MIN
PANEL_PX = 280
GUTTER_PX = 56
IB_LANE_PX = 8
ADVANCE_EM = 0.6
NAMED_DOCS = {
    "MEMO": (MEMO_REL, MEMO_HEAD),
    "D02E18": ("docs/design/E18/E18-D02.md", BASE),
    "D02": (D02_REL, D02_HEAD),
    "D05E11": ("docs/design/E11/E11-D05.md", BASE),
    "D04E11": ("docs/design/E11/E11-D04.md", BASE),
    "D03E47": ("docs/design/E47/E47-D03.md", BASE),
    "D09E09": ("docs/design/E09/E09-D09.md", BASE),
    "R32": (".claude/rules/32-design-specs.md", BASE),
    "README": ("docs/design/README.md", BASE),
    "E19J": ("docs/plan/backlog/E19.json", BASE),
    "SD": (TOKENS + "semantic-dark.tokens.json", BASE),
    "SL": (TOKENS + "semantic-light.tokens.json", BASE),
    "PRIM": (TOKENS + "primitives.tokens.json", BASE),
    "PM": ("tools/contrast/pairs.mjs", BASE),
    "EX": ("tools/contrast/exemptions.json", BASE),
    "CM": ("tools/contrast/color-math.mjs", BASE),
    "BT": ("packages/ui/scripts/build-tokens.mjs", BASE),
    "CVD": ("docs/design/_tools/cvd_sim.py", BASE),
}
# (document, line, a substring that must be on that line at its pinned revision)
KEY_CITES: tuple[tuple[str, int, str], ...] = (
    ("05", 118, "glyph"),
    ("05", 125, "4.5:1"),
    ("05", 128, "profile-histogram bars"),
    ("05", 151, "1 update / 2s"),
    ("05", 179, "In VA"),
    ("05", 208, "10 px"),
    ("11", 1766, "range midpoint"),
    ("11", 1800, "history toggle"),
    ("11", 1803, "count of hidden ones"),
    ("11", 1821, "zero net delta"),
    ("11", 1837, "initial balance"),
    ("11", 1839, "glyph"),
    ("14", 1013, "5 000 rows"),
    ("14", 1017, "Design sign-off acceptance checklist"),
    ("14", 1028, "Design sign-off acceptance checklist"),
    ("15", 464, "2 px `color.focus.ring` at 2 px offset"),
    ("15", 592, "composite-grid"),
    ("15", 1292, "chart-primitive-adjacent"),
    ("15", 1298, "Volume, Delta, TPO, POC, ValueArea"),
    ("15", 1331, "`Esc` dismisses it"),
    ("15", 2380, "periodType"),
    ("15", 2390, "color.tpo.letter"),
    ("15", 2937, '"(estimated)"'),
    ("15", 2948, '"footprint"|"heatmap"|"candles"|"theme"'),
    ("16", 141, "spacing-token resolution only"),
    ("16", 166, "high-contrast"),
    ("16", 191, "never the sole encoding"),
    ("16", 193, "diverging ramp"),
    ("16", 198, "exact same tokens"),
    ("16", 301, "Chart Engine Primitives"),
    ("16", 530, "Runbook B"),
    ("24", 812, "aggressor SELL"),
    ("24", 813, "aggressor BUY"),
    ("24", 980, "buy_volume"),
    ("24", 981, "sell_volume"),
    ("24", 1001, "naked_poc_ticks"),
    ("24", 1004, "complete: bool"),
    ("24", 1009, "closest to period VWAP"),
    ("24", 1015, "default 20"),
    ("24", 1021, "A, B, …, Z, a, …, z"),
    ("26", 24, "≤ 8 ms"),
    ("26", 238, "2 px"),
    ("26", 282, "`▲`, `▼`"),
    ("26", 286, "≤ 6 text draw calls"),
    ("26", 331, "dash pattern index"),
    ("D02", 97, "R-1 C-2.11"),
    ("D02", 124, "280 px"),
    ("D02", 163, "zero net delta"),
    ("D02", 353, "Developing · as of {HH:MM} UTC"),
    ("D02", 376, "Net delta zero"),
    ("D02", 342, "200 % zoom"),
    ("D02", 459, "the 10 px floor kept"),
    ("MEMO", 140, "2.86"),
    ("MEMO", 142, "binding on E19-D03"),
    ("MEMO", 146, "reserved, F-3"),
    ("MEMO", 156, '"tested"'),
    ("D05E11", 43, "ruling 2"),
    ("D05E11", 313, "`pattern.hatch.estimated`"),
    ("D05E11", 317, "`pattern.dashed.tested`"),
    ("D05E11", 342, "+1 draw call per pane"),
    ("D04E11", 196, "0.6 em advance"),
    ("D03E47", 267, "stale"),
    ("D09E09", 90, "Only the owner can {verb}."),
    ("D09E09", 95, "Read-only while viewing as {user}."),
    ("SD", 98, "color.buy.default"),
    ("SD", 114, "color.sell.default"),
    ("SD", 222, "color.footprint.bid"),
    ("SD", 234, "color.profile.bar"),
    ("SD", 715, "color.chart.focus.ring"),
    ("SL", 57, "color.profile.bar"),
    ("PM", 64, "color.profile.bar"),
    ("PM", 337, "color.chart.focus.ring"),
    ("EX", 65, "dark:color.profile.bar"),
    ("CM", 48, "contrastRatio"),
    ("CM", 109, "simulateCvd"),
    ("BT", 92, "loadResolvedThemes"),
    ("BT", 98, "high-contrast"),
    ("CVD", 39, "0.299"),
    ("E19J", 100, '"E19-D03"'),
    ("R32", 79, "R6"),
    ("R32", 81, "R7"),
    ("README", 14, "boards"),
    ("README", 77, "SCR-nnn/<state>"),
)
UNTOUCHED_PREFIXES = ("docs/plan/", "docs/design/research/", ".claude/", "CONSTITUTION.md")

# Public-text deny list, assembled from fragments so this file never carries the literals.
_KW = "|".join(("clo" + "se[sd]?", "fi" + "x(?:e[sd])?", "reso" + "lve[sd]?"))
CLOSING = re.compile(r"\b(?:" + _KW + r")\b\s*:?\s*#\d+", re.IGNORECASE)
WHAT_FIXES = re.compile(r"^#+\s*Wh" + r"at this\b.*\bfi" + r"xes\b", re.IGNORECASE | re.MULTILINE)
DENY_FRAGMENTS = (
    "/ho" + "me/",
    "/t" + "mp/",
    "pen" + "pot.candle",
    "rel" + "ay.candle",
    "hcl" + "-worker",
    "hpe" + "-worker",
    "An" + "vil",
    "scr" + "atch-an" + "vil",
)
PENPOT_DENY = ("file" + "-id", "team" + "-id", "page" + "-id=", "work" + "space?", "#/" + "view")
URL = re.compile(r"\bhttps?://|\bwww\.[a-z]", re.IGNORECASE)
HEX40 = re.compile(r"\b[0-9a-f]{40}\b")
HEX_COLOUR = re.compile(r"#[0-9A-Fa-f]{6}\b")
COMMENT = re.compile(r"<!--(.*?)-->", re.DOTALL)
COMMENT_OPEN = re.compile(r"<!--(?!.*?-->)", re.DOTALL)
ANCHOR_BODY = re.compile(r"^ audit:([a-z_0-9]+)=([0-9a-f]+) $", re.DOTALL)
FENCE = re.compile(r"^```.*?^```[ \t]*$", re.DOTALL | re.MULTILINE)
DOC_TOKEN = r"(?:`(?P<nn>\d\d)`|(?<![\w-])(?P<named>" + "|".join(NAMED_DOCS) + r"))"
CITE = re.compile(
    DOC_TOKEN + r" ?:(?P<first>\d+)(?:–(?P<firstend>\d+))?(?P<more>(?:, :\d+(?:–\d+)?)*)"
)
MORE = re.compile(r":(\d+)(?:–(\d+))?")
FRAME = re.compile(r"`(SCR-03[89]/[a-z0-9-]+)`")
PLAIN_FRAME = re.compile(r"(?<![`/\w])(SCR-03[89]/[a-z0-9-]+)")
W_REF = re.compile(r"(?<!D02 )\bW-(\d+)\b")
ROW_ID = re.compile(r"\bD03-(C|G|A|OQ)(\d+)\b")
TICKET = re.compile(r"\bE\d\d-[A-Z]\d\d\b")
CMP_ID = re.compile(r"\bCMP-(\d{3})\b")
TOKEN_NAME = re.compile(
    r"`((?:color|type|space|opacity|radius|size|font|border|elevation|palette)\.[a-z0-9.*-]+)`"
)
PATTERN_NAME = re.compile(r"`((?:pattern|glyph)\.[a-z0-9.-]+)`")


@dataclass
class Ctx:
    spec: str
    handoff: str
    pins: str
    tool: str
    changed: list[str]
    sources: dict[str, list[str]] = field(default_factory=dict)
    keys: frozenset[str] = frozenset()
    pointer: tuple[list[str], list[str]] = field(default_factory=lambda: ([], []))
    catalogue: tuple[list[str], list[str]] = field(default_factory=lambda: ([], []))
    ticket: str = ""


@dataclass
class Result:
    gate: str
    ok: bool
    detail: list[str]


def git(*args: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return proc.returncode, proc.stdout


def show(rev: str, rel: str) -> str | None:
    code, out = git("show", f"{rev}:{rel}")
    return out if code == 0 else None


def plan_rel(nn: str) -> str | None:
    code, out = git("ls-tree", "--name-only", BASE, "docs/plan/")
    if code != 0:
        return None
    for line in out.splitlines():
        name = line.rsplit("/", 1)[-1]
        if name.startswith(nn + "-") and name.endswith((".md", ".yaml")):
            return line
    return None


def load_sources(doc_ids: set[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for doc in sorted(doc_ids):
        if doc in NAMED_DOCS:
            rel, rev = NAMED_DOCS[doc]
            text = show(rev, rel)
        else:
            prel = plan_rel(doc)
            text = show(BASE, prel) if prel else None
        if text is not None:
            out[doc] = text.splitlines()
    return out


def backlog_keys() -> frozenset[str]:
    code, out = git("grep", "-h", "-o", '"key": "E[0-9][0-9]-[A-Z][0-9][0-9]"', BASE, "--")
    if code != 0:
        return frozenset()
    return frozenset(TICKET.findall(out))


def ticket_body(e19json: list[str]) -> str:
    try:
        data = json.loads("\n".join(e19json))
    except ValueError:
        return ""
    for item in data if isinstance(data, list) else []:
        if isinstance(item, dict) and item.get("key") == TICKET_KEY:
            body = item.get("body")
            return body if isinstance(body, str) else ""
    return ""


def diff_base() -> str:
    """The merge-base with origin/main, so a merged or rebased tree diffs only this branch's own
    changes; BASE when origin/main (or a merge-base with it) is absent."""
    code, out = git("merge-base", "HEAD", "origin/main")
    return out.strip() if code == 0 and out.strip() else BASE


def changed_paths(rev: str) -> list[str]:
    _, tracked = git("diff", "--name-only", rev, "--")
    _, untracked = git("ls-files", "--others", "--exclude-standard")
    return sorted({p for p in (tracked + untracked).splitlines() if p})


def read(rel: str) -> str:
    path = ROOT / rel
    return path.read_text(encoding="utf-8") if path.exists() else ""


def build_ctx() -> Ctx:
    spec = read(SPEC_REL)
    handoff = read(HANDOFF_REL)
    docs = {m.group("nn") or m.group("named") for m in CITE.finditer(spec + "\n" + handoff)}
    docs |= {d for d, _, _ in KEY_CITES}
    docs |= {"SD", "SL", "PRIM", "D05E11", "D02", "E19J", "15", "16"}
    hc = show(BASE, TOKENS + "semantic-hc.tokens.json")
    sources = load_sources(docs)
    if hc is not None:
        sources["HC"] = hc.splitlines()
    rev = diff_base()
    return Ctx(
        spec=spec,
        handoff=handoff,
        pins=read(PIN_REL),
        tool=read(TOOL_REL),
        changed=changed_paths(rev),
        sources=sources,
        keys=backlog_keys(),
        pointer=((show(rev, POINTER_REL) or "").splitlines(), read(POINTER_REL).splitlines()),
        catalogue=(
            (show(rev, CATALOGUE_REL) or "").splitlines(),
            read(CATALOGUE_REL).splitlines(),
        ),
        ticket=ticket_body(sources.get("E19J", [])),
    )


# ---------------------------------------------------------------- tokens and colour maths


def token_json(c: Ctx, doc: str) -> dict[str, str]:
    try:
        data = json.loads("\n".join(c.sources.get(doc, [])))
    except ValueError:
        return {}
    out: dict[str, str] = {}
    for name, entry in data.items() if isinstance(data, dict) else []:
        if isinstance(entry, dict) and isinstance(entry.get("$value"), str):
            out[name] = entry["$value"]
    return out


def token_names(c: Ctx, doc: str) -> set[str]:
    """Every token name in a token file, whatever its value type (typography values are objects)."""
    try:
        data = json.loads("\n".join(c.sources.get(doc, [])))
    except ValueError:
        return set()
    return set(data) if isinstance(data, dict) else set()


def theme_values(c: Ctx, theme: str, proposed: dict[str, dict[str, str]]) -> dict[str, str]:
    """BT:92's merge order (primitives, dark, then the theme's override), plus the spec's PROPOSED
    aliases; returns every name resolved to a hex colour."""
    merged = dict(token_json(c, "PRIM"))
    merged.update(token_json(c, "SD"))
    if theme == "light":
        merged.update(token_json(c, "SL"))
    if theme == "high-contrast":
        merged.update(token_json(c, "HC"))
    for name, aliases in proposed.items():
        alias = aliases["light" if theme == "light" else "dark"]
        merged[name] = "{" + alias + "}"
    out: dict[str, str] = {}
    for name, start in merged.items():
        value, seen = start, 0
        while value.startswith("{") and value.endswith("}") and seen < 10:
            value, seen = merged.get(value[1:-1], ""), seen + 1
        if re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
            out[name] = value.upper()
    return out


def _lin(channel: int) -> float:
    cs = channel / 255
    return cs / 12.92 if cs <= 0.04045 else ((cs + 0.055) / 1.055) ** 2.4


def luminance(hex_colour: str) -> float:
    r, g, b = (int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def ratio(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def grey(hex_colour: str) -> str:
    """CVD:39's Rec. 601 luma, rounded half up like the measuring script."""
    r, g, b = (int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
    y = max(0, min(255, math.floor(r * 0.299 + g * 0.587 + b * 0.114 + 0.5)))
    return f"#{y:02X}{y:02X}{y:02X}"


# ---------------------------------------------------------------- parsing helpers


def section(text: str, heading_start: str) -> str:
    """The body under the first heading line starting with `heading_start`, to the next peer."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(heading_start):
            level = len(line) - len(line.lstrip("#"))
            body: list[str] = []
            for nxt in lines[i + 1 :]:
                stripped = nxt.lstrip("#")
                if (
                    nxt.startswith("#")
                    and len(nxt) - len(stripped) <= level
                    and stripped[:1] == " "
                ):
                    break
                body.append(nxt)
            return "\n".join(body)
    return ""


def unfenced(text: str) -> str:
    return FENCE.sub("", text)


def table_rows(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in unfenced(text).splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):
            continue
        rows.append(cells)
    return rows[1:] if rows else rows  # drop the header


def anchors(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in COMMENT.finditer(text):
        a = ANCHOR_BODY.match(m.group(1))
        if a:
            out[a.group(1)] = a.group(2)
    return out


def bq_section(spec: str) -> tuple[str, str]:
    for line in spec.splitlines():
        if line.startswith("## The questions BQ-0"):
            return line, section(spec, line)
    return "", ""


def proposed_aliases(spec: str) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for r in token_rows(spec):
        if r[5] == "PROPOSED":
            out[r[0].strip("`")] = {"dark": r[2].strip("`"), "light": r[3].strip("`")}
    return out


def token_rows(spec: str) -> list[list[str]]:
    return [r for r in table_rows(section(spec, "### 2.1")) if len(r) == 6]


def number(cell: str) -> float | None:
    try:
        return float(cell)
    except ValueError:
        return None


# ---------------------------------------------------------------- gates


def g_version(c: Ctx) -> list[str]:
    bad: list[str] = []
    a = anchors(c.spec)
    for key, want in (("base", BASE), ("d02_head", D02_HEAD), ("memo_head", MEMO_HEAD)):
        if a.get(key) != want:
            bad.append(f"{key} anchor {a.get(key)!r} != {want}")
    for need in (
        f"`{D02_HEAD}`",
        f"`{MEMO_HEAD}`",
        "re-pins to its merge commit when it merges",
        "if #416's PR 1 merges as is",
    ):
        if need not in c.spec:
            bad.append(f"the spec must state {need!r}")
    if f"`{D02_HEAD}`" not in c.handoff:
        bad.append("the hand-off must name the D02 pin")
    for doc, rel in (("D02", D02_REL), ("MEMO", MEMO_REL)):
        if doc not in c.sources:
            bad.append(f"{rel} not readable at its pin (fetch the PR head)")
    for text, name in ((c.spec, "spec"), (c.handoff, "hand-off"), (c.pins, "pins")):
        if HEX40.search(text):
            bad.append(f"a 40-hex sha in the {name}; pin short shas only")
    return bad


def g_cite(c: Ctx) -> list[str]:
    bad: list[str] = []
    found = 0
    for text in (c.spec, c.handoff):
        for m in CITE.finditer(text):
            doc = m.group("nn") or m.group("named")
            lines = c.sources.get(doc)
            spans = [(int(m.group("first")), int(m.group("firstend") or m.group("first")))]
            spans += [(int(a), int(b or a)) for a, b in MORE.findall(m.group("more"))]
            for lo, hi in spans:
                found += 1
                if lines is None:
                    bad.append(f"{doc}:{lo} — document not readable at its pin")
                elif not 1 <= lo <= hi <= len(lines):
                    bad.append(f"{doc}:{lo}–{hi} — outside the document ({len(lines)} lines)")
    if found < 100:
        bad.append(f"only {found} cites parsed; the cite grammar is broken")
    for doc, n, needle in KEY_CITES:
        lines = c.sources.get(doc)
        if lines is None or n > len(lines) or needle not in lines[n - 1]:
            bad.append(f"{doc}:{n} no longer carries {needle!r} (re-pin the cite)")
    return bad


def g_bq(c: Ctx) -> list[str]:
    bad: list[str] = []
    head, body = bq_section(c.spec)
    last = BQ_COUNT - 1
    if RULING_ID is None:
        want = (
            f"## The questions BQ-0 … BQ-{last} — defaults built; ruling pending "
            f"(comment {BQ_LIST_ID})"
        )
    else:
        want = f"## The questions BQ-0 … BQ-{last} — RULED (comment {RULING_ID})"
    if head != want:
        bad.append(f"BQ heading must read {want!r}")
    if BQ_LIST_ID not in body:
        bad.append(f"the BQ section must cite the list {BQ_LIST_ID}")
    bullets = re.findall(r"^- \*\*BQ-(\d+) — [^*]+\.\*\* (.*)$", body, re.MULTILINE)
    if [int(n) for n, _ in bullets] != list(range(BQ_COUNT)):
        bad.append(f"BQ bullets must be BQ-0 … BQ-{last} in order")
    for n, text in bullets:
        if RULING_ID is None and not text.startswith("ORCH-default:"):
            bad.append(f"BQ-{n} must state its ORCH-default")
        if RULING_ID is not None:
            verdict = "OVERRIDE" if int(n) in RULED_OVERRIDES else "ACCEPT"
            if not text.startswith(f"RULED: {verdict}."):
                bad.append(f"BQ-{n} must open with 'RULED: {verdict}.' (comment {RULING_ID})")
        if "Built as:" not in text:
            bad.append(f"BQ-{n} must say what is built")
    return bad


def pins_text(spec: str) -> str:
    head, body = bq_section(spec)
    lines = [
        "# E19-D03 pins: the BQ section of the spec, verbatim (heading + body).",
        "# Written by `--repin-ruled` only; `--check` reads it (never hand-edit; G-RULED).",
        head,
        body.strip("\n"),
    ]
    return "\n".join(lines) + "\n"


def g_ruled(c: Ctx) -> list[str]:
    if not bq_section(c.spec)[0]:
        return ["no BQ section to pin"]
    if c.pins != pins_text(c.spec):
        return [f"{PIN_REL} differs from the spec's BQ section (run --repin-ruled after a ruling)"]
    return []


def board_rows(spec: str) -> list[list[str]]:
    return [r for r in table_rows(section(spec, "## 0.")) if len(r) == 5]


def not_drawn(spec: str) -> list[str]:
    for line in section(spec, "## 0.").splitlines():
        if line.startswith("**Not drawn — the text is binding**"):
            return FRAME.findall(line)
    return []


def g_boards(c: Ctx) -> list[str]:
    bad: list[str] = []
    rows = board_rows(c.spec)
    if not rows:
        return ["no board table in §0"]
    if len(rows) > BOARD_CAP:
        bad.append(f"{len(rows)} boards > cap {BOARD_CAP}")
    if anchors(c.spec).get("boards") != str(len(rows)):
        bad.append(f"boards anchor != {len(rows)} table rows")
    for i, row in enumerate(rows, 1):
        if row[0] != f"{i:02d}":
            bad.append(f"board number {row[0]} out of sequence")
        if not row[1].startswith(f"`E19-D03 / {i:02d} "):
            bad.append(f"board {row[0]} name must be `E19-D03 / NN slug`")
        if row[3] not in ("dark", "light twin"):
            bad.append(f"board {row[0]} theme {row[3]!r} must be 'dark' or 'light twin'")
        if row[4] != "PENDING":
            bad.append(f"board {row[0]} status {row[4]!r}; only PENDING until drawn")
    twins = sum(1 for r in rows if r[3] == "light twin")
    if twins * 3 > len(rows):
        bad.append("light twins exceed one third")
    if "Not drawn — the text is binding" not in c.spec:
        bad.append("the not-drawn line is missing")
    return bad


def g_states(c: Ctx) -> list[str]:
    bad: list[str] = []
    planned: list[str] = []
    for row in board_rows(c.spec):
        planned += FRAME.findall(row[2])
    planned += not_drawn(c.spec)
    dupes = sorted({f for f in planned if planned.count(f) > 1})
    if dupes:
        bad.append(f"frames planned twice: {dupes}")
    zero = c.spec.split("\n## 0.", 1)
    rest = zero[1].split("\n## 1.", 1)[1] if len(zero) == 2 and "\n## 1." in zero[1] else ""
    used = set(FRAME.findall(rest))
    if not used:
        bad.append("no frame named outside §0")
    for f in sorted(used - set(planned)):
        bad.append(f"{f} is specified but on no board and not in the not-drawn list (R4)")
    for f in sorted(set(planned) - used):
        bad.append(f"{f} is planned in §0 but specified nowhere (R4)")
    return bad


def g_resolve(c: Ctx) -> list[str]:
    """Every E19-D02 frame (its §0 table and not-drawn line, at its pin) has a hi-fi frame."""
    d02 = "\n".join(c.sources.get("D02", []))
    want = set(FRAME.findall(section(d02, "## 0.")))
    if len(want) < 30:
        return [f"only {len(want)} D02 frames read at {D02_HEAD}"]
    rows = table_rows(section(c.spec, "### 10.3"))
    got: dict[str, list[str]] = {}
    bad: list[str] = []
    for r in rows:
        if len(r) != 4 or not PLAIN_FRAME.fullmatch(r[0]):
            bad.append(f"§10.3 row {r[:1]} is not 'D02 frame | hi-fi frame | treatment | ann'")
            continue
        got[r[0]] = FRAME.findall(r[1])
    for f in sorted(want - set(got)):
        bad.append(f"D02 frame {f} is not resolved in §10.3 (T DoD)")
    for f in sorted(set(got) - want):
        bad.append(f"§10.3 lists {f}, which is not a D02 frame")
    for f, hifi in got.items():
        if not hifi:
            bad.append(f"{f} names no hi-fi frame")
    return bad


def g_ac(c: Ctx) -> list[str]:
    titles = re.findall(r"^\s*Scenario: (.+?)\s*$", c.ticket, re.MULTILINE)
    if len(titles) != 6:
        return [f"{len(titles)} scenarios read from the ticket at {BASE} (6 expected)"]
    trace = section(c.spec, "## Acceptance-criteria trace")
    bad: list[str] = []
    for i, t in enumerate(titles, 1):
        if f"| AC {i} — Scenario: {t} " not in trace:
            bad.append(f"AC {i} must quote 'Scenario: {t}' verbatim")
    # The `14` design sign-off checklists of SCR-038 and SCR-039, item by item (§18.4).
    src = c.sources.get("14", [])
    sign = section(c.spec, "### 18.4")
    for n in CHECKLIST_LINES:
        line = src[n - 1] if n <= len(src) else ""
        items = [i.strip() for i in line.split("[ ]")[1:]]
        if not items:
            bad.append(f"`14`:{n} carries no sign-off checklist at {BASE}")
        for item in items:
            if f"\u201c{item}\u201d" not in sign:
                bad.append(f"§18.4 does not quote the `14`:{n} item {item!r}")
    if "§18.4" not in trace:
        bad.append("the trace has no row for the `14` sign-off checklists (§18.4)")
    return bad


def g_dod(c: Ctx) -> list[str]:
    body = c.ticket.split("## Definition of Done", 1)
    items = re.findall(r"^- \[ \] (.+)$", body[1].split("\n## ", 1)[0], re.MULTILINE)
    items = [i.replace("**", "").strip() for i in items] if len(body) == 2 else []
    if len(items) != 7:
        return [f"{len(items)} DoD items read from the ticket (7 expected)"]
    trace = section(c.spec, "## Acceptance-criteria trace")
    bad = [f"DoD item not quoted in the trace: {i[:50]!r}" for i in items if f'"{i}"' not in trace]
    if "### 18.1 DoD" not in c.spec:
        bad.append("§18.1 DoD missing")
    return bad


def g_tokens(c: Ctx) -> list[str]:
    bad: list[str] = []
    rows = token_rows(c.spec)
    names = [r[0].strip("`") for r in rows]
    for need in ("color.profile.bar", "color.profile.poc", "color.profile.valuearea"):
        if need not in names:
            bad.append(f"§2.1 lacks {need}")
    for need in ("color.tpo.letter", "color.tpo.initialbalance"):
        if need not in names:
            bad.append(f"§2.1 lacks {need}")
    prim = token_json(c, "PRIM")
    sd, sl = token_json(c, "SD"), token_json(c, "SL")
    for r in rows:
        name, dark, light, status = r[0].strip("`"), r[2].strip("`"), r[3].strip("`"), r[5]
        if not dark.startswith("palette.") or dark.startswith("palette.light."):
            bad.append(f"{name}: the dark alias {dark!r} is not a dark primitive")
        if not light.startswith("palette.light."):
            bad.append(f"{name}: the light alias {light!r} is not a light primitive")
        for alias in (dark, light):
            if alias not in prim:
                bad.append(f"{name}: {alias} is not a primitive at {BASE}")
        if status == "shipped":
            if sd.get(name) != "{" + dark + "}" or sl.get(name) != "{" + light + "}":
                bad.append(f"{name}: shipped, but SD / SL at {BASE} resolve otherwise")
        elif status == "PROPOSED":
            if name in sd or name in sl:
                bad.append(f"{name}: marked PROPOSED but already ships")
        else:
            bad.append(f"{name}: status {status!r} must be shipped or PROPOSED")
    for text, label in ((c.spec, "spec"), (c.handoff, "hand-off")):
        if HEX_COLOUR.search(text):
            bad.append(f"a hex colour in the {label}; tokens by name only (R-6)")
    return bad


def contrast_rows(spec: str) -> list[list[str]]:
    return [r for r in table_rows(section(spec, "### 2.2")) if len(r) == 7]


def pair_names(cell: str) -> tuple[str, str] | None:
    m = re.fullmatch(r"`([a-z0-9.]+)` on `([a-z0-9.]+)`", cell)
    return (m.group(1), m.group(2)) if m else None


def g_contrast(c: Ctx) -> list[str]:
    bad: list[str] = []
    rows = contrast_rows(c.spec)
    if len(rows) < 10:
        return [f"§2.2 has {len(rows)} measured pairs"]
    vals = {t: theme_values(c, t, proposed_aliases(c.spec)) for t in THEMES}
    inks = {p[0] for r in rows if (p := pair_names(r[0])) and p[1] == "color.surface.canvas"}
    for r in token_rows(c.spec):
        if r[0].strip("`") not in inks:
            bad.append(f"{r[0]} has no measured ratio on the canvas (AC 2)")
    for r in rows:
        pair = pair_names(r[0])
        if pair is None or r[1] not in THRESHOLD:
            bad.append(f"§2.2 row {r[0]!r}: pair or kind unreadable")
            continue
        want = THRESHOLD[r[1]]
        if number(r[2]) != want:
            bad.append(f"{r[0]}: threshold {r[2]} != {want} for {r[1]}")
        for theme, cell in zip(THEMES, r[3:6], strict=True):
            a, b = vals[theme].get(pair[0]), vals[theme].get(pair[1])
            got = number(cell)
            if a is None or b is None or got is None:
                bad.append(f"{r[0]} ({theme}): unresolved or unreadable")
                continue
            calc = ratio(a, b)
            if abs(calc - got) > 0.015:
                bad.append(f"{r[0]} ({theme}): {got} stated, {calc:.2f} computed")
            if got < want:
                bad.append(f"{r[0]} ({theme}): {got} < {want}")
        if r[6] != "pass":
            bad.append(f"{r[0]}: verdict {r[6]!r}")
    return bad


def g_cvd(c: Ctx) -> list[str]:
    bad: list[str] = []
    thresholds = {
        p[0]: THRESHOLD.get(r[1], 9.0)
        for r in contrast_rows(c.spec)
        if (p := pair_names(r[0])) and p[1] == "color.surface.canvas"
    }
    rows = [r for r in table_rows(section(c.spec, "### 2.3")) if len(r) == 4]
    if len(rows) < 5:
        return [f"§2.3 has {len(rows)} inks"]
    names = {r[0].strip("`") for r in rows}
    for need in ("color.profile.bar", "color.profile.poc", "color.profile.valuearea"):
        if need not in names:
            bad.append(f"§2.3 lacks {need}")
    vals = {t: theme_values(c, t, proposed_aliases(c.spec)) for t in THEMES}
    for r in rows:
        ink = r[0].strip("`")
        want = thresholds.get(ink)
        if want is None:
            bad.append(f"{ink}: no §2.2 threshold on the canvas")
            continue
        for theme, cell in zip(THEMES, r[1:4], strict=True):
            parts = [number(p.strip()) for p in cell.split("/")]
            if len(parts) != 5 or any(p is None for p in parts):
                bad.append(f"{ink} ({theme}): needs normal / grey / deut / prot / trit")
                continue
            a, b = vals[theme].get(ink), vals[theme].get("color.surface.canvas")
            if a is None or b is None:
                bad.append(f"{ink} ({theme}): unresolved")
                continue
            for label, calc, got in (
                ("normal", ratio(a, b), parts[0]),
                ("greyscale", ratio(grey(a), grey(b)), parts[1]),
            ):
                if got is None or abs(calc - got) > 0.015:
                    bad.append(f"{ink} ({theme}) {label}: {got} stated, {calc:.2f} computed")
            if min(p for p in parts if p is not None) < want:
                bad.append(f"{ink} ({theme}): a simulated ratio below {want}")
    return bad


def g_encoding(c: Ctx) -> list[str]:
    bad: list[str] = []
    body = section(c.spec, "## 3.")
    rows = [r for r in table_rows(body) if len(r) == 6]
    if tuple(r[1] for r in rows) != MEANINGS:
        bad.append(f"§3 meanings {[r[1] for r in rows]} != the eight + six of BQ-5")
    if anchors(c.spec).get("meanings") != str(len(MEANINGS)):
        bad.append("meanings anchor != 14")
    for i, r in enumerate(rows, 1):
        if r[0] != str(i):
            bad.append(f"§3 row number {r[0]} out of sequence")
        if "`color." in r[2] or not r[2]:
            bad.append(f"{r[1]}: the primary carrier must be non-colour")
        if "hollow" in r[2]:
            bad.append(f"{r[1]}: hollow marks are reserved (R-2)")
        if not r[4].startswith(COST_CLASSES):
            bad.append(f"{r[1]}: cost class {r[4]!r} not one of {COST_CLASSES}")
        if not r[5]:
            bad.append(f"{r[1]}: the DOM-mirror flag is empty")
        for pid, row_no in REGISTERED.items():
            if pid in " ".join(r) and i != row_no:
                bad.append(f"{pid} used outside its registered meaning (row {i})")
    for pid, row_no in REGISTERED.items():
        if len(rows) >= row_no and pid not in rows[row_no - 1][2]:
            bad.append(f"row {row_no} must carry {pid}")
    for need in ("**Greyscale proof (AC 1):**", "**DOM-mirror-only, stated:**"):
        if need not in body:
            bad.append(f"§3 lacks {need}")
    return bad


def g_e18(c: Ctx) -> list[str]:
    bad: list[str] = []
    for doc in ("SD", "SL"):
        t = token_json(c, doc)
        for fp, side in (("color.footprint.bid", "color.buy.default"),):
            if not t.get(fp) or t.get(fp) != t.get(side):
                bad.append(f"{doc}: {fp} and {side} are not one primitive (AC 6's family claim)")
        if not t.get("color.footprint.ask") or t.get("color.footprint.ask") != t.get(
            "color.sell.default"
        ):
            bad.append(f"{doc}: color.footprint.ask and color.sell.default are not one primitive")
    body = section(c.spec, "## 8.")
    for need in ("`24`:812–813", "the same token family", "D03-C4", "segment order", "▲ / ▼"):
        if need not in body:
            bad.append(f"§8 lacks {need!r}")
    return bad


def g_npoc(c: Ctx) -> list[str]:
    bad: list[str] = []
    body = section(c.spec, "## 5.")
    m = re.search(r"N defaults to (\d+)", body)
    if not m or not 1 <= int(m.group(1)) <= 20:
        bad.append("§5 must state a default N within the contract's lookback of 20")
    for need in (
        "nearest N",
        "configurable 1–20",
        "`pattern.dashed.tested`",
        "W-2",
        "W-3",
        "W-5",
        "W-6",
        "D03-G1",
        "`24`:1001",
    ):
        if need not in body:
            bad.append(f"§5 lacks {need!r}")
    return bad


def g_tpo(c: Ctx) -> list[str]:
    bad: list[str] = []
    body = section(c.spec, "## 6.")
    letters = len("ABCDEFGHIJKLMNOPQRSTUVWXYZ") + len("abcdefghijklmnopqrstuv")
    if letters != TPO_LETTERS or f"{TPO_LETTERS} periods" not in body or "A–Z, a–v" not in body:
        bad.append(f"§6 must state the {TPO_LETTERS} periods lettered A–Z, a–v")
    rows = [r for r in table_rows(section(c.spec, "### 6.1")) if len(r) == 8]
    if [r[0] for r in rows] != ["compact", "dense", "comfortable"]:
        bad.append("§6.1 needs one row per density: compact, dense, comfortable")
    runs: list[int] = []
    for r in rows:
        vals = [number(x) for x in r[1:7]]
        if any(v is None for v in vals):
            bad.append(f"{r[0]}: unreadable numbers")
            continue
        inset, run, size, adv, fit, need = (float(v) for v in vals if v is not None)
        want_run = PANEL_PX - 2 * inset - GUTTER_PX - IB_LANE_PX
        want_adv = round(ADVANCE_EM * size, 2)
        if run != want_run:
            bad.append(f"{r[0]}: run {run:g} != {want_run:g}")
        if size < 10:
            bad.append(f"{r[0]}: letter {size:g} px below the 10 px floor")
        if adv != want_adv:
            bad.append(f"{r[0]}: advance {adv:g} != {want_adv:g}")
        if fit != math.floor(want_run / want_adv):
            bad.append(f"{r[0]}: fit {fit:g} != {math.floor(want_run / want_adv)}")
        if need != TPO_LETTERS * want_adv:
            bad.append(
                f"{r[0]}: the {TPO_LETTERS}-letter run {need:g} != {TPO_LETTERS * want_adv:g}"
            )
        form = "letters" if math.floor(want_run / want_adv) >= TPO_LETTERS else "blocks"
        if r[7] != form:
            bad.append(f"{r[0]}: form {r[7]!r} != {form!r}")
        runs.append(int(want_run))
    pitch = re.search(r"on a (\d+) px pitch", section(c.spec, "### 6.2"))
    if not pitch or not runs or int(pitch.group(1)) * TPO_LETTERS > min(runs):
        bad.append(f"§6.2's block pitch × {TPO_LETTERS} must fit every density's run")
    if "W-7" not in section(c.spec, "### 6.2"):
        bad.append("§6.2 must name the legend note W-7")
    return bad


def g_t2(c: Ctx) -> list[str]:
    bad: list[str] = []
    body = section(c.spec, "### 1.4")
    d09 = c.sources.get("D09E09", [])
    keys = {m for line in d09[80:100] for m in re.findall(r"^\| `(rbac\.[a-z_]+)`", line)}
    verbs = "\n".join(d09[100:120])
    used = re.findall(r"`(rbac\.[a-z_]+)`", body)
    if not used:
        bad.append("§1.4 names no reason key")
    for k in used:
        if k not in keys:
            bad.append(f"{k} is not a D09E09 §3.1 key")
    for verb in re.findall(r'verb "([^"]+)"', body):
        if f'`recording:write` → "{verb}"' not in verbs:
            bad.append(f"verb {verb!r} is not D09E09 §3.2's for recording:write")
    for need in (
        'aria-disabled="true"',
        "never `disabled`",
        "aria-describedby",
        "G-T2.5",
        "the label is `color.text.tertiary`, the reason `color.text.secondary`",
        "never `opacity.disabled`",
    ):
        if need not in body:
            bad.append(f"§1.4 lacks {need!r}")
    t2 = (
        "SCR-038/no-history-sentence",
        "SCR-038/no-history-view-as",
        "SCR-038/presets-view-as",
        "SCR-039/view-as",
    )
    rows = {r[0]: r for r in table_rows(section(c.spec, "### 10.3"))}
    for f in t2:
        if f not in rows or "**T2 (§1.4)**" not in rows[f][2]:
            bad.append(f"{f} must name T2 (§1.4) (G-T2.6)")
    if "**T2 (§1.4)**" not in section(c.spec, "## 11."):
        bad.append("§11's view-as must name T2 (§1.4) (G-T2.6)")
    return bad


def g_env(c: Ctx) -> list[str]:
    body = section(c.spec, "### 1.3")
    need = (
        "C-2.11",
        "no DEMO / LIVE badge",
        "no environment control",
        "no account context",
        "no per-account affordance",
        "synthetic BTCUSDT",
    )
    return [f"R-1 lacks {n!r}" for n in need if n not in body]


def base_stories(c: Ctx, heading: str) -> list[str]:
    lines = c.sources.get("15", [])
    start = next((i for i, ln in enumerate(lines) if ln.startswith(heading)), None)
    if start is None:
        return []
    for ln in lines[start + 1 :]:
        if ln.startswith("### "):
            break
        if ln.startswith("- **Storybook**: "):
            return [s.strip() for s in ln[len("- **Storybook**: ") :].rstrip(".").split(",")]
    return []


def g_stories(c: Ctx) -> list[str]:
    bad: list[str] = []
    body = section(c.spec, "## 15.")
    allowed: set[str] = set()
    for heading in OWNED_ENTRIES:
        cmp_id = heading[4:].strip()
        m = re.search(
            r"^- \*\*" + cmp_id + r" [A-Za-z]+:\*\* kept — (.+?) \(`15`:\d+\); PROPOSED — (.+)\.$",
            body,
            re.MULTILINE,
        )
        want = base_stories(c, heading)
        if not want:
            bad.append(f"{cmp_id}: no Storybook line in `15` at {BASE}")
            continue
        if not m:
            bad.append(f"{cmp_id}: no 'kept — … ; PROPOSED — …' line in §15")
            continue
        kept = [s.strip() for s in m.group(1).split(",")]
        if kept != want:
            bad.append(f"{cmp_id}: kept {kept} != `15`'s {want}")
        allowed |= set(kept) | {s.strip() for s in m.group(2).split(",")}
    for r in table_rows(c.handoff):
        if len(r) == 5 and r[2].startswith("`CMP-"):
            for s in (x.strip() for x in r[3].split(",")):
                if s not in allowed:
                    bad.append(f"hand-off story {s!r} is not in the spec's §15 list")
    return bad


def g_newcmp(c: Ctx) -> list[str]:
    bad: list[str] = []
    cat = "\n".join(c.sources.get("15", []))
    text = c.spec + "\n" + c.handoff
    for n in sorted(set(CMP_ID.findall(text))):
        if f"\n### CMP-{n} " not in cat:
            bad.append(f"CMP-{n} is not a `15` entry at {BASE} (no new CMP id)")
    known = set(proposed_aliases(c.spec))
    for doc in ("PRIM", "SD", "SL", "HC"):
        known |= token_names(c, doc)
    for name in sorted(set(TOKEN_NAME.findall(text))):
        if "*" not in name and name not in known:
            bad.append(f"`{name}` is neither a shipped token nor a §2.1 PROPOSED row")
    registry = "\n".join(c.sources.get("D05E11", [])[312:320])
    for name in sorted(set(PATTERN_NAME.findall(text))):
        if f"`{name}`" not in registry:
            bad.append(f"`{name}` is not in D05E11's pattern registry")
    return bad


def checklist_labels(c: Ctx) -> list[str]:
    """The §11.4 template's bold labels (its fenced block holds a `##` heading, so this reads a
    window of lines rather than the section)."""
    lines = c.sources.get("16", [])
    start = next((i for i, ln in enumerate(lines) if ln.startswith("### 11.4")), None)
    if start is None:
        return []
    body = "\n".join(lines[start : start + 60])
    return re.findall(r"^- \[ \] \*\*([^*]+)\*\*", body, re.MULTILINE)


def g_handoff(c: Ctx) -> list[str]:
    bad: list[str] = []
    labels = checklist_labels(c)
    if len(labels) < 12:
        return [f"only {len(labels)} §11.4 checklist labels read from `16`"]
    for heading in OWNED_ENTRIES:
        cmp_id = heading[4:].strip()
        head = next(
            (
                ln
                for ln in c.handoff.splitlines()
                if ln.startswith(f"## Handoff checklist — {cmp_id} ")
                and ln.endswith("(E19-D03, #438)")
            ),
            "",
        )
        if not head:
            bad.append(f"no '## Handoff checklist — {cmp_id} … (E19-D03, #438)' block")
            continue
        body = section(c.handoff, head)
        for label in labels:
            m = re.search(
                r"^- \[( |x)\] \*\*" + re.escape(label) + r"\*\*(.*)$", body, re.MULTILINE
            )
            if not m:
                bad.append(f"{cmp_id}: checklist line {label!r} missing")
            elif m.group(1) == " " and "PENDING" not in m.group(2) and "N/A —" not in m.group(2):
                bad.append(f"{cmp_id}: open line {label!r} is neither PENDING nor N/A")
    return bad


def copy_rows(spec: str) -> list[list[str]]:
    return [r for r in table_rows(section(spec, "## 13.")) if r and r[0].startswith("W-")]


def g_copy(c: Ctx) -> list[str]:
    bad: list[str] = []
    rows = copy_rows(c.spec)
    ids = [int(r[0][2:]) for r in rows]
    if ids != list(range(1, len(ids) + 1)) or not ids:
        bad.append("W ids must run W-1 … W-n without gaps")
    defined = set(ids)
    outside = c.spec.replace(section(c.spec, "## 13."), "")
    referenced = {int(n) for n in W_REF.findall(outside)}
    for n in sorted(referenced - defined):
        bad.append(f"W-{n} referenced but not in the deck")
    for n in sorted(defined - referenced):
        bad.append(f"W-{n} defined but used nowhere")
    for r in rows:
        if len(r) != 4:
            bad.append(f"{r[0]}: needs string, source and status")
            continue
        if not r[3].startswith(("verbatim", "PROPOSED")):
            bad.append(f"{r[0]}: status must be verbatim or PROPOSED")
        if not r[3].startswith("verbatim"):
            continue
        m = CITE.match(r[2])
        quoted = re.match(r'"([^"]+)"', r[1])
        if not m or not quoted:
            bad.append(f"{r[0]}: a verbatim row needs one cite and one quoted string")
            continue
        lines = c.sources.get(m.group("nn") or m.group("named"), [])
        n = int(m.group("first"))
        if n > len(lines) or quoted.group(1) not in lines[n - 1]:
            bad.append(f"{r[0]}: {quoted.group(1)!r} is not verbatim on its cited line")
    return bad


def g_ann(c: Ctx) -> list[str]:
    bad: list[str] = []
    if "**R-4 Announcements ≤ 1 Hz.**" not in c.spec:
        bad.append("R-4 (announcements ≤ 1 Hz) missing")
    cells = [r[-1] for r in table_rows(section(c.spec, "### 10.3")) if len(r) == 4]
    if len(cells) < 30:
        bad.append("the §10.3 announcement column was not found")
    for cell in cells:
        if not cell.startswith(("none", "once")):
            bad.append(f"announcement {cell!r} is neither none nor once (R-4)")
    return bad


def g_rows(c: Ctx) -> list[str]:
    bad: list[str] = []
    defined: set[str] = set()
    for sub, kind in (("### 14.1", "C"), ("### 14.2", "G"), ("### 14.3", "A"), ("### 14.4", "OQ")):
        rows = table_rows(section(c.spec, sub))
        ids = [r[0] for r in rows]
        if ids != [f"D03-{kind}{i}" for i in range(1, len(ids) + 1)] or not ids:
            bad.append(f"{sub} ids {ids} are not D03-{kind}1 … in order")
        for r in rows:
            defined.add(r[0])
            owner = r[-1]
            tickets = TICKET.findall(owner)
            if not tickets and "owner" not in owner:
                bad.append(f"{r[0]}: owner {owner!r} names no ticket and not the owner")
            for t in tickets:
                if t not in c.keys:
                    bad.append(f"{r[0]}: {t} is not a backlog ticket")
    for kind, n in ROW_ID.findall(c.spec + "\n" + c.handoff):
        if f"D03-{kind}{n}" not in defined:
            bad.append(f"D03-{kind}{n} referenced but not defined")
    return bad


def g_walk(c: Ctx) -> list[str]:
    items = re.findall(r"^(\d+)\. ", section(c.spec, "### 17.2"), re.MULTILINE)
    if not items or len(items) > WALK_CAP:
        return [f"walkthrough has {len(items)} items (1 … {WALK_CAP})"]
    return []


def g_heur(c: Ctx) -> list[str]:
    rows = table_rows(section(c.spec, "### 17.1"))
    bad = [f"{r[0]} is not marked (heuristic)" for r in rows if not r[1].startswith("(heuristic)")]
    return bad if rows else ["no heuristic table"]


def inserted_lines(base: list[str], cur: list[str], rel: str) -> tuple[list[int], list[str]]:
    bad: list[str] = []
    inserted: list[int] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(
        None, base, cur, autojunk=False
    ).get_opcodes():
        if op == "insert":
            inserted += range(j1, j2)
        elif op != "equal":
            bad.append(f"{rel}: base lines {i1 + 1}–{i2} {op}d; only insertions are allowed")
    return inserted, bad


def pointer_diff(c: Ctx) -> list[str]:
    """BQ-2: exactly one inserted pointer line under SCR-038 and one under SCR-039."""
    base, cur = c.pointer
    if not base or not cur:
        return [f"{POINTER_REL} not readable at the diff base and in the worktree"]
    inserted, bad = inserted_lines(base, cur, POINTER_REL)
    screens: list[str] = []
    for j in inserted:
        if not POINTER_LINE.match(cur[j]):
            bad.append(f"{POINTER_REL}:{j + 1} is not an E19-D03 pointer line")
        heads = [ln for ln in cur[:j] if ln.startswith("### ")]
        screens.append(heads[-1] if heads else "")
    got = [next((s for s in POINTER_SCREENS if h.startswith(s)), h) for h in screens]
    if got != list(POINTER_SCREENS):
        bad.append(f"{POINTER_REL}: the pointer lines must be one under SCR-038, one under SCR-039")
    return bad


def owned_spans(lines: list[str]) -> dict[str, tuple[int, int]]:
    spans: dict[str, tuple[int, int]] = {}
    for heading in OWNED_ENTRIES:
        start = next((i for i, ln in enumerate(lines) if ln.startswith(heading)), None)
        if start is None:
            continue
        end = next(
            (k for k in range(start + 1, len(lines)) if lines[k].startswith("### ")), len(lines)
        )
        spans[heading] = (start + 1, end)  # the heading itself stays untouched
    return spans


def catalogue_diff(c: Ctx) -> list[str]:
    """BQ-2: `15` changes only inside the CMP-110, CMP-183 and CMP-184 entries, and each changes."""
    base, cur = c.catalogue
    if not base or not cur:
        return [f"{CATALOGUE_REL} not readable at the diff base and in the worktree"]
    bspans, cspans = owned_spans(base), owned_spans(cur)
    if len(bspans) != 3 or len(cspans) != 3:
        return [f"{CATALOGUE_REL}: the three owned entries were not found"]
    bad: list[str] = []
    touched: set[str] = set()

    def owner(spans: dict[str, tuple[int, int]], lo: int, hi: int) -> str | None:
        for h, (s, e) in spans.items():
            if s <= lo and hi <= e:
                return h
        return None

    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(
        None, base, cur, autojunk=False
    ).get_opcodes():
        if op == "equal":
            continue
        hb = owner(bspans, i1, max(i1, i2)) if i2 > i1 else None
        hc = owner(cspans, j1, max(j1, j2)) if j2 > j1 else None
        h = hc or hb
        if (i2 > i1 and hb is None) or (j2 > j1 and hc is None) or (hb and hc and hb != hc):
            bad.append(f"{CATALOGUE_REL}: lines {j1 + 1}–{j2} change outside CMP-110 / 183 / 184")
        elif h:
            touched.add(h)
    for h in OWNED_ENTRIES:
        if h not in touched:
            bad.append(f"{CATALOGUE_REL}: {h.strip()} is not updated (T DoD)")
    return bad


def g_untouched(c: Ctx) -> list[str]:
    bad: list[str] = []
    for p in c.changed:
        if p == POINTER_REL:
            bad += pointer_diff(c)
        elif p == CATALOGUE_REL:
            bad += catalogue_diff(c)
        elif p not in OWN_PATHS:
            bad.append(f"{p} changed; this ticket writes only {', '.join(OWN_PATHS)}")
        elif p.startswith(UNTOUCHED_PREFIXES):
            bad.append(f"{p} is an owner document")
    if CATALOGUE_REL not in c.changed:
        bad.append(f"{CATALOGUE_REL} is unchanged; BQ-2 rewrites the three entries")
    return bad


def public_texts(c: Ctx) -> tuple[tuple[str, str], ...]:
    return (("spec", c.spec), ("hand-off", c.handoff), ("pins", c.pins), ("tool", c.tool))


def g_noclose(c: Ctx) -> list[str]:
    bad: list[str] = []
    for name, text in public_texts(c):
        if CLOSING.search(text):
            bad.append(f"{name}: a closing keyword followed by an issue number")
        if WHAT_FIXES.search(text):
            bad.append(f"{name}: a 'What this … fixes' heading")
    return bad


def g_public(c: Ctx) -> list[str]:
    bad: list[str] = []
    for name, text in public_texts(c):
        for frag in DENY_FRAGMENTS:
            if frag in text:
                bad.append(f"{name}: a denied fragment (host, path or worker name)")
        if name != "tool" and URL.search(text):
            bad.append(f"{name}: a URL")
    return bad


def g_penpot(c: Ctx) -> list[str]:
    bad: list[str] = []
    for need in ("Penpot file `E19-D03 boards`", "page `E19-D03`", "page name and page id only"):
        if need not in c.spec:
            bad.append(f"§0 lacks {need!r} (R7)")
    if "page `E19-D03`" not in c.handoff:
        bad.append("the hand-off must name page `E19-D03`")
    for name, text in public_texts(c)[:3]:
        for frag in PENPOT_DENY:
            if frag in text:
                bad.append(f"{name}: a Penpot workspace, file or team reference (R7)")
    return bad


def g_comment(c: Ctx) -> list[str]:
    bad: list[str] = []
    for name, text in (("spec", c.spec), ("hand-off", c.handoff)):
        for m in COMMENT.finditer(text):
            if not ANCHOR_BODY.match(m.group(1)):
                bad.append(f"{name}: hidden comment {m.group(0)[:40]!r}; only audit anchors")
        if COMMENT_OPEN.search(COMMENT.sub("", text)):
            bad.append(f"{name}: an unterminated comment")
        if re.search("[\\u00ad\\u200b-\\u200d\\u2060\\ufeff]", text):
            bad.append(f"{name}: an invisible character")
    return bad


GATES: dict[str, Callable[[Ctx], list[str]]] = {
    "G-VERSION": g_version,
    "G-CITE": g_cite,
    "G-BQ": g_bq,
    "G-RULED": g_ruled,
    "G-BOARDS": g_boards,
    "G-STATES": g_states,
    "G-RESOLVE": g_resolve,
    "G-AC": g_ac,
    "G-DOD": g_dod,
    "G-TOKENS": g_tokens,
    "G-CONTRAST": g_contrast,
    "G-CVD": g_cvd,
    "G-ENCODING": g_encoding,
    "G-E18": g_e18,
    "G-NPOC": g_npoc,
    "G-TPO": g_tpo,
    "G-T2": g_t2,
    "G-ENV": g_env,
    "G-STORIES": g_stories,
    "G-NEWCMP": g_newcmp,
    "G-HANDOFF": g_handoff,
    "G-COPY": g_copy,
    "G-ANN": g_ann,
    "G-ROWS": g_rows,
    "G-WALK": g_walk,
    "G-HEUR": g_heur,
    "G-UNTOUCHED": g_untouched,
    "G-NOCLOSE": g_noclose,
    "G-PUBLIC": g_public,
    "G-PENPOT": g_penpot,
    "G-COMMENT": g_comment,
}


def run(c: Ctx) -> list[Result]:
    out: list[Result] = []
    for name, gate in GATES.items():
        try:
            detail = gate(c)
        except (IndexError, KeyError, ValueError, TypeError) as exc:  # default-deny: a crash FAILs
            detail = [f"gate raised {type(exc).__name__}: {exc}"]
        out.append(Result(name, not detail, detail))
    return out


# ---------------------------------------------------------------- self-test


def sub_spec(old: str, new: str) -> Callable[[Ctx], Ctx]:
    def apply(c: Ctx) -> Ctx:
        if old not in c.spec:
            raise ValueError(f"mutation anchor missing: {old[:50]!r}")
        return replace(c, spec=c.spec.replace(old, new, 1))

    return apply


def sub_handoff(old: str, new: str) -> Callable[[Ctx], Ctx]:
    def apply(c: Ctx) -> Ctx:
        if old not in c.handoff:
            raise ValueError(f"mutation anchor missing: {old[:50]!r}")
        return replace(c, handoff=c.handoff.replace(old, new, 1))

    return apply


def sub_re(pattern: str, new: str) -> Callable[[Ctx], Ctx]:
    def apply(c: Ctx) -> Ctx:
        spec, n = re.subn(pattern, new, c.spec, count=1, flags=re.MULTILINE)
        if not n:
            raise ValueError(f"mutation pattern missing: {pattern[:50]!r}")
        return replace(c, spec=spec)

    return apply


def sub_both(old: str, new: str) -> Callable[[Ctx], Ctx]:
    def apply(c: Ctx) -> Ctx:
        spec = sub_spec(old, new)(c).spec
        return replace(c, spec=spec, pins=pins_text(spec))

    return apply


def set_pins(c: Ctx) -> Ctx:
    return replace(c, pins=c.pins + "x\n")


def add_changed(c: Ctx) -> Ctx:
    return replace(c, changed=[*c.changed, "docs/plan/22-api-openapi.yaml"])


def extra_pointer(c: Ctx) -> Ctx:
    base, cur = c.pointer
    if not cur:
        raise ValueError(f"{POINTER_REL} not loaded")
    return replace(
        c,
        changed=sorted({*c.changed, POINTER_REL}),
        pointer=(base, [*cur, "- **Hi-fi (E19-D03):** a requirement change"]),
    )


def stray_catalogue(c: Ctx) -> Ctx:
    base, cur = c.catalogue
    i = next((k for k, ln in enumerate(cur) if ln.startswith("### CMP-109 ")), None)
    if i is None:
        raise ValueError("CMP-109 not found")
    edited = [*cur[: i + 2], cur[i + 2] + " (edited)", *cur[i + 3 :]]
    return replace(c, catalogue=(base, edited))


def drift_source(c: Ctx) -> Ctx:
    lines = list(c.sources["24"])
    lines[1014] = lines[1014].replace("default 20", "default 30")
    return replace(c, sources={**c.sources, "24": lines})


def drift_footprint(c: Ctx) -> Ctx:
    lines = list(c.sources["SD"])
    lines[223] = lines[223].replace("palette.green.500", "palette.green.400")
    if lines == c.sources["SD"]:
        raise ValueError("SD footprint value line moved")
    return replace(c, sources={**c.sources, "SD": lines})


_CLOSE = "Clo" + "ses #" + "438"
_HOST = "pen" + "pot.candle" + "viewer.example"
_HEAD = "\n## Wh" + "at this PR fi" + "xes\n"
_FILE = "file" + "-id=0"
_ANCHOR = "### 18.3 Deviations\n"

MUTATIONS: tuple[tuple[str, str, Callable[[Ctx], Ctx]], ...] = (
    ("M-1", "G-VERSION", sub_spec("d02_head=bed73afaa", "d02_head=bed73afab")),
    ("M-2", "G-VERSION", sub_spec("re-pins to its merge commit when it merges", "stays")),
    ("M-3", "G-VERSION", sub_spec(_ANCHOR, _ANCHOR + "ab" * 20 + "\n")),
    ("M-4", "G-CITE", sub_spec("(`24`:1001, :1015 — rays", "(`24`:99999, :1015 — rays")),
    ("M-5", "G-CITE", drift_source),
    ("M-6", "G-BQ", sub_both("Built as: §6.", "Then §6.")),
    ("M-7", "G-RULED", set_pins),
    ("M-8", "G-BOARDS", sub_re(r"^(\| 10 .*\| )PENDING \|$", r"\1DRAWN   |")),
    ("M-9", "G-BOARDS", sub_spec("audit:boards=10 ", "audit:boards=11 ")),
    ("M-10", "G-BOARDS", sub_re(r"^(\| 01 .*\| )dark      ( *\| PENDING)", r"\1light twin\2")),
    (
        "M-11",
        "G-STATES",
        sub_spec("`SCR-038/loading-dark`, `SCR-038/no-history", "`SCR-038/no-history"),
    ),
    ("M-12", "G-STATES", sub_spec(_ANCHOR, _ANCHOR + "`SCR-038/ghost-dark`\n")),
    ("M-13", "G-RESOLVE", sub_re(r"^\| SCR-038/aligned-log ", "| SCR-038/aligned-logx")),
    (
        "M-14",
        "G-AC",
        sub_spec("Scenario: Naked POC clutter is capped", "Scenario: Naked POC capped"),
    ),
    ("M-53", "G-AC", sub_spec("\u201clive preview\u201d", "\u201cpreview\u201d")),
    ("M-15", "G-DOD", sub_spec("written and attached to the ticket.", "written.")),
    ("M-16", "G-TOKENS", sub_re(r"^(\| `color\.profile\.bar` .*\| )shipped ", r"\1PROPOSED")),
    ("M-17", "G-TOKENS", sub_spec(_ANCHOR, _ANCHOR + "Canvas #11151A.\n")),
    (
        "M-18",
        "G-CONTRAST",
        sub_re(r"(`color\.profile\.poc` on .*\| 8\.45  \| )3\.22", r"\g<1>3.40"),
    ),
    ("M-19", "G-CONTRAST", sub_re(r"(`color\.tpo\.letter` on .*\| text     \| )4\.5", r"\g<1>3.0")),
    ("M-20", "G-CVD", sub_spec("3.03 / 3.02 / 3.02", "3.03 / 3.32 / 3.02")),
    (
        "M-21",
        "G-ENCODING",
        sub_spec("a solid right-pointing", "a `color.text.secondary` right-pointing"),
    ),
    (
        "M-22",
        "G-ENCODING",
        sub_spec(
            'a solid 1 px ray from its session to the right edge, "nPOC"',
            'a `pattern.dashed.tested` ray, "nPOC"',
        ),
    ),
    ("M-23", "G-E18", drift_footprint),
    ("M-24", "G-E18", sub_spec("the same token family", "a related family")),
    ("M-25", "G-NPOC", sub_spec("N defaults to 5", "N defaults to 25")),
    ("M-26", "G-TPO", sub_re(r"^(\| compact .*\| 6\.0 +\| )33", r"\g<1>35")),
    ("M-27", "G-TPO", sub_spec("48 periods", "46 periods")),
    ("M-28", "G-T2", sub_spec("sentence form, `rbac.view_as`", "sentence form, `rbac.viewas`")),
    ("M-29", "G-T2", sub_re(r"^(\| SCR-038/presets-view-as .*)\*\*T2 \(§1\.4\)\*\*, ", r"\1")),
    (
        "M-30",
        "G-ENV",
        sub_spec("and no per-account affordance (no", "and a per-account affordance (no"),
    ),
    ("M-31", "G-STORIES", sub_spec("TPO, POC, ValueArea (`15`:1298)", "TPO, POC (`15`:1298)")),
    ("M-32", "G-NEWCMP", sub_spec(_ANCHOR, _ANCHOR + "CMP-999 is new.\n")),
    ("M-33", "G-NEWCMP", sub_spec(_ANCHOR, _ANCHOR + "`color.profile.ghost` is new.\n")),
    ("M-34", "G-HANDOFF", sub_handoff("- [x] **Keyboard table** — table 2 (shared, the", "- the")),
    ("M-35", "G-HANDOFF", sub_handoff("**Motion pair** — N/A — every", "**Motion pair** — every")),
    ("M-36", "G-COPY", sub_re(r'^(\| W-14 \| )"\(estimated\)"', r'\1"(est.)"      ')),
    ("M-37", "G-COPY", sub_spec(_ANCHOR, _ANCHOR + "See W-77.\n")),
    ("M-38", "G-ANN", sub_re(r"^(\| SCR-038/final .*\| )once at close", r"\1per update   ")),
    ("M-39", "G-ROWS", sub_re(r"^\| D03-C4  \|", "| D03-C3  |")),
    ("M-40", "G-ROWS", sub_re(r"^(\| D03-C4 .*\| )E18-D03", r"\1E18-Z99")),
    (
        "M-41",
        "G-WALK",
        sub_spec("10. Review the ten boards", "10. Review.\n11. Review the ten boards"),
    ),
    ("M-42", "G-HEUR", sub_spec("| (heuristic) Error prevention", "| Error prevention")),
    ("M-43", "G-UNTOUCHED", add_changed),
    ("M-44", "G-UNTOUCHED", extra_pointer),
    ("M-45", "G-UNTOUCHED", stray_catalogue),
    ("M-46", "G-NOCLOSE", sub_spec(_ANCHOR, _ANCHOR + _CLOSE + "\n")),
    ("M-47", "G-NOCLOSE", sub_spec("\n## 1. Purpose", _HEAD + "\n## 1. Purpose")),
    ("M-48", "G-PUBLIC", sub_spec(_ANCHOR, _ANCHOR + _HOST + "\n")),
    ("M-49", "G-PUBLIC", sub_spec(_ANCHOR, _ANCHOR + "https" + "://example.org\n")),
    ("M-50", "G-PENPOT", sub_spec(_ANCHOR, _ANCHOR + _FILE + "\n")),
    ("M-51", "G-PENPOT", sub_spec("page name and page id only", "page name")),
    ("M-52", "G-COMMENT", sub_spec(_ANCHOR, _ANCHOR + "<!-- a\nnote -->\n")),
)


def self_test(c: Ctx) -> list[str]:
    errors: list[str] = []
    base_fail = [r.gate for r in run(c) if not r.ok]
    if base_fail:
        errors.append(f"baseline is not clean: {base_fail}")
    covered = {g for _, g, _ in MUTATIONS}
    for g in sorted(set(GATES) - covered):
        errors.append(f"{g} has no mutation")
    for mid, gate, mutate in MUTATIONS:
        try:
            mutated = mutate(c)
        except ValueError as exc:
            errors.append(f"{mid}: {exc}")
            continue
        failed = sorted(r.gate for r in run(mutated) if not r.ok)
        if failed != [gate]:
            errors.append(f"{mid}: expected exactly [{gate}] to FAIL, got {failed}")
    return errors


# ---------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--json", action="store_true")
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--repin-ruled", action="store_true")
    args = ap.parse_args(argv)
    if args.repin_ruled:
        (ROOT / PIN_REL).write_text(pins_text(read(SPEC_REL)), encoding="utf-8", newline="\n")
        print(f"wrote {PIN_REL}")
        return 0
    c = build_ctx()
    if args.self_test:
        errors = self_test(c)
        for e in errors:
            print(f"FAIL {e}")
        print(f"self-test: {len(MUTATIONS)} mutations, {len(errors)} errors")
        return 1 if errors else 0
    results = run(c)
    if args.json:
        print(json.dumps([r.__dict__ for r in results], ensure_ascii=False, indent=1))
    else:
        for r in results:
            print(f"{'PASS' if r.ok else 'FAIL'} {r.gate}")
            for d in r.detail:
                print(f"     {d}")
    fails = sum(not r.ok for r in results)
    if not args.json:
        print(
            f"FAIL {fails} of {len(results)} gates" if fails else f"PASS all {len(results)} gates"
        )
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
