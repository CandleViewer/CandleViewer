"""#4664 (SR-015): the two second-factor routes share one per-address budget of refusals.

Each refusal of `/auth/mfa/verify` or `/auth/mfa/recovery` counts against the address; an address
over the budget is answered `429` `rate_limited` with a `Retry-After` at once, before the service
is asked to check anything, so no challenge is read and no attempt counted. A refusal caused by
the server (a store failure) is not the caller's attempt and does not count. Another address keeps
its own budget. No network, no sleeps (C-13.7): the budget's clock stands still.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

import httpx
from fastapi import FastAPI

from candleviewer.api.auth import make_auth_router
from candleviewer.auth.csrf import CsrfCodec
from candleviewer.auth.errors import MfaCodeInvalid, RecoveryCodeInvalid
from candleviewer.auth.models import MfaRecoveryCheck, MfaVerifiedResult, UserRecord
from candleviewer.auth.throttle import PerIpLoginThrottle
from tests.unit.api._fakes import AuditService, Identity, sessions
from tests.unit.auth.auth_fakes import make_user

_V, _R = "/auth/mfa/verify", "/auth/mfa/recovery"
_VERIFY = {"mfa_token": "t" * 20, "method": "totp", "code": "000000"}
_RECOVER = {"mfa_token": "t" * 20, "recovery_code": "zzzz-zzzz-zzzz"}
_BODY = {_V: _VERIFY, _R: _RECOVER}
_CSRF = CsrfCodec(b"\x05" * 32)
_BUDGET = 2
_INERT_DIGEST = "unused"  # stored-hash placeholder: no password is ever verified here


class _Mfa:
    """Refuses every check with *error*, or passes; counts the checks it was asked for."""

    def __init__(self, error: Exception | None, *, spend_error: Exception | None = None) -> None:
        self.error, self.spend_error, self.checks = error, spend_error, 0

    async def verify(self, *_args: object) -> MfaVerifiedResult:
        self.checks += 1
        if self.error is not None:
            raise self.error
        return MfaVerifiedResult(user_id=uuid.uuid4())

    async def check_recovery(self, *_args: object) -> MfaRecoveryCheck:
        self.checks += 1
        if self.error is not None:
            raise self.error
        return MfaRecoveryCheck(user_id=uuid.uuid4(), challenge_id=uuid.uuid4(), code_id="c")

    async def complete_recovery(self, check: MfaRecoveryCheck) -> None:
        if self.spend_error is not None:
            raise self.spend_error


class _Auth:
    is_active = mfa_is_active = sessions_is_active = True

    def __init__(self, mfa: _Mfa) -> None:
        self.mfa, self.login, self.sessions = mfa, None, sessions()

    async def find_user(self, user_id: str) -> UserRecord:
        user = make_user(username="u", email="u@x.test", password_hash=_INERT_DIGEST)
        return user.model_copy(update={"id": uuid.UUID(user_id)})


def _app(mfa: _Mfa) -> FastAPI:
    budget = PerIpLoginThrottle(max_attempts=_BUDGET, window_s=60.0, clock=lambda: 0.0)
    router = make_auth_router(
        cast(Any, _Auth(mfa)),
        AuditService(),
        identity=Identity(),
        csrf=_CSRF,
        mfa_refusal_budget=budget,
    )
    app = FastAPI()
    app.include_router(router)
    return app


def _client(app: FastAPI, ip: str = "10.0.0.1") -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, client=(ip, 50000))
    return httpx.AsyncClient(transport=transport, base_url="http://t")


async def test_mfa_verify_over_the_budget_is_rate_limited_before_any_check() -> None:
    mfa = _Mfa(MfaCodeInvalid("x"))
    async with _client(_app(mfa)) as client:
        for _ in range(_BUDGET):
            assert (await client.post(_V, json=_VERIFY)).status_code == 401
        over = await client.post(_V, json=_VERIFY)

    assert over.status_code == 429
    assert over.json()["code"] == "rate_limited"
    assert int(over.headers["Retry-After"]) >= 1
    assert over.json()["retry_after_seconds"] == int(over.headers["Retry-After"])
    assert mfa.checks == _BUDGET  # the answer over the budget asked nothing of the service


async def test_mfa_recovery_over_the_budget_is_rate_limited_before_any_check() -> None:
    mfa = _Mfa(RecoveryCodeInvalid("x"))
    async with _client(_app(mfa)) as client:
        for _ in range(_BUDGET):
            assert (await client.post(_R, json=_RECOVER)).status_code == 401
        over = await client.post(_R, json=_RECOVER)

    assert (over.status_code, over.json()["code"]) == (429, "rate_limited")
    assert mfa.checks == _BUDGET


async def test_mfa_refusals_of_either_route_count_against_one_budget() -> None:
    mfa = _Mfa(MfaCodeInvalid("x"))
    async with _client(_app(mfa)) as client:
        for _ in range(_BUDGET):
            assert (await client.post(_V, json=_VERIFY)).status_code == 401
        over = await client.post(_R, json=_RECOVER)

    assert over.status_code == 429


async def test_mfa_budget_is_kept_per_address() -> None:
    mfa = _Mfa(MfaCodeInvalid("x"))
    app = _app(mfa)
    async with _client(app, "10.0.0.1") as first:
        for _ in range(_BUDGET):
            await first.post(_V, json=_VERIFY)
        assert (await first.post(_V, json=_VERIFY)).status_code == 429
    async with _client(app, "10.0.0.2") as second:
        assert (await second.post(_V, json=_VERIFY)).status_code == 401


async def test_mfa_recovery_store_failure_does_not_count_against_the_budget() -> None:
    mfa = _Mfa(None, spend_error=OSError("statement timeout"))
    async with _client(_app(mfa)) as client:
        for _ in range(_BUDGET + 1):
            assert (await client.post(_R, json=_RECOVER)).status_code == 401

    assert mfa.checks == _BUDGET + 1  # every attempt reached the check
