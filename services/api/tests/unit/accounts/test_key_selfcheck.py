"""E27-T03 slice 2a (#836): the stored-key self-check, its boot assertion and its outcomes.

Facts come from the documented-shape fixtures through the adapter parsers (as in
`test_key_verification.py`). `World` is the store, gate, audit, calls factory and calls at once,
recording one event log so the order (latch, audit, write) is asserted. The clock is fixed and the
loop's sleep is the test's, so nothing waits on wall time or the network.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID

import pytest

from candleviewer.accounts.selfcheck import FAILED, STALE, UNAVAILABLE, KeySelfCheck
from candleviewer.accounts.service import AccountsService
from candleviewer.accounts.verification import (
    KeyRefused,
    Refusal,
    VerificationInconclusive,
    VerificationPolicy,
)
from candleviewer.app import AppContext
from candleviewer.net.read_only_gate import ReadOnlyGate
from candleviewer.observability.health import HealthStatus
from candleviewer.storage.repositories.accounts import (
    ExchangeAccountRow,
    SelfCheckTargetRow,
    VerifiedKey,
)
from tests.unit.accounts.test_key_verification import EGRESS, NOW, WITHDRAW, facts, probed

KEY, ACCT = UUID(int=11), UUID(int=1)
HOUR = timedelta(hours=1)


def target(env: str = "demo", armed: bool = True, age: timedelta = HOUR / 2) -> SelfCheckTargetRow:
    account = ExchangeAccountRow(
        ACCT, "bybit", env, "main", "1000001", None, "fx", "accent.neutral", True, armed,
        "one_way", "cross", "UNIFIED", "USDT", None, None, 5, None, NOW, NOW, None,
    )  # fmt: skip
    return SelfCheckTargetRow(KEY, False, NOW - age, account)


class World:
    def __init__(self, *rows: SelfCheckTargetRow, info: object = None, probe: object = None,
                 egress: str | None = EGRESS, gate: Any = None, interval_s: float = 3600.0,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:  # fmt: skip
        self.rows, self.fail_audit, self.now = list(rows), False, NOW
        self.fail: Exception | None = None
        self.info = facts() if info is None else info
        self.seen = probed() if probe is None else probe
        self.events: list[tuple[Any, ...]] = []
        self.built: list[tuple[UUID, str]] = []
        self.check = KeySelfCheck(
            self, self.calls, gate=gate or self, audit=self, env="demo", clock=lambda: self.now,
            policy=VerificationPolicy(egress_ip=egress), interval_s=interval_s, sleep=sleep,
        )  # fmt: skip

    async def targets(self) -> tuple[SelfCheckTargetRow, ...]:
        if self.fail is not None:
            raise self.fail
        return tuple(self.rows)

    async def record_pass(self, key_id: UUID, verified: VerifiedKey) -> bool:
        self.events.append(("pass", key_id, verified))
        return True

    async def record_error(self, key_id: UUID, *, code: str, at: datetime) -> bool:
        self.events.append(("error", key_id, code))
        return True

    async def disable_trading(self, account_id: UUID) -> bool:
        self.events.append(("disable", account_id))
        return True

    def latch(self, *, reason_code: str, reason_text: str) -> None:
        self.events.append(("latch", reason_code))

    async def emit(self, action: str, **fields: Any) -> None:
        if self.fail_audit:
            raise RuntimeError("audit unavailable")
        self.events.append(("audit", action, fields))

    def calls(self, key_id: UUID, uid: str) -> World:
        self.built.append((key_id, uid))
        return self

    async def _answer(self, name: str, outcome: object) -> Any:
        self.events.append((name,))
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def key_info(self) -> Any:
        return await self._answer("key_info", self.info)

    async def probe(self) -> Any:
        return await self._answer("probe", self.seen)

    async def aclose(self) -> None:
        self.events.append(("aclose",))

    def kinds(self) -> list[tuple[Any, ...]]:
        return [e[:2] for e in self.events if e[0] not in ("key_info", "probe", "aclose")]


async def test_pass_audits_then_refreshes_the_verified_columns() -> None:
    w = World(target())
    await w.check.run_once()
    assert w.kinds() == [("audit", "account.tested"), ("pass", KEY)]
    audit, written = w.events[3][2], w.events[4][2]
    assert audit["after_state"]["failures"] == [] and "outcome" not in audit
    assert (audit["actor_label"], audit["object_kind"], audit["object_id"], audit["env"]) == (
        "system:key-selfcheck", "api_key", str(KEY), "demo",
    )  # fmt: skip
    snapshot = {
        "fetched_at": NOW.isoformat(),
        "uid": "1000001",
        "readOnly": 0,
        "permissions": dict(facts().permissions),
        "ips": [EGRESS],
        "expiredAt": "2027-04-13T00:00:00+00:00",
    }
    assert written == VerifiedKey(snapshot, True, False, (EGRESS,), facts().expires_at, NOW)
    check = w.check.results[KEY]
    assert (check.outcome, check.code, check.last_pass_at, w.built) == (
        "passed", None, NOW, [(KEY, "1000001")],
    )  # fmt: skip


async def test_stored_key_with_withdraw_is_force_disabled_with_the_reason_verbatim() -> None:
    w = World(target(), info=facts(permissions=WITHDRAW))
    await w.check.run_once()
    assert ("probe",) not in w.events  # the fund-right gate runs before any second signed call
    assert w.kinds() == [
        ("latch", FAILED),
        ("audit", "account.tested"),
        ("error", KEY),
        ("audit", "account.disabled_by_policy"),
        ("disable", ACCT),
    ]
    tested, disabled = w.events[3][2], w.events[5][2]
    assert (tested["outcome"], tested["severity"], tested["reason"]) == (
        "failure", "critical", "key_withdraw_permission",
    )  # fmt: skip
    assert disabled["after_state"] == {
        "trading_enabled": False,
        "reason": "permissions.Wallet contains 'Withdraw'",
    }
    assert w.events[4] == ("error", KEY, "key_withdraw_permission")


@pytest.mark.parametrize(
    ("info", "rule"),
    [
        (facts(ips=["198.51.100.9"]), "key_ip_whitelist_mismatch"),
        (facts(ips=[]), "key_ip_whitelist_missing"),
        (KeyRefused(Refusal.UNKNOWN_KEY, 10003), "key_wrong_environment"),
    ],
    ids=["ip-mismatch", "no-whitelist", "wrong-environment-10003"],
)
async def test_verdict_failure_latches_records_the_rule_and_disables(
    info: object, rule: str
) -> None:
    w = World(target(), info=info)
    await w.check.run_once()
    assert [k for k in w.kinds() if k[0] != "audit"] == [
        ("latch", FAILED),
        ("error", KEY),
        ("disable", ACCT),
    ]
    check = w.check.results[KEY]
    assert (check.outcome, check.code, check.egress_ip) == ("failed", rule, EGRESS)
    assert check.result is not None and w.check.failing == 1


async def test_ip_mismatch_keeps_the_egress_ip_for_copying_into_the_whitelist() -> None:
    w = World(target(), info=facts(ips=["198.51.100.9"]))
    await w.check.run_once()
    result = w.check.results[KEY].result
    assert result is not None and EGRESS in result.failures[0].message


@pytest.mark.parametrize(
    ("info", "probe", "code"),
    [
        (VerificationInconclusive("10004"), None, "10004"),
        (VerificationInconclusive("10018"), None, "10018"),
        (VerificationInconclusive("transport_error"), None, "transport_error"),
        (VerificationInconclusive("unknown_state"), None, "unknown_state"),
        (None, VerificationInconclusive("10002"), "10002"),
        (TimeoutError(), None, "timeout"),
        (RuntimeError("signing refused"), None, "check_error"),
        (VerificationInconclusive("Not a code"), None, "inconclusive"),
    ],
    ids=["10004", "10018", "5xx", "malformed", "probe-10002", "timeout", "error", "odd-text"],
)
async def test_inconclusive_check_never_disables_or_refreshes(
    info: object, probe: object, code: str
) -> None:
    w = World(target(), info=info, probe=probe)
    await w.check.run_once()
    assert w.kinds() == [("error", KEY)] and w.events[-1] == ("error", KEY, code)
    check = w.check.results[KEY]
    assert (check.outcome, check.result, check.last_pass_at) == (
        "inconclusive",
        None,
        NOW - HOUR / 2,
    )


@pytest.mark.parametrize(
    ("age", "latched"), [(HOUR + timedelta(minutes=15), False), (HOUR * 2, True)]
)
async def test_inconclusive_past_the_freshness_window_latches_as_stale(
    age: timedelta, latched: bool
) -> None:
    w = World(target(age=age), info=VerificationInconclusive("10018"))
    await w.check.run_once()
    assert (("latch", STALE) in w.kinds()) is latched and ("disable", ACCT) not in w.kinds()


async def test_an_unarmed_account_is_not_disabled_again() -> None:
    w = World(target(armed=False), info=facts(permissions=WITHDRAW))
    await w.check.run_once()
    assert w.kinds() == [("latch", FAILED), ("audit", "account.tested"), ("error", KEY)]


async def test_a_key_of_another_environment_is_never_checked() -> None:
    w = World(target(env="live"))
    await w.check.run_once()
    assert (w.built, w.events, w.check.results) == ([], [], {})


async def test_a_row_the_model_refuses_fails_closed_without_a_verdict() -> None:
    bad = target()
    w = World(SelfCheckTargetRow(KEY, False, NOW, replace(bad.account, exchange_uid="abc")))
    await w.check.run_once()
    assert (w.events, w.built) == ([("latch", UNAVAILABLE)], [])


async def test_no_egress_ip_latches_without_judging_any_key() -> None:
    w = World(target(), egress=None)
    await w.check.run_once()
    assert (w.events, w.built) == ([("latch", UNAVAILABLE)], [])
    empty = World(egress=None)
    await empty.check.run_once()
    assert empty.events == []


async def test_unreadable_key_list_fails_closed_at_boot_and_once_known_keys_go_stale() -> None:
    w = World(target())
    w.fail = RuntimeError("database down")
    await w.check.run_once()
    assert w.events == [("latch", UNAVAILABLE)]
    w.fail, w.events = None, []
    await w.check.run_once()
    w.fail = RuntimeError("database down")
    await w.check.run_once()
    assert ("latch", UNAVAILABLE) not in w.events
    w.now = NOW + HOUR * 2
    await w.check.run_once()
    assert w.events[-1] == ("latch", UNAVAILABLE)


async def test_a_refused_audit_refuses_the_write() -> None:
    w = World(target())
    w.fail_audit = True
    await w.check.run_once()
    assert w.kinds() == [] and w.check.results[KEY].outcome == "passed"


async def test_boot_assertion_ends_before_start_returns_and_degrades_health() -> None:
    gate = ReadOnlyGate()
    w = World(target(), info=facts(permissions=WITHDRAW), gate=gate)
    svc = AccountsService()
    svc.attach_key_selfcheck(w.check)
    await svc.start(cast(AppContext, object()))
    try:
        assert (gate.is_read_only, gate.reason_code) == (True, FAILED)
        assert svc.health().status is HealthStatus.DEGRADED
    finally:
        await svc.stop(1.0)
    assert svc.health().status is HealthStatus.STOPPED


async def test_loop_rechecks_every_interval_and_a_dead_loop_latches() -> None:
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)
        if len(delays) > 1:
            raise RuntimeError("loop broke")

    w = World(target(), interval_s=600.0, sleep=sleep)
    await w.check.start()
    task = w.check._task
    assert task is not None
    await asyncio.gather(task, return_exceptions=True)
    assert (
        delays == [600.0, 600.0] and [k for k in w.kinds() if k[0] == "pass"] == [("pass", KEY)] * 2
    )
    assert w.events[-1] == ("latch", UNAVAILABLE)
    await w.check.start()  # idempotent: the boot assertion runs once per process
    await w.check.stop()
    await w.check.stop()
    assert [k for k in w.kinds() if k[0] == "pass"] == [("pass", KEY)] * 2


@pytest.mark.parametrize("interval_s", [0.0, 3600.5])
def test_the_interval_is_positive_and_at_most_hourly(interval_s: float) -> None:
    with pytest.raises(ValueError, match="hourly"):
        World(interval_s=interval_s)
