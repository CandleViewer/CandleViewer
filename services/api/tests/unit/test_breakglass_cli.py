"""The break-glass entry point (E09-S11 #2119 slice 5): `main()` (logging first, exit statuses),
`run()` over the composed ports with in-memory stores (the real flow, host journal, run lock and
KEK proof), and the operator's terminal on a real pseudo-terminal. The Postgres cases are in
`tests/integration/auth/test_breakglass_cli_pg.py`. Files only under `tmp_path`; no network."""

from __future__ import annotations

import asyncio
import dataclasses
import functools
import json
import os
import termios
import uuid
from collections.abc import Iterator, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import structlog
from pydantic import SecretStr
from structlog.testing import capture_logs

from candleviewer import breakglass
from candleviewer.admin import breakglass as flow
from candleviewer.admin import breakglass_wiring
from candleviewer.admin.breakglass import BreakGlassExit as X
from candleviewer.admin.breakglass import RunCancelled
from candleviewer.audit.actions import UnknownAuditAction
from candleviewer.audit.journal import RunLockHeld, hold_run_lock, journal_dir
from candleviewer.audit.wal import AuditWal
from candleviewer.audit.writer import AuditWriter
from candleviewer.auth.recovery_codes import hash_recovery_code
from candleviewer.observability.logging import configure_logging, reset_logging
from candleviewer.secrets import KekCheckResult, prove_kek_possession
from candleviewer.secrets._kek import LoadedKek
from candleviewer.secrets.store import InMemoryCredentialStore
from candleviewer.settings import Environment, Settings
from tests.unit.audit.audit_fakes import FakeAuditRepository

ATTEMPT, REFUSED, RESET = (
    "auth.break_glass_attempt",
    "auth.break_glass_refused",
    "auth.break_glass_reset",
)
_OWNER_ID = uuid.UUID(int=7)
_KEY = bytes(range(32))  # test-only HMAC key, not a credential
_CODE = "TEST-ONLY-CODE-0001"  # not a real recovery code
_AUDITED = "Audit: every record reached audit_log."
_HELD = "held"  # cv-api holds the run lock, shared
#: A record's fields as the flow emits them (`AuditTrail.emit`).
_FIELDS: dict[str, Any] = {"actor_label": "system:breakglass", "actor_user_id": None,
                           "object_kind": None, "object_id": None, "object_label": None,
                           "outcome": "success", "severity": "critical", "reason": None,
                           "after_state": None, "request_id": None, "env": None}  # fmt: skip
P = pytest.param


class _Owners:
    """`BreakGlassOwners` in memory: `alice` is the one active Owner."""

    def __init__(self) -> None:
        self.hashes: list[str | None] = []

    async def find_active_owner(self, identifier: str) -> str | None:
        return str(_OWNER_ID) if identifier == "alice" else None

    async def reset_owner_mfa(
        self,
        target_user_id: str,
        *,
        now: datetime,
        recovery_code_hash: str | None,
        correlation_id: str,
    ) -> tuple[int, int, int]:
        self.hashes.append(recovery_code_hash)
        return 1, 2, 41


@dataclasses.dataclass
class _Stores:
    """`BreakGlassStores` in memory; `up`: Postgres answers; `others`: another session (R2c)."""

    audit_log: FakeAuditRepository = dataclasses.field(default_factory=FakeAuditRepository)
    kcv: InMemoryCredentialStore = dataclasses.field(default_factory=InMemoryCredentialStore)
    owners: _Owners = dataclasses.field(default_factory=_Owners)
    up: bool = True
    others: bool = False
    stuck: bool = False  # `dispose` fails
    disposed: int = 0

    async def reachable(self) -> bool:
        return self.up

    async def others_connected(self) -> bool:
        return self.others

    async def dispose(self) -> None:
        self.disposed += 1
        if self.stuck:
            raise OSError("injected")


class _Operator:
    """A terminal whose operator types back the phrase shown, and `_CODE` when asked for one."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def is_interactive(self) -> bool:
        return True

    def write(self, line: str) -> None:
        self.lines.append(line)

    async def ask(self, prompt: str) -> str:
        return self.lines[-1].removeprefix("To confirm, type: ")

    async def ask_secret(self, prompt: str) -> str:
        return _CODE


@pytest.fixture(autouse=True)
def _unhardened(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real KEK proof, minus SR-009 hardening, which must not reach the pytest process."""
    proof = functools.partial(prove_kek_possession, harden=lambda: True)
    monkeypatch.setattr(breakglass_wiring, "prove_kek_possession", proof)


