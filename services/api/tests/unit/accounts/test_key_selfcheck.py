"""E27-T03 slice 2a (#836): the stored-key self-check, its boot assertion and its outcomes.

Facts come from the documented-shape fixtures through the adapter parsers (`_helpers`). `World`
is the store, audit sink and calls at once, around the real `ReadOnlyGate`: one event log keeps
the order (latch, audit, write), and the audit sink refuses what `AuditWriter.emit` refuses
(#2144). The clock is fixed, the loop's sleep is the test's and a hang is cut by a zero timeout,
so nothing waits on wall time or the network.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.accounts.selfcheck import (
    CHECK_DEADLINE_S,
    FAILED,
    STALE,
    UNAVAILABLE,
    KeySelfCheck,
)
from candleviewer.accounts.service import AccountsService
from candleviewer.accounts.verification import (
    KeyRefused,
    Refusal,
    VerificationInconclusive,
    VerificationPolicy,
)
from candleviewer.app import AppContext
from candleviewer.audit.actions import validate_action
from candleviewer.audit.models import AuditEmission
from candleviewer.audit.writer import AuditWriter
from candleviewer.net.read_only_gate import ReadOnlyGate
from candleviewer.observability.health import HealthStatus
from candleviewer.storage.repositories.accounts import (
    ExchangeAccountRow,
    SelfCheckTargetRow,
    VerifiedKey,
)
from tests.unit.accounts._helpers import EGRESS, NOW, WITHDRAW, facts, probed

KEY, ACCT, KEY2, ACCT2 = UUID(int=11), UUID(int=1), UUID(int=12), UUID(int=2)
HOUR = timedelta(hours=1)
KEK = "secrets.kek_unavailable"
TESTED, DISABLED = "account.tested", "account.disabled_by_policy"
WITHDRAW_FAILURE = [
    ("latch", FAILED), ("audit", TESTED), ("error", KEY), ("disable", ACCT), ("audit", DISABLED),
]  # fmt: skip


def target(
    env: str = "demo", armed: bool = True, age: timedelta = HOUR / 2, *, key: UUID = KEY,
    acct: UUID = ACCT, read_only: bool = False, uid: str = "1000001",
) -> SelfCheckTargetRow:  # fmt: skip
    account = ExchangeAccountRow(
        acct, "bybit", env, "main", uid, None, "fx", "accent.neutral", True, armed,
        "one_way", "cross", "UNIFIED", "USDT", None, None, 5, None, NOW, NOW, None,
    )  # fmt: skip
    return SelfCheckTargetRow(key, read_only, NOW - age, account)


def inconclusive() -> VerificationInconclusive:
    return VerificationInconclusive("10018")


class World:
    def __init__(self, *rows: SelfCheckTargetRow, info: object = None, probe: object = None,
                 egress: str | None = EGRESS, interval_s: float = 3600.0, timeout_s: float = 10.0,
                 deadline_s: float = CHECK_DEADLINE_S,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:  # fmt: skip
        self.rows, self.now, self.fail_audit, self.written = list(rows), NOW, False, True
        self.fail: Exception | None = None
        self.close_error: Exception | None = None
        self.hang: set[str] = set()
        self.info = facts() if info is None else info
        self.infos: dict[UUID, object] = {}
        self.seen = probed() if probe is None else probe
        self.armed = {row.account.id: row.account.trading_enabled for row in rows}
        self.events: list[tuple[Any, ...]] = []
        self.built: list[tuple[UUID, str]] = []
        self.gate = ReadOnlyGate()
        self.gate.subscribe(lambda _on, code, _text: self.events.append(("latch", code)))
        self.check = KeySelfCheck(
            self, self.calls, gate=self.gate, audit=self, env="demo", clock=lambda: self.now,
            policy=VerificationPolicy(egress_ip=egress), interval_s=interval_s,
            timeout_s=timeout_s, check_deadline_s=deadline_s, sleep=sleep,
        )  # fmt: skip

    async def _io(self, name: str) -> None:
        if name in self.hang:
            await asyncio.Event().wait()

    async def targets(self) -> tuple[SelfCheckTargetRow, ...]:
        await self._io("targets")
        if self.fail is not None:
            raise self.fail
        return tuple(self.rows)

    async def record_pass(self, key_id: UUID, verified: VerifiedKey) -> bool:
        await self._io("record_pass")
        self.events.append(("pass", key_id, verified))
        return self.written

    async def record_error(self, key_id: UUID, *, code: str, at: datetime) -> bool:
        await self._io("record_error")
        self.events.append(("error", key_id, code))
        return True

    async def disable_trading(self, account_id: UUID) -> bool:
        await self._io("disable_trading")
        self.events.append(("disable", account_id))
        armed, self.armed[account_id] = self.armed.get(account_id, False), False
        return armed

    async def emit(self, action: str, **fields: Any) -> None:
        validate_action(action)  # what `AuditWriter.emit` refuses, the double refuses
        inspect.signature(AuditWriter.emit).bind(None, action, **fields)
        AuditEmission(record_id=UUID(int=0), action=action, event_ts=NOW, **fields)
        await self._io("emit")
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
        return await self._answer("key_info", self.infos.get(self.built[-1][0], self.info))

    async def probe(self) -> Any:
        return await self._answer("probe", self.seen)

    async def aclose(self) -> None:
        self.events.append(("aclose",))
        await self._io("aclose")
        if self.close_error is not None:
            raise self.close_error

    def kinds(self) -> list[tuple[Any, ...]]:
        return [e[:2] for e in self.events if e[0] not in ("key_info", "probe", "aclose")]

    def of(self, kind: str) -> list[tuple[Any, ...]]:
        return [e for e in self.events if e[0] == kind]

    def audit(self, action: str) -> dict[str, Any]:
        (fields,) = [e[2] for e in self.of("audit") if e[1] == action]
        return cast(dict[str, Any], fields)


class Ticks:
    """The loop's sleep: returns `n` times, then blocks until cancelled (`blocked` set)."""

    def __init__(self, n: int) -> None:
        self.n, self.blocked = n, asyncio.Event()
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        if len(self.delays) > self.n:
            self.blocked.set()
            await asyncio.Event().wait()


