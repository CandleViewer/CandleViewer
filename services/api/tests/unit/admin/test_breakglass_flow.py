"""Break-glass CLI flow (E09-S11 #2119 slice 4, SR-023, threat model U10): the flow over
in-memory ports and the real `BreakGlassResetService` (slice 3) over a fake store. Slice 5
composes the real ports and runs them on Postgres."""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import json
import re
import sys
import traceback
import uuid
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.admin import breakglass
from candleviewer.admin.breakglass import (
    CLOSE_GRACE_S,
    BreakGlassFlow,
    BreakGlassPorts,
    RunCancelled,
    confirmation_phrase,
    new_phrase_nonce,
)
from candleviewer.admin.breakglass import BreakGlassExit as X
from candleviewer.admin.errors import BreakGlassUnavailable
from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.audit.journal import ACTOR as JOURNAL_ACTOR
from candleviewer.audit.journal import BREAK_GLASS_ACTIONS
from candleviewer.audit.models import AuditOutcome, ExchangeEnv, Severity
from candleviewer.audit.redact import redact
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.auth.break_glass import BreakGlassRefusal, BreakGlassResetService
from candleviewer.auth.break_glass import BreakGlassStoreRefusal as StoreRefusal
from candleviewer.auth.recovery_codes import hash_recovery_code, normalize_recovery_code
from candleviewer.secrets import KekCheckResult
from candleviewer.settings import Environment

#: The action names approved under R3 (#2119), pinned so that a rename fails here.
ATTEMPT, REFUSED, RESET = (
    "auth.break_glass_attempt",
    "auth.break_glass_refused",
    "auth.break_glass_reset",
)
_OWNER, _OWNER_ID, _RUN = "alice", uuid.UUID(int=7), uuid.UUID(int=9)
_KEY = bytes(range(32))  # test-only HMAC key, not a credential
_CODE = "ABCD-EFGH-JKMN-PQRS-TUVW-XYZ2-3456"  # test value, not a real recovery code
_HASH = hash_recovery_code(_CODE, key=_KEY)
_PROVEN, _DONE = KekCheckResult(3, True, None), (2, 3, 41)  # methods, sessions, event id
_PRE_AUDIT = "Audit: no record could be written (pre-audit refusal); the log has the reason."
_UNRECORDED = "Audit: the outcome record could not be written; the attempt record is kept."
_AUDITED = "Audit: every record reached audit_log."
_CANCELLED = "Cancelled: the line above says how the run ended."
LIVE, DEMO, TESTNET = Environment.LIVE, Environment.DEMO, Environment.TESTNET
DENIED, FAILURE, SUCCESS = AuditOutcome.DENIED, AuditOutcome.FAILURE, AuditOutcome.SUCCESS
P = pytest.param
_Outcome = tuple[int, int, int] | StoreRefusal


def _answer[T](value: T | BaseException) -> T:
    if isinstance(value, BaseException):
        raise value
    return value


@dataclasses.dataclass(eq=False)
class _Trail:
    """`refuse`: an action it cannot keep; `pending`: what `close()` reports (or raises);
    `hang`: "emit" or "close" parks (and sets `entered`) until `release`; `close()` frees
    `lock` (the run lock)."""

    calls: list[str]
    pending: int | BaseException = 0
    refuse: str | None = None
    hang: str | None = None
    lock: list[_Trail] | None = None
    release: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    entered: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    records: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    closed: list[float] = dataclasses.field(default_factory=list)

    async def _park(self, step: str) -> None:
        if self.hang == step:
            self.entered.set()
            await self.release.wait()  # hung unless the test releases it: the flow's timer ends it

    async def emit(self, action: str, **fields: Any) -> None:
        self.calls.append(action)
        await self._park("emit")
        if action == self.refuse:
            raise AuditUnavailable("injected: the trail refused the append")
        self.records.append({"action": action, **fields})

    async def close(self, grace_s: float) -> int:
        self.calls.append("close")
        self.closed.append(grace_s)
        if self.lock is not None and self in self.lock:
            self.lock.remove(self)
        await self._park("close")
        return _answer(self.pending)