@pytest.fixture
def stores(tmp_path: Path) -> _Stores:
    """`kek_versions` as a cv-api boot left it: the test KEK in `tmp_path` enrolled for demo."""
    raw = os.urandom(32)
    (tmp_path / "kek").write_bytes(raw)
    (tmp_path / "kek").chmod(0o400)
    loaded = LoadedKek(bytearray(raw), 1, env_name="demo")
    found = _Stores()
    found.kcv.kcvs[("demo", 1)] = loaded.kcv()
    loaded.close()
    return found


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    base: dict[str, Any] = {"kek_source": "file", "kek_handle": str(tmp_path / "kek")}
    base["audit_wal_path"] = str(tmp_path / "audit" / "audit.wal")
    return Settings(environment=Environment.DEMO, **base | overrides)


async def _run(settings: Settings, stores: _Stores, owner: str = "alice") -> tuple[X, _Operator]:
    operator = _Operator()
    status = await breakglass.run(
        settings,
        owner,
        live_flag=settings.environment is Environment.LIVE,
        recovery_code_key=_KEY,
        terminal=operator,
        stores=stores,
    )
    return status, operator


def _rows(stores: _Stores) -> list[tuple[str, str, str | None]]:
    return [(r["action"], r["outcome"], r["reason"]) for r in stores.audit_log.rows]


def _journal(settings: Settings) -> Path:
    return journal_dir(settings.audit_wal_path) / "journal.wal"


async def test_run_resets_over_the_composed_ports(tmp_path: Path, stores: _Stores) -> None:
    status, operator = await _run(_settings(tmp_path), stores)
    assert status is X.RESET and stores.owners.hashes == [None]  # no code outside live
    assert _rows(stores) == [(ATTEMPT, "success", None), (RESET, "success", None)]
    assert {r["actor_label"] for r in stores.audit_log.rows} == {"system:breakglass"}
    assert operator.lines[-1] == _AUDITED
    journal = _journal(_settings(tmp_path))
    assert journal.read_bytes() == b""  # flushed and compacted
    hold_run_lock(journal.parent, exclusive=True).close()  # the run lock is released


@pytest.mark.parametrize(("setup", "status", "journaled"), [
    P({"audit_wal_path": "var/audit/audit.wal"}, X.HOST_FS_UNAVAILABLE, False, id="S3-relative"),
    P({"run_lock": _HELD}, X.API_RUNNING, False, id="S4-run-lock"),
    P({"others": True}, X.API_RUNNING, True, id="S4-R2c-other-session"),
    P({"owner": "mallory"}, X.NOT_OWNER, True, id="S5-not-an-owner"),
    P({"kek_handle": "missing"}, X.KEK_UNPROVEN, True, id="S2-no-kek"),
])  # fmt: skip
async def test_run_refuses_over_the_composed_ports(
    tmp_path: Path,
    stores: _Stores,
    monkeypatch: pytest.MonkeyPatch,
    setup: dict[str, Any],
    status: X,
    journaled: bool,
) -> None:
    # Every refusal has its two records in audit_log: through the journal, or straight there
    # when no journal could be had (S3, or the run lock is held); nothing is reset.
    monkeypatch.chdir(tmp_path)  # a relative WAL path resolves here, never in the checkout
    stores.others = setup.get("others", False)
    overrides = {k: v for k, v in setup.items() if k in ("audit_wal_path", "kek_handle")}
    if "kek_handle" in overrides:
        overrides["kek_handle"] = str(tmp_path / "missing")
    settings = _settings(tmp_path, **overrides)
    held = None
    if setup.get("run_lock") == _HELD:
        held = hold_run_lock(journal_dir(settings.audit_wal_path), exclusive=False)
    try:
        assert (await _run(settings, stores, setup.get("owner", "alice")))[0] is status
    finally:
        if held is not None:
            held.close()
    assert _rows(stores) == [(ATTEMPT, "success", None), (REFUSED, "denied", status.reason)]
    assert stores.owners.hashes == []
    assert _journal(settings).exists() is journaled


async def test_unenrolled_kek_is_refused_and_never_enrolled(
    tmp_path: Path, stores: _Stores
) -> None:
    # S2 and decision O1: a KEK no cv-api boot enrolled is refused, and the proof enrols nothing.
    stores.kcv.kcvs.clear()
    status, _ = await _run(_settings(tmp_path), stores)
    assert status is X.KEK_UNPROVEN and stores.kcv.kcvs == {} and stores.kcv.kcv_audit == []
    refused = stores.audit_log.rows[-1]
    proof = json.loads(refused["after_state"])
    assert (refused["reason"], proof) == ("kek_unproven", {"proof": "kek_not_enrolled"})


