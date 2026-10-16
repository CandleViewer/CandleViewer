"""E27-T03 slice 2a (#836): the stored-key self-check, its boot assertion and its outcomes.

Facts come from the documented-shape replies in `tests/fixtures/key_verification/` (its README
names source, date, env and redaction), parsed by the adapter parsers. `World` is the store, audit
sink and calls at once, around the real `ReadOnlyGate`: one event log keeps the order (latch,
audit, write), and the audit sink refuses what `AuditWriter.emit` refuses (#2144). The clock is
fixed, the loop's sleep is the test's and a hang is cut by a zero timeout, so nothing waits on
wall time or the network.
"""

from __future__ import annotations

import asyncio
import copy
import inspect
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.accounts.selfcheck import FAILED, KEY_DEADLINE_S, STALE, UNAVAILABLE, KeySelfCheck
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
from candleviewer.exchange.bybit.key_info import (
    ApiKeyFacts,
    ProbeFacts,
    parse_key_info,
    parse_probe,
)
from candleviewer.net.read_only_gate import ReadOnlyGate
from candleviewer.observability.health import HealthStatus
from candleviewer.storage.repositories.accounts import (
    ExchangeAccountRow,
    SelfCheckTargetRow,
    VerifiedKey,
)
from tests.unit.accounts._permission_cases import BASE

FIXTURES = Path(__file__).parents[2] / "fixtures" / "key_verification"
NOW = datetime(2026, 10, 15, 9, tzinfo=UTC)
T = 1792054800000  # the fixtures' exchange clock, NOW in epoch ms
EGRESS = "203.0.113.7"
WITHDRAW = {**BASE, "Wallet": ["Withdraw"]}
KEY, ACCT, KEY2, ACCT2 = UUID(int=11), UUID(int=1), UUID(int=12), UUID(int=2)
HOUR = timedelta(hours=1)
KEK = "secrets.kek_unavailable"
TESTED, DISABLED = "account.tested", "account.disabled_by_policy"
RECORD = {"actor_label", "object_kind", "object_id", "env", "after_state"}
FAILURE = {"outcome", "severity", "reason"}
FACTS = {"fetched_at", "uid", "readOnly", "permissions", "expiredAt", "uta", "withdraw_enabled"}
CODES = {"warnings", "failures"}
WITHDRAW_FAILURE = [
    ("latch", FAILED), ("audit", TESTED), ("error", KEY), ("disable", ACCT), ("audit", DISABLED),
]  # fmt: skip


def load(name: str) -> dict[str, Any]:
    body: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return body


def facts(**result: Any) -> ApiKeyFacts:
    body = copy.deepcopy(load("key_info_trade.json"))
    body["result"].update(result)
    return parse_key_info(body)


def probed() -> ProbeFacts:
    return parse_probe(load("wallet_balance.json"), sent_at_ms=T - 50, received_at_ms=T + 50)


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


async def within(call: Awaitable[object]) -> None:
    """A lost bound fails the test here instead of hanging the suite."""
    async with asyncio.timeout(1.0):
        await call


class World:
    def __init__(
        self, *rows: SelfCheckTargetRow, info: object = None, timeout_s: float = 10.0,
        key_deadline_s: float = KEY_DEADLINE_S, probe: object = None, egress: str | None = EGRESS,
        interval_s: float = 3600.0, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        held: str | None = None,
    ) -> None:  # fmt: skip
        self.rows, self.now, self.fail_audit, self.written = list(rows), NOW, False, True
        self.fail: Exception | None = None
        self.close_error: Exception | None = None
        self.disable_error: Exception | None = None
        self.hang: set[str] = set()
        self.info = facts() if info is None else info
        self.infos: dict[UUID, object] = {}
        self.seen = probed() if probe is None else probe
        self.armed = {row.account.id: row.account.trading_enabled for row in rows}
        self.events: list[tuple[Any, ...]] = []
        self.built: list[tuple[UUID, str]] = []
        self.gate = ReadOnlyGate()
        self.gate.subscribe(lambda _on, code, _text: self.events.append(("latch", code)))
        if held is not None:  # another module's latch, held before the job runs
            self.gate.latch(reason_code=held, reason_text="held")
        self.check = KeySelfCheck(
            self, self.calls, gate=self.gate, audit=self, env="demo", clock=lambda: self.now,
            policy=VerificationPolicy(egress_ip=egress), timeout_s=timeout_s,
            key_deadline_s=key_deadline_s, interval_s=interval_s, sleep=sleep,
        )  # fmt: skip

    async def _io(self, name: str) -> None:
        if name in self.hang:
            await asyncio.Event().wait()

    async def run(self) -> None:
        """One pass. The outer bound makes a lost inner one fail the test, not hang the suite."""
        async with asyncio.timeout(1.0):
            await self.check.run_once()

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
        if self.disable_error is not None:  # applied, but the answer never came back
            raise self.disable_error
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
        await self._io(name)
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


