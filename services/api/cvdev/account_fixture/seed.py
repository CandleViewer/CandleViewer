"""#2893 closure, PR 1: the account-fixture stack's seed command, its gate and its run directory.

    python -m cvdev.account_fixture.seed users --run-dir /run-dir

`users` makes the roster (`ROSTER`: three Owners, two Managers, a Viewer) through the nightly seeder
`scripts.seed_fixture_user.seed`, called once per user and never changed. Each password is made here
(`pw-<user>`, mode 0400); the seeder stores its hash, enrols a confirmed TOTP method and writes the
base32 secret (`totp-<user>`, a new 0600 file). Then `roster.json` (usernames and roles only, 0444)
and, last, the marker `.seeded` (0444). Each file of this module's own is new, made
`O_CREAT|O_EXCL|O_NOFOLLOW` with its exact mode in the run directory: nothing is replaced, followed
or written elsewhere. `secrets` and `init` are named so the command line stays stable, and refuse
until the stack overlay that needs them lands.

The gate, in this order, each refusal one fixed line (`account-fixture: refused: ...`), exit 2,
never a value or a traceback:

1. ADR-0036's structural gate (`cli.armed`): demo, the synthetic feed, no `CV_BYBIT_API_*` variable
   of any name, no test clock, the scenario and its state directory set. There is no `CV_ENV=dev`.
2. The run directory: absolute, no `..`, its own real path (no link in or above it), an existing
   directory that the effective uid owns and that has no group or other permission bit, with no
   `.seeded` marker and none of the files this command makes. Both come before any file or
   database access of this module's own, and `seed_users` takes only the `RunDir` that `gate` makes.
3. One read-only transaction before the first write: the database is named `test` or ends `_test`,
   and `users`, `exchange_accounts` and `api_keys` hold no row.

Every await on the database is bounded (`PROBE_TIMEOUT_S`, `SEED_TIMEOUT_S`). A failure the gate
does not name, a `TimeoutError` included, ends the run as one fixed line that names the exception's
class and nothing else, so an unreachable database, a missing table and a permission error read
apart.

Nothing generated is logged, printed or put in an exception. The standard library's `secrets` makes
the passwords; neither `candleviewer.secrets` nor `candleviewer.audit` is imported (C-3.2, C-3.3).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import sys
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Final, NamedTuple, NewType

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from candleviewer.auth.envelope import LOCAL_KEY_REF, TotpEncryptor
from candleviewer.settings import Settings
from cvdev.account_fixture.cli import CliRefused, armed
from scripts.seed_fixture_user import seed

COMMANDS: Final = ("users", "secrets", "init")
EXIT_REFUSED: Final = 2

INVALID_SETTINGS: Final = "invalid settings; nothing changed"
RUN_DIR_RELATIVE: Final = "the run directory must be an absolute path without '..'"
RUN_DIR_LINKED: Final = "the run directory must be a real directory, not a symlink or under one"
RUN_DIR_MISSING: Final = "the run directory does not exist"
RUN_DIR_SHARED: Final = (
    "the run directory must be owned by the invoking user, with no group or other access"
)
ALREADY_SEEDED: Final = "the run directory already holds a seed marker: a run is seeded once"
FILE_EXISTS: Final = "the run directory already holds a file the seed would create"
NO_PEPPER: Final = "CV_AUTH_PEPPER must be set to seed users"
BAD_TOTP_KEY: Final = "CV_AUTH_TOTP_KEY_HEX must hold 32 bytes in hex to enrol TOTP"
NOT_THROWAWAY: Final = "the database is not a throwaway one: its name is not 'test' or '*_test'"
NOT_EMPTY: Final = "the database already holds users, exchange accounts or API keys"
USER_EXISTS: Final = "a user of the roster already exists: the run is incomplete, start a new run"
NOT_BUILT: Final = "this command is not built yet: only 'users' is available"
FAILED: Final = "the seed did not complete: start a new run"

SEEDED_MARKER: Final = ".seeded"
ROSTER_FILE: Final = "roster.json"
PW_PREFIX: Final = "pw-"
TOTP_PREFIX: Final = "totp-"
#: `secrets.token_urlsafe` bytes: 24 give a 32-character URL-safe password.
PASSWORD_BYTES: Final = 24
PASSWORD_MODE: Final = 0o400
PUBLIC_MODE: Final = 0o444
GROUP_OTHER_BITS: Final = 0o077  # any of these on the run directory refuses it
#: Bounds, in seconds, on the awaits that reach the database: one connection and one read-only
#: transaction; one user's argon2id hash, three inserts and the audit rows (an audit insert waits on
#: a lock). A `TimeoutError` ends the run as `main`'s catch-all line.
PROBE_TIMEOUT_S: Final = 30
SEED_TIMEOUT_S: Final = 60
_CREATE_FLAGS: Final = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
_READ_ONLY: Final = sa.text("SET TRANSACTION READ ONLY")
_FACTS: Final = sa.text(
    "SELECT current_database(), EXISTS (SELECT 1 FROM users) "
    "OR EXISTS (SELECT 1 FROM exchange_accounts) OR EXISTS (SELECT 1 FROM api_keys)"
)


class Member(NamedTuple):
    """One seeded user: a username and a role of the shared seeder's vocabulary."""

    username: str
    role: str


