"""The host gate the offline CLIs share (#4479 PR-A; SR-023, threat model Sec.3.6.1).

Break-glass's own suites pin its behaviour on the gate; these pin the gate's seams. A second
flow's `GateSpec` brings its own actions, actor, phrase verb, log events, task names and exit
status through it, on every path the gate ends a run on. Every flow's exit status keeps the gate's
numbers (`GATE_STATUSES`); a spec that breaks them, or names an unregistered action or a user
actor, is refused when it is built. Whatever the flow, the gate runs its checks in one order
before the flow's act: the live flag, the KEK proof, the cv-api probe, the flow's target, then the
TTY and the phrase. Its steps are final, and a hook's verdict that breaks its contract is recorded
as a step failure. The host journal's trails take only the actions they declare. Over the
break-glass test host's in-memory ports and `_Trail`; no network, no files outside `tmp_path`."""

from __future__ import annotations

import asyncio
import dataclasses
import re
import uuid
from enum import IntEnum
from io import FileIO
from pathlib import Path
from typing import Any, cast

import pytest
from structlog.testing import capture_logs

from candleviewer.admin import breakglass, breakglass_wiring
from candleviewer.admin.breakglass import (
    GATE_STATUSES,
    BreakGlassExit,
    BreakGlassFlow,
    GateRecords,
    GateSpec,
    HostGatedFlow,
    RunCancelled,
    Verdict,
)
from candleviewer.audit.actions import UnknownAuditAction
from candleviewer.audit.models import AuditOutcome
from candleviewer.audit.repository import AuditRepository
from candleviewer.audit.writer import AuditWriter
from candleviewer.secrets import KekCheckResult
from candleviewer.settings import Environment
from tests.unit.admin.test_breakglass_flow import (
    _AUDITED,
    _CANCELLED,
    _OWNER_ID,
    _RUN,
    _answer,
    _Host,
    _parked,
)

#: A second CLI's actions: registered ones (`GateSpec` refuses any other), none of break-glass's.
#: Any three would do; the toy flow is not the KEK rotation, it only borrows its names.
ATTEMPT, REFUSED, DONE = (
    "security.kek_rotation_started",
    "security.kek_rotation_refused",
    "security.kek_rotated",
)
DENIED, FAILURE, SUCCESS = AuditOutcome.DENIED, AuditOutcome.FAILURE, AuditOutcome.SUCCESS
P = pytest.param


class ToyExit(IntEnum):
    """A second CLI's exit status: the gate's statuses with their numbers, then its own."""

    DONE = 0
    STEP_FAILED = 1
    DONE_FAILED = 3
    HOST_FS_UNAVAILABLE = 4
    API_RUNNING = 5
    AUDIT_UNAVAILABLE = 6
    LIVE_FLAG_REQUIRED = 7
    LIVE_FLAG_MISMATCH = 8
    KEK_UNPROVEN = 9
    NO_TTY = 11
    CONFIRMATION_MISMATCH = 12
    CONFIRMATION_TIMEOUT = 13
    OPERATOR_CANCELLED = 16
    NO_TARGET = 17


_TOY = GateSpec(
    "toygate", "system:toygate", ATTEMPT, REFUSED, DONE, "toy", ToyExit, "DONE", "DONE_FAILED"
)


@dataclasses.dataclass(frozen=True, slots=True)
class _Ports:
    """The gate's own ports (`GatePorts`), none of break-glass's."""

    open_journal: Any
    open_direct: Any
    prove_kek: Any
    api_running: Any
    terminal: Any
    new_run_id: Any


