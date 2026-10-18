"""E27-T03 slice 2a (#836): the stored-key self-check, its boot assertion and its outcomes.

Facts come from the documented-shape replies in `tests/fixtures/key_verification/` (its README
names source, date, env and redaction), parsed by the adapter parsers. `World` is the store, audit
sink and calls at once, around the real `ReadOnlyGate`: one event log keeps the order (latch,
audit, write), and the audit sink refuses what `AuditWriter.emit` refuses (#2144). Its `disarms`
are the store's policy-disarm columns: a second `World` over them is a restart (slice 2d). The
clock is fixed, the loop's sleep is the test's and a hang is cut by a zero timeout, so nothing
waits on wall time or the network.
"""

from __future__ import annotations

import asyncio
import copy
import inspect
import json
import math
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from candleviewer.accounts.selfcheck import (
    BOOT_DEADLINE_S,
    FAILED,
    KEY_DEADLINE_S,
    MIN_INTERVAL_S,
    STALE,
    UNAVAILABLE,
    KeySelfCheck,
    Outcome,
    is_fresh,
)
from candleviewer.accounts.service import AccountsService
from candleviewer.accounts.verification import (
    KeyRefused,
    Refusal,
    Rule,
    VerificationInconclusive,
    VerificationPolicy,
)
from candleviewer.api.health import make_health_router
from candleviewer.app import AppContext, create_app
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
from candleviewer.observability.metrics import BoundedMetric, Metrics
from candleviewer.observability.metrics_catalogue import register_r0
from candleviewer.settings import Environment, Settings
from candleviewer.storage.repositories.accounts import (
    ExchangeAccountRow,
    PolicyDisarm,
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
#: No audit record names an exchange UID: it is Confidential, and Viewers read the audit log (4b).
FACTS = {"fetched_at", "readOnly", "permissions", "expiredAt", "uta", "withdraw_enabled"}
CODES = {"warnings", "failures"}
WITHDRAW_FAILURE = [
    ("latch", FAILED), ("audit", TESTED), ("error", KEY), ("disable", ACCT), ("audit", DISABLED),
    ("mark", ACCT),
]  # fmt: skip
#: The `account.disabled_by_policy` record of a withdrawal-right disarm, whichever pass sends it.
DISARM_RECORD = {
    "actor_label": "system:key-selfcheck", "object_kind": "exchange_account",
    "object_id": str(ACCT), "env": "demo", "before_state": {"trading_enabled": True},
    "after_state": {"trading_enabled": False}, "severity": "critical",
    "reason": "key_withdraw_permission",
}  # fmt: skip


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
    last_error: str | None = None, expires: datetime | None = None,
) -> SelfCheckTargetRow:  # fmt: skip
    account = ExchangeAccountRow(
        acct, "bybit", env, "main", uid, None, "fx", "accent.neutral", True, armed,
        "one_way", "cross", "UNIFIED", "USDT", None, None, 5, None, NOW, NOW, None,
    )  # fmt: skip
    return SelfCheckTargetRow(key, read_only, NOW - age, account, last_error, expires)


def inconclusive() -> VerificationInconclusive:
    return VerificationInconclusive("rate_limited")


async def within(call: Awaitable[object]) -> None:
    """A lost bound fails the test here instead of hanging the suite."""
    async with asyncio.timeout(1.0):
        await call


