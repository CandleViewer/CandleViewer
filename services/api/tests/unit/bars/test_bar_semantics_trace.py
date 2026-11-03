"""Trace check for the bar-semantics reference (E12-K02, #526).

The reference is `docs/plan/36-bar-semantics-reference.md`. Every normative row names its
evidence: a QA case (`E12-TC-…` in the E12 test plan), a golden conformance pair
(`golden:<tape>/<pair>` in the E12-Q02 MANIFEST) or a test (`test:<path>::<name>`). A cited id
that does not exist fails here, so the document cannot keep claiming evidence that was renamed or
removed. A claim with no backing test is removed or turned into a test; only the claims #2200
tracks may say "convention, no golden (#2200)" instead. Every signal named in §9 must be
registered in `candleviewer`.

Tables with an "Evidence" column are checked row by row; every other table must be one of the
five known exceptions (the §0 name map, the §7 non-guarantees, the §9 signal table, the §10
"Status" table and the §11 register), so a normative table cannot drop out of the trace by losing
or renaming its Evidence column. A §9 metric must be in the `20-architecture.md` §12.1 catalogue
with the labels §9 gives it; a pending marker that names a ticket key names that ticket's issue;
the §7 and §11 tracking cells name an issue. The `py` filter of `pr.yml` must name every file this
test reads, so a PR that edits only one of them still runs it.
"""

from __future__ import annotations

import importlib.util
import json
import re
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[5]
REFERENCE = ROOT / "docs/plan/36-bar-semantics-reference.md"
QA_PLAN = ROOT / "qa/plans/e12-bars-and-series-test-plan.md"
MANIFEST = ROOT / "packages/fixtures/golden/bars/conformance/MANIFEST.toml"
API_TESTS = ROOT / "services/api/tests"
SOURCE = ROOT / "services/api/candleviewer"
ARCHITECTURE = ROOT / "docs/plan/20-architecture.md"
PUBLISHED = ROOT / "docs/plan/backlog/_tools/published.json"
PATH_FILTERS = ROOT / "tools/ci/path_filters.py"
#: Headers of the tables that carry no Evidence column, by design (see the module docstring).
UNTRACED_TABLES = {
    (
        "Domain (`24` §3.1)",
        "Store (`21` §4.8)",
        "REST `Bar` (`22`)",
        "WS item (`23` §14.3)",
        "Meaning",
    ),
    ("#", "Non-guarantee", "Tracked"),
    ("Symptom", "Signal"),
    ("Figure", "Value", "Status"),
    ("#", "Divergence", "Kind", "Routed to"),
}

_TC = re.compile(r"\bE12-TC-[A-Z]\d{2}\b")
_GOLDEN = re.compile(r"`golden:([a-z0-9-]+)/([a-z]+:[0-9a-z]+)`")
_TEST = re.compile(r"`test:([^`:]+)(?:::([A-Za-z_][A-Za-z0-9_]*))?`")
_CONVENTION = re.compile(r"convention, no golden \(#2200\)")
_ANY_CONVENTION = re.compile(r"convention, no golden \(#(\d+)\)")
_SIGNAL = re.compile(r"`((?:bars?|kline)_[a-z0-9_]+)(?:\{[a-z,]+\})?`")
_FAMILY = re.compile(r"^### 2\.\d (.+)$", re.MULTILINE)


def _text() -> str:
    return REFERENCE.read_text(encoding="utf-8")


def _family_sections(text: str) -> dict[str, str]:
    heads = list(_FAMILY.finditer(text))
    end = text.index("\n## 3.")
    return {
        m.group(1): text[m.end() : heads[i + 1].start() if i + 1 < len(heads) else end]
        for i, m in enumerate(heads)
    }


def test_reference_cites_only_qa_cases_that_exist() -> None:
    known = set(_TC.findall(QA_PLAN.read_text(encoding="utf-8")))
    cited = set(_TC.findall(_text()))
    assert cited, "the reference cites no E12-TC case"
    assert sorted(cited - known) == []


