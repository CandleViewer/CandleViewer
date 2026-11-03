#!/usr/bin/env python3
"""E47-D13 (#1311) audit: the conformance report, the statement and the limitations register.

Offline, stdlib only, under `python3 -I`; the one repo module it loads is the product generator
`tools/a11y/conformance.py` (E47-T05, BQ-01), which holds the model it shares. It reads,
AS TEXT at the pinned base (`git show`): the plan texts and merged design texts the spec cites; the
E47-T01 register (`findings.json`) and the E47-D02 register (`47-audit-register.json`) by their
pinned git blob shas, so a tick in another lane never reds `--check`; the token JSON. From the
working tree it reads the spec `docs/design/E47/E47-D13.md`, its hand-off, the `05` section this PR
edits (§8.3), the limitations register `docs/plan/a11y/47-limitations.json`, the generated dry run
`docs/plan/a11y/47-conformance-report.md` and the pins file. Its form follows the E47-D04 tool.

1. **The report.** The dry run at the pins is generated in memory from the two registers under the
   honest-claims rule (spec §3) and the evidence-capture contract (spec §4); the committed file
   `47-conformance-report.md` is E47-T05's, generated from the live registers by
   `tools/a11y/conformance.py`. G-REPORT checks the in-memory dry run (per row; a row another
   gate FAILs prints as NOTE).
2. **Values.** Every `{{KIND:key}}` placeholder is written by `--fill` as `VALUE<!--=KIND:key-->`:
   COUNT (the report, the register, the spec's own tables), LIST (the seeded ten-row sample) and
   CONTRAST (a WCAG 2.x ratio over the resolved tokens). `--check` re-derives each (G-ANCHOR) and
   FAILs a placeholder left behind or a stray HTML comment (G-MARKER).
3. **Cites.** Every `NN`:line and KEY:line cite resolves to a non-blank line at the base (G-CITE);
   every "verbatim" copy string occurs on its cited line (G-QUOTE); every A-row Old fragment
   occurs on its cited line (G-AROW).
4. **Gates.** One FAIL line per gate: G-PENDING (BQ-0 ... BQ-16 once each; BQ-0 ... BQ-12 "RULED
   as proposed (comment 6566807313)", BQ-13 ... BQ-16 "RULED as built, default taken (comment
   6567605210)", none "ruling pending"; the heading names both rulings and the list; the ruling
   quoted verbatim), G-BOARDS, G-ROWS (55 rows, A 31 + AA 24 as the
   D02 catalogue tool lists them, 4.1.1 noted not rowed, levels as the four words), G-CONTRACT
   (spec §4 equals this tool's class map; every criterion in one class), G-CLAIM (no Supports
   without every required artefact on every screen and no open finding; no override raises),
   G-NA (Not Applicable only with a registered reason whose check holds), G-ALT (every Partially
   row names an alternative), G-CANVAS (the six canvas rows name the four layers, never "the
   canvas is accessible"), G-LIMIT (every open T01 finding covered once; dispositions legal; a
   Level A row never an accepted risk; the audit is never a fix ticket), G-PLAIN (statement rows in
   plain words, no criterion number, no jargon), G-DISCLOSE (statement text carries no host, id,
   key-like string or image; internal rows map to a category sentence), G-NORM (`05` §8.3 carries
   the cadence bullet), G-T2, G-RECUR, G-HEUR, G-WALK, G-OWNER, G-INFLIGHT (the in-flight pins and
   their re-pin note), G-UNMERGED, G-URL, G-UNTOUCHED, G-BUDGET, G-MUTLIST.
5. **Pins (G-RULED-PIN).** A whole-document default-deny pin set over every unit of the spec and
   the hand-off in `e47_d13_ruled_pins.txt`; `--repin-ruled` is its only writer.
6. **--self-test** applies every mutation (M-n) in memory with the values frozen at the filled
   baseline; each must add exactly one FAIL, from the gate it names; the files on disk are checked
   byte-identical afterwards (sha256). Output is ASCII.

Usage (from the repo root):
  python3 -I docs/design/_tools/e47_d13_conformance_audit.py --check [--fill]
  python3 -I docs/design/_tools/e47_d13_conformance_audit.py --json
  python3 -I docs/design/_tools/e47_d13_conformance_audit.py --self-test
  python3 -I docs/design/_tools/e47_d13_conformance_audit.py --repin-ruled
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import importlib.util
import json
import math
import random
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
_CONF_REL = "tools/a11y/conformance.py"
_cspec = importlib.util.spec_from_file_location("a11y_conformance", ROOT / _CONF_REL)
assert _cspec and _cspec.loader
C = importlib.util.module_from_spec(_cspec)
sys.modules["a11y_conformance"] = C  # dataclasses resolve their module here
_cspec.loader.exec_module(C)
BASE = "4c662fd5b"  # origin/main when the spec was written; every cite is read here
SPEC_REL = "docs/design/E47/E47-D13.md"
HAND_REL = "docs/design/E47/E47-D13-handoff.md"
TOOL_REL = "docs/design/_tools/e47_d13_conformance_audit.py"
PIN_REL = "docs/design/_tools/e47_d13_ruled_pins.txt"
NORM_REL = "docs/plan/05-accessibility-standard.md"  # §8.3 is edited by this PR (BQ-10)
REPORT_REL = "docs/plan/a11y/47-conformance-report.md"
LIMITS_REL = "docs/plan/a11y/47-limitations.json"
OWN = (SPEC_REL, HAND_REL, TOOL_REL, PIN_REL, NORM_REL, REPORT_REL, LIMITS_REL)
# E47-T05's generator, its checks and its inputs: the successor PRs may touch these (BQ-01).
T05_OWN = (
    _CONF_REL,
    "scripts/tests/test_a11y_conformance.py",
    "docs/plan/a11y/_tools/register.py",
    "docs/plan/a11y/conformance-matrix.md",
    "docs/plan/a11y/finding-record.schema.json",
    ".github/workflows/governance.yml",
)
OWN_BOARDS = re.compile(r"docs/design/E47/img/E47-D13-\d\d-[a-z0-9-]+\.png")
SPEC_BUDGET = 560
HAND_BUDGET = 160

FINDINGS_REL = "docs/plan/a11y/findings.json"
REGISTER_REL = "docs/plan/a11y/47-audit-register.json"
FINDINGS_BLOB = "e01de0d9709d04f43ba0cf2957ca1a85d2a08fbf"  # BQ-15: the inputs pinned by blob
REGISTER_BLOB = "94aa5cc5e1523805e0b6bb4a10e6246e22442256"

PLAN = {
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "12": "docs/plan/12-sitemap.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "30": "docs/plan/30-release-roadmap.md",
    "31": "docs/plan/31-sprint-plan.md",
}
CITE_FILES = {
    "E47J": "docs/plan/backlog/E47.json",
    "Q01": "qa/plans/e47-accessibility-test-plan.md",
    "CATPY": "docs/plan/a11y/_tools/catalogue.py",
    "CAT": "docs/plan/a11y/47-audit-catalogue.md",
    "MATRIX": "docs/plan/a11y/conformance-matrix.md",
    "SCHEMA": "docs/plan/a11y/finding-record.schema.json",
    "REGPY": "docs/plan/a11y/_tools/register.py",
    "SWEEP": "docs/qa/a11y/e47-t01-sweep.md",
    "MXR": "docs/qa/a11y/e47-motion-exception-register.md",
    "ASS": "apps/web/src/features/a11y-preferences/AccessibilitySettingsScreen.tsx",
    "S07": "docs/design/E47/E47-S07.md",
    "D09E09": "docs/design/E09/E09-D09.md",
    "D12TOOL": "docs/design/_tools/e09_d12_audit.py",
}
UNMERGED_PATHS = tuple(f"E47-D{n:02d}.md" for n in (1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14))
INFLIGHT = (("E47-D03", "10eb2a345", "#5392"), ("E47-D04", "1ff5d8cb9", "#5387"))
INFLIGHT_NOTE = "re-pinned to their merge commits at merge"

BQ_LIST_ID = "6566521425"  # the BQ list on #1311 (posted 2026-11-02)
BQ_MARK = "default built; ruling pending"
BQ_IDS = tuple(f"BQ-{n}" for n in range(17))
RULING_ID = "6566807313"  # the ruling of record on #1311 (orchestrator, 2026-11-02 01:20Z)
RULED_MARK = f"RULED as proposed (comment {RULING_ID})"
RULED_IDS = tuple(f"BQ-{n}" for n in range(13))  # the ruling names BQ-0 ... BQ-12
RULING_HEAD = f"BQ-0 … BQ-12 RULED (comment {RULING_ID}, on the list {BQ_LIST_ID})"
READ_ID = "6567605210"  # the design read of record on the PR (orchestrator, 2026-11-02 02:27Z)
READ_MARK = f"RULED as built, default taken (comment {READ_ID})"  # BQ-13 ... BQ-16
READ_HEAD = f"BQ-13 … BQ-16 RULED as built (comment {READ_ID})"
RULING_TEXT = (
    "**Rulings of record — E47-D13 (#1311) BQ-0..BQ-12 (orchestrator, 01:20Z 2026-11-02, unde"
    "r the owner's 2026-10-29 delegation): all ORCH-defaults as proposed (6566521425).** Pins"
    ": BQ-1 — D13 = structure, rules, statement hi-fi and a dry run; T05 (#1360) = the CI gen"
    'erator, the Owner acceptances and the shipped statement; "E47-T06" read as T05 (C-rows).'
    ' BQ-2 — the committed report is a generated **dry run** with the banner "Dry run at `<sh'
    'a>`, not a conformance claim"; columns, row order and remark grammar frozen in the spec.'
    " BQ-3 — the 55 WCAG 2.2 A + AA rows, 4.1.1 noted removed, AAA / Section 508 / EN 301 549"
    ' "not claimed", Not Applicable only with a cited reason. BQ-4 — **honest claims made mec'
    "hanical: Supports only on sufficient artefacts on every non-reserved screen with no open"
    " finding; a reviewer can lower, never raise.** BQ-5 — the SC → artefact table with the `"
    "<kind>:<id>@<sha>` grammar; carried rows posted on the owning tickets, not edits. BQ-6 —"
    ' name the four layers (`05` §6.1–§6.4) in the remarks; never "the canvas is accessible";'
    " Partially until D06 / S01 / S02 evidence. BQ-7 — one limitations register (`47-limitati"
    "ons.json`); a row with no disposition blocks sign-off; **a Level A row is never an accep"
    "ted exception**. BQ-8 — the statement at the as-built `/accessibility` as a SCR-119 sub-"
    'view, all roles, lazy chunk; A-rows to `12` / `14`. BQ-9 — W3C words only ("Fully confor'
    'ms" iff all 55 rows Supports / N/A, else "Partially conforms"); limitations in plain wor'
    "ds, the SC number after. BQ-10 — a versioned statement data chunk; stale → still renders"
    " under a CMP-028 notice; the cadence and owner written into `05` §8.3 in this PR. BQ-11 "
    "— the copy-template feedback path, no personal fields; the submit endpoint a G-row; the "
    "two analytics events as a `14` A-row. BQ-12 — read-only for all roles, no T2 control. `R"
    "efs #1311` + `Partial:` while #1301 is open, then the closing keyword for this ticket."
)

DS_SRC_REL = "packages/ui/tokens"
THEMES: dict[str, tuple[str, ...]] = {
    "dark": ("primitives", "semantic-dark"),
    "light": ("primitives", "semantic-dark", "semantic-light"),
    "hc": ("primitives", "semantic-dark", "semantic-hc"),
}
TEXT_BAR = 4.5  # SC 1.4.3, text
NONTEXT_BAR = 3.0  # SC 1.4.11, non-text (focus ring, borders)
BOARD_PENDING = "pending: drawn in a later push of this PR"

# ---------------------------------------------------------------------------- the criteria
# The model (criteria, evidence-capture contract, honest-claims rule, report renderer, limitations
# checks) lives in the product tool tools/a11y/conformance.py (E47-T05, BQ-01); this audit feeds it
# its blob-pinned inputs and keeps its own gates over the spec, the hand-off and the report.

SC = C.SC
REMOVED = C.REMOVED
LEVEL_WORDS = C.LEVEL_WORDS
CONTRACT = C.CONTRACT
REGISTER_KINDS = C.REGISTER_KINDS
ALT = C.ALT
CANVAS = C.CANVAS
CANVAS_REMARK = C.CANVAS_REMARK
NA_REASONS = C.NA_REASONS
TRADING_BANDS = C.TRADING_BANDS
Row = C.Row
sc_key = C.sc_key
class_of = C.class_of
cell_verdict = C.cell_verdict
overrides = C.overrides
limits_data = C.limits_data
limit_rows = C.limit_rows
disposition_ok = C.disposition_ok
unowned = C.unowned
table = C.table
counts = C.counts
status_words = C.status_words
SAMPLE_SEED = BASE
SAMPLE_N = 10

# ---------------------------------------------------------------------------- statement checks

URL_RE = C.URL_RE
KEYLIKE_RE = C.KEYLIKE_RE
IMAGE_RE = C.IMAGE_RE
IDLIKE_RE = C.IDLIKE_RE
SCNUM_RE = re.compile(r"\b\d\.\d{1,2}\.\d{1,2}\b")
JARGON_RE = re.compile(
    r"\b[Aa]ria\b|aria-|\bARIA\b|\bDOM\b|\bWCAG\b|\b[Vv]iewport\b|\bCSS\b|\bpx\b|role=|\bSC\b|\bAT\b"
)
PLAIN_MAX_WORDS = 30
AGENT_RE = re.compile(r"worker|orchestrator|\bagent\b|lane\b", re.IGNORECASE)
OWNER_OK_RE = re.compile(r"\bE\d\d-[A-Z]+\d\d\b|\bowner")
TICKET_RE = C.TICKET_RE

Finding = tuple[str, str, str, str]  # gate, message, doc, region
Values = dict[str, str]
SECONDARY = ("G-RULED-PIN", "G-REPORT")


# ---------------------------------------------------------------------------- git and files


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=True,
    ).stdout


@functools.lru_cache(maxsize=64)
def at_base(rel: str) -> str:
    return git("show", f"{BASE}:{rel}")


@functools.lru_cache(maxsize=64)
def base_lines(rel: str) -> tuple[str, ...]:
    return tuple(at_base(rel).split("\n"))


@functools.lru_cache(maxsize=4)
def blob_json(blob: str) -> dict[str, object]:
    data = json.loads(git("cat-file", "-p", blob))
    return data if isinstance(data, dict) else {}


def changed_paths() -> tuple[str, ...]:
    fork = git("merge-base", "HEAD", "origin/main").strip()
    tracked = git("diff", "--name-only", fork).split()
    untracked = git("ls-files", "--others", "--exclude-standard").split()
    return tuple(sorted(set(tracked) | set(untracked)))


# ---------------------------------------------------------------------------- markdown model


@dataclass(frozen=True)
class Texts:
    spec: str
    hand: str
    norm: str
    report: str
    limits: str
    changed: tuple[str, ...]

    def doc(self, name: str) -> str:
        return {
            "spec": self.spec,
            "hand": self.hand,
            "norm": self.norm,
            "report": self.report,
            "limits": self.limits,
        }[name]


def line_regions(text: str) -> list[str]:
    """The heading path (with an occurrence suffix) of every line; a heading belongs to itself."""
    stack: list[tuple[int, str]] = []
    seen: dict[str, int] = {}
    current = "(top)#1"
    out: list[str] = []
    for line in text.split("\n"):
        m = re.match(r"^(#{1,6}) (.*)$", line)
        if m:
            level = len(m.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, m.group(2).strip()))
            path = " > ".join(t for _, t in stack)
            seen[path] = seen.get(path, 0) + 1
            current = f"{path}#{seen[path]}"
        out.append(current)
    return out


def section(text: str, prefix: str) -> tuple[int, int, str]:
    """(first body line index, end index, region) of the heading starting with `prefix`."""
    lines = text.split("\n")
    regions = line_regions(text)
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            level = len(line) - len(line.lstrip("#"))
            end = len(lines)
            for j in range(i + 1, len(lines)):
                m = re.match(r"^(#{1,6}) ", lines[j])
                if m and len(m.group(1)) <= level:
                    end = j
                    break
            return i + 1, end, regions[i]
    return 0, 0, f"(missing {prefix})"


def body(text: str, prefix: str) -> list[str]:
    s, e, _ = section(text, prefix)
    return text.split("\n")[s:e]


def cells(line: str) -> list[str]:
    inner = line.strip().removeprefix("|").removesuffix("|")
    return [c.strip() for c in re.split(r"(?<!\\)\|", inner)]


def is_rule_row(line: str) -> bool:
    return bool(re.fullmatch(r"\|[\s:|-]+\|", line.strip()))


def tables(text: str, prefix: str) -> list[list[list[str]]]:
    out: list[list[list[str]]] = []
    cur: list[list[str]] = []
    for line in body(text, prefix):
        if line.strip().startswith("|"):
            if not is_rule_row(line):
                cur.append(cells(line))
        elif cur:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def first_table(text: str, prefix: str) -> list[list[str]]:
    ts = tables(text, prefix)
    return ts[0] if ts else []


def plain(cell: str) -> str:
    return cell.replace("`", "").strip()


# ---------------------------------------------------------------------------- anchors

ANCHOR_RE = re.compile(
    r"(?<![0-9A-Za-z.,])([0-9A-Za-z.,]+)<!--=([A-Z]+):([a-z0-9.\-]+)-->", re.DOTALL
)
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z]+):([a-z0-9.\-]+)\}\}")
ANCHOR_TAG_RE = re.compile(r"<!--=[A-Z]+:[a-z0-9.\-]+-->", re.DOTALL)


def cut_anchors(text: str) -> str:
    return ANCHOR_RE.sub(lambda m: f"<!--={m.group(2)}:{m.group(3)}-->", text)


# ---------------------------------------------------------------------------- the registers


def t01() -> dict[str, object]:
    return blob_json(FINDINGS_BLOB)


def d02() -> dict[str, object]:
    return blob_json(REGISTER_BLOB)


def dicts(value: object) -> list[dict[str, object]]:
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def text_of(value: object) -> str:
    return value if isinstance(value, str) else ""


def t01_screens() -> list[dict[str, object]]:
    return dicts(t01().get("screens"))


def t01_findings() -> list[dict[str, object]]:
    return dicts(t01().get("findings"))


def t01_patterns() -> list[dict[str, object]]:
    return dicts(t01().get("patterns"))


def audited_sha() -> str:
    return text_of(t01().get("auditedSha"))[:9]


def live_screens() -> list[dict[str, object]]:
    return [s for s in t01_screens() if not text_of(s.get("coverage")).startswith("reserved")]


@functools.lru_cache(maxsize=1)
def pinned() -> C.Inputs:
    """The model's inputs at this audit's pins (spec §4: a tick in another lane never reds it)."""
    return C.Inputs(
        findings=t01(),
        register=d02(),
        plan14=at_base(PLAN["14"]),
        findings_blob=FINDINGS_BLOB,
        register_blob=REGISTER_BLOB,
    )


def determine(sc: str, limits: str) -> tuple[C.Row, bool]:
    return C.determine(sc, limits, pinned())


def model(limits: str) -> list[C.Row]:
    return C.model(limits, pinned())


def render_report(limits: str) -> str:
    """The dry run at the pins: the committed report is E47-T05's, generated from the live inputs."""
    return C.render_report(
        limits,
        pinned(),
        generator=TOOL_REL,
        ref=BASE,
        note="E47-T05 may replace the generator, not this format.",
        exceptions=False,
    )


