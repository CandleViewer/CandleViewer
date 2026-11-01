"""E01-D02 (#139) audit: the design QA and accessibility review of the built contributor surfaces.

Stdlib only, offline (`python3 -I -B`). It reads the spec, the pins file and the tool itself from the
working tree, and every cited or lifted file AS TEXT at the merge-base with `origin/main` (`git
show`): the issue forms, the chooser file, the pull-request template, the guard code, the contributor
spec E01-D01, the governance documents and the sprint calendar. It runs no repo code, drives no
browser and makes no network call: the label, team and issue records it needs are written into the
pins file by `--repin-ruled` (the only mode that calls `gh`) and read back from there.
Default-deny: a gate that cannot read its input FAILs.

Two modes, chosen by content, never by flag. PR-1 mode: the spec is absent at the merge-base; the
diff may touch the three own files, E01-D01 (the reconciliation) and the issue forms, where only
description, option and placeholder text may change (RULED BQ-01, BQ-08); a `{{RENDER:key}}`
slot (a value only the rendered check can give) is a WARN. Post-merge mode: the spec ships at the
merge-base; the inputs are read at the base the spec records, every merged table row stands
unchanged, and a RENDER slot is a FAIL. Every comparison reads the forms at the base, before the
in-place fixes, so one PR carries both (RULED BQ-01).

Gates (each FAIL led by its code):

- [G01-FILLED] no `{{KIND:key}}` slot is left in the spec (RENDER: WARN in PR-1 mode).
- [G02-AUDIT] every `<!-- audit:key=value -->` marker is a known key, equals the recomputed value
  and stands right after its visible value.
- [G03-CITE] every cited endpoint resolves at the base to a non-blank line and its pin matches.
- [G04-PINS] the pins file and the spec's cited endpoints match both ways.
- [G05-VERBATIM] every quoted string in a table row stands whole on a line the row cites.
- [G06-SPEC] the comparison tables are exactly the rows computed from the forms and E01-D01: the
  row set, the built line of each label, the label wording, the required flags, the options and
  the status class of every row.
- [G07-LABEL] every label any of the eight forms applies has a record; an absent one is named by a
  register row citing its labels line; a label the ruling records as fixed at source is recorded
  present and keeps its row; post-merge, the records are not older than the base.
- [G08-OPTION] a dropdown with a bare option names a drift row, a register row for exactly its
  options span, and nothing else does; in PR-1 mode a row fixed here has no bare option left in the
  working tree.
- [G09-FINDINGS] every DF row has a class, severity, clause, owner, target and method from the ruled
  sets and a cited sentence; a WCAG clause on a content defect is Major or Blocking; every PT row
  and every section 3.7 row that is not a match names a register row of the same class and
  severity, and a PT row's class, severity and clause cells are from the ruled sets.
- [G10-PLATFORM] the platform note: tags from the ruled set; a platform row names a criterion and
  "platform limitation, accepted" and never a defect id.
- [G11-GUARD] the guard-comment rows equal the flags computed from the guard code at the base.
- [G12-MD] the governance-document rows are the five documents in order, their counts computed
  fence-aware, and a register row exists for a diagram without adjacent prose exactly when one is.
- [G13-ROUTE] owners come from the ruled set; a ticket named as an owner or a consumer is read from
  the issue record, and a closed one is called closed.
- [G14-HYGIENE] no lane-private word, URL, local path, uuid or closing keyword in the own files.
- [G15-SECRET] no secret-shaped value in the own files.
- [G16-SCOPE] PR-1 mode: the changed paths are the own files, E01-D01 and the six D01 forms; a
  changed form keeps its name, title, labels, element types, ids, field labels, required flags,
  markdown blocks and option counts, so only description, option and placeholder text moved.
- [G17-IDS] the ids of each table family are 1..n in order.
- [G18-RULED] section R lists BQ-01..BQ-22 once each with the ruling stamp; every "RULED BQ-nn"
  names a listed question, each question is stamped in the text, and no unruled marker is left.
- [G19-WALK] the owner checklist holds at most ten items.
- [G20-FREEZE] post-merge mode: every merged table row stands unchanged.
- [G21-SECURITY] a security-bearing row (SC) carries no quoted string and no built-file cite.
- [G22-ANCHOR] a script, security, template, chooser and guard row cites exactly the lines it is
  anchored to: the element, option span, heading or flag line computed from the base.
- [G23-LATER] the later-change table lists, from the log at the base, each commit after the T05
  merge that touched a form, the chooser file or the template.
- [G24-STATUS] the status of every section 3.7 row is a ruled word, and a waiver row carries the
  status its evidence supports.

`--json` prints the numbers, findings and RENDER slots; `--check` exits 1 on any FAIL; `--fill`
writes the computed values into the spec's slots and markers; `--self-test` applies one mutation
per gate to an in-memory copy and passes only when each adds a FAIL of its gate's code and the base
run is clean; `--repin-ruled` rewrites the pins file from the spec's cites and the `gh` records
and is its only writer.

Usage: python3 -I -B docs/design/_tools/e01_d02_designqa_audit.py [--check] [--json] [--fill]
       [--self-test] [--repin-ruled]
"""

from __future__ import annotations

import argparse
import codecs
import dataclasses
import datetime
import functools
import hashlib
import json
import re
import subprocess
import sys
import urllib.parse
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SPEC_REL = "docs/design/E01/E01-D02.md"
TOOL_REL = "docs/design/_tools/e01_d02_designqa_audit.py"
PINS_REL = "docs/design/_tools/e01_d02_ruled_pins.txt"
D01_REL = "docs/design/E01/E01-D01.md"
# The rendered-surface screenshots embedded in the PR body (RULED BQ-01: no boards).
IMG_RELS = {
    f"docs/design/E01/img/E01-D02-{n}.png"
    for n in ("01-signin-wall", "02-pr-template-rendered", "03-story-form-preview")
}
OWN = {SPEC_REL, TOOL_REL, PINS_REL, *IMG_RELS}
UPSTREAM = "origin/main"
REPO = "CandleViewer/CandleViewer"
FORMS_DIR = ".github/ISSUE_TEMPLATE/"
GOV_DOCS = ("CONSTITUTION.md", "CONTRIBUTING.md", "SECURITY.md", "AGENTS.md", "CODE_OF_CONDUCT.md")
GOV_KEYS = ("const", "contrib", "sec", "agents", "coc")
MERGES = {"d01": "1423", "t05": "1429", "t07": "1436"}  # E01-D01, E01-T05, E01-T07 pull requests
ISSUES = {
    "76": "E01-D01",
    "83": "E01-T05",
    "85": "E01-T07",
    "78": "E01-Q01",
    "140": "E01-Q02",
    "139": "E01-D02",
}

FORM_FILES = {
    "epic": "epic.yml",
    "story": "story.yml",
    "task": "task.yml",
    "spike": "spike.yml",
    "bug": "bug_report.yml",
    "chore": "chore.yml",
}
D01_FORMS = tuple(FORM_FILES)
EXTRA_FORMS = {"quarterly": "quarterly-ci-review.yml", "release": "release-checklist.yml"}
KEYS: dict[str, str] = {
    **{k: FORMS_DIR + v for k, v in {**FORM_FILES, **EXTRA_FORMS}.items()},
    "CHOOSER": FORMS_DIR + "config.yml",
    "PRT": ".github/PULL_REQUEST_TEMPLATE.md",
    "GH": "scripts/gh/gh_adapter.py",
    "RG": "scripts/gh/run_guard.py",
    "GQ": "scripts/gh/guard_qa_signoff.py",
    "GS": "scripts/gh/guard_security.py",
    "GA": "scripts/gh/guard_a11y.py",
    "IB": "scripts/gh/issue_body.py",
    "CAL": "docs/plan/backlog/_tools/calendar_cv.py",
    "D01": D01_REL,
    "CPM": "tools/ci/check_pr_metadata.py",
    "OWN": ".github/CODEOWNERS",
}
KEY_RE = "|".join(sorted(KEYS, key=len, reverse=True)) + r"|\d\d"
MD_CITE = re.compile(
    rf"`(?P<key>{KEY_RE})`:(?P<a>\d+)(?:[–-](?P<b>\d+))?(?P<more>(?:, :\d+(?:[–-]\d+)?)*)"
)
MORE = re.compile(r":(\d+)(?:[–-](\d+))?")
SLOT = re.compile(r"\{\{([A-Z]+):([\w.-]+)\}\}")
AUDIT = re.compile(r"<!-- audit:([\w.-]+)=([^>]*?) -->")
QUOTE = re.compile(r'"([^"]*)"')
BQ_MARK = re.compile(r"<!-- BQ-(\d\d) -->")
RULED_STAMP = "RULED (orchestrator, 2026-11-01, #139 ruling of record 6551875204)"
RULED_REF = re.compile(r"RULED (BQ-\d\d)((?:, BQ-\d\d)*)")
# A label the ruling records as created at source (BQ-08): name -> the creation date.
FIXED_AT_SOURCE = {"type/story": "2026-11-01"}

# Ruled sets (the BQ list's options as ruled, #139 ruling of record 6551875204).
CLASSES = ("content defect", "spec update", "drift", "known")
SEVERITIES = ("Blocking", "Major", "Minor", "Info")
METHODS = ("desk", "rendered-tree", "owner-run", "desk (tool)")
OBSERVED = ("desk", "rendered-tree", "owner-run", "desk (tool)", "platform")
TAGS = ("ours", "shared", "platform")
OWNERS = (
    "this ticket (fixed here)",
    "this ticket (D01, fixed here)",
    "this ticket",
    "the owner",
    "the `scripts/gh` lane",
    "the lane that owns them",
    "the amendment path (C-16)",
    "the orchestrator",
    "n/a",
)
FM_CLASSES = ("drift", "spec-update", "defect", "fixed-at-source", "out-of-spec-owner")
SR_OBSERVED = ("desk", "rendered-tree", "owner-run")
CLAUSE_PART = re.compile(
    r"`[1-4]\.\d{1,2}\.\d{1,2}`|D01 §\d+|T (?:AC\d|Sec(?: \([a-z]\))?|Obs|Scope|Tech|a11y|DoD)"
)
RULE_ID = re.compile(r"^\W*C-\d+(?:\.\d+)?\b")
EXTRA_FM = {"quarterly": "FM-13", "release": "FM-14"}
FM_DF_CLASS = {"drift": "drift", "spec-update": "spec update", "defect": "content defect"}
WV_STATUS = {
    "WV-1": "merge order:",
    "WV-2": "`not-evidenced`",
    "WV-3": "gap",
    "WV-4": "done",
}
WCAG = re.compile(r"\b[1-4]\.\d{1,2}\.(?:\d{1,2}|x)\b")
# rot13 keeps the private list out of plain text; underscores stand for spaces.
BANNED_ROT13 = (
    "yrnx rkcbfrq olcnff rkcybvg nggnpx benpyr erirny haobhaqrq sybbq fgnyy qbf nqivfbel tufn "
    "cer-nhgu ucr-jbexre znva-bepurfgengbe"
)
BANNED = [w.replace("_", " ") for w in codecs.decode(BANNED_ROT13, "rot13").split()]
URL = re.compile(r"https?://|\bwww\.", re.IGNORECASE)
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
LOCAL_PATH = re.compile("|".join("/" + w + "/" for w in ("home", "mnt", "tmp")))
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?) #\d+", re.IGNORECASE)
SECRET = re.compile(r"\b[A-Z2-7]{16,}\b|(?<![\w.-])\d{6}(?![\w.-])|otpauth:")

Findings = list[tuple[str, str]]
RUN_ERRORS = (KeyError, ValueError, IndexError, TypeError, AttributeError, OSError, RuntimeError)


# --------------------------------------------------------------------------------------- git


def git(*args: str) -> str:
    out = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )
    return out.stdout if out.returncode == 0 else ""


@functools.cache
def merge_base() -> str:
    return git("merge-base", "HEAD", UPSTREAM).strip()


