#!/usr/bin/env python3
"""E17-Q04 (#569) audit: the E17 regression pack against its specs, E17-D02's state matrix and `main`.

Standalone, offline, stdlib only; it runs under `python3 -I` and executes no repo code. It reads AS TEXT, at the
merge-base with `origin/main` (`git show`): E17-D02 section 2, `23` (the section 16 C-rules and its headings), the
CONSTITUTION, the user stories, the E17 threat model, `03`:373 and `_job-e2e.yml`:88. It reads the pack
(`qa/plans/e17-regression-pack.md`), the E17 specs, the unit and e2e files the ledger cites and the pins from the
working tree, and greps `origin/main` for the parked rows' probes.

Values. `{{SHA:base}}` and `{{COUNT:key}}` outside a code span are computed and `--fill` writes them as
`VALUE<!--=KIND:key-->`; `{{D02:n}}` becomes the matrix row's name; the block between the `q04-matrix` markers is
generated from the specs' `covers` annotations. `--check` re-derives each; no placeholder may remain.

Gates (one mutation each in `--self-test`, each caught by its own gate only):
  G-VALUES    the anchored base SHA (the merge-base in PR-1 mode; frozen post-merge) and the counts.
  G-CASES     sections A0 and A1 against the specs: every case once, its file, driver and pack status, and its
              C-rule, D02 row and story or AC cells equal to its `covers` annotation (BQ-07, BQ-14).
  G-CITE      every cited C-rule stands in `23` section 16, every section heading in `23`, every CONSTITUTION rule
              at its definition, every story and its scenario in `11`, every threat id in the E17 threat model.
  G-LEDGER    section B: rows 1 to 24 in order, each State cell the D02 row's name at the base, the status
              vocabulary, and the cases of a row equal to the A1 cases citing it, both ways (BQ-01).
  G-PARKED    every probe of a partial or parked row, and of section B2, is absent from its path at `origin/main`
              (a needle probe needs its path to exist there); a probe found means the row must be updated (BQ-03).
  G-UNIT      every `unit` or `e2e` cell names a file that exists and contains its quoted needle.
  G-MUTATION  one mutation line per non-named case; for the named rows, one line per marked assertion, and every
              assertion line of the named-row bodies carries its `// M-Nnn-k` mark (BQ-08).
  G-TAG       every case's test carries `@e17-regression`; the tag resolves to at least one spec; Q04-R01 alone
              carries `@e17-realtime` and lives in a `.nightly.ts` file; the F cases live in `.flagged.ts` files.
  G-RUNWHERE  section H: the where vocabulary, and no result but "not run" where nothing ran (BQ-11).
  G-OWNERRUN  section E: OR-1 to OR-5, a person (never an agent) per row, the status vocabulary (BQ-12, BQ-13).
  G-CARRY     the BQ-10 carry: `03`:373 and `_job-e2e.yml`:88 say, at the base, what the carry says they do.
  G-WAIVERS   axe waivers live in the pins file only, each with its ruling; `support.ts` reads them from there;
              `e2e/support/axe.ts` (`seriousAxe`) is untouched (BQ-06).
  G-MATRIX    the generated traceability block equals the derivation from the specs.
  G-RULED     the ruling id and every BQ-01 to BQ-14 cited in the pack.
  G-HYGIENE   no placeholder, no local path, agent name or URL, no closing keyword, none of the public-text words.
  G-SIGNOFF   post-merge mode: the sign-off draft lists the suites, the coverage, the defects by severity and an
              explicit decision line left for the signer; every owner-run row is run or waived.
  G-FROZEN    post-merge mode (the pack is on the merge-base): every case and ledger row of the first commit stands,
              and no row's status moves down (covered, partial, unit, parked).
  G-RULED-PIN a default-deny pin set over every unit of the pack (values cut out); only `--repin-ruled` writes it,
              keeping the ruled `axe-waiver` lines. Its findings print as NOTE while another gate FAILs.

Usage (from the repo root):
  python3 -I qa/plans/_tools/e17_q04_audit.py --check [--json] [--fill] [--post-merge]
  python3 -I qa/plans/_tools/e17_q04_audit.py --self-test
  python3 -I qa/plans/_tools/e17_q04_audit.py --repin-ruled
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HEAD_REF = "origin/main"
ISSUE = "569"
RULING_ID = "6556829275"
BQ_TOTAL = 14

PACK_REL = "qa/plans/e17-regression-pack.md"
TOOL_REL = "qa/plans/_tools/e17_q04_audit.py"
PIN_REL = "qa/plans/_tools/e17_q04_ruled_pins.txt"
E17 = "apps/web/e2e/e17"
SPECS = {
    "T": f"{E17}/transport-states.spec.ts",
    "N": f"{E17}/named-rows.spec.ts",
    "X": f"{E17}/accessibility.spec.ts",
    "F": f"{E17}/fault-channel.flagged.ts",
    "R": f"{E17}/realtime.nightly.ts",
}
NAMED_BODIES = f"{E17}/namedRows.ts"
SUPPORT_REL = f"{E17}/support.ts"
AXE_REL = "apps/web/e2e/support/axe.ts"
D02_REL = "docs/design/E17/E17-D02.md"
P23_REL = "docs/plan/23-ws-protocol.md"
P03_REL = "docs/plan/03-testing-strategy.md"
P11_REL = "docs/plan/11-user-stories.md"
CONST_REL = "CONSTITUTION.md"
TM_REL = "docs/security/threat-models/E17-ws-gateway.md"
JOB_REL = ".github/workflows/_job-e2e.yml"
CARRY = ((P03_REL, 373, "No automatic CI retries"), (JOB_REL, 88, "--retries=1"))

PACK_TAG = "@e17-regression"
REALTIME_TAG = "@e17-realtime"
PACK_STATUS = re.compile(r"candidate \([0-9]/10\)|in pack \(10/10\)")
LEDGER_STATUS = ("covered", "partial", "unit", "parked")
WHERE = re.compile(r"laptop headless shell|laptop node|CI nightly|not run \(.+\)")
RESULT = re.compile(r"\d+ passed, \d+ failed(; .+)?|not run")
OR_STATUS = re.compile(
    r"owner-run; not run|run \d{4}-\d\d-\d\d; notes on #569|waived by the owner on #569"
)
ASSERT = re.compile(r"\b(expect|patient|stillTheSameAnnouncement)\(")
MARK = re.compile(r"// (M-N\d\d-\d+)$")
AGENT_NAME = re.compile(r"\b[a-z]{2,4}-" + "worker" + r"-\d\b")
LOCAL_PATH = re.compile(r"/home/|/mnt/|/tmp/|[A-Z]:\\\\")
URL = re.compile(r"https?://")
CLOSING = re.compile(r"\b(close[sd]?|fix(e[sd])?|resolve[sd]?) #\d+", re.IGNORECASE)
_W = ("le" + "ak", "expo" + "sed", "by" + "pass", "expl" + "oit", "att" + "ack", "ora" + "cle",
      "rev" + "eal", "unbou" + "nded", "flo" + "od", "sta" + "ll", r"\bd" + r"os\b", "advi" + "sory",
      "gh" + "sa", "pre-" + "auth")  # fmt: skip
WORDS = re.compile("|".join(_W), re.IGNORECASE)
PLACEHOLDER = re.compile(r"\{\{([A-Z0-9]+):([^}]+)\}\}")
ANCHOR = re.compile(r"([^\s<|`(]+)<!--=([A-Z]+:[^>]+)-->")
GEN_BEGIN = "<!-- BEGIN GENERATED: q04-matrix -->"
GEN_END = "<!-- END GENERATED: q04-matrix -->"


# ---------------------------------------------------------------------------- git and files


def git_raw(*args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=False)
    except OSError:
        return None
    return r.stdout.decode("utf-8", "surrogateescape") if r.returncode == 0 else None


def show(rev: str, rel: str) -> str | None:
    return git_raw("show", f"{rev}:{rel}")


def merge_base() -> str | None:
    out = git_raw("merge-base", "HEAD", HEAD_REF)
    return out.strip() if out and re.fullmatch(r"[0-9a-f]{40}\s*", out) else None


def first_commit(rel: str) -> str | None:
    out = git_raw("log", "--diff-filter=A", "--format=%H", f"{HEAD_REF}", "--", rel)
    shas = [s for s in (out or "").split("\n") if s]
    return shas[-1] if shas else None


def read_raw(rel: str) -> str:
    with open(ROOT / rel, encoding="utf-8", newline="") as f:
        return f.read()


def read_opt(rel: str) -> str | None:
    return read_raw(rel) if (ROOT / rel).is_file() else None


def write_text(rel: str, text: str) -> None:
    with open(ROOT / rel, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def grep_main(needle: str, path: str) -> bool:
    out = git_raw("grep", "-l", "-F", "-e", needle, HEAD_REF, "--", path)
    return bool(out and out.strip())


def path_at_main(path: str) -> bool:
    out = git_raw("ls-tree", "--name-only", HEAD_REF, "--", path)
    return bool(out and out.strip())


# ---------------------------------------------------------------------------- text helpers


def norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def table(text: str, first: str, second: str) -> list[tuple[int, list[str]]]:
    """The body rows (line number, cells) of the table whose header starts `first | second`."""
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        if not ln.startswith("|"):
            continue
        head = split_row(ln)
        if len(head) >= 2 and head[0] == first and head[1] == second:
            rows: list[tuple[int, list[str]]] = []
            for j in range(i + 2, len(lines)):
                if not lines[j].startswith("|"):
                    break
                rows.append((j + 1, split_row(lines[j])))
            return rows
    return []


def without_code(text: str) -> str:
    return re.sub(r"`[^`\n]*`", "", text)


def unfill(text: str) -> str:
    """The text with every anchored value cut out and the generated block collapsed (what the pins hold)."""
    text = ANCHOR.sub(lambda m: "{{" + m.group(2) + "}}", text)
    return re.sub(
        re.escape(GEN_BEGIN) + r".*?" + re.escape(GEN_END), GEN_BEGIN, text, flags=re.DOTALL
    )


def cells(cell: str) -> list[str]:
    return [p.strip() for p in re.split(r";|,", cell) if p.strip()]


def code_spans(cell: str) -> list[str]:
    return re.findall(r"`([^`\n]*)`", cell)


# ---------------------------------------------------------------------------- the inputs


@dataclass(frozen=True)
class Texts:
    pack: str
    specs: dict[str, str]  # file letter -> text
    named: str  # namedRows.ts
    support: str
    pins: str
    base: str  # the merge-base (PR-1) or the recorded base (post-merge), full sha
    mb: str
    post: bool  # post-merge mode
    frozen: str | None  # the pack at its first commit on main, when it is on the merge-base
    d02_names: dict[int, str]  # matrix row -> name, at the base
    crules: frozenset[str]  # `23` section 16's C-rules at the base
    sections: frozenset[str]  # `23`'s numbered headings at the base ("10.3")
    const_rules: frozenset[str]  # CONSTITUTION rule ids at the base ("C-14.1")
    stories: dict[str, frozenset[str]]  # story id -> scenario names, at the base
    threats: frozenset[str]  # E17 threat model ids at the base
    carry_lines: dict[str, str]  # "rel:line" -> the line's text at the base
    files: dict[str, str | None]  # cited unit and e2e files, working tree
    present: frozenset[str]  # the probes found at `origin/main` ("needle@path" or "path@")
    axe_changed: bool  # `e2e/support/axe.ts` differs from the merge-base
    values: dict[str, str] = field(default_factory=dict)


def d02_names(text: str) -> dict[int, str]:
    """Section 2's rows: the name is the row's text up to its first explaining parenthesis."""
    out: dict[int, str] = {}
    sec = text.split("## 2. The state matrix", 1)[-1].split("\n## 3.", 1)[0]
    for ln in sec.split("\n"):
        m = re.match(r"\|\s*(\d+)\s*\|", ln)
        if not m:
            continue
        cell = split_row(ln)[1]
        name = cell
        for p in re.finditer(r" \(([^)]*)\)?", cell):
            inner = p.group(1)
            if "`" in inner or re.match(r"[A-Z0-9]", inner):
                name = cell[: p.start()]
                break
        out[int(m.group(1))] = name.strip()
    return out


def c_rules(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"^\| (C\d+)\s+\|", text, flags=re.MULTILINE))


def headings(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"^#{2,4} (\d+(?:\.\d+)*)\.? ", text, flags=re.MULTILINE))


def constitution(text: str) -> frozenset[str]:
    return frozenset(
        re.findall(r"\*\*(C-\d+\.\d+)\b", text)
        + re.findall(r"^\| (C-\d+\.\d+)", text, flags=re.MULTILINE)
    )


def stories(text: str) -> dict[str, frozenset[str]]:
    out: dict[str, frozenset[str]] = {}
    for part in re.split(r"^#### ", text, flags=re.MULTILINE)[1:]:
        m = re.match(r"(US-[A-Z]+-\d{3})\b", part)
        if m:
            out[m.group(1)] = frozenset(
                re.findall(r"^Scenario: (.+?)\s*$", part, flags=re.MULTILINE)
            )
    return out


def threat_ids(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"^\| (WS-[A-Z]\d\d) \|", text, flags=re.MULTILINE))


# ---------------------------------------------------------------------------- the specs


@dataclass(frozen=True)
class Case:
    cid: str  # "T03"
    letter: str  # the file letter
    titles: tuple[str, ...]
    covers: tuple[str, ...]


def test_blocks(text: str) -> list[tuple[str, str]]:
    """(title, body) per `test(` call; a loop's template title keeps its `${...}` parts."""
    starts = [m.start() for m in re.finditer(r"^\s*test\(`", text, flags=re.MULTILINE)]
    out: list[tuple[str, str]] = []
    for i, s in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        block = text[s:end]
        m = re.search(r"test\(`([^`]*)`", block)
        if m:
            out.append((m.group(1), block))
    return out


