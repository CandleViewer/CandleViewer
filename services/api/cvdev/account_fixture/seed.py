"""#2893 closure: the account-fixture stack's seed command, its gate and its run directory.

    python -m cvdev.account_fixture.seed users|secrets|init --run-dir /run-dir

`users` makes the roster (`ROSTER`: three Owners, two Managers, a Viewer) through the nightly seeder
`scripts.seed_fixture_user.seed`, called once per user and never changed. Each password is made here
(`pw-<user>`, mode 0400); the seeder stores its hash, enrols a confirmed TOTP method and writes the
base32 secret (`totp-<user>`, a new 0600 file). Then `roster.json` (usernames and roles only, 0444)
and, last, the marker `.seeded` (0444). `ACCOUNTS` (six registered accounts, each with its own UID
and pack key id; E27-Q03, #892) is fixture data only: no command writes it yet. `secrets` makes the
run's KEK (`kek`, 32 random bytes) and audit lane key (`lane.key`, 64 hex digits), each 0400, which
the stack's api mounts as file secrets. `init`, the stack's one-shot (`fixture-init`), is `secrets`
then `users`, both after the database check. Each file of this module's own is new, made
`O_CREAT|O_EXCL|O_NOFOLLOW` with its exact mode in the run directory: nothing is replaced, followed
or written elsewhere.

The gate, in this order, each refusal one fixed line (`account-fixture: refused: ...`), exit 2,
never a value or a traceback:

1. ADR-0036's structural gate (`cli.armed`): demo, the synthetic feed, no `CV_BYBIT_API_*` variable
   of any name, no test clock, the scenario and its state directory set. There is no `CV_ENV=dev`.
2. The run directory: absolute, no `..`, its own real path (no link in or above it), an existing
   directory owned by the uid the caller names in `CV_ACCTFIX_RUN_UID` (the stack's one-shot runs as
   root and compose passes the invoking user's uid), else by the effective uid, with no group or
   other permission bit, and with no `.seeded` marker and none of the files the command makes. No
   uid, root's included, passes without that match. Both come before any file or database access
   of this module's own, and `seed_users` takes only the `RunDir` that `gate` makes.
3. For `users` and `init`, one read-only transaction before the first write: the database is named
   `test` or ends `_test`, and `users`, `exchange_accounts` and `api_keys` hold no row.

Every await on the database is bounded (`PROBE_TIMEOUT_S`, `SEED_TIMEOUT_S`). A failure the gate
does not name, a `TimeoutError` included, ends the run as one fixed line that names the exception's
class and nothing else, so an unreachable database, a missing table and a permission error read
apart.

Nothing generated is logged, printed or put in an exception. The standard library's `secrets` makes
the passwords and both keys; neither `candleviewer.secrets` nor `candleviewer.audit` is imported
(C-3.2, C-3.3).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import secrets
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
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
#: The uid a caller names as the run directory's owner (R1C-01 (a)): the stack's one-shot runs as
#: root, and compose passes the invoking user's uid here.
RUN_UID_VARIABLE: Final = "CV_ACCTFIX_RUN_UID"

INVALID_SETTINGS: Final = "invalid settings; nothing changed"
RUN_UID_INVALID: Final = f"{RUN_UID_VARIABLE} must be a uid: digits only"
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
FAILED: Final = "the seed did not complete: start a new run"
SECRETS_WRITTEN: Final = "wrote kek and lane.key"

SEEDED_MARKER: Final = ".seeded"
ROSTER_FILE: Final = "roster.json"
PW_PREFIX: Final = "pw-"
TOTP_PREFIX: Final = "totp-"
KEK_FILE: Final = "kek"
LANE_KEY_FILE: Final = "lane.key"
#: `secrets.token_urlsafe` bytes: 24 give a 32-character URL-safe password.
PASSWORD_BYTES: Final = 24
#: The KEK loader reads exactly 32 raw bytes; the lane-key loader exactly 64 hex digits (32 bytes).
KEK_BYTES: Final = 32
LANE_KEY_BYTES: Final = 32
PASSWORD_MODE: Final = 0o400
SECRET_MODE: Final = 0o400  # both loaders refuse another mode
PUBLIC_MODE: Final = 0o444
GROUP_OTHER_BITS: Final = 0o077  # any of these on the run directory refuses it
_UID: Final = re.compile(r"[0-9]{1,10}")
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


class Account(NamedTuple):
    """One registered exchange account of the fixture data: the plan's alias and label, its
    exchange UID, the UID of the main account it belongs to (`None` for a main account) and the
    pack key id stored on it (`fixture-<scenario>-NNNN`, so the stub admits it)."""

    alias: str
    label: str
    uid: str
    parent_uid: str | None
    key_id: str


#: E27-Q03 (#892) AC1: six registered demo accounts, a main account and five sub-accounts, each with
#: its own UID and its own pack key id (BQ-04, ruled 2026-11-01). The first three are the plan's
#: (`qa/plans/e27-accounts-test-plan.md` 9.2); `90000013`..`90000015` extend its fabricated range.
#: Fixture data only: no command seeds them yet (`init` makes the stack's keys and users, never
#: these), so `users` and every file it writes are unchanged. A load run switches each key to
#: `compliant` before it starts (`python -m cvdev.account_fixture.cli switch <key> --to compliant`).
ACCOUNTS: Final = (
    Account("acct-demo-main", "QA Main", "90000001", None, "fixture-compliant-0001"),
    Account("acct-demo-sub1", "QA Sub 1", "90000011", "90000001", "fixture-key_delete_5xx-0029"),
    Account("acct-demo-sub2", "QA Sub 2", "90000012", "90000001", "fixture-compliant_alt-0002"),
    Account("acct-demo-sub3", "QA Sub 3", "90000013", "90000001", "fixture-leverage_ok-0031"),
    Account("acct-demo-sub4", "QA Sub 4", "90000014", "90000001", "fixture-expiring_15d-0017"),
    Account("acct-demo-sub5", "QA Sub 5", "90000015", "90000001", "fixture-close_rejected-0030"),
)
#: Every name `users` creates in the run directory, and no other.
USER_FILES: Final = (
    *(PW_PREFIX + member.username for member in ROSTER),
    *(TOTP_PREFIX + member.username for member in ROSTER),
    ROSTER_FILE,
    SEEDED_MARKER,
)
#: Every name `secrets` creates, and no other.
SECRET_FILES: Final = (KEK_FILE, LANE_KEY_FILE)
#: The names each command creates; the gate refuses a run directory holding any of them.
COMMAND_FILES: Final[Mapping[str, tuple[str, ...]]] = {
    "users": USER_FILES,
    "secrets": SECRET_FILES,
    "init": (*SECRET_FILES, *USER_FILES),
}


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


def _owner_uid(named: str | None) -> int:
    """The uid the run directory must belong to: the one the caller names, else the effective
    uid (R1C-01 (a)). There is no other way through: root gets no pass of its own."""
    if named is None:
        return os.geteuid()
    if _UID.fullmatch(named) is None:
        raise SeedRefused(RUN_UID_INVALID)
    return int(named)


def _fresh_run_dir(value: str, owner: int, names: Sequence[str]) -> Path:
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise SeedRefused(RUN_DIR_RELATIVE)
    if os.path.realpath(path) != str(path):
        raise SeedRefused(RUN_DIR_LINKED)
    if not path.is_dir():
        raise SeedRefused(RUN_DIR_MISSING)
    info = path.stat()
    if info.st_uid != owner or info.st_mode & GROUP_OTHER_BITS:
        raise SeedRefused(RUN_DIR_SHARED)
    if os.path.lexists(path / SEEDED_MARKER):
        raise SeedRefused(ALREADY_SEEDED)
    if any(os.path.lexists(path / name) for name in names if name != SEEDED_MARKER):
        raise SeedRefused(FILE_EXISTS)
    return path


def gate(settings: Settings, run_dir: str, command: str, owner: str | None = None) -> RunDir:
    """The gate's first two checks, before any file or database access of this module's own: the
    run directory, checked for `command`'s files and the uid `owner` names, or `SeedRefused`."""
    try:
        armed(settings)
    except CliRefused as refused:
        raise SeedRefused(str(refused)) from None  # Settings' fixed messages: a rule, never a value
    uid = _owner_uid(owner)
    return RunDir(_fresh_run_dir(run_dir, uid, COMMAND_FILES[command]))


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


