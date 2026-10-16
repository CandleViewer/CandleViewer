"""Break-glass CLI flow (E09-S11 #2119 slice 4, SR-023, threat model U10): the flow over
in-memory ports and the real `BreakGlassResetService` (slice 3) over a fake store. Slice 5
composes the real ports and runs them on Postgres."""

from __future__ import annotations

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

from candleviewer.admin.breakglass import (
    CLOSE_GRACE_S,
    BreakGlassFlow,
    BreakGlassPorts,
    confirmation_phrase,
    new_phrase_nonce,
)
from candleviewer.admin.breakglass import BreakGlassExit as X
from candleviewer.admin.errors import BreakGlassUnavailable
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
LIVE, DEMO, TESTNET = Environment.LIVE, Environment.DEMO, Environment.TESTNET
DENIED, FAILURE, SUCCESS = AuditOutcome.DENIED, AuditOutcome.FAILURE, AuditOutcome.SUCCESS
P = pytest.param
_Outcome = tuple[int, int, int] | StoreRefusal


def _answer[T](value: T | BaseException) -> T:
    if isinstance(value, BaseException):
        raise value
    return value


class _Trail:
    """`refuse`: an action it cannot keep; `pending`: what `close()` reports (or raises)."""

    def __init__(self, calls: list[str], pending: int | BaseException, refuse: str | None) -> None:
        self.calls, self.pending, self.refuse = calls, pending, refuse
        self.records: list[dict[str, Any]] = []
        self.closed: list[float] = []

    async def emit(self, action: str, **fields: Any) -> None:
        self.calls.append(action)
        if action == self.refuse:
            raise AuditUnavailable("injected: the trail refused the append")
        self.records.append({"action": action, **fields})

    async def close(self, grace_s: float) -> int:
        self.calls.append("close")
        self.closed.append(grace_s)
        return _answer(self.pending)


@dataclasses.dataclass(repr=False)  # its knobs hold the test code; frames must not show it
class _Host:
    """Every port in memory; the knobs say how each answers, `calls` the order of use."""

    env: Environment = DEMO
    journal_error: BaseException | None = None
    direct_up: bool | BaseException = True
    direct_refuse: str | None = None
    pending: int | BaseException = 0
    refuse: str | None = None
    kek: KekCheckResult = _PROVEN
    api_up: bool | BaseException = False
    owner_id: uuid.UUID | None = _OWNER_ID
    tty: bool | BaseException = True
    typed: str | BaseException | None = None  # None: the phrase the terminal showed
    code: str | BaseException = _CODE
    outcome: _Outcome | Exception = _DONE
    calls: list[str] = dataclasses.field(default_factory=list)
    lines: list[str] = dataclasses.field(default_factory=list)
    seen: list[dict[str, str | None]] = dataclasses.field(default_factory=list)

    def __post_init__(self) -> None:
        self.journal = _Trail(self.calls, self.pending, self.refuse)
        self.direct = _Trail(self.calls, 0, self.direct_refuse)
        reset = BreakGlassResetService(self, recovery_code_key=_KEY, environment=self.env)
        ports = BreakGlassPorts(
            self.open_journal, self.open_direct, self.prove_kek, self.probe, self.resolve_owner,
            reset, self, new_run_id=lambda: _RUN,
        )  # fmt: skip
        self.flow = BreakGlassFlow(ports, environment=self.env)

    async def run(self, owner: str = _OWNER, *, live_flag: bool = False) -> X:
        return await self.flow.run(owner, live_flag=live_flag)

    def _use[T](self, port: str, answer: T | BaseException) -> T:
        self.calls.append(port)
        return _answer(answer)

    async def open_journal(self) -> _Trail:
        return self._use("journal", self.journal_error or self.journal)

    async def open_direct(self) -> _Trail | None:
        return self.direct if self._use("direct", self.direct_up) else None

    async def prove_kek(self) -> KekCheckResult:
        return self._use("kek", self.kek)

    async def probe(self) -> bool:
        return self._use("probe", self.api_up)

    async def resolve_owner(self, identifier: str) -> uuid.UUID | None:
        return self._use("owner", self.owner_id if identifier == _OWNER else None)

    def is_interactive(self) -> bool:
        return self._use("tty", self.tty)

    def write(self, line: str) -> None:
        self.lines.append(line)
        sys.stdout.write(line + "\n")  # what the operator sees, for capsys

    async def ask(self, prompt: str) -> str:
        shown = self.lines[-1].removeprefix("To confirm, type: ")
        return self._use("ask", shown if self.typed is None else self.typed)

    async def ask_secret(self, prompt: str) -> str:
        return self._use("ask_secret", self.code)

    async def reset_owner_mfa(self, target_user_id: str, **kw: Any) -> _Outcome:
        code_hash, corr = kw["recovery_code_hash"], kw["correlation_id"]
        self.seen.append({"target": target_user_id, "hash": code_hash, "corr": corr})
        return self._use("reset", self.outcome)


