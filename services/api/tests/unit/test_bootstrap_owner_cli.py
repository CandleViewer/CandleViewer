"""The bootstrap-Owner entry point (#4479 C2): `main()` (logging first, exit statuses, the settings
the compose service passes) and `run()` over the composed ports with in-memory stores (the real
flow and C1 service, the host journal, the run lock and the KEK proof). The terminal is
break-glass's `_Tty`, tested in `test_breakglass_cli.py`; Postgres is in
`tests/integration/auth/test_bootstrap_owner_e2e_pg.py`. Files only under `tmp_path`; no network."""

from __future__ import annotations

import dataclasses
import json
import os
import uuid
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from candleviewer import bootstrap_owner, breakglass
from candleviewer.admin import breakglass_wiring
from candleviewer.admin.bootstrap_owner import BootstrapOwnerExit as X
from candleviewer.admin.breakglass import RunCancelled
from candleviewer.audit.actions import UnknownAuditAction
from candleviewer.audit.journal import hold_run_lock, journal_dir
from candleviewer.auth.invite_service import hash_token
from candleviewer.observability.logging import configure_logging, reset_logging
from candleviewer.secrets._kek import LoadedKek
from candleviewer.settings import Environment, Settings
from tests.unit import test_breakglass_cli as bg
from tests.unit.test_breakglass_cli import (
    _FIELDS,
    _journal,
    _Operator,
    _rows,
    _settings,
    _unhardened,  # noqa: F401 - autouse fixture
)

ATTEMPT, REFUSED, INVITED = (
    "auth.bootstrap_owner_attempt",
    "auth.bootstrap_owner_refused",
    "auth.bootstrap_owner_invited",
)
_EMAIL, _SHOWN = "owner@example.invalid", "Invite token (shown once): "
_MINTED = (uuid.UUID(int=7), uuid.UUID(int=8), True, 0)
P = pytest.param


class _Mints:
    """`BootstrapOwnerStore` in memory: `state` is what the read and the mint answer (None: the
    email names no user yet, so the mint creates one)."""

    def __init__(self) -> None:
        self.state: str | None = None
        self.reads, self.hashes = 0, list[str]()

    async def bootstrap_state(self, email: str, username: str) -> Any:
        self.reads += 1
        return self.state

    async def mint_owner_invite(self, **fields: Any) -> Any:
        self.hashes.append(fields["token_hash"])
        return self.state or _MINTED


@dataclasses.dataclass
class _Stores(bg._Stores):
    """`BootstrapOwnerStores` in memory (break-glass's, plus the mint)."""

    bootstrap_owners: _Mints = dataclasses.field(default_factory=_Mints)


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


async def _run(settings: Settings, stores: _Stores, owner: str = _EMAIL) -> tuple[X, _Operator]:
    operator = _Operator()
    status = await bootstrap_owner.run(
        settings, owner, live_flag=False, terminal=operator, stores=stores
    )
    return status, operator


async def test_run_mints_over_the_composed_ports(tmp_path: Path, stores: _Stores) -> None:
    settings = _settings(tmp_path)
    status, operator = await _run(settings, stores)
    assert status is X.INVITED
    assert _rows(stores) == [(ATTEMPT, "success", None), (INVITED, "success", None)]
    assert {r["actor_label"] for r in stores.audit_log.rows} == {"system:bootstrap"}
    [token] = [line.removeprefix(_SHOWN) for line in operator.lines if line.startswith(_SHOWN)]
    assert stores.bootstrap_owners.hashes == [hash_token(token)]  # the store had only its hash
    assert token not in json.dumps(stores.audit_log.rows) and operator.lines[-1] == bg._AUDITED
    assert _journal(settings).read_bytes() == b""  # flushed and compacted
    hold_run_lock(_journal(settings).parent, exclusive=True).close()  # the run lock is released


@pytest.mark.parametrize(("setup", "status", "journaled"), [
    P({"audit_wal_path": "var/audit/audit.wal"}, X.HOST_FS_UNAVAILABLE, False, id="4-relative"),
    P({"run_lock": True}, X.API_RUNNING, False, id="5-run-lock-held"),
    P({"others": True}, X.API_RUNNING, True, id="5-another-session"),
    P({"kek_handle": "missing"}, X.KEK_UNPROVEN, True, id="9-no-kek"),
    P({"state": "owner_exists"}, X.OWNER_EXISTS, True, id="17-an-owner-is-active"),
])  # fmt: skip
async def test_run_refuses_over_the_composed_ports(
    tmp_path: Path,
    stores: _Stores,
    monkeypatch: pytest.MonkeyPatch,
    setup: dict[str, Any],
    status: X,
    journaled: bool,
) -> None:
    # Every refusal has its two records in audit_log, through the journal or straight there
    # when no journal could be had; nothing is minted.
    monkeypatch.chdir(tmp_path)  # a relative WAL path resolves here, never in the checkout
    stores.others, stores.bootstrap_owners.state = setup.get("others", False), setup.get("state")
    overrides = {k: v for k, v in setup.items() if k in ("audit_wal_path", "kek_handle")}
    if "kek_handle" in overrides:
        overrides["kek_handle"] = str(tmp_path / "missing")
    settings = _settings(tmp_path, **overrides)
    held = None
    if setup.get("run_lock"):  # cv-api holds the run lock, shared
        held = hold_run_lock(journal_dir(settings.audit_wal_path), exclusive=False)
    try:
        assert (await _run(settings, stores))[0] is status
    finally:
        if held is not None:
            held.close()
    assert _rows(stores) == [(ATTEMPT, "success", None), (REFUSED, "denied", status.reason)]
    assert stores.bootstrap_owners.hashes == []
    assert _journal(settings).exists() is journaled


