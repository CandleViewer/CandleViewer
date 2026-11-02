"""#2893 closure PR 1: the account-fixture seed command (`cvdev.account_fixture.seed`).

`main` runs in process. The shared seeder is a fake that writes the TOTP file as the real one does
and hashes nothing (argon2id is slow, and no database is needed), and the database probe is a fake.
Generated values are read back from the run directory, so every output can be searched for them.
No network, no sleep.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import base64
import builtins
import inspect
import json
import logging
import os
import re
import secrets
import stat
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NoReturn
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
from pydantic import SecretStr
from sqlalchemy.exc import ProgrammingError

from candleviewer.audit_lane_wiring import read_key_file
from candleviewer.auth.envelope import LOCAL_KEY_REF, TotpEncryptor
from candleviewer.secrets._kek import LoadedKek, PathKekSource
from candleviewer.settings import Environment, FeedMode, Settings
from cvdev.account_fixture import cli, seed
from cvdev.account_fixture.pack import PACK_ROOT, Pack, fixture_key_ids
from cvdev.account_fixture.seed import DatabaseFacts
from scripts import seed_fixture_user

KEY_HEX, PEPPER = "11" * 32, "unit-pepper-marker"
DSN_MARK, DB_MARK, RUN_MARK = "dsn-marker-7", "dbmark_prod", "runmark-7f3"
DSN = f"postgresql+asyncpg://cv:{DSN_MARK}@x.invalid/fixture_test"
MARKS = {PEPPER, KEY_HEX, DSN, DSN_MARK, DB_MARK, RUN_MARK, "attest"}  # what a refusal never echoes
#: The plan's roster (`qa/plans/e27-accounts-test-plan.md` 9.1 and two more Owners), spelled out
#: here apart from the module's own.
USERS = (
    "qa-owner-1 qa-owner-2 qa-owner-3 qa-manager-grants qa-manager-nogrants qa-viewer-granted"
).split()
ROLES = ["owner"] * 3 + ["manager"] * 2 + ["viewer"]
CLOSED = {f"{kind}-{user}" for kind in ("pw", "totp") for user in USERS} | {
    "roster.json",
    ".seeded",
}
SECRET_FILES = {"kek", "lane.key"}  # what `secrets` makes, and `init` with the users
MODES = {"pw-": 0o400, "totp-": 0o600, "roster.json": 0o444, ".seeded": 0o444}
MODES |= {"kek": 0o400, "lane.key": 0o400}


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    """No `CV_*` variable of the host reaches `Settings`, and no real engine is ever built."""
    for name in [n for n in os.environ if n.upper().startswith("CV_")]:
        monkeypatch.delenv(name)

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("an engine was built")

    monkeypatch.setattr(seed, "create_async_engine", forbidden)


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    (tmp_path / "run").mkdir(mode=0o700)
    return tmp_path / "run"


class FakeSeeder:
    """`seed_fixture_user.seed`'s stand-in: records its calls, writes the TOTP file as it does."""

    def __init__(self, *, existing: frozenset[str] = frozenset(), explode: bool = False) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.existing, self.explode = existing, explode

    async def __call__(self, *args: Any, **kwargs: Any) -> str | None:
        self.calls.append((args, kwargs))
        if self.explode:
            raise RuntimeError(f"seeding failed: {args!r} {kwargs!r}")  # holds every value it got
        if args[1] in self.existing:
            return None
        seed_fixture_user.write_secret(kwargs["totp_out"], secrets.token_hex(10))
        return f"id-{args[1]}"


class FakeProbe:
    def __init__(self, name: str = "fixture_test", holds_rows: bool = False) -> None:
        self.calls: list[str] = []
        self.facts = DatabaseFacts(name, holds_rows)

    async def __call__(self, dsn: str) -> DatabaseFacts:
        self.calls.append(dsn)
        return self.facts


def _missing_table(text: str) -> Exception:
    """SQLAlchemy's own error for a missing table: its text carries the statement and parameters."""
    return ProgrammingError("SELECT 1 FROM users", {"text": text}, Exception("no table"))


class Failing:
    """A probe or a seeder that fails as a database does: it raises `error(text)`, the text holding
    every value it was handed, or, with none, it never answers. It then yields to the loop until
    `asyncio.timeout` cancels it, and fails after a bounded number of yields, so a missing bound is
    a quick failure of the run and never a hang."""

    def __init__(self, error: Callable[[str], Exception] | None = None) -> None:
        self.error, self.reached = error, False

    async def __call__(self, *args: Any, **kwargs: Any) -> NoReturn:
        self.reached = True
        if self.error is not None:
            raise self.error(f"failed: {args!r} {kwargs!r}")
        for _ in range(100):
            await asyncio.sleep(0)
        raise AssertionError("no timeout ended this await")