def _rows(records: list[dict[str, Any]]) -> list[tuple[str, AuditOutcome, str | None]]:
    return [(r["action"], r["outcome"], r["reason"]) for r in records]


def _assert_breakglass_record(record: dict[str, Any], env: Environment) -> None:
    """Critical, no user, a label not the identifier, this run, nothing the writer redacts."""
    assert (record["actor_label"], record["actor_user_id"]) == ("system:breakglass", None)
    assert (record["severity"], record["request_id"]) == (Severity.CRITICAL, _RUN)
    assert (record["object_label"], record["env"]) == ("ali***(len=5)", ExchangeEnv(env.value))
    assert redact(record["after_state"]) == record["after_state"]


_NO_FS = ["journal", "direct"]  # no journal and no audit_log either: nothing else runs
_NO_KEK = ["journal", ATTEMPT, "kek", REFUSED, "close"]


@pytest.mark.parametrize(("setup", "ran", "refusals", "exit_code"), [
    P({"journal_error": BreakGlassUnavailable("host_fs_unavailable")}, _NO_FS, [],
      X.HOST_FS_UNAVAILABLE, id="journal-dir-not-anchored"),
    P({"journal_error": PermissionError("injected")}, _NO_FS, [], X.HOST_FS_UNAVAILABLE,
      id="journal-unwritable"),
    *(P({"kek": KekCheckResult(None, False, r)}, _NO_KEK, [{"proof": r}], X.KEK_UNPROVEN, id=r)
      for r in ("kek_unavailable", "kek_mismatch", "kek_not_enrolled")),
])  # fmt: skip
async def test_break_glass_requires_host_filesystem_and_kek_present(
    setup: dict[str, Any], ran: list[str], refusals: list[dict[str, str]], exit_code: X
) -> None:
    # U10 / E09-X04: no host journal, nothing else runs; no KEK, attempt + refusal, no reset.
    w = _Host(direct_up=False, **setup)
    assert await w.run() is exit_code
    assert (w.calls, w.seen) == (ran, [])
    assert [r["after_state"] for r in w.journal.records if r["action"] == REFUSED] == refusals


@pytest.mark.parametrize(("env", "live_flag", "checks"), [
    (DEMO, False, ["kek", "probe", "owner", "tty", "ask", "reset"]),
    (LIVE, True, ["kek", "probe", "owner", "tty", "ask", "ask_secret", "reset"]),
])  # fmt: skip
async def test_attempt_record_precedes_every_precondition_check(
    env: Environment, live_flag: bool, checks: list[str]
) -> None:
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


async def test_refusal_records_stay_in_journal_when_postgres_is_down() -> None:
    # Postgres down: no KCV rows, no flush; the records wait in the journal for the fold-in.
    w = _Host(kek=KekCheckResult(None, False, "kek_unavailable"), pending=2)
    assert await w.run() is X.KEK_UNPROVEN
    assert [r["action"] for r in w.journal.records] == [ATTEMPT, REFUSED]
    assert (w.journal.closed, "direct" in w.calls) == ([CLOSE_GRACE_S], False)
    assert "Audit: records waiting in the host journal: 2;" in "\n".join(w.lines)


@pytest.mark.parametrize(("live_flag", "code", "outcome", "exit_code", "asked", "hashes"), [
    P(False, _CODE, _DONE, X.LIVE_FLAG_REQUIRED, False, [], id="no-live-flag"),
    P(True, "", _DONE, X.RECOVERY_CODE_REQUIRED, True, [], id="no-code"),
    P(True, _CODE, "recovery_code_invalid", X.RECOVERY_CODE_INVALID, True, [_HASH], id="used"),
    P(True, TimeoutError(), _DONE, X.RECOVERY_CODE_REQUIRED, True, [], id="code-prompt-timeout"),
    P(True, _CODE, _DONE, X.RESET, True, [_HASH], id="unused-owner-code"),
])  # fmt: skip
async def test_live_requires_explicit_flag_and_unused_recovery_code(
    live_flag: bool, code: Any, outcome: Any, exit_code: X, asked: bool, hashes: list[str]
) -> None:
    # Read with echo off after --live and the phrase; the store sees only its keyed hash.
    w = _Host(LIVE, code=code, outcome=outcome)
    assert await w.run(live_flag=live_flag) is exit_code
    assert ("ask_secret" in w.calls, [s["hash"] for s in w.seen]) == (asked, hashes)


