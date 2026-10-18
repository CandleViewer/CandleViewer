"""E27-T03 (#836) composition guard: the deployed `create_app()` on the real backend attaches the
stored-key self-check, bound to the process environment, and a stored key that fails it at
start-up latches order entry off and degrades `/readyz` (the ticket's "Boot assertion degrades
the app"). The fake backend attaches none. Only the store's SQL edges, the audit sink and the
exchange calls are faked (no Postgres, no network); the job, its wiring, the gate and the routes
are the deployed ones."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

import candleviewer.app as appmod
from candleviewer.accounts.selfcheck import FAILED
from candleviewer.audit.actions import validate_action
from candleviewer.exchange.bybit.key_info import ApiKeyFacts, parse_key_info
from candleviewer.exchange.bybit.service import ExchangeBybitService
from candleviewer.observability.health import HealthStatus
from candleviewer.settings import Environment, Settings
from candleviewer.storage.repositories.accounts import (
    ExchangeAccountRow,
    PolicyDisarm,
    SelfCheckTargetRow,
)
from candleviewer.storage.repositories.key_selfcheck_sqlalchemy import SqlAlchemyKeySelfCheckStore

FIXTURES = Path(__file__).parents[2] / "fixtures" / "key_verification"
NOW = datetime(2026, 10, 15, 9, tzinfo=UTC)
KEY, ACCOUNT, UID = UUID(int=11), UUID(int=1), "1000001"
_STORE_EDGES = (
    "targets", "record_error", "disable_trading", "owed_disarms", "mark_disarm_audited",
)  # fmt: skip


class _Edges:
    """The store's SQL edges over one armed testnet key, the audit sink and the venue's calls,
    which find a withdrawal right on the key."""

    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    async def targets(self) -> tuple[SelfCheckTargetRow, ...]:
        account = ExchangeAccountRow(
            ACCOUNT, "bybit", "testnet", "main", UID, None, "fx", "accent.neutral", True, True,
            "one_way", "cross", "UNIFIED", "USDT", None, None, 5, None, NOW, NOW, None,
        )  # fmt: skip
        return (SelfCheckTargetRow(KEY, False, NOW, account),)

    async def record_error(self, key_id: UUID, *, code: str, at: datetime) -> bool:
        self.events.append(("error", code))
        return True

    async def disable_trading(self, account_id: UUID, *, code: str, at: datetime) -> bool:
        self.events.append(("disable", account_id))
        return True

    async def owed_disarms(self) -> tuple[PolicyDisarm, ...]:
        return ()  # no disarm of an earlier process is owed its record

    async def mark_disarm_audited(self, disarm: PolicyDisarm, *, at: datetime) -> bool:
        self.events.append(("mark", disarm.account_id))
        return True

    async def emit(self, action: str, **_fields: Any) -> None:
        validate_action(action)
        self.events.append(("audit", action))

    def key_verification_calls(self, env: str, *_args: Any, **_kwargs: Any) -> Any:
        self.events.append(("calls", env))
        return self

    async def key_info(self) -> ApiKeyFacts:
        body = json.loads((FIXTURES / "key_info_trade.json").read_text(encoding="utf-8"))
        body["result"]["permissions"]["Wallet"] = ["Withdraw"]
        return parse_key_info(body)

    async def aclose(self) -> None:
        self.events.append(("aclose", None))


def _real() -> Settings:
    return Settings(
        storage_backend="real",
        environment=Environment.TESTNET,
        egress_ip="203.0.113.7",  # the key's whitelist (fixture): only the withdrawal right fails
        auth_pepper=SecretStr("test-pepper"),
        auth_totp_key_hex=SecretStr("11" * 32),
        auth_recovery_hmac_key_hex=SecretStr("22" * 32),
        auth_csrf_key_hex=SecretStr("33" * 32),
    )


def _readyz(app: Any) -> dict[str, Any]:
    body: dict[str, Any] = TestClient(app, client=("127.0.0.1", 50000)).get("/readyz").json()
    return body


@pytest.fixture
def deployed() -> Iterator[SimpleNamespace]:
    """The real-backend app with only the edges faked; the row-gauge store (Postgres) is off."""
    edges = _Edges()
    with pytest.MonkeyPatch.context() as mp:
        for name in _STORE_EDGES:
            mp.setattr(SqlAlchemyKeySelfCheckStore, name, _delegate(edges, name))
        calls = "key_verification_calls"
        mp.setattr(ExchangeBybitService, calls, _delegate(edges, calls))
        mp.setattr(appmod, "_build_accounts_counts", lambda _settings: None)
        app = appmod.create_app(_real())  # nothing else injected: the deployed composition
        app.state.app_context.audit._writer = edges
        yield SimpleNamespace(app=app, ctx=app.state.app_context, edges=edges)


def _delegate(edges: _Edges, name: str) -> Any:
    return lambda _self, *args, **kwargs: getattr(edges, name)(*args, **kwargs)


def test_the_real_backend_attaches_a_self_check_bound_to_the_process_environment(
    deployed: SimpleNamespace,
) -> None:
    check = deployed.ctx.accounts._selfcheck
    assert check is not None and (check._env, check._store._env) == ("testnet", "testnet")
    assert check._gate is deployed.ctx.oms_read_only_gate


def test_the_fake_backend_attaches_no_self_check() -> None:
    ctx = appmod.create_app(Settings(environment=Environment.TESTNET)).state.app_context
    assert ctx.accounts._selfcheck is None


async def test_a_stored_key_failing_at_boot_latches_order_entry_and_degrades_readyz(
    deployed: SimpleNamespace,
) -> None:
    ctx = deployed.ctx
    assert _readyz(deployed.app)["status"] == "ok"  # not started: no accounts check yet
    await ctx.accounts.start(ctx)  # the supervisor's call: the boot assertion runs here
    try:
        assert ctx.oms_read_only_gate.reason_code == FAILED
        assert ctx.accounts.health().status is HealthStatus.DEGRADED
        body = _readyz(deployed.app)
    finally:
        await ctx.accounts.stop(1.0)
    accounts = {"name": "accounts", "ok": False, "detail": "1 stored key(s) fail the self-check"}
    assert body["status"] == "degraded" and accounts in body["checks"]
    assert deployed.edges.events == [
        ("calls", "testnet"), ("aclose", None), ("audit", "account.tested"),
        ("error", "key_withdraw_permission"), ("disable", ACCOUNT),
        ("audit", "account.disabled_by_policy"), ("mark", ACCOUNT),
    ]  # fmt: skip
