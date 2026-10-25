"""The bootstrap-Owner CLI flow (#4479 C2, SR-023; threat model U46, U49, U50): the flow over
in-memory ports and the real `BootstrapOwnerService` (C1) over a fake store, on break-glass's
host gate. Every refusal is pinned by its exact port trace (DC-4479-06), and the token by where it
may appear: once, on the terminal, after its record landed. The composed ports are in
`tests/unit/test_bootstrap_owner_cli.py`; Postgres in `tests/integration/auth/`."""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import json
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.admin import bootstrap_owner as flow
from candleviewer.admin import breakglass_wiring
from candleviewer.admin.bootstrap_owner import BootstrapOwnerExit as X
from candleviewer.admin.bootstrap_owner import BootstrapOwnerFlow, BootstrapOwnerPorts
from candleviewer.admin.breakglass import (
    GATE_STATUSES,
    BreakGlassExit,
    BreakGlassFlow,
    GateSpec,
    RunCancelled,
    _label,
)
from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.audit.journal import (
    BOOTSTRAP_ACTOR,
    BOOTSTRAP_OWNER_ACTIONS,
    BREAK_GLASS_ACTIONS,
)
from candleviewer.audit.models import AuditOutcome, ExchangeEnv, Severity
from candleviewer.audit.redact import redact
from candleviewer.auth import bootstrap_owner as service
from candleviewer.auth.bootstrap_owner import BootstrapOwnerService
from candleviewer.auth.invite_service import hash_token
from candleviewer.secrets import KekCheckResult, prove_kek_possession
from candleviewer.secrets._kek import LoadedKek
from candleviewer.secrets.store import InMemoryCredentialStore
from candleviewer.settings import Environment, Settings
from tests.unit.admin import test_breakglass_flow as bg
from tests.unit.admin.test_breakglass_flow import _CANCELLED, _PRE_AUDIT, _UNRECORDED, _Trail
from tests.unit.audit.audit_fakes import FakeAuditRepository

#: The action names registered by #4479 C1, pinned so that a rename fails here.
ATTEMPT, REFUSED, INVITED = (
    "auth.bootstrap_owner_attempt",
    "auth.bootstrap_owner_refused",
    "auth.bootstrap_owner_invited",
)
_EMAIL, _LABEL = "owner@example.invalid", "own***(len=21)"
_USER, _INVITE, _RUN = uuid.UUID(int=7), uuid.UUID(int=8), uuid.UUID(int=9)
_NOW = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
_DRAWN = "test-only-bootstrap-token-0123456789abcdef"  # each mint draws it; not a credential
_ROW = (_USER, _INVITE, True, 0)  # the store's mint row: the user created, nothing superseded
_PROVEN = KekCheckResult(3, True, None)
LIVE, DEMO, TESTNET = Environment.LIVE, Environment.DEMO, Environment.TESTNET
DENIED, FAILURE, SUCCESS = AuditOutcome.DENIED, AuditOutcome.FAILURE, AuditOutcome.SUCCESS
P = pytest.param


@pytest.fixture(autouse=True)
def _known_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """C1's service draws `secrets.token_urlsafe(32)`: here it draws `_DRAWN`, so a test can
    look for the token wherever it must not be."""
    monkeypatch.setattr(service, "secrets", SimpleNamespace(token_urlsafe=lambda _n: _DRAWN))