class World:
    def __init__(
        self, *rows: SelfCheckTargetRow, info: object = None, timeout_s: float = 10.0,
        key_deadline_s: float = KEY_DEADLINE_S, probe: object = None, egress: str | None = EGRESS,
        interval_s: float = 3600.0, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        held: str | None = None, boot_deadline_s: float = BOOT_DEADLINE_S,
    ) -> None:  # fmt: skip
        self.rows, self.now, self.fail_audit, self.written = list(rows), NOW, False, True
        self.fail: Exception | None = None
        self.close_error: Exception | None = None
        self.disable_error: Exception | None = None
        self.mark_error: Exception | None = None
        self.hang: set[str] = set()
        self.info = facts() if info is None else info
        self.infos: dict[UUID, object] = {}
        self.seen = probed() if probe is None else probe
        self.armed = {row.account.id: row.account.trading_enabled for row in rows}
        #: The policy-disarm columns by account: [rule code, disarmed at, record marked at].
        self.disarms: dict[UUID, list[Any]] = {}
        self.events: list[tuple[Any, ...]] = []
        self.built: list[tuple[UUID, str]] = []
        self.gate = ReadOnlyGate()
        self.gate.subscribe(lambda _on, code, _text: self.events.append(("latch", code)))
        if held is not None:  # another module's latch, held before the job runs
            self.gate.latch(reason_code=held, reason_text="held")
        self.metrics = Metrics("demo")
        register_r0(self.metrics)
        self.check = KeySelfCheck(
            self, self.calls, gate=self.gate, audit=self, env="demo", clock=lambda: self.now,
            metrics=self.metrics, policy=VerificationPolicy(egress_ip=egress), timeout_s=timeout_s,
            key_deadline_s=key_deadline_s, interval_s=interval_s, sleep=sleep,
            boot_deadline_s=boot_deadline_s,
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

    async def disable_trading(self, account_id: UUID, *, code: str, at: datetime) -> bool:
        await self._io("disable_trading")
        self.events.append(("disable", account_id))
        armed, self.armed[account_id] = self.armed.get(account_id, False), False
        if armed:  # one conditional update: the disarm and its reason commit together
            self.disarms[account_id] = [code, at, None]
        if self.disable_error is not None:  # applied, but the answer never came back
            raise self.disable_error
        return armed

    async def owed_disarms(self) -> tuple[PolicyDisarm, ...]:
        await self._io("owed_disarms")
        return tuple(
            PolicyDisarm(a, c, at) for a, (c, at, mark) in self.disarms.items() if not mark
        )

    async def mark_disarm_audited(self, disarm: PolicyDisarm, *, at: datetime) -> bool:
        await self._io("mark_disarm_audited")
        self.events.append(("mark", disarm.account_id))
        if self.mark_error is not None:
            raise self.mark_error
        row = self.disarms.get(disarm.account_id)
        if row is None or row[1:] != [disarm.at, None]:  # not owed: marked, or a later disarm
            return False
        row[2] = at
        return True

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
        "uta": 1,
        "permissions": dict(facts().permissions),
        "ips": [EGRESS],
        "expiredAt": "2027-04-13T00:00:00+00:00",
    }
    hidden = {"ips", "uid"}  # the whitelist stays in api_keys; the UID is Confidential (4b)
    shown = {k: v for k, v in snapshot.items() if k not in hidden}
    assert "outcome" not in audit and audit["after_state"] == {
        **shown, "uta": True, "withdraw_enabled": False, "warnings": [], "failures": [],
    }  # fmt: skip
    assert w.of("pass") == [
        ("pass", KEY, VerifiedKey(snapshot, True, False, (EGRESS,), facts().expires_at, NOW))
    ]
    stored, shown_uta = w.of("pass")[0][2].snapshot["uta"], audit["after_state"]["uta"]
    assert (type(stored), type(shown_uta)) == (int, bool)  # the snapshot mirrors the exchange's 0/1
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
        ("mark", ACCT),
    ]
    check = w.check.results[KEY]
    assert (check.outcome, check.code, check.egress_ip) == ("failed", rule, EGRESS)
    assert check.result is not None and w.check.failing == 1
    assert w.disarms[ACCT][0] == rule  # the disarm's durable reason is the rule, never its text


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