def _settings(tmp_path: Path, **fields: Any) -> Settings:
    """The armed stack's settings with `fields` changed, unvalidated so a refusal can be built."""
    base: dict[str, Any] = {
        "environment": Environment.DEMO,
        "feed": FeedMode.SYNTHETIC,
        "account_fixture": "compliant",
        "account_fixture_dir": str(tmp_path / "state"),
        "test_clock": False,
        "pg_dsn": SecretStr(DSN),
        "auth_pepper": SecretStr(PEPPER),
        "auth_totp_key_hex": SecretStr(KEY_HEX),
    }
    return Settings.model_construct(**{**base, **fields})


def _go(
    capsys: pytest.CaptureFixture[str],
    run_arg: str | Path,
    settings: Settings,
    seeder: seed.Seeder | None = None,
    probe: seed.Probe | None = None,
    command: str = "users",
    owner: str | None = None,
) -> tuple[int, str, str]:
    """`main` in process; `owner` is the uid the caller names (`CV_ACCTFIX_RUN_UID`), if any."""
    argv = [command, "--run-dir", str(run_arg)]
    environ = {} if owner is None else {seed.RUN_UID_VARIABLE: owner}
    code = seed.main(
        argv,
        settings=settings,
        seeder=seeder or FakeSeeder(),
        probe=probe or FakeProbe(),
        environ=environ,
    )
    out, err = capsys.readouterr()
    return code, out, err


# --- Refusals: one fixed line, exit 2, nothing written, nothing echoed -------------------------


def _run_arg(kind: str, tmp: Path, run: Path, patch: pytest.MonkeyPatch) -> tuple[str, str | None]:
    """The `--run-dir` argument for `kind` and the uid the caller names (None: none named), the
    filesystem (or the effective uid) prepared as that refusal needs."""
    owner: str | None = None
    match kind:
        case "relative":
            return "run", owner
        case "dots":
            return f"{run}/../run", owner
        case "missing":
            return str(tmp / RUN_MARK), owner
        case "link":
            (tmp / "link").symlink_to(run)
            return str(tmp / "link"), owner
        case "under-link":
            (tmp / "real" / RUN_MARK).mkdir(parents=True)
            (tmp / "under").symlink_to(tmp / "real")
            return str(tmp / "under" / RUN_MARK), owner
        case "marker":
            (run / ".seeded").write_text("")
        case "dangling-marker":
            (run / ".seeded").symlink_to(tmp / "nowhere")  # even a dangling link counts
        case "existing-file":
            (run / "pw-qa-owner-2").write_text("kept")
        case "dangling-link":
            (run / "totp-qa-owner-1").symlink_to(tmp / "nowhere")
        case "existing-kek":
            (run / "kek").write_bytes(b"kept")
        case "existing-lane-key":
            (run / "lane.key").write_text("kept")
        case "other-owner":  # the directory is the current user's; the effective uid is not
            other = os.geteuid() + 1
            patch.setattr(os, "geteuid", lambda: other)
        case "root":  # root with no uid named gets no pass of its own
            if run.stat().st_uid == 0:
                pytest.skip("the suite runs as root: no run directory here is another user's")
            patch.setattr(os, "geteuid", lambda: 0)
        case "named-other":  # the caller names a uid that does not own the directory
            owner = str(run.stat().st_uid + 1)
        case "named-not-digits":
            owner = RUN_MARK
        case "group-access":
            run.chmod(0o750)
        case "other-access":
            run.chmod(0o707)
    return str(run), owner


