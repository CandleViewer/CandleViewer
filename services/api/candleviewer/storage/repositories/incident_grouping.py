"""How an `error` or `critical` system event maps onto its incident (E42-T05,
`21-database-schema.md` 3.10.2a): the message normaliser, the grouping signature, and the redacted
`title` and `detail` the materialiser stores. Pure, with no driver, so the writers'
transactions and the tests share one definition.

`normalise_message` replaces what varies between occurrences of one fault with a placeholder, in
this order: UUIDs become `<id>`; timestamps (an ISO 8601 date, with its time and offset if
present) become `<ts>`; instrument symbols (an upper-case `symbol_code` ending in `USDT`, the only
category traded) become `<symbol>`; other ids (a `0x` hex literal, or a run of 8 or more letters
and digits that mixes both, such as a hex digest) become `<id>`; numbers (a digit run, with its
decimal or thousands separators) become `<n>`. Whitespace is then folded. The placeholders are
the contract's (`listIncidents`: "parquet write failed for <symbol> segment <n>"). No digit
survives, and one message always normalises to the same text.

`incident_signature` is the first 16 hex characters of sha256 over the JSON array
`[component, kind, normalised message]`, an encoding in which no two triples share an input.
`title` is the normalised message and `detail` the event's own message, each through
`redact_text` and then cut to the contract's length (a cut first could split a secret into a stub
the redactor no longer matches). A `detail` that cannot be redacted is `None`; a `title` that
cannot is empty, since the column is `NOT NULL`. Either failure is logged by class only.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Final

import structlog

from candleviewer.observability.redaction import redact_text

#: The severities that are incidents (`inc_severity`); every other event is not grouped.
INCIDENT_SEVERITIES: Final = frozenset({"error", "critical"})
#: The contract's `Incident.title` / `detail` `maxLength` (the DDL has no cap).
TITLE_MAX: Final = 200
DETAIL_MAX: Final = 2000

_ALNUM = "0-9A-Za-z"
_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:[.,]\d+)?)?(?:Z|[+-]\d{2}(?::?\d{2})?)?)?"
)
_UUID = re.compile(
    rf"(?<![{_ALNUM}])[0-9a-fA-F]{{8}}(?:-[0-9a-fA-F]{{4}}){{3}}-[0-9a-fA-F]{{12}}(?![{_ALNUM}])"
)
_SYMBOL = re.compile(rf"(?<![{_ALNUM}])[0-9A-Z]{{1,16}}USDT(?![{_ALNUM}])")
_ID = re.compile(
    rf"(?<![{_ALNUM}])(?:0[xX][0-9a-fA-F]+"
    rf"|(?=[{_ALNUM}]*[0-9])(?=[{_ALNUM}]*[A-Za-z])[{_ALNUM}]{{8,}})(?![{_ALNUM}])"
)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_SPACE = re.compile(r"\s+")
_STEPS: Final = (
    (_UUID, "<id>"),
    (_TIMESTAMP, "<ts>"),
    (_SYMBOL, "<symbol>"),
    (_ID, "<id>"),
    (_NUMBER, "<n>"),
)


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def normalise_message(message: str) -> str:
    """The message with its timestamps, ids, symbols and numbers replaced, whitespace folded."""
    for pattern, placeholder in _STEPS:
        message = pattern.sub(placeholder, message)
    return _SPACE.sub(" ", message).strip()


def incident_signature(component: str, kind: str, normalised: str) -> str:
    """16 lowercase hex of sha256 over `[component, kind, normalised]` as ASCII JSON."""
    encoded = json.dumps([component, kind, normalised], separators=(",", ":"))
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class IncidentOccurrence:
    """What one grouped event contributes to its incident row; the time is the event's own."""

    component: str
    signature: str
    severity: str
    title: str
    detail: str | None


def _redacted(field: str, text: str, cap: int) -> str | None:
    try:
        return redact_text(text)[:cap]
    except Exception as exc:  # a text that cannot be redacted is never stored
        _log().error("incident_redaction_failed", field=field, error=type(exc).__name__)
        return None


def incident_occurrence(
    *, component: str, kind: str, severity: str, message: str
) -> IncidentOccurrence:
    """The incident side of an `error` or `critical` system event; `ValueError` for any other
    severity, which is never grouped (`inc_severity`)."""
    if severity not in INCIDENT_SEVERITIES:
        raise ValueError(f"not an incident severity: {severity!r}")
    normalised = normalise_message(message)
    return IncidentOccurrence(
        component=component,
        signature=incident_signature(component, kind, normalised),
        severity=severity,
        title=_redacted("title", normalised, TITLE_MAX) or "",
        detail=_redacted("detail", message, DETAIL_MAX),
    )