# ---------------------------------------------------------------------------- limitations


# ---------------------------------------------------------------------------- the report


def report_rows(report: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for r in first_table(report, "## Criteria")[1:]:
        if r:
            out[r[0].split(" ")[0]] = r
    return out


def sample(limits: str) -> list[str]:
    rng = random.Random(SAMPLE_SEED)
    return sorted(rng.sample(sorted(SC, key=sc_key), SAMPLE_N), key=sc_key)


# ---------------------------------------------------------------------------- contrast


def token_file(name: str) -> dict[str, object]:
    data = json.loads(at_base(f"{DS_SRC_REL}/{name}.tokens.json"))
    return {k: v.get("$value") for k, v in data.items() if isinstance(v, dict)}


@functools.lru_cache(maxsize=4)
def load_theme(name: str) -> dict[str, object]:
    merged: dict[str, object] = {}
    for f in THEMES[name]:
        merged.update(token_file(f))
    return merged


def hex_of(theme: str, name: str) -> str | None:
    tokens = load_theme(theme)
    value: object = tokens.get(name)
    hops = 0
    while isinstance(value, str) and value.startswith("{") and value.endswith("}") and hops < 12:
        value, hops = tokens.get(value[1:-1]), hops + 1
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
        return None
    return value.upper()


def luminance(hex6: str) -> float:
    def lin(c: int) -> float:
        x = c / 255.0
        return x / 12.92 if x <= 0.04045 else float(((x + 0.055) / 1.055) ** 2.4)

    h = hex6.lstrip("#")
    r, g, b = (lin(int(h[i : i + 2], 16)) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def show_ratio(r: float) -> str:
    return f"{math.floor(r * 100) / 100:.2f}"


def contrast_values(spec: str) -> Values:
    """CONTRAST:<pair>.<theme> for every row of §7.6's table: `fg` on `bg`."""
    out: Values = {}
    for row in first_table(spec, "### 7.6")[1:]:
        if len(row) < 3:
            continue
        pid, fg, bg = row[0].lower(), plain(row[1]), plain(row[2])
        for theme in THEMES:
            a, b = hex_of(theme, fg), hex_of(theme, bg)
            if a and b:
                out[f"CONTRAST:{pid}.{theme}"] = show_ratio(contrast(a, b))
    return out


# ---------------------------------------------------------------------------- values


def count_values(t: Texts) -> Values:
    rows = model(t.limits)
    c = counts(rows)

    def n_rows(prefix: str) -> int:
        return max(0, len(first_table(t.spec, prefix)) - 1)

    v: Values = {
        "COUNT:report.rows": str(len(rows)),
        "COUNT:report.a": str(sum(1 for r in rows if r.level == "A")),
        "COUNT:report.aa": str(sum(1 for r in rows if r.level == "AA")),
        "COUNT:report.supports": str(c["Supports"]),
        "COUNT:report.partial": str(c["Partially Supports"]),
        "COUNT:report.dns": str(c["Does Not Support"]),
        "COUNT:report.na": str(c["Not Applicable"]),
        "COUNT:screens.live": str(len(live_screens())),
        "COUNT:limits.rows": str(len(limit_rows(t.limits))),
        "COUNT:limits.blocked": str(len(unowned(t.limits))),
        "COUNT:t01.open": str(sum(1 for f in t01_findings() if f.get("status") != "fixed")),
        "COUNT:boards": str(n_rows("## 0.")),
        "COUNT:boards.twins": str(
            sum(1 for r in first_table(t.spec, "## 0.")[1:] if len(r) > 3 and r[3] != "dark")
        ),
        "COUNT:copy": str(n_rows("## 11.")),
        "COUNT:heuristics": str(n_rows("## 12.")),
        "COUNT:mutations": str(len(MUTATIONS)),
        "COUNT:walkthrough": str(sum(1 for ln in body(t.hand, "## §E") if ln.startswith("- ["))),
        "LIST:sample": ",".join(sample(t.limits)),
    }
    return v


def compute_values(t: Texts) -> Values:
    return {**contrast_values(t.spec), **count_values(t)}


# ---------------------------------------------------------------------------- mutations


@dataclass(frozen=True)
class Mutation:
    mid: str
    what: str
    gate: str
    doc: str  # "spec", "hand", "norm", "report", "limits" or "changed"
    where: str  # a heading prefix; "" = the whole document; "<eof>" = append
    old: str
    new: str


MUTATIONS: tuple[Mutation, ...] = ()  # set below, after the gates


def mutation_rows() -> str:
    return "\n".join(f"| {m.mid} | {m.what} | {m.gate} |" for m in MUTATIONS)


def apply_mutation(t: Texts, m: Mutation) -> Texts:
    if m.doc == "changed":
        return replace(t, changed=(*t.changed, m.new))
    text = t.doc(m.doc)
    if m.where == "<eof>":
        new_text = text + m.new
    else:
        if m.where:
            s, e, _ = section(text, m.where)
            lines = text.split("\n")
            offset = len("\n".join(lines[:s])) + (1 if s else 0)
            span = "\n".join(lines[s:e])
        else:
            offset, span = 0, text
        found = re.search(re.sub(r"(?:\\ )+", "[ ]+", re.escape(m.old)), span)
        if found is None:
            raise SystemExit(f"FAIL {m.mid}: its target text is not in {m.doc} {m.where!r}")
        k = found.start() + offset
        new_text = text[:k] + m.new + text[k + len(found.group(0)) :]
    if m.doc == "spec":
        return replace(t, spec=new_text)
    if m.doc == "hand":
        return replace(t, hand=new_text)
    if m.doc == "norm":
        return replace(t, norm=new_text)
    if m.doc == "report":
        return replace(t, report=new_text)
    return replace(t, limits=new_text)


# ---------------------------------------------------------------------------- gates


def g_anchor(t: Texts, values: Values) -> list[Finding]:
    out: list[Finding] = []
    for doc in ("spec", "hand"):
        text = t.doc(doc)
        regions = line_regions(text)
        for i, line in enumerate(text.split("\n")):
            for m in ANCHOR_RE.finditer(line):
                key = f"{m.group(2)}:{m.group(3)}"
                want = values.get(key)
                if want is None:
                    out.append(("G-ANCHOR", f"unknown anchor {key}", doc, regions[i]))
                elif m.group(1) != want:
                    out.append(
                        ("G-ANCHOR", f"{key} reads {m.group(1)}, derives {want}", doc, regions[i])
                    )
    return out


def g_marker(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for doc in ("spec", "hand"):
        text = t.doc(doc)
        regions = line_regions(text)
        for i, line in enumerate(text.split("\n")):
            if "{{" in line:
                out.append(("G-MARKER", f"unfilled placeholder on line {i + 1}", doc, regions[i]))
            if "<!--" in ANCHOR_TAG_RE.sub("", line):
                out.append(("G-MARKER", f"a stray HTML comment on line {i + 1}", doc, regions[i]))
    return out


CITE_RE = re.compile(
    r"(?:`(\d\d)`|\b(" + "|".join(CITE_FILES) + r"))" r"(:\d+(?:–\d+)?(?:, :\d+(?:–\d+)?)*)"
)


def cite_targets(line: str) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for m in CITE_RE.finditer(line):
        rel = PLAN.get(m.group(1) or "") or CITE_FILES.get(m.group(2) or "")
        if rel is None:
            out.append((f"?{m.group(1)}", 0))
            continue
        for a, b in re.findall(r":(\d+)(?:–(\d+))?", m.group(3)):
            out.append((rel, int(a)))
            if b:
                out.append((rel, int(b)))
    return out


def g_cite(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for doc in ("spec", "hand"):
        text = t.doc(doc)
        regions = line_regions(text)
        for i, line in enumerate(text.split("\n")):
            for rel, n in cite_targets(line):
                if rel.startswith("?"):
                    out.append(("G-CITE", f"unknown cite key {rel[1:]}", doc, regions[i]))
                    continue
                lines = base_lines(rel)
                if not (1 <= n <= len(lines)) or not lines[n - 1].strip():
                    out.append(("G-CITE", f"{rel}:{n} is not a non-blank line", doc, regions[i]))
    return out


def cited_text(cite_cell: str) -> str:
    return "\n".join(
        base_lines(rel)[n - 1]
        for rel, n in cite_targets(cite_cell)
        if not rel.startswith("?") and 1 <= n <= len(base_lines(rel))
    )


def g_quote(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    _, _, region = section(t.spec, "## 11.")
    for row in first_table(t.spec, "## 11.")[1:]:
        if len(row) < 4 or not row[3].startswith("verbatim"):
            continue
        s = row[1].strip().strip('"')
        if s not in cited_text(row[2]):
            out.append(("G-QUOTE", f"{row[0]} is not verbatim on {row[2]}", "spec", region))
    return out


def g_arow(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    _, _, region = section(t.hand, "## §C")
    for row in first_table(t.hand, "## §C")[1:]:
        if len(row) < 5:
            continue
        old = row[3].replace("\\|", "|")
        if old.startswith("`") and old.endswith("`") and old.count("`") == 2:
            old = old[1:-1]
        if old not in cited_text(row[2]):
            out.append(("G-AROW", f"{row[0]}'s Old is not verbatim on its line", "hand", region))
    return out


def g_pending(t: Texts) -> list[Finding]:
    s, e, region = section(t.spec, "## The questions")
    head = t.spec.split("\n")[s - 1] if s else ""
    lines = t.spec.split("\n")[s:e]
    bad: list[str] = []
    if RULING_HEAD not in head or READ_HEAD not in head:
        bad.append("the heading does not name both rulings and the list")
    if not any(ln == "> " + RULING_TEXT for ln in lines):
        bad.append("the ruling is not quoted verbatim")
    for bq in BQ_IDS:
        rows = [ln for ln in lines if ln.startswith(f"- **{bq}**")]
        want, other = (RULED_MARK, READ_MARK) if bq in RULED_IDS else (READ_MARK, RULED_MARK)
        if len(rows) != 1:
            bad.append(f"{bq} appears {len(rows)} times")
        elif want not in rows[0] or other in rows[0] or BQ_MARK in rows[0]:
            bad.append(f"{bq} is not marked '{want}'")
    return [("G-PENDING", b, "spec", region) for b in bad]


def g_boards(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 0.")
    rows = first_table(t.spec, "## 0.")[1:]
    bad: list[str] = []
    if not 1 <= len(rows) <= 10:
        bad.append(f"{len(rows)} boards")
    twins = sum(1 for r in rows if len(r) > 3 and r[3] != "dark")
    if twins * 3 > len(rows):
        bad.append(f"{twins} twins of {len(rows)}")
    for r in rows:
        if len(r) < 5 or r[4] != BOARD_PENDING or r[3] not in ("dark", "light", "hc"):
            bad.append(f"board {r[0] if r else '?'} is not pending with a theme")
        if not re.fullmatch(
            rf"`E47-D13 / {re.escape(r[0])} [a-z0-9-]+`", r[1] if len(r) > 1 else ""
        ):
            bad.append(f"board {r[0] if r else '?'} has no `E47-D13 / NN slug` name")
    if not any(
        ln.startswith("**Not drawn — the text is binding**") for ln in body(t.spec, "## 0.")
    ):
        bad.append("no not-drawn paragraph")
    return [("G-BOARDS", b, "spec", region) for b in bad]


def g_report(t: Texts) -> list[Finding]:
    want = render_report(t.limits)
    if want == t.report:
        return []
    have_rows, want_rows = report_rows(t.report), report_rows(want)
    out: list[Finding] = []
    for sc in sorted(set(have_rows) | set(want_rows), key=sc_key_safe):
        if have_rows.get(sc) != want_rows.get(sc):
            out.append(("G-REPORT", f"row {sc} is stale", "report", f"row {sc}"))
    if outside_rows(want) != outside_rows(t.report):
        out.append(("G-REPORT", "the report is stale outside its rows (run --fill)", "report", ""))
    return out


def outside_rows(text: str) -> list[str]:
    return [ln for ln in text.split("\n") if not re.match(r"^\| \d", ln)]


def sc_key_safe(sc: str) -> tuple[int, ...]:
    try:
        return sc_key(sc)
    except ValueError:
        return (99,)


def g_rows(t: Texts) -> list[Finding]:
    bad: list[tuple[str, str]] = []
    have = report_rows(t.report)
    want_a = set(re.findall(r"\d+\.\d+\.\d+", base_lines(CITE_FILES["CATPY"])[55])) - {REMOVED}
    want_aa = set(re.findall(r"\d+\.\d+\.\d+", base_lines(CITE_FILES["CATPY"])[59]))
    if {s for s, (lv, _) in SC.items() if lv == "A"} != want_a:
        bad.append(("the Level A set differs from the D02 catalogue tool", ""))
    if {s for s, (lv, _) in SC.items() if lv == "AA"} != want_aa:
        bad.append(("the Level AA set differs from the D02 catalogue tool", ""))
    if set(have) != set(SC):
        bad.append((f"{len(have)} rows, not the {len(SC)} criteria", ""))
    for sc, r in have.items():
        if sc in SC and (len(r) < 3 or r[1] != SC[sc][0]):
            bad.append((f"row {sc} has the wrong level", f"row {sc}"))
        if len(r) < 3 or r[2] not in LEVEL_WORDS:
            bad.append((f"row {sc}'s level is not one of the four words", f"row {sc}"))
    if f"{REMOVED} Parsing" not in t.report:
        bad.append((f"{REMOVED} is not noted as removed", ""))
    return [("G-ROWS", b, "report", reg) for b, reg in bad]


def g_contract(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 4.")
    bad: list[str] = []
    rows = {r[0]: r for r in first_table(t.spec, "## 4.")[1:] if r}
    if set(rows) != set(CONTRACT):
        bad.append("the class rows differ from the tool's")
    for k, (scs, kinds, alt) in CONTRACT.items():
        r = rows.get(k)
        if r is None or len(r) < 4:
            continue
        if r[1].split() != list(scs):
            bad.append(f"{k}'s criteria differ")
        if plain(r[2]).split(" + ") != list(kinds):
            bad.append(f"{k}'s artefact kinds differ")
        if plain(r[3]) != plain(ALT[alt]):
            bad.append(f"{k}'s alternative differs")
    every = [sc for scs, _, _ in CONTRACT.values() for sc in scs]
    if sorted(every) != sorted(SC):
        bad.append("a criterion is in no class or in two")
    return [("G-CONTRACT", b, "spec", region) for b in bad]


def g_claim(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for sc in SC:
        _, raised = determine(sc, t.limits)
        if raised:
            out.append(("G-CLAIM", f"an override raises {sc}", "limits", ""))
    for sc, r in report_rows(t.report).items():
        if len(r) < 5 or sc not in SC:
            continue
        if r[2] == "Supports":
            row, _ = determine(sc, t.limits)
            if row.conformance != "Supports" or r[4] in ("", "none produced"):
                out.append(
                    ("G-CLAIM", f"{sc} claims Supports without evidence", "report", f"row {sc}")
                )
        if r[2] in ("Partially Supports", "Does Not Support") and not any(
            x in r[3] for x in ("evidence not produced", "not yet produced", "blocker")
        ):
            out.append(("G-CLAIM", f"{sc} hides its missing evidence", "report", f"row {sc}"))
    return out


def g_na(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    reasons = {reason for reason, _ in NA_REASONS.values()}
    for sc, r in report_rows(t.report).items():
        if len(r) > 3 and r[2] == "Not Applicable":
            ok = any(r[3] == f"not applicable: {x}" for x in reasons) and class_of(sc) in NA_REASONS
            if not ok:
                out.append(
                    (
                        "G-NA",
                        f"{sc} is Not Applicable without a registered reason",
                        "report",
                        f"row {sc}",
                    )
                )
    return out


def g_alt(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    alts = set(ALT.values())
    for sc, r in report_rows(t.report).items():
        if len(r) > 5 and r[2] == "Partially Supports" and r[5] not in alts:
            out.append(
                ("G-ALT", f"{sc} is Partially Supports with no alternative", "report", f"row {sc}")
            )
    return out


def g_canvas(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    rows = report_rows(t.report)
    for sc in CANVAS:
        r = rows.get(sc, [])
        if len(r) < 4 or CANVAS_REMARK not in r[3]:
            out.append(("G-CANVAS", f"{sc} does not name the four layers", "report", f"row {sc}"))
    for doc in ("spec", "hand", "report"):
        # the ruling's quoted prohibition (never "the canvas is accessible") is not a claim
        if re.search(
            r'(?<!never ")the canvas (?:itself )?is accessible', t.doc(doc), re.IGNORECASE
        ):
            out.append(("G-CANVAS", "claims the canvas is accessible", doc, ""))
    return out


def g_limit(t: Texts) -> list[Finding]:
    return [("G-LIMIT", b, "limits", "") for b in C.limits_problems(t.limits, pinned())]


def statement_rows(t: Texts) -> list[dict[str, object]]:
    return [r for r in limit_rows(t.limits) if r.get("disclosure") == "statement"]


def g_plain(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for r in statement_rows(t):
        for field in ("plain", "impact", "workaround"):
            s = text_of(r.get(field))
            why = ""
            if SCNUM_RE.search(s):
                why = "a criterion number"
            elif m := JARGON_RE.search(s):
                why = f"jargon ({m.group(0)})"
            elif len(s.split()) > PLAIN_MAX_WORDS:
                why = f"more than {PLAIN_MAX_WORDS} words"
            elif s and not s.endswith("."):
                why = "no full stop"
            if why:
                out.append(("G-PLAIN", f"{text_of(r.get('id'))}.{field}: {why}", "limits", ""))
    return out


def g_disclose(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    data = limits_data(t.limits)
    cats = data.get("categories")
    catd = cats if isinstance(cats, dict) else {}
    texts = [
        (text_of(r.get("id")), text_of(r.get(f)))
        for r in statement_rows(t)
        for f in ("plain", "impact", "workaround")
    ]
    texts += [(f"category {k}", text_of(v)) for k, v in catd.items()]
    texts += [(r[0], r[1]) for r in first_table(t.spec, "## 11.")[1:] if len(r) > 1]
    for rid, s in texts:
        for rx, what in (
            (URL_RE, "a host"),
            (KEYLIKE_RE, "a key-like string"),
            (IMAGE_RE, "an image"),
            (IDLIKE_RE, "an id"),
        ):
            if rx.search(s):
                out.append(("G-DISCLOSE", f"{rid}: {what} in statement text", "limits", ""))
    for r in limit_rows(t.limits):
        if r.get("disclosure") not in ("statement", "internal"):
            out.append(("G-DISCLOSE", f"{text_of(r.get('id'))}: disclosure unset", "limits", ""))
        if r.get("disclosure") == "internal" and text_of(r.get("category")) not in catd:
            out.append(
                ("G-DISCLOSE", f"{text_of(r.get('id'))}: no category sentence", "limits", "")
            )
    return out


NORM_NEEDS = (
    "Accessibility statement and conformance report",
    "every release",
    "in-scope screen",
    "review date",
    "§8.1",
    "regression checklist",
    "E47-D13",
)


def g_norm(t: Texts) -> list[Finding]:
    lines = body(t.norm, "### 8.3")
    hit = [ln for ln in lines if ln.startswith("- **Accessibility statement and conformance")]
    if len(hit) != 1:
        return [("G-NORM", f"{len(hit)} cadence bullets in `05` §8.3", "norm", "")]
    miss = [x for x in NORM_NEEDS if x not in hit[0]]
    return [("G-NORM", f"the §8.3 bullet lacks {x!r}", "norm", "") for x in miss]


T2_NEEDS = (
    "CMP-079 RbacGate",
    "CMP-019 Icon `lock`",
    "rendering 2a",
    "at mount",
    "one polite announcement",
    "`↑` / `↓`",
    '`aria-disabled="true"`',
)


def g_t2(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "### 7.8")
    para = [ln for ln in body(t.spec, "### 7.8") if "**The T2 paragraph" in ln]
    bad: list[str] = []
    if len(para) != 1:
        bad.append(f"{len(para)} T2 paragraphs in §7.8")
    else:
        bad += [f"the T2 paragraph lacks {x}" for x in T2_NEEDS if x not in para[0]]
    out: list[Finding] = [("G-T2", b, "spec", region) for b in bad]
    hl = t.hand.split("\n")
    comp = [i for i, ln in enumerate(hl) if ln.startswith("Components:")]
    if not comp or "CMP-079" not in hl[comp[0]] or "CMP-019" not in hl[comp[0]]:
        reg = line_regions(t.hand)[comp[0]] if comp else ""
        out.append(("G-T2", "the hand-off's component list lacks CMP-079 or CMP-019", "hand", reg))
    return out


RECUR_NEEDS = {
    "### 7.5": ("200 %", "text scale", "fixed-height", "320 CSS px"),
    "### 7.6": ("forced-colors",),
    "### 7.4": ("initial focus", "`Enter` in a field", "returns to"),
}


def g_recur(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for prefix, needs in RECUR_NEEDS.items():
        text = "\n".join(body(t.spec, prefix))
        _, _, region = section(t.spec, prefix)
        out += [
            ("G-RECUR", f"{prefix} lacks {x!r}", "spec", region) for x in needs if x not in text
        ]
    return out


def row_bar(row: list[str]) -> float:
    """The pair's bar from its last cell (`4.5:1` text, `3:1` non-text); never under 3:1."""
    m = re.fullmatch(r"(\d+(?:\.\d+)?):1", plain(row[-1])) if row else None
    return max(NONTEXT_BAR, float(m.group(1))) if m else TEXT_BAR


def g_contrast(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "### 7.6")
    rows = first_table(t.spec, "### 7.6")[1:]
    vals = contrast_values(t.spec)
    bad: list[str] = []
    if len(rows) < 6:
        bad.append(f"{len(rows)} pairs, not the six")
    for r in rows:
        bar = row_bar(r)
        for theme in THEMES:
            v = vals.get(f"CONTRAST:{r[0].lower()}.{theme}")
            if v is None or float(v) < bar:
                bad.append(f"{r[0]} in {theme} is {v}, under {bar}:1")
    return [("G-CONTRAST", b, "spec", region) for b in bad]


def g_heur(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 12.")
    rows = first_table(t.spec, "## 12.")[1:]
    bad = [r[0] for r in rows if len(r) < 2 or not r[1].startswith("(heuristic)")]
    return [("G-HEUR", f"{b} is not marked (heuristic)", "spec", region) for b in bad]


def g_walk(t: Texts) -> list[Finding]:
    _, _, region = section(t.hand, "## §E")
    n = sum(1 for ln in body(t.hand, "## §E") if ln.startswith("- ["))
    return [] if 1 <= n <= 10 else [("G-WALK", f"{n} walkthrough items", "hand", region)]


def g_owner(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for prefix in ("### 14.2", "### 14.3"):
        _, _, region = section(t.spec, prefix)
        for r in first_table(t.spec, prefix)[1:]:
            owner = r[3] if len(r) > 3 else ""
            if AGENT_RE.search(owner) or not OWNER_OK_RE.search(owner):
                out.append(("G-OWNER", f"{r[0]}'s owner {owner!r}", "spec", region))
    return out


def g_inflight(t: Texts) -> list[Finding]:
    sl = t.spec.split("\n")
    idx = [i for i, ln in enumerate(sl) if ln.startswith("**Start.**")]
    if len(idx) != 1:
        return [("G-INFLIGHT", "no single Start line", "spec", "(top)#1")]
    region = line_regions(t.spec)[idx[0]]
    start = [sl[idx[0]]]
    bad = [
        f"{key} is not pinned at `{sha}` / PR {pr}"
        for key, sha, pr in INFLIGHT
        if f"{key} (PR {pr}, head `{sha}`)" not in start[0]
    ]
    if INFLIGHT_NOTE not in start[0]:
        bad.append("the re-pin note is missing")
    return [("G-INFLIGHT", b, "spec", region) for b in bad]


def g_lines(t: Texts, gate: str, test: Callable[[str], bool], what: str) -> list[Finding]:
    out: list[Finding] = []
    for doc in ("spec", "hand"):
        text = t.doc(doc)
        regions = line_regions(text)
        for i, line in enumerate(text.split("\n")):
            if test(line):
                out.append((gate, f"{what} on line {i + 1}", doc, regions[i]))
    return out


def g_untouched(t: Texts) -> list[Finding]:
    extra = [
        p for p in t.changed if p not in OWN and p not in T05_OWN and not OWN_BOARDS.fullmatch(p)
    ]
    return [("G-UNTOUCHED", f"{p} differs from the base", "changed", "") for p in extra]


def g_budget(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for doc, cap in (("spec", SPEC_BUDGET), ("hand", HAND_BUDGET)):
        if t.doc(doc).count("\n") > cap:
            region = line_regions(t.doc(doc))[-1]
            out.append(("G-BUDGET", f"{doc} has more than {cap} lines", doc, region))
    return out


def g_mutlist(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 13.")
    rows = [(r[0], r[1], r[2]) for r in first_table(t.spec, "## 13.")[1:] if len(r) > 2]
    want = [(m.mid, m.what, m.gate) for m in MUTATIONS]
    return (
        [] if rows == want else [("G-MUTLIST", "§13 differs from the tool's list", "spec", region)]
    )


# ---------------------------------------------------------------------------- pins


def units(doc: str, text: str) -> list[tuple[str, str, str, str]]:
    out: list[tuple[str, str, str, str]] = []
    regions = line_regions(text)
    shape: dict[str, str] = {}
    prose: dict[str, int] = {}
    leads: dict[tuple[str, str], int] = {}
    order: list[str] = []
    for i, line in enumerate(text.split("\n")):
        reg = regions[i]
        if reg not in shape:
            shape[reg] = ""
            order.append(reg)
        text_line = re.sub(r"\s+", " ", cut_anchors(line)).strip()
        if not text_line:
            continue
        if re.match(r"^#{1,6} ", line):
            shape[reg] += "h"
            out.append((doc, reg, "heading", text_line))
        elif line.strip().startswith("|"):
            if is_rule_row(line):
                shape[reg] += "r"
                continue
            shape[reg] += "t"
            c = cells(cut_anchors(line))
            lead = re.sub(r"\s+", " ", c[0]) if c else ""
            leads[(reg, lead)] = leads.get((reg, lead), 0) + 1
            loc = f"row {lead}" + (f" #{leads[(reg, lead)]}" if leads[(reg, lead)] > 1 else "")
            out.append((doc, reg, loc, " | ".join(re.sub(r"\s+", " ", x) for x in c)))
        else:
            shape[reg] += "p"
            prose[reg] = prose.get(reg, 0) + 1
            out.append((doc, reg, f"l{prose[reg]}", text_line))
    for reg in order:
        out.append((doc, reg, "shape", shape[reg] or "(empty)"))
    return out


def all_units(t: Texts) -> list[tuple[str, str, str, str]]:
    return units("spec", t.spec) + units("hand", t.hand)


def read_pins() -> dict[tuple[str, str, str], str]:
    path = ROOT / PIN_REL
    if not path.exists():
        return {}
    pins: dict[tuple[str, str, str], str] = {}
    for line in path.read_text(encoding="utf-8").split("\n"):
        if not line or line.startswith("#"):
            continue
        doc, reg, loc, text = line.split("\t", 3)
        pins[(doc, reg, loc)] = text
    return pins


def g_pins(t: Texts) -> list[Finding]:
    pins = read_pins()
    if not pins:
        return [("G-RULED-PIN", "no pins file; run --repin-ruled", "", "")]
    have = {(d, r, loc): x for d, r, loc, x in all_units(t)}
    out: list[Finding] = []
    for key in sorted(set(pins) | set(have)):
        if key not in have:
            out.append(("G-RULED-PIN", f"unit removed: {key[2]}", key[0], key[1]))
        elif key not in pins:
            out.append(("G-RULED-PIN", f"unit added: {key[2]}", key[0], key[1]))
        elif pins[key] != have[key]:
            out.append(("G-RULED-PIN", f"unit changed: {key[2]}", key[0], key[1]))
    return out


def repin(t: Texts) -> int:
    if PLACEHOLDER_RE.search(t.spec + t.hand) or "{{MUTATIONS" in t.spec:
        print("FAIL --repin-ruled refuses while a placeholder is unfilled")
        return 1
    rows = all_units(t)
    head = (
        "# E47-D13 pins (every unit of the spec and the hand-off): doc, region (heading path"
        f" #occurrence), location, exact normalised text; {len(rows)} units.\n"
        "# Written by `--repin-ruled` only; `--check` reads it (never hand-edit; G-RULED-PIN).\n"
    )
    old = read_pins()
    new = {(d, r, loc): x for d, r, loc, x in rows}
    for key in sorted(set(old) | set(new)):
        if old.get(key) != new.get(key):
            print(f"REPIN {key[0]} {key[2]} in {key[1][:60]}".encode("ascii", "replace").decode())
    (ROOT / PIN_REL).write_text(
        head + "".join(f"{d}\t{r}\t{loc}\t{x}\n" for d, r, loc, x in rows),
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {PIN_REL}: {len(rows)} units")
    return 0


def _m(mid: str, what: str, gate: str, doc: str, where: str, old: str, new: str) -> Mutation:
    return Mutation(mid, what, gate, doc, where, old, new)


PEND = "pending: drawn in a later push of this PR"
MUTATIONS = (
    _m("M-1", "blank board 01's status in §0", "G-BOARDS", "spec", "## 0.", PEND, "drawn"),
    _m(
        "M-2",
        "draw an eleventh board in §0",
        "G-BOARDS",
        "spec",
        "## 0.",
        "| 10 | `E47-D13 / 10",
        f"| 11 | `E47-D13 / 11 extra` | more | dark | {PEND} |\n| 10 | `E47-D13 / 10",
    ),
    _m(
        "M-3",
        "unmark BQ-4's ruling",
        "G-PENDING",
        "spec",
        "## The questions",
        "lowers, never raises — RULED as proposed (comment 6566807313)",
        "lowers, never raises — default built; ruling pending",
    ),
    _m(
        "M-4",
        "drop 2.4.5 from K-MANUAL in §4.1",
        "G-CONTRACT",
        "spec",
        "### 4.1",
        "2.4.5 2.4.6",
        "2.4.6",
    ),
    _m(
        "M-5",
        "claim Supports for 2.4.2 in the report",
        "G-CLAIM",
        "report",
        "",
        "Page Titled | A | Partially Supports",
        "Page Titled | A | Supports",
    ),
    _m(
        "M-6",
        "add an override that raises 2.4.2",
        "G-CLAIM",
        "limits",
        "",
        '"overrides": []',
        '"overrides": [{ "sc": "2.4.2", "to": "Supports", "reason": "reviewer confident" }]',
    ),
    _m(
        "M-7",
        "mark 1.4.2 Not Applicable in the report",
        "G-NA",
        "report",
        "",
        "Audio Control | A | Does Not Support",
        "Audio Control | A | Not Applicable",
    ),
    _m(
        "M-8",
        "blank 2.1.2's alternative in the report",
        "G-ALT",
        "report",
        "",
        "6 fail) | keyboard equivalents (SCR-013) |",
        "6 fail) | |",
    ),
    _m(
        "M-9",
        "drop 'four' from 1.1.1's canvas remark",
        "G-CANVAS",
        "report",
        "",
        "canvas: met only through the four layers",
        "canvas: met only through the layers",
    ),
    _m(
        "M-10",
        "renumber the 3.2.4 row",
        "G-ROWS",
        "report",
        "",
        "3.2.4 Consistent Identification",
        "3.2.5 Consistent Identification",
    ),
    _m(
        "M-11",
        "re-word 2.4.4's name",
        "G-REPORT",
        "report",
        "",
        "2.4.4 Link Purpose (In Context)",
        "2.4.4 Link Purpose",
    ),
    _m(
        "M-12",
        "accept a Level A risk for A11Y-F-0024",
        "G-LIMIT",
        "limits",
        "",
        '{ "kind": "fix-ticket", "ticket": "E17-D02 #325" }',
        '{ "kind": "accepted-risk", "owner": "owner", "decision": "y", "expiry": "2027-03-01" }',
    ),
    _m(
        "M-13",
        "drop A11Y-F-0013 from its row",
        "G-LIMIT",
        "limits",
        "",
        '"covers": ["A11Y-F-0013"]',
        '"covers": []',
    ),
    _m(
        "M-14",
        "put a criterion number in A11Y-F-0029's text",
        "G-PLAIN",
        "limits",
        "",
        "Some settings pages can only",
        "Under 2.4.5 some settings pages can only",
    ),
    _m(
        "M-15",
        "put a host in A11Y-F-0015's workaround",
        "G-DISCLOSE",
        "limits",
        "",
        "in the status bar at the bottom of the window.",
        "at status.example.com today.",
    ),
    _m(
        "M-16",
        "drop the cadence from `05` §8.3",
        "G-NORM",
        "norm",
        "",
        "for every release and for any change touching an in-scope screen",
        "for some releases",
    ),
    _m(
        "M-17",
        "drop the polite announcement from §7.8",
        "G-T2",
        "spec",
        "### 7.8",
        "re-shows the reason with one polite announcement",
        "re-shows the reason",
    ),
    _m(
        "M-18",
        "drop CMP-019 from the hand-off's components",
        "G-T2",
        "hand",
        "",
        "with the **CMP-019 Icon** `lock` glyph",
        "with a `lock` glyph",
    ),
    _m(
        "M-19",
        "drop 320 CSS px from §7.5",
        "G-RECUR",
        "spec",
        "### 7.5",
        "at 320 CSS px (400 %)",
        "at 400 %",
    ),
    _m(
        "M-20",
        "set P3's foreground to the disabled text",
        "G-CONTRAST",
        "spec",
        "### 7.6",
        "| `color.text.link`",
        "| `color.text.disabled`",
    ),
    _m(
        "M-21",
        "drop `(heuristic)` from H-3",
        "G-HEUR",
        "spec",
        "## 12.",
        "| (heuristic) Visibility of system status",
        "| Visibility of system status",
    ),
    _m(
        "M-22",
        "add an eleventh walkthrough item",
        "G-WALK",
        "hand",
        "## §E",
        "- [ ] Record `approved` on #1311",
        "- [ ] One more.\n- [ ] Record `approved` on #1311",
    ),
    _m(
        "M-23",
        "name an agent as D13-G5's owner",
        "G-OWNER",
        "spec",
        "### 14.2",
        "| E47-D12 (#1369)",
        "| the worker",
    ),
    _m(
        "M-24",
        "change E47-D04's pinned head",
        "G-INFLIGHT",
        "spec",
        "",
        "head `1ff5d8cb9`",
        "head `1ff5d8cb0`",
    ),
    _m(
        "M-25",
        "name E47-D03's unmerged file",
        "G-UNMERGED",
        "spec",
        "",
        "the palettes the statement renders in",
        "the palettes of E47-D03.md",
    ),
    _m(
        "M-26",
        "write a host beside the Penpot file",
        "G-URL",
        "spec",
        "## 0.",
        "the per-set file `E47-D13 boards`",
        "the per-set file `E47-D13 boards` at penpot.example.com",
    ),
    _m(
        "M-27",
        "touch `22` in the working tree",
        "G-UNTOUCHED",
        "changed",
        "",
        "",
        "docs/plan/22-api-openapi.yaml",
    ),
    _m("M-28", "pad the spec past its line budget", "G-BUDGET", "spec", "<eof>", "", "\n" * 600),
    _m(
        "M-29",
        "replace a mutation row's gate in §13",
        "G-MUTLIST",
        "spec",
        "## 13.",
        "| G-BOARDS |",
        "| G-ROWS |",
    ),
    _m(
        "M-30",
        "change the Partially count in §10",
        "G-ANCHOR",
        "spec",
        "## 10.",
        "27<!--=COUNT:report.partial-->",
        "26<!--=COUNT:report.partial-->",
    ),
    _m(
        "M-31",
        "leave a placeholder in §10",
        "G-MARKER",
        "spec",
        "## 10.",
        "This is the honest start",
        "This is {{COUNT:report.rows}} the honest start",
    ),
    _m(
        "M-32",
        "point a §1.3 cite past the end of S07",
        "G-CITE",
        "spec",
        "### 1.3",
        "ASS:150; S07:31–32",
        "ASS:150; S07:9998–9999",
    ),
    _m(
        "M-33",
        "re-word W-1",
        "G-QUOTE",
        "spec",
        "## 11.",
        '"Accessibility statement"',
        '"Accessibility page"',
    ),
    _m(
        "M-34",
        "re-word D13-A2's Old fragment",
        "G-AROW",
        "hand",
        "## §C",
        "| and a link to the a11y statement.",
        "| and a link to the a11y page.",
    ),
    _m(
        "M-35",
        "re-word §1.2's first sentence",
        "G-RULED-PIN",
        "spec",
        "### 1.2",
        "Desk work at the base",
        "Desk work at base",
    ),
    _m(
        "M-36",
        "unmark BQ-15's ruling",
        "G-PENDING",
        "spec",
        "## The questions",
        "— RULED as built, default taken (comment 6567605210) → §13; the tool",
        "— default built; ruling pending → §13; the tool",
    ),
    _m(
        "M-37",
        "name a malformed closed fix ticket on A11Y-F-0029",
        "G-LIMIT",
        "limits",
        "",
        '"closedTicket": "E05-S03 #266"',
        '"closedTicket": "#266"',
    ),
)


# ---------------------------------------------------------------------------- run


def findings(t: Texts, values: Values) -> list[Finding]:
    out: list[Finding] = []
    out += g_anchor(t, values) + g_marker(t) + g_cite(t) + g_quote(t) + g_arow(t)
    out += g_pending(t) + g_boards(t) + g_report(t) + g_rows(t) + g_contract(t) + g_claim(t)
    out += g_na(t) + g_alt(t) + g_canvas(t) + g_limit(t) + g_plain(t) + g_disclose(t)
    out += (
        g_contrast(t)
        + g_norm(t)
        + g_t2(t)
        + g_recur(t)
        + g_heur(t)
        + g_walk(t)
        + g_owner(t)
        + g_inflight(t)
    )
    out += g_lines(t, "G-UNMERGED", lambda ln: any(p in ln for p in UNMERGED_PATHS), "a path")
    out += g_lines(t, "G-URL", lambda ln: bool(URL_RE.search(ln)), "a URL, host or local path")
    out += g_untouched(t) + g_budget(t) + g_mutlist(t) + g_pins(t)
    return out


def related(a: str, b: str) -> bool:
    if not a or not b:
        return a == b
    a0, b0 = a.rsplit("#", 1)[0], b.rsplit("#", 1)[0]
    return a0 == b0 or a0.startswith(b0 + " > ") or b0.startswith(a0 + " > ")


def report(fs: list[Finding], quiet: bool = False) -> list[str]:
    """One FAIL line per gate; a secondary finding where another gate FAILs becomes NOTE."""
    primary = [(d, r) for g, _, d, r in fs if g not in SECONDARY]
    lines: list[str] = []
    gates: dict[str, list[Finding]] = {}
    for f in fs:
        if f[0] in SECONDARY and any(
            (d == f[2] and related(r, f[3])) or (f[0] == "G-REPORT" and d in ("report", "limits"))
            for d, r in primary
        ):
            if not quiet:
                lines.append(f"NOTE {f[0]} {f[1]} ({f[2]}; another gate FAILs here)")
            continue
        gates.setdefault(f[0], []).append(f)
    for gate, items in gates.items():
        lines.append(
            f"FAIL {gate}: {len(items)} finding(s); first: {items[0][1]} [{items[0][3][:70]}]"
        )
    return [ln.encode("ascii", "replace").decode() for ln in lines]


def read_texts() -> Texts:
    def rd(rel: str) -> str:
        p = ROOT / rel
        return p.read_text(encoding="utf-8") if p.exists() else ""

    return Texts(
        spec=rd(SPEC_REL),
        hand=rd(HAND_REL),
        norm=rd(NORM_REL),
        report=render_report(rd(LIMITS_REL)) if rd(LIMITS_REL) else "",
        limits=rd(LIMITS_REL),
        changed=changed_paths(),
    )


def fill(t: Texts) -> Texts:
    t = replace(t, spec=t.spec.replace("{{MUTATIONS}}", mutation_rows()))
    t = replace(t, report=render_report(t.limits))
    values = compute_values(t)

    def placeholder(m: re.Match[str]) -> str:
        key = f"{m.group(1)}:{m.group(2)}"
        return f"{values[key]}<!--={key}-->"

    def anchor(m: re.Match[str]) -> str:
        key = f"{m.group(2)}:{m.group(3)}"
        return f"{values.get(key, m.group(1))}<!--={key}-->"

    def sub(text: str) -> str:
        return ANCHOR_RE.sub(anchor, PLACEHOLDER_RE.sub(placeholder, text))

    t = replace(t, spec=sub(t.spec), hand=sub(t.hand))
    (ROOT / SPEC_REL).write_text(t.spec, encoding="utf-8", newline="\n")
    (ROOT / HAND_REL).write_text(t.hand, encoding="utf-8", newline="\n")
    return t


def check(do_fill: bool) -> int:
    t = read_texts()
    if do_fill:
        t = fill(t)
    lines = report(findings(t, compute_values(t)))
    for ln in lines:
        print(ln)
    fails = sum(1 for ln in lines if ln.startswith("FAIL"))
    print(f"{fails} FAIL")
    return 1 if fails else 0


def as_json() -> int:
    t = read_texts()
    rows = model(t.limits)
    out = {
        "base": BASE,
        "values": compute_values(t),
        "status": status_words(rows),
        "sample": [
            {"sc": sc, "conformance": r.conformance, "evidence": r.evidence}
            for sc in sample(t.limits)
            for r in rows
            if r.sc == sc
        ],
        "unowned": unowned(t.limits),
    }
    print(json.dumps(out, indent=2, ensure_ascii=True))
    return 0


def self_test() -> int:
    t = read_texts()

    def digest(x: Texts) -> str:
        return hashlib.sha256((x.spec + x.hand + x.norm + x.report + x.limits).encode()).hexdigest()

    before = digest(t)
    values = compute_values(t)
    base = [ln for ln in report(findings(t, values), quiet=True) if ln.startswith("FAIL")]
    if base:
        print("FAIL self-test: the baseline is not clean:", *base, sep="\n  ")
        return 1
    bad = 0
    for m in MUTATIONS:
        mt = apply_mutation(t, m)
        got = [ln for ln in report(findings(mt, values), quiet=True) if ln.startswith("FAIL")]
        ok = len(got) == 1 and got[0].startswith(f"FAIL {m.gate}:")
        print(
            f"{'ok  ' if ok else 'BAD '} {m.mid} {m.gate} <- {m.what}".encode(
                "ascii", "replace"
            ).decode()
        )
        if not ok:
            bad += 1
            for g in got:
                print(f"       {g}")
    if digest(read_texts()) != before:
        print("FAIL self-test: the texts on disk changed")
        return 1
    print(f"self-test: {len(MUTATIONS) - bad} of {len(MUTATIONS)} ok")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--json", action="store_true")
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--repin-ruled", action="store_true")
    ap.add_argument("--fill", action="store_true", help="with --check: write values first")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.json:
        return as_json()
    if args.repin_ruled:
        return repin(read_texts())
    return check(args.fill)


if __name__ == "__main__":
    sys.exit(main())
