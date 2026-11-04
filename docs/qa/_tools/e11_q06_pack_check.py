"""Check the E11-Q06 regression-pack index against the repository at its pinned base.

Usage:
    python3 docs/qa/_tools/e11_q06_pack_check.py --check
    python3 docs/qa/_tools/e11_q06_pack_check.py --self-test

`--check` re-reads, at the base named in the pack's header, the E11 ticket JSON and every file the
pack cites. It fails on: a Story or Task scenario missing from section 3, added to it or retitled;
a status outside the vocabulary (`traced`, `partial`, `gap`, `blocked: #N`, the senses of the E11-Q01
plan's section 7.2); a `blocked` number that is not the row's owner; a section 3 cite that is not a
`describe` / `it` / `test` line, or is a `todo` / `skip` line on a `traced` row; a doc cite or other
cite past the end of its file; a section 3.1 count that differs (the `named` count is derived: a
`traced` row whose cite carries the scenario's title); and a word the public-text scrub rejects in
the pack or its charters. It does not pin the line of a doc cite. `--self-test` applies one
mutation per failure family and expects each to fail.
"""

from __future__ import annotations

import argparse
import codecs
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PACK = Path("docs/qa/e11-regression-pack.md")
CHARTERS = tuple(
    Path(f"docs/qa/charters/E11-charter-{n}.md")
    for n in (
        "3-trading-session",
        "4-awkward-user",
        "5-no-pointer",
        "6-long-session",
        "7-cross-story-seams",
    )
)
TICKETS = "docs/plan/backlog/E11.json"
ALIASES = {"CE/": "packages/chart-engine/", "WEB/": "apps/web/", "UI/": "packages/ui/"}
STATUSES = ("traced", "partial", "blocked", "gap")
BLOCKED = re.compile(r"blocked: (#\d+)")
# The public-text scrub list and the title stand-ins, rot13 so this file does not carry the words.
SCRUB_ROT13 = (
    "cer-nhgu yrnx rkcbfrq olcnff rkcybvg nggnpx benpyr erirny haobhaqrq sybbq fgnyy qbf "
    "nqivfbel tufn /ubzr/ /gzc/"
)
STAND_INS = tuple(
    (codecs.decode(word, "rot13"), sub)
    for word, sub in (("sybbqvat", "overrunning"), ("sybbq", "overrun"))
)
SCRUB = re.compile(
    "|".join(
        r"\b" + re.escape(w) + r"\b" if len(w) <= 3 else re.escape(w)
        for w in codecs.decode(SCRUB_ROT13, "rot13").split()
    ),
    re.IGNORECASE,
)
ROW = re.compile(r"^\|\s*(?:S|T)\d\d\.\d+\s*\|")
ROW_CITE = re.compile(r"`((?:CE|WEB|UI)/[^`]+?):(\d+)`")
DOC_CITE = re.compile(r"`([A-Za-z][^`\s]*\.[a-z]{2,4})`:(\d+)")
TEST_CALL = re.compile(r"\b(describe|it|test)(\.\w+)*\(")
COUNTS = re.compile(
    r"(\d+) scenarios: (\d+) traced \((\d+) named\), (\d+) partial, (\d+) blocked, (\d+) gap\."
)


@dataclass(frozen=True)
class Row:
    """One section 3 row."""

    rid: str
    title: str
    owner: str
    status: str
    cites: tuple[tuple[str, int], ...]
    evidence: str


