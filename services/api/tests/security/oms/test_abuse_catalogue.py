"""E29-X02 (#982): the OMS abuse-case catalogue accounts for every seed (BQ-6 as ruled), as
E42-X03's `tests/security/admin/test_abuse_catalogue.py` does for the admin area.

`docs/security/abuse-cases/e29-oms.md` holds one row per seed of `E29-oms.md` section 8.2 (AC-01 to
AC-31), and rows for the ticket's named cases, the rows posted on #982 and the Gherkin. This fails,
in CI, when a seed has no row or a row no seed; when a cited test is renamed or removed; when a
verdict is not a word of the key; when a waiting row names no ticket, a manual row not E29-X03, or
a row holding the case cites no test; when a pin names no accepted-risk record or another owner
ticket than its record's, a record has no sign-off for its owner ticket or no pin, a strict xfail
of this suite names no record or its record's ticket, or a row or a record's pin cites a test (and
parameter) whose strict xfail does not name that record (BQ-5 as ruled); and when an in-scope route
or private topic is missing from the coverage table (BQ-8 as ruled).
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any, Final

import pytest

from tests.security.oms import _cells as cells

_HERE: Final = Path(__file__).parent
_API: Final = Path(__file__).resolve().parents[3]
_DOCS: Final = _API.parents[1] / "docs" / "security"
_MODEL: Final = _DOCS / "threat-models" / "E29-oms.md"
_CATALOGUE: Final = _DOCS / "abuse-cases" / "e29-oms.md"
_SEED: Final = re.compile(r"^\| (AC-\d\d) +\|", re.MULTILINE)
#: `tests/...py::name`, `tests/...py`, or `::name` continuing the path cited before it.
_CITE: Final = re.compile(r"`(tests/[\w/.-]+\.py)?(?:::(\w+))?`")
_TICKET: Final = re.compile(r"#\d+|\bE\d\d-[A-Z]\d\d\b")
_RECORD: Final = re.compile(r"\b(X02-R\d+), (#\d+)")
_KEY_WORD: Final = re.compile(r"^  - \*\*([A-Z]+)\*\*:", re.MULTILINE)
_KEY: Final = {"SUITE", "NEW", "COVERED", "PIN", "WAITING", "MANUAL"}
_HOLDING: Final = {"SUITE", "NEW", "COVERED", "PIN"}  # each must cite the test that holds it

Row = tuple[str, str]  # (verdict, evidence)
#: test name -> parameter id (None: the whole function) -> the reason of its strict xfail.
Pins = dict[str, dict[str | None, str]]


def _text() -> str:
    return _CATALOGUE.read_text(encoding="utf-8")


def _table(heading: str) -> list[list[str]]:
    """The cells of each body row of the table under `## heading`."""
    section = _text().split(f"\n## {heading}\n", 1)[1].split("\n## ", 1)[0]
    rows = [[c.strip() for c in line.strip().strip("|").split("|")]
            for line in section.splitlines() if line.startswith("| ")]  # fmt: skip
    return [r for r in rows[1:] if set(r[0]) != {"-"}]  # past the header and its rule


def _rows() -> dict[str, Row]:
    """Every catalogued case: the seeds', the named cases', the posted rows' and the Gherkin's."""
    rows = {c[0]: (c[1], c[2]) for c in _table("The abuse cases (`E29-oms.md` section 8.2)")}
    rows |= {c[0]: (c[2], c[3]) for c in _table("The ticket's named cases")}
    rows |= {c[0]: (c[1], c[2]) for c in _table("The rows posted on #982")}
    return rows | {c[0]: (c[1], c[2]) for c in _table("The ticket's Gherkin")}


def _records() -> dict[str, tuple[str, str, str]]:
    """Accepted-risk record -> (its owner ticket's cell, its sign-off, its pin test's cell)."""
    return {c[0]: (c[5], c[6], c[2]) for c in _table("Accepted risks and sign-off")}


def _cited(line: str) -> list[tuple[str, str | None]]:
    out: list[tuple[str, str | None]] = []
    path = None
    for match in _CITE.finditer(line):
        path = match.group(1) or path
        if path is not None and (match.group(1) or match.group(2)):
            out.append((path, match.group(2)))
    return out


def _row_faults(rows: dict[str, Row], records: dict[str, tuple[str, str, str]]) -> list[str]:
    """Each row whose verdict is not words of the key, or that lacks the evidence its words owe."""
    faults: list[str] = []
    for name, (verdict, evidence) in rows.items():
        words = {w.strip() for w in verdict.split(",")}
        if not words <= _KEY:
            faults.append(f"{name}: verdict {verdict!r} is not in the key {sorted(_KEY)}")
        if "WAITING" in words and not _TICKET.search(evidence):
            faults.append(f"{name}: WAITING names no issue or ticket key")
        if "MANUAL" in words and "E29-X03 (#1152)" not in evidence:
            faults.append(f"{name}: MANUAL names no E29-X03 (#1152)")
        if words & _HOLDING and not _cited(evidence):
            faults.append(f"{name}: {verdict} cites no test")
        pins = _RECORD.findall(evidence)
        if "PIN" in words and not pins:
            faults.append(f"{name}: PIN names no accepted-risk record and owner ticket")
        for record, ticket in pins:
            if ticket not in records.get(record, ("", "", ""))[0]:
                faults.append(f"{name}: {record} is no record of {ticket}")
    return faults


def test_the_catalogue_has_a_row_for_every_seed_and_no_other() -> None:
    model = _MODEL.read_text(encoding="utf-8")
    seeds = set(_SEED.findall(model[model.index("### 8.2 Seeds") : model.index("\n## 9.")]))
    assert len(seeds) == 31  # AC-01 to AC-31 when this test was written
    rows = {r for r in _rows() if _SEED.match(f"| {r} |")}
    assert sorted(seeds - rows) == [], "seeds with no catalogue row"
    assert sorted(rows - seeds) == [], "catalogue rows for no seed"


def test_every_cited_test_exists() -> None:
    cited = [cite for line in _text().splitlines() for cite in _cited(line)]
    assert len(cited) > 80  # the citations were read
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
    rows = _rows()
    assert len(rows) == 31 + 9 + 3 + 5  # the seeds, named cases, posted rows and scenarios
    assert _row_faults(rows, _records()) == []


def test_a_verdict_outside_the_key_or_a_row_without_its_evidence_fails() -> None:
    records = {"X02-R1": ("#859", "signed", "")}
    rows = {
        "AC-96": ("COVERED, WAITING", "the rest waits on E34-T02 (#859)"),
        "AC-97": ("WATING", "E34-T02 (#859)"),
        "AC-98": ("PIN", "`tests/security/oms/test_x.py::test_y`; X02-R1, #1152"),
        "AC-99": ("MANUAL", "a checklist"),
    }
    faults = _row_faults(rows, records)
    assert [f.split(":", 1)[0] for f in faults] == ["AC-96", "AC-97", "AC-98", "AC-99"]


def _strict_pins() -> Pins:
    """Every strict-xfail reason of the suite's tests, keyed by test name, then by parameter id."""
    found: Pins = {}
    for path in sorted(_HERE.glob("test_*.py")):
        module = importlib.import_module(f"tests.security.oms.{path.stem}")
        for name, fn in vars(module).items():
            for mark in getattr(fn, "pytestmark", []) if name.startswith("test_") else []:
                if mark.name == "xfail":
                    found.setdefault(name, {})[None] = _pin_reason(name, mark.kwargs)
                for value in mark.args[1] if mark.name == "parametrize" else []:
                    for m in getattr(value, "marks", ()):
                        if m.name == "xfail":
                            param = value.id or str(value.values[0])
                            found.setdefault(name, {})[param] = _pin_reason(name, m.kwargs)
    return found


