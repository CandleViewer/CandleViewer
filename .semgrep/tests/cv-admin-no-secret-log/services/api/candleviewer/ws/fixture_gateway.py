"""Fixtures for cv-admin-no-secret-log's one sanitizer: the ids that ws/gateway.py's
`run_auth(conn, frame)` gets back from `authenticate(token)` are not the token (E42-X03). It is
bound to that signature, so another function of the name gets no exemption."""

from typing import Any

import structlog


class _Connection:
    """ws/gateway.py's per-socket state, as the real signature names it."""


def _log() -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(__name__)


def make_gateway(authenticate: object) -> tuple[object, object]:
    async def run_auth(conn: _Connection, frame: dict[str, Any]) -> None:
        token = frame.get("access_token")
        result = await authenticate(token)
        session_id, user_id = result[0], result[1]
        structlog.contextvars.bind_contextvars(user_id=str(user_id), session_id=session_id)  # ok: cv-admin-no-secret-log
        _log().info("ws auth refused", token=token)  # ruleid: cv-admin-no-secret-log

    async def run_reauth(frame: dict[str, object]) -> None:
        token = frame.get("access_token")
        result = await authenticate(token)
        _log().info("ws re-authenticated", session_id=result[0])  # ruleid: cv-admin-no-secret-log

    return run_auth, run_reauth


def authenticate(token: str) -> tuple[str, str]:
    return token, token


def run_auth(token: str) -> None:  # the name alone earns nothing
    result = authenticate(token)
    _log().info("auth", session_id=result[0])  # ruleid: cv-admin-no-secret-log