KEY, SECRET = SecretStr("k"), SecretStr("s")
#: Settings fields, or `env` (set once the settings exist, as the gate reads it), `dir` (a run
#: directory kind), `db` (the probe's name and whether it holds rows) or `command`; then the reason.
REFUSALS: dict[str, tuple[dict[str, Any], str]] = {
    "live": ({"environment": Environment.LIVE}, cli.LIVE),
    "testnet": ({"environment": Environment.TESTNET}, "CV_ENVIRONMENT=demo"),
    "live-feed": (
        {"feed": FeedMode.LIVE, "bybit_api_key": KEY, "bybit_api_secret": SECRET},
        "CV_FEED=synthetic",
    ),
    "exchange-key": ({"bybit_api_key": KEY}, "CV_BYBIT_API_*"),
    "undeclared-exchange-variable": ({"env": {"CV_BYBIT_API_OTHER": "x"}}, "CV_BYBIT_API_*"),
    "test-clock": ({"test_clock": True}, "CV_TEST_CLOCK"),
    "fixture-unset": ({"account_fixture": None}, cli.NOT_ARMED),
    "state-dir-unset": ({"account_fixture_dir": None}, cli.NO_DIR),
    "secrets-unarmed": ({"account_fixture": None, "command": "secrets"}, cli.NOT_ARMED),
    "relative-run-dir": ({"dir": "relative"}, seed.RUN_DIR_RELATIVE),
    "run-dir-with-dots": ({"dir": "dots"}, seed.RUN_DIR_RELATIVE),
    "missing-run-dir": ({"dir": "missing"}, seed.RUN_DIR_MISSING),
    "symlinked-run-dir": ({"dir": "link"}, seed.RUN_DIR_LINKED),
    "run-dir-under-a-symlink": ({"dir": "under-link"}, seed.RUN_DIR_LINKED),
    "marker": ({"dir": "marker"}, seed.ALREADY_SEEDED),
    "dangling-marker-link": ({"dir": "dangling-marker"}, seed.ALREADY_SEEDED),
    "existing-file": ({"dir": "existing-file"}, seed.FILE_EXISTS),
    "dangling-link-in-the-way": ({"dir": "dangling-link"}, seed.FILE_EXISTS),
    "run-dir-of-another-owner": ({"dir": "other-owner"}, seed.RUN_DIR_SHARED),
    "root-with-no-uid-named": ({"dir": "root"}, seed.RUN_DIR_SHARED),
    "named-uid-that-does-not-own-it": ({"dir": "named-other"}, seed.RUN_DIR_SHARED),
    "named-uid-not-digits": ({"dir": "named-not-digits"}, seed.RUN_UID_INVALID),
    "run-dir-open-to-the-group": ({"dir": "group-access"}, seed.RUN_DIR_SHARED),
    "run-dir-open-to-others": ({"dir": "other-access"}, seed.RUN_DIR_SHARED),
    "secrets-after-the-seed": ({"dir": "marker", "command": "secrets"}, seed.ALREADY_SEEDED),
    "secrets-with-a-key-in-the-way": (
        {"dir": "existing-lane-key", "command": "secrets"},
        seed.FILE_EXISTS,
    ),
    "init-with-a-key-in-the-way": ({"dir": "existing-kek", "command": "init"}, seed.FILE_EXISTS),
    "init-with-a-user-file-in-the-way": (
        {"dir": "existing-file", "command": "init"},
        seed.FILE_EXISTS,
    ),
    "no-pepper": ({"auth_pepper": SecretStr("")}, seed.NO_PEPPER),
    "no-totp-key": ({"auth_totp_key_hex": None}, seed.BAD_TOTP_KEY),
    "totp-key-not-hex": ({"auth_totp_key_hex": SecretStr("zz" * 32)}, seed.BAD_TOTP_KEY),
    "totp-key-too-short": ({"auth_totp_key_hex": SecretStr("11" * 31)}, seed.BAD_TOTP_KEY),
    "database-not-a-throwaway": ({"db": (DB_MARK, False)}, seed.NOT_THROWAWAY),
    "database-name-ends-in-test-only": ({"db": ("attest", False)}, seed.NOT_THROWAWAY),
    "database-holds-rows": ({"db": ("fixture_test", True)}, seed.NOT_EMPTY),
    "init-database-not-a-throwaway": (
        {"db": (DB_MARK, False), "command": "init"},
        seed.NOT_THROWAWAY,
    ),
}


