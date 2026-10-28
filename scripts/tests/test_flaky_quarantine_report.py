"""Unit tests for tools/ci/flaky_quarantine_report.py (E02-T10, C-9.3)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.flaky_quarantine_report import build_report, scan_pytest_file, scan_vitest_file


def test_scan_pytest_file_referenced_marker(tmp_path: Path) -> None:
    f = tmp_path / "test_x.py"
    f.write_text(
        "import pytest\n"
        "@pytest.mark.flaky  # ticket: OF-42\n"
        "def test_thing():\n"
        "    assert True\n",
        encoding="utf-8",
    )
    entries = scan_pytest_file(f, tmp_path)
    assert len(entries) == 1
    assert entries[0].ticket == "OF-42"
    assert entries[0].referenced


def test_scan_pytest_file_unreferenced_marker(tmp_path: Path) -> None:
    f = tmp_path / "test_x.py"
    f.write_text(
        "import pytest\n@pytest.mark.flaky\ndef test_thing():\n    assert True\n",
        encoding="utf-8",
    )
    entries = scan_pytest_file(f, tmp_path)
    assert len(entries) == 1
    assert not entries[0].referenced


def test_scan_vitest_file_referenced_marker(tmp_path: Path) -> None:
    f = tmp_path / "x.test.mjs"
    f.write_text(
        '// ticket: OF-99\nit.flaky("does a thing", () => {});\n',
        encoding="utf-8",
    )
    entries = scan_vitest_file(f, tmp_path)
    assert len(entries) == 1
    assert entries[0].ticket == "OF-99"


def test_scan_vitest_file_unreferenced_marker(tmp_path: Path) -> None:
    f = tmp_path / "x.test.mjs"
    f.write_text('it.flaky("does a thing", () => {});\n', encoding="utf-8")
    entries = scan_vitest_file(f, tmp_path)
    assert len(entries) == 1
    assert not entries[0].referenced


def test_build_report_skips_venv_and_node_modules(tmp_path: Path) -> None:
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "test_ignored.py").write_text(
        "@pytest.mark.flaky\ndef test_x(): pass\n", encoding="utf-8"
    )
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.test.mjs").write_text(
        'it.flaky("x", () => {});\n', encoding="utf-8"
    )
    report = build_report(tmp_path)
    assert report.entries == ()


def test_build_report_finds_real_files(tmp_path: Path) -> None:
    (tmp_path / "test_real.py").write_text(
        "@pytest.mark.flaky  # ticket: OF-1\ndef test_x(): pass\n", encoding="utf-8"
    )
    report = build_report(tmp_path)
    assert len(report.entries) == 1
    assert report.unreferenced == ()


def test_report_to_dict_counts_unreferenced() -> None:
    from tools.ci.flaky_quarantine_report import QuarantineEntry, QuarantineReport

    report = QuarantineReport(
        entries=(
            QuarantineEntry(path="a.py", line=1, ticket="OF-1"),
            QuarantineEntry(path="b.py", line=2, ticket=None),
        )
    )
    d = report.to_dict()
    assert d["unreferenced_count"] == 1
    assert len(d["quarantined"]) == 2


def test_scan_pytest_file_ignores_a_marker_in_a_string_or_a_comment(tmp_path: Path) -> None:
    """#4839: a marker's text inside a string literal, a docstring or a comment is not a marker;
    only a decorator is (the report reads tokens)."""
    f = tmp_path / "test_x.py"
    f.write_text(
        'FIXTURE = "@pytest.mark.flaky\\ndef test_thing(): pass\\n"\n'
        "def test_uses_it():\n"
        '    """@pytest.mark.flaky in a docstring is not a marker."""\n'
        "    # @pytest.mark.flaky in a comment is not one either\n"
        "    assert FIXTURE\n",
        encoding="utf-8",
    )
    assert scan_pytest_file(f, tmp_path) == []


def test_scan_pytest_file_reads_a_called_marker_on_its_own_line(tmp_path: Path) -> None:
    f = tmp_path / "test_x.py"
    f.write_text(
        "import pytest\n\n\n# ticket: OF-7\n@pytest.mark.flaky(reruns=0)\ndef test_thing():\n"
        "    assert True\n",
        encoding="utf-8",
    )
    (entry,) = scan_pytest_file(f, tmp_path)
    assert (entry.line, entry.ticket) == (5, "OF-7")


def test_scan_pytest_file_falls_back_to_the_line_scan_when_it_cannot_tokenize(
    tmp_path: Path,
) -> None:
    """A file that does not tokenize (here an unterminated string) is scanned line by line, as
    before, so a marker in it is never missed."""
    f = tmp_path / "test_x.py"
    f.write_text('"""unterminated\n@pytest.mark.flaky\ndef test_thing(): pass\n', encoding="utf-8")
    assert [e.line for e in scan_pytest_file(f, tmp_path)] == [2]


def test_this_files_fixture_strings_are_no_markers_of_its_own() -> None:
    """#4839: run over the repo, the report listed this file's fixture strings (lines 31 and 61)
    as unticketed markers; read as tokens, the file has none."""
    here = Path(__file__).resolve()
    assert scan_pytest_file(here, here.parents[2]) == []