@dataclasses.dataclass(repr=False)  # its knobs hold the test code; frames must not show it
class _Host:
    """Every port in memory, the bootstrap store included; the knobs say how each answers,
    `calls` the order of use. The journal and `audit_log` are break-glass's `_Trail`."""

    env: Environment = DEMO
    email: str = _EMAIL
    journal_error: BaseException | None = None
    direct_up: bool | BaseException = True
    pending: int | BaseException = 0
    refuse: str | None = None
    kek: KekCheckResult | BaseException = _PROVEN
    api_up: bool | BaseException | list[bool | BaseException] = False  # a list: one per probe
    state: uuid.UUID | str | BaseException | None = None  # the read; None: the mint creates
    minted: tuple[uuid.UUID, uuid.UUID, bool, int] | str | BaseException = _ROW
    tty: bool | BaseException = True
    typed: str | BaseException | None = None  # None: the phrase the terminal showed
    hang: str | None = None  # the port (or journal "emit"/"close") parked until `release`
    calls: list[str] = dataclasses.field(default_factory=list)
    lines: list[str] = dataclasses.field(default_factory=list)
    hashes: list[str] = dataclasses.field(default_factory=list)  # what the store was given
    landed_at_print: list[str] | None = None  # the records already written when it printed
    entered: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    release: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)

    def __post_init__(self) -> None:
        if isinstance(self.api_up, list):  # this host's copy: `probe` consumes it, not the case
            self.api_up = list(self.api_up)
        park: dict[str, Any] = {"release": self.release, "entered": self.entered}
        self.journal = _Trail(self.calls, self.pending, self.refuse, self.hang, **park)
        self.direct = _Trail(self.calls, **park)
        mint = BootstrapOwnerService(self, environment=self.env, clock=lambda: _NOW)
        ports = BootstrapOwnerPorts(
            self.open_journal, self.open_direct, self.prove_kek, self.probe, mint, self,
            new_run_id=lambda: _RUN,
        )  # fmt: skip
        self.flow = BootstrapOwnerFlow(ports)

    async def run(self, *, live_flag: bool = False) -> X:
        return await self.flow.run(self.email, live_flag=live_flag)

    async def _port[T](self, port: str, answer: T | BaseException) -> T:
        if port == self.hang:
            self.entered.set()
            await self.release.wait()  # hung unless the test releases it
        self.calls.append(port)
        return bg._answer(answer)

    async def open_journal(self) -> _Trail:
        return await self._port("journal", self.journal_error or self.journal)

    async def open_direct(self) -> _Trail | None:
        return self.direct if await self._port("direct", self.direct_up) else None

    async def prove_kek(self) -> KekCheckResult:
        return await self._port("kek", self.kek)

    async def probe(self) -> bool:
        up = self.api_up.pop(0) if isinstance(self.api_up, list) else self.api_up
        return await self._port("probe", up)

    async def bootstrap_state(self, email: str, username: str) -> Any:
        return await self._port("state", self.state)

    async def mint_owner_invite(self, **fields: Any) -> Any:
        self.hashes.append(fields["token_hash"])
        return await self._port("mint", self.minted)

    def is_interactive(self) -> bool:
        self.calls.append("tty")
        return bg._answer(self.tty)

    def write(self, line: str) -> None:
        if _DRAWN in line:
            self.landed_at_print = [r["action"] for r in self.journal.records]
        self.lines.append(line)
        sys.stdout.write(line + "\n")  # what the operator sees, for capsys

    async def ask(self, prompt: str) -> str:
        shown = self.lines[-1].removeprefix("To confirm, type: ")
        return await self._port("ask", shown if self.typed is None else self.typed)

    async def ask_secret(self, prompt: str) -> str:
        raise AssertionError("the bootstrap flow reads no secret")


async def _exit(w: _Host, *, live_flag: bool = False) -> X:
    """The run's exit status, also when a cancel carries it (`RunCancelled`)."""
    try:
        return await w.run(live_flag=live_flag)
    except RunCancelled as cut:
        return X(cut.exit)


async def _parked(w: _Host) -> None:
    async with asyncio.timeout(5):  # a flow that never gets there fails, not hangs
        await w.entered.wait()


async def _cancel_exit(running: asyncio.Task[X]) -> X:
    """The exit the re-raised cancel carries once the run ended (bounded too)."""
    await asyncio.wait({running}, timeout=5)
    with pytest.raises(RunCancelled) as cut:
        running.result()  # InvalidStateError if the run is still going
    return X(cut.value.exit)


def _rows(w: _Host) -> list[tuple[str, AuditOutcome, str | None]]:
    return [(r["action"], r["outcome"], r["reason"]) for r in w.direct.records + w.journal.records]


def _assert_bootstrap_record(record: dict[str, Any], env: Environment) -> None:
    """Critical, no user, a label not the email, this run, nothing the writer redacts."""
    assert (record["actor_label"], record["actor_user_id"]) == ("system:bootstrap", None)
    assert (record["severity"], record["request_id"]) == (Severity.CRITICAL, _RUN)
    assert (record["object_kind"], record["object_label"]) == ("user", _LABEL)
    assert record["env"] == ExchangeEnv(env.value)
    assert redact(record["after_state"]) == record["after_state"]