def test_reference_cites_only_golden_pairs_in_the_manifest() -> None:
    manifest = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
    known = {(t["name"], g["pair"]) for t in manifest["tape"] for g in t["goldens"]}
    cited = set(_GOLDEN.findall(_text()))
    assert cited, "the reference cites no golden pair"
    assert sorted(cited - known) == []


def test_reference_cites_only_tests_that_exist() -> None:
    cited = _TEST.findall(_text())
    assert cited, "the reference cites no test"
    missing: list[str] = []
    for path, name in cited:
        file = ROOT / path if path.startswith("packages/") else API_TESTS / path
        if not file.is_file():
            missing.append(path)
        elif name and not re.search(
            rf"^\s*(?:async )?def {re.escape(name)}\(", file.read_text(encoding="utf-8"), re.M
        ):
            missing.append(f"{path}::{name}")
    assert missing == []


def test_reference_specifies_all_six_families_in_order() -> None:
    names = [n.split(" (")[0] for n in _family_sections(_text())]
    assert names == [
        "Time bars",
        "Tick bars",
        "Volume bars",
        "Range bars",
        "Delta bars",
        "Renko bricks",
    ]


@pytest.mark.parametrize("aspect", ["Close", "Times", "Wall-clock comparable"])
def test_every_family_states_each_core_aspect(aspect: str) -> None:
    for family, body in _family_sections(_text()).items():
        rows = [r for r in body.splitlines() if r.startswith("| ")]
        found = any(r.split("|")[1].strip().startswith(aspect) for r in rows)
        assert found, f"{family} has no '{aspect}' row"


def _evidence_rows(text: str) -> list[tuple[str, str]]:
    """(first cell, evidence cell) of every data row of every table with an Evidence column."""
    rows: list[tuple[str, str]] = []
    for header, body in _tables(text):
        if "Evidence" in header:
            col = header.index("Evidence")
            rows += [(cells[0], cells[col] if len(cells) > col else "") for cells in body]
    return rows


def _tables(text: str) -> list[tuple[tuple[str, ...], list[list[str]]]]:
    """(header cells, data rows) of every table; the separator row is dropped."""
    tables: list[tuple[tuple[str, ...], list[list[str]]]] = []
    current: list[list[str]] | None = None
    for line in text.splitlines():
        if not line.startswith("|"):
            current = None
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if current is None:
            current = []
            tables.append((tuple(cells), current))
        elif any(c.strip("-: ") for c in cells):
            current.append(cells)
    return tables


def test_every_claim_names_evidence_or_the_2200_label() -> None:
    rows = _evidence_rows(_text())
    assert len(rows) > 60, "the evidence tables were not found"
    bare = [
        claim[:60]
        for claim, evidence in rows
        if not (
            _TC.search(evidence)
            or _GOLDEN.search(evidence)
            or _TEST.search(evidence)
            or _CONVENTION.search(evidence)
        )
    ]
    assert bare == []


def test_the_no_golden_label_is_used_only_for_2200() -> None:
    assert set(_ANY_CONVENTION.findall(_text())) == {"2200"}


def test_every_section_9_signal_is_registered() -> None:
    text = _text()
    section = text[text.index("\n## 9.") : text.index("\n## 10.")]
    table = "\n".join(r for r in section.splitlines() if r.startswith("| "))
    names = set(_SIGNAL.findall(table))
    assert len(names) > 15, "the §9 signal table was not found"
    source = "\n".join(
        f.read_text(encoding="utf-8") for f in SOURCE.rglob("*.py") if "__pycache__" not in f.parts
    )
    assert sorted(n for n in names if f'"{n}"' not in source) == []


def test_every_family_cites_a_golden_pair() -> None:
    for family, body in _family_sections(_text()).items():
        assert _GOLDEN.search(body), f"{family} cites no golden conformance pair"