def covers_of(block: str, text: str) -> tuple[str, ...]:
    m = re.search(r"covers\(([^)]*)\)", block)
    if not m:
        return ()
    out: list[str] = []
    for arg in [a.strip() for a in m.group(1).split(",") if a.strip()]:
        if arg.startswith('"'):
            out.append(arg.strip('"'))
        elif arg.endswith(".row"):  # a loop's variable: every `row:` literal of the file
            out += re.findall(r'\brow: "([^"]+)"', text)
    return tuple(out)


def spec_cases(t: Texts) -> dict[str, Case]:
    cases: dict[str, Case] = {}
    for letter, text in t.specs.items():
        for title, block in test_blocks(text):
            m = re.match(r"Q04-([A-Z]\d\d) ", title)
            if not m:
                continue
            cid = m.group(1)
            old = cases.get(cid)
            cov = covers_of(block, text)
            if old is None:
                cases[cid] = Case(cid, letter, (title,), cov)
            else:
                cases[cid] = Case(
                    cid,
                    old.letter if old.letter == letter else "?",
                    old.titles + (title,),
                    old.covers,
                )
    return cases


def kinds(covers: tuple[str, ...]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {"rule": [], "row": [], "story": []}
    for c in covers:
        if c.startswith("D02-row-"):
            out["row"].append(c[len("D02-row-") :])
        elif re.fullmatch(r"C\d+|C-\d+\.\d+|§\d+(\.\d+)*", c):
            out["rule"].append(c)
        elif re.fullmatch(r"US-[A-Z]+-\d{3}#.+|AC-\d|WS-[A-Z]\d\d", c):
            out["story"].append(c.replace("#", " ").replace("AC-", "AC "))
    return out


# ---------------------------------------------------------------------------- the pack's tables


def a1(t: Texts) -> list[tuple[int, list[str]]]:
    return table(t.pack, "Case", "What a person sees")


def a0(t: Texts) -> list[tuple[int, list[str]]]:
    return table(t.pack, "Case", "What it shows")


def ledger(text: str) -> list[tuple[int, list[str]]]:
    return table(text, "Row", "State")


def b2(t: Texts) -> list[tuple[int, list[str]]]:
    return table(t.pack, "Id", "The parked half")


def mutations(t: Texts) -> list[tuple[int, list[str]]]:
    return table(t.pack, "Mutation", "Case")


def owner_rows(t: Texts) -> list[tuple[int, list[str]]]:
    return table(t.pack, "Row", "Session")


def run_rows(t: Texts) -> list[tuple[int, list[str]]]:
    return table(t.pack, "Run", "What")


def case_id(cell: str) -> str:
    m = re.fullmatch(r"Q04-([A-Z]\d\d)", cell)
    return m.group(1) if m else ""


def probes(cell: str) -> list[tuple[str, str]]:
    """`needle` in `path` (needle, path) and path `path` ("", path), in cell order."""
    out: list[tuple[str, str]] = []
    for part in cell.split(";"):
        p = part.strip()
        m = re.fullmatch(r"`([^`]+)` in `([^`]+)`", p)
        n = re.fullmatch(r"path `([^`]+)`", p)
        if m:
            out.append((m.group(1), m.group(2)))
        elif n:
            out.append(("", n.group(1)))
        elif p:
            out.append(("?", p))
    return out


def elsewhere(cell: str) -> tuple[str, str, str] | None:
    m = re.fullmatch(r"(unit|e2e) `([^`]+)` \"([^\"]+)\"", cell)
    return (m.group(1), m.group(2), m.group(3)) if m else None


def all_probes(t: Texts) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for _, r in ledger(t.pack):
        if len(r) >= 6:
            out += probes(r[5])
    for _, r in b2(t):
        if len(r) >= 3:
            out += probes(r[2])
    return out


def probe_key(needle: str, path: str) -> str:
    return f"{needle}@{path}"


# ---------------------------------------------------------------------------- values and the matrix


def ledger_counts(t: Texts) -> dict[str, int]:
    out = dict.fromkeys(LEDGER_STATUS, 0)
    for _, r in ledger(t.pack):
        if len(r) >= 3 and r[2] in out:
            out[r[2]] += 1
    return out


def compute(t: Texts) -> dict[str, str]:
    v = {"SHA:base": t.base[:10], "COUNT:cases": str(len(a1(t)) + len(a0(t)))}
    for k, n in ledger_counts(t).items():
        v[f"COUNT:ledger.{k}"] = str(n)
    for n, name in t.d02_names.items():
        v[f"D02:{n}"] = name
    return v


def matrix(t: Texts) -> str:
    """Story scenario or AC -> the cases citing it, from the `covers` annotations."""
    by: dict[str, set[str]] = {}
    for c in spec_cases(t).values():
        if c.cid.startswith("S"):
            continue
        for s in kinds(c.covers)["story"]:
            by.setdefault(s, set()).add(f"Q04-{c.cid}")
    rows = ["| Story scenario or AC | Cases |", "| --- | --- |"]
    for key in sorted(by, key=lambda k: (not k.startswith("US"), k)):
        rows.append(f"| {key} | {', '.join(sorted(by[key]))} |")
    return "\n".join(rows)


def generated(text: str) -> str | None:
    if GEN_BEGIN not in text or GEN_END not in text:
        return None
    return text.split(GEN_BEGIN, 1)[1].split(GEN_END, 1)[0].strip("\n")


def fill(text: str, values: dict[str, str], block: str) -> tuple[str, list[str]]:
    missing: list[str] = []

    def one(m: re.Match[str]) -> str:
        key = f"{m.group(1)}:{m.group(2)}"
        if key == "MATRIX:covers":
            return block
        val = values.get(key)
        if val is None:
            missing.append(key)
            return m.group(0)
        return val if key.startswith("D02:") else f"{val}<!--={key}-->"

    out = PLACEHOLDER.sub(one, text)
    if GEN_BEGIN in out and GEN_END in out:
        head, rest = out.split(GEN_BEGIN, 1)
        _, tail = rest.split(GEN_END, 1)
        out = f"{head}{GEN_BEGIN}\n{block}\n{GEN_END}{tail}"
    for value, key in ANCHOR.findall(out):  # a value that moved since the last fill
        if key in values and values[key] != value:
            out = out.replace(f"{value}<!--={key}-->", f"{values[key]}<!--={key}-->")
    return out, missing


# ---------------------------------------------------------------------------- findings


@dataclass(frozen=True)
class Finding:
    level: str
    gate: str
    msg: str


def one(gate: str, problems: list[str], level: str = "FAIL") -> list[Finding]:
    return [Finding(level, gate, p) for p in problems]


def g_values(t: Texts) -> list[Finding]:
    bad: list[str] = []
    seen: set[str] = set()
    for value, key in ANCHOR.findall(without_code(t.pack)):
        seen.add(key)
        want = t.values.get(key)
        if want is None:
            bad.append(f"`{key}` is anchored, but the tool derives no such value")
        elif key == "SHA:base" and t.post:
            if not t.base.startswith(value):
                bad.append(f"the frozen base {value} does not resolve")
        elif want != value:
            bad.append(f"`{key}` reads {value}; the tool derives {want}")
    for key in ("SHA:base", "COUNT:cases", *(f"COUNT:ledger.{k}" for k in LEDGER_STATUS)):
        if key not in seen:
            bad.append(f"`{key}` is not anchored in the pack")
    return one("G-VALUES", bad)


def g_cases(t: Texts) -> list[Finding]:
    bad: list[str] = []
    specs = spec_cases(t)
    rows = {case_id(r[0]): (ln, r) for ln, r in a1(t)}
    prem = {case_id(r[0]): (ln, r) for ln, r in a0(t)}
    if len(rows) != len(a1(t)) or len(prem) != len(a0(t)):
        bad.append("a case id is listed twice, or is not of the form Q04-Xnn")
    for cid, c in sorted(specs.items()):
        if cid == "R01":
            continue
        where = prem if cid.startswith("S") else rows
        if cid not in where:
            bad.append(
                f"Q04-{cid} has a test but no row in section {'A0' if cid.startswith('S') else 'A1'}"
            )
        if c.letter == "?":
            bad.append(f"Q04-{cid}'s tests are in more than one file")
    for cid, (ln, r) in list(rows.items()) + list(prem.items()):
        found = specs.get(cid)
        if found is None:
            bad.append(f"pack:{ln} Q04-{cid} has no test")
            continue
        if len(r) < (8 if cid in rows else 4) or r[2] != found.letter:
            bad.append(
                f"pack:{ln} Q04-{cid}'s file cell reads {r[2] if len(r) > 2 else '?'}; its tests are in {c.letter}"
            )
            continue
        if cid in prem:
            continue
        k = kinds(found.covers)
        if sorted(cells(r[3])) != sorted(k["rule"]):
            bad.append(
                f"pack:{ln} Q04-{cid} C-rule {r[3]!r}; its covers say {', '.join(k['rule'])}"
            )
        if sorted(cells(r[4]), key=int if all(x.isdigit() for x in cells(r[4])) else str) != sorted(
            k["row"], key=int
        ):
            bad.append(
                f"pack:{ln} Q04-{cid} D02 row {r[4]!r}; its covers say {', '.join(k['row'])}"
            )
        if sorted(cells(r[5])) != sorted(k["story"]):
            bad.append(
                f"pack:{ln} Q04-{cid} story {r[5]!r}; its covers say {'; '.join(k['story'])}"
            )
        driver = "fault" if found.letter == "F" else "harness"
        if r[6] != driver:
            bad.append(f"pack:{ln} Q04-{cid} driver {r[6]!r}; its file says {driver}")
        if not PACK_STATUS.fullmatch(r[7]):
            bad.append(f"pack:{ln} Q04-{cid} pack status {r[7]!r} is not in the vocabulary")
        if not k["rule"] or not k["row"] or not k["story"]:
            bad.append(f"Q04-{cid}'s covers lack a C-rule, a D02 row or a story or AC (BQ-07)")
    return one("G-CASES", bad)


def g_cite(t: Texts) -> list[Finding]:
    bad: list[str] = []
    for c in spec_cases(t).values():
        for x in c.covers:
            if re.fullmatch(r"C\d+", x) and x not in t.crules:
                bad.append(f"Q04-{c.cid} cites {x}, which is not a `23` section 16 C-rule")
            elif x.startswith("§") and x[1:] not in t.sections:
                bad.append(f"Q04-{c.cid} cites {x}, which is no `23` heading")
            elif x.startswith("C-") and x not in t.const_rules:
                bad.append(f"Q04-{c.cid} cites {x}, which the CONSTITUTION does not define")
            elif x.startswith("US-"):
                sid, _, scen = x.partition("#")
                if scen not in t.stories.get(sid, frozenset()):
                    bad.append(f"Q04-{c.cid} cites {x}, which is no scenario of {sid} in `11`")
            elif x.startswith("WS-") and x not in t.threats:
                bad.append(f"Q04-{c.cid} cites {x}, which is no row of the E17 threat model")
            elif x.startswith("D02-row-") and int(x[len("D02-row-") :]) not in t.d02_names:
                bad.append(f"Q04-{c.cid} cites {x}, which E17-D02 section 2 does not have")
            elif re.fullmatch(r"AC-\d", x) and not 1 <= int(x[3:]) <= 6:
                bad.append(f"Q04-{c.cid} cites {x}; the ticket has AC 1 to 6")
    return one("G-CITE", bad)


ORDER = {s: i for i, s in enumerate(LEDGER_STATUS)}


def g_ledger(t: Texts) -> list[Finding]:
    bad: list[str] = []
    rows = ledger(t.pack)
    if [r[0] for _, r in rows] != [str(n) for n in range(1, 25)]:
        bad.append("section B does not hold rows 1 to 24 in order")
    citing: dict[str, set[str]] = {}
    for ln, r in a1(t):
        for n in cells(r[4]) if len(r) > 4 else []:
            citing.setdefault(n, set()).add(r[0])
    for ln, r in rows:
        if len(r) != 7:
            bad.append(f"pack:{ln} has {len(r)} cells, not 7")
            continue
        n, state, status, cases, other, probe, owner = r
        want = t.d02_names.get(int(n)) if n.isdigit() else None
        if want is None or norm(state) != norm(want):
            bad.append(f"pack:{ln} row {n}'s State is not E17-D02's name for it")
        if status not in ORDER:
            bad.append(f"pack:{ln} row {n}'s status {status!r} is not in the vocabulary")
            continue
        listed = set(cells(cases))
        if listed != citing.get(n, set()):
            bad.append(
                f"pack:{ln} row {n} lists {sorted(listed)}; the A1 cases citing it are {sorted(citing.get(n, set()))}"
            )
        if status in ("covered", "partial") and not listed:
            bad.append(f"pack:{ln} row {n} is {status} with no case")
        if status in ("unit", "parked") and listed:
            bad.append(f"pack:{ln} row {n} is {status} but lists cases")
        if status == "unit" and elsewhere(other) is None:
            bad.append(f"pack:{ln} row {n} is unit with no unit file")
        if status in ("partial", "parked") and (not probes(probe) or not owner):
            bad.append(f"pack:{ln} row {n} is {status} with no probe or no owner")
        if status in ("covered", "unit") and (probe or owner):
            bad.append(f"pack:{ln} row {n} is {status} but names a parked half")
        if AGENT_NAME.search(owner):
            bad.append(f"pack:{ln} row {n}'s owner is an agent, not a ticket and its area")
    return one("G-LEDGER", bad)


def g_parked(t: Texts) -> list[Finding]:
    bad: list[str] = []
    for needle, path in all_probes(t):
        if needle == "?":
            bad.append(f"a probe cell part {path!r} is neither `needle` in `path` nor path `path`")
        elif probe_key(needle, path) in t.present:
            what = f"`{needle}` is in `{path}`" if needle else f"`{path}` exists"
            bad.append(
                f"at {HEAD_REF} {what}: the surface is built, so the row is no longer parked"
            )
        elif needle and probe_key("", path) not in t.present:
            bad.append(f"the probe path `{path}` does not exist at {HEAD_REF}: a vacuous probe")
    return one("G-PARKED", bad)


def g_unit(t: Texts) -> list[Finding]:
    bad: list[str] = []
    for ln, r in ledger(t.pack):
        e = elsewhere(r[4]) if len(r) > 4 and r[4] else None
        if len(r) > 4 and r[4] and e is None:
            bad.append(f'pack:{ln} Elsewhere {r[4]!r} is not unit|e2e `file` "needle"')
        if e is None:
            continue
        body = t.files.get(e[1])
        if body is None:
            bad.append(f"pack:{ln} {e[1]} does not exist")
        elif e[2] not in body:
            bad.append(f"pack:{ln} {e[1]} does not contain {e[2]!r}")
    return one("G-UNIT", bad)


def marks(text: str) -> tuple[list[str], list[str]]:
    """The `// M-Nnn-k` marks of a file, and its assertion lines that carry none."""
    found: list[str] = []
    unmarked: list[str] = []
    for i, ln in enumerate(text.split("\n"), 1):
        s = ln.strip()
        if s.startswith(("//", "*", "/**", "import")) or "expect.configure" in s:
            continue
        m = MARK.search(s)
        if m:
            found.append(m.group(1))
        elif ASSERT.search(s):
            unmarked.append(f"{i}: {s[:60]}")
    return found, unmarked


def g_mutation(t: Texts) -> list[Finding]:
    bad: list[str] = []
    rows = mutations(t)
    ids = [r[0] for _, r in rows]
    if len(set(ids)) != len(ids):
        bad.append("a mutation id is listed twice")
    for ln, r in rows:
        if len(r) != 3 or not r[2] or case_id(r[1]) == "":
            bad.append(f"pack:{ln} is not a mutation line (id, case, change)")
            continue
        if not (r[0] == f"M-{case_id(r[1])}" or r[0].startswith(f"M-{case_id(r[1])}-")):
            bad.append(f"pack:{ln} {r[0]} does not belong to {r[1]}")
    for _, r in a1(t):
        cid = case_id(r[0])
        if cid.startswith("N"):
            continue
        if f"M-{cid}" not in ids:
            bad.append(f"Q04-{cid} has no mutation line")
    named: list[str] = []
    for label, text in (("namedRows.ts", t.named), ("named-rows.spec.ts", t.specs.get("N", ""))):
        found, unmarked = marks(text)
        named += found
        bad += [f"{label}:{u} is an assertion with no mutation mark" for u in unmarked]
    if sorted(named) != sorted(i for i in ids if re.fullmatch(r"M-N\d\d-\d+", i)):
        bad.append("the named rows' assertion marks and the pack's M-Nnn-k lines differ")
    return one("G-MUTATION", bad)


def g_tag(t: Texts) -> list[Finding]:
    bad: list[str] = []
    tagged = 0
    for letter, text in t.specs.items():
        for title, _ in test_blocks(text):
            realtime = title.startswith("Q04-R01 ")
            if realtime and (letter != "R" or not title.endswith("${REALTIME}")):
                bad.append("Q04-R01 is not alone in a `.nightly.ts` file with `@e17-realtime`")
            if not realtime and not title.endswith("${PACK}"):
                bad.append(f"{title[:40]!r} does not carry the pack tag")
            if not realtime and letter == "R":
                bad.append(f"{title[:40]!r} is in the real-time lane")
            tagged += not realtime
    if (
        tagged == 0
        or f'PACK = "{PACK_TAG}"' not in t.support
        or f'REALTIME = "{REALTIME_TAG}"' not in t.support
    ):
        bad.append("the pack tag resolves to no spec, or `support.ts` does not define the two tags")
    if any(
        re.match(r"Q04-F", title) for _, text in t.specs.items() for title, _ in test_blocks(text)
    ) and any(title.startswith("Q04-F") for title, _ in test_blocks(t.specs.get("T", ""))):
        bad.append("an F case is outside the flagged lane")
    return one("G-TAG", bad)


def g_runwhere(t: Texts) -> list[Finding]:
    bad: list[str] = []
    rows = run_rows(t)
    if not rows:
        bad.append("section H has no run record")
    for ln, r in rows:
        if len(r) != 4:
            bad.append(f"pack:{ln} is not a run row (run, what, where, result)")
            continue
        if not WHERE.fullmatch(r[2]):
            bad.append(f"pack:{ln} where {r[2]!r} is not in the vocabulary")
        if not RESULT.fullmatch(r[3]):
            bad.append(f"pack:{ln} result {r[3]!r} is not in the vocabulary")
        if r[2].startswith("not run") != (r[3] == "not run"):
            bad.append(
                f"pack:{ln} says {r[3]!r} where it says {r[2]!r}: nothing says passed that was not run"
            )
    return one("G-RUNWHERE", bad)


def g_ownerrun(t: Texts) -> list[Finding]:
    bad: list[str] = []
    rows = owner_rows(t)
    if [r[0] for _, r in rows] != [f"OR-{n}" for n in range(1, 6)]:
        bad.append("section E does not hold OR-1 to OR-5 in order")
    for ln, r in rows:
        if (
            len(r) != 4
            or not r[2]
            or AGENT_NAME.search(r[2])
            or re.search(r"\bagent\b", r[2], re.IGNORECASE)
        ):
            bad.append(f"pack:{ln} names no person to run it, or names an agent")
        elif not OR_STATUS.fullmatch(r[3]):
            bad.append(f"pack:{ln} status {r[3]!r} is not in the vocabulary")
    return one("G-OWNERRUN", bad)


def g_carry(t: Texts) -> list[Finding]:
    bad: list[str] = []
    gaps = {r[0]: r[1] for _, r in table(t.pack, "Id", "Gap") if len(r) > 1}
    carry = next((g for g in gaps.values() if "BQ-10 carry" in g), "")
    for rel, line, says in CARRY:
        if f"`{rel}`:{line}" not in carry:
            bad.append(f"the BQ-10 carry does not cite `{rel}`:{line}")
        if says not in t.carry_lines.get(f"{rel}:{line}", ""):
            bad.append(
                f"{rel}:{line} at the base does not say {says!r}: the carry cites a moved line"
            )
    return one("G-CARRY", bad)


def g_waivers(t: Texts) -> list[Finding]:
    bad: list[str] = []
    for ln in t.pins.split("\n"):
        if ln.startswith("axe-waiver"):
            parts = ln.split("\t")
            if (
                len(parts) != 3
                or not re.fullmatch(r"[a-z0-9-]+", parts[1])
                or not re.search(r"\d{6,}", parts[2])
            ):
                bad.append(f"the waiver line {ln!r} lacks a rule id or its ruling")
    if (
        "PINS_REL" not in t.support
        or "axe-waiver\\t" not in t.support
        or "AXE_WAIVERS" in t.support
    ):
        bad.append("`support.ts` does not read its waivers from the pins file alone")
    if (
        "withTags([...AXE_GATE_TAGS])" not in t.support
        or ".filter((v) => !waived.includes(v.id))" not in t.support
    ):
        bad.append(
            "`strictAxe` is not the gate's tagged scan with only the ruled waivers taken out"
        )
    if t.axe_changed:
        bad.append("`e2e/support/axe.ts` (`seriousAxe`) changed; it stays as it is (BQ-06)")
    return one("G-WAIVERS", bad)


def g_matrix(t: Texts) -> list[Finding]:
    got = generated(t.pack)
    if got is None:
        return one("G-MATRIX", ["the pack has no generated traceability block"])
    if "{{MATRIX:covers}}" in got:
        return one("G-MATRIX", ["the traceability block is not filled (run --check --fill)"])

    def rows(block: str) -> list[list[str]]:  # cell by cell: prettier pads a table, the cells stay
        return [
            split_row(ln) for ln in block.split("\n") if ln.strip() and not set(ln) <= set("|- ")
        ]

    same = rows(got) == rows(matrix(t))
    return one(
        "G-MATRIX", [] if same else ["the traceability block differs from the specs' covers"]
    )


def g_ruled(t: Texts) -> list[Finding]:
    bad: list[str] = []
    if f"Ruling of record: {RULING_ID}" not in t.pack:
        bad.append(f"the pack does not name the ruling of record {RULING_ID}")
    for n in range(1, BQ_TOTAL + 1):
        if f"BQ-{n:02d}" not in t.pack:
            bad.append(f"BQ-{n:02d} is cited nowhere in the pack")
    return one("G-RULED", bad)


def g_hygiene(t: Texts) -> list[Finding]:
    bad: list[str] = []
    docs = {
        "pack": t.pack,
        **{f"spec {k}": v for k, v in t.specs.items()},
        "namedRows": t.named,
        "support": t.support,
    }
    for doc, text in docs.items():
        prose = without_code(text) if doc == "pack" else text
        for i, ln in enumerate(prose.split("\n"), 1):
            for rx, what in ((LOCAL_PATH, "a local path"), (AGENT_NAME, "an agent name"), (URL, "a URL"),
                             (WORDS, "a public-text word"), (CLOSING, "a closing keyword")):  # fmt: skip
                if rx.search(ln):
                    bad.append(f"{doc}:{i} carries {what}")
        if doc == "pack" and PLACEHOLDER.search(text):
            bad.append("the pack has an unfilled placeholder (run --check --fill)")
    return one("G-HYGIENE", bad)


SIGNOFF_HEAD = "## I. Sign-off"
SIGNOFF_LINES = (
    re.compile(r"^Suites run: .+", re.MULTILINE),
    re.compile(r"^Coverage: .+", re.MULTILINE),
    re.compile(r"^Defects by severity: P0 \d+, P1 \d+, P2 \d+, P3 \d+\.?$", re.MULTILINE),
    re.compile(r"^E17-D04 verdict: #408 .+", re.MULTILINE),
    re.compile(
        r"^Decision: _{3,} \(accept or reject\), signed by _{3,} on _{3,}\.?$", re.MULTILINE
    ),
)


def g_signoff(t: Texts) -> list[Finding]:
    if not t.post:
        return []
    bad: list[str] = []
    body = t.pack.split(SIGNOFF_HEAD, 1)[1] if SIGNOFF_HEAD in t.pack else ""
    if not body:
        bad.append("post-merge mode, and the pack has no sign-off draft")
    for rx in SIGNOFF_LINES:
        if body and not rx.search(body):
            bad.append(f"the sign-off draft lacks a line matching {rx.pattern!r}")
    for ln, r in owner_rows(t):
        if len(r) == 4 and r[3] == "owner-run; not run":
            bad.append(f"pack:{ln} {r[0]} is neither run nor waived")
    return one("G-SIGNOFF", bad)


def g_frozen(t: Texts) -> list[Finding]:
    if t.frozen is None:
        return []
    bad: list[str] = []
    now = {r[0] for _, r in a1(t)}
    for _, r in table(t.frozen, "Case", "What a person sees"):
        if r[0] not in now:
            bad.append(f"{r[0]} stood in the first commit and is gone")
    was = {r[0]: r[2] for _, r in ledger(t.frozen) if len(r) > 2}
    for _, r in ledger(t.pack):
        old = was.get(r[0])
        if old in ORDER and len(r) > 2 and r[2] in ORDER and ORDER[r[2]] > ORDER[old]:
            bad.append(f"ledger row {r[0]} moved down from {old} to {r[2]}")
    return one("G-FROZEN", bad)


# ---------------------------------------------------------------------------- pins

Unit = tuple[str, str, str]


def units(t: Texts) -> list[Unit]:
    """(region, location, normalised text) per line of the pack, values cut out, the generated block collapsed."""
    out: list[Unit] = []
    region = "(top)"
    seen: dict[str, int] = {}
    for ln in unfill(t.pack).split("\n"):
        if not ln.strip():
            continue
        if ln.startswith("#"):
            region = norm(ln.lstrip("#"))
        if ln.startswith("|"):
            first = split_row(ln)[0]
            if set(first) <= set("- "):
                continue
            key = f"{region}|{first}"
        else:
            key = f"{region}|p"
        seen[key] = seen.get(key, 0) + 1
        out.append((f"pack:{key}#{seen[key]}", sha12(norm(ln)), norm(ln)[:80]))
    return out


def write_pins(t: Texts) -> str:
    us = units(t)
    ruled = [ln for ln in t.pins.split("\n") if ln.startswith("axe-waiver\t")]
    head = (
        f"# E17-Q04 pins: {len(us)} units of the pack (region|first cell#n, sha12 of the normalised line, its "
        "first 80 characters); values cut out, the generated block collapsed.\n"
        "# Written by `--repin-ruled` only; `--check` reads it (G-RULED-PIN). Never hand-edit the units.\n"
        "# Ruled axe waivers (BQ-06): `axe-waiver<TAB>rule-id<TAB>ruling`, kept by a repin; none is ruled.\n"
    )
    return head + "".join(r + "\n" for r in ruled) + "".join("\t".join(u) + "\n" for u in us)


def parse_pins(text: str) -> list[Unit]:
    out: list[Unit] = []
    for ln in text.split("\n"):
        parts = ln.split("\t")
        if ln.startswith("pack:") and len(parts) == 3:
            out.append((parts[0], parts[1], parts[2]))
    return out


def g_ruled_pin(t: Texts) -> list[Finding]:
    bad: list[str] = []
    was = {u[0]: u[1] for u in parse_pins(t.pins)}
    now = {u[0]: (u[1], u[2]) for u in units(t)}
    if not was:
        bad.append("the pins file holds no units (run --repin-ruled)")
    for k, (h, txt) in now.items():
        if k not in was:
            bad.append(f"unpinned unit {k[-60:]}: {txt[:40]!r}")
        elif was[k] != h:
            bad.append(f"changed unit {k[-60:]}: {txt[:40]!r}")
    for k in was:
        if k not in now:
            bad.append(f"deleted unit {k[-60:]}")
    return one("G-RULED-PIN", bad)


# ---------------------------------------------------------------------------- the audit

GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_values, g_cases, g_cite, g_ledger, g_parked, g_unit, g_mutation, g_tag, g_runwhere,
    g_ownerrun, g_carry, g_waivers, g_matrix, g_ruled, g_hygiene, g_signoff, g_frozen,
)  # fmt: skip


