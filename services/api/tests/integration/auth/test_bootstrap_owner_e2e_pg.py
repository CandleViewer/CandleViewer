"""Integration: the bootstrap-Owner CLI end to end on real Postgres 16 (#4479 C2, SR-023). One
bootstrap per module, read back by three tests. The CLI runs in a child process on a real
pseudo-terminal, through the whole composition, with no recovery-code key; the operator retypes
the phrase. cv-api in process then redeems the printed token (`POST /invites/{token}`, a first
TOTP code, `/confirm`) and signs the Owner in (password, then TOTP); a second CLI run follows.
AC1 reads back the records, the invite, the Owner and PR-B's names (`users.owner_bootstrapped`,
the `auth`/`owner_bootstrapped` event and its gauge) and C2's durable count; AC2 the refusal; AC3
(DC-4479-16) that the token shows once and no token, hash, DSN credential, KEK or password shows
in the CLI's output, in `audit_log` or in cv-api's log lines as rendered. Test-only keys; real
Postgres via testcontainers (the CI integration lane; needs Docker).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import io
import json
import os
import re
import select
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest
import sqlalchemy as sa
from prometheus_client import REGISTRY
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import create_async_engine

from candleviewer.app import create_app
from candleviewer.auth.break_glass_notice import BreakGlassNotice
from candleviewer.auth.invite_service import hash_token
from candleviewer.auth.metrics import auth_owner_bootstrap_events
from candleviewer.auth.totp import generate_code, time_step_for
from candleviewer.observability.logging import configure_logging, reset_logging
from candleviewer.secrets._kek import LoadedKek
from candleviewer.settings import Environment, Settings
from candleviewer.storage.repositories.break_glass_sqlalchemy import SqlAlchemyBreakGlassEvents
from candleviewer.storage.repositories.owner_floor_sqlalchemy import COUNT_OWNERS
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.integration import _refused

pytestmark = pytest.mark.integration
pg_dsn = _refused.pg_dsn  # the module-scoped Postgres 16 at head, on loopback

ATTEMPT, REFUSED, INVITED = (
    "auth.bootstrap_owner_attempt",
    "auth.bootstrap_owner_refused",
    "auth.bootstrap_owner_invited",
)
_ACTOR = ("system:bootstrap", "critical")
_EMAIL = "owner@example.invalid"
_PW = "correct horse battery staple"  # throwaway fixture sign-in value, not a credential
_PHRASE = re.compile(rb"To confirm, type: (bootstrap [^\r\n]+)\r?\n")
_SHOWN = re.compile(r"Invite token \(shown once\): (\S+)")
_ENROL = sa.text("INSERT INTO kek_versions (env, version, kcv) VALUES ('demo', 1, :kcv)")
_STRAYS = sa.text(
    "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity WHERE usename = session_user "
    "AND backend_type = 'client backend' AND pid <> pg_backend_pid()"
)
_RECORDS = sa.text(
    "SELECT action, CAST(outcome AS text), reason, actor_label, CAST(severity AS text) "
    "FROM audit_log WHERE CAST(request_id AS text) = :run ORDER BY id"
)
_INVITES = sa.text(
    "SELECT i.token_hash, i.expires_at - i.created_at, i.invited_by = i.user_id, "
    "CAST(u.status AS text) FROM user_invites i JOIN users u ON u.id = i.user_id "
    "WHERE u.email = :email AND i.role = 'owner'"
)
_GRANT = sa.text(
    "SELECT CAST(outcome AS text), CAST(severity AS text), host(actor_ip), after_state "
    "FROM audit_log WHERE action = 'users.owner_bootstrapped'"
)
_EVENT = sa.text(
    "SELECT CAST(severity AS text), details, resolved_at IS NOT NULL, CAST(resolved_by AS text) "
    "FROM system_events WHERE component = 'auth' AND kind = 'owner_bootstrapped'"
)
_AUDIT_ROWS = sa.text("SELECT CAST(to_jsonb(a) AS text) FROM audit_log a ORDER BY id")


async def _execute(dsn: str, statement: sa.TextClause, **params: Any) -> None:
    engine = create_async_engine(dsn)
    try:
        async with engine.begin() as conn:
            await conn.execute(statement, params)
    finally:
        await engine.dispose()


def _fetch(dsn: str, statement: sa.TextClause, **params: Any) -> list[tuple[Any, ...]]:
    async def fetch() -> list[tuple[Any, ...]]:
        engine = create_async_engine(dsn)
        try:
            async with engine.connect() as conn:
                return [tuple(row) for row in await conn.execute(statement, params)]
        finally:
            await engine.dispose()

    return asyncio.run(fetch())


def _child_env(dsn: str, kek: Path, wal: Path) -> dict[str, str]:
    """What the `bootstrap-owner` compose service passes (#3180): no other `CV_*` variable, so
    no recovery-code key."""
    inherited = {k: v for k, v in os.environ.items() if not k.startswith("CV_")}
    return inherited | {
        "CV_ENVIRONMENT": "demo",
        "CV_PG_DSN": dsn,
        "CV_KEK_SOURCE": "file",
        "CV_KEK_HANDLE": str(kek),
        "CV_AUDIT_WAL_PATH": str(wal),
    }


def _on_a_terminal(env: dict[str, str], cwd: Path) -> tuple[int, str]:
    """`python -m candleviewer.bootstrap_owner --owner owner@example.invalid` on a pseudo-terminal
    whose operator retypes the phrase it shows; its exit status and all it wrote to the terminal.
    The argv is literal (ruff S603): the settings travel in the environment, as in compose."""
    master, slave = os.openpty()
    child = subprocess.Popen(
        [sys.executable, "-m", "candleviewer.bootstrap_owner", "--owner", "owner@example.invalid"],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=env,
        cwd=cwd,
    )
    os.close(slave)
    shown, answered, deadline = bytearray(), False, time.monotonic() + 120
    try:
        while True:
            ready, _, _ = select.select([master], [], [], max(deadline - time.monotonic(), 0))
            if not ready:
                raise AssertionError(f"the CLI did not end: {shown.decode(errors='replace')}")
            try:
                chunk = os.read(master, 4096)
            except OSError:  # EIO: the child has closed the terminal
                break
            if not chunk:
                break
            shown += chunk
            typed = _PHRASE.search(shown)
            if typed is not None and not answered:
                os.write(master, typed.group(1) + b"\n")
                answered = True
        return child.wait(timeout=60), shown.decode(errors="replace")
    finally:
        if child.poll() is None:
            child.kill()
        os.close(master)


def _run_id(shown: str) -> str:
    """The run's id, read as runbook section 4 step 4 says: its `bootstrap_owner.run_ended` line."""
    lines = [json.loads(line) for line in shown.splitlines() if line.startswith("{")]
    [ended] = [line for line in lines if line["event"] == "bootstrap_owner.run_ended"]
    return str(ended["run_id"])


def _code(secret_base32: str, at: datetime) -> str:
    secret = base64.b32decode(secret_base32 + "=" * (-len(secret_base32) % 8))
    return generate_code(secret, time_step_for(at.timestamp()))


async def _redeem(settings: Settings, token: str) -> dict[str, Any]:
    """The Owner's side in an in-process cv-api (its auth and audit modules): the offer, the
    password, the first TOTP code, then a password sign-in and its MFA step a minute later."""
    clock = [datetime.now(UTC).replace(microsecond=0)]
    app = create_app(settings, auth_clock=lambda: clock[0])
    ctx = app.state.app_context
    await ctx.audit.start(ctx)
    await ctx.auth.start(ctx)
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
    dsn = settings.pg_dsn.get_secret_value()
    try:
        async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as c:
            offer = (await c.get(f"/invites/{token}")).json()
            begun = await c.post(f"/invites/{token}", json={"password": _PW})
            assert begun.status_code == 200, begun.text
            method, b32 = begun.json()["method_id"], begun.json()["secret_base32"]
            body = {"method_id": method, "code": _code(b32, clock[0])}
            confirmed = await c.post(f"/invites/{token}/confirm", json=body)
            event = await asyncio.to_thread(_fetch, dsn, _EVENT)
            login = (
                await c.post("/auth/login", json={"identifier": _EMAIL, "password": _PW})
            ).json()
            # A later TOTP step: the code the confirmation took is spent.
            clock[0] += timedelta(seconds=60)
            mfa = {"mfa_token": login["mfa_token"], "method": "totp", "code": _code(b32, clock[0])}
            verified = await c.post("/auth/mfa/verify", json=mfa)
        await ctx.audit.writer.flush(10.0)
    finally:
        await ctx.auth.stop(1.0)
        await ctx.audit.stop(1.0)
    relational = SqlAlchemyRelationalRepository(dsn)  # the reads a cv-api boot makes first
    try:
        await BreakGlassNotice(SqlAlchemyBreakGlassEvents(relational)).refresh()
    finally:
        await relational.dispose()
    return {
        "offer": offer,
        "confirmed": (confirmed.status_code, confirmed.json()),
        "event_at_redemption": event,
        "grants_gauge": REGISTRY.get_sample_value("auth_owner_bootstrap_events"),
        "bootstraps_gauge": REGISTRY.get_sample_value("auth_owner_bootstraps"),
        "login": login["status"],
        "verified": verified.status_code,
    }


@pytest.fixture(scope="module")
def world(pg_dsn: str, tmp_path_factory: pytest.TempPathFactory) -> SimpleNamespace:
    """The bootstrap: the CLI on a pty, the redemption and first sign-in in an in-process cv-api
    whose log lines are captured as they render, then a second CLI run."""
    base = tmp_path_factory.mktemp("bootstrap").resolve()
    kek, wal, lane = base / "kek", base / "audit" / "audit.wal", base / "lane-key"
    raw = os.urandom(32)
    kek.write_bytes(raw)
    kek.chmod(0o400)
    lane.write_text(os.urandom(32).hex(), encoding="ascii")  # ADR-0037: off the audit directory
    lane.chmod(0o400)
    loaded = LoadedKek(bytearray(raw), 1, env_name="demo")
    asyncio.run(_execute(pg_dsn, _ENROL, kcv=loaded.kcv()))  # as cv-api's first boot enrols it
    loaded.close()
    asyncio.run(_execute(pg_dsn, _STRAYS))  # R2c: no other session of the role
    first = _on_a_terminal(_child_env(pg_dsn, kek, wal), base)
    shown = _SHOWN.search(first[1])
    assert shown is not None, first[1]
    keys: dict[str, Any] = {
        "auth_pepper": SecretStr("it-pepper"),
        "CV_AUDIT_LANE_KEY_FILE": str(lane),
    }
    keys |= {f"auth_{name}_hex": SecretStr(byte * 32) for name, byte in (
        ("totp_key", "11"), ("recovery_hmac_key", "22"), ("csrf_key", "33"))}  # fmt: skip
    settings = Settings(
        environment=Environment.DEMO, storage_backend="real", pg_dsn=SecretStr(pg_dsn),
        kek_source="file", kek_handle=str(kek), audit_wal_path=str(wal), **keys,
    )  # fmt: skip
    rendered = io.StringIO()
    with contextlib.redirect_stdout(rendered):  # cv-api's handler writes its lines here
        configure_logging(env="demo", level="debug", fmt="json")
    auth_owner_bootstrap_events.set(0)  # process-wide: count this redemption alone
    try:
        answers = asyncio.run(_redeem(settings, shown.group(1)))
    finally:
        reset_logging()  # its listener writes out what is queued
    asyncio.run(_execute(pg_dsn, _STRAYS))  # what cv-api's modules left pooled (R2c)
    second = _on_a_terminal(_child_env(pg_dsn, kek, wal), base)
    return SimpleNamespace(
        dsn=pg_dsn, kek=raw.hex(), token=shown.group(1), first=first, second=second,
        api_log=rendered.getvalue(), **answers,
    )  # fmt: skip


def test_cli_on_a_pty_then_redeem_makes_an_active_owner(world: SimpleNamespace) -> None:
    status, shown = world.first
    assert status == 0, shown
    assert "Audit: every record reached audit_log." in shown
    assert _fetch(world.dsn, _RECORDS, run=_run_id(shown)) == [
        (ATTEMPT, "success", None, *_ACTOR),
        (INVITED, "success", None, *_ACTOR),
    ]
    # One marked invite, stored as the token's sha256 and valid 4 h; the user is now active.
    expected = (hash_token(world.token), timedelta(hours=4), True, "active")
    assert _fetch(world.dsn, _INVITES, email=_EMAIL) == [expected]
    code, confirmed = world.confirmed
    assert (world.offer["role"], code, confirmed["status"], confirmed["role"]) == (
        "owner", 200, "active", "owner",
    )  # fmt: skip
    assert len(confirmed["recovery_codes"]) == 10
    assert (world.login, world.verified, _fetch(world.dsn, COUNT_OWNERS)) == (
        "mfa_required", 200, [(1,)],
    )  # fmt: skip
    [(outcome, severity, actor_ip, after)] = _fetch(world.dsn, _GRANT)
    assert (outcome, severity, actor_ip, list(after)) == ("success", "critical", "127.0.0.1", [
        "invite_id"
    ])  # fmt: skip
    [(severity, details, resolved, by)] = world.event_at_redemption
    assert (severity, resolved, by) == ("critical", False, None)  # unresolved at the redemption
    assert _fetch(world.dsn, _EVENT) == [(severity, details, True, details["user_id"])]
    assert (world.grants_gauge, world.bootstraps_gauge) == (1.0, 1.0)


def test_a_second_run_after_redemption_refuses_owner_exists(world: SimpleNamespace) -> None:
    status, shown = world.second
    assert status == 17, shown
    assert _fetch(world.dsn, _RECORDS, run=_run_id(shown)) == [
        (ATTEMPT, "success", None, *_ACTOR),
        (REFUSED, "denied", "owner_exists", *_ACTOR),
    ]
    assert "To confirm, type:" not in shown  # refused at the target check, before the TTY
    assert len(_fetch(world.dsn, _INVITES, email=_EMAIL)) == 1  # nothing minted


def test_no_secret_beyond_the_single_print(world: SimpleNamespace) -> None:
    printed = world.first[1] + world.second[1]
    assert printed.count(world.token) == 1
    dsn = urlparse(world.dsn)
    rows = "\n".join(row[0] for row in _fetch(world.dsn, _AUDIT_ROWS))
    others = [hash_token(world.token), f"{dsn.username}:{dsn.password}@", world.kek, _PW]
    assert [secret for secret in others if secret in printed] == []
    assert [secret for secret in (world.token, *others) if secret in rows + world.api_log] == []
    # The capture is live: cv-api's audit lane logged the redemption's records, and the three
    # request lines that carried the token (the offer, the password, the confirmation: httpx's,
    # as uvicorn's access log would be) passed through the same pipeline, redacted (#415).
    assert '"event":"audit.lane.appended"' in world.api_log
    assert world.api_log.count("[redacted:invite-token-shape]") == 3
