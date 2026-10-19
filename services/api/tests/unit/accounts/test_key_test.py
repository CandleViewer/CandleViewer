"""E27-T03 slice 2b6 (#836): `testApiKey`'s flow over its ports and the job it runs (decision 11).

The job is `test_key_selfcheck.World`'s real `KeySelfCheck`, its store, audit sink and calls one
event log over documented-shape replies; the reads and the WebSocket half are scripted. Clocks are
fakes, and a hang ends at a bound cut to zero, never a sleep, except in one case, which lets a
1 ms bound expire on a socket that never answers, deterministically. No network.
"""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.accounts import key_test as kt
from candleviewer.accounts.errors import AccountNotFoundError
from candleviewer.accounts.key_import import Importer
from candleviewer.accounts.key_test import KeyTest, KeyTested, KeyTestRefused, Probe, Throttle
from candleviewer.accounts.models import ExchangeAccount
from candleviewer.accounts.repository import AccountsRepository
from candleviewer.accounts.selfcheck import FAILED, UNAVAILABLE
from candleviewer.accounts.verification import VerificationInconclusive, VerificationResult
from candleviewer.exchange.bybit import key_info
from candleviewer.storage.repositories.accounts import PolicyDisarm, SelfCheckTargetRow
from tests.contract._admin_support import SPEC
from tests.unit.accounts.test_key_import import ACCT, KEY, OTHER, OWNER, account_row, key_row
from tests.unit.accounts.test_key_selfcheck import (
    DISABLED,
    HOUR,
    NOW,
    TESTED,
    VIOLATION,
    WITHDRAW,
    WITHDRAW_FAILURE,
    World,
    facts,
    inconclusive,
    sample,
    target,
)

ACTOR = Importer(OWNER, "owner", "198.51.100.4", UUID(int=8))
OWNED = {"actor_label": "user:owner", "actor_user_id": OWNER, "actor_ip": "198.51.100.4"}
AUTHED = SimpleNamespace(ok=True, error=None, latency_ms=42)


class Clock:
    """The flow's monotonic clock: it moves only when told."""

    now = 0.0

    def __call__(self) -> float:
        return self.now


class Reads:
    """The owner-scoped account and key reads, scripted; `hang` never answers."""

    def __init__(self, status: str = "active", env: str = "demo", error: Any = None) -> None:
        self.status, self.env, self.error = status, env, error

    async def get_account(self, scope: Any, account_id: UUID) -> Any:
        if self.error == "hang":
            await asyncio.Event().wait()
        if self.error is not None:
            raise self.error
        return account_row(self.env) if account_id == ACCT else None

    async def get_key(self, scope: Any, account_id: UUID, key_id: UUID) -> Any:
        return key_row(KEY, self.status) if (account_id, key_id) == (ACCT, KEY) else None


class Socket:
    """The WebSocket half: answers `result`, raises it, or never answers (`None`)."""

    def __init__(self, result: Any = AUTHED) -> None:
        self.result, self.calls = result, list[UUID]()

    async def __call__(self, key_id: UUID) -> Any:
        self.calls.append(key_id)
        if self.result is None:
            await asyncio.Event().wait()
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class Slow:
    """The job, its REST half taking `took` seconds of the flow's clock."""

    def __init__(self, job: Any, clock: Clock, took: float) -> None:
        self.job, self.clock, self.took = job, clock, took

    async def test(self, *args: Any) -> Any:
        self.clock.now += self.took
        return await self.job.test(*args)


def flow_of(w: World, reads: Reads | None = None, **ports: Any) -> KeyTest:
    accounts = AccountsRepository(reads or Reads())  # type: ignore[arg-type]  # the two reads
    return KeyTest(
        accounts, ports.pop("job", w.check), ports.pop("socket", Socket()), env="demo",
        clock=lambda: NOW, monotonic=ports.pop("clock", Clock()), **ports,
    )  # fmt: skip