def gate_name(g: Callable[[Texts], list[Finding]]) -> str:
    return "G-" + g.__name__[2:].upper().replace("_", "-")


def audit(t: Texts) -> list[Finding]:
    found: list[Finding] = []
    for g in GATES:
        found += g(t)
    pins = g_ruled_pin(t)
    if any(f.level == "FAIL" for f in found):
        pins = [replace(f, level="NOTE") for f in pins]
    return found + pins


def load(force_post: bool = False) -> Texts:
    mb = merge_base()
    if mb is None:
        raise SystemExit(f"`git merge-base HEAD {HEAD_REF}` does not resolve")
    pack = read_raw(PACK_REL)
    on_base = show(mb, PACK_REL) is not None
    post = force_post or on_base or SIGNOFF_HEAD in pack
    base = mb
    m = re.search(r"([0-9a-f]{10})<!--=SHA:base-->", pack)
    if post and m:
        base = (
            git_raw("rev-parse", "--verify", f"{m.group(1)}^{{commit}}") or ""
        ).strip() or m.group(1)
    first = first_commit(PACK_REL) if on_base else None
    frozen = show(first, PACK_REL) if first else None

    def at(rel: str) -> str:
        text = show(base, rel)
        if text is None:
            raise SystemExit(f"{rel} is missing at the base {base[:10]}")
        return text

    lines = {f"{rel}:{n}": (at(rel).split("\n") + [""] * n)[n - 1] for rel, n, _ in CARRY}
    texts = {k: read_raw(v) for k, v in SPECS.items()}
    t = Texts(pack, texts, read_raw(NAMED_BODIES), read_raw(SUPPORT_REL), read_opt(PIN_REL) or "", base, mb,
              post, frozen, d02_names(at(D02_REL)), c_rules(at(P23_REL)), headings(at(P23_REL)),
              constitution(at(CONST_REL)), stories(at(P11_REL)), threat_ids(at(TM_REL)), lines, {},
              frozenset(), git_raw("diff", "--quiet", mb, "--", AXE_REL) is None)  # fmt: skip
    files = {e[1]: read_opt(e[1]) for _, r in ledger(pack) if len(r) > 4 and (e := elsewhere(r[4]))}
    present: set[str] = set()
    for needle, path in all_probes(t):
        if needle and needle != "?" and grep_main(needle, path):
            present.add(probe_key(needle, path))
        if needle != "?" and path_at_main(path):
            present.add(probe_key("", path))
    t = replace(t, files=files, present=frozenset(present))
    return replace(t, values=compute(t))