async def started(w: World) -> AccountsService:
    svc = AccountsService()
    svc.attach_key_selfcheck(w.check)
    await svc.start(cast(AppContext, object()))
    return svc


async def test_pass_audits_then_refreshes_the_verified_columns() -> None:
    w = World(target())
    await w.check.run_once()
    assert w.kinds() == [("audit", TESTED), ("pass", KEY)]
    audit = w.audit(TESTED)
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
    assert w.of("pass") == [
        ("pass", KEY, VerifiedKey(snapshot, True, False, (EGRESS,), facts().expires_at, NOW))
    ]
    check = w.check.results[KEY]
    assert (check.outcome, check.code, check.last_pass_at, w.built) == (
        "passed", None, NOW, [(KEY, "1000001")],
    )  # fmt: skip


async def test_a_read_only_stored_key_passes_as_read_only() -> None:
    w = World(target(read_only=True), info=facts(readOnly=1))
    await w.check.run_once()
    ((_, _, written),) = w.of("pass")
    assert (written.can_trade, written.read_only) == (False, True)


async def test_stored_key_with_withdraw_is_force_disabled_with_the_reason_verbatim() -> None:
    w = World(target(), info=facts(permissions=WITHDRAW))
    await w.check.run_once()
    assert ("probe",) not in w.events  # the fund-right gate runs before any second signed call
    assert w.kinds() == WITHDRAW_FAILURE
    tested, disabled = w.audit(TESTED), w.audit(DISABLED)
    assert (tested["outcome"], tested["severity"], tested["reason"]) == (
        "failure", "critical", "key_withdraw_permission",
    )  # fmt: skip
    assert (disabled["before_state"], disabled["after_state"]) == (
        {"trading_enabled": True},
        {"trading_enabled": False, "reason": "permissions.Wallet contains 'Withdraw'"},
    )
    assert w.of("error") == [("error", KEY, "key_withdraw_permission")]


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