@dataclasses.dataclass(repr=False)  # its knobs hold the test code; frames must not show it
class _Host:
    """Every port in memory; the knobs say how each answers, `calls` the order of use."""

    env: Environment = DEMO
    journal_error: BaseException | None = None
    direct_up: bool | BaseException = True
    direct_trail: dict[str, Any] = dataclasses.field(default_factory=dict)  # its `_Trail` knobs
    pending: int | BaseException = 0
    refuse: str | None = None
    kek: KekCheckResult = _PROVEN
    api_up: bool | BaseException | list[bool] = False  # a list: one answer per probe
    owner_id: uuid.UUID | None = _OWNER_ID
    tty: bool | BaseException = True
    typed: str | BaseException | None = None  # None: the phrase the terminal showed
    code: str | BaseException = _CODE
    outcome: _Outcome | Exception = _DONE
    hang: str | None = None  # the port (or journal "emit"/"close") parked until `release`
    hang_after: int = 0  # visits of that port before the one that parks
    lock: list[_Trail] | None = None  # a run lock shared by hosts: one open journal at a time
    calls: list[str] = dataclasses.field(default_factory=list)
    lines: list[str] = dataclasses.field(default_factory=list)
    seen: list[dict[str, str | None]] = dataclasses.field(default_factory=list)
    entered: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    release: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    cut: list[BaseException] = dataclasses.field(default_factory=list)  # what ended a park

    def __post_init__(self) -> None:
        park: dict[str, Any] = {"release": self.release, "entered": self.entered}  # one per test
        self.journal = _Trail(self.calls, self.pending, self.refuse, self.hang, self.lock, **park)
        self.direct = _Trail(self.calls, **self.direct_trail, **park)
        reset = BreakGlassResetService(self, recovery_code_key=_KEY, environment=self.env)
        ports = BreakGlassPorts(
            self.open_journal, self.open_direct, self.prove_kek, self.probe, self.resolve_owner,
            reset, self, new_run_id=lambda: _RUN,
        )  # fmt: skip
        self.flow = BreakGlassFlow(ports)

    async def run(self, owner: str = _OWNER, *, live_flag: bool = False) -> X:
        return await self.flow.run(owner, live_flag=live_flag)

    def _use[T](self, port: str, answer: T | BaseException) -> T:
        self.calls.append(port)
        return _answer(answer)

    async def _port[T](self, port: str, answer: T | BaseException) -> T:
        if port == self.hang and self.calls.count(port) == self.hang_after:
            self.entered.set()
            try:
                await self.release.wait()
            except BaseException as exc:  # the flow's timer or a cancel: kept for its frames
                self.cut.append(exc)
                raise
        return self._use(port, answer)

    async def open_journal(self) -> _Trail:
        journal = await self._port("journal", self.journal_error or self.journal)
        if self.lock is not None:
            if self.lock:  # held, as by cv-api or another run: what the real lock reports
                raise BreakGlassUnavailable("api_running")
            self.lock.append(journal)
        return journal

    async def open_direct(self) -> _Trail | None:
        return self.direct if await self._port("direct", self.direct_up) else None

    async def prove_kek(self) -> KekCheckResult:
        return await self._port("kek", self.kek)

    async def probe(self) -> bool:
        up = self.api_up.pop(0) if isinstance(self.api_up, list) else self.api_up
        return await self._port("probe", up)

    async def resolve_owner(self, identifier: str) -> uuid.UUID | None:
        return await self._port("owner", self.owner_id if identifier == _OWNER else None)

    def is_interactive(self) -> bool:
        return self._use("tty", self.tty)

    def write(self, line: str) -> None:
        self.lines.append(line)
        sys.stdout.write(line + "\n")  # what the operator sees, for capsys

    async def ask(self, prompt: str) -> str:
        shown = self.lines[-1].removeprefix("To confirm, type: ")
        return await self._port("ask", shown if self.typed is None else self.typed)

    async def ask_secret(self, prompt: str) -> str:
        return await self._port("ask_secret", self.code)

    async def reset_owner_mfa(self, target_user_id: str, **kw: Any) -> _Outcome:
        code_hash, corr = kw["recovery_code_hash"], kw["correlation_id"]
        self.seen.append({"target": target_user_id, "hash": code_hash, "corr": corr})
        return await self._port("reset", self.outcome)


async def _parked(w: _Host) -> None:
    """Wait for the `hang` port to park, bounded: a flow that never gets there fails, not hangs."""
    async with asyncio.timeout(5):
        await w.entered.wait()


async def _cancel_exit(running: asyncio.Task[X]) -> X:
    """The exit the re-raised cancel carries once the run ended (bounded too)."""
    await asyncio.wait({running}, timeout=5)
    with pytest.raises(RunCancelled) as cut:
        running.result()  # InvalidStateError if the run is still going
    return cut.value.exit


async def _cancelled(w: _Host, *, live_flag: bool) -> X:
    """Run, cancel once the `hang` port is parked (Ctrl-C under `asyncio.run`), let the port
    answer; the run re-raises the cancel with its exit, which this returns."""
    running = asyncio.create_task(w.run(live_flag=live_flag))
    await _parked(w)
    running.cancel()
    w.release.set()
    return await _cancel_exit(running)


def _rows(records: list[dict[str, Any]]) -> list[tuple[str, AuditOutcome, str | None]]:
    return [(r["action"], r["outcome"], r["reason"]) for r in records]


def _assert_breakglass_record(record: dict[str, Any], env: Environment) -> None:
    """Critical, no user, a label not the identifier, this run, nothing the writer redacts."""
    assert (record["actor_label"], record["actor_user_id"]) == ("system:breakglass", None)
    assert (record["severity"], record["request_id"]) == (Severity.CRITICAL, _RUN)
    assert (record["object_label"], record["env"]) == ("ali***(len=5)", ExchangeEnv(env.value))
    assert redact(record["after_state"]) == record["after_state"]