async def run(flow: KeyTest, **options: Any) -> KeyTested:
    """One test of `KEY`; the outer bound makes a lost inner one fail instead of hang."""
    async with asyncio.timeout(1.0):
        return await flow.run(ACCT, KEY, ACTOR, **options)


async def test_a_pass_refreshes_the_keys_last_pass_on_a_record_naming_the_owner() -> None:
    w = World(target(age=2 * HOUR))
    done = await run(flow_of(w))
    assert (done.passed, done.checked_at, done.rest.ok, done.rest.ret_code) == (True, NOW, True, 0)
    assert w.kinds() == [("audit", TESTED), ("pass", KEY)] and w.gate.latched_reason_code is None
    record = w.audit(TESTED)
    assert {k: record[k] for k in OWNED} == OWNED and record["request_id"] == UUID(int=8)
    assert w.check.results[KEY].last_pass_at == NOW  # SR-E27-18: fresh again


async def test_a_failure_latches_and_disarms_as_the_hourly_check_and_skips_the_socket() -> None:
    w, socket = World(target(), info=facts(permissions=WITHDRAW)), Socket()
    done = await run(flow_of(w, socket=socket))
    assert w.kinds() == WITHDRAW_FAILURE and w.armed[ACCT] is False  # C-2.8: never waits
    assert sample(w, "cv_keys_failing_policy", rule="key_withdraw_permission") == 1.0  # its page
    assert w.audit(TESTED)["actor_label"] == "user:owner"
    assert w.audit(DISABLED)["actor_label"] == "system:key-selfcheck"
    assert (done.passed, done.websocket, socket.calls) == (False, None, [])  # not signed again
    assert done.verdict is not None and done.verdict.withdraw_enabled


async def test_the_websocket_half_alone_never_latches_or_disarms() -> None:
    w, refused = World(target()), SimpleNamespace(ok=False, error="auth_error", latency_ms=7)
    done = await run(flow_of(w, socket=Socket(refused)))
    assert (done.passed, done.rest.ok) == (False, True)
    assert done.websocket == Probe(False, 7, "auth_error")
    assert w.kinds() == [("audit", TESTED), ("pass", KEY)] and w.armed[ACCT] is True
    assert w.gate.latched_reason_code is None


async def test_a_test_with_no_verdict_changes_nothing_and_still_probes_the_socket() -> None:
    w, socket = World(target(), info=VerificationInconclusive("rate_limited", 10018)), Socket()
    done = await run(flow_of(w, socket=socket))
    assert (done.verdict, done.rest.error, done.rest.ret_code) == (None, "rate_limited", 10018)
    assert (w.kinds(), w.check.results, socket.calls) == ([], {}, [KEY])  # SR-E27-18
    assert not done.passed


async def test_with_no_egress_ip_a_test_signs_and_judges_nothing_as_the_hourly_pass() -> None:
    """Decision 11: a pass with no egress IP judges no key, so neither does a test; its unmet
    whitelist rule is the deployment's, never the key's, so nothing is disarmed or recorded."""
    w, socket = World(target(), egress=None), Socket()
    flow = flow_of(w, socket=socket)
    with capture_logs() as logs, pytest.raises(KeyTestRefused) as refused:
        await run(flow)
    assert (refused.value.code, w.built, socket.calls) == ("exchange_unavailable", [], [])
    assert (w.kinds(), w.armed[ACCT], w.check.results) == ([("latch", UNAVAILABLE)], True, {})
    unset = {"event": "key_selfcheck_no_egress_ip", "key_id": str(KEY), "log_level": "critical"}
    assert unset in logs and flow.throttle.admit(KEY) is None  # nothing probed: its minute back