# ---------------------------------------------------------------------------- self-test


@dataclass(frozen=True)
class Mutation:
    gate: str
    what: str
    apply: Callable[[Texts], Texts]


def flex(old: str) -> re.Pattern[str]:
    """`old` with every run of spaces matching any run of spaces (prettier pads the tables)."""
    return re.compile(r"\s+".join(re.escape(p) for p in old.split(" ") if p != ""))


def subst(old: str, new: str, where: str = "pack") -> Callable[[Texts], Texts]:
    def swap(text: str, label: str) -> str:
        m = flex(old).search(text)
        if not m:
            raise SystemExit(f"self-test: {label} lacks {old[:60]!r}")
        return text[: m.start()] + new + text[m.end() :]

    def f(t: Texts) -> Texts:
        if where.startswith("spec:"):
            letter = where[5:]
            return replace(t, specs={**t.specs, letter: swap(t.specs[letter], f"spec {letter}")})
        return replace(t, pack=swap(t.pack, "pack"))

    return f


def recompute(f: Callable[[Texts], Texts]) -> Callable[[Texts], Texts]:
    def g(t: Texts) -> Texts:
        u = f(t)
        return replace(u, values=compute(u))

    return g


def with_(**kw: object) -> Callable[[Texts], Texts]:
    return lambda t: replace(t, **kw)  # type: ignore[arg-type]  # a mutation sets a field of its own type