@pytest.mark.parametrize(("kw", "ran"), [
    P({"journal_error": BreakGlassUnavailable("api_running")},
      ["journal", "direct", ATTEMPT, REFUSED, "close"], id="run-lock-held-by-cv-api"),
    P({"api_up": True}, ["journal", ATTEMPT, "kek", "probe", REFUSED, "close"],
      id="cv-api-session-on-postgres"),
])  # fmt: skip
async def test_refuses_while_api_instance_lock_is_held(kw: dict[str, Any], ran: list[str]) -> None:
    # cv-api holds the run lock: the records go straight to audit_log, nothing else runs. The
    # R2(c) probe catches a cv-api whose lock lives elsewhere but whose sessions are live.
    w = _Host(**kw)
    assert await w.run() is X.API_RUNNING
    assert (w.calls, w.seen) == (ran, [])
    written = [(r["action"], r["reason"]) for r in w.direct.records + w.journal.records]
    assert written == [(ATTEMPT, None), (REFUSED, "api_running")]


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
    failure = ConnectionError("injected: connection lost mid-transaction")
    w = _Host(LIVE, outcome=failure)
    exit_code = await w.run(live_flag=True)
    assert (exit_code, int(exit_code) != 0) == (X.RESET_FAILED, True)
    assert _rows(w.journal.records) == [(ATTEMPT, SUCCESS, None), (RESET, FAILURE, "reset_failed")]
    assert w.journal.records[1]["after_state"] == {"error": "ConnectionError"}
    # No frame of the failed call, the flow's included, still holds the plaintext code.
    frames = [frame for frame, _ in traceback.walk_tb(failure.__traceback__)]
    assert "BreakGlassFlow._reset" in {frame.f_code.co_qualname for frame in frames}
    plain = (_CODE, normalize_recovery_code(_CODE))
    assert not [v for f in frames for v in f.f_locals.values() if any(p in repr(v) for p in plain)]
    assert await _Host(LIVE).run(live_flag=True) is X.RESET  # S10: rolled back, a re-run works


@pytest.mark.parametrize(("refuse", "tail", "resets"), [
    P(ATTEMPT, ["journal", ATTEMPT, "close"], 0, id="attempt-not-durable"),
    P(RESET, ["reset", RESET, "close"], 1, id="outcome-not-durable"),
])  # fmt: skip
async def test_no_option_skips_audit(refuse: str, tail: list[str], resets: int) -> None:
    # C-4.14: the inputs are the target and --live, no port is a switch, nothing runs without
    # its write-ahead record, and a record the journal cannot keep ends in AUDIT_UNAVAILABLE.
    assert list(inspect.signature(BreakGlassFlow.run).parameters) == ["self", "owner", "live_flag"]
    assert [f.name for f in dataclasses.fields(BreakGlassPorts)] == [
        "open_journal", "open_direct", "prove_kek", "api_running", "resolve_owner", "reset",
        "terminal", "new_run_id",
    ]  # fmt: skip
    w = _Host(LIVE, refuse=refuse)
    assert await w.run(live_flag=True) is X.AUDIT_UNAVAILABLE
    assert (w.calls[-len(tail) :], len(w.seen)) == (tail, resets)


async def test_no_secret_in_captured_output_or_logs(capsys: pytest.CaptureFixture[str]) -> None:
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
    # `live` is the configured environment (arch P9), as for the reset service.
    assert "environment" not in inspect.signature(BreakGlassFlow.run).parameters
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


@pytest.mark.parametrize(("setup", "exit_code", "last", "shown"), [
    P({"pending": OSError("injected")}, X.RESET, [(RESET, SUCCESS, None)], "did not close cleanly",
      id="journal-close-fails"),
    P({"tty": RuntimeError("injected")}, X.STEP_FAILED, [(REFUSED, FAILURE, "step_failed")],
      "step_failed: flow", id="terminal-port-raises"),
    P({"journal_error": _LOCK, "direct_up": OSError("injected")}, X.API_RUNNING, [],
      "pre-audit refusal", id="audit-log-unreachable"),
    P({"journal_error": _LOCK, "direct_refuse": ATTEMPT}, X.API_RUNNING, [], "pre-audit refusal",
      id="audit-log-refuses"),
])  # fmt: skip
async def test_degraded_ports_fail_closed_with_a_record_where_possible(
    setup: dict[str, Any], exit_code: X, last: list[Any], shown: str
) -> None:
    w = _Host(**setup)
    assert await w.run() is exit_code
    assert _rows(w.journal.records + w.direct.records)[1:] == last
    assert shown in "\n".join(w.lines)


def test_nonce_phrase_exit_codes_and_reasons() -> None:
    nonces = {new_phrase_nonce() for _ in range(5)}
    assert all(re.fullmatch(r"[0-9A-F]{6}", nonce) for nonce in nonces) and len(nonces) > 1
    assert confirmation_phrase("alice", LIVE, "0A1B2C") == "reset alice on live 0A1B2C"
    # The runbook's exit codes and the audit `reason` codes, pinned; 0 only for a reset.
    assert {x.reason: int(x) for x in X} == {
        "reset": 0, "step_failed": 1, "reset_failed": 3, "host_fs_unavailable": 4,
        "api_running": 5, "audit_unavailable": 6, "live_flag_required": 7,
        "live_flag_mismatch": 8, "kek_unproven": 9, "not_owner": 10, "no_tty": 11,
        "confirmation_mismatch": 12, "confirmation_timeout": 13, "recovery_code_required": 14,
        "recovery_code_invalid": 15,
    }  # fmt: skip
    assert {r.value for r in BreakGlassRefusal} <= {x.reason for x in X}