class _Toy(HostGatedFlow[uuid.UUID]):
    """A second offline CLI on the gate: it looks its target up, then acts once."""

    def __init__(self, w: _Host, acted: int | BaseException = 1) -> None:
        ports = _Ports(w.open_journal, w.open_direct, w.prove_kek, w.probe, w, lambda: _RUN)
        super().__init__(ports, _TOY, w.env)
        self.w, self.acted = w, acted
        self.tasks: list[str] = []  # the act's task name

    async def run(self, ident: str = "alice", *, live_flag: bool = False) -> IntEnum:
        return await self._run(ident, live_flag=live_flag)

    async def _target(self, records: GateRecords, ident: str) -> Verdict | uuid.UUID:
        found = await self._step("toy_lookup", lambda: self.w.resolve_owner(ident))
        if found is None:
            return Verdict(ToyExit.NO_TARGET)
        records.target = found
        return found

    def _warning(self, ident: str) -> str:
        return f"Toy acts once on {ident}."

    async def _act(self, records: GateRecords, target: uuid.UUID) -> Verdict:
        refused = await self._probe_again()  # the gate's last probe, as every act runs it
        if refused is not None:
            return refused
        try:
            acted = await records.to_the_end(self._acting(), "act")
        except Exception as exc:
            return Verdict(ToyExit.DONE_FAILED, {"error": type(exc).__name__})
        return Verdict(ToyExit.DONE, {"acted": acted})

    async def _acting(self) -> int:
        self.w.calls.append("act")
        task = asyncio.current_task()
        self.tasks.append("" if task is None else task.get_name())
        return _answer(self.acted)

    def _outcome(self, verdict: Verdict, ident: str, why: str) -> list[str]:
        if verdict.status is ToyExit.DONE:  # the identifier is echoed only once acted on
            return [f"Toy done for {ident}."]
        return [f"Toy ended ({why})."]


class _Rogue(_Toy):
    """A flow whose hook `at` ("target" or "act") breaks the gate's contract: once it has run, it
    ends the run with `verdict`."""

    def __init__(self, w: _Host, at: str, verdict: Verdict) -> None:
        super().__init__(w)
        self.at, self.verdict = at, verdict

    async def _target(self, records: GateRecords, ident: str) -> Verdict | uuid.UUID:
        found = await super()._target(records, ident)
        return self.verdict if self.at == "target" else found

    async def _act(self, records: GateRecords, target: uuid.UUID) -> Verdict:
        done = await super()._act(records, target)
        return self.verdict if self.at == "act" else done


def _rows(w: _Host) -> list[tuple[str, AuditOutcome, str | None]]:
    return [(r["action"], r["outcome"], r["reason"]) for r in w.direct.records + w.journal.records]


def _shown(w: _Host) -> list[str]:
    """The terminal's lines but the phrase, whose nonce is random."""
    return [line for line in w.lines if not line.startswith("To confirm, type: ")]


#: The port trace of a run whose checks all hold, up to the act (DC-4479-06: traces, not exits).
_CHECKS = ["journal", ATTEMPT, "kek", "probe", "owner", "tty", "ask"]
_ACTED = [*_CHECKS, "probe", "act", DONE, "close"]
_ATTEMPTED = (ATTEMPT, SUCCESS, None)
_UNCLOSED = "Audit: the journal did not close cleanly."


async def test_a_second_spec_brings_its_own_actions_actor_task_and_log_names() -> None:
    w = _Host()
    toy = _Toy(w)
    with capture_logs() as logs:
        status = await toy.run()
    assert (type(status), status, w.calls) == (ToyExit, ToyExit.DONE, _ACTED)
    assert _rows(w) == [_ATTEMPTED, (DONE, SUCCESS, None)]
    actors = {(r["actor_label"], r["request_id"]) for r in w.journal.records}
    assert actors == {("system:toygate", _RUN)}
    closing = w.journal.records[-1]
    assert (closing["object_id"], closing["after_state"]) == (str(_OWNER_ID), {"acted": 1})
    assert toy.tasks == ["toygate.act"]
    assert [entry["event"] for entry in logs] == ["toygate.run_ended"]
    warning, phrase, *summary = w.lines
    assert re.fullmatch(r"To confirm, type: toy alice on demo [0-9A-F]{6}", phrase)
    assert [warning, *summary] == ["Toy acts once on alice.", "Toy done for alice.", _AUDITED]