async def test_postgres_down_records_stay_in_the_journal(
    tmp_path: Path, stores: _Stores, monkeypatch: pytest.MonkeyPatch
) -> None:
    # S7: Postgres refuses every insert, so the records stay journaled for cv-api's boot
    # fold-in; the summary says so, and the run lock is released for that boot.
    monkeypatch.setattr(flow, "CLOSE_GRACE_S", 0.05)  # the flush gives up at once
    stores.audit_log.down = True
    settings = _settings(tmp_path)
    status, operator = await _run(settings, stores, owner="mallory")
    assert status is X.NOT_OWNER and stores.audit_log.rows == []
    kept = [record["action"] for _end, record in AuditWal(_journal(settings)).replay()]
    assert kept == [ATTEMPT, REFUSED]
    waiting = "Audit: records waiting in the host journal: 2; cv-api folds them in."
    assert operator.lines[-1] == waiting
    hold_run_lock(_journal(settings).parent, exclusive=True).close()


async def test_unusable_journal_is_refused_and_kept(tmp_path: Path, stores: _Stores) -> None:
    # A corrupt journal is no journal (S3): the records go straight to audit_log, the file stays
    # as evidence for cv-api's fold-in to report, and the lock is released with the writer.
    settings = _settings(tmp_path)
    journal = _journal(settings)
    journal.parent.mkdir(parents=True)
    journal.write_bytes(b"not a frame\n")
    assert (await _run(settings, stores))[0] is X.HOST_FS_UNAVAILABLE
    assert _rows(stores) == [(ATTEMPT, "success", None), (REFUSED, "denied", "host_fs_unavailable")]
    assert journal.read_bytes() == b"not a frame\n"
    hold_run_lock(journal.parent, exclusive=True).close()


async def test_postgres_down_without_a_journal_is_a_pre_audit_refusal(
    tmp_path: Path, stores: _Stores, monkeypatch: pytest.MonkeyPatch
) -> None:
    # S3 with Postgres down: no record can be written anywhere, and the summary says so.
    monkeypatch.chdir(tmp_path)
    stores.up = False
    settings = _settings(tmp_path, audit_wal_path="var/audit/audit.wal")
    status, operator = await _run(settings, stores)
    assert status is X.HOST_FS_UNAVAILABLE and stores.audit_log.rows == []
    pre_audit = "Audit: no record could be written (pre-audit refusal); the log has the reason."
    assert operator.lines[-1] == pre_audit


async def test_trails_admit_only_the_break_glass_actions(tmp_path: Path) -> None:
    audit_log = FakeAuditRepository()
    direct = breakglass_wiring._DirectTrail(audit_log)
    journal = await breakglass_wiring._open_journal(str(tmp_path / "audit.wal"), audit_log)
    try:
        for trail in (direct, journal):
            with pytest.raises(UnknownAuditAction):
                await trail.emit("auth.login", **_FIELDS)
    finally:
        assert await journal.close(1.0) == 0
    assert audit_log.rows == []


async def test_journal_writer_that_does_not_start_releases_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Broken:
        def __init__(self, *_: Any) -> None: ...

        async def start(self) -> None:
            raise RuntimeError("injected")

    monkeypatch.setattr(breakglass_wiring, "AuditWriter", _Broken)
    wal = str(tmp_path / "audit.wal")
    with pytest.raises(RuntimeError):
        await breakglass_wiring._open_journal(wal, FakeAuditRepository())
    hold_run_lock(journal_dir(wal), exclusive=True).close()


async def test_journal_lock_outlives_the_writer_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # While the writer stops, its flusher may still write journal.wal: the run keeps the lock
    # until the stop returns, so cv-api (or another run) cannot fold that journal in meanwhile.
    wal = str(tmp_path / "audit.wal")
    held: list[bool] = []

    class _Watched(AuditWriter):
        async def stop(self, grace_s: float = 5.0) -> None:
            try:
                hold_run_lock(journal_dir(wal), exclusive=True).close()
            except RunLockHeld:
                held.append(True)
            else:
                held.append(False)
            await super().stop(grace_s)

    monkeypatch.setattr(breakglass_wiring, "AuditWriter", _Watched)
    audit_log = FakeAuditRepository()
    trail = await breakglass_wiring._open_journal(wal, audit_log)
    await trail.emit(ATTEMPT, **_FIELDS)
    assert await trail.close(1.0) == 0
    assert held == [True] and [row["action"] for row in audit_log.rows] == [ATTEMPT]
    hold_run_lock(journal_dir(wal), exclusive=True).close()  # released once close returned


