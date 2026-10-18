"""E27-T03 slice 2b4 (#836): key import's flow, `createApiKey` over its ports.

The ports are faked around the real facade: `AccountsRepository` over a scripted store, M2's hold
(it runs the check with the id it minted and stores only a returned snapshot), the verified columns
and an audit sink that refuses what `AuditWriter.emit` refuses. Facts come from the documented-shape
`tests/fixtures/key_verification/` replies (their README), through the adapter's parsers. One event
log keeps the order. No network, no sleeps.
"""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.accounts.errors import AccountConflictError, AccountsError
from candleviewer.accounts.key_import import Importer, KeyImport, KeyImportFailed, KeyImportRequest
from candleviewer.accounts.repository import AccountsRepository
from candleviewer.accounts.verification import (
    KeyRefused,
    Refusal,
    VerificationInconclusive,
    VerificationPolicy,
)
from candleviewer.audit.actions import validate_action
from candleviewer.audit.models import AuditEmission
from candleviewer.audit.writer import AuditWriter
from candleviewer.exchange.bybit.key_info import parse_probe
from candleviewer.observability.logging import reset_logging
from candleviewer.observability.secret_type import Secret
from candleviewer.secrets import WithdrawPermissionRejected
from candleviewer.secrets.errors import SnapshotInvalid
from candleviewer.storage.repositories.accounts import (
    AccountsStoreConflictError,
    ApiKeyRow,
    ExchangeAccountRow,
)
from tests.unit.accounts.test_key_selfcheck import EGRESS, NOW, WITHDRAW, T, facts, load, probed

ACCT, KEY, OTHER, OWNER = UUID(int=1), UUID(int=11), UUID(int=12), UUID(int=99)
#: Low-entropy markers for the leak checks, never a real credential.
MARK_ID, MARK_SECRET = "importkey" + "0" * 9, "importsecret-" + "z" * 19


def account_row(env: str = "demo") -> ExchangeAccountRow:
    return ExchangeAccountRow(
        ACCT, "bybit", env, "main", "1000001", None, "fx", "accent.neutral", True, True,
        "one_way", "cross", "UNIFIED", "USDT", None, None, 5, None, NOW, NOW, None,
    )  # fmt: skip


def key_row(key_id: UUID, status: str, label: str = "other", read_only: bool = False) -> ApiKeyRow:
    snap: dict[str, object] = {"fetched_at": NOW.isoformat(), "uid": "1000001", "permissions": {}}
    return ApiKeyRow(
        key_id, ACCT, label, "A1b2", 1, snap, NOW, not read_only, False, False, read_only,
        status, None, None, None, NOW, None,
    )  # fmt: skip


