"""Domain errors for the ws module (M23)."""

from __future__ import annotations

from typing import Any

from candleviewer.observability.metrics import Counter
from candleviewer.ws._generated.error_codes import ERROR_META, WS_ERROR_CODES, ErrorCode

cv_ws_errors_total = Counter(
    "cv_ws_errors_total", "WS err frames built, by catalogue code.", ["code"]
)


class WsError(Exception):
    """Base exception for the M23 `ws` module."""


class UnknownErrorCode(WsError):
    """An error code outside the generated 23-ws-protocol.md 10.2 catalogue was emitted (S10)."""


def build_ws_error(
    code: str,
    *,
    id: str | None = None,
    ch: str | None = None,
    rs: str | None = None,
    message: str | None = None,
    field: str | None = None,
    request_id: str | None = None,
    close: bool = False,
) -> dict[str, Any]:
    """The one sanctioned ``err`` frame builder (requirement S10).

    Raises ``UnknownErrorCode`` for a code that is not in the generated WS catalogue.
    ``message`` defaults to the code's catalogue title (``common#/$defs/error`` requires one).
    ``internal_error`` always carries only its generic title, plus ``request_id``: no caller
    text, so no exception text, stack trace or SQL can reach a client through this path.
    ``rs`` (a canonical session id) goes on the envelope beside ``ch`` only (§7.5, #3218).
    """
    try:
        known = ErrorCode(code)
    except ValueError:
        raise UnknownErrorCode(f"error code {code!r} is not in the WS catalogue") from None
    if known not in WS_ERROR_CODES:
        raise UnknownErrorCode(f"error code {code!r} is REST-only, not legal on the WS")
    cv_ws_errors_total.labels(code).inc()
    meta = ERROR_META[known]
    own = message is not None and known is not ErrorCode.INTERNAL_ERROR
    payload: dict[str, Any] = {
        "code": code,
        "message": message if own else meta.title,
        "retryable": meta.retryable,
        "close": close,
    }
    if field is not None:
        payload["field"] = field
    if request_id is not None:
        payload["request_id"] = request_id
    frame: dict[str, Any] = {"t": "err", "p": payload}
    if id is not None:
        frame["id"] = id
    if ch is not None:
        frame["ch"] = ch
        if rs is not None:
            frame["rs"] = rs
    return frame