@pytest.mark.parametrize(("setup", "acted", "status", "ran", "rows", "events"), [
    P({"owner_id": None}, 1, ToyExit.NO_TARGET, [*_CHECKS[:5], REFUSED, "close"],
      [_ATTEMPTED, (REFUSED, DENIED, "no_target")], {"run_ended"}, id="its-own-refusal"),
    P({}, OSError("injected"), ToyExit.DONE_FAILED, _ACTED,
      [_ATTEMPTED, (DONE, FAILURE, "done_failed")], {"run_ended"}, id="its-act-fails"),
    P({"kek": OSError("injected")}, 1, ToyExit.STEP_FAILED, [*_CHECKS[:3], REFUSED, "close"],
      [_ATTEMPTED, (REFUSED, FAILURE, "step_failed")], {"step_failed", "run_ended"},
      id="a-gate-port-breaks"),
    P({"env": Environment.LIVE}, 1, ToyExit.LIVE_FLAG_REQUIRED,
      ["journal", ATTEMPT, REFUSED, "close"], [_ATTEMPTED, (REFUSED, DENIED, "live_flag_required")],
      {"run_ended"}, id="live-without-the-flag"),
    P({"typed": TimeoutError()}, 1, ToyExit.CONFIRMATION_TIMEOUT, [*_CHECKS, REFUSED, "close"],
      [_ATTEMPTED, (REFUSED, DENIED, "confirmation_timeout")], {"run_ended"},
      id="its-phrase-times-out"),
    P({"typed": EOFError()}, 1, ToyExit.CONFIRMATION_MISMATCH, [*_CHECKS, REFUSED, "close"],
      [_ATTEMPTED, (REFUSED, DENIED, "confirmation_mismatch")], {"run_ended"},
      id="its-phrase-meets-eof"),
    P({"refuse": ATTEMPT}, 1, ToyExit.AUDIT_UNAVAILABLE, ["journal", ATTEMPT, "close"], [],
      {"attempt_unrecorded"}, id="its-attempt-record-is-refused"),
    P({"refuse": DONE}, 1, ToyExit.AUDIT_UNAVAILABLE, _ACTED, [_ATTEMPTED],
      {"outcome_unrecorded"}, id="its-closing-record-is-refused"),
    P({"pending": OSError("injected")}, 1, ToyExit.DONE, _ACTED,
      [_ATTEMPTED, (DONE, SUCCESS, None)], {"run_ended", "trail_close_failed"},
      id="its-journal-does-not-close"),
    P({"pending": 2}, 1, ToyExit.DONE, _ACTED, [_ATTEMPTED, (DONE, SUCCESS, None)], {"run_ended"},
      id="its-records-wait-in-the-journal"),
    P({"journal_error": OSError("injected")}, 1, ToyExit.HOST_FS_UNAVAILABLE,
      ["journal", "direct", ATTEMPT, REFUSED, "close"],
      [_ATTEMPTED, (REFUSED, DENIED, "host_fs_unavailable")],
      {"journal_unavailable", "refused_unjournaled"}, id="no-journal-straight-to-audit-log"),
    P({"journal_error": OSError("injected"), "direct_trail": {"refuse": ATTEMPT}}, 1,
      ToyExit.HOST_FS_UNAVAILABLE, ["journal", "direct", ATTEMPT, "close"], [],
      {"journal_unavailable", "direct_audit_failed", "refused_unjournaled"},
      id="no-journal-and-audit-log-refuses"),
    P({"journal_error": OSError("injected"), "direct_up": False}, 1, ToyExit.HOST_FS_UNAVAILABLE,
      ["journal", "direct"], [], {"journal_unavailable", "refused_unjournaled"},
      id="no-journal-and-no-audit-log"),
])  # fmt: skip
async def test_its_statuses_records_and_events_flow_through_the_gate(
    setup: dict[str, Any],
    acted: int | BaseException,
    status: ToyExit,
    ran: list[str],
    rows: list[tuple[str, AuditOutcome, str | None]],
    events: set[str],
) -> None:
    w = _Host(**setup)
    with capture_logs() as logs:
        exit_code = await _Toy(w, acted).run()
    assert (type(exit_code), exit_code, w.calls) == (ToyExit, status, ran)
    assert _rows(w) == rows
    assert {entry["event"] for entry in logs} == {f"toygate.{event}" for event in events}