class World:
    """The accounts store, M2's hold, the candidate's calls, the verified columns and the audit
    sink at once, in one event log. The store keeps what M2 stored and the flow wrote."""

    def __init__(self, *, info: Any = None, probe: Any = None, timeout_s: float = 5.0) -> None:
        self.events: list[tuple[Any, ...]] = []
        self.account: ExchangeAccountRow | None = account_row()
        self.keys: list[ApiKeyRow] = []
        self.info = facts() if info is None else info
        self.seen = probed() if probe is None else probe
        self.store_error: Exception | None = None
        self.hang = False
        self.hold_error: Exception | None = None
        self.seal_error: BaseException | None = None  # M2 refusing after the pass, at the store
        self.transition_error: Exception | None = None
        self.verified: Any = None
        self.audit_down, self.written, self.stored = False, True, None
        self.gate, self.entered = asyncio.Event(), asyncio.Event()
        self.gate.set()
        self.flow = KeyImport(
            AccountsRepository(self),  # type: ignore[arg-type]  # the store's three reads/writes
            self, self, audit=self, policy=VerificationPolicy(egress_ip=EGRESS), env="demo",
            clock=lambda: NOW, timeout_s=timeout_s,
        )  # fmt: skip

    async def run(self, **request: Any) -> Any:
        fields = {"account_id": ACCT, "api_key": Secret(MARK_ID), "api_secret": Secret(MARK_SECRET)}
        actor = Importer(OWNER, "owner", "198.51.100.4", UUID(int=8))
        async with asyncio.timeout(1.0):  # a lost bound fails the test instead of hanging it
            return await self.flow.run(KeyImportRequest(**{**fields, **request}), actor)

    def kinds(self) -> list[Any]:
        return [e[0] if e[0] != "audit" else ("audit", e[1]["outcome"]) for e in self.events]

    def audit(self) -> list[dict[str, Any]]:
        return [e[1] for e in self.events if e[0] == "audit"]

    async def get_account(self, scope: Any, account_id: UUID) -> ExchangeAccountRow | None:
        if self.hang:
            await asyncio.Event().wait()
        if self.store_error is not None:
            raise self.store_error
        return self.account if account_id == ACCT else None

    async def list_keys(self, scope: Any, account_id: UUID) -> tuple[ApiKeyRow, ...]:
        self.events.append(("list",))
        return tuple(self.keys)

    async def transition_key_status(self, scope: Any, account_id: UUID, key_id: UUID, *,
                                    expected: str, new: str) -> ApiKeyRow:  # fmt: skip
        self.events.append(("transition", key_id, expected, new, scope.user_id))
        if self.transition_error is not None:
            raise self.transition_error
        (held,) = [k for k in self.keys if k.id == key_id]
        row = key_row(key_id, new, held.label, self.verified.read_only)
        self.keys[self.keys.index(held)] = row
        return row

    async def verify_and_store(self, account: Any, label: str, request: Any, check: Any,
                               actor: Any, activate: Any) -> Any:  # fmt: skip
        """M2's hold: the check, the store (`pending`), then the activation, or the destroy."""
        self.events.append(("hold", label, str(actor.user_id), actor.role))
        if self.hold_error is not None:
            raise self.hold_error
        if (snapshot := await check(self, KEY)) is None:
            return None
        if self.seal_error is not None:
            raise self.seal_error
        self.stored = snapshot
        self.keys.append(key_row(KEY, "pending", label))
        self.events.append(("store", KEY))
        try:
            await activate(SimpleNamespace(key_id=KEY))
        except BaseException:
            self.keys = [k for k in self.keys if k.id != KEY]  # revoked: its label is free
            self.events.append(("destroy", KEY))
            raise
        return SimpleNamespace(key_id=KEY)

    async def key_info(self) -> Any:
        self.events.append(("key_info",))
        self.entered.set()
        await self.gate.wait()
        if isinstance(self.info, BaseException):
            raise self.info
        return self.info

    async def probe(self) -> Any:
        self.events.append(("probe",))
        return self.seen

    async def record_pass(self, key_id: UUID, verified: Any) -> bool:
        self.events.append(("verified", key_id, verified))
        self.verified = verified
        return self.written

    async def emit(self, action: str, **fields: Any) -> None:
        validate_action(action)  # what `AuditWriter.emit` refuses, the double refuses
        inspect.signature(AuditWriter.emit).bind(None, action, **fields)
        AuditEmission(record_id=UUID(int=0), action=action, event_ts=NOW, **fields)
        if self.audit_down:
            raise RuntimeError("audit unavailable")
        self.events.append(("audit", {"action": action, **fields}))


async def test_a_compliant_key_is_recorded_stored_verified_and_promoted_in_that_order() -> None:
    w = World()
    imported = await w.run(label="main-trade")
    assert w.kinds() == [
        "list", "hold", "key_info", "probe", ("audit", "success"), "store", "verified",
        "transition",
    ]  # fmt: skip
    assert w.events[1] == ("hold", "main-trade", str(OWNER), "owner")
    assert w.events[-1] == ("transition", KEY, "pending", "active", OWNER)  # AC-34: after the pass
    assert (imported.key.status, imported.verification.passed, imported.at) == ("active", True, NOW)
    verified = w.events[-2][2]
    assert (verified.can_trade, verified.ip_whitelist, verified.at) == (True, ("203.0.113.7",), NOW)
    assert w.stored == verified.snapshot and verified.snapshot["uta"] == 1  # what M2 stored
    assert w.audit() == [{
        "action": "api_key.import", "actor_label": "user:owner", "actor_user_id": OWNER,
        "actor_ip": "198.51.100.4", "object_kind": "exchange_account", "object_id": str(ACCT),
        "outcome": "success", "severity": "info", "reason": None, "request_id": UUID(int=8),
        "after_state": {"failures": [], "warnings": [], "key_id": str(KEY)}, "env": "demo",
    }]  # fmt: skip
    plain = World()
    await plain.run()
    assert plain.events[1][1] == "fx"  # without a label, the key takes the account's


_WITHDRAW = ("key_withdraw_permission", "permissions.Wallet contains 'Withdraw'")
_UNKNOWN = ("key_wrong_environment", "key does not belong to this environment")


