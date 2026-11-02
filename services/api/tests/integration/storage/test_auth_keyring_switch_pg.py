"""Integration (#2152 S5b): the auth keyring at the switch-over boot, on real Postgres 16.

M2 with the seam the real backend passes (`auth_keyring=`) over `SqlAlchemyAuthKeyStore` and the
real `kek_versions`, booted again and again on one database: a fresh environment generates its
keyring and a later boot opens it (AC1); a rotation boot re-wraps both rows and a restart without
the previous KEK still opens them, the MFA rows untouched (AC4); a demo database's enrolments
survive the import (AC3, the exit test counting what the old formats still serve); a live process
on a database sealed by demo fails closed and generates nothing (D1, AC7). Fake KEK sources,
synthetic keys and seeds only; CI integration lane.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from testcontainers.postgres import PostgresContainer

from candleviewer.admin.wiring import secrets_audit_row
from candleviewer.domain.primitives import Environment
from candleviewer.secrets.service import SecretsService, mint_auth_keyring
from candleviewer.storage.repositories.auth_keys_sqlalchemy import SqlAlchemyAuthKeyStore
from candleviewer.storage.repositories.credentials_sqlalchemy import SqlAlchemyCredentialStore
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.unit.credentials_m2._service_fakes import _bound_sources, _ctx, _Src
from tests.unit.credentials_m2._vectors import KEK_LIVE, KEK_V1, KEK_V2, AuditLog

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
AK_T, AK_R = bytes(range(140, 172)), bytes(range(172, 204))  # the env keys an import reads
SEED, CODE = bytes(range(1, 21)), "-".join(["7K3M"] * 7)  # synthetic (C-13.5)
USER = UUID(int=0xA11CE)


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        url = container.get_connection_url()
        dsn = url.replace("postgresql+psycopg2", "postgresql+psycopg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT, env={**os.environ, "CV_PG_DSN": dsn}, check=True,
        )  # fmt: skip
        yield url.replace("postgresql+psycopg2", "postgresql+asyncpg")


def _sql(dsn: str, query: str, params: tuple[object, ...] = ()) -> list[tuple[Any, ...]]:
    with psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True) as c:
        cur = c.execute(query, params)
        return cur.fetchall() if cur.description else []


def _audit_row(action: str, fields: dict[str, str]) -> dict[str, Any]:
    """The production row builder, bound per record to the environment of the boot."""
    return secrets_audit_row(fields["env"])(action, fields)


@pytest.fixture
async def rel(pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    """No lineage, no keyring and no MFA material at the start of every test."""
    _sql(pg_dsn, "TRUNCATE auth_keys; DELETE FROM recovery_codes; DELETE FROM mfa_methods")
    _sql(pg_dsn, "DELETE FROM api_keys; DELETE FROM kek_versions")
    repository = SqlAlchemyRelationalRepository(pg_dsn)
    try:
        yield repository
    finally:
        await repository.dispose()


async def _boot(
    rel: SqlAlchemyRelationalRepository,
    env_name: Environment,
    src: _Src,
    prev: _Src | None = None,
    /,
    **settings: Any,
) -> SecretsService:
    """One boot of `env_name`'s M2 with the keyring seam, as `admin.wiring` passes it."""
    store = SqlAlchemyCredentialStore(rel, audit_row=_audit_row)
    keys = SqlAlchemyAuthKeyStore(rel, env=env_name, audit_row=_audit_row)
    svc = SecretsService(
        store=store, kcv_store=store, audit=AuditLog(), sources=_bound_sources(src, prev),
        harden=lambda: True, auth_keys=keys, auth_keyring=keys,
    )  # fmt: skip
    await svc.start(_ctx(environment=env_name, **settings))
    return svc


def _keyring(dsn: str, env_name: str) -> list[tuple[str, str, int]]:
    return sorted(
        (str(p), str(o), int(v))
        for p, o, v in _sql(
            dsn, "SELECT purpose, origin, kek_version FROM auth_keys WHERE env = %s", (env_name,)
        )
    )