async def test_a_failure_restored_after_a_restart_answers_a_test_until_a_pass_replaces_it() -> None:
    """Decision 3 leaves a `failed` check with no result: a test reads no verdict from it."""
    w, clock = World(target(last_error="key_withdraw_permission"), info=inconclusive()), Clock()
    await w.run()  # the boot pass, with no verdict: the stored rule is a standing failure
    restored, flow = w.check.results[KEY], flow_of(w, clock=clock)
    assert (restored.outcome, restored.result) == ("failed", None)
    done = await run(flow)
    assert (done.passed, done.verdict, done.rest.error) == (False, None, "rate_limited")
    assert w.check.results[KEY] is restored and w.gate.latched_reason_code == FAILED
    w.info, clock.now = facts(), 60.0  # fixed at the exchange, tested a minute later
    passed = await run(flow)
    check = w.check.results[KEY]
    assert passed.passed and (check.outcome, check.result) == ("passed", passed.verdict)
    assert w.gate.latched_reason_code == FAILED  # only a restart clears the latch


async def test_the_rest_half_ends_at_the_jobs_deadline_with_no_verdict() -> None:
    w = World(target(), key_deadline_s=0.0)
    w.hang = {"key_info"}
    done = await run(flow_of(w))
    assert (done.verdict, done.rest.ok, done.rest.error) == (None, False, "timeout")
    assert w.kinds() == [] and w.check.results == {}


@pytest.mark.parametrize(("took", "dialled"), [(11.999, [KEY]), (12.0, []), (12.5, [])])
async def test_the_socket_half_gets_only_what_is_left_of_the_twelve_seconds(
    took: float, dialled: list[UUID]
) -> None:
    """A socket that never answers is cut at what is left (here 1 ms); with nothing left the port
    is never called, so no open of the deployment's budget is spent (SR-E27-05)."""
    w, clock, socket = World(target()), Clock(), Socket(None)  # a socket that never answers
    done = await run(flow_of(w, job=Slow(w.check, clock, took), clock=clock, socket=socket))
    assert (done.websocket, socket.calls) == (Probe(False, None, "timeout"), dialled)


@pytest.mark.parametrize(
    "error",
    [
        type("Refusal", (Exception,), {"code": "kek_unavailable"})("m2 refused"),
        RuntimeError("no signing capability is wired"),
    ],
    ids=["m2-refused", "unwired"],
)
async def test_a_socket_half_that_raises_is_service_unavailable_never_the_keys_auth_error(
    error: Exception,
) -> None:
    """A port that raises is CandleViewer's own fault (M2 refusing to sign, say), never the key's:
    the exchange did not refuse it. It stays the half's result and never fails the test."""
    with capture_logs() as logs:
        done = await run(flow_of(World(target()), socket=Socket(error)))
    assert done.websocket == Probe(False, None, "service_unavailable") and not done.passed
    failed = {"event": "key_test_ws_failed", "key_id": str(KEY), "log_level": "warning"}
    assert failed | {"error": type(error).__name__} in logs


async def test_without_include_ws_the_socket_half_does_not_run() -> None:
    socket = Socket()
    done = await run(flow_of(World(target()), socket=socket), include_ws=False)
    assert (done.passed, done.websocket, socket.calls) == (True, None, [])


@pytest.mark.parametrize(
    ("reads", "key_id", "error", "code"),
    [
        (Reads(env="live"), KEY, AccountNotFoundError, "not found"),  # no oracle: as a missing one
        (Reads(), OTHER, AccountNotFoundError, "not found"),
    ],
    ids=["other-env", "other-key"],
)
async def test_a_key_that_cannot_be_tested_is_refused_before_anything_is_signed(
    reads: Reads, key_id: UUID, error: type[Exception], code: str
) -> None:
    w = World(target())
    with pytest.raises(error, match=f"^{code}$"):
        await flow_of(w, reads).run(ACCT, key_id, ACTOR)
    assert w.built == [] and w.events == []


@pytest.mark.parametrize(
    ("status", "signed"),
    [("active", True), ("rotating", True)]  # rotating: the old key through a rotation's overlap
    + [(status, False) for status in ("pending", "revoked", "invalid", "expired")],
)
async def test_only_an_active_or_rotating_key_is_signed_with(status: str, signed: bool) -> None:
    """The contract's `Not signable`: any other key is a `409 conflict` (its detail: the route's
    tests), and nothing is signed."""
    w = World(target())
    with nullcontext() if signed else pytest.raises(KeyTestRefused, match=r"^conflict$"):
        await run(flow_of(w, Reads(status)))
    assert bool(w.built) is signed