def row_of(t: Texts, first: str) -> str:
    return next(ln for ln in t.pack.split("\n") if re.match(rf"\|\s*{re.escape(first)}\s*\|", ln))


MUTATIONS = (
    Mutation("G-VALUES", "a count anchor off by one",
             lambda t: subst(next(f"{v}<!--=COUNT:cases-->" for v, k in ANCHOR.findall(t.pack) if k == "COUNT:cases"),
                             "99<!--=COUNT:cases-->")(t)),
    Mutation("G-CASES", "T02's story cell names another scenario of the same story",
             subst("| US-MKT-005 Subscribed |", "| US-MKT-005 Reconnect |")),
    Mutation("G-CITE", "`23` loses the C-rule T11 cites", lambda t: replace(t, crules=t.crules - {"C4"})),
    Mutation("G-LEDGER", "row 4 lists a case that does not cite it",
             subst("| covered | Q04-T11 |", "| covered | Q04-T11, Q04-T02 |")),
    Mutation("G-PARKED", "main gains row 19's surface",
             lambda t: replace(t, present=t.present | {probe_key("Connection unstable", "apps/web/src")})),
    Mutation("G-UNIT", "row 7's unit needle is not in its file", subst('"OFFLINE_COPY"', '"OFFLINE_COPY_X"')),
    Mutation("G-MUTATION", "a case loses its mutation line",
             lambda t: subst(row_of(t, "M-T11") + "\n", "")(t)),
    Mutation("G-TAG", "a test loses the pack tag",
             subst("live: no region, no announcement, one socket ${PACK}", "live: no region, no announcement, one socket", "spec:T")),
    Mutation("G-RUNWHERE", "a row says passed where nothing ran",
             lambda t: subst(row_of(t, "H1"), re.sub(r"\|\s*laptop headless shell\s*\|", "| not run (no browser) |", row_of(t, "H1")))(t)),
    Mutation("G-OWNERRUN", "OR-2 claims a session in a word outside the vocabulary",
             lambda t: subst(row_of(t, "OR-2"), row_of(t, "OR-2").replace("owner-run; not run", "done"))(t)),
    Mutation("G-CARRY", "`03`:373 no longer says what the carry cites",
             lambda t: replace(t, carry_lines={**t.carry_lines, f"{P03_REL}:373": "moved"})),
    Mutation("G-WAIVERS", "a waiver with no ruling", lambda t: replace(t, pins="axe-waiver\tcolor-contrast\t\n" + t.pins)),
    Mutation("G-MATRIX", "the generated block is edited by hand", subst("| AC 4 | Q04-X01", "| AC 4 | Q04-X09")),
    Mutation("G-RULED", "the ruling id is mistyped", subst(f"Ruling of record: {RULING_ID}", "Ruling of record: 6556829276")),
    Mutation("G-HYGIENE", "a local path in the prose", subst("This pack holds what", "This pack (in /home/x) holds what")),
    Mutation("G-SIGNOFF", "post-merge mode with no sign-off draft", with_(post=True)),
    Mutation("G-FROZEN", "a case of the first commit is gone",
             lambda t: replace(t, frozen=t.pack.replace(row_of(t, "Q04-T02"), row_of(t, "Q04-T02") + "\n" + row_of(t, "Q04-T02").replace("Q04-T02", "Q04-T98")))),
    Mutation("G-RULED-PIN", "an unpinned word in the prose", subst("This pack holds what", "This page holds what")),
)  # fmt: skip