def _pin_reason(test: str, kw: dict[str, Any]) -> str:
    assert (kw.get("strict"), kw.get("raises")) == (True, AssertionError), test
    return str(kw.get("reason"))


def _pin_faults(text: str, pins: Pins, where: str) -> list[str]:
    """Each record `text` names whose nearest test cited before it (with the parameter ids between
    the two, if any) has no strict xfail naming that record."""
    faults: list[str] = []
    cites = [m for m in _CITE.finditer(text) if m.group(2)]
    for record in re.finditer(r"\bX02-R\d+\b", text):
        cite = next((c for c in reversed(cites) if c.end() <= record.start()), None)
        if cite is None:
            faults.append(f"{where}: {record[0]} follows no cited test")
            continue
        test = cite.group(2)
        params = re.findall(r"`(\w+)`", text[cite.end() : record.start()])
        held = pins.get(test, {})
        reasons = [r for p, r in held.items() if p is None or not params or p in params]
        if not any(r.startswith(f"{record[0]} (") for r in reasons):
            faults.append(f"{where}: {test} {params or ''} holds no strict xfail of {record[0]}")
    return faults


def test_every_record_is_signed_for_its_owner_ticket_and_every_pin_names_its_record() -> None:
    records, pins = _records(), _strict_pins()
    assert len(records) == 5 and sum(map(len, pins.values())) >= 5, (records, pins)
    unsigned = [
        r
        for r, (ticket, sign, _pin) in records.items()
        if not (
            (owner := _TICKET.search(ticket))
            and "main-orchestrator" in sign
            and "#982" in sign
            and f"for {owner[0]}" in sign
        )
    ]
    assert unsigned == [], "a record with no owner ticket or no sign-off for it"
    named: set[str] = set()
    for test, held in pins.items():
        for reason in held.values():
            found = re.match(r"(X02-R\d+) \((#\d+)\): ", reason)
            assert found and found[2] in records.get(found[1], ("", "", ""))[0], (test, reason)
            named.add(found[1])
    assert named == set(records), "a record no strict xfail names"
    pinned = {r for _v, e in _rows().values() for r, _t in _RECORD.findall(e)}
    assert pinned == set(records), "a record no catalogue row pins"