@pytest.mark.parametrize(("hang", "status", "ran", "rows", "events", "shown"), [
    P("ask", ToyExit.OPERATOR_CANCELLED, [*_CHECKS[:6], REFUSED, "close"],
      [_ATTEMPTED, (REFUSED, DENIED, "operator_cancelled")], {"run_cancelled", "run_ended"},
      ["Toy acts once on alice.", "Toy ended (operator_cancelled).", _AUDITED],
      id="at-the-phrase"),
    P("journal", ToyExit.OPERATOR_CANCELLED, ["direct", ATTEMPT, REFUSED, "close"],
      [_ATTEMPTED, (REFUSED, DENIED, "operator_cancelled")], {"refused_unjournaled"},
      ["Toy ended (operator_cancelled).", _AUDITED], id="while-the-journal-opens"),
    P("emit", ToyExit.OPERATOR_CANCELLED, ["journal", ATTEMPT, REFUSED, "close"],
      [_ATTEMPTED, (REFUSED, DENIED, "operator_cancelled")], {"run_cancelled", "run_ended"},
      ["Toy ended (operator_cancelled).", _AUDITED], id="while-the-attempt-is-recorded"),
    P("close", ToyExit.DONE, _ACTED, [_ATTEMPTED, (DONE, SUCCESS, None)],
      {"run_ended", "trail_close_cancelled"},
      ["Toy acts once on alice.", "Toy done for alice.", _CANCELLED, _UNCLOSED],
      id="while-the-journal-closes"),
])  # fmt: skip
async def test_a_cancel_carries_the_second_flows_exit(
    hang: str,
    status: ToyExit,
    ran: list[str],
    rows: list[tuple[str, AuditOutcome, str | None]],
    events: set[str],
    shown: list[str],
) -> None:
    w = _Host(hang=hang)
    with capture_logs() as logs:
        running = asyncio.create_task(_Toy(w).run())
        await _parked(w)
        running.cancel()
        w.release.set()
        await asyncio.wait({running}, timeout=5)
    with pytest.raises(RunCancelled) as cut:
        running.result()  # InvalidStateError if the run is still going
    assert (type(cut.value.exit), cut.value.exit) == (ToyExit, status)
    assert (w.calls, _rows(w)) == (ran, rows)
    assert {entry["event"] for entry in logs} == {f"toygate.{event}" for event in events}
    assert _shown(w) == shown


@pytest.mark.parametrize(("setup", "live_flag", "status", "ran"), [
    P({}, False, ToyExit.DONE, _ACTED[:-1], id="all-hold-then-the-probe-again-then-the-act"),
    P({}, True, ToyExit.LIVE_FLAG_MISMATCH, [*_CHECKS[:2], REFUSED], id="first-the-live-flag"),
    P({"kek": KekCheckResult(None, False, "kek_mismatch")}, False, ToyExit.KEK_UNPROVEN,
      [*_CHECKS[:3], REFUSED], id="then-the-kek-proof"),
    P({"api_up": True}, False, ToyExit.API_RUNNING, [*_CHECKS[:4], REFUSED],
      id="then-the-api-probe"),
    P({"owner_id": None}, False, ToyExit.NO_TARGET, [*_CHECKS[:5], REFUSED], id="then-the-target"),
    P({"tty": False}, False, ToyExit.NO_TTY, [*_CHECKS[:6], REFUSED], id="then-the-tty"),
    P({"typed": "toy alice on demo"}, False, ToyExit.CONFIRMATION_MISMATCH, [*_CHECKS, REFUSED],
      id="then-the-phrase"),
    P({"api_up": [False, True]}, False, ToyExit.API_RUNNING, [*_CHECKS, "probe", REFUSED],
      id="last-the-probe-again"),
])  # fmt: skip
async def test_the_gate_checks_in_one_order_before_the_flows_act(
    setup: dict[str, Any], live_flag: bool, status: ToyExit, ran: list[str]
) -> None:
    w = _Host(**setup)
    assert await _Toy(w).run(live_flag=live_flag) is status
    assert w.calls == [*ran, "close"]


async def test_a_last_probe_that_breaks_is_the_gates_api_probe_step() -> None:
    w = _Host(api_up=cast(list[bool], [False, OSError("injected")]))  # the second probe raises
    with capture_logs() as logs:
        assert await _Toy(w).run() is ToyExit.STEP_FAILED
    assert w.calls == [*_CHECKS, "probe", REFUSED, "close"]  # no act
    assert _rows(w) == [_ATTEMPTED, (REFUSED, FAILURE, "step_failed")]
    assert w.journal.records[-1]["after_state"] == {"step": "api_probe", "error": "OSError"}
    failed = [(e["event"], e["step"], e["error"]) for e in logs if "step" in e]
    assert failed == [("toygate.step_failed", "api_probe", "OSError")]