async def test_a_uid_mismatch_record_names_no_exchange_uid() -> None:
    w = World(target(uid="2000002"))  # the fixture key reports 1000001: another account's
    await w.run()
    assert w.audit(TESTED)["reason"] == "key_uid_mismatch"
    text = json.dumps(w.of("audit"))  # the failure and the disable records alike
    assert "1000001" not in text and "2000002" not in text


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
    assert (w.kinds(), w.disarms) == (WITHDRAW_FAILURE[:-2], {})


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
    assert w.kinds() == [
        ("audit", DISABLED), ("mark", ACCT), ("audit", TESTED), ("error", KEY), ("disable", ACCT),
    ]  # fmt: skip
    assert w.audit(DISABLED) == DISARM_RECORD
    w.events = []
    await w.run()
    assert w.kinds() == [("audit", TESTED), ("error", KEY), ("disable", ACCT)]


async def test_the_disarm_commits_its_rule_code_and_time_and_its_record_is_marked_after() -> None:
    w = World(target(), info=facts(permissions=WITHDRAW))
    w.now = NOW + HOUR
    await w.run()
    assert w.disarms == {ACCT: ["key_withdraw_permission", NOW + HOUR, NOW + HOUR]}
    assert w.audit(DISABLED) == DISARM_RECORD and w.kinds()[-2:] == WITHDRAW_FAILURE[-2:]


async def test_an_owed_record_is_sent_once_by_the_boot_pass_after_a_restart() -> None:
    w = World(target(), info=facts(permissions=WITHDRAW))
    w.fail_audit = True  # the sink refuses: the disarm applies and its record is owed
    await w.run()
    assert (w.armed[ACCT], w.disarms[ACCT]) == (False, ["key_withdraw_permission", NOW, None])
    booted = World(target(armed=False), info=facts(permissions=WITHDRAW), sleep=Ticks(0))
    booted.disarms = w.disarms  # a new process over the same store: the job's memory is gone
    await within(booted.check.start())  # the boot pass
    await within(booted.check.stop())
    assert [e[1] for e in booted.of("audit")] == [DISABLED, TESTED]
    assert booted.audit(DISABLED) == DISARM_RECORD and booted.disarms[ACCT][2] == NOW
    booted.events = []
    await booted.run()
    assert [e[1] for e in booted.of("audit")] == [TESTED] and booted.of("mark") == []


async def test_a_refused_re_send_stays_owed_and_is_logged_critical() -> None:
    w = World(target(armed=False))  # passes now; a disarm of an earlier process is still owed
    w.disarms[ACCT] = ["key_withdraw_permission", NOW - HOUR, None]
    w.fail_audit = True
    with capture_logs() as logs:
        await w.run()
    refused = [log for log in logs if log["event"] == "key_selfcheck_disable_unaudited"]
    assert [(log["log_level"], log["account_id"]) for log in refused] == [("critical", str(ACCT))]
    assert (w.disarms[ACCT][2], w.of("mark")) == (None, [])
    w.fail_audit = False
    await w.run()
    assert (w.audit(DISABLED), w.disarms[ACCT][2]) == (DISARM_RECORD, NOW)


async def test_a_sent_record_whose_mark_fails_is_never_sent_twice() -> None:
    w = World(target(), info=facts(permissions=WITHDRAW))
    w.mark_error = RuntimeError("database down")
    await w.run()
    w.mark_error, w.events = None, []
    await w.run()  # only the mark is retried
    assert [e[1] for e in w.of("audit")] == [TESTED]
    assert (w.of("mark"), w.disarms[ACCT][2]) == ([("mark", ACCT)], NOW)


async def test_an_unreadable_owed_list_is_logged_and_the_pass_goes_on() -> None:
    w = World(target(), timeout_s=0.0)
    w.hang.add("owed_disarms")
    with capture_logs() as logs:
        await w.run()
    assert w.kinds() == [("audit", TESTED), ("pass", KEY)]
    unread = {"event": "key_selfcheck_owed_unread", "error": "TimeoutError", "log_level": "error"}
    assert unread in logs