def _create(directory: Path, name: str, content: bytes, mode: int) -> None:
    """A new file `name` of exactly `mode`: an existing file or link of that name is never replaced
    or followed."""
    try:
        descriptor = os.open(directory / name, _CREATE_FLAGS, mode)
    except FileExistsError:
        raise SeedRefused(FILE_EXISTS) from None
    with os.fdopen(descriptor, "wb") as out:
        os.fchmod(descriptor, mode)  # the umask never loosens or tightens what the contract names
        out.write(content)


def write_secrets(run_dir: RunDir) -> None:
    """The run's KEK (32 random bytes) and audit lane key (64 hex digits), 0400 each, as the
    stack's api reads them: the KEK protects only the pack's fabricated keys in a throwaway
    database, and this module never loads, wraps or logs with either."""
    _create(run_dir, KEK_FILE, secrets.token_bytes(KEK_BYTES), SECRET_MODE)
    _create(run_dir, LANE_KEY_FILE, secrets.token_hex(LANE_KEY_BYTES).encode("ascii"), SECRET_MODE)


async def seed_users(
    run_dir: RunDir,
    settings: Settings,
    *,
    seeder: Seeder = seed,
    probe: Probe = probe_database,
    with_secrets: bool = False,
) -> tuple[str, ...]:
    """Seed `ROSTER` into the stack's database and `run_dir`, after the run's KEK and lane key when
    `with_secrets` (`init`); the usernames, in roster order."""
    pepper, encryptor = _auth_material(settings)
    dsn = settings.pg_dsn.get_secret_value()
    async with asyncio.timeout(PROBE_TIMEOUT_S):
        facts = await probe(dsn)
    check_database(facts)
    if with_secrets:
        write_secrets(run_dir)
    for member in ROSTER:
        password = secrets.token_urlsafe(PASSWORD_BYTES)
        _create(run_dir, PW_PREFIX + member.username, password.encode("ascii"), PASSWORD_MODE)
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
    text = json.dumps(roster, indent=2, sort_keys=True) + "\n"
    _create(run_dir, ROSTER_FILE, text.encode("ascii"), PUBLIC_MODE)
    _create(run_dir, SEEDED_MARKER, b"", PUBLIC_MODE)  # last: a run directory is seeded once
    return tuple(member.username for member in ROSTER)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cvdev.account_fixture.seed",
        description="Seed a fixture run's users and keys on the dev stack, once, into its run dir.",
    )
    parser.add_argument(
        "command", choices=COMMANDS, help="`init` is `secrets` and then `users`, the stack's step"
    )
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
    owner: str | None = None,
) -> str:
    """Do what `args` asks, the run directory owned by the uid `owner` names (else the effective
    uid); the line to print. Raises `SeedRefused`."""
    run_dir = gate(settings, args.run_dir, args.command, owner)
    if args.command == "secrets":
        write_secrets(run_dir)
        return SECRETS_WRITTEN
    init = args.command == "init"
    names = asyncio.run(
        seed_users(run_dir, settings, seeder=seeder, probe=probe, with_secrets=init)
    )
    seeded = f"seeded {len(names)} users: {', '.join(names)}"
    return f"{SECRETS_WRITTEN}; {seeded}" if init else seeded


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    seeder: Seeder = seed,
    probe: Probe = probe_database,
    environ: Mapping[str, str] = os.environ,
) -> int:
    args = _parser().parse_args(argv)
    try:
        try:
            resolved = settings if settings is not None else Settings()
        except ValueError:  # a pydantic ValidationError: its text may hold an input value
            raise SeedRefused(INVALID_SETTINGS) from None
        owner = environ.get(RUN_UID_VARIABLE)
        line = run(args, resolved, seeder=seeder, probe=probe, owner=owner)
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