@pytest.mark.parametrize(("at", "verdict", "ran", "error"), [
    P("act", Verdict(BreakGlassExit.RESET), [*_CHECKS, "probe", "act"], "TypeError",
      id="its-act-ends-with-another-flows-status"),
    P("target", Verdict(BreakGlassExit.NOT_OWNER), _CHECKS[:5], "TypeError",
      id="its-target-ends-with-another-flows-status"),
    P("target", Verdict(ToyExit.DONE), _CHECKS[:5], "RuntimeError",
      id="its-target-ends-the-run-as-done"),
    P("target", Verdict(ToyExit.DONE_FAILED), _CHECKS[:5], "RuntimeError",
      id="its-target-ends-the-run-as-failed"),
])  # fmt: skip
async def test_a_hook_that_breaks_the_gates_contract_is_a_recorded_step_failure(
    at: str, verdict: Verdict, ran: list[str], error: str
) -> None:
    w = _Host()
    with capture_logs() as logs:
        status = await _Rogue(w, at, verdict).run()
    assert (type(status), status) == (ToyExit, ToyExit.STEP_FAILED)
    assert w.calls == [*ran, REFUSED, "close"]  # after a check's verdict: no TTY, phrase or act
    assert _rows(w) == [_ATTEMPTED, (REFUSED, FAILURE, "step_failed")]
    assert w.journal.records[-1]["after_state"] == {"step": "flow", "error": error}
    assert [entry["event"] for entry in logs] == ["toygate.step_failed", "toygate.run_ended"]
    assert _shown(w)[-2:] == ["Toy ended (step_failed: flow).", _AUDITED]


def test_a_spec_records_no_status_of_another_flows() -> None:
    assert _TOY.record_of(Verdict(ToyExit.DONE)) == (DONE, SUCCESS, None)
    with pytest.raises(TypeError, match="BreakGlassExit"):
        _TOY.record_of(Verdict(BreakGlassExit.RESET))


def test_every_flow_keeps_the_gates_status_numbers() -> None:
    assert dict(GATE_STATUSES) == {
        "STEP_FAILED": 1, "HOST_FS_UNAVAILABLE": 4, "API_RUNNING": 5, "AUDIT_UNAVAILABLE": 6,
        "LIVE_FLAG_REQUIRED": 7, "LIVE_FLAG_MISMATCH": 8, "KEK_UNPROVEN": 9, "NO_TTY": 11,
        "CONFIRMATION_MISMATCH": 12, "CONFIRMATION_TIMEOUT": 13, "OPERATOR_CANCELLED": 16,
    }  # fmt: skip
    for exits in (BreakGlassExit, ToyExit):
        assert {name: int(exits[name]) for name in GATE_STATUSES} == dict(GATE_STATUSES)


_OWN = {"DONE": 0, "FAILED": 3}
_NUMBERS = "Exits must number"
_NOT_OWN = "two of its own"


@pytest.mark.parametrize(("members", "fields", "error"), [
    P({**GATE_STATUSES, **_OWN, "NO_TTY": 10}, {}, _NUMBERS, id="a-gate-status-renumbered"),
    P({k: v for k, v in GATE_STATUSES.items() if k != "NO_TTY"} | _OWN, {}, _NUMBERS,
      id="a-gate-status-missing"),
    P({**GATE_STATUSES, **_OWN, "DONE": 2}, {}, _NUMBERS, id="done-is-not-zero"),
    P({**GATE_STATUSES, **_OWN}, {"failed_status": "FAILS"}, "define FAILS",
      id="no-such-failed-status"),
    P({**GATE_STATUSES, **_OWN}, {"failed_status": "DONE"}, _NOT_OWN, id="failed-is-done"),
    P({**GATE_STATUSES, **_OWN}, {"failed_status": "STEP_FAILED"}, _NOT_OWN,
      id="failed-is-a-gate-status"),
    P({**GATE_STATUSES, "STEP_FAILED": 0, "FAILED": 3}, {"done_status": "STEP_FAILED"}, _NOT_OWN,
      id="done-is-a-gate-status"),
    P({**GATE_STATUSES, **_OWN, "NO_TARGET": 5}, {}, "one number", id="an-alias"),
    P({**GATE_STATUSES, "DONE": 0, "FAILED": 1}, {}, "one number",
      id="its-failed-status-is-a-gate-number"),
    P({**GATE_STATUSES, **_OWN}, {"actor": "alice"}, "system: label", id="a-user-actor"),
])  # fmt: skip
def test_a_spec_that_breaks_a_gate_rule_is_refused(
    members: dict[str, int], fields: dict[str, str], error: str
) -> None:
    exits = IntEnum("Exits", members)  # type: ignore[misc]  # computed, as a mistyped one is
    spec: dict[str, Any] = {"exits": exits, "done_status": "DONE", "failed_status": "FAILED"}
    with pytest.raises(ValueError, match=error):
        dataclasses.replace(_TOY, **(spec | fields))