_NO_FS = ["journal", "direct"]  # no journal and no audit_log either: nothing else runs
_S3 = [*_NO_FS, ATTEMPT, REFUSED, "close"]  # no journal, Postgres up: straight to audit_log
_NO_KEK = ["journal", ATTEMPT, "kek", REFUSED, "close"]
_NO_DIR = BreakGlassUnavailable("host_fs_unavailable")


@pytest.mark.parametrize(("setup", "ran", "refused", "exit_code"), [
    P({"journal_error": _NO_DIR}, _NO_FS, [], X.HOST_FS_UNAVAILABLE, id="journal-dir-not-anchored"),
    P({"journal_error": PermissionError("injected")}, _NO_FS, [], X.HOST_FS_UNAVAILABLE,
      id="journal-unwritable"),
    P({"journal_error": _NO_DIR, "direct_up": True}, _S3, [("host_fs_unavailable", None)],
      X.HOST_FS_UNAVAILABLE, id="S3-records-straight-to-audit-log"),
    *(P({"kek": KekCheckResult(None, False, r)}, _NO_KEK, [("kek_unproven", {"proof": r})],
        X.KEK_UNPROVEN, id=r) for r in ("kek_unavailable", "kek_mismatch", "kek_not_enrolled")),
])  # fmt: skip
async def test_break_glass_requires_host_filesystem_and_kek_present(
    setup: dict[str, Any], ran: list[str], refused: list[tuple[str, Any]], exit_code: X
) -> None:
    # U10 / E09-X04 / S3: no host journal, nothing else runs, and the attempt and refusal go
    # straight to audit_log if Postgres is up; no KEK: attempt + refusal, no reset.
    w = _Host(**{"direct_up": False, **setup})
    assert await w.run() is exit_code
    assert (w.calls, w.seen) == (ran, [])
    records = w.direct.records + w.journal.records
    assert [(r["reason"], r["after_state"]) for r in records if r["action"] == REFUSED] == refused


@pytest.mark.parametrize(("env", "live_flag", "checks"), [
    (DEMO, False, ["kek", "probe", "owner", "tty", "ask", "probe", "reset"]),
    (LIVE, True, ["kek", "probe", "owner", "tty", "ask", "ask_secret", "probe", "reset"]),
])  # fmt: skip
async def test_attempt_record_precedes_every_check(
    env: Environment, live_flag: bool, checks: list[str]
) -> None:
    # cv-api is probed again last, after the prompts, right before the reset (R2c).
    w = _Host(env)
    assert await w.run(live_flag=live_flag) is X.RESET
    assert w.calls == ["journal", ATTEMPT, *checks, RESET, "close"]


@pytest.mark.parametrize(("setup", "status"), [
    P({"kek": KekCheckResult(None, False, "kek_mismatch")}, X.KEK_UNPROVEN, id="SC2-kek"),
    P({"api_up": True}, X.API_RUNNING, id="SC4-api-connected"),
    P({"owner_id": None}, X.NOT_OWNER, id="SC5-unknown-user"),
    P({"outcome": "not_owner"}, X.NOT_OWNER, id="SC5-not-an-active-owner"),
    P({"tty": False}, X.NO_TTY, id="SC7-no-tty"),
    P({"typed": "reset alice on demo"}, X.CONFIRMATION_MISMATCH, id="SC7-mismatch"),
    P({"env": LIVE}, X.LIVE_FLAG_REQUIRED, id="SC6-live-without-flag"),
    P({"env": LIVE, "code": " - "}, X.RECOVERY_CODE_REQUIRED, id="SC6-blank-code"),
    P({"env": LIVE, "outcome": "recovery_code_invalid"}, X.RECOVERY_CODE_INVALID, id="SC6-used"),
])  # fmt: skip
async def test_each_refusal_writes_a_critical_denied_record_with_reason_code(
    setup: dict[str, Any], status: X
) -> None:
    w = _Host(**setup)
    live_flag = w.env is LIVE and status is not X.LIVE_FLAG_REQUIRED
    assert await w.run(live_flag=live_flag) is status
    assert _rows(w.journal.records) == [(ATTEMPT, SUCCESS, None), (REFUSED, DENIED, status.reason)]
    for record in w.journal.records:
        _assert_breakglass_record(record, w.env)
    assert w.journal.closed == [CLOSE_GRACE_S]


async def test_refusals_journaled_when_postgres_down() -> None:
    # S7, Postgres down: no KCV rows, no flush; the records wait in the journal for the fold-in.
    w = _Host(kek=KekCheckResult(None, False, "kek_unavailable"), pending=2)
    assert await w.run() is X.KEK_UNPROVEN
    assert [r["action"] for r in w.journal.records] == [ATTEMPT, REFUSED]
    assert (w.journal.closed, "direct" in w.calls) == ([CLOSE_GRACE_S], False)
    assert "Audit: records waiting in the host journal: 2;" in "\n".join(w.lines)


