"""E27-T03 slice 2b4 (#836): key import's composition-root wiring. `Rig` (also the route tests')
is `test_key_import.World` with the real candidate port: M2 on its in-memory store (demo) and the
adapter on an injected `MockTransport` answering with the documented-shape key-verification
replies (their README). Fixed low-entropy key vectors only (`_vectors`). No network.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
import respx
from pydantic import SecretStr

from candleviewer import key_import_wiring as wiring
from candleviewer.accounts.errors import AccountConflictError
from candleviewer.accounts.key_import import KeyImport, KeyImportFailed
from candleviewer.accounts.repository import AccountsRepository
from candleviewer.accounts.verification import VerificationPolicy
from candleviewer.app import AppContext
from candleviewer.exchange.bybit.key_info import KEY_INFO_PATH, PROBE_PATH
from candleviewer.exchange.bybit.service import ExchangeBybitService
from candleviewer.observability.secret_type import Secret as Pasted
from candleviewer.secrets import (
    CredentialUnavailable,
    KekUnavailable,
    mint_candidate_keys,
)
from candleviewer.secrets.store import InMemoryCredentialStore
from candleviewer.settings import Environment, Settings
from candleviewer.storage.repositories.accounts import AccountsStoreConflictError
from tests.unit.accounts.test_key_import import World, key_row
from tests.unit.accounts.test_key_selfcheck import EGRESS, NOW
from tests.unit.credentials_m2._service_fakes import _ctx, _Src, _svc
from tests.unit.credentials_m2._vectors import API_KEY, API_SECRET, KEK_V1, AuditLog

FIXTURES = Path(__file__).parent.parent / "fixtures" / "key_verification"
REPLIES = {KEY_INFO_PATH: "key_info_trade.json", PROBE_PATH: "wallet_balance.json"}


class Rig(World):
    """`World` with the real candidate port: M2 on demo, the adapter on a recording transport.
    The accounts store lists and promotes the rows M2 stored."""

    def __init__(
        self, *, skew_ms: int = 0, swap: dict[str, str] | None = None, withdraw: bool = False
    ) -> None:
        super().__init__()
        self.sent: list[httpx.Request] = []
        self.skew_ms, self.swap, self.withdraw = skew_ms, swap or {}, withdraw
        self.m2, self.m2_audit, self.capability = InMemoryCredentialStore(), AuditLog(), None
        self.adapter = ExchangeBybitService(rest_transport=httpx.MockTransport(self.answer))

    def answer(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(request)
        name = self.swap.get(request.url.path, REPLIES[request.url.path])
        body = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        if name == "key_info_trade.json" and self.withdraw:
            body["result"]["permissions"]["Wallet"] = ["Withdraw"]
        if name == "wallet_balance.json":  # the exchange's clock, ahead of the host by the skew
            body["time"] = int(time.time() * 1000) + self.skew_ms
        return httpx.Response(200, json=body)

    async def list_keys(self, scope: Any, account_id: Any) -> tuple[Any, ...]:
        self.events.append(("list",))
        rows = [(k, r) for k, r in self.m2.rows.items() if not r["revoked"]]
        return tuple(key_row(k, r["status"], r["label"]) for k, r in rows)

    async def transition_key_status(self, scope: Any, account_id: Any, key_id: Any, *,
                                    expected: str, new: str) -> Any:  # fmt: skip
        self.events.append(("transition", key_id, expected, new, scope.user_id))
        if self.transition_error is not None:
            raise self.transition_error
        self.m2.rows[key_id]["status"] = new
        return key_row(key_id, new, self.m2.rows[key_id]["label"], self.verified.read_only)

    async def boot(self) -> None:
        svc = _svc(_Src(KEK_V1, 1), store=self.m2, audit=self.m2_audit)
        await svc.start(_ctx())
        self.m2_audit.records.clear()  # the boot's own records
        self.capability = mint_candidate_keys(svc)

    def importer(self, keys: Any = None) -> KeyImport:
        verifier = wiring.CandidateVerifier(
            keys or self.capability, self.adapter, env="demo", recv_window_ms=5000,
            clock_offset_ms=lambda: 0,
        )  # fmt: skip
        return KeyImport(
            AccountsRepository(self),  # type: ignore[arg-type]
            verifier, self, audit=self, policy=VerificationPolicy(egress_ip=EGRESS), env="demo",
            clock=lambda: NOW,
        )  # fmt: skip

    async def imports(self, keys: Any, **fields: Any) -> Any:
        self.flow = self.importer(keys)
        pair = {"api_key": Pasted(API_KEY), "api_secret": Pasted(API_SECRET), **fields}
        with respx.mock():  # nothing but the injected transport answers
            return await self.run(**pair)


class Refusing:
    """An M2 capability that refuses as M2 does, before any hold."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    async def store_if_verified(self, *_args: Any, **_kwargs: Any) -> None:
        raise self.error