async def test_live_rule_checks_the_code_with_the_configured_key(
    tmp_path: Path, stores: _Stores, monkeypatch: pytest.MonkeyPatch
) -> None:
    # In live the reset hashes the operator's code with cv-api's recovery-code key (O3, the
    # ratified rule). `file` KEKs are refused in live, so the proof's answer is given here.
    async def proven(*_: Any) -> KekCheckResult:
        return KekCheckResult(1, True, None)

    monkeypatch.setattr(breakglass_wiring, "prove_kek_possession", proven)
    settings = _settings(tmp_path).model_copy(update={"environment": Environment.LIVE})
    status, _ = await _run(settings, stores)
    assert status is X.RESET
    assert stores.owners.hashes == [hash_recovery_code(_CODE, key=_KEY)]


@pytest.mark.parametrize("stuck", [False, True], ids=["released", "release-fails"])
async def test_run_builds_and_releases_its_own_pool(
    tmp_path: Path, stores: _Stores, monkeypatch: pytest.MonkeyPatch, stuck: bool
) -> None:
    # Without `stores` the run builds the CLI's one pool from CV_PG_DSN and releases it once
    # it has ended; a pool that will not close is logged, and the run's status stands.
    dsns: list[str] = []

    def database(dsn: str) -> _Stores:
        dsns.append(dsn)
        stores.stuck = stuck
        return stores

    monkeypatch.setattr(breakglass, "SqlAlchemyBreakGlassDatabase", database)
    settings = _settings(tmp_path)
    with capture_logs() as logs:
        status = await breakglass.run(
            settings, "nobody", live_flag=False, recovery_code_key=_KEY, terminal=_Operator()
        )
    assert status is X.NOT_OWNER
    assert dsns == [settings.pg_dsn.get_secret_value()] and stores.disposed == 1
    unreleased = [e for e in logs if e["event"] == "breakglass.pool_not_released"]
    assert unreleased == ([{"event": "breakglass.pool_not_released", "error": "OSError",
                           "log_level": "warning"}] if stuck else [])  # fmt: skip


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    monkeypatch.chdir(tmp_path)  # no stray `.env` file is read
    monkeypatch.setenv("CV_ENVIRONMENT", "demo")
    monkeypatch.setenv("CV_AUTH_RECOVERY_HMAC_KEY_HEX", _KEY.hex())
    yield
    reset_logging()


def _main(argv: Sequence[str]) -> int:
    """`main()`, then its log listener stopped, so every line it wrote reaches this phase's
    capture: pytest closes a phase's capture before the fixtures' teardown runs."""
    try:
        return breakglass.main(argv)
    finally:
        reset_logging()


def _fake_run(calls: list[str], outcome: X | BaseException) -> Any:
    async def run(settings: Settings, owner: str, **_: Any) -> X:
        calls.append("run")
        structlog.get_logger("probe").warning("breakglass.probe", recovery_code="probe")
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return run


