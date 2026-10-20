"""The admin abuse-case catalogue accounts for every seed of the E42 threat model (E42-X03, #1026).

`docs/security/abuse-cases/e42-admin.md` holds one row per seed of `e42-admin.md` §9.2
(AC-ADM-nn) and of the user-lifecycle annex §4 (UL-ACnn). A seed added to the model later fails
here, in CI, until it has a row; a row whose cited test is renamed or removed fails too. Every
verdict is a word of the catalogue's key; a row waiting on another ticket must name it, and a row
with any verdict word besides WAITING must cite the test that holds it. As E09's
`test_catalogue_threat_coverage.py` does for E09.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[5]
_DOCS = _REPO / "docs" / "security"
_MODEL = _DOCS / "threat-models" / "e42-admin.md"
_ANNEX = _DOCS / "threat-models" / "e42-user-lifecycle.md"
_CATALOGUE = _DOCS / "abuse-cases" / "e42-admin.md"
_API = _REPO / "services" / "api"
_SEED = re.compile(r"^\| (AC-ADM-\d\d|UL-AC\d\d) +\|", re.MULTILINE)
_NAMED = "## The ticket's named cases"
#: `tests/...py::name`, `tests/...py`, or `::name` continuing the path cited before it.
_CITE = re.compile(r"`(tests/[\w/.-]+\.py)?(?:::(\w+))?`")
_TICKET = re.compile(r"#\d+|\bE\d\d-[A-Z]\d\d\b")
#: A word of the verdict key: `- **WORD**: ...` under "Verdict key".
_KEY_WORD = re.compile(r"^  - \*\*([A-Z]+)\*\*:", re.MULTILINE)
_KEY = {"SUITE", "NEW", "COVERED", "PIN", "WAITING"}

Row = tuple[str, str]  # (verdict, evidence)


def _text() -> str:
    return _CATALOGUE.read_text(encoding="utf-8")


def _rows() -> dict[str, Row]:
    """Seed id -> (verdict, evidence) of its row in the per-seed tables."""
    rows: dict[str, Row] = {}
    for line in _text().splitlines():
        if _SEED.match(line):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            rows[cells[0]] = (cells[1], cells[2])
    return rows


def _named_rows() -> dict[str, Row]:
    """Ticket case -> (verdict, evidence) of the table of the ticket's named cases."""
    section = _text().split(_NAMED, 1)[1].split("\n## ", 1)[0]
    rows: dict[str, Row] = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) == 4 and cells[0] not in ("Ticket case", "---"):
            rows[cells[0]] = (cells[2], cells[3])
    return rows


def _cited(line: str) -> list[tuple[str, str | None]]:
    out: list[tuple[str, str | None]] = []
    path = None
    for match in _CITE.finditer(line):
        path = match.group(1) or path
        if path is not None and (match.group(1) or match.group(2)):
            out.append((path, match.group(2)))
    return out


def _citations() -> list[tuple[str, str | None]]:
    return [cite for line in _text().splitlines() for cite in _cited(line)]


def _row_faults(rows: dict[str, Row], key: set[str]) -> list[str]:
    """Each row whose verdict is not words of `key`, that waits without naming a ticket, or that
    has a verdict word besides WAITING without citing the test that holds it."""
    faults: list[str] = []
    for name, (verdict, evidence) in rows.items():
        words = {w.strip() for w in verdict.split(",")}
        if not words or not words <= key:
            faults.append(f"{name}: verdict {verdict!r} is not in the key {sorted(key)}")
        if "WAITING" in words and not _TICKET.search(evidence):
            faults.append(f"{name}: WAITING names no issue or ticket key")
        if words - {"WAITING"} and not _cited(evidence):
            faults.append(f"{name}: {verdict} cites no test")
    return faults


def test_the_catalogue_has_a_row_for_every_seed_and_no_other() -> None:
    seeds = set(_SEED.findall(_MODEL.read_text(encoding="utf-8")))
    seeds |= set(_SEED.findall(_ANNEX.read_text(encoding="utf-8")))
    assert len(seeds) >= 51  # 35 AC-ADM and 16 UL-AC seeds when this test was written
    rows = set(_rows())
    assert sorted(seeds - rows) == [], "seeds with no catalogue row"
    assert sorted(rows - seeds) == [], "catalogue rows for no seed"


def test_every_cited_test_exists() -> None:
    cited = _citations()
    assert len(cited) > 50  # the citations were read
    missing = []
    for path, name in cited:
        source = _API / path
        if not source.is_file():
            missing.append(path)
        elif name and not re.search(rf"^(async )?def {name}\b", source.read_text("utf-8"), re.M):
            missing.append(f"{path}::{name}")
    assert missing == [], f"the catalogue cites tests that do not exist: {missing}"


def test_the_verdict_key_is_the_one_the_rows_use() -> None:
    assert set(_KEY_WORD.findall(_text())) == _KEY


def test_every_row_has_a_verdict_of_the_key_and_its_evidence() -> None:
    named = _named_rows()
    assert len(named) >= 11  # the ticket's eleven named cases were read
    rows = {**_rows(), **named}
    assert _row_faults(rows, _KEY) == []


def test_a_verdict_outside_the_key_or_a_row_without_evidence_fails() -> None:
    rows = {
        "AC-ADM-96": ("COVERED, WAITING", "the rest waits on E42-T05 (#966)"),
        "AC-ADM-97": ("WATING", "E42-T05 (#966)"),
        "AC-ADM-98": ("COVERED", "the store holds it"),
        "AC-ADM-99": ("WAITING", "a later ticket"),
    }
    faults = _row_faults(rows, _KEY)
    assert [f.split(":", 1)[0] for f in faults] == [
        "AC-ADM-96",
        "AC-ADM-97",
        "AC-ADM-97",
        "AC-ADM-98",
        "AC-ADM-99",
    ]