async def test_every_key_of_a_pass_is_judged_and_recorded_on_its_own() -> None:
    w = World(target(), target(key=KEY2, acct=ACCT2))
    w.infos[KEY2] = facts(permissions=WITHDRAW)
    await w.check.run_once()
    outcomes = {key: check.outcome for key, check in w.check.results.items()}
    assert (outcomes, w.of("pass")[0][1]) == ({KEY: "passed", KEY2: "failed"}, KEY)
    assert (w.of("error"), w.of("disable")) == (
        [("error", KEY2, "key_withdraw_permission")], [("disable", ACCT2)],
    )  # fmt: skip


async def test_an_unarmed_account_is_not_recorded_as_disabled() -> None:
    w = World(target(armed=False), info=facts(permissions=WITHDRAW))
    await w.check.run_once()
    assert w.kinds() == WITHDRAW_FAILURE[:-1]


async def test_an_account_armed_after_the_key_list_read_is_still_disabled() -> None:
    w = World(target(armed=False), info=facts(permissions=WITHDRAW))
    w.armed[ACCT] = True  # armed after `targets()` returned its snapshot
    await w.check.run_once()
    assert (w.kinds(), w.armed[ACCT]) == (WITHDRAW_FAILURE, False)


async def test_a_refused_audit_never_stops_the_force_disable() -> None:
    w = World(target(), info=facts(permissions=WITHDRAW))
    w.fail_audit = True
    await w.check.run_once()
    assert (w.kinds(), w.armed[ACCT]) == ([("latch", FAILED), ("disable", ACCT)], False)


async def test_a_refused_disable_record_is_sent_on_the_next_pass() -> None:
    w = World(target(), info=facts(permissions=WITHDRAW))
    w.fail_audit = True
    await w.check.run_once()
    w.fail_audit, w.events = False, []
    await w.check.run_once()
    assert w.kinds() == [("audit", DISABLED), ("audit", TESTED), ("error", KEY), ("disable", ACCT)]
    assert w.audit(DISABLED)["before_state"] == {"trading_enabled": True}


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


async def test_an_inconclusive_check_is_logged_as_a_warning() -> None:
    w = World(target(), info=inconclusive())
    with capture_logs() as logs:
        await w.check.run_once()
    expected = {"event": "key_selfcheck_inconclusive", "key_id": str(KEY), "code": "10018"}
    assert {**expected, "log_level": "warning"} in logs


@pytest.mark.parametrize(
    ("age", "latched"), [(HOUR + timedelta(minutes=15), False), (HOUR * 2, True)]
)
async def test_inconclusive_past_the_freshness_window_latches_as_stale(
    age: timedelta, latched: bool
) -> None:
    w = World(target(age=age), info=inconclusive())
    await w.check.run_once()
    assert (("latch", STALE) in w.kinds()) is latched and ("disable", ACCT) not in w.kinds()


async def test_an_inconclusive_check_keeps_a_standing_failure_in_force() -> None:
    w = World(target(), info=facts(permissions=WITHDRAW))
    svc = await started(w)
    w.info, w.events = inconclusive(), []
    try:
        await w.check.run_once()
        assert (w.check.results[KEY].code, w.of("error")) == ("key_withdraw_permission", [])
        assert (w.check.failing, svc.health().status) == (1, HealthStatus.DEGRADED)
    finally:
        await svc.stop(1.0)


async def test_a_pass_clears_a_standing_failure() -> None:
    w = World(target(), info=facts(permissions=WITHDRAW))
    await w.check.run_once()
    w.info = facts()
    await w.check.run_once()
    assert (w.check.failing, w.check.results[KEY].outcome) == (0, "passed")


