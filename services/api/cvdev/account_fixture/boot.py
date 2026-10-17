"""#2893 S8: the boot guard, layer 2 of the account fixture's fence (ADR-0036 decision 4).

Run by the lifespan through `wiring.guard_boot` before the app serves, it refuses boot while any
unrevoked key is stored outside demo, or any unrevoked demo key's `key_id_last4` (the only
plaintext part of a key id) is not a pack key id's tail, unique per pack (FX-S01). Revoked rows
never block, so revoke-then-restart recovers (FX-D01). A real demo key whose tail equals a pack
tail passes here and the per-request guard (S7) refuses it exactly; the read-only latch on a trip
is S7's too, since refusing to start is the action at boot. A refusal names counts and
environments, never a key character (C-12.6). The read is this module's own query, read-only,
through `candleviewer.storage`; the fake backend stores no key, so there it passes with its log
line. On a pass it logs a warning and writes `system.config.account_fixture_enabled` (scenario
and state dir only) through the injected audit writer (FX-R01). The pack is
`packages/fixtures/accounts` under the working directory, as the synthetic feed's sample is
(`Settings.feed_sample_path`); one naming no fixture key id refuses boot.
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
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
from cvdev.account_fixture.pack import Pack, manifest, scenario_names

PACK_ROOT: Final = Path("packages") / "fixtures" / "accounts"
#: A pack key id (README): hyphenated, so never key-shaped; the four-digit tail is unique per pack.
_FIXTURE_KEY_ID: Final = re.compile(r"fixture-[a-z][a-z0-9_]*-[0-9]{4}")
#: The most stored keys the guard reads; a database holding more refuses boot (fail closed).
MAX_STORED_KEYS: Final = 10_000
_READ_TIMEOUT_S: Final = 30.0
_DEMO: Final = Environment.DEMO.value
_READ_ONLY: Final = sa.text("SET TRANSACTION READ ONLY")
_STORED_KEYS: Final = sa.text(
    "SELECT ea.env::text AS env, k.key_id_last4 AS key_id_last4, "
    "(k.revoked_at IS NOT NULL) AS revoked "
    "FROM api_keys k JOIN exchange_accounts ea ON ea.id = k.exchange_account_id LIMIT :limit"
)


@dataclass(frozen=True, slots=True)
class StoredKey:
    """One `api_keys` row as the guard reads it: its account's environment, the last 4 characters
    of its key id and whether it is revoked. Never the key id itself."""

    env: str
    key_id_last4: str
    revoked: bool


class StoredKeys(Protocol):
    async def stored_keys(self) -> Sequence[StoredKey]: ...


class PgStoredKeys:
    """Every stored key's row on Postgres, at most `MAX_STORED_KEYS + 1`, read-only."""

    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._rel = relational

    async def stored_keys(self) -> list[StoredKey]:
        async with self._rel.unit_of_work() as uow:
            await uow.session.execute(_READ_ONLY)
            result = await uow.session.execute(_STORED_KEYS, {"limit": MAX_STORED_KEYS + 1})
            rows = result.mappings().all()
        return [StoredKey(str(r["env"]), str(r["key_id_last4"]), bool(r["revoked"])) for r in rows]


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


def fixture_key_ids(pack: Pack) -> frozenset[str]:
    """The key ids the pack's key scenarios name, fixture-shaped ones only (blocking reads)."""
    named = (manifest(pack, n).get("tester_inputs", {}).get("key_id") for n in scenario_names(pack))
    return frozenset(i for i in named if isinstance(i, str) and _FIXTURE_KEY_ID.fullmatch(i))


@dataclass(frozen=True, slots=True)
class KeyCensus:
    """The stored keys by what the guard makes of them; revoked ones never block."""

    outside_demo: Mapping[str, int]
    non_fixture_demo: int
    fixture_demo: int
    revoked: int

    @classmethod
    def of(cls, stored: Iterable[StoredKey], tails: frozenset[str]) -> KeyCensus:
        outside: Counter[str] = Counter()
        non_fixture = fixture = revoked = 0
        for key in stored:
            if key.revoked:
                revoked += 1
            elif key.env != _DEMO:
                outside[key.env] += 1
            elif key.key_id_last4 in tails:
                fixture += 1
            else:
                non_fixture += 1
        return cls(dict(sorted(outside.items())), non_fixture, fixture, revoked)

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


async def run(
    settings: Settings,
    audit: AccountFixtureAudit | None,
    *,
    keys: StoredKeys | None = None,
    pack: Pack | None = None,
) -> None:
    """The boot guard (module docstring): raises `AccountFixtureRefused`, or passes and records."""
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
            f"CV_ACCOUNT_FIXTURE refuses boot: more than {MAX_STORED_KEYS} exchange keys are stored"
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
        revoked_keys=census.revoked,
        detail="every unrevoked stored key is a demo key with a fixture key id tail",
    )
    if audit is not None:
        await audit.emit(
            ACCOUNT_FIXTURE_AUDIT_ACTION,
            actor_label="system:account-fixture",
            object_kind="settings",
            object_id="CV_ACCOUNT_FIXTURE",
            severity="warning",
            env=settings.environment.value,
            after_state={
                "scenario": settings.account_fixture,
                "fixture_dir": settings.account_fixture_dir,
            },
        )