@functools.cache
def show(rev: str, rel: str) -> str | None:
    out = subprocess.run(
        ["git", "show", f"{rev}:{rel}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )
    return out.stdout if out.returncode == 0 else None


@functools.cache
def plan_path(nn: str, rev: str) -> str | None:
    for name in git("ls-tree", "--name-only", rev, "docs/plan/").split():
        if Path(name).name.startswith(f"{nn}-") and name.endswith((".md", ".yaml")):
            return name
    return None


def key_path(key: str, rev: str) -> str | None:
    if key in KEYS:
        return KEYS[key]
    return plan_path(key, rev) if re.fullmatch(r"\d\d", key) else None


def read(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


@functools.cache
def commit_of(pr: str) -> tuple[str, str]:
    """The squash commit of pull request `pr` on the upstream: (full sha, committer date, UTC)."""
    out = git("log", UPSTREAM, f"--grep=(#{pr})$", "--format=%H %cI", "-1").split()
    if len(out) != 2:
        raise ValueError(f"no commit for (#{pr}) on {UPSTREAM}")
    when = datetime.datetime.fromisoformat(out[1]).astimezone(datetime.UTC)
    return out[0], when.strftime("%Y-%m-%dT%H:%MZ")


# ----------------------------------------------------------------------------------- parsing


def heading_level(line: str) -> int:
    m = re.match(r"(#{1,6}) ", line)
    return len(m[1]) if m else 0


def section(text: str, prefix: str) -> str:
    lines = text.split("\n")
    for i, line in enumerate(lines):
        lvl = heading_level(line)
        if lvl and line[lvl + 1 :].startswith(prefix):
            out = []
            for nxt in lines[i + 1 :]:
                n = heading_level(nxt)
                if n and n <= lvl:
                    break
                out.append(nxt)
            return "\n".join(out)
    return ""


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def rows(block: str, family: str) -> list[list[str]]:
    pat = re.compile(rf"^\|\s*{re.escape(family)}-\d+\s*\|")
    return [cells(ln) for ln in block.split("\n") if pat.match(ln)]


def table_rows(block: str) -> list[list[str]]:
    """Data rows of the first table in `block`: no header, no separator."""
    out: list[list[str]] = []
    seen_sep = False
    for ln in block.split("\n"):
        if not ln.startswith("|"):
            if seen_sep:
                break
            continue
        if re.match(r"^\|\s*:?-{3,}", ln):
            seen_sep = True
            continue
        if seen_sep:
            out.append(cells(ln))
    return out


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("`", "").replace("*", "")).strip()


def squash(s: str) -> str:
    return re.sub(r"[\s\-/]+", "", norm(s)).lower()


def line_hash(s: str) -> str:
    return hashlib.sha1(norm(s).encode("utf-8")).hexdigest()[:16]


def cite_spans(text: str) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []
    for m in MD_CITE.finditer(text):
        a = int(m["a"])
        out.append((m["key"], a, int(m["b"]) if m["b"] else a))
        for mm in MORE.finditer(m["more"] or ""):
            x = int(mm[1])
            out.append((m["key"], x, int(mm[2]) if mm[2] else x))
    return out


def endpoints(spec: str) -> set[tuple[str, int]]:
    out: set[tuple[str, int]] = set()
    for key, a, b in cite_spans(spec):
        out.add((key, a))
        out.add((key, b))
    return out


def parse_pins(pins: str) -> dict[tuple[str, int], str]:
    out: dict[tuple[str, int], str] = {}
    for ln in pins.split("\n"):
        m = re.fullmatch(rf"({KEY_RE}):(\d+) ([0-9a-f]{{16}})", ln.strip())
        if m:
            out[(m[1], int(m[2]))] = m[3]
    return out


def parse_records(pins: str) -> dict[str, str]:
    """`REC label|team|issue|date <name> <state...>` lines of the pins file: name -> state."""
    out: dict[str, str] = {}
    for ln in pins.split("\n"):
        m = re.fullmatch(r"REC (label|team|issue|date) (\S+)(?: (.+))?", ln.strip())
        if m:
            out[f"{m[1]} {m[2]}"] = m[3] or ""
    return out


def ids_in(text: str, fam: str) -> list[int]:
    """`DF-3` and `SR-4..SR-11` style mentions, ranges expanded."""
    out: list[int] = []
    for m in re.finditer(rf"\b{fam}-(\d+)(?:\.\.{fam}-(\d+))?\b", text):
        a = int(m[1])
        out.extend(range(a, int(m[2]) + 1) if m[2] else [a])
    return out


def strip_markers(s: str) -> str:
    return re.sub(r"\s*<!-- (?:audit:[^>]*?|BQ-\d\d) -->", "", s).strip()


# ------------------------------------------------------------------- the forms' YAML subset


@dataclasses.dataclass
class Opt:
    text: str
    line: int
    required: bool | None = None


@dataclasses.dataclass
class Elem:
    type: str
    start: int
    end: int
    id: str = ""
    label: str = ""
    label_line: int = 0
    desc: str = ""
    desc_line: int = 0
    value: str = ""
    options_line: int = 0
    options: list[Opt] = dataclasses.field(default_factory=list)
    required: bool | None = None
    required_line: int = 0
    render: str = ""
    placeholder: str = ""


@dataclasses.dataclass
class Form:
    name: str = ""
    name_line: int = 0
    title: str = ""
    title_line: int = 0
    labels: list[str] = dataclasses.field(default_factory=list)
    labels_line: int = 0
    elems: list[Elem] = dataclasses.field(default_factory=list)

    @property
    def controls(self) -> list[Elem]:
        return [e for e in self.elems if e.type != "markdown"]

    def by_id(self, ident: str) -> Elem:
        for e in self.elems:
            if e.id == ident:
                return e
        raise KeyError(ident)


def unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] == '"':
        return s[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if len(s) >= 2 and s[0] == s[-1] == "'":
        return s[1:-1]
    return s


def inline_list(s: str) -> list[str]:
    inner = s.strip()[1:-1]
    return [unquote(p) for p in re.split(r",\s*", inner) if p.strip()]


def scalar(lines: list[str], i: int, indent: int, rest: str) -> tuple[str, int]:
    """The value of a key whose text after the colon is `rest`; returns (value, next line index)."""
    if rest in (">-", ">", "|", "|-"):
        body: list[str] = []
        j = i + 1
        while j < len(lines) and (
            not lines[j].strip() or len(lines[j]) - len(lines[j].lstrip()) > indent
        ):
            body.append(lines[j].strip() if rest.startswith(">") else lines[j][indent + 2 :])
            j += 1
        while body and not body[-1].strip():
            body.pop()
        return (" ".join(body) if rest.startswith(">") else "\n".join(body)), j
    return unquote(rest), i + 1


def parse_form(text: str) -> Form:
    lines = text.split("\n")
    form = Form()
    top = re.compile(r"^(name|title|labels|body):\s*(.*)$")
    start_of_body = 0
    for i, ln in enumerate(lines):
        m = top.match(ln)
        if not m:
            continue
        if m[1] == "name":
            form.name, form.name_line = unquote(m[2]), i + 1
        elif m[1] == "title":
            form.title, form.title_line = unquote(m[2]), i + 1
        elif m[1] == "labels":
            form.labels, form.labels_line = inline_list(m[2]), i + 1
        else:
            start_of_body = i + 1
    starts = [
        i for i in range(start_of_body, len(lines)) if re.match(r"^  - type: \w+\s*$", lines[i])
    ]
    for n, s in enumerate(starts):
        stop = starts[n + 1] if n + 1 < len(starts) else len(lines)
        while stop > s + 1 and not lines[stop - 1].strip():
            stop -= 1
        form.elems.append(parse_elem(lines, s, stop))
    return form


def parse_elem(lines: list[str], s: int, stop: int) -> Elem:
    el = Elem(type=lines[s].split(":", 1)[1].strip(), start=s + 1, end=stop)
    i = s + 1
    while i < stop:
        ln = lines[i]
        m = re.match(
            r"^( *)(id|label|description|value|render|required|options|placeholder):\s*(.*)$", ln
        )
        if not m:
            i += 1
            continue
        indent, key, rest = len(m[1]), m[2], m[3]
        if key == "options":
            el.options_line = i + 1
            if rest.startswith("["):
                el.options = [Opt(t, i + 1) for t in inline_list(rest)]
                i += 1
                continue
            if not rest and i + 1 < stop and lines[i + 1].strip().startswith("["):
                j = i + 1  # a flow list over several lines (the formatter's layout)
                while j < stop and "]" not in lines[j]:
                    j += 1
                flow = " ".join(x.strip() for x in lines[i + 1 : j + 1])
                el.options = [Opt(t, i + 2) for t in inline_list(flow)]
                i = j + 1
                continue
            i += 1
            while i < stop and re.match(r"^\s+- ", lines[i]):
                item = re.match(r"^(\s+)- (label: )?(.*)$", lines[i])
                if item is None:
                    break
                if item[2]:
                    opt = Opt("", i + 1, False)
                    text, j = scalar(lines, i, len(item[1]) + 2, item[3])
                    opt.text = text
                    while j < stop and not re.match(r"^\s+- ", lines[j]):
                        rq = re.match(r"^\s+required:\s*(true|false)", lines[j])
                        if rq:
                            opt.required = rq[1] == "true"
                        j += 1
                    el.options.append(opt)
                    i = j
                else:
                    el.options.append(Opt(unquote(item[3]), i + 1))
                    i += 1
            continue
        val, nxt = scalar(lines, i, indent, rest)
        if key == "id":
            el.id = val
        elif key == "label" and not el.label:
            el.label, el.label_line = val, i + 1
        elif key == "description":
            el.desc, el.desc_line = val, i + 1
        elif key == "value":
            el.value = val
        elif key == "render":
            el.render = val
        elif key == "placeholder":
            el.placeholder = val
        elif key == "required":
            el.required, el.required_line = val == "true", i + 1
        i = nxt
    return el


def option_span(e: Elem) -> tuple[int, int]:
    return (e.options_line, max(o.line for o in e.options)) if e.options else (0, 0)


def is_bare(opt: str) -> bool:
    """An option that is no self-describing phrase out of context (E01-D01 section 7)."""
    return bool(
        re.fullmatch(r"\d+|XS|S|M|L|XL", opt) or (opt.startswith("priority/") and " — " not in opt)
    )


# ---------------------------------------------------------------- the spec's field tables


def d01_fields(d01: str, n: int) -> list[tuple[str, str, bool | None, str | None]]:
    """Rows of E01-D01 section 4.n: field, control cell, required flag, quoted help text."""
    out: list[tuple[str, str, bool | None, str | None]] = []
    for c in table_rows(section(d01, f"4.{n} ")):
        control = c[1]
        req: bool | None = None
        if re.search(r"\brequired\b", control):
            req = True
        elif re.search(r"\boptional\b", control):
            req = False
        q = re.search(r'"([^"]+)"', c[2])
        out.append((c[0], control, req, q[1] if q else None))
    return out


# Section 4.n row order of E01-D01 -> the built field ids, in the spec's order.
SPEC_IDS: dict[str, tuple[str, ...]] = {
    "epic": (
        "problem-value",
        "scope",
        "research-links",
        "architecture-impact",
        "touches-security-surface",
        "has-user-facing-screens",
        "sizing",
        "dependencies",
        "owner",
    ),
    "story": (
        "user-story",
        "acceptance-criteria",
        "has-ui-surface",
        "touches-sensitive-surface",
        "test-plan-outline",
        "contract-link",
        "dependencies",
        "out-of-scope",
        "estimate",
    ),
    "task": (
        "description",
        "acceptance-criteria",
        "changes-shared-contract",
        "area",
        "priority",
        "dependencies",
    ),
    "spike": (
        "questions",
        "timebox",
        "decision-criteria",
        "research-links",
        "produces-shippable-code",
    ),
    "bug": (
        "description",
        "repro",
        "expected",
        "actual",
        "priority",
        "root-cause-hypothesis",
        "regression-origin",
        "environment",
        "logs",
    ),
    "chore": ("what-and-why", "risk-level", "estimate"),
}


def label_token(spec_label: str, built: str) -> str:
    """The Label cell: `same`, `same (spacing)` or the built label in quotes."""
    a, b = norm(spec_label), norm(built)
    if a == b:
        return "same"
    return "same (spacing)" if squash(a) == squash(b) else f'"{built}"'


def options_cell(e: Elem) -> str:
    if e.type != "dropdown":
        return "n/a"
    texts = [o.text for o in e.options]
    if len(texts) <= 5 and all(len(t) <= 20 for t in texts):
        return ", ".join(texts)
    return f"{len(texts)} values"


def fm_rows(ctx: Ctx, key: str) -> list[dict[str, Any]]:
    """The computed comparison rows of one form (section 3.n): spec rows, built-only fields, labels."""
    form = ctx.forms[key]
    n = D01_FORMS.index(key) + 1
    spec = d01_fields(ctx.d01, n)
    ids = SPEC_IDS[key]
    if len(spec) != len(ids):
        raise ValueError(f"{key}: E01-D01 has {len(spec)} rows, the map {len(ids)}")
    out: list[dict[str, Any]] = []
    for (field, _control, sreq, _help), ident in zip(spec, ids, strict=True):
        e = form.by_id(ident)
        out.append(_row(key, field, e, sreq))
    mapped = set(ids)
    for e in form.controls:
        if e.id not in mapped:
            out.append(_row(key, "(not in D01)", e, None, added=True))
    absent = [x for x in form.labels if ctx.records.get(f"label {x}") == "absent"]
    fixed = [x for x in form.labels if x in FIXED_AT_SOURCE and x not in absent]
    if absent or fixed:

        def note(x: str) -> str:
            if x in absent:
                return " (absent)"
            return f" (created {FIXED_AT_SOURCE[x]})" if x in fixed else ""

        out.append(
            {
                "d01": "(the form's labels)",
                "cite": (key, form.labels_line, form.labels_line),
                "label": ", ".join(f"`{x}`{note(x)}" for x in form.labels),
                "req": "n/a / n/a",
                "options": "n/a",
                "flag": "label" if absent else "label-fixed",
                "bare_span": None,
            }
        )
    return out


def _row(key: str, field: str, e: Elem, sreq: bool | None, added: bool = False) -> dict[str, Any]:
    yn = {True: "yes", False: "no", None: "unstated"}
    breq = bool(e.required)
    flag = ""
    span = None
    if added:
        flag = "added"
    elif sreq is not None and sreq != breq:
        flag = "required"
    if e.type == "dropdown" and any(is_bare(o.text) for o in e.options):
        flag = flag or "bare"
        span = option_span(e)
    return {
        "d01": field,
        "cite": (key, e.label_line, e.label_line),
        "label": f'"{e.label}"' if added else label_token(field, e.label),
        "req": f"{'n/a' if added else yn[sreq]} / {yn[breq]}",
        "options": options_cell(e),
        "flag": flag,
        "bare_span": span,
        "id": e.id,
    }


# ----------------------------------------------------------- the governance documents (G12)

VAGUE = {"here", "link", "this", "click here", "more", "read more", "see", "url", "this link"}


def md_scan(text: str) -> dict[str, int]:
    """Fence-aware counts for one governance document: the five checks of the markdown pass."""
    lines = text.split("\n")
    fence = ""
    h1 = naive_h1 = steps = bad_tables = links = 0
    prev_level = 0
    blocks: list[tuple[int, int]] = []
    open_at = -1
    in_table = False
    table_lines = 0
    for i, ln in enumerate(lines):
        m = re.match(r"^\s*(`{3,}|~{3,})(.*)$", ln)
        if m:
            if not fence:
                fence = m[1][0] * 3
                open_at = i if m[2].strip().startswith("mermaid") else -1
            elif ln.strip().startswith(fence):
                fence = ""
                if open_at >= 0:
                    blocks.append((open_at, i))
                    open_at = -1
            continue
        if ln.startswith("# "):
            naive_h1 += 1
        if fence:
            continue
        lvl = heading_level(ln)
        if ln.startswith("# "):
            h1 += 1
        if lvl:
            if prev_level and lvl > prev_level + 1:
                steps += 1
            prev_level = lvl
        if ln.startswith("|"):
            table_lines += 1
            if not in_table:
                in_table = True
                if i + 1 >= len(lines) or not re.match(r"^\|\s*:?-{3,}", lines[i + 1]):
                    bad_tables += 1
        else:
            in_table = False
        plain = re.sub(r"`[^`]*`", "", ln)
        if re.match(r"^\[[^\]]+\]:\s", ln):
            continue
        for lm in re.finditer(r"\[([^\]]*)\]\(([^)]*)\)", plain):
            if norm(lm[1]).lower() in VAGUE or re.match(r"https?://", lm[1]):
                links += 1
        stripped = re.sub(r"\[[^\]]*\]\([^)]*\)", "", plain)
        links += len(re.findall(r"(?<![\w(<\"])https?://\S+", stripped))
    kinds = [(a, _prose_class(lines, a, b)) for a, b in blocks]
    none = [a + 1 for a, k in kinds if k == "none"]
    weak = [a + 1 for a, k in kinds if k == "weak"]
    return {
        "h1": h1,
        "naive_extra": naive_h1 - h1,
        "steps": steps,
        "tables": bad_tables,
        "links": links,
        "mermaid": len(blocks),
        "noprose": len(none),
        "noprose_line": none[0] if none else 0,
        "weak": len(weak),
        "weak_line": weak[0] if weak else 0,
    }


def _prose_line(ln: str) -> bool:
    s = ln.strip()
    return bool(
        len(s) >= 25
        and not re.match(r"^(#|\||```|~~~|<!--|---|- \[)", s)
        and not s.startswith("![")
    )


def _prose_class(lines: list[str], a: int, b: int) -> str:
    """`ok` (prose before the opening fence, or after the closing one and not another rule's),
    `weak` (only a neighbouring rule's text after it) or `none`."""
    j = a - 1
    while j >= 0 and not lines[j].strip():
        j -= 1
    k = b + 1
    while k < len(lines) and not lines[k].strip():
        k += 1
    if j >= 0 and _prose_line(lines[j]):
        return "ok"
    if k < len(lines) and _prose_line(lines[k]):
        return "weak" if RULE_ID.match(lines[k].strip()) else "ok"
    return "none"


# ------------------------------------------------------------- the pull-request template (G22)

GATE_HEADINGS = (
    "Acceptance criteria",
    "Test plan",
    "QA sign-off",
    "Security review",
    "a11y evidence",
)


def prt_facts(prt: str) -> dict[str, Any]:
    lines = prt.split("\n")
    heads: list[tuple[int, int, str]] = []
    for i, ln in enumerate(lines):
        lvl = heading_level(ln)
        if lvl:
            heads.append((i + 1, lvl, ln[lvl + 1 :].strip()))
    empty: list[int] = []
    gates: dict[str, int] = {}
    for n, (line, lvl, title) in enumerate(heads):
        if lvl == 3 and title in GATE_HEADINGS:
            gates[title] = line
        if lvl != 3:
            continue
        end = heads[n + 1][0] - 1 if n + 1 < len(heads) else len(lines)
        body = "\n".join(lines[line:end])
        visible = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL).strip()
        if not visible or visible == "---":
            empty.append(line)
    boxes = sum(1 for ln in lines if re.match(r"^\s*- \[[ x~]\]", ln))
    handles = [
        (i + 1, h)
        for i, ln in enumerate(lines)
        for h in re.findall(r"`?@(CandleViewer/[\w-]+)", ln)
    ]
    type_line = next(line for line, lvl, t in heads if lvl == 2 and t == "Type of change")
    gate_empty = [x for x in empty if any(x == v for v in gates.values())]
    return {
        "heads": heads,
        "gates": gates,
        "empty": empty,
        "gate_empty": gate_empty,
        "boxes": boxes,
        "handles": handles,
        "type_line": type_line,
        "reviews_line": next(line for line, lvl, t in heads if t.startswith("Reviews required")),
        "contract_comment": (7, 12),
    }


# ----------------------------------------------------------------------- the chooser (G22)


def chooser_facts(text: str) -> dict[str, Any]:
    lines = text.split("\n")
    out: dict[str, Any] = {"blank_line": 0, "links": []}
    for i, ln in enumerate(lines):
        if ln.startswith("blank_issues_enabled:"):
            out["blank_line"] = i + 1
            out["blank_off"] = ln.split(":", 1)[1].strip() == "false"
        m = re.match(r"^  - name: (.*)$", ln)
        if m:
            out["links"].append({"name": m[1], "start": i + 1, "end": i + 1})
        elif out["links"] and re.match(r"^    (url|about): ", ln):
            out["links"][-1]["end"] = i + 1
    return out


# ------------------------------------------------------------------- the guard code (G11)

MARKER_LITERALS = (
    "QA sign-off:",
    "Security sign-off:",
    "QA capacity deviation",
    "re-run",
    "Actions run",
)


def guard_text(ctx: Ctx, key: str, a: int, b: int) -> str:
    return "\n".join(ctx.base_line(key, n) or "" for n in range(a, b + 1))


# The literal each guard itself reads: a comment that holds it states the next step in full.
GUARD_LITERAL = {"GQ": "QA sign-off:", "GS": "Security sign-off:", "GA": "Actions run"}


def guard_flags(ctx: Ctx, spans: list[tuple[str, int, int]]) -> dict[str, str]:
    text = "\n".join(guard_text(ctx, k, a, b) for k, a, b in spans)
    emoji = re.search("[\U0001f000-\U0001faff☀-➿]", text)
    marker = any(m in text for m in MARKER_LITERALS)
    named = bool(spans) and all(GUARD_LITERAL[k] in guard_text(ctx, k, a, b) for k, a, b in spans)
    return {
        "verdict": "yes" if re.search(r"BLOCKED|ALLOWED", text) else "no",
        "emoji": "no" if emoji else "yes",
        "next": "yes" if named else "partly" if marker else "no",
        "reopen": "yes" if re.search(r"reopen", text, re.IGNORECASE) else "no",
    }


# ---------------------------------------------------------------------------- the sprints


def sprint_calendar(cal: str) -> tuple[datetime.date, int]:
    m = re.search(r"^SPRINT01_START = datetime\.date\((\d+), (\d+), (\d+)\)", cal, re.MULTILINE)
    d = re.search(r"^SPRINT_DAYS = (\d+)", cal, re.MULTILINE)
    if not m or not d:
        raise ValueError("the calendar constants are not readable")
    return datetime.date(int(m[1]), int(m[2]), int(m[3])), int(d[1])


def sprint_range(cal: tuple[datetime.date, int], n: int) -> tuple[datetime.date, datetime.date]:
    start = cal[0] + datetime.timedelta(days=(n - 1) * cal[1])
    return start, start + datetime.timedelta(days=cal[1] - 1)


def sprint_of(cal: tuple[datetime.date, int], day: datetime.date) -> int:
    return (day - cal[0]).days // cal[1] + 1


# ------------------------------------------------------------------------------ context


@dataclasses.dataclass
class Ctx:
    spec: str
    pins: str
    tool: str
    changed: list[str]
    merged_spec: str | None
    base: str
    mode: str
    d01: str
    forms: dict[str, Form]
    records: dict[str, str]
    sources: dict[str, str]
    head: dict[str, str] = dataclasses.field(default_factory=dict)

    def base_text(self, key: str) -> str | None:
        rel = key_path(key, self.base)
        if rel is None:
            return None
        if rel in self.sources:
            return self.sources[rel]
        return show(self.base, rel)

    def base_line(self, key: str, n: int) -> str | None:
        text = self.base_text(key)
        if text is None:
            return None
        lines = text.split("\n")
        return lines[n - 1] if 0 < n <= len(lines) else None


def recorded_base(spec: str, merged: bool) -> str | None:
    m = re.search(r"<!-- audit:sha=([0-9a-f]{12}) -->", spec)
    if not merged or not m:
        return None
    full = git("rev-parse", "--verify", f"{m[1]}^{{commit}}").strip()
    return full or None


def build_ctx() -> Ctx:
    head_base = merge_base()
    merged_spec = show(head_base, SPEC_REL)
    spec = read(SPEC_REL)
    base = recorded_base(spec, merged_spec is not None) or head_base
    changed = sorted(
        {
            *git("diff", "--name-only", head_base).split(),
            *git("ls-files", "-o", "--exclude-standard").split(),
        }
    )
    rels = {*KEYS.values(), *GOV_DOCS}
    sources = {r: t for r in sorted(rels) if (t := show(base, r)) is not None}
    forms = {k: parse_form(sources.get(KEYS[k], "")) for k in (*FORM_FILES, *EXTRA_FORMS)}
    return Ctx(
        spec=spec,
        pins=read(PINS_REL),
        tool=read(TOOL_REL),
        changed=changed,
        merged_spec=merged_spec,
        base=base,
        mode="post-merge" if merged_spec is not None else "PR-1",
        d01=show(base, D01_REL) or "",
        forms=forms,
        records=parse_records(read(PINS_REL)),
        sources=sources,
        head={k: read(KEYS[k]) for k in FORM_FILES},
    )


# ------------------------------------------------------------------------- spec readers


def trows(block: str) -> list[list[str]]:
    return [[strip_markers(c) for c in r] for r in table_rows(block)]


def frows(block: str, fam: str) -> list[list[str]]:
    return [[strip_markers(c) for c in r] for r in rows(block, fam)]


def sec(ctx: Ctx, prefix: str) -> str:
    return section(ctx.spec, prefix)


def help_norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", norm(s).lower())).strip()


def d01_warning(d01: str) -> str:
    m = re.search(r'\*"(Never paste.*?)"\*', "\n".join(d01.split("\n")[139:152]), re.DOTALL)
    if not m:
        raise ValueError("the persistent warning of E01-D01 section 4 is not readable")
    return norm(m[1])


def first_para(value: str) -> str:
    return norm(re.split(r"\n\s*\n", value.strip())[0])


def label_names(ctx: Ctx) -> list[str]:
    seen: dict[str, None] = {}
    for f in ctx.forms.values():
        for x in f.labels:
            seen[x] = None
    return list(seen)


def team_handles(ctx: Ctx) -> list[str]:
    prt = prt_facts(ctx.sources[KEYS["PRT"]])
    return sorted({h for _, h in prt["handles"]})


def last_line(text: str, needle: str) -> int:
    hits = [i + 1 for i, ln in enumerate(text.split("\n")) if needle in ln]
    if not hits:
        raise ValueError(f"no line holds {needle!r}")
    return hits[-1]


def find_line(text: str, needle: str) -> int:
    for i, ln in enumerate(text.split("\n")):
        if needle in ln:
            return i + 1
    raise ValueError(f"no line holds {needle!r}")


def merge_lines(lines: list[int]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for n in sorted(set(lines)):
        if out and n == out[-1][1] + 1:
            out[-1] = (out[-1][0], n)
        else:
            out.append((n, n))
    return out


def decisions(text: str) -> list[tuple[int, int, bool]]:
    """`return Decision(` calls with allow=False: (first line, last line, fail_closed)."""
    lines = text.split("\n")
    out: list[tuple[int, int, bool]] = []
    for i, ln in enumerate(lines):
        m = re.match(r"^(\s+)return Decision\($", ln)
        if not m:
            continue
        j = i + 1
        while j < len(lines) and lines[j] != f"{m[1]})":
            j += 1
        body = "\n".join(lines[i : j + 1])
        if "allow=False" in body:
            out.append((i + 1, j + 1, "fail_closed=True" in body))
    return out


def gh_body_span(gh: str) -> tuple[int, int]:
    lines = gh.split("\n")
    start = next(i for i, ln in enumerate(lines) if ln.strip() == "body = (")
    end = start
    while lines[end].strip() != ")":
        end += 1
    return start + 1, end + 1


# --------------------------------------------------------------------------- the numbers


def compute(ctx: Ctx) -> dict[str, str]:
    v: dict[str, str] = {"sha": ctx.base[:12]}
    flagged = 0
    for n, key in enumerate(D01_FORMS, 1):
        form = ctx.forms[key]
        spec = d01_fields(ctx.d01, n)
        ids = SPEC_IDS[key]
        rws = fm_rows(ctx, key)
        flagged += sum(1 for r in rws if r["flag"])
        cmp_n = diff = 0
        for (_f, _c, _r, helptext), ident in zip(spec, ids, strict=True):
            if helptext is None:
                continue
            cmp_n += 1
            diff += help_norm(helptext) != help_norm(form.by_id(ident).desc)
        built_order = [e.id for e in form.controls if e.id in ids]
        v[f"fm.{key}.help_cmp"] = str(cmp_n)
        v[f"fm.{key}.help_diff"] = str(diff)
        v[f"fm.{key}.order_diff"] = str(sum(a != b for a, b in zip(built_order, ids, strict=True)))
        ctl = form.controls
        stops = sum(len(e.options) if e.type == "checkboxes" else 1 for e in ctl)
        v[f"kb.{key}.stops"] = str(stops + 3)
        v[f"kb.{key}.typed"] = str(sum(e.type in ("textarea", "input") for e in ctl))
        v[f"kb.{key}.req"] = str(sum(bool(e.required) for e in ctl))
        v[f"kb.{key}.drop"] = str(sum(e.type == "dropdown" for e in ctl))
        v[f"kb.{key}.d01rows"] = str(len(spec))
        v[f"kb.{key}.diff"] = str(len(ctl) - len(spec))
    v["fm.bug.changed"] = str(
        sum(1 for r in fm_rows(ctx, "bug") if r["flag"] in ("added", "required"))
    )
    rows37 = trows(sec(ctx, "3.7 "))
    v["fm.rows"] = str(sum(len(fm_rows(ctx, k)) for k in D01_FORMS) + len(rows37))
    v["fm.non_match"] = str(flagged + sum(1 for r in rows37 if not r[3].startswith("match")))
    quarterly = [
        o for e in ctx.forms["quarterly"].elems if e.type == "checkboxes" for o in e.options
    ]
    v["fm.quarterly.req"] = str(sum(bool(o.required) for o in quarterly))
    v["fm.release.req"] = str(
        sum(
            bool(e.required) + sum(bool(o.required) for o in e.options)
            for e in ctx.forms["release"].controls
        )
    )
    for k in EXTRA_FORMS:
        v[f"fm.{k}.absent"] = str(
            sum(ctx.records.get(f"label {x}") == "absent" for x in ctx.forms[k].labels)
        )
    v["task.area_options"] = str(len(ctx.forms["task"].by_id("area").options))
    names = label_names(ctx)
    v["labels.checked"] = str(len(names))
    absent_names = [x for x in names if ctx.records.get(f"label {x}") == "absent"]
    v["labels.missing"] = str(len(absent_names))
    v["labels.absent_names"] = ", ".join(f"`{x}`" for x in absent_names)
    v["labels.fixed"] = ", ".join(
        f"`{x}`"
        for x in names
        if x in FIXED_AT_SOURCE and ctx.records.get(f"label {x}") == "present"
    )
    v["teams.checked"] = str(len(team_handles(ctx)))
    v["teams.absent"] = str(
        sum(ctx.records.get(f"team {x}") == "absent" for x in team_handles(ctx))
    )
    v["records.date"] = ctx.records.get("date checked", "")
    repro = ctx.forms["bug"].by_id("repro")
    v["bug.repro.redaction"] = "yes" if re.search(r"redact", repro.desc, re.IGNORECASE) else "no"
    # the no-secrets block
    warn = d01_warning(ctx.d01)
    v["sc.forms_all"] = str(len(ctx.forms))
    v["sc.forms_d01"] = str(len(D01_FORMS))
    first, second = warn_pair(warn)
    v["sc.present"] = str(sum(has_text(f, first, second) for f in ctx.forms.values()))
    extras = [ctx.forms[k] for k in EXTRA_FORMS]
    v["sc.extra_total"] = str(len(extras))
    v["sc.extra_pair"] = str(sum(has_text(f, first, second) for f in extras))
    v["sc.extra_first"] = str(sum(has_text(f, first) for f in extras))
    v["sc.same"] = str(
        sum(
            1
            for k in D01_FORMS
            if ctx.forms[k].elems and first_para(ctx.forms[k].elems[0].value) == warn
        )
    )
    v["sc.vuln_fields"] = str(
        sum(
            bool(re.search(r"vulnerab", f"{e.label} {e.desc}", re.IGNORECASE))
            for f in ctx.forms.values()
            for e in f.controls
        )
    )
    # the governance documents
    hits = diagrams = no_prose = 0
    for gk, doc in zip(GOV_KEYS, GOV_DOCS, strict=True):
        sc = md_scan(ctx.sources.get(doc, ""))
        for k, val in sc.items():
            v[f"gm.{gk}.{k}"] = str(val)
        hits += sc["steps"] + sc["tables"] + sc["links"] + sc["noprose"] + (sc["h1"] != 1)
        diagrams += sc["mermaid"]
        no_prose += sc["noprose"]
    v["gm.hits"], v["gm.diagrams"], v["gm.no_prose"] = str(hits), str(diagrams), str(no_prose)
    v["gm.weak"] = str(sum(int(v[f"gm.{gk}.weak"]) for gk in GOV_KEYS))
    v["gm.docs"] = str(len(GOV_DOCS))
    # the pull-request template
    prt = prt_facts(ctx.sources[KEYS["PRT"]])
    v["pt.gates_present"] = str(len(prt["gates"]))
    v["pt.gates_total"] = str(len(re.findall(r"^\| `### ", section(ctx.d01, "5. "), re.MULTILINE)))
    v["pt.checkboxes"] = str(prt["boxes"])
    ceiling = re.search(r"~(\d+) checklist lines", ctx.d01)
    filled = re.search(r"checklist at ~(\d+) lines", ctx.d01)
    if not ceiling or not filled:
        raise ValueError("the ceiling figures of E01-D01 section 6 are not readable")
    v["pt.ceiling"], v["pt.filled"] = ceiling[1], filled[1]
    dead = [h for h in team_handles(ctx) if ctx.records.get(f"team {h}") == "absent"]
    owners = ctx.sources.get(KEYS["OWN"], "").split("\n")
    named = [ln for ln in owners if any(re.search(rf"@{re.escape(h)}(?![\w-])", ln) for h in dead)]
    v["owners.comments"] = str(sum(ln.lstrip().startswith("#") for ln in named))
    v["owners.rules"] = str(sum(not ln.lstrip().startswith("#") for ln in named))
    v["lc.rows"] = str(len(later_changes(ctx)))
    gcs = [guard_flags(ctx, guard_spans(ctx, f"GC-{n}")) for n in range(1, 5)]
    v["gc.next_yes"] = str(sum(g["next"] == "yes" for g in gcs))
    v["gc.next_partly"] = str(sum(g["next"] == "partly" for g in gcs))
    v["gc.reopen_no"] = str(sum(g["reopen"] == "no" for g in gcs))
    v["pt.empty_gates"] = str(len(prt["gate_empty"]))
    # spec-derived counts (each table is also checked against the base by its own gate)
    for fam, pre, key in (
        ("PT", "10. ", "pt.rows"),
        ("SC", "7. ", "sc.rows"),
        ("GC", "8. ", "gc.rows"),
        ("PN", "6. ", "pn.rows"),
    ):
        v[key] = str(len(frows(sec(ctx, pre), fam)))
    sr = frows(sec(ctx, "5. "), "SR")
    v["sr.total"] = str(len(sr))
    v["sr.tree"] = str(sum(r[5].startswith("tree:") for r in sr if len(r) > 5))
    v["sr.owner"] = str(sum("owner-run" in r[4] for r in sr if len(r) > 4))
    df = frows(sec(ctx, "11. "), "DF")
    v["df.total"] = str(len(df))
    for sev in SEVERITIES:
        v[f"df.{sev.lower()}"] = str(sum(r[2] == sev for r in df))
    for cls, k in (
        ("content defect", "defect"),
        ("drift", "drift"),
        ("spec update", "spec"),
        ("known", "known"),
        ("accepted", "accepted"),
    ):
        v[f"df.{k}"] = str(sum(r[1] == cls for r in df))
    blocking = {r[0] for r in df if r[2] == "Blocking"}
    px = frows(sec(ctx, "12. "), "PX")
    v["px.blocking"] = str(
        sum(bool(blocking & {f"DF-{n}" for n in ids_in(r[2], "DF")}) for r in px)
    )
    # merges, records, sprints
    for k, pr in MERGES.items():
        v[f"{k}.merge"] = f"#{pr} `{commit_of(pr)[0][:10]}`"
    v["wv.d01.merge"] = commit_of(MERGES["d01"])[1]
    v["wv.t05.merge"] = commit_of(MERGES["t05"])[1]
    v["wv.order"] = "yes" if v["wv.d01.merge"] < v["wv.t05.merge"] else "no"
    closed = ctx.records.get("issue 76", "")
    v["wv.d01.closed"] = closed.split(" ", 1)[1] if closed.startswith("closed ") else "unrecorded"
    cpm = ctx.sources.get(KEYS["CPM"], "")
    readers = re.search(r"QA sign-off|a11y evidence|Security review|### Test plan", cpm)
    v["parser.file"] = (
        "read by the PR-metadata check" if readers else "none; the a11y guard reads an issue body"
    )
    cal = sprint_calendar(ctx.sources[KEYS["CAL"]])
    due = due_date(ctx)
    base_day = base_date(ctx.base)
    placed, now = sprint_of(cal, due), sprint_of(cal, base_day)
    v["sprint.placed"], v["sprint.now"], v["sprint.late"] = (
        f"{placed:02d}",
        f"{now:02d}",
        str(now - placed),
    )
    for tag, n in (("placed", placed), ("now", now)):
        a, b = sprint_range(cal, n)
        v[f"{tag}.start"], v[f"{tag}.end"] = a.isoformat(), b.isoformat()
    v["base.date"] = base_day.isoformat()
    return v


def warn_pair(warn: str) -> tuple[str, str]:
    """The two sentences of the no-secrets block: the first, and the report diversion."""
    cut = warn.index("Found a vulnerability?")
    return warn[:cut].strip(), warn[cut:].strip()


def has_text(form: Form, *parts: str) -> bool:
    """The form's opening markdown block holds every part whole (whitespace-normalised)."""
    value = norm(form.elems[0].value) if form.elems and form.elems[0].type == "markdown" else ""
    return all(p in value for p in parts)


def later_changes(ctx: Ctx) -> list[tuple[str, str, str]]:
    """(short sha, UTC date, file keys) of each commit after the T05 merge that touched a form, the
    chooser file or the template, up to the base, newest first."""
    names = {v: k for k, v in KEYS.items() if v.startswith(FORMS_DIR) or v == KEYS["PRT"]}
    out = git(
        "log",
        f"{commit_of(MERGES['t05'])[0]}..{ctx.base}",
        "--name-only",
        "--format=@@%H %cI",
        "--",
        FORMS_DIR,
        KEYS["PRT"],
    )
    rows: list[tuple[str, str, str]] = []
    for blk in out.split("@@")[1:]:
        head, *files = blk.strip().split("\n")
        sha, when = head.split()
        day = datetime.datetime.fromisoformat(when).astimezone(datetime.UTC).date().isoformat()
        keys = sorted({names[f] for f in files if f in names})
        rows.append((sha[:10], day, ", ".join(f"`{k}`" for k in keys)))
    return rows


def base_date(base: str) -> datetime.date:
    out = git("show", "-s", "--format=%cI", base).strip()
    return datetime.datetime.fromisoformat(out).astimezone(datetime.UTC).date()


def due_line(ctx: Ctx) -> int:
    text = ctx.base_text("31") or ""
    hits = [
        i + 1
        for i, ln in enumerate(text.split("\n"))
        if "`E01-D02`" in ln and re.search(r"\d{4}-\d\d-\d\d", ln)
    ]
    if len(hits) != 1:
        raise ValueError(f"the sprint plan has {len(hits)} dated rows for E01-D02")
    return hits[0]


def due_date(ctx: Ctx) -> datetime.date:
    line = ctx.base_line("31", due_line(ctx)) or ""
    m = re.search(r"(\d{4})-(\d\d)-(\d\d)", line)
    if not m:
        raise ValueError("no date on the E01-D02 row")
    return datetime.date(int(m[1]), int(m[2]), int(m[3]))


# ------------------------------------------------------------------------------- the gates

Gate = Callable[[Ctx, dict[str, str], Findings, list[str]], None]


def g_filled(ctx: Ctx, vals: dict[str, str], f: Findings, w: list[str]) -> None:
    for m in SLOT.finditer(ctx.spec):
        if m[1] == "RENDER" and ctx.mode == "PR-1":
            w.append(f"RENDER slot {m[0]} waits for the rendered check")
        else:
            f.append(("G01-FILLED", f"slot {m[0]} is not filled"))


def g_audit(ctx: Ctx, vals: dict[str, str], f: Findings, w: list[str]) -> None:
    for m in AUDIT.finditer(ctx.spec):
        key, val = m[1], m[2]
        if key not in vals:
            f.append(("G02-AUDIT", f"marker {key!r} is not a key the tool computes"))
            continue
        if vals[key] != val:
            f.append(("G02-AUDIT", f"{key}: the marker says {val!r}, the tool {vals[key]!r}"))
        before = ctx.spec[: m.start()].rstrip()
        if not (before.endswith(val) or before.rstrip("`").endswith(val.rstrip("`"))):
            f.append(("G02-AUDIT", f"{key}: the visible value before the marker is not {val!r}"))


def g_cite(ctx: Ctx, vals: dict[str, str], f: Findings, w: list[str]) -> None:
    pins = parse_pins(ctx.pins)
    for key, n in sorted(endpoints(ctx.spec)):
        line = ctx.base_line(key, n)
        if line is None or not line.strip():
            f.append(("G03-CITE", f"{key}:{n} does not resolve to a non-blank line at the base"))
            continue
        if (key, n) in pins and pins[(key, n)] != line_hash(line):
            f.append(("G03-CITE", f"{key}:{n} moved: its pin no longer matches the base line"))


def g_pins(ctx: Ctx, vals: dict[str, str], f: Findings, w: list[str]) -> None:
    pins = set(parse_pins(ctx.pins))
    ends = endpoints(ctx.spec)
    for k, n in sorted(ends - pins):
        f.append(("G04-PINS", f"{k}:{n} is cited but not pinned"))
    for k, n in sorted(pins - ends):
        f.append(("G04-PINS", f"{k}:{n} is pinned but no longer cited"))


QUOTED_SECTIONS = (
    "3.1 ",
    "3.2 ",
    "3.3 ",
    "3.4 ",
    "3.5 ",
    "3.6 ",
    "3.7 ",
    "5. ",
    "6. ",
    "8. ",
    "10. ",
    "11. ",
    "15. ",
)


def g_verbatim(ctx: Ctx, vals: dict[str, str], f: Findings, w: list[str]) -> None:
    for pre in QUOTED_SECTIONS:
        for r in trows(sec(ctx, pre)):
            text = " | ".join(r)
            quotes = QUOTE.findall(text)
            if not quotes:
                continue
            spans = cite_spans(text)
            if not spans:
                f.append(
                    ("G05-VERBATIM", f"{pre.strip()} {r[0][:24]}: a quoted string and no cite")
                )
                continue
            hay = [
                " ".join(ctx.base_line(k, n) or "" for n in range(a, b + 1)) for k, a, b in spans
            ]
            for q in quotes:
                rx = re.compile(rf"(?<!\w){re.escape(q)}(?!\w)")
                if not any(rx.search(h) for h in hay):
                    f.append(
                        ("G05-VERBATIM", f"{r[0][:24]}: {q[:40]!r} stands on no line the row cites")
                    )


STATUS_FLAG = {
    "bare": "drift",
    "required": "spec-update",
    "added": "spec-update",
    "label": "defect",
    "label-fixed": "fixed-at-source",
}


def g_spec(ctx: Ctx, vals: dict[str, str], f: Findings, w: list[str]) -> None:
    for n, key in enumerate(D01_FORMS, 1):
        got = trows(sec(ctx, f"3.{n} "))
        want = fm_rows(ctx, key)
        if len(got) != len(want):
            f.append(
                ("G06-SPEC", f"3.{n}: {len(got)} rows, the forms and E01-D01 give {len(want)}")
            )
            continue
        for g, x in zip(got, want, strict=True):
            tag = f"3.{n} {x['d01'][:24]}"
            if len(g) != 6:
                f.append(("G06-SPEC", f"{tag}: {len(g)} cells, not 6"))
                continue
            if norm(g[0]) != norm(x["d01"]):
                f.append(("G06-SPEC", f"{tag}: the spec row cell reads {g[0]!r}"))
            if cite_spans(g[1]) != [x["cite"]]:
                f.append(("G06-SPEC", f"{tag}: the built cite is not {x['cite']}"))
            if norm(g[2]) != norm(x["label"]):
                f.append(("G06-SPEC", f"{tag}: the label cell is not {x['label']!r}"))
            if g[3] != x["req"]:
                f.append(("G06-SPEC", f"{tag}: required is {g[3]!r}, not {x['req']!r}"))
            if norm(g[4]) != norm(x["options"]):
                f.append(("G06-SPEC", f"{tag}: options are {g[4]!r}, not {x['options']!r}"))
            m = re.match(r"FM-\d+ (drift|spec-update|defect|fixed-at-source): \S", g[5])
            if x["flag"]:
                if not m or m[1] != STATUS_FLAG[x["flag"]]:
                    f.append(
                        ("G06-SPEC", f"{tag}: status must be an FM {STATUS_FLAG[x['flag']]} row")
                    )
            elif not g[5].startswith("match"):
                f.append(("G06-SPEC", f"{tag}: a row with no difference must read match"))


def df_by_id(ctx: Ctx) -> dict[str, list[str]]:
    return {r[0]: r for r in frows(sec(ctx, "11. "), "DF")}


def g_label(ctx: Ctx, vals: dict[str, str], f: Findings, w: list[str]) -> None:
    names = label_names(ctx)
    for name_ in names:
        if ctx.records.get(f"label {name_}") not in ("present", "absent"):
            f.append(("G07-LABEL", f"label {name_} has no record in the pins file"))
    for k in ctx.records:
        kind, _, name = k.partition(" ")
        if kind == "label" and name not in names:
            f.append(("G07-LABEL", f"the record of label {name} names no form's label"))
    handles = team_handles(ctx)
    for handle in handles:
        if ctx.records.get(f"team {handle}") not in ("present", "absent"):
            f.append(("G07-LABEL", f"team {handle} has no record in the pins file"))
    checked = ctx.records.get("date checked", "")
    if not checked:
        f.append(("G07-LABEL", "the records carry no check date"))
    elif ctx.mode == "post-merge" and checked < base_date(ctx.base).isoformat():
        f.append(("G07-LABEL", f"the records of {checked} are older than the base"))
    dfs = df_by_id(ctx)
    rows37 = {r[0]: r for r in trows(sec(ctx, "3.7 ")) if len(r) > 3}
    for k, fm in EXTRA_FM.items():
        form = ctx.forms[k]
        row = rows37.get(fm)
        for lab in form.labels:
            if ctx.records.get(f"label {lab}") != "absent":
                continue
            dref = re.search(r"DF-\d+", row[3]) if row else None
            cite = (k, form.labels_line, form.labels_line)
            if row is None or f"`{lab}`" not in row[2]:
                f.append(("G07-LABEL", f"{k}: the absent label {lab} is not named in {fm}"))
            elif not dref or dref[0] not in dfs or cite not in set(cite_spans(dfs[dref[0]][7])):
                f.append(("G07-LABEL", f"{k}: {fm} needs a register row citing its labels line"))
    for lab, day in FIXED_AT_SOURCE.items():
        if lab in names and ctx.records.get(f"label {lab}") != "present":
            f.append(("G07-LABEL", f"label {lab} is ruled fixed at source ({day}), not present"))
    for key in D01_FORMS:
        for x in fm_rows(ctx, key):
            if x["flag"] not in ("label", "label-fixed"):
                continue
            got = next(
                (
                    r
                    for r in trows(sec(ctx, f"3.{D01_FORMS.index(key) + 1} "))
                    if r[1:2] and cite_spans(r[1]) == [x["cite"]]
                ),
                None,
            )
            ref = re.search(r"DF-\d+", got[5]) if got else None
            if not ref or ref[0] not in dfs or x["cite"] not in set(cite_spans(dfs[ref[0]][7])):
                f.append(
                    (
                        "G07-LABEL",
                        f"{key}: a missing label needs a register row citing its labels line",
                    )
                )


def g_option(ctx: Ctx, vals: dict[str, str], f: Findings, w: list[str]) -> None:
    dfs = df_by_id(ctx)
    for n, key in enumerate(D01_FORMS, 1):
        got = trows(sec(ctx, f"3.{n} "))
        want = fm_rows(ctx, key)
        for g, x in zip(got, want, strict=False):
            if x["bare_span"] is None or len(g) < 6:
                continue
            ref = re.search(r"DF-\d+", g[5])
            span = (key, *x["bare_span"])
            if not ref or ref[0] not in dfs:
                f.append(
                    ("G08-OPTION", f"{key} {x['d01'][:20]}: a bare option names no register row")
                )
            elif span not in set(cite_spans(dfs[ref[0]][7])):
                f.append(("G08-OPTION", f"{ref[0]} does not cite the options span {span}"))
            elif ctx.mode == "PR-1" and dfs[ref[0]][4].startswith("this ticket (fixed here)"):
                head = parse_form(ctx.head.get(key, ""))
                ids = {e.id for e in head.elems}
                if x["id"] not in ids or any(is_bare(o.text) for o in head.by_id(x["id"]).options):
                    f.append(
                        ("G08-OPTION", f"{ref[0]} is fixed here, yet {key} keeps a bare option")
                    )


def g_findings(ctx: Ctx, vals: dict[str, str], f: Findings, w: list[str]) -> None:
    dfs = df_by_id(ctx)
    pxs = {r[0] for r in frows(sec(ctx, "12. "), "PX")}
    for ident, r in dfs.items():
        if len(r) != 8:
            f.append(("G09-FINDINGS", f"{ident}: {len(r)} cells, not 8"))
            continue
        _, cls, sev, clause, _owner, target, method, sentence = r
        if cls not in (*CLASSES, "accepted"):
            f.append(("G09-FINDINGS", f"{ident}: class {cls!r} is not in the ruled set"))
        if sev not in SEVERITIES:
            f.append(("G09-FINDINGS", f"{ident}: severity {sev!r} is not in the ruled set"))
        if (sev == "Info") != (cls in ("known", "accepted")):
            f.append(("G09-FINDINGS", f"{ident}: Info and a known or accepted class go together"))
        if not clause or (
            WCAG.search(clause) and cls == "content defect" and sev not in ("Major", "Blocking")
        ):
            f.append(
                ("G09-FINDINGS", f"{ident}: a WCAG clause on a content defect is Major or Blocking")
            )
        if target not in pxs:
            f.append(("G09-FINDINGS", f"{ident}: target {target!r} is not a PX row"))
        if method not in METHODS and not re.fullmatch(r"\{\{RENDER:[\w.]+\}\}", method):
            f.append(("G09-FINDINGS", f"{ident}: method {method!r} is not in the ruled set"))
        if len(sentence) < 20:
            f.append(("G09-FINDINGS", f"{ident}: no sentence"))
    for n, key in enumerate(D01_FORMS, 1):
        got = trows(sec(ctx, f"3.{n} "))
        for g, x in zip(got, fm_rows(ctx, key), strict=False):
            if not x["flag"] or x["flag"] == "bare" or len(g) < 6:
                continue
            ref = re.search(r"DF-\d+", g[5])
            if not ref or ref[0] not in dfs:
                f.append(
                    ("G09-FINDINGS", f"{key} {x['d01'][:20]}: the status names no register row")
                )
            elif x["cite"] not in set(cite_spans(dfs[ref[0]][7])):
                f.append(("G09-FINDINGS", f"{ref[0]} does not cite {x['cite']}"))
    text = sec(ctx, "11. ") + sec(ctx, "12. ")
    for n in set(ids_in(text, "DF")):
        if f"DF-{n}" not in dfs:
            f.append(("G09-FINDINGS", f"DF-{n} is named and is not a register row"))
    for ident, r in dfs.items():
        if r[5] in pxs:
            px = next(x for x in frows(sec(ctx, "12. "), "PX") if x[0] == r[5])
            if ident not in {f"DF-{n}" for n in ids_in(px[2], "DF")}:
                f.append(("G09-FINDINGS", f"{r[5]} does not list {ident}"))
    findings_pt(ctx, dfs, f)
    findings_fm(ctx, dfs, f)


def findings_pt(ctx: Ctx, dfs: dict[str, list[str]], f: Findings) -> None:
    """Section 10: the ruled sets, the WCAG floor and a register row for every difference."""
    for r in frows(sec(ctx, "10. "), "PT"):
        if len(r) != 6:
            f.append(("G09-FINDINGS", f"{r[0]}: {len(r)} cells, not 6"))
            continue
        _, _obs, clause, cls, sev, _own = r
        if cls not in (*CLASSES, "accepted", "match"):
            f.append(("G09-FINDINGS", f"{r[0]}: class {cls!r} is not in the ruled set"))
        if sev not in SEVERITIES:
            f.append(("G09-FINDINGS", f"{r[0]}: severity {sev!r} is not in the ruled set"))
        if (sev == "Info") != (cls in ("match", "known", "accepted")):
            f.append(("G09-FINDINGS", f"{r[0]}: Info goes with match, known or accepted only"))
        parts = [p.strip() for p in re.split(r"[;,]", clause)]
        if not clause or not all(CLAUSE_PART.fullmatch(p) for p in parts):
            f.append(("G09-FINDINGS", f"{r[0]}: clause {clause!r} is not a ruled clause"))
        if WCAG.search(clause) and cls == "content defect" and sev not in ("Major", "Blocking"):
            f.append(("G09-FINDINGS", f"{r[0]}: a WCAG clause on a content defect is Major or up"))
        if cls in ("content defect", "spec update", "drift"):
            linked = [d for d in dfs.values() if re.search(rf"\b{r[0]}\b", d[7])]
            if not any(d[1] == cls and d[2] == sev for d in linked):
                f.append(("G09-FINDINGS", f"{r[0]}: no register row of its class and severity"))


def findings_fm(ctx: Ctx, dfs: dict[str, list[str]], f: Findings) -> None:
    """Section 3.7: a row that is not a match names a register row that names it back."""
    for r in trows(sec(ctx, "3.7 ")):
        if len(r) < 4 or r[3].startswith("match"):
            continue
        ref = re.search(r"DF-\d+", r[3])
        if not ref or ref[0] not in dfs:
            f.append(("G09-FINDINGS", f"{r[0]}: the status names no register row"))
            continue
        row = dfs[ref[0]]
        if not re.search(rf"\b{r[0]}\b", row[7]):
            f.append(("G09-FINDINGS", f"{ref[0]} does not name {r[0]}"))
        word = r[3].split(" ", 1)[0]
        if word in FM_DF_CLASS and row[1] != FM_DF_CLASS[word]:
            f.append(("G09-FINDINGS", f"{r[0]}: {word} is not the class of {ref[0]}"))


def g_platform(ctx: Ctx, vals: dict[str, str], f: Findings, w: list[str]) -> None:
    for r in frows(sec(ctx, "6. "), "PN"):
        if len(r) != 6:
            f.append(("G10-PLATFORM", f"{r[0]}: {len(r)} cells, not 6"))
            continue
        tag, verdict = r[2], r[5]
        if tag not in TAGS:
            f.append(("G10-PLATFORM", f"{r[0]}: tag {tag!r} is not ours, shared or platform"))
        if not WCAG.search(r[1]):
            f.append(("G10-PLATFORM", f"{r[0]}: no WCAG criterion"))
        if tag == "platform" and not verdict.startswith("platform limitation, accepted"):
            f.append(
                ("G10-PLATFORM", f"{r[0]}: a platform row reads platform limitation, accepted")
            )
        if tag == "shared" and "our share" not in verdict:
            f.append(("G10-PLATFORM", f"{r[0]}: a shared row names our share"))
        if tag == "ours" and "accepted" in verdict:
            f.append(("G10-PLATFORM", f"{r[0]}: an ours row is a defect to fix, never accepted"))
        if re.search(r"\bDF-\d+|\b(?:Blocking|Major|Minor)\b", " ".join(r)):
            f.append(
                ("G10-PLATFORM", f"{r[0]}: a platform-note row is no defect id and has no severity")
            )


GUARD_ROWS = {
    "GC-1": ("GQ", False),
    "GC-2": ("GS", False),
    "GC-3": ("GA", False),
    "GC-4": ("*", True),
}


def guard_spans(ctx: Ctx, ident: str) -> list[tuple[str, int, int]]:
    if ident == "GC-5":
        a, b = gh_body_span(ctx.base_text("GH") or "")
        return [("GH", a, b)]
    out: list[tuple[str, int, int]] = []
    for key in ("GQ", "GS", "GA"):
        want_key, closed = GUARD_ROWS[ident]
        if want_key not in (key, "*"):
            continue
        for a, b, fc in decisions(ctx.base_text(key) or ""):
            if fc == closed:
                out.append((key, a, b))
    return out


def g_guard(ctx: Ctx, vals: dict[str, str], f: Findings, w: list[str]) -> None:
    for r in frows(sec(ctx, "8. "), "GC"):
        if len(r) != 10:
            f.append(("G11-GUARD", f"{r[0]}: {len(r)} cells, not 10"))
            continue
        spans = guard_spans(ctx, r[0])
        if not spans:
            f.append(("G11-GUARD", f"{r[0]}: the guard code has no such decision"))
            continue
        if cite_spans(r[2]) != spans:
            f.append(("G11-GUARD", f"{r[0]}: the cited spans are not {spans}"))
        if r[0] == "GC-5":
            gh = ctx.base_text("GH") or ""
            a, b = spans[0][1], spans[0][2]
            body = "\n".join(gh.split("\n")[a - 1 : b])
            dods = [
                m[1]
                for k in ("GQ", "GS", "GA")
                for m in re.finditer(r'^DOD_REF = "([^"]+)"', ctx.base_text(k) or "", re.MULTILINE)
            ]
            ok = (
                " -- " in body
                and "Reason: " in body
                and "DoD reference: " in body
                and not re.search(r"^\s*f?\"- ", body, re.MULTILINE)
                and len(dods) == 3
                and all("#" in d and "://" not in d for d in dods)
            )
            if not ok:
                f.append(
                    (
                        "G11-GUARD",
                        "GC-5: the comment body is not a dash line plus paragraphs and a path",
                    )
                )
            continue
        fl = guard_flags(ctx, spans)
        for col, name in ((3, "verdict"), (4, "emoji"), (5, "next"), (6, "reopen")):
            if r[col] != fl[name]:
                f.append(
                    ("G11-GUARD", f"{r[0]}: {name} is {r[col]!r}, the code gives {fl[name]!r}")
                )
    ids = [r[0] for r in frows(sec(ctx, "8. "), "GC")]
    if ids != [f"GC-{n}" for n in range(1, 6)]:
        f.append(("G11-GUARD", "section 8 is not GC-1..GC-5"))
    for r in frows(sec(ctx, "8. "), "GC"):
        if len(r) == 10 and (r[7] not in CLASSES or r[8] not in SEVERITIES):
            f.append(("G11-GUARD", f"{r[0]}: class or severity is not in the ruled set"))


def g_md(ctx: Ctx, vals: dict[str, str], f: Findings, w: list[str]) -> None:
    raw = [ln for ln in sec(ctx, "9. ").split("\n") if re.match(r"^\|\s*GM-\d+", ln)]
    if len(raw) != len(GOV_DOCS):
        f.append(("G12-MD", f"section 9 has {len(raw)} GM rows, not {len(GOV_DOCS)}"))
        return
    cols = ("h1", "steps", "tables", "links", "mermaid", "noprose")
    hit_ids: set[str] = set()
    for ln, doc, gk in zip(raw, GOV_DOCS, GOV_KEYS, strict=True):
        c = cells(ln)
        if len(c) != 8 or c[1].strip("`") != doc:
            f.append(("G12-MD", f"{c[0]}: the document cell is not {doc}"))
            continue
        for i, col in enumerate(cols):
            key = f"gm.{gk}.{col}"
            if f"{{{{COUNT:{key}}}}}" not in c[2 + i] and f"audit:{key}=" not in c[2 + i]:
                f.append(("G12-MD", f"{c[0]}: the {col} cell is not the slot {key}"))
        sc = md_scan(ctx.sources.get(doc, ""))
        if sc["h1"] != 1 or sc["steps"] or sc["tables"] or sc["links"] or sc["noprose"]:
            hit_ids.add(c[0])
    named: set[str] = set()
    for r in df_by_id(ctx).values():
        named |= set(re.findall(r"GM-\d+", r[7]))
    if named != hit_ids:
        f.append(("G12-MD", f"register rows name {sorted(named)}, the hits are {sorted(hit_ids)}"))


def g_route(ctx: Ctx, vals: dict[str, str], f: Findings, w: list[str]) -> None:
    owners: list[tuple[str, str]] = []
    owners += [(r[0], r[4]) for r in df_by_id(ctx).values() if len(r) == 8]
    owners += [(r[0], r[3]) for r in frows(sec(ctx, "12. "), "PX") if len(r) > 3]
    owners += [(r[0], r[4]) for r in frows(sec(ctx, "7. "), "SC") if len(r) > 4]
    owners += [(r[0], r[5]) for r in frows(sec(ctx, "10. "), "PT") if len(r) > 5]
    owners += [(r[0], r[9]) for r in frows(sec(ctx, "8. "), "GC") if len(r) > 9]
    for ident, cell in owners:
        head = cell.split(";")[0].strip()
        if head not in OWNERS:
            f.append(("G13-ROUTE", f"{ident}: owner {head!r} is not in the ruled set"))
    text = " ".join(c for _, c in owners) + sec(ctx, "16. ")
    for m in re.finditer(r"\bE\d\d-[A-Z]\d\d\b", text):
        num = next((n for n, k in ISSUES.items() if k == m[0]), None)
        state = ctx.records.get(f"issue {num}", "") if num else ""
        if not state:
            f.append(("G13-ROUTE", f"{m[0]} is named and has no issue record"))
        elif state.startswith("closed") and not re.search(rf"{m[0]}[^|;]*closed", text):
            f.append(("G13-ROUTE", f"{m[0]} is closed and the text does not say so"))


def g_hygiene(ctx: Ctx, vals: dict[str, str], f: Findings, w: list[str]) -> None:
    for name, text in (("the spec", ctx.spec), ("the tool", ctx.tool), ("the pins", ctx.pins)):
        low = text.lower()
        for word in BANNED:
            if word in low:
                f.append(("G14-HYGIENE", f"{name}: a word from the private list"))
        for pat, what in ((URL, "a URL"), (UUID, "a uuid"), (LOCAL_PATH, "a local path")):
            m = pat.search(text)
            if m:
                f.append(("G14-HYGIENE", f"{name}: {what} {m[0][:24]!r}"))
    if CLOSING.search(ctx.spec):
        f.append(("G14-HYGIENE", "the spec carries a closing keyword before an issue number"))


def g_secret(ctx: Ctx, vals: dict[str, str], f: Findings, w: list[str]) -> None:
    for name, text in (("the spec", ctx.spec), ("the pins", ctx.pins)):
        m = SECRET.search(text)
        if m:
            f.append(("G15-SECRET", f"{name}: a secret-shaped value {m[0][:6]!r}…"))


EDIT_FORMS = {KEYS[k]: k for k in FORM_FILES}


def form_frame(form: Form) -> list[Any]:
    """What an in-place wording fix may not move (RULED BQ-08): all but descriptions, option
    text and placeholders."""
    elems = [
        (e.type, e.id, e.label, e.required, e.render, e.value, [o.required for o in e.options])
        for e in form.elems
    ]
    return [form.name, form.title, form.labels, elems]


def g_scope(ctx: Ctx, vals: dict[str, str], f: Findings, w: list[str]) -> None:
    if ctx.mode != "PR-1":
        return
    for p in ctx.changed:
        if p not in OWN and p != D01_REL and p not in EDIT_FORMS:
            f.append(("G16-SCOPE", f"{p} is outside the edit set"))
    for rel, key in EDIT_FORMS.items():
        if rel in ctx.changed and form_frame(parse_form(ctx.head.get(key, ""))) != form_frame(
            ctx.forms[key]
        ):
            f.append(("G16-SCOPE", f"{key}: a change beyond description, option, placeholder"))


def id_lists(ctx: Ctx) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    fm: list[str] = []
    for n in range(1, 7):
        for r in trows(sec(ctx, f"3.{n} ")):
            fm += re.findall(r"^FM-\d+", r[5]) if len(r) > 5 else []
    fm += [r[0] for r in trows(sec(ctx, "3.7 "))]
    out["FM"] = fm
    for fam, pre in (
        ("LC", "3.8 "), ("SR", "5. "), ("PN", "6. "), ("SC", "7. "), ("GC", "8. "), ("GM", "9. "), ("PT", "10. "),
        ("DF", "11. "), ("PX", "12. "), ("KB", "4. "), ("OR", "14. "), ("WV", "15. "), ("CO", "16. "),
    ):  # fmt: skip
        out[fam] = [r[0] for r in frows(sec(ctx, pre), fam)]
    return out


def g_ids(ctx: Ctx, vals: dict[str, str], f: Findings, w: list[str]) -> None:
    for fam, ids in id_lists(ctx).items():
        nums = [int(i.rsplit("-", 1)[1]) for i in ids]
        if not ids or nums != list(range(1, len(ids) + 1)):
            f.append(("G17-IDS", f"{fam}: the ids are not 1..n in order ({ids[:3]}…)"))


def g_ruled(ctx: Ctx, vals: dict[str, str], f: Findings, w: list[str]) -> None:
    want = [f"BQ-{n:02d}" for n in range(1, 23)]
    rows_r = frows(sec(ctx, "R. "), "BQ")
    listed = [r[0] for r in rows_r]
    if listed != want:
        f.append(("G18-RULED", f"section R lists {len(listed)} BQ rows, not BQ-01..BQ-22"))
    for r in rows_r:
        if r[-1] != RULED_STAMP:
            f.append(("G18-RULED", f"{r[0]}: the status is not the ruling stamp"))
    body = ctx.spec.replace(sec(ctx, "R. "), "")
    stamped: set[str] = set()
    for m in RULED_REF.finditer(body):
        stamped |= {m[1], *re.findall(r"BQ-\d\d", m[2])}
    for bq in sorted(stamped - set(want)):
        f.append(("G18-RULED", f"a stamp names {bq}, which is not on the list"))
    for bq in sorted(set(want) - stamped):
        f.append(("G18-RULED", f"{bq} is stamped nowhere in the text"))
    if BQ_MARK.search(ctx.spec):
        f.append(("G18-RULED", "an unruled BQ marker is left"))


def g_walk(ctx: Ctx, vals: dict[str, str], f: Findings, w: list[str]) -> None:
    items = re.findall(r"^\d+\. ", sec(ctx, "14. "), re.MULTILINE)
    if not items or len(items) > 10:
        f.append(("G19-WALK", f"the owner checklist holds {len(items)} items, not 1..10"))


def g_freeze(ctx: Ctx, vals: dict[str, str], f: Findings, w: list[str]) -> None:
    if ctx.merged_spec is None:
        return
    now = {strip_markers(ln) for ln in ctx.spec.split("\n")}
    for ln in ctx.merged_spec.split("\n"):
        if ln.startswith("|") and not ln.startswith("| ---") and strip_markers(ln) not in now:
            f.append(("G20-FREEZE", f"a merged row changed: {ln[:48]!r}"))


BUILT_KEYS = {
    *FORM_FILES,
    *EXTRA_FORMS,
    "CHOOSER",
    "PRT",
    "GH",
    "RG",
    "GQ",
    "GS",
    "GA",
    "IB",
    "CPM",
}


def g_security(ctx: Ctx, vals: dict[str, str], f: Findings, w: list[str]) -> None:
    for r in frows(sec(ctx, "7. "), "SC"):
        text = " | ".join(r)
        if '"' in text:
            f.append(("G21-SECURITY", f"{r[0]}: a security-bearing row carries a quoted string"))
        if any(k in BUILT_KEYS for k, _, _ in cite_spans(text)):
            f.append(("G21-SECURITY", f"{r[0]}: a security-bearing row cites built code or a form"))


def anchors(
    ctx: Ctx,
) -> tuple[dict[str, set[tuple[str, int, int]]], dict[str, set[tuple[str, int, int]]]]:
    story, task = ctx.forms["story"], ctx.forms["task"]
    chooser = chooser_facts(ctx.sources[KEYS["CHOOSER"]])
    links = [("CHOOSER", x["start"], x["end"]) for x in chooser["links"]]
    prt = prt_facts(ctx.sources[KEYS["PRT"]])
    prt_text = ctx.sources[KEYS["PRT"]]
    lines = prt_text.split("\n")
    qa_line = prt["gates"]["QA sign-off"]
    items = [i + 1 for i in range(qa_line, len(lines)) if re.match(r"^\s*- \[[ x~]\]", lines[i])]
    first_items = merge_lines(items)[0]
    d01 = ctx.d01
    ex: dict[str, set[tuple[str, int, int]]] = {
        "SR-1": set(links),
        "SR-2": {links[0]},
        "SR-3": {("story", story.name_line, story.name_line), ("story", story.title_line, story.title_line)},
        "SR-4": {("story", story.elems[0].start, story.elems[0].end)},
        "SR-5": {("story", story.by_id("user-story").start, story.by_id("user-story").end)},
        "SR-6": {("story", story.by_id("acceptance-criteria").start, story.by_id("acceptance-criteria").end)},
        "SR-7": {("story", story.by_id("has-ui-surface").start, story.by_id("has-ui-surface").end)},
        "SR-8": {("story", story.by_id("contract-link").start, story.by_id("contract-link").end)},
        "SR-9": {("story", *option_span(story.by_id("estimate"))), ("task", *option_span(task.by_id("priority")))},
        "SR-11": {one("story", story.by_id("acceptance-criteria").required_line)},
        "PT-2": {("PRT", prt["type_line"], prt["type_line"])}
        | {("PRT", prt["gates"][h], prt["gates"][h]) for h in ("Acceptance criteria", "Test plan")},
        "PT-3": {("PRT", ln, ln2) for ln, ln2 in prt_empty_spans(prt, lines)},
        "PT-4": {
            ("PRT", prt["reviews_line"], prt["reviews_line"]),
            ("PRT", qa_line, qa_line),
            ("PRT", *first_items),
        },
        "PT-5": {("PRT", find_line(prt_text, "Gate-heading contract"), find_line(prt_text, "never a checkbox"))},
        "PT-7": {("PRT", a, b) for a, b in merge_lines([ln for ln, _ in prt["handles"]])},
        "PT-8": {one("PRT", find_line(prt_text, "[~]"))},
        "PT-9": {one("D01", find_line(d01, "~110")), one("D01", find_line(d01, "~35"))},
        "PT-10": {
            one("GA", find_line(ctx.base_text("GA") or "", "find_section(issue.body")),
            one("D01", find_line(d01, "parses the **PR body**")),
        },
    }  # fmt: skip
    sup = {"DF-1": {one("GH", find_line(ctx.base_text("GH") or "", '"type/story": "Story"'))}}
    return ex, sup


def one(key: str, n: int) -> tuple[str, int, int]:
    return (key, n, n)


def prt_empty_spans(prt: dict[str, Any], lines: list[str]) -> list[tuple[int, int]]:
    heads = [h[0] for h in prt["heads"]]
    out: list[tuple[int, int]] = []
    for ln in prt["gate_empty"]:
        nxt = next((h for h in heads if h > ln), len(lines) + 1)
        end = nxt - 1
        while end > ln and lines[end - 1].strip() in ("", "---"):
            end -= 1
        out.append((ln, end))
    return out


def g_anchor(ctx: Ctx, vals: dict[str, str], f: Findings, w: list[str]) -> None:
    ex, sup = anchors(ctx)
    by_row: dict[str, set[tuple[str, int, int]]] = {}
    for pre, fam in (("5. ", "SR"), ("10. ", "PT"), ("11. ", "DF")):
        for r in frows(sec(ctx, pre), fam):
            by_row[r[0]] = set(cite_spans(" | ".join(r)))
    for ident, want in ex.items():
        got = by_row.get(ident)
        if got is None:
            f.append(("G22-ANCHOR", f"{ident}: the row is missing"))
        elif got != want:
            f.append(
                ("G22-ANCHOR", f"{ident}: cites {sorted(got)}, the base anchors {sorted(want)}")
            )
    for ident, want in sup.items():
        if not want <= by_row.get(ident, set()):
            f.append(("G22-ANCHOR", f"{ident}: does not cite {sorted(want)}"))
    chooser = [
        set(),
        set(),
        {("CHOOSER", *_span(chooser_facts(ctx.sources[KEYS["CHOOSER"]]), 1))},
        {one("CHOOSER", chooser_facts(ctx.sources[KEYS["CHOOSER"]])["blank_line"])},
        {
            ("CHOOSER", *_span(chooser_facts(ctx.sources[KEYS["CHOOSER"]]), 0)),
            one("D01", find_line(ctx.d01, "positioned above the template list")),
            one("D01", last_line(ctx.d01, "positioned above the template list")),
        },
    ]  # fmt: skip
    rows37 = trows(sec(ctx, "3.7 "))
    if len(rows37) != len(chooser):
        f.append(("G22-ANCHOR", f"section 3.7 has {len(rows37)} rows, not {len(chooser)}"))
    for r, want in zip(rows37, chooser, strict=False):
        if set(cite_spans(" | ".join(r))) != want:
            f.append(
                ("G22-ANCHOR", f"{r[0]}: the cites are not the chooser anchors {sorted(want)}")
            )
    s16 = set(cite_spans(sec(ctx, "16. ")))
    due = ("31", due_line(ctx), due_line(ctx))
    if due not in s16:
        f.append(("G22-ANCHOR", "section 16 does not cite the sprint plan's E01-D02 row"))


def _span(ch: dict[str, Any], i: int) -> tuple[int, int]:
    return ch["links"][i]["start"], ch["links"][i]["end"]


def g_later(ctx: Ctx, vals: dict[str, str], f: Findings, w: list[str]) -> None:
    got = [r[1:] for r in frows(sec(ctx, "3.8 "), "LC")]
    want = [[f"`{sha}`", day, files] for sha, day, files in later_changes(ctx)]
    if not want:
        f.append(("G23-LATER", "the log at the base shows no change after the T05 merge"))
    if got != want:
        f.append(
            ("G23-LATER", f"the table has {len(got)} rows, the log at the base gives {len(want)}")
        )


def g_status(ctx: Ctx, vals: dict[str, str], f: Findings, w: list[str]) -> None:
    for r in trows(sec(ctx, "3.7 ")):
        if len(r) < 4 or not re.match(r"(?:drift|spec-update|defect|out-of-spec-owner)\b", r[3]):
            f.append(("G24-STATUS", f"{r[0] if r else '?'}: the status is not a ruled word"))
    rows = {r[0]: r for r in frows(sec(ctx, "15. "), "WV") if len(r) > 3}
    for ident, head in WV_STATUS.items():
        if ident not in rows or not rows[ident][3].startswith(head):
            f.append(("G24-STATUS", f"{ident}: the status must read {head!r}"))


GATES: list[tuple[str, Gate]] = [
    ("G01-FILLED", g_filled),
    ("G02-AUDIT", g_audit),
    ("G03-CITE", g_cite),
    ("G04-PINS", g_pins),
    ("G05-VERBATIM", g_verbatim),
    ("G06-SPEC", g_spec),
    ("G07-LABEL", g_label),
    ("G08-OPTION", g_option),
    ("G09-FINDINGS", g_findings),
    ("G10-PLATFORM", g_platform),
    ("G11-GUARD", g_guard),
    ("G12-MD", g_md),
    ("G13-ROUTE", g_route),
    ("G14-HYGIENE", g_hygiene),
    ("G15-SECRET", g_secret),
    ("G16-SCOPE", g_scope),
    ("G17-IDS", g_ids),
    ("G18-RULED", g_ruled),
    ("G19-WALK", g_walk),
    ("G20-FREEZE", g_freeze),
    ("G21-SECURITY", g_security),
    ("G22-ANCHOR", g_anchor),
    ("G23-LATER", g_later),
    ("G24-STATUS", g_status),
]


def run(ctx: Ctx) -> tuple[dict[str, str], Findings, list[str]]:
    f: Findings = []
    w: list[str] = []
    try:
        vals = compute(ctx)
    except RUN_ERRORS as e:
        return {}, [("G00-READ", f"the numbers could not be computed: {type(e).__name__}: {e}")], w
    for code, gate in GATES:
        try:
            gate(ctx, vals, f, w)
        except RUN_ERRORS as e:  # default-deny: an unreadable input is a FAIL
            f.append((code, f"the gate could not run: {type(e).__name__}: {e}"))
    return vals, f, w


# ---------------------------------------------------------------------------------- writers


def fill(ctx: Ctx) -> str:
    vals = compute(ctx)

    def slot(m: re.Match[str]) -> str:
        if m[1] == "RENDER":
            return m[0]
        key = "sha" if m[1] == "SHA" else m[2]
        return f"{vals[key]} <!-- audit:{key}={vals[key]} -->" if key in vals else m[0]

    out = []
    for ln in SLOT.sub(slot, ctx.spec).split("\n"):
        for m in list(AUDIT.finditer(ln)):
            key, old = m[1], m[2]
            if key in vals and old != vals[key]:
                ln = ln.replace(
                    f"{old} <!-- audit:{key}={old} -->",
                    f"{vals[key]} <!-- audit:{key}={vals[key]} -->",
                )
        out.append(ln)
    return "\n".join(out)


def gh_state(path: str) -> str | None:
    """`present`, `absent` (an HTTP 404) or None for any other failure (never guessed)."""
    out = subprocess.run(
        ["gh", "api", path],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )
    if out.returncode == 0:
        return "present"
    return "absent" if "HTTP 404" in out.stderr else None


def gh_issue(num: str) -> str | None:
    out = subprocess.run(
        ["gh", "api", f"repos/{REPO}/issues/{num}", "--jq", '.state + " " + (.closed_at // "-")'],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else None


def records(ctx: Ctx) -> list[str]:
    lines = ["REC date checked " + datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")]
    for name in label_names(ctx):
        state = gh_state(f"repos/{REPO}/labels/{urllib.parse.quote(name, safe='')}")
        if state is None:
            raise RuntimeError(f"label {name}: the lookup failed for a reason other than a 404")
        lines.append(f"REC label {name} {state}")
    for handle in team_handles(ctx):
        org, _, slug = handle.partition("/")
        state = gh_state(f"orgs/{org}/teams/{slug}")
        if state is None:
            raise RuntimeError(f"team {handle}: the lookup failed for a reason other than a 404")
        lines.append(f"REC team {handle} {state}")
    for num in ISSUES:
        got = gh_issue(num)
        if got is None:
            raise RuntimeError(f"issue {num}: the lookup failed")
        lines.append(f"REC issue {num} {got}")
    return lines


def repin(ctx: Ctx, recs: list[str]) -> str:
    lines = [
        "# E01-D02 pins: one cited endpoint per line, `KEY:line sha1-16` of its words at the base,",
        "# then the `REC` lines: label, team and issue states as the hosting site gave them on the",
        "# check date (a 404 is recorded as absent). Written only by",
        "# `e01_d02_designqa_audit.py --repin-ruled`.",
    ]
    for key, n in sorted(endpoints(ctx.spec)):
        lines.append(f"{key}:{n} {line_hash(ctx.base_line(key, n) or '')}")
    return "\n".join([*lines, *recs]) + "\n"


# -------------------------------------------------------------------------------- self-test


def _swap(text: str, old: str, new: str) -> str:
    if old not in text:
        raise ValueError(f"mutation anchor missing: {old[:40]!r}")
    return text.replace(old, new, 1)


def set_cell(text: str, row_id: str, index: int, value: str) -> str:
    out = []
    done = False
    for ln in text.split("\n"):
        if not done and re.match(rf"^\|\s*{re.escape(row_id)}\s*\|", ln):
            parts = ln.split("|")
            parts[index + 1] = f" {value} "
            ln = "|".join(parts)
            done = True
        out.append(ln)
    if not done:
        raise ValueError(f"mutation anchor missing: row {row_id}")
    return "\n".join(out)


def spec_mut(fn: Callable[[str], str]) -> Callable[[Ctx], Ctx]:
    return lambda c: dataclasses.replace(c, spec=fn(c.spec))


def self_test(ctx: Ctx) -> tuple[int, int, list[str]]:
    _, base, _ = run(ctx)
    problems: list[str] = []
    if base:
        problems.append(f"the base run is not clean: {len(base)} FAIL(s)")
    before = {code for code, _ in base}
    passed = 0
    for code, mutate in MUTATIONS:
        try:
            _, got, _ = run(mutate(ctx))
        except RUN_ERRORS as e:
            problems.append(f"{code}: the mutation could not apply: {e}")
            continue
        if any(c == code for c, _ in got) and code not in before:
            passed += 1
        else:
            problems.append(f"{code}: the mutation added no FAIL of its gate")
    if {code for code, _ in GATES} - {code for code, _ in MUTATIONS}:
        problems.append("a gate has no mutation")
    return passed, len(MUTATIONS), problems


# ------------------------------------------------------------------------------------- main


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 on any FAIL (a bare run does too)")
    ap.add_argument("--json", action="store_true", help="print the numbers and findings as JSON")
    ap.add_argument("--fill", action="store_true", help="write the computed values into the spec")
    ap.add_argument("--self-test", action="store_true", help="the mutation self-test")
    ap.add_argument("--repin-ruled", action="store_true", help="rewrite the pins file")
    args = ap.parse_args(argv)
    ctx = build_ctx()
    if args.repin_ruled:
        (ROOT / PINS_REL).write_text(repin(ctx, records(ctx)), encoding="utf-8")
        print(f"pins rewritten: {len(endpoints(ctx.spec))} cited endpoints")
        return 0
    if args.fill:
        (ROOT / SPEC_REL).write_text(fill(ctx), encoding="utf-8")
        print("spec filled")
        return 0
    if args.self_test:
        passed, total, problems = self_test(ctx)
        for p in problems:
            print(f"SELF-TEST FAIL {p}")
        print(f"self-test: {passed}/{total} mutations caught; {len(GATES)} gates; mode {ctx.mode}")
        return 0 if passed == total and not problems else 1
    vals, f, w = run(ctx)
    if args.json:
        slots = sorted({m[0] for m in SLOT.finditer(ctx.spec) if m[1] == "RENDER"})
        print(
            json.dumps(
                {
                    "mode": ctx.mode,
                    "base": ctx.base,
                    "numbers": vals,
                    "findings": f,
                    "warnings": w,
                    "render_slots": slots,
                },
                indent=2,
            )
        )
    else:
        for code, msg in f:
            print(f"FAIL [{code}] {msg}")
        for msg in w:
            print(f"WARN {msg}")
        print(
            f"mode {ctx.mode}; base {ctx.base[:12]}; {len(GATES)} gates; "
            f"FAIL {len(f)} / WARN {len(w)}"
        )
    return 1 if f else 0


def pins_mut(fn: Callable[[str], str]) -> Callable[[Ctx], Ctx]:
    def apply(c: Ctx) -> Ctx:
        pins = fn(c.pins)
        return dataclasses.replace(c, pins=pins, records=parse_records(pins))

    return apply


def src_mut(rel: str, fn: Callable[[str], str]) -> Callable[[Ctx], Ctx]:
    def apply(c: Ctx) -> Ctx:
        sources = {**c.sources, rel: fn(c.sources[rel])}
        forms = {k: parse_form(sources.get(KEYS[k], "")) for k in (*FORM_FILES, *EXTRA_FORMS)}
        return dataclasses.replace(c, sources=sources, forms=forms)

    return apply


def head_mut(key: str, fn: Callable[[str], str]) -> Callable[[Ctx], Ctx]:
    return lambda c: dataclasses.replace(c, head={**c.head, key: fn(c.head[key])})


def stale_records(c: Ctx) -> Ctx:
    return dataclasses.replace(
        c,
        mode="post-merge",
        merged_spec=c.spec,
        records={**c.records, "date checked": "2026-01-01"},
    )


MUTATIONS: list[tuple[str, Callable[[Ctx], Ctx]]] = [
    ("G01-FILLED", spec_mut(lambda s: s + "\n{{COUNT:zz}}\n")),
    (
        "G02-AUDIT",
        spec_mut(
            lambda s: re.sub(
                r"<!-- audit:fm\.rows=\d+ -->", "<!-- audit:fm.rows=99 -->", s, count=1
            )
        ),
    ),
    (
        "G03-CITE",
        pins_mut(
            lambda p: re.sub(
                r"^(story:4) [0-9a-f]{16}$", r"\1 0000000000000000", p, flags=re.MULTILINE
            )
        ),
    ),
    ("G04-PINS", spec_mut(lambda s: s + "\nSee `D01`:5.\n")),
    ("G05-VERBATIM", spec_mut(lambda s: _swap(s, '"Severity"', '"Priority level"'))),
    ("G06-SPEC", spec_mut(lambda s: set_cell(s, "Area", 3, "no / no"))),
    ("G06-SPEC", spec_mut(lambda s: set_cell(s, "Owner", 2, "same (spacing)"))),
    ("G07-LABEL", pins_mut(lambda p: _swap(p, "REC label qa present\n", ""))),
    (
        "G08-OPTION",
        spec_mut(
            lambda s: _swap(s, "FM-2 drift: option text (DF-3)", "FM-2 drift: option text (DF-1)")
        ),
    ),
    ("G09-FINDINGS", spec_mut(lambda s: set_cell(s, "DF-2", 2, "Severe"))),
    ("G09-FINDINGS", spec_mut(lambda s: set_cell(s, "DF-6", 2, "Minor"))),
    ("G10-PLATFORM", spec_mut(lambda s: set_cell(s, "PN-7", 5, "graded in §3"))),
    ("G11-GUARD", spec_mut(lambda s: set_cell(s, "GC-1", 5, "yes"))),
    ("G11-GUARD", spec_mut(lambda s: set_cell(s, "GC-2", 6, "yes"))),
    (
        "G12-MD",
        spec_mut(
            lambda s: _swap(s, "| GM-5 | `CODE_OF_CONDUCT.md`", "| GM-5 | `CODE_OF_CONDUCT.mdx`")
        ),
    ),
    ("G12-MD", spec_mut(lambda s: _swap(s, "audit:gm.agents.noprose=", "audit:gm.agents.steps="))),
    ("G13-ROUTE", spec_mut(lambda s: set_cell(s, "DF-1", 4, "an agent"))),
    ("G13-ROUTE", spec_mut(lambda s: _swap(s, "(E01-Q02, closed)", "(E01-Q02)"))),
    ("G14-HYGIENE", spec_mut(lambda s: s + "\n" + BANNED[0].upper() + "\n")),
    ("G15-SECRET", spec_mut(lambda s: s + "\nABCDEFGHABCDEFGH\n")),
    ("G16-SCOPE", lambda c: dataclasses.replace(c, changed=[*c.changed, KEYS["PRT"]])),
    ("G16-SCOPE", head_mut("story", lambda t: _swap(t, "label: Estimate", "label: Points"))),
    ("G17-IDS", spec_mut(lambda s: _swap(s, "| SC-3 ", "| SC-2 "))),
    ("G18-RULED", spec_mut(lambda s: _swap(s, f"| {RULED_STAMP} |", "| pending |"))),
    ("G18-RULED", spec_mut(lambda s: s + "\n<!-- BQ-05 -->\n")),
    (
        "G19-WALK",
        spec_mut(
            lambda s: _swap(s, "10. Record approval on #139.", "10. Record it.\n11. And more.")
        ),
    ),
    (
        "G20-FREEZE",
        lambda c: dataclasses.replace(c, merged_spec="| ST-99 | a merged row since |\n"),
    ),
    ("G21-SECURITY", spec_mut(lambda s: set_cell(s, "SC-7", 1, '"x"'))),
    ("G21-SECURITY", spec_mut(lambda s: set_cell(s, "SC-7", 1, "see `story`:14"))),
    ("G22-ANCHOR", spec_mut(lambda s: _swap(s, "`story`:14–23", "`story`:14–22"))),
    ("G22-ANCHOR", spec_mut(lambda s: _swap(s, "`PRT`:68–74", "`PRT`:68–73"))),
    ("G22-ANCHOR", spec_mut(lambda s: _swap(s, "`CHOOSER`:1 ", "`CHOOSER`:2 "))),
    (
        "G02-AUDIT",
        spec_mut(lambda s: re.sub(r"audit:gc\.next_yes=\d+", "audit:gc.next_yes=9", s, count=1)),
    ),
    (
        "G02-AUDIT",
        src_mut(KEYS["story"], lambda t: _swap(t, "Found a vulnerability?", "Found a problem?")),
    ),
    ("G02-AUDIT", spec_mut(lambda s: _swap(s, "audit:sc.extra_pair=0", "audit:sc.extra_pair=2"))),
    ("G11-GUARD", spec_mut(lambda s: set_cell(s, "GC-3", 5, "partly"))),
    ("G07-LABEL", spec_mut(lambda s: _swap(s, "applies `quarterly-ci-review`", "applies a label"))),
    ("G07-LABEL", stale_records),
    (
        "G07-LABEL",
        pins_mut(lambda p: _swap(p, "label type/story present", "label type/story absent")),
    ),
    ("G08-OPTION", head_mut("story", lambda t: _swap(t, '"1 point"', '"1"'))),
    ("G09-FINDINGS", spec_mut(lambda s: set_cell(s, "PT-2", 4, "Minor"))),
    ("G09-FINDINGS", spec_mut(lambda s: set_cell(s, "PT-5", 3, "accepted"))),
    ("G09-FINDINGS", spec_mut(lambda s: set_cell(s, "PT-3", 2, "a loose clause"))),
    ("G09-FINDINGS", spec_mut(lambda s: _swap(s, "(PT-4)", "(PT-0)"))),
    ("G09-FINDINGS", spec_mut(lambda s: _swap(s, "spec-update (DF-22)", "spec-update (DF-99)"))),
    ("G09-FINDINGS", spec_mut(lambda s: _swap(s, "drift (DF-12)", "defect (DF-12)"))),
    ("G23-LATER", spec_mut(lambda s: set_cell(s, "LC-1", 1, "`0000000000`"))),
    ("G24-STATUS", spec_mut(lambda s: _swap(s, "spec-update (DF-22)", "bogus (DF-22)"))),
    ("G24-STATUS", spec_mut(lambda s: set_cell(s, "WV-2", 3, "done"))),
]

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