def test_every_pin_row_and_every_records_pin_cite_a_test_whose_xfail_names_that_record() -> None:
    pins = _strict_pins()
    faults = [f for name, (_v, e) in _rows().items() for f in _pin_faults(e, pins, name)]
    for record, (_ticket, _sign, cell) in _records().items():
        faults += _pin_faults(f"{cell}; {record}", pins, record)
    assert faults == []


def test_a_row_naming_another_record_than_its_tests_xfail_or_a_passing_test_fails() -> None:
    pins: Pins = {"test_p": {"a": "X02-R1 (#859): a", "b": "X02-R2 (#859): b"}}
    path = "`tests/security/oms/test_x.py::"
    cases = {
        "held": f"{path}test_p` (`a`); X02-R1, #859",
        "unparametrised": f"{path}test_p`, X02-R2, #859",
        "swapped": f"{path}test_p` (`a`); X02-R2, #859",
        "passing": f"{path}test_q`; X02-R1, #859",
        "uncited": "X02-R1, #859",
    }
    faults = [f.split(":", 1)[0] for k, e in cases.items() for f in _pin_faults(e, pins, k)]
    assert faults == ["swapped", "passing", "uncited"]


def test_every_in_scope_route_and_private_topic_is_listed_once() -> None:
    """BQ-8 as ruled: the coverage table lists each E29 operation of 22 by its operationId and
    route, and each private topic this suite runs, once; an unlisted one fails."""
    listed = [(c[0].strip("`"), c[1].strip("`")) for c in _table(
        "Coverage: the routes and topics in scope")]  # fmt: skip
    operations = {
        (op["operationId"], key) for key, op in (
            (f"{m.upper()} {p}", item[m]) for p, item in cells.contract()["paths"].items()
            for m in ("get", "post", "put", "patch", "delete") if isinstance(item.get(m), dict)
        ) if cells.E29_PATHS.match(key.split(" ", 1)[1])
    }  # fmt: skip
    topics = {(f"topic `{t}", "WS") for t in cells.WS_TOPICS}
    assert len(listed) == len(set(listed)), "a route or topic listed twice"
    assert set(listed) == operations | topics, sorted(set(listed) ^ (operations | topics))


@pytest.mark.parametrize("heading", ["Negative controls", "Manual checks (E29-X03, #1152)"])
def test_the_negative_controls_and_the_manual_checks_each_cite_their_tests(heading: str) -> None:
    section = _text().split(f"\n## {heading}\n", 1)[1].split("\n## ", 1)[0]
    assert [c for line in section.splitlines() for c in _cited(line)], heading