async def test_an_inconclusive_check_keeps_the_last_pass_and_records_its_code() -> None:
    w = World(target())
    await w.check.run_once()
    w.info, w.now = inconclusive(), NOW + HOUR
    await w.check.run_once()
    check = w.check.results[KEY]
    assert (check.outcome, check.checked_at) == ("passed", NOW)
    assert w.of("error") == [("error", KEY, "10018")]


async def test_a_refused_audit_refuses_the_pass_write_and_keeps_the_last_pass() -> None:
    w = World(target())
    w.fail_audit = True
    await w.check.run_once()
    assert (w.kinds(), w.check.results[KEY].last_pass_at) == ([], NOW - HOUR / 2)


async def test_a_pass_that_changes_no_row_is_logged_and_keeps_the_last_pass() -> None:
    w = World(target())
    w.written = False
    with capture_logs() as logs:
        await w.check.run_once()
    assert w.check.results[KEY].last_pass_at == NOW - HOUR / 2
    assert [log["event"] for log in logs if log["log_level"] == "warning"] == [
        "key_selfcheck_record_unchanged"
    ]


async def test_a_kek_latch_is_never_replaced_by_a_stale_key() -> None:
    w = World(target(age=HOUR * 2), info=inconclusive())
    w.gate.latch(reason_code=KEK, reason_text="kek")
    await w.check.run_once()
    assert (w.gate.reason_code, w.of("latch")) == (KEK, [("latch", KEK)])


async def test_a_failure_is_never_replaced_by_a_key_that_cannot_be_checked() -> None:
    w = World(target(), target(key=KEY2, acct=ACCT2, uid="abc"), info=facts(permissions=WITHDRAW))
    await w.check.run_once()
    assert (w.gate.reason_code, w.of("latch")) == (FAILED, [("latch", FAILED)])


async def test_a_repeated_failure_notifies_the_gate_listeners_once() -> None:
    w = World(target(), info=facts(permissions=WITHDRAW))
    await w.check.run_once()
    await w.check.run_once()
    assert w.of("latch") == [("latch", FAILED)]


async def test_a_failure_replaces_a_weaker_latch_of_the_job() -> None:
    w = World(target(), info=facts(permissions=WITHDRAW))
    w.fail = RuntimeError("database down")
    await w.check.run_once()
    w.fail = None
    await w.check.run_once()
    assert (w.gate.reason_code, w.of("latch")) == (
        FAILED, [("latch", UNAVAILABLE), ("latch", FAILED)],
    )  # fmt: skip


@pytest.mark.parametrize(
    ("info", "expected"),
    [(None, [("audit", TESTED), ("pass", KEY)]), (facts(permissions=WITHDRAW), WITHDRAW_FAILURE)],
    ids=["pass", "withdraw"],
)
@pytest.mark.parametrize(
    ("hang", "error"),
    [(set(), RuntimeError("close failed")), ({"aclose"}, None)],
    ids=["raises", "hangs"],
)
async def test_a_failing_close_never_changes_the_verdict(
    info: object, expected: list[tuple[Any, ...]], hang: set[str], error: Exception | None
) -> None:
    w = World(target(), info=info, timeout_s=0.0)
    w.hang, w.close_error = hang, error
    await w.check.run_once()
    assert w.kinds() == expected


@pytest.mark.parametrize("step", ["emit", "record_pass"])
async def test_a_hanging_write_never_holds_the_boot_assertion(step: str) -> None:
    w = World(target(), timeout_s=0.0, sleep=Ticks(0))
    w.hang.add(step)
    await w.check.start()
    await w.check.stop()
    assert (w.of("pass"), w.check.results[KEY].last_pass_at) == ([], NOW - HOUR / 2)