@pytest.mark.parametrize(
    ("info", "rule", "message"),
    [
        (facts(permissions=WITHDRAW), *_WITHDRAW),
        (KeyRefused(Refusal.UNKNOWN_KEY, 10003), *_UNKNOWN),
    ],
    ids=["withdraw", "unknown_key"],
)
async def test_a_verdict_refusing_the_key_stores_nothing(
    info: Any, rule: str, message: str
) -> None:
    w = World(info=info)
    with pytest.raises(KeyImportFailed) as refused:
        await w.run()
    assert (refused.value.code, refused.value.errors) == (
        "validation_failed", (("api_key", rule, message),),
    )  # fmt: skip
    assert refused.value.result is not None and refused.value.result.failures[0].rule == rule
    assert w.kinds() == ["list", "hold", "key_info", ("audit", "denied")] and w.stored is None
    assert (w.audit()[0]["reason"], w.audit()[0]["after_state"]["failures"]) == (rule, [rule])


async def test_a_pass_carries_the_clock_skew_it_measured() -> None:
    body = load("wallet_balance.json")
    w = World(probe=parse_probe(body, sent_at_ms=T - 12_050, received_at_ms=T - 11_950))
    imported = await w.run()
    assert imported.verification.clock_offset_ms == 12_000
    assert [str(x) for x in imported.verification.warnings] == ["clock_skew"]


_SLOW = parse_probe(load("wallet_balance.json"), sent_at_ms=T, received_at_ms=T + 6000)


@pytest.mark.parametrize(
    ("info", "probe", "answer", "ret_code"),
    [
        (VerificationInconclusive("transport_error"), None, "exchange_unavailable", None),
        (VerificationInconclusive("timeout"), None, "exchange_unavailable", None),
        (None, _SLOW, "exchange_unavailable", None),  # slower than the receive window
        (VerificationInconclusive("auth_error", 10004), None, "exchange_error", 10004),
        (VerificationInconclusive("rate_limited", 10006), None, "exchange_error", 10006),
    ],
)
async def test_a_call_without_a_verdict_stores_nothing_and_keeps_only_the_return_code(
    info: Any, probe: Any, answer: str, ret_code: int | None
) -> None:
    w = World(info=info, probe=probe)
    with pytest.raises(KeyImportFailed) as failed:
        await w.run()
    assert (failed.value.code, failed.value.ret_code) == (answer, ret_code)
    assert failed.value.result is None and "store" not in w.kinds()
    assert w.kinds()[-1] == ("audit", "failure") and w.audit()[0]["after_state"] == {"code": answer}


@pytest.mark.parametrize(
    ("state", "request_", "code", "listed"),
    [
        ({"account": None}, {}, "not_found", False),
        ({"account": account_row("live")}, {}, "not_found", False),  # as a missing one
        ({}, {"expected_uid": "2000002"}, "validation_failed", False),
        ({"keys": [key_row(OTHER, "active")]}, {}, "conflict", True),
        ({"keys": [key_row(OTHER, "pending", "FX")]}, {}, "conflict", True),  # the default label
    ],
    ids=["missing", "other_env", "expected_uid", "active_key", "label"],
)
async def test_a_request_the_stored_state_refuses_signs_nothing(
    state: dict[str, Any], request_: dict[str, Any], code: str, listed: bool
) -> None:
    w = World()
    for name, value in state.items():
        setattr(w, name, value)
    with pytest.raises(AccountsError):
        await w.run(**request_)
    assert w.kinds() == ["list"] * listed + [("audit", "denied")]
    assert w.audit()[0]["reason"] == code


async def test_a_second_import_for_the_account_while_one_runs_is_a_conflict() -> None:
    w = World()
    w.gate.clear()
    first = asyncio.create_task(w.run(label="one"))
    await w.entered.wait()
    with pytest.raises(KeyImportFailed) as refused:
        await w.run(label="two")
    w.gate.set()
    assert (refused.value.code, refused.value.transient) == ("conflict", True)  # it clears itself
    assert (await first).key.status == "active"
    w.keys.clear()  # the first key revoked
    assert await w.run(label="three") is not None  # the account is free again


@pytest.mark.parametrize(("state", "seen"), [
    ({}, ["list", "hold", "key_info", "probe"]),  # a pass: never stored
    ({"info": facts(permissions=WITHDRAW)}, ["list", "hold", "key_info"]),  # a 422 refusal
    ({"account": None}, []),  # a 404 refusal
], ids=["pass", "withdraw", "not_found"])  # fmt: skip
async def test_an_import_whose_record_is_lost_is_audit_unavailable(state: Any, seen: Any) -> None:
    w = World()
    vars(w).update(state, audit_down=True)
    with pytest.raises(KeyImportFailed) as failed:
        await w.run()
    assert (failed.value.code, w.stored, w.kinds()) == ("audit_unavailable", None, seen)


