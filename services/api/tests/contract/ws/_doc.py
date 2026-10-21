"""Readers of `23-ws-protocol.md` shared by the tests that compare it with the code (#572).

`between`, `paragraph` and `table` are the helpers `test_ws_topic_registry_as_built.py` (#2823)
wrote for itself. `strict_table` is the reader the parity test uses: it fails on a table that is
not as expected and never skips a row (as `tools/contracts/check_error_registry.py` does for
§10.2). Every row carries its line number in the document, so a drift can name it."""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import takewhile

from tests.contract.ws._harness import PROTOCOL_DOC

DOC = PROTOCOL_DOC.read_text(encoding="utf-8")


@dataclass(frozen=True)
class Section:
    """A slice of the document and the number of its first line (1-based)."""

    text: str
    first_line: int

    def line_of(self, needle: str) -> int:
        """The document line of the first line of this section that holds `needle`."""
        for offset, line in enumerate(self.text.splitlines()):
            if needle in line:
                return self.first_line + offset
        raise AssertionError(f"23-ws-protocol.md section has no line with {needle!r}")


@dataclass(frozen=True)
class Row:
    cells: list[str]
    line: int


def section(start: str, end: str) -> Section:
    """The doc from the first `start` up to the next `end` after it."""
    i = DOC.find(start)
    j = DOC.find(end, i + len(start))
    assert 0 <= i < j, f"23-ws-protocol.md no longer has {start!r} followed by {end!r}"
    return Section(DOC[i:j], DOC.count("\n", 0, i) + 1)


def between(start: str, end: str) -> str:
    return section(start, end).text


def paragraph(sec: str, needle: str) -> str:
    """The one paragraph of `sec` that holds `needle`."""
    found = [p for p in sec.split("\n\n") if needle in p]
    assert len(found) == 1, f"{len(found)} paragraphs hold {needle!r}; this test reads exactly one"
    return found[0]


def table(sec: str) -> list[list[str]]:
    """The cells of the first table in `sec`, without its header and delimiter rows."""
    lines = sec.splitlines()
    first = next(i for i, ln in enumerate(lines) if ln.startswith("|"))
    rows = takewhile(lambda ln: ln.startswith("|"), lines[first:])
    return [[cell.strip() for cell in ln.strip("|").split("|")] for ln in rows][2:]


def strict_table(sec: Section, columns: tuple[str, ...], what: str) -> list[Row]:
    """The first table of `sec`: its header must be `columns` exactly, its delimiter row must
    follow, and every row must have as many cells. Anything else is an assertion failure, so a
    reworded or malformed table is a red test, never a skipped row."""
    lines = sec.text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.startswith("|")), None)
    assert start is not None, f"{what}: no table in the section"
    block = list(takewhile(lambda ln: ln.startswith("|"), lines[start:]))
    cells = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in block]
    assert tuple(cells[0]) == columns, f"{what}: header is {cells[0]}, expected {list(columns)}"
    assert re.fullmatch(r"\|?[\s:|-]+\|?", block[1]), f"{what}: no delimiter row"
    rows = []
    for n, row in enumerate(cells[2:]):
        line = sec.first_line + start + 2 + n
        assert len(row) == len(columns), f"{what} (line {line}): {len(row)} cells in {row}"
        rows.append(Row(row, line))
    return rows


def first_number(cell: str) -> int:
    """The first whole number of a cell: a space groups thousands, so `262 144` is 262144."""
    found = re.search(r"\d[\d \u202f]*\d|\d", cell)
    assert found, f"no number in {cell!r}"
    return int(re.sub(r"[ \u202f]", "", found.group()))