_CHECKS = ["journal", ATTEMPT, "kek", "probe", "state", "tty", "ask"]
_MINTS = [*_CHECKS, "probe", "mint"]
#: An active Owner, as the store sees it at the read and again inside the mint, under its lock.
_OWNED: dict[str, Any] = {"state": "owner_exists", "minted": "owner_exists"}


@pytest.mark.parametrize(("env", "live_flag"), [(DEMO, False), (LIVE, True)])
async def test_attempt_record_precedes_every_check(env: Environment, live_flag: bool) -> None:
    # The gate's order; cv-api is probed again last, right before the mint (R2c). No secret is
    # asked for, in live either.
    w = _Host(env)
    assert await w.run(live_flag=live_flag) is X.INVITED
    assert w.calls == [*_MINTS, INVITED, "close"]


@pytest.mark.parametrize(("setup", "live_flag", "status", "ran"), [
    P(_OWNED, False, X.OWNER_EXISTS, _CHECKS[:5], id="17-at-the-target"),
    P({"minted": "owner_exists"}, False, X.OWNER_EXISTS, _MINTS, id="17-from-the-mint"),
    P({"state": "not_candidate"}, False, X.NOT_CANDIDATE, _CHECKS[:5], id="18-at-the-target"),
    P({"minted": "not_candidate"}, False, X.NOT_CANDIDATE, _MINTS, id="18-from-the-mint"),
    P({"kek": KekCheckResult(None, False, "kek_mismatch")}, False, X.KEK_UNPROVEN, _CHECKS[:3],
      id="9-kek"),
    P({"api_up": True}, False, X.API_RUNNING, _CHECKS[:4], id="5-at-the-first-probe"),
    P({"api_up": [False, True]}, False, X.API_RUNNING, _MINTS[:-1], id="5-at-the-last-probe"),
    P({"tty": False}, False, X.NO_TTY, _CHECKS[:6], id="11-no-tty"),
    P({"typed": "bootstrap owner@example.invalid on demo"}, False, X.CONFIRMATION_MISMATCH,
      _CHECKS, id="12-mismatch"),
    P({"typed": TimeoutError()}, False, X.CONFIRMATION_TIMEOUT, _CHECKS, id="13-no-answer"),
    P({"env": LIVE}, False, X.LIVE_FLAG_REQUIRED, _CHECKS[:2], id="7-live-without-the-flag"),
    P({}, True, X.LIVE_FLAG_MISMATCH, _CHECKS[:2], id="8-the-flag-outside-live"),
    P({"typed": asyncio.CancelledError()}, False, X.OPERATOR_CANCELLED, _CHECKS,
      id="16-ctrl-c-at-the-phrase"),
])  # fmt: skip
async def test_each_refusal_writes_a_critical_denied_record(
    setup: dict[str, Any], live_flag: bool, status: X, ran: list[str]
) -> None:
    # DC-4479-06: the exact trace, so a check whose refusal a later step repeats (the first
    # probe, owner_exists at the target) cannot go missing unseen: nothing runs after it.
    w = _Host(**setup)
    assert await _exit(w, live_flag=live_flag) is status
    assert w.calls == [*ran, REFUSED, "close"]
    assert _rows(w) == [(ATTEMPT, SUCCESS, None), (REFUSED, DENIED, status.reason)]
    for record in w.journal.records:
        _assert_bootstrap_record(record, w.env)
    assert _DRAWN not in "\n".join(w.lines)


async def test_a_last_probe_that_breaks_is_a_step_failure_before_any_mint() -> None:
    # SEC-4479A-05 (b): the gate cannot see inside `_act`, so this flow's traces pin its last
    # probe. cv-api up there is the refusal `5-at-the-last-probe` above; a probe that breaks
    # there is the gate's `api_probe` step failure. Neither reaches the mint.
    w = _Host(api_up=[False, OSError("injected")])
    assert await w.run() is X.STEP_FAILED
    assert (w.calls, w.hashes) == ([*_MINTS[:-1], REFUSED, "close"], [])
    assert _rows(w)[-1] == (REFUSED, FAILURE, "step_failed")
    assert w.journal.records[-1]["after_state"] == {"step": "api_probe", "error": "OSError"}