_SHAPE = [("body", "credential_shape_invalid")]


@pytest.mark.parametrize(
    ("error", "code", "fields"),
    [
        (KekUnavailable("kek_unavailable"), "kek_unavailable", []),
        (CredentialUnavailable("credential_shape_invalid"), "validation_failed", _SHAPE),
        (CredentialUnavailable("candidate_timeout"), "exchange_unavailable", []),
        (CredentialUnavailable("audit_timeout"), "audit_unavailable", []),
        (CredentialUnavailable("audit_unavailable"), "audit_unavailable", []),
        (CredentialUnavailable("store_failed"), "store_unavailable", []),
        (CredentialUnavailable("store_unavailable"), "store_unavailable", []),
        (CredentialUnavailable("candidate_not_removed"), "store_unavailable", []),
    ],
)
async def test_m2_refusals_become_the_imports_problem_codes(
    error: Exception, code: str, fields: list[tuple[str, str]]
) -> None:
    with pytest.raises(KeyImportFailed) as failed:
        await Rig().imports(Refusing(error))
    assert (failed.value.code, [e[:2] for e in failed.value.errors]) == (code, fields)
    assert failed.value.__cause__ is None  # nothing of M2's error goes on


@pytest.mark.parametrize(
    "error", [CredentialUnavailable("candidate_unavailable"), RuntimeError("defect")]
)
async def test_any_other_error_propagates_unchanged(error: Exception) -> None:
    with pytest.raises(type(error)) as raised:
        await Rig().imports(Refusing(error))
    assert raised.value is error


async def test_a_failed_promotion_is_undone_by_m2_so_a_retry_succeeds() -> None:
    rig = Rig()
    await rig.boot()
    rig.transition_error = AccountsStoreConflictError("ux_api_keys_active")  # a race lost
    with pytest.raises(AccountConflictError):
        await rig.imports(rig.capability)
    (first,) = rig.m2.rows.values()
    assert first["revoked"] and rig.m2_audit.actions()[-1] == "security.credential_destroyed"
    rig.transition_error = None
    assert (await rig.imports(rig.capability)).key.status == "active"  # the label is free again


def _ctx_for(**settings: Any) -> Any:
    return SimpleNamespace(
        settings=Settings(questdb_pg_password=SecretStr("not-the-dev-default"), **settings),
        exchange_bybit=ExchangeBybitService(),
        ingestion=SimpleNamespace(clock_offset_ms=lambda: None),
    )


def test_the_fake_backend_wires_no_import() -> None:
    assert wiring.wire_key_import(cast(AppContext, _ctx_for()), Refusing(OSError()), Rig()) is None


def test_the_real_backend_wires_an_import_bound_to_the_process_environment() -> None:
    ctx = _ctx_for(
        storage_backend="real", environment=Environment.TESTNET, egress_ip=EGRESS,
        recv_window_ms=4000,
    )  # fmt: skip
    keys, audit = Refusing(OSError()), Rig()
    flow: Any = wiring.wire_key_import(cast(AppContext, ctx), keys, audit)
    held, policy = flow._candidates, flow._policy
    assert (flow._env, flow._verified._env, held._env, held._window) == ("testnet",) * 3 + (4000,)
    assert (flow._audit, held._keys, held._exchange) == (audit, keys, ctx.exchange_bybit)
    assert (policy.egress_ip, policy.recv_window_ms, held._offset()) == (EGRESS, 4000, 0)
