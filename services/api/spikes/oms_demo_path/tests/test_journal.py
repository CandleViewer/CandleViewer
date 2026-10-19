"""The journals a run keeps while it runs (`orders.csv`, `cycles.csv`, `rest_calls.csv`): a row
is on disk, whole, when `append` returns, so a run that is aborted or killed still leaves its
record (#843). Rows are masked and leak-checked like every other output (C-12.2)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from structlog.testing import capture_logs

from candleviewer.secrets import Secret
from spikes.oms_demo_path.journal import Journal
from spikes.oms_demo_path.scrub import MASK, Scrubber

#: Key-shaped values, derived at run time (no secret-shaped literal in the source).
KEY_ID = "k" + hashlib.sha256(b"journal key id").hexdigest()[:19]
UNKNOWN = "k" + hashlib.sha256(b"an unknown key-shaped value in a row").hexdigest()[:19]
COLUMNS = ("cycle", "order_link_id", "note")


def _journal(path: Path) -> Journal:
    return Journal(path, COLUMNS, Scrubber([Secret(KEY_ID)]))


def _lines(path: Path) -> list[str]:
    """What a second reader finds on disk: only what the journal flushed to the system."""
    return path.read_text(encoding="utf-8").splitlines()


def test_a_row_is_on_disk_when_append_returns(tmp_path: Path) -> None:
    path = tmp_path / "run" / "orders.csv"
    assert _journal(path).append({"cycle": 0, "order_link_id": "cvd-a", "note": "first"}) is True
    assert _lines(path) == ["cycle,order_link_id,note", "0,cvd-a,first"]


def test_nothing_is_created_before_the_first_row(tmp_path: Path) -> None:
    _journal(tmp_path / "run" / "orders.csv")
    assert not (tmp_path / "run").exists()


def test_each_row_follows_the_last_and_the_header_is_written_once(tmp_path: Path) -> None:
    path = tmp_path / "orders.csv"
    journal = _journal(path)
    journal.append({"cycle": 0, "order_link_id": "cvd-a", "note": ""})
    journal.append({"cycle": 1, "order_link_id": "cvd-b", "note": ""})
    assert _lines(path) == ["cycle,order_link_id,note", "0,cvd-a,", "1,cvd-b,"]


def test_a_second_journal_on_the_same_file_adds_no_second_header(tmp_path: Path) -> None:
    path = tmp_path / "orders.csv"
    _journal(path).append({"cycle": 0, "order_link_id": "cvd-a", "note": ""})
    _journal(path).append({"cycle": 1, "order_link_id": "cvd-b", "note": ""})
    assert _lines(path) == ["cycle,order_link_id,note", "0,cvd-a,", "1,cvd-b,"]


def test_a_missing_cell_is_empty_and_a_key_outside_the_columns_is_not_written(
    tmp_path: Path,
) -> None:
    path = tmp_path / "orders.csv"
    _journal(path).append({"order_link_id": "cvd-a", "extra": "never"})
    assert _lines(path) == ["cycle,order_link_id,note", ",cvd-a,"]


def test_a_cell_with_a_comma_or_a_quote_stays_one_cell(tmp_path: Path) -> None:
    path = tmp_path / "orders.csv"
    _journal(path).append({"cycle": 0, "order_link_id": "cvd-a", "note": 'a, "b"'})
    assert _lines(path)[1] == '0,cvd-a,"a, ""b"""'


def test_a_known_value_in_a_row_is_masked(tmp_path: Path) -> None:
    path = tmp_path / "orders.csv"
    assert _journal(path).append({"cycle": 0, "order_link_id": "cvd-a", "note": KEY_ID}) is True
    assert _lines(path)[1] == f"0,cvd-a,{MASK}"
    assert KEY_ID not in path.read_text(encoding="utf-8")


def test_a_row_that_fails_the_leak_check_is_withheld_and_reported(tmp_path: Path) -> None:
    path = tmp_path / "orders.csv"
    journal = _journal(path)
    with capture_logs() as logs:
        written = journal.append({"cycle": 0, "order_link_id": "cvd-a", "note": UNKNOWN})
    assert written is False
    assert _lines(path) == ["cycle,order_link_id,note", "withheld by the leak check: key-shape"]
    assert UNKNOWN not in path.read_text(encoding="utf-8")
    event = {"event": "output_withheld", "file": "orders.csv", "patterns": ["key-shape"]}
    assert event | {"log_level": "warning"} in logs
    assert journal.append({"cycle": 1, "order_link_id": "cvd-b", "note": ""}) is True


def test_a_row_that_cannot_be_written_is_reported_once_and_never_raised(tmp_path: Path) -> None:
    path = tmp_path / "orders.csv"
    path.mkdir()  # a directory where the file goes: every open for append fails
    journal = _journal(path)
    with capture_logs() as logs:
        first = journal.append({"cycle": 0, "order_link_id": "cvd-a", "note": ""})
        second = journal.append({"cycle": 1, "order_link_id": "cvd-b", "note": ""})
    assert (first, second) == (False, False)
    failed = [entry for entry in logs if entry["event"] == "journal_unwritable"]
    assert failed == [
        {
            "event": "journal_unwritable",
            "file": "orders.csv",
            "error": "IsADirectoryError",
            "log_level": "error",
        }
    ]