class Repo:
    """Reads files at one commit, cached."""

    def __init__(self, base: str) -> None:
        self.base = base
        self._cache: dict[str, list[str] | None] = {}

    def lines(self, path: str) -> list[str] | None:
        if path not in self._cache:
            out = subprocess.run(
                ["git", "show", f"{self.base}:{path}"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self._cache[path] = out.stdout.splitlines() if out.returncode == 0 else None
        return self._cache[path]


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def stand_in(title: str) -> str:
    for word, sub in STAND_INS:
        title = title.replace(word, sub)
    return title


def expand(path: str) -> str:
    for alias, full in ALIASES.items():
        if path.startswith(alias):
            return full + path[len(alias) :]
    return path


def expected_scenarios(repo: Repo) -> dict[str, str]:
    raw = repo.lines(TICKETS)
    if raw is None:
        raise SystemExit(f"cannot read {TICKETS} at {repo.base}")
    out: dict[str, str] = {}
    for ticket in json.loads("\n".join(raw)):
        found = re.fullmatch(r"E11-((?:S|T)\d\d)", ticket["key"])
        if not found:
            continue
        titles = re.findall(r"^\s*Scenario(?: Outline)?:\s*(.+)$", ticket["body"], re.MULTILINE)
        for i, title in enumerate(titles, 1):
            out[f"{found.group(1)}.{i}"] = title.strip()
    return out


def parse_rows(text: str) -> list[Row]:
    rows = []
    for line in text.splitlines():
        if ROW.match(line):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) != 6:
                rows.append(Row(cells[0], "", "", "malformed", (), ""))
                continue
            rid, title, owner, status, evidence, _note = cells
            cites = tuple((expand(p), int(n)) for p, n in ROW_CITE.findall(evidence))
            rows.append(Row(rid, title, owner, status, cites, evidence))
    return rows


def check_rows(text: str, repo: Repo) -> list[str]:
    errors: list[str] = []
    expected = expected_scenarios(repo)
    rows = parse_rows(text)
    named: set[str] = set()
    seen = Counter(r.rid for r in rows)
    errors += [f"{rid}: listed {n} times" for rid, n in seen.items() if n > 1]
    errors += [f"{rid}: scenario missing" for rid in expected if rid not in seen]
    errors += [f"{rid}: not a scenario at the base" for rid in seen if rid not in expected]
    for row in rows:
        original = expected.get(row.rid)
        if original is not None and row.title != stand_in(original):
            errors.append(f"{row.rid}: title differs from the ticket")
        kind = row.status.split(":")[0]
        pinned = BLOCKED.fullmatch(row.status)
        if kind not in STATUSES or (kind == "blocked") != bool(pinned):
            errors.append(f"{row.rid}: status {row.status!r} not in the vocabulary")
        elif pinned and pinned.group(1) != row.owner:
            errors.append(f"{row.rid}: {row.status} is not the owner {row.owner}")
        if kind in ("gap", "blocked") and (row.cites or row.evidence != "none"):
            errors.append(f"{row.rid}: a gap row carries evidence")
        if kind not in ("gap", "blocked") and not row.cites:
            errors.append(f"{row.rid}: {row.status} row without a cite")
        titled = False
        for path, num in row.cites:
            lines = repo.lines(path)
            if lines is None or not 1 <= num <= len(lines):
                errors.append(f"{row.rid}: {path}:{num} does not exist")
                continue
            line = lines[num - 1]
            if not TEST_CALL.search(line):
                errors.append(f"{row.rid}: {path}:{num} is not a describe / it / test line")
            if row.status == "traced" and re.search(r"\.(todo|skip|fixme)\(", line):
                errors.append(f"{row.rid}: {path}:{num} is a todo / skip line")
            if original is not None and norm(original) in norm(line):
                titled = True
        if row.status == "traced" and titled:
            named.add(row.rid)
    return errors + check_counts(text, rows, len(named))


def check_counts(text: str, rows: list[Row], named: int) -> list[str]:
    found = COUNTS.search(text)
    if not found:
        return ["section 3.1: count line missing"]
    tally = Counter(r.status.split(":")[0] for r in rows)
    actual = [len(rows), tally["traced"], named, tally["partial"], tally["blocked"], tally["gap"]]
    stated = [int(g) for g in found.groups()]
    return [] if stated == actual else [f"section 3.1: stated {stated}, derived {actual}"]


def check_doc_cites(name: str, text: str, repo: Repo) -> list[str]:
    errors = []
    for path, num in DOC_CITE.findall(text):
        full = expand(path)
        if "/" not in full:
            continue
        lines = repo.lines(full)
        if lines is None or not 1 <= int(num) <= len(lines):
            errors.append(f"{name}: {full}:{num} does not exist at the base")
    return errors


def check_scrub(name: str, text: str) -> list[str]:
    return [f"{name}: rejected word {hit!r}" for hit in SCRUB.findall(text)]


def run(texts: dict[str, str], repo: Repo) -> list[str]:
    errors = check_rows(texts[str(PACK)], repo)
    for name, text in texts.items():
        errors += check_doc_cites(name, text, repo) + check_scrub(name, text)
    return errors


def load() -> tuple[dict[str, str], Repo]:
    texts = {str(p): (ROOT / p).read_text(encoding="utf-8") for p in (PACK, *CHARTERS)}
    base = re.search(r"Base: `([0-9a-f]{40})`", texts[str(PACK)])
    if not base:
        raise SystemExit("the pack header names no 40-character base")
    return texts, Repo(base.group(1))


def self_test(texts: dict[str, str], repo: Repo) -> list[str]:
    pack = texts[str(PACK)]
    titled = next(r for r in parse_rows(pack) if r.status == "traced" and r.cites)
    path, num = titled.cites[0]
    short = next(a + path[len(f) :] for a, f in ALIASES.items() if path.startswith(f))
    first_row = next(line for line in pack.splitlines() if ROW.match(line))
    blocked = next(r for r in parse_rows(pack) if r.status.startswith("blocked"))
    title_cell = next(r.title for r in parse_rows(pack) if r.title)
    mutations = {
        "a moved cite": pack.replace(f"`{short}:{num}`", f"`{short}:{num + 1}`", 1),
        "a dropped row": pack.replace(first_row + "\n", "", 1),
        "a changed count": COUNTS.sub(
            "1 scenarios: 0 traced (0 named), 0 partial, 0 blocked, 0 gap.", pack
        ),
        "a rejected word": pack + "\n" + codecs.decode("haobhaqrq", "rot13") + "\n",
        "an unknown status": pack.replace("| traced ", "| passed ", 1),
        "a retitled row": pack.replace(f"| {title_cell} ", f"| {title_cell}z ", 1),
        "a blocked row on the wrong owner": pack.replace(
            f"| {blocked.status} ", "| blocked: #1 ", 1
        ),
    }
    failures = []
    for label, mutated in mutations.items():
        if not run({**texts, str(PACK): mutated}, repo):
            failures.append(f"self-test: {label} was not caught")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    texts, repo = load()
    errors = self_test(texts, repo) if args.self_test else run(texts, repo)
    for error in errors:
        print(error)
    label = "self-test" if args.self_test else "check"
    print(f"{label}: {'FAIL' if errors else 'PASS'} ({len(errors)} problems)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