@pytest.mark.parametrize(("live_flag", "setup", "exit_code", "asked", "hashes"), [
    P(False, {}, X.LIVE_FLAG_REQUIRED, False, [], id="no-live-flag"),
    P(True, {"typed": "reset alice on live"}, X.CONFIRMATION_MISMATCH, False, [], id="no-phrase"),
    P(True, {"code": ""}, X.RECOVERY_CODE_REQUIRED, True, [], id="no-code"),
    P(True, {"outcome": "recovery_code_invalid"}, X.RECOVERY_CODE_INVALID, True, [_HASH],
      id="used"),
    P(True, {"code": TimeoutError()}, X.RECOVERY_CODE_REQUIRED, True, [], id="code-prompt-timeout"),
    P(True, {}, X.RESET, True, [_HASH], id="unused-owner-code"),
])  # fmt: skip
async def test_live_requires_flag_and_phrase(
    live_flag: bool, setup: dict[str, Any], exit_code: X, asked: bool, hashes: list[str]
) -> None:
    # S6: --live, the retyped phrase, then (O3) one Owner recovery code read with echo off;
    # the store sees only its keyed hash, and a refusal consumes nothing.
    w = _Host(LIVE, **setup)
    assert await w.run(live_flag=live_flag) is exit_code
    assert ("ask_secret" in w.calls, [s["hash"] for s in w.seen]) == (asked, hashes)


_PROMPTED = ["journal", ATTEMPT, "kek", "probe", "owner", "tty", "ask", "ask_secret", "probe"]


@pytest.mark.parametrize(("kw", "ran"), [
    P({"journal_error": BreakGlassUnavailable("api_running")},
      ["journal", "direct", ATTEMPT, REFUSED, "close"], id="run-lock-held-by-cv-api"),
    P({"api_up": True}, ["journal", ATTEMPT, "kek", "probe", REFUSED, "close"],
      id="cv-api-session-on-postgres"),
    P({"env": LIVE, "api_up": [False, True]}, [*_PROMPTED, REFUSED, "close"],
      id="cv-api-connected-during-the-prompts"),
])  # fmt: skip
async def test_refuses_while_api_running(kw: dict[str, Any], ran: list[str]) -> None:
    # S4: cv-api holds the run lock: the records go straight to audit_log, nothing else runs.
    # The R2(c) probe catches a cv-api whose lock lives elsewhere but whose sessions are live,
    # also one that connected while the operator answered the prompts.
    w = _Host(**kw)
    assert await w.run(live_flag=w.env is LIVE) is X.API_RUNNING
    assert (w.calls, w.seen) == (ran, [])
    written = [(r["action"], r["reason"]) for r in w.direct.records + w.journal.records]
    assert written == [(ATTEMPT, None), (REFUSED, "api_running")]


async def test_second_run_refused() -> None:
    # Concurrency: the run lock admits one journal. A second run while the first waits at its
    # prompt is refused like a running cv-api and changes nothing; the first's close frees it.
    lock: list[Any] = []
    first, second = _Host(lock=lock, hang="ask"), _Host(lock=lock)
    running = asyncio.create_task(first.run())
    await _parked(first)
    assert await second.run() is X.API_RUNNING
    refused = [r["reason"] for r in second.direct.records]
    assert (refused, second.seen) == ([None, "api_running"], [])
    first.release.set()
    assert (await running, len(first.seen), lock) == (X.RESET, 1, [])
    assert await _Host(lock=lock).run() is X.RESET


@pytest.mark.parametrize(("tty", "typed", "status"), [
    P(False, None, X.NO_TTY, id="no-tty"),
    P(True, "reset alice on live", X.CONFIRMATION_MISMATCH, id="no-nonce"),
    P(True, EOFError(), X.CONFIRMATION_MISMATCH, id="stdin-closed"),
    P(True, TimeoutError(), X.CONFIRMATION_TIMEOUT, id="no-answer"),
])  # fmt: skip
async def test_refuses_without_tty_or_on_confirmation_mismatch(
    tty: bool, typed: str | BaseException | None, status: X
) -> None:
    w = _Host(LIVE, tty=tty, typed=typed)
    assert await w.run(live_flag=True) is status
    assert w.journal.records[-1]["reason"] == status.reason
    assert ("ask_secret" in w.calls, w.seen) == (False, [])


@pytest.mark.parametrize(("env", "live_flag", "consumed"), [(DEMO, False, 0), (LIVE, True, 1)])
async def test_happy_path_resets_owner_writes_outcome_and_raises_critical_system_event(
    env: Environment, live_flag: bool, consumed: int
) -> None:
    w = _Host(env)
    assert await w.run(live_flag=live_flag) is X.RESET
    attempt, reset = w.journal.records
    assert attempt["after_state"] == {"environment": env.value, "live_flag": live_flag}
    assert (reset["action"], reset["outcome"]) == (RESET, SUCCESS)
    assert reset["object_id"] == str(_OWNER_ID)
    counts = {"methods_revoked": 2, "sessions_revoked": 3, "codes_consumed": consumed}
    assert reset["after_state"] == {**counts, "system_event_id": 41}
    # One reset; its transaction writes the critical `break_glass_used` event (slice 3) with
    # this run's id as correlation id, which both records carry as their request id.
    assert [(s["target"], s["corr"]) for s in w.seen] == [(str(_OWNER_ID), str(_RUN))]
    for record in w.journal.records:
        _assert_breakglass_record(record, env)
    shown = "\n".join(w.lines)
    assert f"To confirm, type: reset alice on {env.value} " in shown and "event 41" in shown


