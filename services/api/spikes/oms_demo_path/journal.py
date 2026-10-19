"""The CSV files a run keeps while it runs: `orders.csv`, `cycles.csv` and `rest_calls.csv`.

A row is written whole and flushed to the operating system before `append` returns: the file is
opened for append and closed again for each row, so nothing waits in a buffer of this process and
a run that is aborted or killed (SIGKILL, the OOM killer) still leaves the record of what it sent.
One small write on a local file; it is not offloaded to a thread because the record of an order
must exist before the request that sends it.

A row is masked and leak-checked like every other output (C-12.2): a row that still fails the
check is withheld (one line naming the failed checks stands in for it), and a row that cannot be
written is logged, once per file. `append` never raises, and says by its return value whether the
row is on disk: the run sends no opening order whose row is not.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import structlog

from .scrub import LeakError, Scrubber


def _log() -> Any:
    return structlog.get_logger(__name__)


class Journal:
    """An append-only CSV file with a fixed header, written lazily: nothing exists on disk until
    the first row. A file that already holds rows keeps its header."""

    def __init__(self, path: Path, columns: Sequence[str], scrubber: Scrubber) -> None:
        self.path = path
        self._columns, self._scrubber = tuple(columns), scrubber
        self._started = False
        self._reported = False

    def append(self, row: Mapping[str, object]) -> bool:
        """Write `row` (a missing column is an empty cell; a key outside the columns is not
        written). `True` once the row itself is on disk; `False` when it was withheld by the
        leak check or could not be written."""
        try:
            text, written = self._text([row.get(column, "") for column in self._columns])
            self._write(text)
        except (OSError, ValueError, csv.Error) as exc:
            if not self._reported:
                self._reported = True
                _log().error("journal_unwritable", file=self.path.name, error=type(exc).__name__)
            return False
        return written

    def _text(self, cells: Sequence[object]) -> tuple[str, bool]:
        """The row as CSV with the run's known values masked, or, when the leak check still
        fails it, one line naming the failed checks (and `False`)."""
        line = self._line(cells)
        try:
            return self._scrubber.check(self._scrubber.mask_known(line)), True
        except LeakError as exc:
            _log().warning("output_withheld", file=self.path.name, patterns=exc.patterns)
            return self._line([f"withheld by the leak check: {', '.join(exc.patterns)}"]), False

    @staticmethod
    def _line(cells: Sequence[object]) -> str:
        out = io.StringIO()
        csv.writer(out).writerow(cells)
        return out.getvalue()

    def _write(self, text: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self._started and (not self.path.exists() or self.path.stat().st_size == 0):
            text = self._line(self._columns) + text
        with self.path.open("a", encoding="utf-8", newline="") as stream:
            stream.write(text)
        self._started = True