@pytest.mark.parametrize("owner", [
    "", "not an email", "ab@example.invalid", "\x1b[2Jowner@example.invalid",
    f"{'x' * 33}@example.invalid",
])  # fmt: skip
async def test_any_owner_string_is_recorded_before_it_is_validated(owner: str) -> None:
    # DC-4479-10: whatever is typed reaches the attempt record, as a label, then the target
    # refuses it before any store call; the terminal never echoes it.
    w = _Host(email=owner)
    assert await w.run() is X.NOT_CANDIDATE
    assert w.calls == ["journal", ATTEMPT, "kek", "probe", REFUSED, "close"]
    assert [r["object_label"] for r in w.journal.records] == [_label(owner)] * 2
    assert [line for line in w.lines if owner and owner in line] == []


@pytest.mark.parametrize(("state", "created"), [(None, True), (_USER, False)])
async def test_records_carry_the_bootstrap_actor_and_run_id(
    state: uuid.UUID | None, created: bool
) -> None:
    w = _Host(LIVE, state=state, minted=(_USER, _INVITE, created, 1))
    assert await w.run(live_flag=True) is X.INVITED
    attempt, invited = w.journal.records
    for record in (attempt, invited):
        _assert_bootstrap_record(record, LIVE)
    assert (attempt["object_id"], invited["object_id"]) == (None, str(_USER))
    assert attempt["after_state"] == {"environment": "live", "live_flag": True}
    assert (invited["action"], invited["outcome"], invited["reason"]) == (INVITED, SUCCESS, None)
    minted = {"invite_id": str(_INVITE), "expires_at": (_NOW + timedelta(hours=4)).isoformat()}
    assert invited["after_state"] == {**minted, "created_user": created, "superseded": 1}


@pytest.mark.parametrize(("setup", "status"), [
    P({"typed": "bootstrap owner@example.invalid on demo"}, X.CONFIRMATION_MISMATCH,
      id="12-mismatch"),
    P({"api_up": [False, True]}, X.API_RUNNING, id="5-at-the-last-probe"),
    P({"minted": ConnectionError("injected")}, X.MINT_FAILED, id="3-the-mint-fails"),
])  # fmt: skip
@pytest.mark.parametrize("state", [_USER, None], ids=["an-invited-user", "no-user-yet"])
async def test_a_run_past_the_target_check_names_the_user_it_found(
    setup: dict[str, Any], status: X, state: uuid.UUID | None
) -> None:
    # Design section 4, `object_id` set to the target once known: a run that ends after the
    # target check names the invited user it found, and nobody when the mint would create one.
    w = _Host(state=state, **setup)
    assert await w.run() is status
    named = None if state is None else str(state)
    assert [record["object_id"] for record in w.journal.records] == [None, named]


async def test_token_is_printed_once_and_never_recorded_or_logged() -> None:
    w = _Host()
    with capture_logs() as logs:
        assert await w.run() is X.INVITED
    shown = "\n".join(w.lines)
    assert shown.count(_DRAWN) == 1 and f"Invite token (shown once): {_DRAWN}" in w.lines
    assert w.landed_at_print == [ATTEMPT, INVITED]  # printed once its record had landed
    assert "valid 4 h" in w.lines[0] and w.lines[-1] == bg._AUDITED
    assert w.hashes == [hash_token(_DRAWN)]  # the store had only its sha256
    elsewhere = json.dumps(logs, default=str) + json.dumps(w.journal.records, default=str)
    assert [s for s in (_DRAWN, *w.hashes) if s in elsewhere] == [] and w.hashes[0] not in shown
    assert w.flow._token is None


async def test_token_is_withheld_when_the_invited_record_fails() -> None:
    # Design section 4: the invite exists, its record is not durable, so the token is never
    # shown; the next run revokes the invite (the store's supersede, C1).
    w = _Host(refuse=INVITED)
    assert await w.run() is X.AUDIT_UNAVAILABLE
    assert (w.calls, len(w.hashes)) == ([*_MINTS, INVITED, "close"], 1)
    assert _DRAWN not in "\n".join(w.lines) and "its token is withheld" in w.lines[-2]
    assert w.lines[-1] == _UNRECORDED and w.flow._token is None


class _Aborted(BaseException):
    """Not an `Exception`: nothing in the gate catches it, so the run ends by it."""


async def test_a_run_that_ends_by_an_exception_after_the_mint_drops_the_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Design section 4: `run`'s `finally` clears the token too, and a run that ends by an
    # exception between the mint and the summary meets no other clearing (CR-4494-07).
    w = _Host()
    emit = w.journal.emit

    async def aborting(action: str, **fields: Any) -> None:
        if action == INVITED:
            raise _Aborted
        await emit(action, **fields)

    monkeypatch.setattr(w.journal, "emit", aborting)
    with pytest.raises(_Aborted):
        await w.run()
    assert (w.hashes, w.flow._token) == ([hash_token(_DRAWN)], None)
    assert _DRAWN not in "\n".join(w.lines)