async def test_reset_failure_writes_failure_outcome_and_exits_nonzero() -> None:
    w = _Host(LIVE, outcome=ConnectionError("injected: connection lost mid-transaction"))
    exit_code = await w.run(live_flag=True)
    assert (exit_code, int(exit_code) != 0) == (X.RESET_FAILED, True)
    assert _rows(w.journal.records) == [(ATTEMPT, SUCCESS, None), (RESET, FAILURE, "reset_failed")]
    # A link lost at COMMIT may have committed: the record does not claim a rollback.
    state = {"error": "ConnectionError", "outcome": "rolled_back_or_unknown"}
    assert w.journal.records[1]["after_state"] == state


async def test_reset_failure_leaves_no_plaintext_code_in_any_frame() -> None:
    failure = ConnectionError("injected: connection lost mid-transaction")
    assert await _Host(LIVE, outcome=failure).run(live_flag=True) is X.RESET_FAILED
    # No frame of the failed call, the flow's included, still holds the plaintext code.
    frames = [frame for frame, _ in traceback.walk_tb(failure.__traceback__)]
    assert "BreakGlassFlow._reset" in {frame.f_code.co_qualname for frame in frames}
    plain = (_CODE, normalize_recovery_code(_CODE))
    assert not [v for f in frames for v in f.f_locals.values() if any(p in repr(v) for p in plain)]


async def test_rerun_after_a_failed_reset_resets() -> None:
    # S10: the failed run released the run lock and left nothing behind; a re-run resets.
    w = _Host(LIVE, outcome=ConnectionError("injected: connection lost mid-transaction"), lock=[])
    assert await w.run(live_flag=True) is X.RESET_FAILED
    w.outcome = _DONE
    assert await w.run(live_flag=True) is X.RESET


_WAITING = "Audit: records waiting in the host journal: 1; cv-api folds them in."


@pytest.mark.parametrize(("setup", "tail", "resets", "audit"), [
    P({"refuse": ATTEMPT}, ["journal", ATTEMPT, "close"], 0, [_PRE_AUDIT],
      id="attempt-not-durable"),
    P({"refuse": RESET}, ["reset", RESET, "close"], 1, [_UNRECORDED], id="outcome-not-durable"),
    P({"refuse": RESET, "pending": 1}, ["reset", RESET, "close"], 1, [_UNRECORDED, _WAITING],
      id="outcome-not-durable-attempt-not-flushed"),
    P({"refuse": REFUSED, "owner_id": None}, ["owner", REFUSED, "close"], 0, [_UNRECORDED],
      id="refusal-not-durable"),
])  # fmt: skip
async def test_no_option_skips_audit(
    setup: dict[str, Any], tail: list[str], resets: int, audit: list[str]
) -> None:
    # C-4.14: the inputs are the target and --live, no port is a switch, nothing runs without
    # its write-ahead record, and a record the journal cannot keep ends in AUDIT_UNAVAILABLE,
    # with a summary that claims no more than was written (C-2.9).
    assert list(inspect.signature(BreakGlassFlow.run).parameters) == ["self", "owner", "live_flag"]
    assert [f.name for f in dataclasses.fields(BreakGlassPorts)] == [
        "open_journal", "open_direct", "prove_kek", "api_running", "resolve_owner", "reset",
        "terminal", "new_run_id",
    ]  # fmt: skip
    w = _Host(LIVE, **setup)
    assert await w.run(live_flag=True) is X.AUDIT_UNAVAILABLE
    assert (w.calls[-len(tail) :], len(w.seen)) == (tail, resets)
    assert [line for line in w.lines if line.startswith("Audit:")] == audit


async def test_no_secret_in_output_or_logs(capsys: pytest.CaptureFixture[str]) -> None:
    dsn, seed, kek = "LEAK-DSN-PASSWORD-5c1f", "LEAK-TOTP-SEED-JBSWY3DP", "LEAK-KEK-9f8e"
    hosts = [  # each port answers with something that must not travel further
        _Host(LIVE, outcome=ConnectionError(f"{dsn} {seed} {_HASH}")),
        _Host(kek=KekCheckResult(None, False, f"kek_mismatch {kek}")),
        _Host(api_up=OSError(f"password authentication failed: {dsn}")),
        _Host(journal_error=OSError(f"cannot open {dsn}")),
        _Host(LIVE),
    ]
    with capture_logs() as logs:
        exits = [await w.run(live_flag=w.env is LIVE) for w in hosts]
    out = capsys.readouterr()
    records = [r for w in hosts for r in w.journal.records + w.direct.records]
    seen = out.out + out.err + json.dumps(logs, default=str) + json.dumps(records, default=str)
    leaks = [dsn, seed, kek, _CODE, normalize_recovery_code(_CODE), _HASH]
    assert [leak for leak in leaks if leak in seen] == []
    assert exits == [X.RESET_FAILED, X.KEK_UNPROVEN, X.STEP_FAILED, X.HOST_FS_UNAVAILABLE, X.RESET]
    assert hosts[1].journal.records[-1]["after_state"] == {"proof": "kek_unavailable"}
    events = {entry["event"].removeprefix("breakglass.") for entry in logs}
    assert {"reset_failed", "step_failed", "journal_unavailable"} <= events