@pytest.mark.parametrize("step", ["emit", "record_error", "disable_trading"])
async def test_a_hanging_write_never_undoes_the_failure_latch(step: str) -> None:
    w = World(target(), info=facts(permissions=WITHDRAW), timeout_s=0.0)
    w.hang.add(step)
    await w.check.run_once()
    assert (w.gate.reason_code, w.check.failing) == (FAILED, 1)


async def test_a_check_past_its_deadline_fails_closed() -> None:
    w = World(target(), timeout_s=60.0, deadline_s=0.0)
    w.hang.add("record_pass")
    await w.check.run_once()
    assert (w.gate.reason_code, w.of("pass")) == (UNAVAILABLE, [])


async def test_a_key_of_another_environment_is_never_checked() -> None:
    w = World(target(env="live"))
    await w.check.run_once()
    assert (w.built, w.events, w.check.results) == ([], [], {})


async def test_a_row_the_model_refuses_fails_closed_without_a_verdict() -> None:
    w = World(target(uid="abc"))
    await w.check.run_once()
    assert (w.events, w.built) == ([("latch", UNAVAILABLE)], [])


async def test_no_egress_ip_latches_without_judging_any_key() -> None:
    w = World(target(), egress=None)
    await w.check.run_once()
    assert (w.events, w.built) == ([("latch", UNAVAILABLE)], [])


async def test_no_egress_ip_and_no_stored_key_latches_nothing() -> None:
    w = World(egress=None)
    await w.check.run_once()
    assert w.events == []


async def test_an_unreadable_key_list_at_boot_fails_closed() -> None:
    w = World(target())
    w.fail = RuntimeError("database down")
    await w.check.run_once()
    assert w.events == [("latch", UNAVAILABLE)]


async def test_an_unreadable_key_list_within_the_window_latches_nothing() -> None:
    w = World(target())
    await w.check.run_once()
    w.fail = RuntimeError("database down")
    await w.check.run_once()
    assert w.of("latch") == []


async def test_an_unreadable_key_list_once_a_known_key_is_stale_fails_closed() -> None:
    w = World(target())
    await w.check.run_once()
    w.fail, w.now = RuntimeError("database down"), NOW + HOUR * 2
    await w.check.run_once()
    assert w.of("latch") == [("latch", UNAVAILABLE)]


async def test_boot_assertion_ends_before_start_returns_and_degrades_health() -> None:
    w = World(target(), info=facts(permissions=WITHDRAW))
    svc = await started(w)
    try:
        assert (w.gate.is_read_only, w.gate.reason_code) == (True, FAILED)
        assert svc.health().status is HealthStatus.DEGRADED
    finally:
        await svc.stop(1.0)
    assert svc.health().status is HealthStatus.STOPPED


async def test_the_loop_rechecks_after_every_interval() -> None:
    ticks = Ticks(1)
    w = World(target(), interval_s=600.0, sleep=ticks)
    await w.check.start()
    await ticks.blocked.wait()
    await w.check.stop()
    assert (ticks.delays, len(w.of("pass"))) == ([600.0, 600.0], 2)


async def test_a_dead_loop_fails_closed() -> None:
    async def broken(_delay: float) -> None:
        raise RuntimeError("loop broke")

    w = World(target(), sleep=broken)
    await w.check.start()
    task = w.check._task
    assert task is not None
    await asyncio.gather(task, return_exceptions=True)
    assert w.gate.reason_code == UNAVAILABLE


async def test_the_boot_assertion_runs_once_and_stop_is_idempotent() -> None:
    w = World(target(), sleep=Ticks(0))
    await w.check.start()
    await w.check.start()
    await w.check.stop()
    await w.check.stop()
    assert len(w.of("pass")) == 1


@pytest.mark.parametrize("interval_s", [0.0, 3600.5])
def test_the_interval_is_positive_and_at_most_hourly(interval_s: float) -> None:
    with pytest.raises(ValueError, match="hourly"):
        World(interval_s=interval_s)