async def test_mint_failure_records_mint_failed_and_exits_3() -> None:
    w = _Host(minted=ConnectionError("injected: connection lost mid-transaction"))
    assert await w.run() is X.MINT_FAILED
    assert w.calls == [*_MINTS, INVITED, "close"]
    assert _rows(w) == [(ATTEMPT, SUCCESS, None), (INVITED, FAILURE, "mint_failed")]
    state = {"error": "ConnectionError", "outcome": "rolled_back_or_unknown"}
    assert w.journal.records[-1]["after_state"] == state  # a link lost at COMMIT may have minted
    assert "no invite is confirmed" in w.lines[-2] and _DRAWN not in "\n".join(w.lines)


@pytest.mark.parametrize(("minted", "closing", "status"), [
    P(_ROW, (INVITED, SUCCESS, None), X.INVITED, id="the-mint-commits"),
    P(ConnectionError("injected"), (INVITED, FAILURE, "mint_failed"), X.MINT_FAILED,
      id="the-mint-raises"),
    P("owner_exists", (REFUSED, DENIED, "owner_exists"), X.OWNER_EXISTS, id="the-mint-refuses"),
])  # fmt: skip
async def test_cancel_during_the_mint_finishes_and_prints_the_token(
    minted: Any, closing: tuple[str, AuditOutcome, str | None], status: X
) -> None:
    # A cancel cannot cut the mint at COMMIT and leave an invite unrecorded: the mint runs to
    # its end, its outcome is recorded and summarised (a minted token printed, once), then the
    # cancel propagates with that outcome's exit.
    w = _Host(hang="mint", minted=minted)
    running = asyncio.create_task(w.run())
    await _parked(w)
    running.cancel()
    w.release.set()
    assert await _cancel_exit(running) is status
    assert _rows(w) == [(ATTEMPT, SUCCESS, None), closing]
    shown = "\n".join(w.lines)
    assert (shown.count(_DRAWN), _CANCELLED in w.lines) == (int(status is X.INVITED), True)


async def test_a_mint_cut_short_at_shutdown_is_an_unknown_outcome() -> None:
    # A second Ctrl-C cancels every task, the mint's too: what it did is unknown, so it is a
    # failed mint that may have committed, never "nothing was minted".
    w = _Host(hang="mint")
    running = asyncio.create_task(w.run())
    await _parked(w)
    running.cancel()
    [mint] = [task for task in asyncio.all_tasks() if task.get_name() == "bootstrap_owner.mint"]
    mint.cancel()
    assert await _cancel_exit(running) is X.MINT_FAILED
    state = {"error": "Interrupted", "outcome": "rolled_back_or_unknown"}
    assert w.journal.records[-1]["after_state"] == state


def test_exit_codes_and_reasons_are_pinned() -> None:
    # The runbook's exit table and the audit `reason` codes; 0 only for a recorded invite.
    assert {x.reason: int(x) for x in X} == {
        "invited": 0, "step_failed": 1, "mint_failed": 3, "host_fs_unavailable": 4,
        "api_running": 5, "audit_unavailable": 6, "live_flag_required": 7,
        "live_flag_mismatch": 8, "kek_unproven": 9, "no_tty": 11, "confirmation_mismatch": 12,
        "confirmation_timeout": 13, "operator_cancelled": 16, "owner_exists": 17,
        "not_candidate": 18,
    }  # fmt: skip


def test_gate_statuses_share_their_numbers_with_break_glass() -> None:
    # A number means one thing in both CLIs: the gate's statuses keep theirs, break-glass's own
    # refusals (10, 14, 15) are unused here, and only the done and failed statuses differ.
    for name, number in GATE_STATUSES.items():
        assert int(X[name]) == int(BreakGlassExit[name]) == number
    theirs = {int(x): x.name for x in BreakGlassExit}
    assert {int(x) for x in X if theirs.get(int(x), x.name) != x.name} == {0, 3}
    assert not {10, 14, 15} & {int(x) for x in X}


