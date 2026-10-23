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
    """`set_pin` named a symbol with no active `recorded_symbols` row: a pin needs a row."""


class RecorderInvalidUpdateError(RecorderError):
    """`add_manual` or `update_manual` named a depth or a stream that `recorded_symbols` refuses
    (`rs_depth`, `stream_kind`); raised before any audit or write (the REST binding maps it to 422).
    """