@pytest.mark.parametrize("field", ["attempt", "refused", "done"])
def test_a_spec_naming_an_unregistered_action_is_refused(field: str) -> None:
    unregistered: dict[str, Any] = {field: "toy.unregistered"}
    with pytest.raises(UnknownAuditAction):
        dataclasses.replace(_TOY, **unregistered)


def test_break_glass_runs_on_its_pinned_spec() -> None:
    pinned = GateSpec(
        "breakglass", "system:breakglass", "auth.break_glass_attempt", "auth.break_glass_refused",
        "auth.break_glass_reset", "reset", BreakGlassExit, "RESET", "RESET_FAILED",
    )  # fmt: skip
    assert breakglass._BREAK_GLASS == pinned
    assert _Host().flow._spec is breakglass._BREAK_GLASS


#: The gate's own steps: final, so mypy rejects a flow that overrides one (reorders or drops it).
_GATE = {
    "_run", "_intent", "_journaled", "_decide", "_own", "_step", "_check", "_confirm",
    "_probe_again", "_refuse_unjournaled", "_summarise",
}  # fmt: skip


def test_the_gates_steps_are_final_and_break_glass_brings_only_its_hooks() -> None:
    final = {name for name, f in vars(HostGatedFlow).items() if getattr(f, "__final__", False)}
    assert final == _GATE
    own = {name for name in vars(BreakGlassFlow) if not name.startswith("__")} - {"_abc_impl"}
    assert own == {"run", "_target", "_warning", "_act", "_reset", "_outcome"}


class _AuditLog:
    """An `audit_log` that keeps what it is given (here, nothing may reach it)."""

    def __init__(self) -> None:
        self.rows: list[object] = []

    async def insert(self, row: object) -> None:
        self.rows.append(row)


_BG_ATTEMPT, _BG_RESET = "auth.break_glass_attempt", "auth.break_glass_reset"


def _untouched(directory: Path) -> bool:
    return not any(directory.iterdir())


async def test_a_trail_takes_only_the_actions_it_admits() -> None:
    breakglass_wiring._admit(_BG_RESET, frozenset({_BG_RESET}))  # its own: taken
    with pytest.raises(UnknownAuditAction):
        breakglass_wiring._admit(_BG_ATTEMPT, frozenset({_BG_RESET}))
    audit_log = _AuditLog()
    trail = breakglass_wiring._DirectTrail(cast(AuditRepository, audit_log), frozenset({_BG_RESET}))
    with pytest.raises(UnknownAuditAction):
        await trail.emit(_BG_ATTEMPT)
    assert audit_log.rows == []  # refused before anything was written


@pytest.mark.parametrize("admitted", [
    P(frozenset({"auth.login"}), id="another-action"),
    P(frozenset({_BG_ATTEMPT, "auth.login"}), id="its-own-and-another"),
])  # fmt: skip
async def test_a_trail_cannot_admit_an_action_its_emit_does_not_declare(
    tmp_path: Path, admitted: frozenset[str]
) -> None:
    audit_log = cast(AuditRepository, _AuditLog())
    writer, lock = cast(AuditWriter, None), cast(FileIO, None)  # never used: refused first
    with pytest.raises(ValueError, match=r"_DirectTrail\.emit declares no \['auth\.login'\]"):
        breakglass_wiring._DirectTrail(audit_log, admitted)
    with pytest.raises(ValueError, match=r"_JournalTrail\.emit declares no \['auth\.login'\]"):
        breakglass_wiring._JournalTrail(writer, lock, tmp_path / "journal.wal", admitted)
    with pytest.raises(ValueError, match=r"_JournalTrail\.emit declares no"):
        await breakglass_wiring._open_journal(str(tmp_path / "audit.wal"), audit_log, admitted)
    assert _untouched(tmp_path)  # refused before the journal or its run lock was touched