@asynccontextmanager
async def serving(w: World) -> AsyncIterator[AccountsService]:
    """The service with the job attached, started and always stopped, each within a bound."""
    svc = AccountsService()
    svc.attach_key_selfcheck(w.check)
    await within(svc.start(cast(AppContext, object())))
    try:
        yield svc
    finally:
        await within(svc.stop(1.0))


async def test_pass_audits_then_refreshes_the_verified_columns() -> None:
    w = World(target())
    await w.run()
    assert w.kinds() == [("audit", TESTED), ("pass", KEY)]
    audit = w.audit(TESTED)
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
    shown = {k: v for k, v in snapshot.items() if k != "ips"}  # the whitelist stays in api_keys
    assert "outcome" not in audit and audit["after_state"] == {
        **shown, "uta": True, "withdraw_enabled": False, "warnings": [], "failures": [],
    }  # fmt: skip
    assert w.of("pass") == [
        ("pass", KEY, VerifiedKey(snapshot, True, False, (EGRESS,), facts().expires_at, NOW))
    ]
    check = w.check.results[KEY]
    assert (check.outcome, check.code, check.last_pass_at, w.built) == (
        "passed", None, NOW, [(KEY, "1000001")],
    )  # fmt: skip


async def test_a_read_only_stored_key_passes_as_read_only() -> None:
    w = World(target(read_only=True), info=facts(readOnly=1))
    await w.run()
    ((_, _, written),) = w.of("pass")
    assert (written.can_trade, written.read_only) == (False, True)


async def test_stored_key_with_withdraw_latches_first_and_records_the_rule() -> None:
    w = World(target(), info=facts(permissions=WITHDRAW))
    await w.run()
    assert ("probe",) not in w.events  # the fund-right gate runs before any second signed call
    assert w.kinds() == WITHDRAW_FAILURE
    tested = w.audit(TESTED)
    assert (tested["outcome"], tested["severity"], tested["reason"]) == (
        "failure", "critical", "key_withdraw_permission",
    )  # fmt: skip
    assert tested["after_state"]["withdraw_enabled"] is True
    assert w.of("error") == [("error", KEY, "key_withdraw_permission")]


async def test_a_failing_key_force_disables_its_account_and_keeps_its_reason_for_display() -> None:
    w = World(target(), info=facts(permissions=WITHDRAW))
    await w.run()
    disabled = w.audit(DISABLED)
    assert set(disabled) == (RECORD | FAILURE | {"before_state"}) - {"outcome"}
    assert (disabled["before_state"], disabled["after_state"], disabled["reason"]) == (
        {"trading_enabled": True}, {"trading_enabled": False}, "key_withdraw_permission",
    )  # fmt: skip
    result = w.check.results[KEY].result
    assert w.armed[ACCT] is False and result is not None
    assert result.failures[0].message == "permissions.Wallet contains 'Withdraw'"


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
    await w.run()
    assert [k for k in w.kinds() if k[0] != "audit"] == [
        ("latch", FAILED),
        ("error", KEY),
        ("disable", ACCT),
    ]
    check = w.check.results[KEY]
    assert (check.outcome, check.code, check.egress_ip) == ("failed", rule, EGRESS)
    assert check.result is not None and w.check.failing == 1