def test_actions_and_actor_match_the_registry_and_the_journal() -> None:
    # A drift would end every run in AUDIT_UNAVAILABLE (an unknown action) or make cv-api's boot
    # fold-in reject the journal as foreign. The flow brings only its hooks to the gate.
    names = {flow.ATTEMPT, flow.REFUSED, flow.INVITED}
    assert names == {ATTEMPT, REFUSED, INVITED} == BOOTSTRAP_OWNER_ACTIONS <= AUDIT_ACTIONS
    pinned = GateSpec(
        "bootstrap_owner", "system:bootstrap", ATTEMPT, REFUSED, INVITED, "bootstrap", X,
        "INVITED", "MINT_FAILED",
    )  # fmt: skip
    assert (flow._BOOTSTRAP, BOOTSTRAP_ACTOR) == (pinned, "system:bootstrap")
    own = {name for name in vars(BootstrapOwnerFlow) if not name.startswith("__")} - {"_abc_impl"}
    assert own == {"run", "_target", "_warning", "_act", "_outcome"}


@pytest.mark.parametrize(("setup", "tail", "mints", "audit"), [
    P({"refuse": ATTEMPT}, ["journal", ATTEMPT, "close"], 0, [_PRE_AUDIT], id="attempt"),
    P({"refuse": INVITED}, ["mint", INVITED, "close"], 1, [_UNRECORDED], id="invited"),
    P({"refuse": REFUSED, "state": "owner_exists"}, ["state", REFUSED, "close"], 0,
      [_UNRECORDED], id="refusal"),
])  # fmt: skip
async def test_no_option_skips_audit(
    setup: dict[str, Any], tail: list[str], mints: int, audit: list[str]
) -> None:
    # C-4.14: the inputs are the email and --live, no port is a switch, nothing runs without
    # its write-ahead record, and a record the journal cannot keep ends in AUDIT_UNAVAILABLE,
    # with a summary that claims no more than was written (C-2.9).
    assert list(inspect.signature(BootstrapOwnerFlow.run).parameters) == [
        "self", "owner", "live_flag",
    ]  # fmt: skip
    assert [f.name for f in dataclasses.fields(BootstrapOwnerPorts)] == [
        "open_journal", "open_direct", "prove_kek", "api_running", "bootstrap", "terminal",
        "new_run_id",
    ]  # fmt: skip
    w = _Host(**setup)
    assert await w.run() is X.AUDIT_UNAVAILABLE
    assert (w.calls[-len(tail) :], len(w.hashes)) == (tail, mints)
    assert [line for line in w.lines if line.startswith("Audit:")] == audit


@pytest.mark.parametrize(("env", "live_flag", "status"), [
    (LIVE, True, X.INVITED),
    (LIVE, False, X.LIVE_FLAG_REQUIRED),
    (DEMO, True, X.LIVE_FLAG_MISMATCH),  # --live cannot make a demo deployment live
    (DEMO, False, X.INVITED),
    (TESTNET, False, X.INVITED),
])  # fmt: skip
async def test_live_derived_from_environment_not_argv(
    env: Environment, live_flag: bool, status: X
) -> None:
    # `live` is the configured environment (arch P9), the bootstrap service's alone: the flow
    # takes none of its own, so the two cannot disagree.
    assert "environment" not in inspect.signature(BootstrapOwnerFlow.run).parameters
    assert list(inspect.signature(BootstrapOwnerFlow).parameters) == ["ports"]
    w = _Host(env)
    assert await w.run(live_flag=live_flag) is status
    assert (w.hashes != []) is (status is X.INVITED)