@pytest.mark.parametrize(
    ("error", "answer"),
    [
        (None, "store_unavailable"),  # the verified columns changed no row
        (AccountsStoreConflictError("ux_api_keys_active"), "conflict"),  # a race
        (OSError("down"), "store_unavailable"),
    ],
    ids=["written", "race", "outage"],
)
async def test_a_failed_activation_is_undone_and_recorded_so_a_retry_succeeds(
    error: Exception | None, answer: str
) -> None:
    w = World()
    w.written, w.transition_error = error is not None, error
    with pytest.raises((KeyImportFailed, AccountConflictError)):
        await w.run()
    assert [k for k in w.kinds() if isinstance(k, tuple)] == [
        ("audit", "success"), ("audit", "failure"),  # after the pass, never `denied`
    ]  # fmt: skip
    closing = {"code": answer, "key_id": str(KEY)}  # the key the pass's record named
    assert (w.audit()[1]["after_state"], w.kinds()[-2], w.keys) == (closing, "destroy", [])
    w.written, w.transition_error = True, None
    assert (await w.run()).key.status == "active"  # the label is free again


@pytest.mark.parametrize(
    ("error", "hang"), [(OSError("DETAIL: Key (label)=(main) exists"), False), (None, True)]
)
async def test_a_store_outage_or_hang_is_store_unavailable_and_never_its_text(
    error: Exception | None, hang: bool
) -> None:
    w = World(timeout_s=0.01)  # a step that hangs is cut at its bound
    w.store_error, w.hang = error, hang
    reset_logging()  # structlog's defaults: every level reaches the capture
    with capture_logs() as logs, pytest.raises(KeyImportFailed) as failed:
        await w.run()
    assert failed.value.code == "store_unavailable" and "DETAIL" not in repr(logs)


async def test_a_refusal_of_m2_is_recorded_and_stores_nothing() -> None:
    w = World()
    w.hold_error = KeyImportFailed("kek_unavailable", "no KEK")
    with pytest.raises(KeyImportFailed):
        await w.run()
    assert w.kinds() == ["list", "hold", ("audit", "failure")]


@pytest.mark.parametrize(
    "error",
    [
        WithdrawPermissionRejected("key_withdraw_permission"),  # M2's C-2.8 gate at the store
        SnapshotInvalid("snapshot_invalid"),
        asyncio.CancelledError(),
    ],
    ids=["withdraw", "snapshot", "cancelled"],
)
async def test_any_error_after_the_pass_gets_a_closing_failure_record_and_goes_on(
    error: BaseException,
) -> None:
    w = World()
    w.seal_error = error
    with pytest.raises(type(error)) as raised:
        await w.run()
    code = "cancelled" if isinstance(error, asyncio.CancelledError) else "error"
    assert (raised.value, w.stored, w.kinds()[-1]) == (error, None, ("audit", "failure"))
    closing = {"code": code, "error": type(error).__name__, "key_id": str(KEY)}
    assert w.audit()[1]["after_state"] == closing


async def test_an_unexpected_error_or_a_cancellation_before_the_pass_is_recorded_too() -> None:
    w = World()
    w.hold_error = RuntimeError("defect")
    with pytest.raises(RuntimeError):
        await w.run()
    assert w.audit()[0]["after_state"] == {"code": "error", "error": "RuntimeError"}
    w.audit_down = True  # a record lost to an outage never hides the error
    with pytest.raises(RuntimeError):
        await w.run()
    stalled = World()
    stalled.gate.clear()
    task = asyncio.create_task(stalled.run())
    await stalled.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    closing = stalled.audit()[0]
    assert (closing["outcome"], closing["reason"]) == ("failure", "cancelled")


async def test_a_read_only_import_ends_read_only_and_unable_to_trade() -> None:
    w = World(info=facts(readOnly=1))
    key = (await w.run(read_only=True, label="watch")).key  # the row as the store keeps it
    assert (key.label, key.read_only, key.can_trade) == ("watch", True, False)
    assert not w.verified.can_trade


async def test_no_record_or_log_holds_key_material() -> None:
    refused, passed = World(info=facts(permissions=WITHDRAW)), World()
    reset_logging()
    with capture_logs() as logs, pytest.raises(KeyImportFailed) as failure:
        await refused.run()
    await passed.run()
    seen = repr((refused.events, passed.events, logs, failure.value.__dict__, passed.stored))
    assert MARK_ID not in seen and MARK_SECRET not in seen