@pytest.mark.parametrize(
    ("info", "fields", "state"),
    [
        (None, RECORD, FACTS | CODES),
        (facts(ips=["198.51.100.9"]), RECORD | FAILURE, FACTS | CODES),
        (KeyRefused(Refusal.UNKNOWN_KEY, 10003), RECORD | FAILURE, CODES),
    ],
    ids=["pass", "ip-mismatch", "refusal"],
)
async def test_an_audit_record_holds_codes_and_permissions_never_an_ip(
    info: object, fields: set[str], state: set[str]
) -> None:
    w = World(target(), info=info)
    await w.run()
    record = w.audit(TESTED)
    assert (set(record), set(record["after_state"])) == (fields, state)
    text = json.dumps(w.of("audit"))  # the whitelist and egress IP stay in api_keys and the result
    assert EGRESS not in text and "198.51.100.9" not in text


async def test_ip_mismatch_keeps_the_egress_ip_for_copying_into_the_whitelist() -> None:
    w = World(target(), info=facts(ips=["198.51.100.9"]))
    await w.run()
    result = w.check.results[KEY].result
    assert result is not None and EGRESS in result.failures[0].message


async def test_every_key_of_a_pass_is_judged_and_recorded_on_its_own() -> None:
    w = World(target(), target(key=KEY2, acct=ACCT2))
    w.infos[KEY2] = facts(permissions=WITHDRAW)
    await w.run()
    outcomes = {key: check.outcome for key, check in w.check.results.items()}
    assert (outcomes, w.of("pass")[0][1]) == ({KEY: "passed", KEY2: "failed"}, KEY)
    assert (w.of("error"), w.of("disable")) == (
        [("error", KEY2, "key_withdraw_permission")], [("disable", ACCT2)],
    )  # fmt: skip


async def test_an_unarmed_account_is_not_recorded_as_disabled() -> None:
    w = World(target(armed=False), info=facts(permissions=WITHDRAW))
    await w.run()
    assert w.kinds() == WITHDRAW_FAILURE[:-1]


async def test_an_account_armed_after_the_key_list_read_is_still_disabled() -> None:
    w = World(target(armed=False), info=facts(permissions=WITHDRAW))
    w.armed[ACCT] = True  # armed after `targets()` returned its snapshot
    await w.run()
    assert (w.kinds(), w.armed[ACCT]) == (WITHDRAW_FAILURE, False)


async def test_a_refused_audit_never_stops_the_force_disable() -> None:
    w = World(target(), info=facts(permissions=WITHDRAW))
    w.fail_audit = True
    await w.run()
    assert (w.kinds(), w.armed[ACCT]) == ([("latch", FAILED), ("disable", ACCT)], False)


async def test_a_refused_disable_record_is_sent_on_the_next_pass_and_then_cleared() -> None:
    w = World(target(), info=facts(permissions=WITHDRAW))
    w.fail_audit = True
    await w.run()
    w.fail_audit, w.events = False, []
    await w.run()
    assert w.kinds() == [("audit", DISABLED), ("audit", TESTED), ("error", KEY), ("disable", ACCT)]
    assert w.audit(DISABLED)["before_state"] == {"trading_enabled": True}
    w.events = []
    await w.run()
    assert w.kinds() == [("audit", TESTED), ("error", KEY), ("disable", ACCT)]


@pytest.mark.parametrize(
    ("hang", "error", "audited"),
    [
        ({"disable_trading"}, None, [TESTED, TESTED, DISABLED]),
        (set(), RuntimeError("lost"), [TESTED] * 2),
    ],
    ids=["hangs", "raises-after-applying"],
)
async def test_a_disable_that_fails_has_an_unknown_outcome_and_leaves_the_failure_record(
    hang: set[str], error: Exception | None, audited: list[str]
) -> None:
    w = World(target(), info=facts(permissions=WITHDRAW), timeout_s=0.0)
    w.hang, w.disable_error = hang, error
    with capture_logs() as logs:
        await w.run()
    unknown = [log for log in logs if log["event"] == "key_selfcheck_disable_failed"]
    assert [(log["log_level"], log["outcome_unknown"]) for log in unknown] == [("critical", True)]
    w.hang, w.disable_error = set(), None
    await w.run()  # a disable that applied makes the next conditional update report no change
    assert [event[1] for event in w.of("audit")] == audited


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
    await w.run()
    assert w.kinds() == [("error", KEY)] and w.events[-1] == ("error", KEY, code)
    assert w.of("aclose") == [("aclose",)]
    check = w.check.results[KEY]
    assert (check.outcome, check.result, check.last_pass_at) == (
        "inconclusive",
        None,
        NOW - HOUR / 2,
    )