@pytest.mark.usefixtures("cli_env")
def test_logging_configured_first(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[str] = []
    key = breakglass.recovery_code_key

    def logging_first(**kw: Any) -> None:
        calls.append("logging")
        configure_logging(**kw)

    def key_second(settings: Settings) -> bytes | None:
        calls.append("key")
        return key(settings)

    monkeypatch.setattr(breakglass, "configure_logging", logging_first)
    monkeypatch.setattr(breakglass, "recovery_code_key", key_second)
    monkeypatch.setattr(breakglass, "run", _fake_run(calls, X.RESET))
    assert _main(["--owner", "alice"]) == 0
    [line] = [json.loads(out) for out in capsys.readouterr().out.splitlines() if "probe" in out]
    assert calls == ["logging", "key", "run"]
    assert (line["recovery_code"], line["env"]) == ("[redacted:key-name]", "demo")


@pytest.mark.usefixtures("cli_env")
@pytest.mark.parametrize(("outcome", "status"), [
    P(X.RESET, 0, id="reset"),
    P(X.NOT_OWNER, 10, id="refused"),
    P(RunCancelled(X.API_RUNNING), 5, id="ctrl-c-once-keeps-the-runs-status"),
    P(KeyboardInterrupt(), breakglass.EXIT_INTERRUPTED, id="ctrl-c-twice"),
])  # fmt: skip
def test_main_exits_with_the_runs_status(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    outcome: X | BaseException,
    status: int,
) -> None:
    monkeypatch.setattr(breakglass, "run", _fake_run([], outcome))
    assert _main(["--owner", "alice"]) == status
    interrupted = "Break-glass interrupted: its outcome is unknown." in capsys.readouterr().out
    assert interrupted is (status == breakglass.EXIT_INTERRUPTED)


@pytest.mark.usefixtures("cli_env")
@pytest.mark.parametrize(("variable", "value", "message"), [
    P("CV_ENVIRONMENT", "nowhere", "invalid settings (ValidationError)", id="settings"),
    P("CV_LOG_FORMAT", "console", "invalid settings (ValueError)", id="logging"),
    P("CV_AUTH_RECOVERY_HMAC_KEY_HEX", None, "recovery-code key", id="no-key"),
    P("CV_AUTH_RECOVERY_HMAC_KEY_HEX", "zz" * 32, "recovery-code key", id="not-hex"),
    P("CV_AUTH_RECOVERY_HMAC_KEY_HEX", "ab" * 16, "recovery-code key", id="short-key"),
])  # fmt: skip
def test_unusable_settings_exit_2_before_any_record(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    variable: str,
    value: str | None,
    message: str,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(breakglass, "run", _fake_run(calls, X.RESET))
    if value is None:
        monkeypatch.delenv(variable)
    else:
        monkeypatch.setenv(variable, value)
    assert _main(["--owner", "alice"]) == breakglass.EXIT_INVALID
    captured = capsys.readouterr()
    assert message in captured.err and "nothing ran" in captured.err and calls == []
    assert value is None or value not in captured.err + captured.out


def test_owner_is_required() -> None:
    with pytest.raises(SystemExit) as usage:
        breakglass.main([])
    assert usage.value.code == breakglass.EXIT_INVALID


@pytest.fixture
def pty() -> Iterator[tuple[int, Any, Any]]:
    """A pseudo-terminal: the operator's end (`master`), and the CLI's stdin and stdout."""
    master, slave = os.openpty()
    with open(slave, closefd=False) as stdin, open(slave, "w", closefd=False) as stdout:
        yield master, stdin, stdout
    os.close(master)
    os.close(slave)


async def test_tty_reads_a_typed_line(pty: tuple[int, Any, Any]) -> None:
    master, stdin, stdout = pty
    tty = breakglass._Tty(stdin, stdout)
    assert tty.is_interactive()
    os.write(master, b"reset alice on demo 0A1B2C\n")
    assert await asyncio.wait_for(tty.ask("> "), 5) == "reset alice on demo 0A1B2C"
    os.write(master, b"\x04")  # Ctrl-D on an empty line: end of input
    with pytest.raises(EOFError):
        await asyncio.wait_for(tty.ask("> "), 5)


async def test_tty_reads_the_code_with_echo_off(pty: tuple[int, Any, Any]) -> None:
    master, stdin, stdout = pty
    tty = breakglass._Tty(stdin, stdout)
    reading = asyncio.create_task(tty.ask_secret("code: "))
    await asyncio.sleep(0)  # one loop turn: the prompt is up and echo is off
    assert not termios.tcgetattr(stdin.fileno())[3] & termios.ECHO
    os.write(master, f"{_CODE}\n".encode())
    assert await asyncio.wait_for(reading, 5) == _CODE
    assert termios.tcgetattr(stdin.fileno())[3] & termios.ECHO  # restored
    shown = os.read(master, 4096)
    assert b"code: " in shown and _CODE.encode() not in shown


async def test_settle_leaves_a_settled_future_alone() -> None:
    settled = asyncio.get_running_loop().create_future()
    settled.set_result(None)
    breakglass._settle(settled)  # a second wake-up before the read: nothing to do
    assert settled.result() is None


def test_tty_is_not_interactive_on_a_pipe() -> None:
    read, write = os.pipe()
    with open(read) as stdin, open(write, "w") as stdout:
        assert not breakglass._Tty(stdin, stdout).is_interactive()


@pytest.mark.parametrize(("configured", "key"), [
    P(_KEY.hex(), _KEY, id="hex"), P(None, None, id="unset"), P("ab", None, id="short"),
])  # fmt: skip
def test_recovery_code_key_is_32_bytes_of_hex(configured: str | None, key: bytes | None) -> None:
    settings = Settings(
        auth_recovery_hmac_key_hex=None if configured is None else SecretStr(configured)
    )
    assert breakglass.recovery_code_key(settings) == key
