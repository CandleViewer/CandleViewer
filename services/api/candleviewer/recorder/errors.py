"""Domain errors for the recorder module (M11)."""

from __future__ import annotations


class RecorderError(Exception):
    """Base exception for the M11 `recorder` module."""


class InvalidRecordedSymbolError(RecorderError):
    """A symbol or trigger reference failed validation (never reaches a topic)."""


class RecorderSymbolLimitError(RecorderError):
    """Adding the symbol would exceed `CV_RECORDER_MAX_SYMBOLS` (`recorder_symbol_limit`, 422)."""

    code = "recorder_symbol_limit"


class InvalidRecorderActorError(RecorderError):
    """A recorder action named no (or an empty / non-user) actor (C-2.9, C-12.4)."""


class RecorderSymbolNotManualError(RecorderError):
    """`update_manual` named a symbol that is not a manual entry: there is nothing to update."""


class RecorderSymbolNotRecordedError(RecorderError):
    """`set_pin` or `set_retention` named a symbol with no active `recorded_symbols` row, or one
    that went before the write: both need an active row."""


class RecorderGateOpenError(RecorderError):
    """`adopt_recorded` or `adopt_positions` ran after the warm-up gate opened: the database's
    view would overwrite live triggers, so adoption is refused once `positions_reloaded()` ran."""


class RecorderInvalidUpdateError(RecorderError):
    """`add_manual` or `update_manual` named a depth or a stream that `recorded_symbols` refuses
    (`rs_depth`, `stream_kind`); raised before any audit or write (the REST binding maps it to 422).
    """


class RecorderRelaxRefusedError(RecorderError):
    """A `restricted` caller asked to unpin a row a hidden cause holds, or to lower its
    `retention_days` (ruling 2026-10-24, C-12.4). Raised after the refusal's own record and before
    the change is audited or written; the REST binding maps it to 403."""

    def __init__(self) -> None:
        super().__init__("Only the owner can unpin this row or lower its retention")