@pytest.mark.parametrize("error", [RuntimeError("store down"), "hang"])
async def test_a_store_that_fails_or_hangs_is_store_unavailable(error: Any) -> None:
    w = World(target())
    with pytest.raises(KeyTestRefused) as refused:
        await run(flow_of(w, Reads(error=error), timeout_s=0.0))
    assert (refused.value.code, w.built) == ("store_unavailable", [])


async def test_a_second_test_inside_the_minute_is_throttled_and_probes_nothing() -> None:
    w, clock = World(target()), Clock()
    flow = flow_of(w, clock=clock)
    await run(flow)
    clock.now = 19.0
    with pytest.raises(KeyTestRefused) as refused:
        await run(flow)
    assert (refused.value.code, refused.value.retry_after_s) == ("rate_limited", 41)
    assert len(w.built) == 1  # the first test's calls only


@pytest.mark.parametrize(
    ("code", "answer"),
    [("kek_unavailable", "kek_unavailable"), ("credential_unavailable", "exchange_unavailable")],
)
async def test_m2_refusing_to_sign_probes_nothing_and_gives_the_minute_back(
    code: str, answer: str
) -> None:
    w = World(target(), info=type("Refusal", (Exception,), {"code": code})("refused"))
    flow = flow_of(w)
    with pytest.raises(KeyTestRefused) as refused:
        await run(flow)
    assert (refused.value.code, w.kinds(), flow.throttle.admit(KEY)) == (answer, [], None)


async def test_any_other_error_of_the_rest_half_propagates() -> None:
    with pytest.raises(RuntimeError, match="defect"):
        await run(flow_of(World(target(), info=RuntimeError("defect"))))


async def test_the_job_refuses_a_key_of_another_environment_before_signing() -> None:
    w = World(target())
    live = ExchangeAccount.model_validate(account_row("live"), from_attributes=True)
    with pytest.raises(ValueError, match="environment"):
        await w.check.test(target(), live, NOW, OWNED)
    assert w.built == []


class Meeting(World):
    """Each `mark_disarm_audited` waits at its own gate, by order of arrival, so a test's mark and
    a pass's are in flight at once and either can finish first."""

    def __init__(self, *rows: SelfCheckTargetRow, **options: Any) -> None:
        super().__init__(*rows, **options)
        self.arrived = [asyncio.Event(), asyncio.Event()]
        self.opened = [asyncio.Event(), asyncio.Event()]
        self.marks = 0

    async def mark_disarm_audited(self, disarm: PolicyDisarm, *, at: datetime) -> bool:
        n, self.marks = self.marks, self.marks + 1
        self.arrived[n].set()
        await self.opened[n].wait()
        return await super().mark_disarm_audited(disarm, at=at)


@pytest.mark.parametrize(
    ("first", "audited"),
    [
        (0, [TESTED, DISABLED, VIOLATION, TESTED, VIOLATION]),
        (1, [TESTED, DISABLED, TESTED, VIOLATION, VIOLATION]),
    ],
    ids=["test-marks-first", "pass-marks-first"],
)
async def test_a_test_and_a_pass_marking_one_disarm_at_once_both_finish(
    first: int, audited: list[str]
) -> None:
    """A test runs outside the pass's lock: a pass reads the test's disarm as owed before the test
    marks it, so both mark it, and the second finds it marked. Neither raises, so the loop goes on
    and the test answers, its violation record written."""
    w = Meeting(target(), info=facts(permissions=WITHDRAW))
    async with asyncio.timeout(1.0):
        tested = asyncio.create_task(flow_of(w).run(ACCT, KEY, ACTOR))
        await w.arrived[0].wait()  # the test sent its disarm's record; its mark is held
        passed = asyncio.create_task(w.check.run_once())
        await w.arrived[1].wait()  # the pass read the disarm as owed: only its mark is retried
        callers = [tested, passed]
        for n in (first, 1 - first):
            w.opened[n].set()
            await callers[n]
    assert [e[1] for e in w.of("audit")] == audited  # one `account.disabled_by_policy`
    assert (w.disarms[ACCT][2], len(w.of("mark")), w.armed[ACCT]) == (NOW, 2, False)
    assert not tested.result().passed