async def test_an_inconclusive_check_is_logged_as_a_warning() -> None:
    w = World(target(), info=inconclusive())
    with capture_logs() as logs:
        await w.run()
    expected = {"event": "key_selfcheck_inconclusive", "key_id": str(KEY), "code": "10018"}
    assert {**expected, "log_level": "warning"} in logs


@pytest.mark.parametrize(
    ("age", "latched"),
    [(HOUR + timedelta(minutes=15), False), (HOUR + timedelta(minutes=15, seconds=1), True)],
)
async def test_inconclusive_past_the_freshness_window_latches_as_stale(
    age: timedelta, latched: bool
) -> None:
    w = World(target(age=age), info=inconclusive())
    await w.run()
    assert (("latch", STALE) in w.kinds()) is latched and ("disable", ACCT) not in w.kinds()


@pytest.mark.parametrize("call", ["key_info", "probe"])
async def test_a_hanging_signed_call_is_inconclusive_at_the_key_deadline(call: str) -> None:
    w = World(target(), key_deadline_s=0.0)
    w.hang.add(call)
    await w.run()  # a lost key deadline fails here, not at the check's
    assert (w.of("latch"), w.of("error")) == ([], [("error", KEY, "timeout")])
    assert w.of("aclose") == [("aclose",)]


async def test_an_inconclusive_check_keeps_a_standing_failure_in_force() -> None:
    w = World(target(), info=facts(permissions=WITHDRAW), held=KEK)  # no latch of the job's
    async with serving(w) as svc:
        w.info, w.events = inconclusive(), []
        await w.run()
        assert (w.check.results[KEY].code, w.of("error")) == ("key_withdraw_permission", [])
        assert (w.check.failing, svc.health().status) == (1, HealthStatus.DEGRADED)


async def test_a_key_that_leaves_the_list_leaves_the_results() -> None:
    w = World(target(), target(key=KEY2, acct=ACCT2))
    await w.run()
    del w.rows[1]
    await w.run()
    assert set(w.check.results) == {KEY}


async def test_a_pass_clears_a_standing_failure() -> None:
    w = World(target(), info=facts(permissions=WITHDRAW))
    await w.run()
    w.info = facts()
    await w.run()
    assert (w.check.results[KEY].outcome, w.check.results[KEY].code) == ("passed", None)


async def test_an_inconclusive_check_keeps_the_last_pass_and_records_its_code() -> None:
    w = World(target())
    await w.run()
    w.info, w.now = inconclusive(), NOW + HOUR
    await w.run()
    check = w.check.results[KEY]
    assert (check.outcome, check.checked_at) == ("passed", NOW)
    assert w.of("error") == [("error", KEY, "10018")]


async def test_a_refused_audit_refuses_the_pass_write_and_keeps_the_last_pass() -> None:
    w = World(target())
    w.fail_audit = True
    await w.run()
    assert (w.kinds(), w.check.results[KEY].last_pass_at) == ([], NOW - HOUR / 2)


async def test_a_pass_that_changes_no_row_is_logged_and_keeps_the_last_pass() -> None:
    w = World(target())
    w.written = False
    with capture_logs() as logs:
        await w.run()
    assert w.check.results[KEY].last_pass_at == NOW - HOUR / 2
    assert [log["event"] for log in logs if log["log_level"] == "warning"] == [
        "key_selfcheck_record_unchanged"
    ]


async def test_a_kek_latch_is_never_replaced_by_a_failing_key() -> None:
    w = World(target(), info=facts(permissions=WITHDRAW))
    w.gate.latch(reason_code=KEK, reason_text="kek")
    await w.run()
    assert (w.gate.reason_code, w.of("latch")) == (KEK, [("latch", KEK)])


async def test_a_kek_latch_is_never_replaced_by_a_stale_key() -> None:
    w = World(target(age=HOUR * 2), info=inconclusive())
    w.gate.latch(reason_code=KEK, reason_text="kek")
    await w.run()
    assert (w.gate.reason_code, w.of("latch")) == (KEK, [("latch", KEK)])