def selftest() -> tuple[bool, list[str]]:
    t0 = time.perf_counter()
    base = load()
    before = (base.pack, read_opt(PIN_REL))
    fails = [f for f in audit(base) if f.level == "FAIL"]
    out = [f"self-test: baseline {len(fails)} FAIL"]
    ok = not fails
    out += [f"  baseline {f.gate}: {f.msg}" for f in fails]
    hit: set[str] = set()
    for i, m in enumerate(MUTATIONS, 1):
        got = sorted({f.gate for f in audit(recompute(m.apply)(base)) if f.level == "FAIL"})
        good = got == [m.gate]
        ok &= good
        if good:
            hit.add(m.gate)
        out.append(
            f"{'ok  ' if good else 'FAIL'} M-{i} {m.gate}: {m.what} -> {', '.join(got) or 'none'}"
        )
    every = {gate_name(g) for g in GATES} | {"G-RULED-PIN"}
    missed = sorted(every - hit)
    ok &= not missed
    restored = (read_raw(PACK_REL), read_opt(PIN_REL)) == before
    ok &= restored
    out.append(f"self-test: {len(MUTATIONS)} mutations over {len(every)} gates, caught {len(hit)}, missed "
               f"{', '.join(missed) or 'none'}; files untouched: {'yes' if restored else 'NO'}")  # fmt: skip
    out.append(f"self-test: {'PASS' if ok else 'FAIL'} in {time.perf_counter() - t0:.1f} s")
    return ok, out


