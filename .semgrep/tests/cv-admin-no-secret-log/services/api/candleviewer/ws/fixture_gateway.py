"""Fixtures for cv-admin-no-secret-log's one sanitizer by name: the ids that ws/gateway.py's
`run_auth` gets back from `authenticate(token)` are not the token (E42-X03)."""

import structlog


def _log() -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(__name__)


def make_gateway(authenticate: object) -> tuple[object, object]:
    async def run_auth(frame: dict[str, object]) -> None:
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