@pytest.mark.parametrize(("live_flag", "status"), [
    P(False, X.LIVE_FLAG_REQUIRED, id="7-live-without-the-flag"),
    P(True, X.KEK_UNPROVEN, id="9-live-refuses-this-file-kek"),
])  # fmt: skip
async def test_composed_ports_take_live_from_the_settings(
    tmp_path: Path, stores: _Stores, live_flag: bool, status: X
) -> None:
    # U49's "--live must match CV_ENVIRONMENT" where the CLI composes it: the flow's environment
    # is the settings', so live needs --live and, given it, reaches the KEK proof, which refuses
    # a `file` KEK there. Nothing is asked, read or minted (CR-4494-03).
    settings = _settings(tmp_path).model_copy(update={"environment": Environment.LIVE})
    operator = _Operator()
    ran = await bootstrap_owner.run(
        settings, _EMAIL, live_flag=live_flag, terminal=operator, stores=stores
    )
    assert ran is status
    assert _rows(stores) == [(ATTEMPT, "success", None), (REFUSED, "denied", status.reason)]
    intent = json.loads(stores.audit_log.rows[0]["after_state"])
    assert intent == {"environment": "live", "live_flag": live_flag}
    assert (stores.bootstrap_owners.reads, stores.bootstrap_owners.hashes) == (0, [])
    assert [line for line in operator.lines if line.startswith("To confirm")] == []


async def test_trails_admit_only_their_own_actions(tmp_path: Path, stores: _Stores) -> None:
    # DC-4479-18: each CLI's trails take its own actions only, so neither journals the other's
    # records, and cv-api's `users.owner_bootstrapped` never comes in through the journal.
    ports = breakglass_wiring.build_bootstrap_owner_ports(_settings(tmp_path), stores, _Operator())
    direct, journal = await ports.open_direct(), await ports.open_journal()
    theirs = breakglass_wiring._DirectTrail(stores.audit_log)  # break-glass's: its own only
    assert direct is not None
    try:
        foreign = [(direct, "auth.break_glass_attempt"), (journal, "auth.break_glass_reset"),
                   (journal, "users.owner_bootstrapped"), (theirs, ATTEMPT)]  # fmt: skip
        for trail, action in foreign:
            with pytest.raises(UnknownAuditAction):
                await trail.emit(action, **_FIELDS)
        await journal.emit(ATTEMPT, **{**_FIELDS, "actor_label": "system:bootstrap"})
    finally:
        assert await journal.close(1.0) == 0
    assert _rows(stores) == [(ATTEMPT, "success", None)]


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[dict[str, str]]:
    """Only what the `bootstrap-owner` compose service passes (#3180): the environment, the DSN,
    the KEK trio, the audit WAL path and the log settings. No other `CV_*` variable is set."""
    monkeypatch.chdir(tmp_path)  # no stray `.env` file is read
    for name in [name for name in os.environ if name.startswith("CV_")]:
        monkeypatch.delenv(name)
    passed = {
        "CV_ENVIRONMENT": "demo",
        "CV_PG_DSN": "postgresql+asyncpg://cv:unused@127.0.0.1:1/candleviewer",
        "CV_KEK_SOURCE": "file",
        "CV_KEK_HANDLE": str(tmp_path / "kek"),
        "CV_KEK_VERSION": "1",
        "CV_AUDIT_WAL_PATH": str(tmp_path / "audit" / "audit.wal"),
        "CV_LOG_LEVEL": "info",
        "CV_LOG_FORMAT": "json",
    }
    for name, value in passed.items():
        monkeypatch.setenv(name, value)
    yield passed
    reset_logging()


def _main(argv: Sequence[str]) -> int:
    """`main()`, then its log listener stopped, so every line it wrote reaches this phase's
    capture (pytest closes a phase's capture before the fixtures' teardown runs)."""
    try:
        return bootstrap_owner.main(argv)
    finally:
        reset_logging()


