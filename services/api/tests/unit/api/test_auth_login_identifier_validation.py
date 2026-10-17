"""A login identifier holding U+0000 is refused by request validation, like any other invalid
body: the redacted 422 (`api.error_redaction`), answered before `LoginService`. Nothing is
audited and the identifier is not echoed. Through the real router, `LoginService` and
`AuditWriter`."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import httpx
from fastapi import FastAPI

from candleviewer.api.auth import make_auth_router
from candleviewer.api.error_redaction import install_error_redaction
from candleviewer.audit.writer import AuditWriter
from candleviewer.auth.csrf import CsrfCodec
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.login_service import LoginService
from candleviewer.domain.text import UNSTORABLE_TEXT
from tests.unit.audit.audit_fakes import FakeClock, PgTextAuditRepository
from tests.unit.auth.auth_fakes import FakeUserRepository

_PEER = ("127.0.0.1", 50000)
_GUESS = "not-the-password"


class _Auth:
    is_active = mfa_is_active = True
    sessions_is_active = False
    mfa = None

    def __init__(self, login: LoginService) -> None:
        self.login = login


class _Audit:
    is_active = True

    def __init__(self, writer: AuditWriter) -> None:
        self.writer = writer


async def test_failed_login_with_a_nul_identifier_is_refused_and_not_audited(
    tmp_path: Path,
) -> None:
    repo = PgTextAuditRepository()
    writer = AuditWriter(repo, str(tmp_path / "a.wal"), clock=FakeClock(), sleep=repo.retry_sleep)
    login = LoginService(FakeUserRepository(), Hasher(pepper="p"))
    app = FastAPI()
    install_error_redaction(app)
    auth = cast(Any, _Auth(login))
    app.include_router(make_auth_router(auth, _Audit(writer), csrf=CsrfCodec(b"\x05" * 32)))
    transport = httpx.ASGITransport(app=app, client=_PEER)
    await writer.start()
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        body = {"identifier": "\x00ab", "password": _GUESS}
        response = await client.post("/auth/login", json=body)
    await writer.flush(5)
    await writer.stop(1)
    assert response.status_code == 422
    assert response.json() == {
        "type": "https://candleviewer.local/errors/validation_failed",
        "title": "Request validation failed",
        "status": 422,
        "code": "validation_failed",
        "errors": [
            {
                "field": "body.identifier",
                "rule": "value_error",
                "message": f"Value error, {UNSTORABLE_TEXT}",
            }
        ],
    }
    assert repo.rows == []