async def test_a_failure_is_never_replaced_by_a_key_that_cannot_be_checked() -> None:
    w = World(target(), target(key=KEY2, acct=ACCT2, uid="abc"), info=facts(permissions=WITHDRAW))
    await w.run()
    assert (w.gate.reason_code, w.of("latch")) == (FAILED, [("latch", FAILED)])


async def test_a_repeated_failure_notifies_the_gate_listeners_once() -> None:
    w = World(target(), info=facts(permissions=WITHDRAW))
    await w.run()
    await w.run()
    assert w.of("latch") == [("latch", FAILED)]


@pytest.mark.parametrize(
    ("weaker", "info", "fail"),
    [(UNAVAILABLE, None, RuntimeError("database down")), (STALE, inconclusive(), None)],
    ids=["unavailable", "stale"],
)
async def test_a_failure_replaces_a_weaker_latch_of_the_job(
    weaker: str, info: object, fail: Exception | None
) -> None:
    w = World(target(age=HOUR * 2), info=info)
    w.fail = fail
    await w.run()
    w.fail, w.info = None, facts(permissions=WITHDRAW)
    await w.run()
    assert (w.gate.reason_code, w.of("latch")) == (FAILED, [("latch", weaker), ("latch", FAILED)])


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
    await w.run()
    assert (w.kinds(), w.of("aclose")) == (expected, [("aclose",)])


@pytest.mark.parametrize("step", ["emit", "record_pass"])
async def test_a_hanging_pass_write_is_cut_and_keeps_the_last_pass(step: str) -> None:
    w = World(target(), timeout_s=0.0)
    w.hang.add(step)
    await w.run()
    assert (w.of("pass"), w.check.results[KEY].last_pass_at) == ([], NOW - HOUR / 2)


@pytest.mark.parametrize("step", ["emit", "record_error", "disable_trading"])
async def test_a_hanging_write_never_undoes_the_failure_latch(step: str) -> None:
    w = World(target(), info=facts(permissions=WITHDRAW), timeout_s=0.0)
    w.hang.add(step)
    await w.run()
    assert (w.gate.reason_code, w.check.results[KEY].outcome) == (FAILED, "failed")


def test_the_overall_deadline_covers_every_bounded_step_of_a_check() -> None:
    check = World(timeout_s=25.0, key_deadline_s=15.0).check
    assert check._deadline_s >= 15.0 + 5 * 25.0  # verify(), the close and four audit or store steps


async def test_a_check_past_its_deadline_fails_closed() -> None:
    w = World(target(), timeout_s=60.0)
    w.check._deadline_s = 0.0  # below every step bound: only the overall deadline cuts the hang
    w.hang.add("record_pass")
    await w.run()
    assert (w.gate.reason_code, w.of("pass")) == (UNAVAILABLE, [])


@pytest.mark.parametrize(
    ("row", "egress"),
    [(target(env="live"), EGRESS), (target(uid="abc"), EGRESS), (target(), None)],
    ids=["other-environment", "refused-row", "no-egress-ip"],
)
async def test_what_cannot_be_checked_fails_closed_without_judging_a_key(
    row: SelfCheckTargetRow, egress: str | None
) -> None:
    w = World(row, egress=egress)
    await w.run()
    assert (w.events, w.built, w.check.results) == ([("latch", UNAVAILABLE)], [], {})


@pytest.mark.parametrize("egress", [EGRESS, None], ids=["egress-ip", "no-egress-ip"])
async def test_an_empty_key_list_latches_nothing_and_warns_once_per_pass(
    egress: str | None,
) -> None:
    w = World(egress=egress)
    with capture_logs() as logs:
        await w.run()
        await w.run()
    warning = {"event": "key_selfcheck_no_keys", "env": "demo", "log_level": "warning"}
    assert (w.events, [log for log in logs if log["log_level"] != "debug"]) == ([], [warning] * 2)


