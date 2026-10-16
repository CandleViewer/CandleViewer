"""#2086 part (a): the server test clock (`candleviewer.auth.testnet_clock`).

Auth time is UTC plus the offset in `CV_TEST_CLOCK_FILE`, read on every call, so rewriting
one file moves the server's session and step-up decisions (Q2: no HTTP surface). The clock
exists only behind the keyless-testnet gate (Q1).
"""

from __future__ import annotations

import errno
import os
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest
from pydantic import SecretStr
from structlog.testing import capture_logs

from candleviewer import app as app_module
from candleviewer.api.csrf import CsrfMiddleware
from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.audit.models import AuditEmission, ExchangeEnv, Severity
from candleviewer.auth import testnet_clock
from candleviewer.auth.errors import SessionIdleLocked, StepUpRequired
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import MfaEnrollRequest, MfaMethodKind, UserRecord
from candleviewer.auth.service import AuthService
from candleviewer.auth.testnet_clock import OffsetFileClock, OffsetFileError, build_test_clock
from candleviewer.auth.totp import base32_to_secret, generate_code, time_step_for
from candleviewer.settings import Environment, Settings

from .auth_fakes import FakeUserRepository, make_user
from .mfa_fakes import FakeMfaRepository
from .session_fakes import FakeSessionRepository

if TYPE_CHECKING:
    from collections.abc import Callable

    from candleviewer.app import AppContext

_T0 = datetime(2026, 10, 15, 12, 0, 0, tzinfo=UTC)
_PASSWORD = "correct horse battery staple"
_REFUSED = ("", "abc", "1e3", "nan", "inf", "1,5", "1.", ".5", "0x10", "1.1234567", "1234567890")


@pytest.fixture
def offset_file(tmp_path: Path) -> Path:
    return tmp_path / "offset"


@pytest.fixture
def clock(offset_file: Path) -> OffsetFileClock:
    return OffsetFileClock(offset_file, now=lambda: _T0)


def _gated(offset_file: Path) -> Settings:
    return Settings(
        environment=Environment.TESTNET,
        test_clock=True,
        test_clock_file=str(offset_file),
        bybit_api_key=None,
        bybit_api_secret=None,
    )


def _set_offset(offset_file: Path, content: str) -> None:
    """What the e2e harness does: write a temp file, then rename it over the offset file."""
    staged = offset_file.with_suffix(".tmp")
    staged.write_bytes(content.encode("utf-8"))
    staged.replace(offset_file)


def test_offset_clock_without_a_file_is_utc(clock: OffsetFileClock) -> None:
    assert clock() == _T0


@pytest.mark.parametrize(
    ("content", "offset"),
    [
        ("301", timedelta(seconds=301)),
        ("-5.5\n", timedelta(seconds=-5.5)),
        (" +43200.000001 ", timedelta(seconds=43200, microseconds=1)),
        ("-999999999.999999", -timedelta(seconds=999999999, microseconds=999999)),
    ],
)
def test_offset_clock_adds_the_file_offset_to_utc(
    clock: OffsetFileClock, offset_file: Path, content: str, offset: timedelta
) -> None:
    _set_offset(offset_file, content)

    assert clock() == _T0 + offset


def test_offset_clock_rereads_the_file_on_every_call(
    clock: OffsetFileClock, offset_file: Path
) -> None:
    _set_offset(offset_file, "60")
    first = clock()
    _set_offset(offset_file, "-60")

    assert (first, clock()) == (_T0 + timedelta(minutes=1), _T0 - timedelta(minutes=1))


# 3, U+200B (zero-width space), 01: must never decode away to 301 (#2728).
@pytest.mark.parametrize("content", [*_REFUSED, "٣٠١", "1" + " " * 40, "3\u200b01"])
def test_offset_clock_refuses_content_that_is_not_bounded_decimal_seconds(
    clock: OffsetFileClock, offset_file: Path, content: str
) -> None:
    _set_offset(offset_file, content)

    with pytest.raises(OffsetFileError, match="CV_TEST_CLOCK_FILE"):
        clock()


def test_offset_clock_accepts_a_32_byte_file(clock: OffsetFileClock, offset_file: Path) -> None:
    _set_offset(offset_file, "301".ljust(32))

    assert clock() == _T0 + timedelta(seconds=301)


def test_offset_clock_refuses_a_33_byte_file(clock: OffsetFileClock, offset_file: Path) -> None:
    _set_offset(offset_file, "301".ljust(33))

    with pytest.raises(OffsetFileError, match="signed decimal seconds"):
        clock()


def test_offset_clock_with_an_unreadable_path_raises_instead_of_reading_as_no_offset(
    tmp_path: Path,
) -> None:
    """#2728: only a missing file means no offset; `ENOTDIR` (a file where a directory is
    expected) must fail the auth decision, never run it on real UTC."""
    (tmp_path / "file").write_bytes(b"0")
    clock = OffsetFileClock(tmp_path / "file" / "offset", now=lambda: _T0)

    with pytest.raises(NotADirectoryError):
        clock()


