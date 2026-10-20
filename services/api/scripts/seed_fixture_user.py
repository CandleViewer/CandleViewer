"""Test-only fixture-user seeder (QA #1658; lets ZAP/E2E log in).

Env-driven: CV_SEED_USERNAME, CV_SEED_PASSWORD, CV_PG_DSN. Refuses to run in
live/demo (C-2.11): only `CV_ENVIRONMENT=testnet` is accepted. Never prints
the password. Parameterised SQL only.

The seeded user has `mfa_required=true` by default (C-12: TOTP for every
user). `--allow-no-mfa` seeds it with `mfa_required=false`; that opt-in is a
registered, expiring exception (04-security-program.md Sec.16.2, EX-01) for the
Owner fixture only, and is refused outside testnet. Every seed writes
`users.create` + `roles.grant` audit rows in the same transaction (C-2.9).

`--role manager` or `--role viewer` seeds that role instead of `owner` (E42-X03,
the ZAP admin profile's synthetic users). `--totp-secret-out PATH` enrols a
confirmed TOTP method with a fresh secret (a real TOTP step, no MFA
exception), encrypted as the API encrypts one, under `CV_AUTH_TOTP_KEY_HEX`,
and writes its base32 form to PATH, a new file of mode 0600, never to the
output; the enrolment is audited as `auth.mfa_enrolled`. A user that already
exists is left as it is, so with `--totp-secret-out` that is an error: no
secret was made and PATH was not written.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from candleviewer.auth.envelope import LOCAL_KEY_REF, TotpEncryptor
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.totp import generate_secret, secret_to_base32
from candleviewer.settings import Environment

ACTOR_LABEL = "seed_fixture_user"
ROLES = ("owner", "manager", "viewer")

_INSERT = sa.text("""
    INSERT INTO users (id, email, username, password_hash, status, mfa_required)
    VALUES (CAST(:id AS uuid), :email, :username, :h, 'active', :mfa_required)
    ON CONFLICT DO NOTHING
    RETURNING id::text
    """)
_ROLE = sa.text("""
    INSERT INTO user_roles (user_id, role_id)
    SELECT u.id, r.id FROM users u, roles r
    WHERE u.username = :username AND r.name = :role ON CONFLICT DO NOTHING
    """)
_TOTP = sa.text("""
    INSERT INTO mfa_methods (id, user_id, kind, label, secret_enc, secret_key_ref, confirmed_at)
    VALUES (CAST(:id AS uuid), CAST(:user_id AS uuid), 'totp', 'fixture', :enc, :ref, :now)
    """)
_AUDIT = sa.text("""
    INSERT INTO audit_log
        (record_id, actor_label, action, object_kind, object_id, outcome, severity,
         reason, after_state, event_ts)
    VALUES
        (CAST(:record_id AS uuid), :actor_label, :action, 'user', :object_id, 'success',
         'warning', :reason, CAST(:after_state AS jsonb), :event_ts)
    """)
_ADVISORY_LOCK = sa.text("SELECT pg_advisory_xact_lock(hashtext('audit_log'))")


def check_environment(env: str, *, allow_no_mfa: bool = False) -> None:
    """Refuse anything but testnet (C-2.11). `allow_no_mfa` is only ever
    meaningful on testnet, so it adds no extra path, only a second reason."""
    if env != Environment.TESTNET.value:
        what = "an MFA-less fixture owner" if allow_no_mfa else "a fixture user"
        raise SystemExit(f"refusing to seed {what} in environment {env!r} (C-2.11)")


def check_options(role: str, *, allow_no_mfa: bool, totp_out: Path | None) -> None:
    """EX-01 covers the Owner fixture alone, and an MFA-less user has no TOTP to enrol."""
    if allow_no_mfa and role != "owner":
        raise SystemExit(f"refusing an MFA-less {role}: EX-01 covers the Owner fixture only")
    if allow_no_mfa and totp_out is not None:
        raise SystemExit("--allow-no-mfa and --totp-secret-out contradict each other")


def totp_key(value: str | None) -> bytes:
    """`CV_AUTH_TOTP_KEY_HEX`, as the API decodes it: 32 bytes, hex; its value is never shown."""
    try:
        key = bytes.fromhex(value or "")
    except ValueError:
        key = b""
    if len(key) != 32:
        raise SystemExit("CV_AUTH_TOTP_KEY_HEX must hold 32 bytes in hex to enrol TOTP")
    return key


def write_secret(path: Path, secret: str) -> None:
    """A new file of mode 0600 holding the base32 secret: an existing one is never replaced."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as out:
        out.write(secret)