@pytest.mark.parametrize("name", REFUSALS)
def test_seed_refuses_outside_the_dev_gate(
    name: str,
    tmp_path: Path,
    run_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Every refusal is exit 2, one `account-fixture: refused: ...` line, an untouched tree and no
    seeder call; only the database's own refusals reach the database, once a run. Nothing refused (a
    path, a name, a setting, a named uid) is echoed: not in the output, a log record, a structlog
    event or the exception `run` raises (its text and `repr`). `init` writes no key before the
    database is checked."""
    caplog.set_level(logging.DEBUG)
    fields, reason = dict(REFUSALS[name][0]), REFUSALS[name][1]
    extra = {key: fields.pop(key) for key in ("env", "dir", "db", "command") if key in fields}
    for key, value in extra.get("env", {}).items():
        monkeypatch.setenv(key, value)
    settings, seeder = _settings(tmp_path, **fields), FakeSeeder()
    probe, command = FakeProbe(*extra.get("db", ())), extra.get("command", "users")
    run_arg, owner = _run_arg(extra.get("dir", ""), tmp_path, run_dir, monkeypatch)
    before = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))

    with structlog.testing.capture_logs() as events:
        code, out, err = _go(capsys, run_arg, settings, seeder, probe, command, owner)
        with pytest.raises(seed.SeedRefused) as raised:
            namespace = argparse.Namespace(command=command, run_dir=run_arg)
            seed.run(namespace, settings, seeder=seeder, probe=probe, owner=owner)

    assert (code, out) == (2, "")
    assert err.startswith("account-fixture: refused: ") and reason in err and err.count("\n") == 1
    assert sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")) == before
    assert seeder.calls == [] and len(probe.calls) == (2 if "db" in extra else 0)
    shown = [out, err, str(raised.value), repr(raised.value), *map(str, events)]
    shown += [record.getMessage() for record in caplog.records]
    assert not any(mark in text for mark in (*MARKS, str(tmp_path)) for text in shown)


# --- A good run: the roster, the files, their modes -----------------------------------------


def test_users_seeds_the_roster_through_the_shared_seeder(
    tmp_path: Path, run_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seeder, probe = FakeSeeder(), FakeProbe("test")

    code, out, err = _go(capsys, run_dir, _settings(tmp_path), seeder, probe)

    assert (code, err) == (0, "")
    assert out == f"account-fixture: seeded 6 users: {', '.join(USERS)}\n"
    assert probe.calls == [DSN]  # the one probe, before any write
    assert [(a[1], k["role"]) for a, k in seeder.calls] == list(zip(USERS, ROLES, strict=True))
    passwords = {user: (run_dir / f"pw-{user}").read_text() for user in USERS}
    assert all(re.fullmatch(r"[A-Za-z0-9_-]{32}", p) for p in passwords.values())
    distinct = len(set(passwords.values())) == 6  # one password a user: a boolean, never a value
    assert distinct
    for args, kwargs in seeder.calls:
        handed = args[2] == passwords[args[1]]  # a boolean: a failure never shows the password
        assert handed, args[1]
        assert (args[0], args[3]) == (DSN, PEPPER)
        assert kwargs["totp_out"] == run_dir / f"totp-{args[1]}"
    encryptor = seeder.calls[0][1]["totp"]
    assert isinstance(encryptor, TotpEncryptor) and encryptor.key_ref == LOCAL_KEY_REF
    assert TotpEncryptor(bytes.fromhex(KEY_HEX)).decrypt(encryptor.encrypt(b"x")) == b"x"
    roster = [{"role": role, "username": user} for user, role in zip(USERS, ROLES, strict=True)]
    assert json.loads((run_dir / "roster.json").read_text()) == {"users": roster}


def test_main_reads_the_settings_from_the_environment_when_none_are_given(
    tmp_path: Path,
    run_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env = {"ENVIRONMENT": "demo", "FEED": "synthetic", "ACCOUNT_FIXTURE": "compliant"}
    env |= {"ACCOUNT_FIXTURE_DIR": str(tmp_path / "state"), "PG_DSN": DSN, "AUTH_PEPPER": PEPPER}
    env |= {"AUTH_TOTP_KEY_HEX": KEY_HEX}
    for name, value in env.items():
        monkeypatch.setenv(f"CV_{name}", value)
    argv = ["users", "--run-dir", str(run_dir)]

    assert seed.main(argv, seeder=FakeSeeder(), probe=FakeProbe()) == 0

    capsys.readouterr()
    monkeypatch.setenv(seed.RUN_UID_VARIABLE, RUN_MARK)  # the named uid comes from there too
    assert seed.main(["secrets", "--run-dir", str(run_dir)]) == 2
    assert capsys.readouterr().err == f"account-fixture: refused: {seed.RUN_UID_INVALID}\n"

    monkeypatch.setenv("CV_ENVIRONMENT", RUN_MARK)  # a setting `Settings` refuses is never echoed
    assert seed.main(argv, seeder=FakeSeeder(), probe=FakeProbe()) == 2
    assert capsys.readouterr().err == f"account-fixture: refused: {seed.INVALID_SETTINGS}\n"


def test_a_root_one_shot_seeds_a_run_dir_owned_by_the_uid_it_is_named(
    tmp_path: Path,
    run_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The stack's one-shot runs as root and compose names the invoking user's uid, so a root
    caller passes the gate for a directory that uid owns, and only then (the matrix above refuses
    root with no uid named, and a named uid that does not own the directory)."""
    owner = str(run_dir.stat().st_uid)
    monkeypatch.setattr(os, "geteuid", lambda: 0)

    code, out, err = _go(capsys, run_dir, _settings(tmp_path), command="init", owner=owner)

    assert (code, err) == (0, "")
    assert out == f"account-fixture: {seed.KEYS_WRITTEN}; seeded 6 users: {', '.join(USERS)}\n"
    assert sorted(p.name for p in run_dir.iterdir()) == sorted(CLOSED | SECRET_FILES)