@pytest.mark.parametrize(("env", "live_flag", "exit_code", "asked_code"), [
    (LIVE, True, X.RESET, True),
    (LIVE, False, X.LIVE_FLAG_REQUIRED, False),
    (DEMO, True, X.LIVE_FLAG_MISMATCH, False),  # --live cannot make a demo deployment live
    (DEMO, False, X.RESET, False),
    (TESTNET, False, X.RESET, False),
])  # fmt: skip
async def test_live_derived_from_environment_not_argv(
    env: Environment, live_flag: bool, exit_code: X, asked_code: bool
) -> None:
    # `live` is the configured environment (arch P9), and only the reset service's: the flow
    # takes no environment of its own, so the two cannot disagree.
    assert "environment" not in inspect.signature(BreakGlassFlow.run).parameters
    assert list(inspect.signature(BreakGlassFlow).parameters) == ["ports"]
    w = _Host(env)
    assert await w.run(live_flag=live_flag) is exit_code
    assert ("ask_secret" in w.calls) is asked_code


@pytest.mark.parametrize(("owner", "label"), [
    ("al ice", "al ***(len=6)"), ("\x1b[2Jalice", "?[2***(len=9)"), ("", "(empty)"),
])  # fmt: skip
async def test_unresolved_identifier_is_labelled_never_echoed(owner: str, label: str) -> None:
    # A typed identifier may hold a pasted secret or control characters: the audit gets a
    # label, and the terminal echoes it only once it names an Owner (in the phrase).
    w = _Host()
    assert await w.run(owner) is X.NOT_OWNER
    assert [r["object_label"] for r in w.journal.records] == [label, label]
    assert [line for line in w.lines if owner and owner in line] == []


_LOCK = BreakGlassUnavailable("api_running")
_UNCONFIRMED = "no change is confirmed. Before re-running, check for an unresolved break_glass_used"
_UNCLOSED = "Audit: the journal did not close cleanly."
_DIRECT_UNCLOSED = "Audit: the audit_log writer did not close cleanly."
_LOCKED_OUT = (REFUSED, DENIED, "api_running")


@pytest.mark.parametrize(("setup", "exit_code", "last", "shown", "audit"), [
    P({"pending": OSError("injected")}, X.RESET, [(RESET, SUCCESS, None)], "done for alice",
      [_UNCLOSED], id="journal-close-fails"),
    P({"tty": RuntimeError("injected")}, X.STEP_FAILED, [(REFUSED, FAILURE, "step_failed")],
      "step_failed: flow", [_AUDITED], id="terminal-port-raises"),
    P({"outcome": ConnectionError("injected")}, X.RESET_FAILED, [(RESET, FAILURE, "reset_failed")],
      _UNCONFIRMED, [_AUDITED], id="reset-raises-outcome-unconfirmed"),
    P({"journal_error": _LOCK, "direct_up": OSError("injected")}, X.API_RUNNING, [],
      "(api_running)", [_PRE_AUDIT], id="audit-log-unreachable"),
    P({"journal_error": _LOCK, "direct_trail": {"refuse": ATTEMPT}}, X.API_RUNNING, [],
      "(api_running)", [_PRE_AUDIT], id="audit-log-refuses"),
    P({"journal_error": _LOCK, "direct_trail": {"refuse": REFUSED}}, X.API_RUNNING, [],
      "(api_running)", [_UNRECORDED], id="audit-log-keeps-only-the-attempt"),
    P({"journal_error": _LOCK, "direct_trail": {"pending": OSError("injected")}}, X.API_RUNNING,
      [_LOCKED_OUT], "(api_running)", [_DIRECT_UNCLOSED], id="audit-log-close-fails"),
])  # fmt: skip
async def test_degraded_ports_fail_closed_with_a_record_where_possible(
    setup: dict[str, Any], exit_code: X, last: list[Any], shown: str, audit: list[str]
) -> None:
    # The summary claims no more than was written, and no less (C-2.9): on the direct path
    # too, it says which records reached audit_log and whether the writer closed cleanly.
    w = _Host(**setup)
    assert await w.run() is exit_code
    assert _rows(w.journal.records + w.direct.records)[1:] == last
    assert shown in "\n".join(w.lines)
    assert [line for line in w.lines if line.startswith("Audit:")] == audit