async def _audit(
    conn: AsyncConnection, action: str, user_id: str, after: dict[str, object]
) -> None:
    await conn.execute(_ADVISORY_LOCK)
    await conn.execute(
        _AUDIT,
        {
            "record_id": str(uuid.uuid4()),
            "actor_label": ACTOR_LABEL,
            "action": action,
            "object_id": user_id,
            "reason": "test fixture seed (QA #1658)",
            "after_state": json.dumps(after, sort_keys=True),
            "event_ts": datetime.now(UTC),
        },
    )


async def seed(
    dsn: str,
    username: str,
    password: str,
    pepper: str = "",
    *,
    allow_no_mfa: bool = False,
    role: str = "owner",
    totp: TotpEncryptor | None = None,
    totp_out: Path | None = None,
) -> str | None:
    """Seed one user of `role`; returns the new user id, or None if it already existed. With
    `totp` and `totp_out`, a confirmed TOTP method whose base32 secret goes to `totp_out`."""
    password_hash = await Hasher(pepper=pepper).hash(password)
    engine = create_async_engine(dsn)
    try:
        async with engine.begin() as conn:
            row = (
                await conn.execute(
                    _INSERT,
                    {
                        "id": str(uuid.uuid4()),
                        "email": f"{username}@fixture.invalid",
                        "username": username,
                        "h": password_hash,
                        "mfa_required": not allow_no_mfa,
                    },
                )
            ).first()
            if row is None:
                return None
            user_id = str(row[0])
            await conn.execute(_ROLE, {"username": username, "role": role})
            await _audit(
                conn,
                "users.create",
                user_id,
                {"username": username, "mfa_required": not allow_no_mfa},
            )
            await _audit(conn, "roles.grant", user_id, {"role": role})
            if totp is not None and totp_out is not None:
                secret = generate_secret()
                await conn.execute(
                    _TOTP,
                    {
                        "id": str(uuid.uuid4()),
                        "user_id": user_id,
                        "enc": totp.encrypt(secret),
                        "ref": totp.key_ref,
                        "now": datetime.now(UTC),
                    },
                )
                await _audit(conn, "auth.mfa_enrolled", user_id, {"method": "totp"})
                write_secret(totp_out, secret_to_base32(secret))  # before the commit
            return user_id
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-no-mfa",
        action="store_true",
        help="seed with mfa_required=false (testnet only; exception EX-01, Owner only)",
    )
    parser.add_argument("--role", choices=ROLES, default="owner", help="the role to seed")
    parser.add_argument(
        "--totp-secret-out",
        type=Path,
        help="enrol TOTP and write its base32 secret to this new file (mode 0600)",
    )
    args = parser.parse_args(argv)
    check_environment(os.environ.get("CV_ENVIRONMENT", "demo"), allow_no_mfa=args.allow_no_mfa)
    check_options(args.role, allow_no_mfa=args.allow_no_mfa, totp_out=args.totp_secret_out)
    totp = None
    if args.totp_secret_out is not None:
        key = totp_key(os.environ.get("CV_AUTH_TOTP_KEY_HEX"))
        totp = TotpEncryptor(key, key_ref=LOCAL_KEY_REF)
    user_id = asyncio.run(
        seed(
            os.environ["CV_PG_DSN"],
            os.environ["CV_SEED_USERNAME"],
            os.environ["CV_SEED_PASSWORD"],
            os.environ.get("CV_AUTH_PEPPER", ""),
            allow_no_mfa=args.allow_no_mfa,
            role=args.role,
            totp=totp,
            totp_out=args.totp_secret_out,
        )
    )
    if user_id is None and args.totp_secret_out is not None:
        raise SystemExit(
            "the user already exists, so no TOTP was enrolled and "
            f"{args.totp_secret_out} was not written"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