#: The plan's four fixtures (`qa/plans/e27-accounts-test-plan.md` 9.1) and two more Owners, so that
#: consecutive sign-ins do not queue behind one user's TOTP step.
ROSTER: Final = (
    Member("qa-owner-1", "owner"),
    Member("qa-owner-2", "owner"),
    Member("qa-owner-3", "owner"),
    Member("qa-manager-grants", "manager"),
    Member("qa-manager-nogrants", "manager"),
    Member("qa-viewer-granted", "viewer"),
)
#: Every name `users` creates in the run directory, and no other.
USER_FILES: Final = (
    *(PW_PREFIX + member.username for member in ROSTER),
    *(TOTP_PREFIX + member.username for member in ROSTER),
    ROSTER_FILE,
    SEEDED_MARKER,
)


class SeedRefused(Exception):
    """A fixed message, printed as the command's one line; it never names a path or a value."""


class DatabaseFacts(NamedTuple):
    """What the gate asks of the database: its own name, and whether it holds a user, an exchange
    account or an API key."""

    name: str
    holds_rows: bool


#: The shared seeder's shape (`seed_fixture_user.seed`; a unit test pins its signature) and the
#: database probe, both injected so that a test needs neither Postgres nor argon2id.
Seeder = Callable[..., Awaitable[str | None]]
Probe = Callable[[str], Awaitable[DatabaseFacts]]
#: A run directory that `gate` passed: the one type `seed_users` takes, made by `gate` and nowhere
#: else, so a type-checked caller cannot reach the seed without the gate (`NewType` is erased at
#: runtime; a test pins both).
RunDir = NewType("RunDir", Path)