@pytest.mark.parametrize(("env", "hang", "after"), [
    P(DEMO, "emit", 0, id="at-the-attempt-record"),
    P(DEMO, "ask", 0, id="at-the-phrase-prompt"),
    P(LIVE, "ask_secret", 0, id="at-the-code-prompt"),
    P(LIVE, "probe", 1, id="at-the-last-probe"),
])  # fmt: skip
async def test_cancel_before_reset_writes_operator_cancelled_refusal(
    env: Environment, hang: str, after: int
) -> None:
    # Ctrl-C: the trail still closes with a refusal, no reset starts, the cancel propagates
    # with OPERATOR_CANCELLED (exit 16) as the run's exit.
    w = _Host(env, hang=hang, hang_after=after)
    assert await _cancelled(w, live_flag=env is LIVE) is X.OPERATOR_CANCELLED
    closing = (REFUSED, DENIED, "operator_cancelled")
    assert _rows(w.journal.records) == [(ATTEMPT, SUCCESS, None), closing]
    assert (w.seen, w.journal.closed) == ([], [CLOSE_GRACE_S])
    assert (w.lines[-1], _CANCELLED in w.lines) == (_AUDITED, False)


@pytest.mark.parametrize(("outcome", "closing", "exit_code"), [
    P(_DONE, (RESET, SUCCESS, None), X.RESET, id="reset-commits"),
    P(ConnectionError("injected"), (RESET, FAILURE, "reset_failed"), X.RESET_FAILED,
      id="reset-raises"),
    P("recovery_code_invalid", (REFUSED, DENIED, "recovery_code_invalid"),
      X.RECOVERY_CODE_INVALID, id="reset-refuses"),
])  # fmt: skip
async def test_cancel_during_reset_lets_it_finish_and_records_its_outcome(
    outcome: _Outcome | Exception, closing: tuple[str, AuditOutcome, str | None], exit_code: X
) -> None:
    # A cancel cannot cut the transaction at COMMIT and leave a reset unrecorded: it runs to
    # its end, its real outcome is recorded and shown, then the cancel propagates with that
    # outcome's exit, so a reset that applied is never reported as a cancel.
    w = _Host(LIVE, hang="reset", outcome=outcome)
    assert await _cancelled(w, live_flag=True) is exit_code
    assert _rows(w.journal.records) == [(ATTEMPT, SUCCESS, None), closing]
    assert (len(w.seen), w.journal.closed) == (1, [CLOSE_GRACE_S])
    assert _CANCELLED in w.lines


async def test_reset_cut_short_at_shutdown_is_an_unknown_outcome_not_a_refusal() -> None:
    # A second Ctrl-C makes asyncio.run cancel every task, the reset's too: what it did is
    # unknown, so it is a failed reset that may have applied, never "nothing was changed".
    w = _Host(LIVE, hang="reset")
    running = asyncio.create_task(w.run(live_flag=True))
    await _parked(w)
    running.cancel()
    [reset] = [task for task in asyncio.all_tasks() if task.get_name() == "breakglass.reset"]
    reset.cancel()
    assert await _cancel_exit(running) is X.RESET_FAILED
    assert _rows(w.journal.records)[1:] == [(RESET, FAILURE, "reset_failed")]
    state = {"error": "Interrupted", "outcome": "rolled_back_or_unknown"}
    assert w.journal.records[1]["after_state"] == state
    assert [line for line in w.lines if "nothing was changed" in line] == []


async def test_cancel_leaves_no_plaintext_code_in_any_frame() -> None:
    # Cancelled at the last probe, after the code was read: no frame the cancel unwound, the
    # flow's included, still holds the plaintext code (C-12.6).
    w = _Host(LIVE, hang="probe", hang_after=1)
    await _cancelled(w, live_flag=True)
    frames = [frame for frame, _ in traceback.walk_tb(w.cut[0].__traceback__)]
    assert "BreakGlassFlow._reset" in {frame.f_code.co_qualname for frame in frames}
    plain = (_CODE, normalize_recovery_code(_CODE))
    assert not [v for f in frames for v in f.f_locals.values() if any(p in repr(v) for p in plain)]


_ATTEMPTED, _GAVE_UP = (ATTEMPT, SUCCESS, None), (REFUSED, DENIED, "operator_cancelled")