async def test_break_glass_and_bootstrap_runs_exclude_each_other(tmp_path: Path) -> None:
    # The two CLIs take one run lock, the host journal's (a real `instance.lock` in tmp_path):
    # while one waits at its phrase, the other is refused like a running cv-api, its records
    # go straight to audit_log, and it changes nothing.
    wal, audit_log = str(tmp_path / "audit" / "audit.wal"), FakeAuditRepository()

    def locked(ports: Any, admitted: frozenset[str]) -> Any:
        async def journal() -> Any:
            return await breakglass_wiring._open_journal(wal, audit_log, admitted)

        return dataclasses.replace(ports, open_journal=journal)

    first, glass = _Host(hang="ask"), bg._Host()
    mint = BootstrapOwnerFlow(locked(first.flow._ports, BOOTSTRAP_OWNER_ACTIONS))
    reset = BreakGlassFlow(locked(glass.flow._ports, BREAK_GLASS_ACTIONS))
    running = asyncio.create_task(mint.run(_EMAIL, live_flag=False))
    await _parked(first)
    assert await reset.run("alice", live_flag=False) is BreakGlassExit.API_RUNNING
    assert ([r["reason"] for r in glass.direct.records], glass.seen) == ([None, "api_running"], [])
    first.release.set()
    assert await running is X.INVITED
    second, later = _Host(), bg._Host(hang="ask")
    mint = BootstrapOwnerFlow(locked(second.flow._ports, BOOTSTRAP_OWNER_ACTIONS))
    reset = BreakGlassFlow(locked(later.flow._ports, BREAK_GLASS_ACTIONS))
    held = asyncio.create_task(reset.run("alice", live_flag=False))
    async with asyncio.timeout(5):
        await later.entered.wait()
    assert await mint.run(_EMAIL, live_flag=False) is X.API_RUNNING
    assert [r["reason"] for r in second.direct.records] == [None, "api_running"]
    assert second.hashes == []
    later.release.set()
    assert await held is BreakGlassExit.RESET


async def test_no_secret_in_output_or_logs(capsys: pytest.CaptureFixture[str]) -> None:
    # DC-4479-16: each port answers with something that must not travel further; the mint port
    # raises with the token and a DSN in its message.
    dsn = "LEAK-DSN-PASSWORD-5c1f"
    hosts = [
        _Host(minted=ConnectionError(f"{_DRAWN} {dsn}")),
        _Host(state=OSError(f"password authentication failed: {dsn}")),
        _Host(api_up=OSError(f"could not connect: {dsn}")),
        _Host(journal_error=OSError(f"cannot open {dsn}")),
        _Host(kek=KekCheckResult(None, False, f"kek_mismatch {dsn}")),
    ]
    with capture_logs() as logs:
        exits = [await w.run() for w in hosts]
    out = capsys.readouterr()
    records = [r for w in hosts for r in w.journal.records + w.direct.records]
    seen = out.out + out.err + json.dumps(logs, default=str) + json.dumps(records, default=str)
    assert [leak for leak in (_DRAWN, dsn, *hosts[0].hashes) if leak in seen] == []
    assert exits == [X.MINT_FAILED, X.STEP_FAILED, X.STEP_FAILED, X.HOST_FS_UNAVAILABLE,
                     X.KEK_UNPROVEN]  # fmt: skip
    stepped = {"step": "target_check", "error": "OSError"}
    assert hosts[1].journal.records[-1]["after_state"] == stepped
    assert hosts[4].journal.records[-1]["after_state"] == {"proof": "kek_unavailable"}
    events = {entry["event"].removeprefix("bootstrap_owner.") for entry in logs}
    assert {"mint_failed", "step_failed", "journal_unavailable"} <= events


async def test_environment_spoof_is_kek_unproven(tmp_path: Path) -> None:
    # DC-4479-16: CV_ENVIRONMENT=demo against a live database. Only the KEK proof stops it: the
    # KEK is enrolled for live alone, so demo's lineage refuses it (`kek_reused`, O1: never
    # enrolled), and nothing is read or minted.
    raw = os.urandom(32)
    (tmp_path / "kek").write_bytes(raw)
    (tmp_path / "kek").chmod(0o400)
    loaded = LoadedKek(bytearray(raw), 1, env_name="live")
    kcv = InMemoryCredentialStore()
    kcv.kcvs[("live", 1)] = loaded.kcv()
    loaded.close()
    settings = Settings(environment=DEMO, kek_source="file", kek_handle=str(tmp_path / "kek"))

    async def proof() -> KekCheckResult:  # SR-009 hardening must not reach the pytest process
        return await prove_kek_possession(settings, kcv, harden=lambda: True)

    w = _Host(DEMO)
    spoofed = BootstrapOwnerFlow(dataclasses.replace(w.flow._ports, prove_kek=proof))
    assert await spoofed.run(_EMAIL, live_flag=False) is X.KEK_UNPROVEN
    assert (w.calls, w.hashes) == (["journal", ATTEMPT, REFUSED, "close"], [])
    assert w.journal.records[-1]["after_state"] == {"proof": "kek_reused"}
    assert (list(kcv.kcvs), kcv.kcv_audit) == ([("live", 1)], [])