def _fake_run(calls: list[Any], outcome: X | BaseException) -> Any:
    async def run(settings: Settings, owner: str, **_: Any) -> X:
        calls.append(settings)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return run


def test_main_runs_on_the_settings_the_compose_service_passes(
    monkeypatch: pytest.MonkeyPatch, cli_env: dict[str, str]
) -> None:
    # The narrow-settings pin: those variables alone make valid settings, and logging is
    # configured from them before anything runs.
    calls: list[Any] = []

    def logging_first(**kw: Any) -> None:
        calls.append("logging")
        configure_logging(**kw)

    monkeypatch.setattr(bootstrap_owner, "configure_logging", logging_first)
    monkeypatch.setattr(bootstrap_owner, "run", _fake_run(calls, X.INVITED))
    assert _main(["--owner", _EMAIL]) == 0
    logging, settings = calls
    assert logging == "logging" and settings.pg_dsn.get_secret_value() == cli_env["CV_PG_DSN"]
    assert (settings.environment.value, settings.kek_source, settings.kek_version) == (
        "demo", "file", 1,
    )  # fmt: skip
    assert (settings.kek_handle, settings.audit_wal_path) == (
        cli_env["CV_KEK_HANDLE"], cli_env["CV_AUDIT_WAL_PATH"],
    )  # fmt: skip


@pytest.mark.usefixtures("cli_env")
def test_main_needs_no_recovery_code_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # Unlike break-glass, the bootstrap checks no recovery code: its key is never read.
    assert "CV_AUTH_RECOVERY_HMAC_KEY_HEX" not in os.environ
    monkeypatch.setattr(bootstrap_owner, "run", _fake_run([], X.OWNER_EXISTS))
    assert _main(["--owner", _EMAIL]) == 17


@pytest.mark.usefixtures("cli_env")
@pytest.mark.parametrize(("outcome", "status"), [
    P(X.INVITED, 0, id="invited"),
    P(X.NOT_CANDIDATE, 18, id="refused"),
    P(RunCancelled(X.API_RUNNING), 5, id="ctrl-c-once-keeps-the-runs-status"),
    P(KeyboardInterrupt(), 130, id="ctrl-c-twice"),
])  # fmt: skip
def test_main_exits_with_the_runs_status(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    outcome: X | BaseException,
    status: int,
) -> None:
    monkeypatch.setattr(bootstrap_owner, "run", _fake_run([], outcome))
    assert _main(["--owner", _EMAIL]) == status
    interrupted = "Bootstrap interrupted: its outcome is unknown." in capsys.readouterr().out
    assert interrupted is (status == 130)


@pytest.mark.parametrize(("variable", "value"), [
    P("CV_ENVIRONMENT", "nowhere", id="settings"), P("CV_LOG_FORMAT", "console", id="logging"),
])  # fmt: skip
def test_unusable_settings_exit_2_before_any_record(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    cli_env: dict[str, str],
    variable: str,
    value: str,
) -> None:
    calls: list[Any] = []
    monkeypatch.setattr(bootstrap_owner, "run", _fake_run(calls, X.INVITED))
    monkeypatch.setenv(variable, value)
    assert _main(["--owner", _EMAIL]) == 2
    captured = capsys.readouterr()
    assert "invalid settings" in captured.err and "nothing ran" in captured.err and calls == []
    assert value not in captured.err + captured.out


@pytest.mark.usefixtures("cli_env")
def test_main_records_an_unusable_email_and_never_echoes_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], stores: _Stores
) -> None:
    # DC-4479-10, over design section 6's "exit 2": a malformed --owner is no usage error. The
    # whole CLI runs, records it as a label, refuses it (18) before the store is read, and
    # echoes it nowhere: not on the terminal, in a log line or in a record.
    typed = "not-an-email\x1b[2J"
    monkeypatch.setattr(bootstrap_owner, "SqlAlchemyBootstrapOwnerDatabase", lambda _dsn: stores)
    assert _main(["--owner", typed]) == 18
    assert _rows(stores) == [(ATTEMPT, "success", None), (REFUSED, "denied", "not_candidate")]
    assert (stores.bootstrap_owners.reads, stores.disposed) == (0, 1)
    captured = capsys.readouterr()
    assert typed not in captured.out + captured.err + json.dumps(stores.audit_log.rows)


def test_owner_is_required() -> None:
    with pytest.raises(SystemExit) as usage:
        bootstrap_owner.main([])
    assert usage.value.code == 2


def test_the_entry_point_reuses_break_glass_terminal_and_statuses() -> None:
    # The issue's "reuse, never copy": one terminal, one pool release, one meaning per status.
    names = ("_Tty", "_dispose", "EXIT_INVALID", "EXIT_INTERRUPTED")
    assert [vars(bootstrap_owner)[name] for name in names] == [vars(breakglass)[n] for n in names]