def test_offset_clock_never_follows_a_symlink(
    clock: OffsetFileClock, offset_file: Path, tmp_path: Path
) -> None:
    (tmp_path / "target").write_bytes(b"301")
    offset_file.symlink_to(tmp_path / "target")

    with pytest.raises(OSError, match=re.escape(os.strerror(errno.ELOOP))):
        clock()


def test_offset_clock_refuses_a_directory(clock: OffsetFileClock, offset_file: Path) -> None:
    offset_file.mkdir()

    with pytest.raises(OffsetFileError, match="regular file"):
        clock()


def test_offset_clock_opens_without_blocking_or_following_a_symlink(
    clock: OffsetFileClock, offset_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#2728: a FIFO or device node at the path must not stall the event loop in `open()`.
    Asserted on the flags: a live FIFO would hang a regressed suite instead of failing it."""
    _set_offset(offset_file, "1")
    flags: list[int] = []
    real_open = os.open

    def _spy(path: Path, open_flags: int, *args: int) -> int:
        flags.append(open_flags)
        return real_open(path, open_flags, *args)

    monkeypatch.setattr(os, "open", _spy)
    clock()

    assert [f & (os.O_NONBLOCK | os.O_NOFOLLOW) for f in flags] == [os.O_NONBLOCK | os.O_NOFOLLOW]


def test_build_test_clock_is_none_and_silent_by_default() -> None:
    with capture_logs() as logs:
        built = build_test_clock(Settings())

    assert (built, logs) == (None, [])


def test_build_test_clock_logs_the_boot_line_without_reading_the_file(offset_file: Path) -> None:
    _set_offset(offset_file, "not seconds")

    with capture_logs() as logs:
        built = build_test_clock(_gated(offset_file))

    assert [(e["event"], e["log_level"], e["environment"], e["clock_file"]) for e in logs] == [
        ("auth.test_clock_enabled", "warning", "testnet", str(offset_file))
    ]
    with pytest.raises(OffsetFileError):  # read on first use, never at boot
        cast("OffsetFileClock", built)()


@pytest.mark.parametrize(
    "fields",
    [
        {"environment": Environment.LIVE},
        {"environment": Environment.DEMO},
        {"environment": Environment.TESTNET, "bybit_api_key": SecretStr("k")},
        {"environment": Environment.TESTNET, "bybit_api_secret": SecretStr("s")},
        {"environment": Environment.TESTNET, "test_clock_file": None},
    ],
    ids=["live", "demo", "api-key", "api-secret", "no-file"],
)
def test_build_test_clock_refuses_settings_that_skipped_validation(
    fields: dict[str, Any],
) -> None:
    settings = Settings.model_construct(**{"test_clock": True, "test_clock_file": "/x", **fields})

    with pytest.raises(RuntimeError, match="CV_TEST_CLOCK"):
        build_test_clock(settings)


def _create_app(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, **kwargs: Any
) -> tuple[list[Callable[[], datetime] | None], object]:
    """`create_app()`: the clocks `build_auth_service` received, and CsrfMiddleware's clock."""
    seen: list[Callable[[], datetime] | None] = []
    real = app_module.build_auth_service

    def _spy(settings: Settings, *, clock: Callable[[], datetime] | None = None) -> AuthService:
        seen.append(clock)
        return real(settings, clock=clock)

    monkeypatch.setattr(app_module, "build_auth_service", _spy)
    app = app_module.create_app(settings, **kwargs)
    (csrf_clock,) = [
        m.kwargs["clock"] for m in app.user_middleware if cast(object, m.cls) is CsrfMiddleware
    ]
    return seen, csrf_clock


def test_create_app_feeds_the_test_clock_to_auth_and_csrf(
    offset_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen, csrf_clock = _create_app(monkeypatch, _gated(offset_file))

    assert len(seen) == 1
    assert isinstance(seen[0], OffsetFileClock)
    assert csrf_clock is seen[0]


def test_create_app_by_default_never_builds_the_test_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _never(*_args: object, **_kwargs: object) -> OffsetFileClock:
        raise AssertionError("the test clock was built outside its gate")

    monkeypatch.setattr(testnet_clock, "OffsetFileClock", _never)

    seen, csrf_clock = _create_app(monkeypatch, Settings())

    assert seen == [None]
    assert not isinstance(csrf_clock, OffsetFileClock)


def test_create_app_injected_auth_clock_wins_over_the_test_clock(
    offset_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#2728: an injected `auth_clock` takes precedence; the gated test clock is never built."""

    def _never(*_args: object, **_kwargs: object) -> OffsetFileClock:
        raise AssertionError("the test clock was built over an injected auth clock")

    def injected() -> datetime:
        return _T0

    monkeypatch.setattr(testnet_clock, "OffsetFileClock", _never)

    seen, csrf_clock = _create_app(monkeypatch, _gated(offset_file), auth_clock=injected)

    assert seen == [injected]
    assert csrf_clock is injected


class _AuditStub:
    """`ctx.audit` as `_LazyAuditEmitter` reads it: `is_active`, then `writer.emit`."""

    def __init__(self, *, active: bool = True) -> None:
        self.is_active = active
        self.writer = self
        self.records: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, action: str, **fields: Any) -> None:
        self.records.append((action, fields))


def _ctx(settings: Settings, audit: _AuditStub) -> AppContext:
    return cast("AppContext", SimpleNamespace(settings=settings, audit=audit))


async def test_boot_audit_records_the_test_clock_as_a_system_warning(offset_file: Path) -> None:
    audit = _AuditStub()

    await app_module.audit_test_clock_boot(_ctx(_gated(offset_file), audit))

    assert audit.records == [
        (
            "system.config.test_clock_enabled",
            {
                "actor_label": "system:test-clock",
                "object_kind": "settings",
                "object_id": "CV_TEST_CLOCK",
                "severity": "warning",
                "env": "testnet",
                "after_state": {"test_clock_file": str(offset_file)},
            },
        )
    ]


async def test_boot_audit_record_is_a_registered_valid_emission(offset_file: Path) -> None:
    """The real writer refuses an unregistered action, and builds an `AuditEmission`."""
    audit = _AuditStub()
    await app_module.audit_test_clock_boot(_ctx(_gated(offset_file), audit))
    ((action, fields),) = audit.records

    emission = AuditEmission(record_id=uuid.uuid4(), action=action, event_ts=_T0, **fields)

    assert action in AUDIT_ACTIONS
    assert (emission.severity, emission.env) == (Severity.WARNING, ExchangeEnv.TESTNET)


async def test_boot_audit_writes_nothing_while_the_clock_is_off() -> None:
    audit = _AuditStub()

    await app_module.audit_test_clock_boot(_ctx(Settings(), audit))

    assert audit.records == []


async def test_boot_audit_writes_nothing_without_an_audit_store(offset_file: Path) -> None:
    """The fake backend has no audit writer: the boot warning is the only record."""
    audit = _AuditStub(active=False)

    await app_module.audit_test_clock_boot(_ctx(_gated(offset_file), audit))

    assert audit.records == []


async def _auth(clock: OffsetFileClock, password_hash: str) -> tuple[AuthService, UserRecord]:
    """The `AuthService` the composition root builds, on fakes, with one injected clock."""
    users = FakeUserRepository()
    user = make_user(password_hash=password_hash)
    users.add(user)
    auth = AuthService(
        users,
        pepper="pepper",
        mfa_repository=FakeMfaRepository(),
        totp_encryption_key=b"t" * 32,
        recovery_code_hmac_key=b"r" * 32,
        session_repository=FakeSessionRepository(),
        clock=clock,
    )
    await auth.start(cast("AppContext", None))
    return auth, user


async def test_test_clock_offset_moves_the_session_idle_lock(
    clock: OffsetFileClock, offset_file: Path
) -> None:
    auth, user = await _auth(clock, "-")
    session_id = str((await auth.sessions.mint(str(user.id))).session_id)
    _set_offset(offset_file, "899")
    await auth.sessions.require_active(session_id)

    _set_offset(offset_file, "900")

    with pytest.raises(SessionIdleLocked):
        await auth.sessions.require_active(session_id)


async def test_test_clock_offset_moves_the_step_up_grace_expiry(
    clock: OffsetFileClock, offset_file: Path
) -> None:
    fast = {"m": 1024, "t": 1, "p": 1}
    auth, user = await _auth(clock, await Hasher(pepper="pepper").hash(_PASSWORD, fast))
    uid = str(user.id)
    enrolled = await auth.mfa.enroll(
        uid, MfaEnrollRequest(method=MfaMethodKind.TOTP), account_name="o"
    )
    seed, step = base32_to_secret(enrolled.secret_base32 or ""), time_step_for(_T0.timestamp())
    confirm = generate_code(seed, step - 1)
    await auth.mfa.confirm_enrollment(uid, method_id=str(enrolled.method_id), code=confirm)
    session_id = str((await auth.sessions.mint(uid)).session_id)
    await auth.step_up.step_up(uid, session_id, "users", generate_code(seed, step), _PASSWORD)
    _set_offset(offset_file, "299")
    await auth.step_up.require_elevation(session_id, "users")

    _set_offset(offset_file, "300")

    with pytest.raises(StepUpRequired):
        await auth.step_up.require_elevation(session_id, "users")
    await auth.stop(0)
