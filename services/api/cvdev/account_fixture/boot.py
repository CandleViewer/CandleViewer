"""#2893 S8: the boot guard, layer 2 of the account fixture's fence (ADR-0036 decision 4).

Run by the lifespan through `wiring.guard_boot` before any module starts, it refuses boot while any
unrevoked key is stored outside demo, or any unrevoked demo key's `key_id_last4` (the only
plaintext part of a key id) is not a pack key id's tail, unique per pack (FX-S01). It reads
unrevoked rows only (`revoked_at IS NULL`), so revoke-then-restart recovers (FX-D01). A real demo
key whose tail equals a pack tail passes here and the per-request guard (S7) refuses it exactly;
the read-only latch on a trip is S7's too, since refusing to start is the action at boot. A refusal
names counts and environments, never a key character (C-12.6). The read is this module's own
query, read-only, through `candleviewer.storage`; the fake backend stores no key, so there it
passes with its log line. A pass logs a warning and returns `Passed`, whose `record` the lifespan
awaits once the modules run: it writes `system.config.account_fixture_enabled` (scenario and
state dir only) through the injected audit writer (FX-R01). The pack is `pack.PACK_ROOT`; one
naming no fixture key id refuses boot.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Protocol

import sqlalchemy as sa
import structlog

from candleviewer.account_fixture_wiring import (
    ACCOUNT_FIXTURE_AUDIT_ACTION,
    AccountFixtureAudit,
    AccountFixtureRefused,
)
from candleviewer.settings import Environment, Settings
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from cvdev.account_fixture.pack import PACK_ROOT, Pack, fixture_key_ids

#: The most unrevoked stored keys the guard reads; a database holding more refuses boot.
MAX_STORED_KEYS: Final = 10_000
_READ_TIMEOUT_S: Final = 30.0
_DEMO: Final = Environment.DEMO.value
_READ_ONLY: Final = sa.text("SET TRANSACTION READ ONLY")
_STORED_KEYS: Final = sa.text(
    "SELECT ea.env::text AS env, k.key_id_last4 AS key_id_last4 "
    "FROM api_keys k JOIN exchange_accounts ea ON ea.id = k.exchange_account_id "
    "WHERE k.revoked_at IS NULL LIMIT :limit"
)


@dataclass(frozen=True, slots=True)
class StoredKey:
    """One unrevoked `api_keys` row as the guard reads it: its account's environment and the last
    4 characters of its key id. Never the key id itself."""

    env: str
    key_id_last4: str


class StoredKeys(Protocol):
    async def stored_keys(self) -> Sequence[StoredKey]: ...


class PgStoredKeys:
    """The unrevoked stored keys' rows on Postgres, at most `MAX_STORED_KEYS + 1`, read-only."""

    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._rel = relational

    async def stored_keys(self) -> list[StoredKey]:
        async with self._rel.unit_of_work() as uow:
            await uow.session.execute(_READ_ONLY)
            result = await uow.session.execute(_STORED_KEYS, {"limit": MAX_STORED_KEYS + 1})
            rows = result.mappings().all()
        return [StoredKey(str(r["env"]), str(r["key_id_last4"])) for r in rows]


async def read_stored_keys(settings: Settings) -> Sequence[StoredKey]:
    """No rows on the fake backend, which stores no key; on Postgres, a short-lived engine reads."""
    if settings.storage_backend != "real":
        return ()
    relational = SqlAlchemyRelationalRepository(
        settings.pg_dsn.get_secret_value(), "account-fixture-boot"
    )
    try:
        async with asyncio.timeout(_READ_TIMEOUT_S):
            return await PgStoredKeys(relational).stored_keys()
    finally:
        await relational.dispose()


@dataclass(frozen=True, slots=True)
class KeyCensus:
    """The unrevoked stored keys by what the guard makes of them."""

    outside_demo: Mapping[str, int]
    non_fixture_demo: int
    fixture_demo: int

    @classmethod
    def of(cls, stored: Iterable[StoredKey], tails: frozenset[str]) -> KeyCensus:
        outside: Counter[str] = Counter()
        non_fixture = fixture = 0
        for key in stored:
            if key.env != _DEMO:
                outside[key.env] += 1
            elif key.key_id_last4 in tails:
                fixture += 1
            else:
                non_fixture += 1
        return cls(dict(sorted(outside.items())), non_fixture, fixture)

    def refusal(self) -> str | None:
        found = []
        if self.outside_demo:
            per_env = ", ".join(f"{env} {n}" for env, n in self.outside_demo.items())
            found.append(f"{sum(self.outside_demo.values())} outside demo ({per_env})")
        if self.non_fixture_demo:
            found.append(f"{self.non_fixture_demo} on demo whose key id is not a fixture key id")
        if not found:
            return None
        return (
            "CV_ACCOUNT_FIXTURE refuses boot: the database holds unrevoked exchange keys, "
            f"{' and '.join(found)}; revoke them, then restart"
        )


@dataclass(frozen=True, slots=True)
class Passed:
    """A passed boot guard. `record` writes its boot record (FX-R01) once the audit writer runs."""

    settings: Settings

    async def record(self, audit: AccountFixtureAudit) -> None:
        await audit.emit(
            ACCOUNT_FIXTURE_AUDIT_ACTION,
            actor_label="system:account-fixture",
            object_kind="settings",
            object_id="CV_ACCOUNT_FIXTURE",
            severity="warning",
            env=self.settings.environment.value,
            after_state={
                "scenario": self.settings.account_fixture,
                "fixture_dir": self.settings.account_fixture_dir,
            },
        )


async def run(
    settings: Settings, *, keys: StoredKeys | None = None, pack: Pack | None = None
) -> Passed:
    """The boot guard (module docstring): raises `AccountFixtureRefused`, or passes and logs."""
    refusal = settings.account_fixture_refusal()
    if refusal is not None:
        raise AccountFixtureRefused(refusal)
    pack = pack or Pack(PACK_ROOT)
    key_ids = await asyncio.to_thread(fixture_key_ids, pack)
    if not key_ids:
        raise AccountFixtureRefused(
            f"CV_ACCOUNT_FIXTURE refuses boot: the account pack at {pack.root} names no "
            "fixture key id"
        )
    stored = await (keys.stored_keys() if keys is not None else read_stored_keys(settings))
    if len(stored) > MAX_STORED_KEYS:
        raise AccountFixtureRefused(
            f"CV_ACCOUNT_FIXTURE refuses boot: more than {MAX_STORED_KEYS} unrevoked exchange "
            "keys are stored"
        )
    census = KeyCensus.of(stored, frozenset(key_id[-4:] for key_id in key_ids))
    refusal = census.refusal()
    log = structlog.get_logger(__name__)
    if refusal is not None:
        log.error(
            "exchange.account_fixture_boot_refused",
            outside_demo=dict(census.outside_demo),
            non_fixture_demo=census.non_fixture_demo,
            detail=refusal,
        )
        raise AccountFixtureRefused(refusal)
    log.warning(
        "exchange.account_fixture_boot_guard_passed",
        environment=settings.environment.value,
        scenario=settings.account_fixture,
        storage_backend=settings.storage_backend,
        fixture_keys=census.fixture_demo,
        detail="every unrevoked stored key is a demo key with a fixture key id tail",
    )
    return Passed(settings)