# ---------------------------------------------------------------------------- main


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else "")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="the default mode")
    g.add_argument("--self-test", action="store_true")
    g.add_argument("--repin-ruled", action="store_true")
    ap.add_argument("--json", action="store_true", help="--check's dump")
    ap.add_argument("--fill", action="store_true", help="fill the values, the names and the matrix")
    ap.add_argument("--post-merge", action="store_true", help="force the post-merge gates")
    a = ap.parse_args(argv)
    if a.self_test:
        ok, lines = selftest()
        print("\n".join(lines))
        return 0 if ok else 1
    t = load(a.post_merge)
    if a.fill:
        text, missing = fill(t.pack, t.values, matrix(t))
        write_text(PACK_REL, text)
        for m in missing:
            print(f"unfilled: {m}")
        t = load(a.post_merge)
    if a.repin_ruled:
        if PLACEHOLDER.search(t.pack):
            print("refused: the pack has an unfilled placeholder (run --check --fill)")
            return 1
        other = [f for f in audit(t) if f.level == "FAIL" and f.gate != "G-RULED-PIN"]
        if other:
            print(
                f"refused: {len(other)} FAIL outside the pins (first: {other[0].gate}: {other[0].msg})"
            )
            return 1
        write_text(PIN_REL, write_pins(t))
        print(f"wrote {PIN_REL}")
        return 0
    found = audit(t)
    fails = [f for f in found if f.level == "FAIL"]
    if a.json:
        dump = {"base": t.base, "merge_base": t.mb, "post_merge": t.post, "values": t.values,
                "findings": [{"level": f.level, "gate": f.gate, "msg": f.msg} for f in found]}  # fmt: skip
        print(json.dumps(dump, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for f in found:
            print(f"{f.level} {f.gate}: {f.msg}")
        warns = sum(f.level == "WARN" for f in found)
        notes = sum(f.level == "NOTE" for f in found)
        mode = "post-merge" if t.post else "PR-1"
        print(
            f"{len(fails)} FAIL / {warns} WARN / {notes} NOTE ({len(GATES) + 1} gates, {mode} mode)"
        )
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