@pytest.mark.parametrize(
    ("hang", "error", "audited"),
    [
        ({"disable_trading"}, None, [TESTED, TESTED, DISABLED]),
        (set(), RuntimeError("lost"), [TESTED, DISABLED, TESTED]),
    ],
    ids=["hangs", "raises-after-applying"],
)
async def test_a_disable_that_fails_has_an_unknown_outcome_and_an_applied_one_is_owed_its_record(
    hang: set[str], error: Exception | None, audited: list[str]
) -> None:
    w = World(target(), info=facts(permissions=WITHDRAW), timeout_s=0.0)
    w.hang, w.disable_error = hang, error
    with capture_logs() as logs:
        await w.run()
    unknown = [log for log in logs if log["event"] == "key_selfcheck_disable_failed"]
    assert [(log["log_level"], log["outcome_unknown"]) for log in unknown] == [("critical", True)]
    w.hang, w.disable_error = set(), None
    await w.run()  # an applied disable is owed its record; the conditional update then no-ops
    assert [event[1] for event in w.of("audit")] == audited


@pytest.mark.parametrize(
    ("info", "probe", "code"),
    [
        (VerificationInconclusive("auth_error"), None, "auth_error"),
        (VerificationInconclusive("rate_limited"), None, "rate_limited"),
        (VerificationInconclusive("service_unavailable"), None, "service_unavailable"),
        (VerificationInconclusive("exchange_unknown"), None, "exchange_unknown"),
        (None, VerificationInconclusive("clock_drift"), "clock_drift"),
        (TimeoutError(), None, "timeout"),
        (RuntimeError("signing refused"), None, "check_error"),
        (VerificationInconclusive("Not a code"), None, "inconclusive"),
    ],
    ids=["auth", "rate-limit", "5xx", "malformed", "probe-clock", "timeout", "error", "odd-text"],
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
    expected = {"event": "key_selfcheck_inconclusive", "key_id": str(KEY), "code": "rate_limited"}
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
    assert w.of("error") == [("error", KEY, "rate_limited")]


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


@pytest.mark.parametrize("step", ["emit", "record_error", "disable_trading", "mark_disarm_audited"])
async def test_a_hanging_write_never_undoes_the_failure_latch(step: str) -> None:
    w = World(target(), info=facts(permissions=WITHDRAW), timeout_s=0.0)
    w.hang.add(step)
    await w.run()
    assert (w.gate.reason_code, w.check.results[KEY].outcome) == (FAILED, "failed")


def test_the_overall_deadline_covers_every_bounded_step_of_a_check() -> None:
    check = World(timeout_s=25.0, key_deadline_s=15.0).check
    # verify(); then the close, five audit or store steps and one step of margin
    assert check._deadline_s == 15.0 + (1 + 5 + 1) * 25.0


async def test_a_check_past_its_deadline_fails_closed() -> None:
    w = World(target(), timeout_s=60.0)
    w.check._deadline_s = 0.0  # below every step bound: only the overall deadline cuts the hang
    w.hang.add("record_pass")
    await w.run()
    assert (w.gate.reason_code, w.of("pass")) == (UNAVAILABLE, [])
    assert sample(w, "cv_key_selfcheck_runs_total", result="error") == 1.0


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
    assert sample(w, "cv_key_selfcheck_runs_total", result="error") == 1.0


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
    assert sample(w, "cv_key_selfcheck_runs_total", result="error") == 1.0  # latched or not


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


async def test_readyz_lists_a_failing_key_as_a_degraded_accounts_check() -> None:
    w, app = World(target(), info=facts(permissions=WITHDRAW)), FastAPI()
    async with serving(w) as svc:
        app.include_router(make_health_router(Settings(), accounts_health=svc.health))
        body = TestClient(app).get("/readyz").json()
    detail = "1 stored key(s) fail the self-check; 1 key(s) checked, oldest last pass 1800s ago"
    accounts = {"name": "accounts", "ok": False, "detail": detail}
    assert (body["status"], body["checks"]) == ("degraded", [accounts])


async def test_readyz_shows_the_key_count_and_the_oldest_last_pass_never_a_key_id() -> None:
    w, app = World(target(), target(key=KEY2, acct=ACCT2, age=HOUR * 2 / 3)), FastAPI()
    w.infos[KEY2] = inconclusive()  # inside its window: no latch, its last pass stays
    async with serving(w) as svc:
        app.include_router(make_health_router(Settings(), accounts_health=svc.health))
        body = TestClient(app).get("/readyz").json()
    ages = "2 key(s) checked, oldest last pass 2400s ago"  # an anonymous route (SR-010)
    detail = f"no accounts store (fake backend): row gauges unset; {ages}"
    assert (body["status"], body["checks"]) == (
        "ok",
        [{"name": "accounts", "ok": True, "detail": detail}],
    )


async def test_failing_counts_a_snapshot_when_the_loop_stores_a_result_mid_count() -> None:
    w = World(target(), info=facts(permissions=WITHDRAW))
    await w.run()
    results = w.check.results
    failed = results[KEY]

    class Storing(str):
        """An outcome whose comparison is where the loop's thread could run: it stores a result
        for another key, as the loop does while `/readyz` counts on a worker thread."""

        def __eq__(self, other: object) -> bool:
            results[KEY2] = failed
            return str.__eq__(self, other)

        __hash__ = str.__hash__

    results[KEY] = replace(failed, outcome=cast(Outcome, Storing("failed")))
    assert w.check.failing == 1  # a live iteration raises "dictionary changed size"
    assert set(results) == {KEY, KEY2}  # the store did happen during the count


async def test_the_app_lists_its_started_accounts_module_on_readyz_ok() -> None:
    app = create_app(Settings(environment=Environment.DEMO))  # fake backend: no self-check
    ctx = app.state.app_context
    await within(ctx.accounts.start(ctx))
    try:
        body = TestClient(app, client=("127.0.0.1", 50000)).get("/readyz").json()
    finally:
        await within(ctx.accounts.stop(1.0))
    detail = "no accounts store (fake backend): row gauges unset"  # no self-check: no key ages
    assert (body["status"], body["checks"]) == (
        "ok",
        [{"name": "accounts", "ok": True, "detail": detail}],
    )


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


async def test_a_boot_pass_past_its_overall_bound_fails_closed_and_the_loop_still_starts() -> None:
    # A zero bound is below every per-key bound: only the boot bound cuts the hang.
    w = World(target(), target(key=KEY2, acct=ACCT2), sleep=Ticks(0), boot_deadline_s=0.0)
    w.hang.add("key_info")
    with capture_logs() as logs:
        await within(w.check.start())
    task = w.check._task
    await within(w.check.stop())
    assert (w.gate.reason_code, w.built) == (UNAVAILABLE, [(KEY, "1000001")])  # KEY2 never ran
    assert w.of("aclose") == [("aclose",)] and task is not None and task.cancelled()
    assert {"event": "key_selfcheck_boot_unfinished", "log_level": "critical"} in logs


def test_the_boot_pass_is_bounded_at_sixty_seconds_unless_told_otherwise() -> None:
    default = inspect.signature(KeySelfCheck).parameters["boot_deadline_s"].default
    assert default == BOOT_DEADLINE_S == 60.0  # the bound the runbook and 20 §7 state


@pytest.mark.parametrize(
    ("interval_s", "refusal"),
    [(0.0, "once a minute"), (MIN_INTERVAL_S - 0.1, "once a minute"), (3600.5, "hourly")],
)
def test_the_interval_is_at_least_a_minute_and_at_most_an_hour(
    interval_s: float, refusal: str
) -> None:
    with pytest.raises(ValueError, match=refusal):
        World(interval_s=interval_s)


async def test_stop_releases_what_the_job_holds_once_its_loop_has_stopped() -> None:
    w, released = World(target(), sleep=Ticks(0)), list[bool]()

    async def release() -> None:
        released.append(w.check._task is None)

    svc = AccountsService()
    svc.attach_key_selfcheck(w.check, release=release)
    await within(svc.start(cast(AppContext, object())))
    await within(svc.stop(1.0))
    assert released == [True]


async def test_a_failed_release_is_logged_and_stop_still_completes() -> None:
    async def release() -> None:
        raise OSError("pool")

    svc = AccountsService()
    svc.attach_key_selfcheck(World(target(), sleep=Ticks(0)).check, release=release)
    await within(svc.start(cast(AppContext, object())))
    with capture_logs() as logs:
        await within(svc.stop(1.0))
    failed = {"event": "key_selfcheck_release_failed", "error": "OSError", "log_level": "warning"}
    assert failed in logs


def sample(w: World, name: str, **labels: str) -> float | None:
    return w.metrics.registry.get_sample_value(name, {"env": "demo", **labels})


@pytest.mark.parametrize(
    ("interval_s", "age", "fresh"),
    [
        (3600.0, HOUR + timedelta(minutes=15), True),
        (3600.0, HOUR + timedelta(minutes=15, microseconds=1), False),
        (600.0, timedelta(minutes=25), True),
        (600.0, timedelta(minutes=25, microseconds=1), False),
    ],
)
def test_a_key_is_fresh_for_one_interval_plus_fifteen_minutes(
    interval_s: float, age: timedelta, fresh: bool
) -> None:
    assert is_fresh(NOW - age, now=NOW, interval_s=interval_s) is fresh


@pytest.mark.parametrize(
    ("elapsed", "latched"),
    [(timedelta(minutes=35), False), (timedelta(minutes=35, seconds=1), True)],
)
async def test_the_watchdog_latches_stale_once_a_last_pass_is_past_its_window(
    elapsed: timedelta, latched: bool
) -> None:
    w = World(target(), target(key=KEY2, acct=ACCT2, age=HOUR * 2 / 3))
    w.infos[KEY2] = inconclusive()  # its last pass stays 40 minutes old; KEY passes at NOW
    await w.run()  # the job runs no more
    w.now = NOW + elapsed
    with capture_logs() as logs:
        w.check.watch()
        w.check.watch()  # a repeat notifies nobody
    stale = [log["key_ids"] for log in logs if log["event"] == "key_selfcheck_stale"]
    assert (w.of("latch"), stale) == (([("latch", STALE)], [[str(KEY2)]]) if latched else ([], []))


async def test_the_row_gauge_loop_runs_the_watchdog_while_the_jobs_loop_is_stalled() -> None:
    w, ticks = World(target(), sleep=Ticks(0)), Ticks(0)  # the job's loop never re-checks
    svc = AccountsService(sleep=ticks)
    svc.attach_key_selfcheck(w.check)
    await within(svc.start(cast(AppContext, object())))  # the boot pass: a pass at NOW
    w.now = NOW + HOUR + timedelta(minutes=16)
    await within(ticks.blocked.wait())  # one pass of the row-gauge loop, its watchdog included
    await within(svc.stop(1.0))
    assert (w.gate.reason_code, len(w.of("pass"))) == (STALE, 1)


async def test_the_watchdog_counts_one_missed_run_per_interval_past_the_grace() -> None:
    w, counted = World(target()), []
    await w.run()  # a run begins at NOW
    with capture_logs() as logs:
        for elapsed in (75 * 60 - 1, 75 * 60, 75 * 60, 135 * 60):
            w.now = NOW + timedelta(seconds=elapsed)
            w.check.watch()
            counted.append(sample(w, "cv_key_selfcheck_missed_runs_total"))
        await w.run()  # a run begins at 135 min: the count starts again from it
        for elapsed in (135 * 60, 210 * 60):
            w.now = NOW + timedelta(seconds=elapsed)
            w.check.watch()
            counted.append(sample(w, "cv_key_selfcheck_missed_runs_total"))
    assert counted == [0, 1, 1, 2, 2, 3]
    runs = [e for e in logs if e["event"] == "key_selfcheck_run_missed"]
    missed = [(e["log_level"], e["missed"]) for e in runs]
    assert missed == [("error", 1), ("error", 2), ("error", 1)]  # none inside the grace


async def test_the_watchdog_before_any_run_counts_and_latches_nothing() -> None:
    w = World(target())
    w.now = NOW + HOUR * 3  # no run has begun, so none is missed yet
    w.check.watch()
    assert (w.events, sample(w, "cv_key_selfcheck_missed_runs_total")) == ([], 0.0)


@pytest.mark.parametrize(
    ("last_error", "info", "latch", "outcome"),
    [
        ("key_withdraw_permission", inconclusive(), FAILED, "failed"),
        ("key_withdraw_permission", None, None, "passed"),  # only a pass ends it
        ("rate_limited", inconclusive(), None, "inconclusive"),  # no verdict: no failure
    ],
    ids=["no-verdict-keeps-it", "a-pass-ends-it", "not-a-rule"],
)
async def test_a_rule_code_in_the_store_is_a_standing_failure_after_a_restart(
    last_error: str, info: object, latch: str | None, outcome: str
) -> None:
    w = World(target(last_error=last_error), info=info)  # a new process: nothing in memory
    await w.run()
    check = w.check.results[KEY]
    assert (w.gate.reason_code, check.outcome, w.check.failing) == (
        latch,
        outcome,
        int(bool(latch)),
    )


async def test_a_failure_survives_a_restart_whose_boot_check_has_no_verdict() -> None:
    before = World(target(), info=facts(permissions=WITHDRAW))
    await before.run()
    [(_, _, rule)] = before.of("error")  # `last_error_code`, as the store keeps it
    after = World(target(last_error=rule), info=inconclusive())
    with capture_logs() as logs:
        await after.run()
    check = after.check.results[KEY]
    assert (after.gate.reason_code, check.code, after.of("error")) == (FAILED, rule, [])
    restored = {"key_id": str(KEY), "rules": [rule], "restored": True, "log_level": "critical"}
    assert {"event": "key_selfcheck_failed", **restored} in logs
    assert sample(after, "cv_keys_failing_policy", rule=rule) == 1.0


async def test_a_restored_failure_keeps_its_stored_last_pass_and_so_its_age() -> None:
    w = World(target(last_error="key_withdraw_permission"), info=inconclusive())
    await w.run()  # a new process: the failure is restored; its last pass is 30 minutes old
    w.now = NOW + timedelta(minutes=10)
    w.check.watch()
    assert (w.check.results[KEY].last_pass_at, w.check.ages()) == (
        NOW - HOUR / 2,
        "1 key(s) checked, oldest last pass 2400s ago",
    )
    assert sample(w, "cv_key_verification_age_seconds") == 2400.0


async def test_a_run_counts_each_verdict_by_result_and_rule() -> None:
    w = World(target(), target(key=KEY2, acct=ACCT2))
    w.infos[KEY2] = facts(permissions=WITHDRAW)
    await w.run()
    w.info = inconclusive()
    await w.run()
    counts = [
        sample(w, "cv_key_verification_total", result=result, rule=rule)
        for result, rule in (
            ("passed", "none"), ("failed", "key_withdraw_permission"), ("inconclusive", "none"),
        )
    ]  # fmt: skip
    assert counts == [1.0, 2.0, 1.0]
    failing = {rule.value: sample(w, "cv_keys_failing_policy", rule=rule.value) for rule in Rule}
    assert failing == {rule.value: float(rule is Rule.WITHDRAW_PERMISSION) for rule in Rule}


@pytest.mark.parametrize(
    ("kwargs", "fail", "result"),
    [
        ({}, None, "passed"),
        ({"info": facts(permissions=WITHDRAW)}, None, "failed"),
        ({"info": inconclusive()}, None, "inconclusive"),
        ({}, RuntimeError("database down"), "error"),
        ({"egress": None}, None, "error"),
    ],
    ids=["passed", "failed", "inconclusive", "key-list", "no-egress-ip"],
)
async def test_each_run_is_counted_by_its_result(
    kwargs: dict[str, Any], fail: Exception | None, result: str
) -> None:
    w = World(target(), **kwargs)
    w.fail = fail
    await w.run()
    assert sample(w, "cv_key_selfcheck_runs_total", result=result) == 1.0


async def test_each_key_check_is_timed_on_the_injected_monotonic_clock() -> None:
    w = World(target())
    w.check._monotonic = iter([100.0, 102.5]).__next__
    await w.run()
    histogram = [
        sample(w, f"cv_key_verification_seconds_{part}", **labels)
        for part, labels in (("count", {}), ("sum", {}), ("bucket", {"le": "2.0"}))
    ]
    assert histogram == [1.0, 2.5, 0.0]


@pytest.mark.parametrize(
    ("expires", "seconds"),
    [
        ((NOW + timedelta(days=30), NOW + timedelta(days=7)), 7 * 86400 - 600.0),
        ((None,) * 2, math.inf),
    ],
)
async def test_the_watchdog_publishes_the_oldest_last_pass_and_the_soonest_expiry(
    expires: tuple[datetime | None, datetime | None], seconds: float
) -> None:
    second = target(key=KEY2, acct=ACCT2, age=HOUR * 2 / 3, expires=expires[1])
    w = World(target(expires=expires[0]), second)
    w.infos[KEY2] = inconclusive()  # its last pass stays 40 minutes old
    await w.run()
    w.now = NOW + timedelta(minutes=10)
    with capture_logs() as logs:
        w.check.watch()
    expiry = sample(w, "cv_key_soonest_expiry_seconds")
    assert (sample(w, "cv_key_verification_age_seconds"), expiry) == (3000.0, seconds)
    ages = {"ages": {str(KEY): 600.0, str(KEY2): 3000.0}, "log_level": "debug"}  # each key's
    assert {"event": "key_selfcheck_ages", **ages} in logs


@pytest.mark.parametrize(("held", "latch"), [(None, UNAVAILABLE), (KEK, KEK)], ids=["job", "kek"])
async def test_a_dead_watchdog_fails_closed_and_reads_degraded_with_no_accounts_store(
    held: str | None, latch: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken() -> None:
        raise KeyError("cv_key_verification_age_seconds")  # a facade missing a series

    w = World(target(), held=held, sleep=Ticks(0))
    monkeypatch.setattr(w.check, "watch", broken)
    with capture_logs() as logs:
        async with serving(w) as svc:
            assert svc._task is not None
            await within(asyncio.wait({svc._task}))  # its done-callback runs before this returns
            status = svc.health().status
    assert (w.gate.reason_code, status) == (latch, HealthStatus.DEGRADED)
    assert {"event": "key_selfcheck_watchdog_died", "log_level": "error"} in logs


async def test_a_clean_stop_of_the_watchdog_loop_latches_nothing() -> None:
    w, ticks = World(target(), sleep=Ticks(0)), Ticks(0)
    svc = AccountsService(sleep=ticks)
    svc.attach_key_selfcheck(w.check)
    await within(svc.start(cast(AppContext, object())))  # the boot pass: a pass at NOW
    await within(ticks.blocked.wait())  # one pass of the row-gauge loop, its watchdog included
    task = svc._task
    await within(svc.stop(1.0))  # its done-callback runs before this returns
    assert task is not None and task.cancelled()  # stopped, not dead: no watchdog died
    assert (w.gate.reason_code, w.of("latch")) == (None, [])


@pytest.mark.parametrize("series", ["cv_key_verification_seconds", "cv_key_verification_total"])
async def test_a_metrics_fault_never_withholds_a_failures_records_or_disarm(
    series: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = World(target(), info=facts(permissions=WITHDRAW))
    real = w.metrics.get

    def get(name: str) -> BoundedMetric:
        if name == series:
            raise KeyError(name)  # a facade missing this series
        return real(name)

    monkeypatch.setattr(w.metrics, "get", get)
    await w.run()
    assert (w.kinds(), w.gate.reason_code) == (WITHDRAW_FAILURE, FAILED)