@pytest.mark.parametrize(("setup", "exit_code", "rows", "audit"), [
    P({"hang": "close"}, X.RESET, [_ATTEMPTED, (RESET, SUCCESS, None)], [_UNCLOSED],
      id="journal-close-after-a-reset"),
    P({"hang": "journal"}, X.OPERATOR_CANCELLED, [_ATTEMPTED, _GAVE_UP], [_AUDITED],
      id="journal-open"),
    P({"journal_error": _LOCK, "hang": "direct"}, X.API_RUNNING, [], [_PRE_AUDIT],
      id="audit-log-open"),
    P({"journal_error": _LOCK, "direct_trail": {"hang": "emit"}}, X.API_RUNNING,
      [_ATTEMPTED, _LOCKED_OUT], [_AUDITED], id="audit-log-record"),
    P({"journal_error": _LOCK, "direct_trail": {"hang": "close"}}, X.API_RUNNING,
      [_ATTEMPTED, _LOCKED_OUT], [_DIRECT_UNCLOSED], id="audit-log-close"),
])  # fmt: skip
async def test_cancel_while_a_trail_opens_records_or_closes_is_summarised_with_its_exit(
    setup: dict[str, Any], exit_code: X, rows: list[Any], audit: list[str]
) -> None:
    # Ctrl-C in the flush grace (S7: Postgres slow or down) or while a trail opens cuts only
    # that step; a record still runs to its end. The summary says where the records are, and
    # the cancel carries how the run ended: a reset that committed stays RESET (exit 0).
    w = _Host(**setup)
    assert await _cancelled(w, live_flag=False) is exit_code
    assert _rows(w.journal.records + w.direct.records) == rows
    assert [line for line in w.lines if line.startswith("Audit:")] == audit
    assert (_CANCELLED in w.lines) is (exit_code is not X.OPERATOR_CANCELLED)


@pytest.mark.parametrize(("setup", "exit_code", "shown"), [
    P({"hang": "journal"}, X.HOST_FS_UNAVAILABLE, "(host_fs_unavailable)", id="open-journal"),
    P({"hang": "direct", "journal_error": _NO_DIR}, X.HOST_FS_UNAVAILABLE, _PRE_AUDIT,
      id="open-audit-log"),
    P({"hang": "kek"}, X.STEP_FAILED, "(step_failed: kek_proof)", id="prove-kek"),
    P({"hang": "ask"}, X.CONFIRMATION_TIMEOUT, "(confirmation_timeout)", id="phrase-prompt"),
    P({"env": LIVE, "hang": "ask_secret"}, X.RECOVERY_CODE_REQUIRED, "(recovery_code_required)",
      id="code-prompt"),
    P({"hang": "emit"}, X.AUDIT_UNAVAILABLE, _PRE_AUDIT, id="attempt-record"),
    P({"hang": "close"}, X.RESET, "Audit: the journal did not close cleanly.", id="close"),
])  # fmt: skip
async def test_hung_port_ends_on_the_flows_timer(
    monkeypatch: pytest.MonkeyPatch, setup: dict[str, Any], exit_code: X, shown: str
) -> None:
    # Every external await is bounded: a port that never answers ends the run on its timer,
    # fail-closed, instead of holding the run lock (and cv-api's boot) forever.
    for timer in ("STEP_TIMEOUT_S", "PROMPT_TIMEOUT_S", "CLOSE_GRACE_S", "CLOSE_SLACK_S"):
        monkeypatch.setattr(breakglass, timer, 0.01)
    w = _Host(**setup)
    running = asyncio.create_task(w.run(live_flag=w.env is LIVE))
    try:  # the flow's own timer ends the run long before 5 s; without one, it fails here
        await asyncio.wait({running}, timeout=5)
        assert running.done() and running.result() is exit_code
    finally:
        w.release.set()  # a port the flow failed to bound answers now: nothing outlives the test
    assert shown in "\n".join(w.lines)


def test_phrase_nonce_is_six_random_hex_digits() -> None:
    nonces = {new_phrase_nonce() for _ in range(5)}
    assert all(re.fullmatch(r"[0-9A-F]{6}", nonce) for nonce in nonces) and len(nonces) > 1


def test_confirmation_phrase_names_owner_environment_and_nonce() -> None:
    assert confirmation_phrase("alice", LIVE, "0A1B2C") == "reset alice on live 0A1B2C"


def test_exit_codes_and_reasons_are_pinned() -> None:
    # The runbook's exit codes and the audit `reason` codes; 0 only for a reset.
    assert {x.reason: int(x) for x in X} == {
        "reset": 0, "step_failed": 1, "reset_failed": 3, "host_fs_unavailable": 4,
        "api_running": 5, "audit_unavailable": 6, "live_flag_required": 7,
        "live_flag_mismatch": 8, "kek_unproven": 9, "not_owner": 10, "no_tty": 11,
        "confirmation_mismatch": 12, "confirmation_timeout": 13, "recovery_code_required": 14,
        "recovery_code_invalid": 15, "operator_cancelled": 16,
    }  # fmt: skip


def test_reset_service_refusals_are_exit_reasons() -> None:
    assert {r.value for r in BreakGlassRefusal} <= {x.reason for x in X}


def test_action_names_and_actor_match_the_audit_registry() -> None:
    # A drift would end every run in AUDIT_UNAVAILABLE (an unknown action) or make cv-api's
    # boot fold-in reject the journal as foreign; slice 1 owns the registry. The flow takes
    # the actor from the journal; `_assert_breakglass_record` pins it on every record.
    flow = {breakglass.ATTEMPT, breakglass.REFUSED, breakglass.RESET}
    assert flow == {ATTEMPT, REFUSED, RESET} == BREAK_GLASS_ACTIONS and flow <= AUDIT_ACTIONS
    assert JOURNAL_ACTOR == "system:breakglass"