def test_the_throttle_opens_one_window_per_key_and_says_how_long_is_left() -> None:
    clock = Clock()
    throttle = Throttle(monotonic=clock)
    assert throttle.admit(KEY) is None
    clock.now = 19.0
    assert (throttle.admit(KEY), throttle.admit(OTHER)) == (41, None)
    clock.now = 59.5
    assert throttle.admit(KEY) == 1
    clock.now = 60.0
    assert throttle.admit(KEY) is None  # its window ended, so a new one opens


def test_a_full_throttle_refuses_until_its_oldest_window_ends_and_drops_none_early() -> None:
    clock, (k1, k2, k3) = Clock(), (UUID(int=21), UUID(int=22), UUID(int=23))
    throttle = Throttle(cap=2, monotonic=clock)
    assert throttle.admit(k1) is None
    clock.now = 10.0
    assert throttle.admit(k2) is None
    clock.now = 20.0
    assert (throttle.admit(k3), throttle.admit(k1)) == (40, 40)  # k1 is never evicted for k3
    clock.now = 60.0  # k1's window ends: its entry goes, and k3 takes the place
    assert (throttle.admit(k3), throttle.admit(k2)) == (None, 10)
    throttle.release(k2)
    assert throttle.admit(k2) is None


def _result(key_info_code: int | None, probe_code: int | None = None) -> VerificationResult:
    return VerificationResult(False, key_info_ret_code=key_info_code, probe_ret_code=probe_code)


@pytest.mark.parametrize(
    ("result", "shown"),
    [
        (_result(0, 0), (True, None, 0)),
        (_result(0), (True, None, 0)),  # a check failed before the probe: the call made was ok
        (_result(10003), (False, "auth_error", 10003)),
        (_result(10010), (False, "ip_not_allowed", 10010)),
        (_result(0, 10005), (False, "permission_denied", 10005)),
        (_result(33004), (False, "exchange_unknown", 33004)),
        (_result(None), (False, None, None)),  # M2 refused the stored row: no call was made
    ],
)
def test_a_verdicts_rest_half_is_shown_by_the_last_call_it_made(
    result: VerificationResult, shown: tuple[bool, str | None, int | None]
) -> None:
    rest = kt._answered(result, 0.118)
    assert (rest.ok, rest.error, rest.ret_code, rest.latency_ms) == (*shown, 118)


@pytest.mark.parametrize(
    ("error", "name"),
    [
        (VerificationInconclusive("probe_slow"), "timeout"),
        (VerificationInconclusive("probe_clock_step"), "clock_drift"),
        (VerificationInconclusive("check_error"), "exchange_unknown"),
        (TimeoutError(), "timeout"),
    ],
)
def test_no_verdict_is_shown_by_a_key_probe_error_name(error: Exception, name: str) -> None:
    assert kt._unanswered(error, 5.0) == Probe(False, 5000, name)


def test_the_flows_names_are_the_adapters_and_the_contracts() -> None:
    assert kt.PROBE_ERRORS == key_info.PROBE_ERRORS
    assert kt.PROBE_ERRORS == set(SPEC["components"]["schemas"]["KeyProbeError"]["enum"])
    names = key_info._PROBE_CODES
    verdicts = {code: names.get(code, "exchange_unknown") for code in key_info._VERDICTS}
    assert verdicts == {**kt._REFUSED, 33004: "exchange_unknown"}