def test_every_table_is_traced_or_a_known_exception() -> None:
    headers = [h for h, _ in _tables(_text())]
    assert [h for h in headers if "Evidence" not in h and h not in UNTRACED_TABLES] == []
    assert sum("Evidence" in h for h in headers) >= 13, "a traced table lost its Evidence column"


def test_every_table_row_has_every_cell() -> None:
    short = [
        (h[0], cells[0][:40])
        for h, body in _tables(_text())
        for cells in body
        if len(cells) != len(h)
    ]
    assert short == []


def test_python_test_citations_name_a_test() -> None:
    bare = [p for p, name in _TEST.findall(_text()) if not name and not p.startswith("packages/")]
    assert bare == []


def _section_9_signals() -> list[tuple[str, str, str]]:
    """(kind word before it, name, labels) of every signal in the §9 table."""
    text = _text()
    section = text[text.index("\n## 9.") : text.index("\n## 10.")]
    table = "\n".join(r for r in section.splitlines() if r.startswith("| "))
    pattern = re.compile(r"(\w+)? ?`((?:bars?|kline)_[a-z0-9_]+)(\{[a-z,]+\})?`")
    return [(m.group(1) or "", m.group(2), m.group(3) or "") for m in pattern.finditer(table)]


def test_every_section_9_metric_is_catalogued_with_its_labels() -> None:
    text = ARCHITECTURE.read_text(encoding="utf-8")
    catalogue = text[text.index("\n### 12.1") : text.index("\n### 12.2")]
    metrics = [(n, lab) for kind, n, lab in _section_9_signals() if kind not in {"log", "health"}]
    assert len(metrics) > 12, "the §9 metrics were not found"
    wrong = []
    for name, labels in metrics:
        found = re.search(rf"`{re.escape(name)}(\{{[a-z_,]+\}})?`", catalogue)
        if found is None or (found.group(1) or "") != labels:
            wrong.append(f"{name}{labels}")
    assert wrong == []


def test_pending_markers_name_their_ticket_issue() -> None:
    published = json.loads(PUBLISHED.read_text(encoding="utf-8"))
    text = _text()
    markers = re.findall(r"_pending ([^_]*)_", text)
    assert markers, "no pending marker found"
    wrong = [
        m
        for m in markers
        for key, num in re.findall(r"\b(E\d{2}-[A-Z]\d{2}) #(\d+)", m)
        if published.get(key, {}).get("number") != int(num)
    ]
    assert wrong == []
    cells = [c for _, body in _tables(text) for cells in body for c in cells]
    unnamed = [c[:60] for c in cells for m in re.findall(r"_pending([^_]*)_", c) if "#" not in m]
    assert unnamed == []


def test_non_guarantees_and_divergences_name_their_tracker() -> None:
    untracked = []
    for header, body in _tables(_text()):
        for cells in body:
            if header[-1] == "Tracked" and not (
                re.search(r"#\d+", cells[-1]) or cells[-1].startswith("by design")
            ):
                untracked.append(cells[0])
            if header[-1] == "Routed to" and not (
                re.search(r"#\d+", cells[-1]) or cells[2].endswith("corrected in this PR")
            ):
                untracked.append(cells[0])
    assert untracked == []


def _path_filters() -> ModuleType:
    spec = importlib.util.spec_from_file_location("path_filters", PATH_FILTERS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_py_filter_names_every_file_this_test_reads() -> None:
    filters = _path_filters()
    rules = filters.load_filters()["py"]
    cited = {
        str((ROOT / p if p.startswith("packages/") else API_TESTS / p).relative_to(ROOT))
        for p, _ in _TEST.findall(_text())
    }
    reads = {REFERENCE, QA_PLAN, MANIFEST, ARCHITECTURE, PUBLISHED, Path(__file__).resolve()}
    paths = cited | {str(p.relative_to(ROOT)) for p in reads}
    assert sorted(p for p in paths if not any(filters.matches(p, r) for r in rules)) == []