@pytest.mark.parametrize(
    ("fail", "hang"),
    [(RuntimeError("database down"), set()), (None, {"targets"})],
    ids=["raises", "hangs"],
)
async def test_an_unreadable_key_list_at_boot_fails_closed(
    fail: Exception | None, hang: set[str]
) -> None:
    w = World(target(), timeout_s=0.0)
    w.fail, w.hang = fail, hang
    await w.run()
    assert w.events == [("latch", UNAVAILABLE)]


@pytest.mark.parametrize(
    ("elapsed", "latched"), [(HOUR + timedelta(minutes=15), False), (HOUR * 2, True)]
)
async def test_an_unreadable_key_list_fails_closed_once_a_known_key_is_stale(
    elapsed: timedelta, latched: bool
) -> None:
    w = World(target())
    await w.run()
    w.fail, w.now = RuntimeError("database down"), NOW + elapsed
    await w.run()
    assert w.of("latch") == ([("latch", UNAVAILABLE)] if latched else [])


async def test_the_service_boots_the_check_before_serving_and_stops_the_job() -> None:
    w = World(target(), info=facts(permissions=WITHDRAW))
    async with serving(w) as svc:
        assert (w.gate.is_read_only, w.gate.reason_code) == (True, FAILED)
        assert svc.health().status is HealthStatus.DEGRADED
    assert (w.check._task, svc.health().status) == (None, HealthStatus.STOPPED)


@pytest.mark.parametrize(
    ("rows", "kwargs", "latch", "status"),
    [
        ([target()], {}, None, HealthStatus.OK),
        ([target()], {"held": KEK}, KEK, HealthStatus.OK),  # the KEK's latch is not the job's
        ([target(age=HOUR * 2)], {"info": inconclusive()}, STALE, HealthStatus.DEGRADED),
        ([target()], {"egress": None}, UNAVAILABLE, HealthStatus.DEGRADED),
    ],
    ids=["healthy", "kek-latch", "stale", "unavailable"],
)
async def test_health_reads_degraded_while_the_job_holds_a_fail_closed_latch(
    rows: list[SelfCheckTargetRow], kwargs: dict[str, Any], latch: str | None, status: HealthStatus
) -> None:
    w = World(*rows, **kwargs)
    async with serving(w) as svc:
        assert (w.gate.reason_code, w.check.failing, svc.health().status) == (latch, 0, status)


async def test_health_stays_degraded_once_a_failed_key_passes_again() -> None:
    w = World(target(), info=facts(permissions=WITHDRAW))
    async with serving(w) as svc:
        w.info = facts()
        await w.run()
        assert (w.gate.reason_code, w.check.failing) == (FAILED, 0)  # the latch holds to a restart
        assert svc.health().status is HealthStatus.DEGRADED


async def test_the_loop_rechecks_after_every_interval() -> None:
    ticks = Ticks(1)
    w = World(target(), interval_s=600.0, sleep=ticks)
    await within(w.check.start())
    await within(ticks.blocked.wait())
    task = w.check._task
    await within(w.check.stop())
    assert (ticks.delays, len(w.of("pass"))) == ([600.0, 600.0], 2)
    assert task is not None and task.cancelled()


@pytest.mark.parametrize(
    ("held", "latch"), [(None, UNAVAILABLE), (KEK, KEK)], ids=["job-latch", "kek-latch"]
)
async def test_a_dead_loop_fails_closed_and_reads_degraded(held: str | None, latch: str) -> None:
    async def broken(_delay: float) -> None:
        raise RuntimeError("loop broke")

    w = World(target(), sleep=broken, held=held)
    async with serving(w) as svc:
        task = w.check._task
        assert task is not None
        await within(asyncio.gather(task, return_exceptions=True))
        assert (w.gate.reason_code, svc.health().status) == (latch, HealthStatus.DEGRADED)


async def test_the_boot_assertion_runs_once_and_stop_is_idempotent() -> None:
    w = World(target(), sleep=Ticks(0))
    await within(w.check.start())
    await within(w.check.start())
    await within(w.check.stop())
    await within(w.check.stop())
    assert len(w.of("pass")) == 1


@pytest.mark.parametrize("interval_s", [0.0, 3600.5])
def test_the_interval_is_positive_and_at_most_hourly(interval_s: float) -> None:
    with pytest.raises(ValueError, match="hourly"):
        World(interval_s=interval_s)