@pytest.mark.usefixtures("_umask")
def test_secrets_writes_the_kek_and_the_lane_key_once_and_shows_neither(
    tmp_path: Path,
    run_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """T2 and T3 for `secrets`: `kek` is exactly 32 bytes and `lane.key` exactly 64 hex digits, each
    a new 0400 file made O_EXCL|O_NOFOLLOW in the run directory and nowhere else, two independent
    draws that the api's own loaders accept; neither value, in any form, reaches an output or a
    log; a second run is refused and changes nothing."""
    caplog.set_level(logging.DEBUG)
    created, real_open = [], os.open

    def spy(path: Any, flags: int, mode: int = 0o777, **kwargs: Any) -> int:
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT):
            created.append((Path(path), flags))
        return real_open(path, flags, mode, **kwargs)

    with structlog.testing.capture_logs() as events, monkeypatch.context() as patch:
        patch.setattr(os, "open", spy)
        first = _go(capsys, run_dir, _settings(tmp_path), command="secrets")
        kept = {p.name: p.read_bytes() for p in run_dir.iterdir()}
        second = _go(capsys, run_dir, _settings(tmp_path), command="secrets")

    assert first == (0, f"account-fixture: {seed.KEYS_WRITTEN}\n", "")
    assert second == (2, "", f"account-fixture: refused: {seed.FILE_EXISTS}\n")
    exclusive = os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    assert sorted(path.name for path, _ in created) == sorted(SECRET_FILES)
    assert all(path.parent == run_dir and flags & exclusive == exclusive for path, flags in created)
    assert sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")) == [
        "run",
        "run/kek",
        "run/lane.key",
    ]
    kek, lane = kept["kek"], kept["lane.key"]
    shaped = len(kek) == 32 and re.fullmatch(rb"[0-9a-f]{64}", lane) is not None  # a boolean
    assert shaped
    independent = bytes.fromhex(lane.decode()) != kek  # a boolean: one key never serves both
    assert independent
    loaded = PathKekSource(run_dir / "kek", 1, allow_fifo=False, env_name="demo").load()
    read = read_key_file("CV_AUDIT_LANE_KEY_FILE", str(run_dir / "lane.key"))
    same_kek = LoadedKek(bytearray(kek), 1, env_name="demo").kcv() == loaded.kcv()
    accepted = same_kek and read == bytes.fromhex(lane.decode())  # a boolean: no key shown
    assert accepted
    unchanged = {p.name: p.read_bytes() for p in run_dir.iterdir()} == kept  # a boolean
    assert unchanged
    for name in SECRET_FILES:
        assert stat.S_IMODE((run_dir / name).stat().st_mode) == 0o400, name
    forms = {kek.hex(), base64.b64encode(kek).decode(), kek.decode("latin-1"), lane.decode()}
    shown = [*first[1:], *second[1:], *map(str, events), *(r.getMessage() for r in caplog.records)]
    echoed = any(form in text for form in forms for text in shown)  # a boolean: no value printed
    assert not echoed