def _fresh_run_dir(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise SeedRefused(RUN_DIR_RELATIVE)
    if os.path.realpath(path) != str(path):
        raise SeedRefused(RUN_DIR_LINKED)
    if not path.is_dir():
        raise SeedRefused(RUN_DIR_MISSING)
    info = path.stat()
    if info.st_uid != os.geteuid() or info.st_mode & GROUP_OTHER_BITS:
        raise SeedRefused(RUN_DIR_SHARED)
    if os.path.lexists(path / SEEDED_MARKER):
        raise SeedRefused(ALREADY_SEEDED)
    if any(os.path.lexists(path / name) for name in USER_FILES if name != SEEDED_MARKER):
        raise SeedRefused(FILE_EXISTS)
    return path


def gate(settings: Settings, run_dir: str) -> RunDir:
    """The gate's first two checks, before any file or database access of this module's own: the
    run directory, checked, or `SeedRefused`."""
    try:
        armed(settings)
    except CliRefused as refused:
        raise SeedRefused(str(refused)) from None  # Settings' fixed messages: a rule, never a value
    return RunDir(_fresh_run_dir(run_dir))


def check_database(facts: DatabaseFacts) -> None:
    """The gate's third check: a throwaway database that holds none of the stack's records."""
    if facts.name != "test" and not facts.name.endswith("_test"):
        raise SeedRefused(NOT_THROWAWAY)
    if facts.holds_rows:
        raise SeedRefused(NOT_EMPTY)


async def probe_database(dsn: str) -> DatabaseFacts:
    """Read `DatabaseFacts` in one read-only transaction on a connection of its own."""
    engine = create_async_engine(dsn)
    try:
        async with engine.connect() as connection:
            await connection.execute(_READ_ONLY)
            name, holds_rows = (await connection.execute(_FACTS)).one()
    finally:
        await engine.dispose()
    return DatabaseFacts(str(name), bool(holds_rows))


def _auth_material(settings: Settings) -> tuple[str, TotpEncryptor]:
    """The pepper and the TOTP encryptor the stack's auth uses, or a refusal naming the setting."""
    pepper = settings.auth_pepper.get_secret_value()
    if not pepper:
        raise SeedRefused(NO_PEPPER)
    configured = settings.auth_totp_key_hex
    try:
        key = bytes.fromhex(configured.get_secret_value()) if configured is not None else b""
    except ValueError:
        key = b""
    if len(key) != 32:
        raise SeedRefused(BAD_TOTP_KEY)
    return pepper, TotpEncryptor(key, key_ref=LOCAL_KEY_REF)


def _create(directory: Path, name: str, content: str, mode: int) -> None:
    """A new file `name` of exactly `mode`: an existing file or link of that name is never replaced
    or followed."""
    try:
        descriptor = os.open(directory / name, _CREATE_FLAGS, mode)
    except FileExistsError:
        raise SeedRefused(FILE_EXISTS) from None
    with os.fdopen(descriptor, "w", encoding="ascii") as out:
        os.fchmod(descriptor, mode)  # the umask never loosens or tightens what the contract names
        out.write(content)


async def seed_users(
    run_dir: RunDir, settings: Settings, *, seeder: Seeder = seed, probe: Probe = probe_database
) -> tuple[str, ...]:
    """Seed `ROSTER` into the stack's database and `run_dir`; the usernames, in roster order."""
    pepper, encryptor = _auth_material(settings)
    dsn = settings.pg_dsn.get_secret_value()
    async with asyncio.timeout(PROBE_TIMEOUT_S):
        facts = await probe(dsn)
    check_database(facts)
    for member in ROSTER:
        password = secrets.token_urlsafe(PASSWORD_BYTES)
        _create(run_dir, PW_PREFIX + member.username, password, PASSWORD_MODE)
        async with asyncio.timeout(SEED_TIMEOUT_S):
            created = await seeder(
                dsn,
                member.username,
                password,
                pepper,
                role=member.role,
                totp=encryptor,
                totp_out=run_dir / (TOTP_PREFIX + member.username),
            )
        if created is None:
            raise SeedRefused(USER_EXISTS)
    roster = {"users": [{"username": m.username, "role": m.role} for m in ROSTER]}
    _create(run_dir, ROSTER_FILE, json.dumps(roster, indent=2, sort_keys=True) + "\n", PUBLIC_MODE)
    _create(run_dir, SEEDED_MARKER, "", PUBLIC_MODE)  # last: a run directory is seeded once
    return tuple(member.username for member in ROSTER)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cvdev.account_fixture.seed",
        description="Seed a fixture run's users on the dev stack, once, into the run's directory.",
    )
    parser.add_argument("command", choices=COMMANDS, help="`users` is the only one built so far")
    parser.add_argument(
        "--run-dir", required=True, help="the run's directory: absolute, flat, a real directory"
    )
    return parser


def run(
    args: argparse.Namespace,
    settings: Settings,
    *,
    seeder: Seeder = seed,
    probe: Probe = probe_database,
) -> str:
    """Do what `args` asks; the line to print. Raises `SeedRefused`."""
    run_dir = gate(settings, args.run_dir)
    if args.command != "users":
        raise SeedRefused(NOT_BUILT)
    names = asyncio.run(seed_users(run_dir, settings, seeder=seeder, probe=probe))
    return f"seeded {len(names)} users: {', '.join(names)}"


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    seeder: Seeder = seed,
    probe: Probe = probe_database,
) -> int:
    args = _parser().parse_args(argv)
    try:
        try:
            resolved = settings if settings is not None else Settings()
        except ValueError:  # a pydantic ValidationError: its text may hold an input value
            raise SeedRefused(INVALID_SETTINGS) from None
        line = run(args, resolved, seeder=seeder, probe=probe)
    except SeedRefused as refused:
        sys.stderr.write(f"account-fixture: refused: {refused}\n")
        return EXIT_REFUSED
    except Exception as failure:  # nothing unexpected may print a traceback, path or value
        name = type(failure).__name__  # the class alone: its text and arguments can hold inputs
        sys.stderr.write(f"account-fixture: refused: {FAILED} ({name})\n")
        return EXIT_REFUSED
    sys.stdout.write(f"account-fixture: {line}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - `python -m`; `main` is tested in process
    raise SystemExit(main())
