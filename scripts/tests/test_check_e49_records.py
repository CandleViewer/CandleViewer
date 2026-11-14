"""E49-Q02: the disposition check passes the real run records and fails injected defects."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import check_e49_records as chk

HEAD = "| " + " | ".join(chk.COLUMNS) + " |\n|" + " --- |" * len(chk.COLUMNS) + "\n"


def _row(status: str, row_id: str = "E49-R9-01", actual: str = "x") -> str:
    cells = [row_id, "C7", "O7.1", "Area", "Steps", "Exp", actual, "P3", status, "ev"]
    return "| " + " | ".join(cells) + " |\n"


def _classify(status: str, **kw: str) -> str:
    rows = chk.parse_rows(HEAD + _row(status, **kw))
    assert len(rows) == 1
    return chk.classify(rows[0])


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        ("bug P1 #123", "bug"),
        ("bug P0; filed as #9", "bug"),
        ("bug P2", "pending"),
        ("not-a-defect: by design", "not-a-defect"),
        ("not-a-defect:", "undecided"),
        ("not-a-defect", "undecided"),
        ("security-private: reported privately", "security-private"),
        ("pending filing; owner E49-S03", "pending"),
        ("bug P4 #1", "undecided"),
        ("investigating", "undecided"),
        ("", "undecided"),
    ],
)
def test_classify_status(status: str, kind: str) -> None:
    assert _classify(status) == kind


def test_empty_cell_and_bad_id_are_undecided() -> None:
    assert _classify("not-a-defect: ok", actual="") == "undecided"
    assert _classify("not-a-defect: ok", row_id="R9-1") == "undecided"


def test_closing_counts_pending_as_undecided() -> None:
    rows = chk.parse_rows(HEAD + _row("pending filing") + _row("bug P2 #5", "E49-R9-02"))
    assert len(chk.summarize(rows)[1]) == 0
    assert len(chk.summarize(rows, closing=True)[1]) == 1


def test_non_findings_tables_are_ignored() -> None:
    text = "| Severity | Count |\n| --- | --- |\n| P0 | 0 |\n\n" + HEAD + _row("not-a-defect: r")
    assert len(chk.parse_rows(text)) == 1


def test_main_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good = tmp_path / "e49-run-9-findings.md"
    good.write_text(HEAD + _row("not-a-defect: r"), encoding="utf-8")
    assert chk.main([str(good), "--root", str(tmp_path)]) == 0
    assert "undecided = 0" in capsys.readouterr().out
    good.write_text(HEAD + _row("maybe"), encoding="utf-8")
    assert chk.main([str(good), "--root", str(tmp_path)]) == 1
    assert "undecided = 1" in capsys.readouterr().out


def test_file_without_rows_or_with_bad_header_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = tmp_path / "e49-run-8-findings.md"
    good.write_text(HEAD + _row("not-a-defect: r"), encoding="utf-8")
    empty = tmp_path / "e49-run-9-findings.md"
    empty.write_text("# no table\n", encoding="utf-8")
    assert chk.main([str(good), str(empty), "--root", str(tmp_path)]) == 1
    assert "no findings rows" in capsys.readouterr().err
    empty.write_text(HEAD.replace("Oracle", "Oracl", 1) + _row("not-a-defect: r"), encoding="utf-8")
    assert chk.main([str(good), str(empty), "--root", str(tmp_path)]) == 1
    assert "exact schema columns" in capsys.readouterr().err


def test_shipped_run_records_have_no_undecided_row() -> None:
    files = sorted(ROOT.glob(chk.DEFAULT_GLOB))
    assert files
    rows = [r for f in files for r in chk.parse_rows(f.read_text(encoding="utf-8"), f.name)]
    assert rows
    assert chk.summarize(rows)[1] == []


def test_blank_line_inside_table_fails_closed() -> None:
    text = HEAD + _row("not-a-defect: r") + "\n" + _row("maybe", "E49-R9-02")
    with pytest.raises(ValueError, match="outside a findings table"):
        chk.parse_rows(text)


def test_note_line_inside_table_fails_closed() -> None:
    text = HEAD + _row("not-a-defect: r") + "note\n" + _row("maybe", "E49-R9-02")
    with pytest.raises(ValueError, match="outside a findings table"):
        chk.parse_rows(text)


def test_header_case_variant_is_rejected() -> None:
    text = "| Id | Charter | Oracle |\n| --- | --- | --- |\n" + _row("not-a-defect: r")
    with pytest.raises(ValueError, match="exact schema columns"):
        chk.parse_rows(text)


def test_bash_ids_parse() -> None:
    assert _classify("not-a-defect: r", row_id="E49-B2-07") == "not-a-defect"
    assert _classify("not-a-defect: r", row_id="E49-X2-07") == "undecided"


def test_pending_filing_requires_a_word_boundary() -> None:
    assert _classify("pending filingXYZ") == "undecided"


def test_duplicate_id_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rec = tmp_path / "e49-run-9-findings.md"
    rec.write_text(HEAD + _row("not-a-defect: r") + _row("not-a-defect: r"), encoding="utf-8")
    assert chk.main([str(rec), "--root", str(tmp_path)]) == 1
    assert "duplicate id" in capsys.readouterr().err


def test_record_outside_root_or_symlink_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "e49-run-9-findings.md"
    outside.write_text(HEAD + _row("not-a-defect: r"), encoding="utf-8")
    assert chk.main([str(outside), "--root", str(root)]) == 1
    assert "inside --root" in capsys.readouterr().err
    link = root / "e49-run-8-findings.md"
    link.symlink_to(outside)
    assert chk.main([str(link), "--root", str(root)]) == 1
    assert "inside --root" in capsys.readouterr().err


def test_closing_message_names_pending_filing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rec = tmp_path / "e49-run-9-findings.md"
    rec.write_text(HEAD + _row("pending filing"), encoding="utf-8")
    assert chk.main([str(rec), "--root", str(tmp_path), "--closing"]) == 1
    assert "not allowed with --closing" in capsys.readouterr().out
