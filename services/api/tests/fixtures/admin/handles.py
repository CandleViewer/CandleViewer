"""The admin area's seeded handles (E42-Q01, #962), named as in the black-box plan
(`docs/qa/e42-admin-test-plan.md` §1).

Every value is synthetic, and visibly so: `example.invalid` addresses, `fixture` labels, and ids
derived from each handle's name, the same on every run and machine. Nothing here is a credential, a
key, a token or anyone's personal data, and `tests/unit/test_admin_fixture_handles.py` passes every
value through the log redactor to keep it so.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Final, Literal

#: The namespace every fixture id is derived in (`uuid5`), so an id never changes between runs.
_NAMESPACE: Final = uuid.UUID("0e42a0c1-9620-4d1f-8e4a-ad31f1c7e962")

#: The exchange's key restriction on a new sub-account: no API key in its first 48 hours.
KEY_RESTRICTION: Final = timedelta(hours=48)

#: How long LOCKED-L stays locked after the seed's `now`.
LOCK_PERIOD: Final = timedelta(hours=1)

#: The password hash of every seeded user: the users table requires an argon2id hash, and this
#: one verifies no password, so no seeded user can sign in with it. A suite that signs in passes
#: a hash it computes at run time (`seed_admin_world(..., password_hash=...)`).
PLACEHOLDER_HASH: Final = "$argon2id$v=19$m=65536,t=3,p=4$fixture-salt$no-password-matches"

Role = Literal["owner", "manager", "viewer"]
Status = Literal["invited", "active", "disabled", "locked"]


def fixture_id(handle: str) -> uuid.UUID:
    """The handle's id: derived from its name, so the same on every run."""
    return uuid.uuid5(_NAMESPACE, f"e42-admin:{handle}")


@dataclass(frozen=True, slots=True)
class FixtureUser:
    handle: str
    role: Role
    status: Status

    @property
    def id(self) -> uuid.UUID:
        return fixture_id(self.handle)

    @property
    def username(self) -> str:
        return f"fx-{self.handle.lower()}"

    @property
    def email(self) -> str:
        return f"{self.username}@example.invalid"


@dataclass(frozen=True, slots=True)
class FixtureAccount:
    handle: str
    #: How long before the seed's `now` the account was created.
    age: timedelta

    @property
    def id(self) -> uuid.UUID:
        return fixture_id(self.handle)

    @property
    def is_main(self) -> bool:
        return self.handle == "MAIN"

    @property
    def label(self) -> str:
        return f"fixture {self.handle}"

    @property
    def exchange_uid(self) -> str:
        """Digits only, as the `ea_uid_fmt` check requires, and derived from the account's id."""
        return str(self.id.int % 10**12)


OWNER: Final = FixtureUser("OWNER", "owner", "active")

#: One user per handle; together every status and every role.
USERS: Final[tuple[FixtureUser, ...]] = (
    OWNER,
    FixtureUser("OWNER-2", "owner", "active"),
    FixtureUser("MGR-M", "manager", "active"),
    FixtureUser("MGR-N", "manager", "active"),
    FixtureUser("MGR-MANY", "manager", "active"),
    FixtureUser("VIEWER-V", "viewer", "active"),
    FixtureUser("INVITED-I", "viewer", "invited"),
    FixtureUser("DISABLED-D", "manager", "disabled"),
    FixtureUser("LOCKED-L", "manager", "locked"),
)

#: The demo main account and its sub-accounts. SUB-K is an hour old, inside the key restriction.
ACCOUNTS: Final[tuple[FixtureAccount, ...]] = (
    FixtureAccount("MAIN", timedelta(days=30)),
    FixtureAccount("SUB-S", timedelta(days=30)),
    FixtureAccount("SUB-T", timedelta(days=30)),
    FixtureAccount("SUB-U", timedelta(days=30)),
    FixtureAccount("SUB-K", timedelta(hours=1)),
)

#: Each manager's trade grants: none, one and many.
GRANTS: Final[dict[str, tuple[str, ...]]] = {
    "MGR-N": (),
    "MGR-M": ("SUB-S",),
    "MGR-MANY": ("SUB-S", "SUB-T", "SUB-U"),
}

#: The flags the plan's cases set, as `candleviewer/admin/flags/catalogue.py` holds them (boolean
#: flags only), and their values. `trading.live_enabled` stays off: the live gate is blocked.
FLAGS: Final[dict[str, bool]] = {
    "trading.live_enabled": False,
    "rules.graph_editor": True,
}


@dataclass(frozen=True, slots=True)
class FixtureBackup:
    handle: str
    status: Literal["verified", "failed"]
    #: How long before the seed's `now` the backup started.
    age: timedelta
    #: The verification's failure code, as the backup store records one.
    error: str | None = None

    @property
    def id(self) -> uuid.UUID:
        return fixture_id(self.handle)

    @property
    def target_path(self) -> str:
        return f"fixture/backups/{self.handle.lower()}"


#: BACKUP-VERIFY-FAILED: the latest backup failed its verification, and the last verified one is
#: three days older, so the page can say how old it is. A world seeded without them is
#: BACKUPS-NONE.
BACKUPS: Final[tuple[FixtureBackup, ...]] = (
    FixtureBackup("BACKUP-VERIFIED", "verified", timedelta(days=3)),
    FixtureBackup("BACKUP-VERIFY-FAILED", "failed", timedelta(hours=1), error="checksum_mismatch"),
)


def user(handle: str) -> FixtureUser:
    return next(u for u in USERS if u.handle == handle)


def account(handle: str) -> FixtureAccount:
    return next(a for a in ACCOUNTS if a.handle == handle)