def test_init_checks_the_database_before_it_writes_the_keys_then_seeds_the_roster(
    tmp_path: Path, run_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`init`, the stack's one-shot: one gate, the database read before the first write, then the
    KEK and the lane key, then the users and, last, the marker."""
    seen: dict[str, list[str]] = {}

    def listing() -> list[str]:
        return sorted(p.name for p in run_dir.iterdir())

    class SeeingProbe(FakeProbe):
        async def __call__(self, dsn: str) -> DatabaseFacts:
            seen.setdefault("probe", listing())
            return await super().__call__(dsn)

    class SeeingSeeder(FakeSeeder):
        async def __call__(self, *args: Any, **kwargs: Any) -> str | None:
            seen.setdefault("seeder", listing())
            return await super().__call__(*args, **kwargs)

    code, out, err = _go(
        capsys, run_dir, _settings(tmp_path), SeeingSeeder(), SeeingProbe(), "init"
    )

    assert (code, err) == (0, "")
    assert out == f"account-fixture: {seed.KEYS_WRITTEN}; seeded 6 users: {', '.join(USERS)}\n"
    assert seen == {"probe": [], "seeder": ["kek", "lane.key", "pw-qa-owner-1"]}
    assert listing() == sorted(CLOSED | SECRET_FILES)


def test_a_roster_user_that_already_exists_stops_the_run_before_the_marker(
    tmp_path: Path, run_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seeder = FakeSeeder(existing=frozenset({"qa-owner-2"}))

    code, out, err = _go(capsys, run_dir, _settings(tmp_path), seeder)

    assert (code, out, err) == (2, "", f"account-fixture: refused: {seed.USER_EXISTS}\n")
    assert [a[1] for a, _ in seeder.calls] == ["qa-owner-1", "qa-owner-2"]  # stopped at the second
    assert not (run_dir / ".seeded").exists() and not (run_dir / "roster.json").exists()


# --- T2: nothing is written outside the run directory ---------------------------------------


@pytest.fixture(params=[0o022, 0o066], ids=["umask-022", "umask-066"])
def _umask(request: pytest.FixtureRequest) -> Iterator[int]:
    """The process umask for one test: the seed's file modes are exact under either."""
    previous = os.umask(request.param)
    yield request.param
    os.umask(previous)


@pytest.mark.usefixtures("_umask")
@pytest.mark.parametrize("command", ["users", "init"])
def test_seed_writes_only_inside_the_run_dir(
    command: str,
    tmp_path: Path,
    run_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spies see every route a write can take, wherever it is aimed: `os.open` (the module's one
    creation primitive, which the AST test below pins), `builtins.open` in a writing mode, and
    `Path.write_text` and `write_bytes`. The tree comparison sees a file made by any other route
    inside `tmp_path`. `init` adds the KEK and the lane key, both 0400."""
    settings, created, real_open, other_routes = _settings(tmp_path), [], os.open, []
    closed = CLOSED | (SECRET_FILES if command == "init" else set())

    def spy(path: Any, flags: int, mode: int = 0o777, **kwargs: Any) -> int:
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT):
            created.append((Path(path), flags))
        return real_open(path, flags, mode, **kwargs)

    def watch(patch: pytest.MonkeyPatch, owner: Any, name: str, when: Callable[..., bool]) -> None:
        real = getattr(owner, name)

        def spy_write(first: Any, *args: Any, **kwargs: Any) -> Any:
            if when(*args, **kwargs):
                other_routes.append(f"{name}: {first}")
            return real(first, *args, **kwargs)

        patch.setattr(owner, name, spy_write)

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", spy)
        watch(patch, builtins, "open", lambda mode="r", *_a, **_k: bool(set(mode) & set("wax+")))
        watch(patch, Path, "write_text", lambda *_a, **_k: True)
        watch(patch, Path, "write_bytes", lambda *_a, **_k: True)
        code = _go(capsys, run_dir, settings, command=command)[0]

    assert code == 0 and other_routes == []
    assert sorted(path.name for path, _ in created) == sorted(closed)  # each once, no other
    assert {path.parent for path, _ in created} == {run_dir}
    exclusive = os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    for path, flags in created:
        if not path.name.startswith("totp-"):  # that file is the shared seeder's own
            assert flags & exclusive == exclusive
    tree = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))
    assert tree == sorted(["run", *(f"run/{name}" for name in closed)])
    for name in closed:
        mode = next(mode for prefix, mode in MODES.items() if name.startswith(prefix))
        assert stat.S_IMODE((run_dir / name).stat().st_mode) == mode, name


@pytest.mark.parametrize("way", ["file", "link"])
def test_a_file_put_in_the_way_after_the_gate_is_never_replaced_or_followed(
    way: str, tmp_path: Path
) -> None:
    kept, target = tmp_path / "kept", tmp_path / "x"
    kept.write_text("kept")
    target.write_text("kept") if way == "file" else target.symlink_to(kept)

    with pytest.raises(seed.SeedRefused, match=re.escape(seed.FILE_EXISTS)):
        seed._create(tmp_path, "x", b"new", 0o400)

    assert kept.read_text() == target.read_text() == "kept"


# --- T3: no generated value reaches a log or an output ----------------------------------------


def test_no_generated_value_reaches_a_log_or_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    """A good run, an `init` run, a roster user that exists, and a seeder that fails with a message
    holding everything it was handed (the matrix above holds every refusal to the same): no
    password, TOTP secret, KEK, lane key, pepper or DSN appears in stdout, stderr, a log record or
    a structlog event, and the failing seeder's own text is never shown."""
    caplog.set_level(logging.DEBUG)
    shown: list[str] = []
    runs = {"good": (FakeSeeder(), "users"), "failing": (FakeSeeder(explode=True), "users")}
    runs["existing"] = (FakeSeeder(existing=frozenset({"qa-owner-3"})), "users")
    runs["init"] = (FakeSeeder(), "init")
    with structlog.testing.capture_logs() as events:
        for name, (seeder, command) in runs.items():
            (tmp_path / name / "run").mkdir(parents=True, mode=0o700)
            code, out, err = _go(
                capsys, tmp_path / name / "run", _settings(tmp_path / name), seeder, None, command
            )
            shown += [out, err]
            assert code == (2 if name in ("failing", "existing") else 0)
            if name == "failing":  # the line names the class only: a boolean, never the text
                named = err == f"account-fixture: refused: {seed.FAILED} (RuntimeError)\n"
                assert named

    generated = {
        p.read_text().strip()
        for p in tmp_path.glob("*/run/*")
        if p.name.startswith(("pw-", "totp-", "lane.key"))
    }
    kek = (tmp_path / "init" / "run" / "kek").read_bytes()
    generated |= {kek.hex(), base64.b64encode(kek).decode(), kek.decode("latin-1")}
    shown += [r.getMessage() for r in caplog.records] + [str(event) for event in events]
    enough = len(generated) >= 28  # two runs' passwords and secrets, a lane key, a KEK's 3 forms
    assert enough  # a boolean: a failure never prints the generated values
    assert not any(value in text for value in generated | MARKS for text in shown)


@pytest.mark.parametrize(
    ("fails", "error", "named"),
    [
        ("probe", None, "TimeoutError"),
        ("seeder", None, "TimeoutError"),
        ("probe", ConnectionRefusedError, "ConnectionRefusedError"),
        ("seeder", _missing_table, "ProgrammingError"),
        ("seeder", PermissionError, "PermissionError"),
    ],
)
def test_a_failure_the_gate_does_not_name_is_one_fixed_line_naming_its_class(
    fails: str,
    error: Callable[[str], Exception] | None,
    named: str,
    tmp_path: Path,
    run_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unreachable database, a refused write and an await that never ends read apart by the
    exception's class name alone; its text, which holds what the step was handed, is never shown.
    Each await on the database has a stated bound, and a `TimeoutError` ends the run the same way.
    The bounds are 0 in the run, so an await that never answers is cancelled at its first yield."""
    assert (seed.PROBE_TIMEOUT_S, seed.SEED_TIMEOUT_S) == (30, 60)  # the stated bounds, in seconds
    monkeypatch.setattr(seed, "PROBE_TIMEOUT_S", 0)
    monkeypatch.setattr(seed, "SEED_TIMEOUT_S", 0)
    failing = Failing(error)
    seeder, probe = (failing, FakeProbe()) if fails == "seeder" else (FakeSeeder(), failing)

    code, out, err = _go(capsys, run_dir, _settings(tmp_path), seeder, probe)

    fixed = err == f"account-fixture: refused: {seed.FAILED} ({named})\n"  # a boolean: no text
    assert (code, out, fixed) == (2, "", True)
    assert failing.reached and not (run_dir / ".seeded").exists()


# --- The shared seeder, the roster and the plan -----------------------------------------------


def test_seed_calls_the_shared_seeder_with_its_signature(
    tmp_path: Path, run_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A change to `seed_fixture_user.seed`'s signature fails here, not on a stack."""
    real = inspect.signature(seed_fixture_user.seed)
    pos, kw = inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY
    assert [(p.name, p.kind, p.default) for p in real.parameters.values()] == [
        ("dsn", pos, inspect.Parameter.empty),
        ("username", pos, inspect.Parameter.empty),
        ("password", pos, inspect.Parameter.empty),
        ("pepper", pos, ""),
        ("allow_no_mfa", kw, False),
        ("role", kw, "owner"),
        ("totp", kw, None),
        ("totp_out", kw, None),
    ]
    assert real.return_annotation == "str | None"  # None: the user already existed
    assert inspect.iscoroutinefunction(seed_fixture_user.seed)
    seeder = FakeSeeder()
    _go(capsys, run_dir, _settings(tmp_path), seeder)
    for args, kwargs in seeder.calls:
        real.bind(*args, **kwargs)  # the call the command makes fits the real signature


def test_roster_matches_plan_9_1() -> None:
    plan = Path(__file__).resolve().parents[5] / "qa/plans/e27-accounts-test-plan.md"
    section = plan.read_text("utf-8").split("### 9.1 Users", 1)[1].split("\n### ", 1)[0]
    rows = [[c.strip(" `") for c in line.strip("| \n").split("|")] for line in section.splitlines()]
    fixtures = {"owner-enrolled": "qa-owner-1", "manager-with-grants": "qa-manager-grants"}
    fixtures |= {
        "manager-without-grants": "qa-manager-nogrants",
        "viewer-granted": "qa-viewer-granted",
    }
    in_plan = {row[0]: row[1].lower() for row in rows if row and row[0] in fixtures}
    roster = {member.username: member.role for member in seed.ROSTER}

    assert set(in_plan) == set(fixtures)  # the plan's four fixtures, each a row of its 9.1
    assert {fixtures[name]: role for name, role in in_plan.items()} == {
        user: roster[user] for user in fixtures.values()
    }
    extra = {user: role for user, role in roster.items() if user not in fixtures.values()}
    assert extra == {"qa-owner-2": "owner", "qa-owner-3": "owner"}  # sign-ins do not queue
    assert list(roster.items()) == list(zip(USERS, ROLES, strict=True))
    assert all(re.fullmatch(r"[a-z0-9-]{3,32}", user) for user in roster)  # users_uname_len
    assert set(seed.USER_FILES) == CLOSED


def test_six_registered_accounts_each_with_its_own_uid_and_pack_key_id() -> None:
    """E27-Q03 AC1 (BQ-04, ruled 2026-11-01): a main account and five sub-accounts under it, the
    first three as the plan's 9.2 names them, every UID and key id their own, every key id one the
    stub admits (a pack key id), and `users` still writes only its own files."""
    plan = Path(__file__).resolve().parents[5] / "qa/plans/e27-accounts-test-plan.md"
    section = plan.read_text("utf-8").split("### 9.2 Accounts", 1)[1].split("\n### ", 1)[0]
    rows = [[c.strip(" `") for c in line.strip("| \n").split("|")] for line in section.splitlines()]
    in_plan = {row[0]: (row[3], row[4]) for row in rows if row and row[0].startswith("acct-demo")}
    accounts = seed.ACCOUNTS
    mains = [a for a in accounts if a.parent_uid is None]

    assert len(accounts) == 6 and len(mains) == 1
    assert all(a.parent_uid == mains[0].uid for a in accounts if a is not mains[0])
    for field in ("alias", "label", "uid", "key_id"):
        assert len({getattr(a, field) for a in accounts}) == 6, field
    assert {a.alias: (a.uid, a.label) for a in accounts[:3]} == {
        alias: in_plan[alias] for alias in ("acct-demo-main", "acct-demo-sub1", "acct-demo-sub2")
    }
    assert all(re.fullmatch(r"9000[0-9]{4}", a.uid) for a in accounts)  # the plan's UID range
    root = Path(__file__).resolve().parents[5]
    assert {a.key_id for a in accounts} <= fixture_key_ids(Pack(root / PACK_ROOT))
    assert set(seed.USER_FILES) == CLOSED  # fixture data only: the `users` files are unchanged


# --- The probe, and the order of the gate -------------------------------------------------------


async def test_the_database_probe_reads_in_a_read_only_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection, engine = AsyncMock(), MagicMock()
    connection.execute.side_effect = [None, SimpleNamespace(one=lambda: ("fixture_test", True))]
    engine.connect.return_value.__aenter__.return_value = connection
    engine.dispose = AsyncMock()
    monkeypatch.setattr(seed, "create_async_engine", lambda dsn: engine)

    assert await seed.probe_database(DSN) == DatabaseFacts("fixture_test", True)

    statements = [str(call.args[0]) for call in connection.execute.call_args_list]
    assert statements[0] == "SET TRANSACTION READ ONLY"  # before anything is read
    assert len(statements) == 2 and "current_database()" in statements[1]
    assert all(table in statements[1] for table in ("users", "exchange_accounts", "api_keys"))
    engine.dispose.assert_awaited_once()


#: The module's I/O is a closed list. A call rooted at one of these modules (the builtin `open` is
#: `io.open`) is one of the six below, the only `Path` methods it calls are the three reads, and
#: it imports these modules in the two ways below and no other.
IO_ROOTS = frozenset("os shutil subprocess tempfile pathlib io open".split())
IO_CALLS = frozenset(
    "os.path.realpath os.path.lexists os.geteuid os.open os.fdopen os.fchmod".split()
)
PATH_READS = frozenset({"is_absolute", "is_dir", "stat"})
IO_IMPORTS = frozenset({"import os", "from pathlib import Path"})


def _calls(node: ast.AST) -> list[str]:
    """The dotted names called inside `node` (a function or the module), in source order."""
    calls = [child for child in ast.walk(node) if isinstance(child, ast.Call)]
    return [ast.unparse(c.func) for c in sorted(calls, key=lambda c: (c.lineno, c.col_offset))]


def _io_surface(tree: ast.AST) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """What the module reaches the file system or a process by, in three sets: the calls rooted at
    an I/O module, the `Path` methods called on any other value, and the imports of those modules.
    The attribute is read from the syntax tree, so a dot inside a path literal hides nothing."""
    funcs = [call.func for call in ast.walk(tree) if isinstance(call, ast.Call)]
    rooted = [f for f in funcs if ast.unparse(f).split(".", 1)[0] in IO_ROOTS]
    methods = {f.attr for f in funcs if isinstance(f, ast.Attribute) and f not in rooted}
    imports = {ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.Import | ast.ImportFrom)}
    io_imports = {i for i in imports if IO_ROOTS & set(re.findall(r"\w+", i))}
    names = frozenset(ast.unparse(f) for f in rooted)
    return names, frozenset(methods & set(dir(Path))), frozenset(io_imports)


def test_the_seed_gate_runs_before_any_io() -> None:
    """In `run`, the gate is the first call, before every call that reaches a file, a database or an
    event loop, and in `gate` the structural gate (`armed`) is asked before the uid the caller
    names is read and then the run directory checked; in `seed_users`, the probe and its check come
    before the first write (the keys of `init` included) and the shared seeder; the module's own
    I/O sits in three functions only and is a closed list (`IO_CALLS`, `PATH_READS`); and
    `seed_users` takes the gate's own result type, which only `gate` makes, so a type-checked
    caller cannot reach the seed without the gate (the type is erased at runtime)."""
    tree = ast.parse(Path(seed.__file__).read_text("utf-8"))
    functions = {
        n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    in_run, in_gate = _calls(functions["run"]), _calls(functions["gate"])
    in_users = _calls(functions["seed_users"])
    io = {"open", "os.open", "os.fdopen", "os.mkdir", "create_async_engine", "asyncio.run"}

    # no call precedes the gate (a stub command's refusal included), and `armed` precedes the uid
    # and the run directory's checks
    assert in_run[0] == "gate"
    assert in_gate.index("armed") < in_gate.index("_owner_uid") < in_gate.index("_fresh_run_dir")
    checked = max(in_users.index("probe"), in_users.index("check_database"))
    assert in_users.index("_auth_material") < in_users.index("probe")
    assert checked < min(in_users.index(name) for name in ("write_secrets", "_create", "seeder"))
    assert _calls(functions["write_secrets"]).count("_create") == 2
    sites = {n: sorted(set(_calls(f)) & io) for n, f in functions.items() if set(_calls(f)) & io}
    assert sites == {
        "_create": ["os.fdopen", "os.open"],
        "probe_database": ["create_async_engine"],
        "run": ["asyncio.run"],
    }
    # a closed list, whatever the route: `os.makedirs`, `shutil.copy`, `Path(...).write_text`, a
    # `from os import makedirs` and the rest each fail it
    assert _io_surface(tree) == (IO_CALLS, PATH_READS, IO_IMPORTS)
    taken = inspect.signature(seed.seed_users).parameters["run_dir"].annotation
    assert [n for n, f in functions.items() if "RunDir" in _calls(f)] == ["gate"]
    assert taken == inspect.signature(seed.gate).return_annotation == "RunDir"