def _seed_legacy_material(dsn: str) -> UUID:
    """A new demo user enrolled under the env keys: a TOTP method sealed with no AAD and one
    unused recovery code digested with no user, as before the switch-over; its id."""
    user = uuid4()
    nonce = bytes(12)
    sealed = nonce + AESGCM(AK_T).encrypt(nonce, SEED, None)
    norm = CODE.replace("-", "").encode()
    digest = hmac.new(AK_R, norm, hashlib.sha256).hexdigest()
    _sql(
        dsn,
        "INSERT INTO users (id, email, username, password_hash) VALUES (%s, %s, %s, %s)",
        (user, f"{user.hex[:8]}@x.io", f"u{user.hex[:8]}", "$argon2id$x"),
    )
    _sql(
        dsn,
        "INSERT INTO mfa_methods (id, user_id, kind, secret_enc, secret_key_ref, confirmed_at) "
        "VALUES (gen_random_uuid(), %s, 'totp', %s, 'local-dev-v1', now() - interval '1 day')",
        (user, sealed),
    )
    _sql(
        dsn,
        "INSERT INTO recovery_codes (id, user_id, code_hash, created_at) "
        "VALUES (gen_random_uuid(), %s, %s, now() - interval '1 day')",
        (user, digest),
    )
    return user


async def test_a_fresh_environment_generates_and_a_later_boot_opens_it(
    pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    first = await _boot(rel, "demo", _Src(KEK_V1, 1))
    cap = mint_auth_keyring(first)
    blob, ref = await cap.seal_totp_seed(SEED, USER)
    await first.stop(1.0)
    generated = [("recovery_hmac", "generated", 1), ("totp_seal", "generated", 1)]
    assert _keyring(pg_dsn, "demo") == generated
    later = await _boot(rel, "demo", _Src(KEK_V1, 1))
    assert bytes(await mint_auth_keyring(later).open_totp_seed(blob, ref, USER)) == SEED
    await later.stop(1.0)


async def test_a_rotation_boot_rewraps_and_a_restart_without_the_previous_kek_opens(
    pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    """AC4: both rows move to v2, each new wrap proven first; MFA rows never change; a restart
    without the previous handle still opens the keyring."""
    first = await _boot(rel, "demo", _Src(KEK_V1, 1))
    cap = mint_auth_keyring(first)
    blob, ref = await cap.seal_totp_seed(SEED, USER)
    digests = await cap.recovery_code_digests(CODE, USER)
    await first.stop(1.0)
    rotated = await _boot(rel, "demo", _Src(KEK_V2, 2), _Src(KEK_V1, 1))
    await rotated.stop(1.0)
    assert {v for _, _, v in _keyring(pg_dsn, "demo")} == {2}
    restarted = await _boot(rel, "demo", _Src(KEK_V2, 2))
    cap = mint_auth_keyring(restarted)
    assert bytes(await cap.open_totp_seed(blob, ref, USER)) == SEED
    assert await cap.recovery_code_digests(CODE, USER) == digests
    await restarted.stop(1.0)


async def test_the_first_boot_imports_a_demo_database_and_keeps_its_enrolments(
    pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    """AC3: material made under the env keys stays usable after the import; the exit test
    counts it until it is gone."""
    user = _seed_legacy_material(pg_dsn)
    keys = {"auth_totp_key_hex": AK_T.hex(), "auth_recovery_hmac_key_hex": AK_R.hex()}
    svc = await _boot(rel, "demo", _Src(KEK_V1, 1), **keys)
    assert {o for _, o, _ in _keyring(pg_dsn, "demo")} == {"imported_env"}
    cap = mint_auth_keyring(svc)
    (sealed,) = _sql(pg_dsn, "SELECT secret_enc FROM mfa_methods WHERE user_id = %s", (user,))[0]
    assert bytes(await cap.open_totp_seed(bytes(sealed), "local-dev-v1", user)) == SEED
    (stored,) = _sql(pg_dsn, "SELECT code_hash FROM recovery_codes WHERE user_id = %s", (user,))[0]
    assert str(stored).strip() in await cap.recovery_code_digests(CODE, user)
    keys_store = SqlAlchemyAuthKeyStore(rel, env="demo", audit_row=_audit_row)
    assert await keys_store.count_legacy_material("demo") == 2
    await svc.stop(1.0)


async def test_a_live_process_on_a_demo_sealed_database_fails_closed(
    pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    """D1/AC7: material another environment sealed is never generated over: MFA is
    `auth_keyring_missing` in live, and no live row is written."""
    _seed_legacy_material(pg_dsn)
    svc = await _boot(rel, "live", _Src(KEK_LIVE, 1))
    assert svc.health().detail == "auth_keyring_missing"
    assert _keyring(pg_dsn, "live") == []
    assert not await mint_auth_keyring(svc).available()
    await svc.stop(1.0)
