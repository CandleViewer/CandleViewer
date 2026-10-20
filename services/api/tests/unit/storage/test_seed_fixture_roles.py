"""The fixture seeder's roles and TOTP (E42-X03): the ZAP admin profile's synthetic Manager and
Viewer, each with a real, confirmed TOTP method and no MFA exception."""

from __future__ import annotations

import stat
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from candleviewer.auth.envelope import LOCAL_KEY_REF, TotpEncryptor
from candleviewer.auth.totp import base32_to_secret
from scripts import seed_fixture_user as seeder

_KEY = "ab" * 32  # a test key, not a secret: 32 bytes in hex


@pytest.mark.parametrize("role", ["manager", "viewer"])
def test_an_mfa_less_user_is_refused_unless_it_is_the_owner(role: str) -> None:
    with pytest.raises(SystemExit, match="EX-01 covers the Owner fixture only"):
        seeder.check_options(role, allow_no_mfa=True, totp_out=None)
    seeder.check_options("owner", allow_no_mfa=True, totp_out=None)
    seeder.check_options(role, allow_no_mfa=False, totp_out=Path("totp"))


def test_no_mfa_and_a_totp_secret_contradict_each_other() -> None:
    with pytest.raises(SystemExit, match="contradict"):
        seeder.check_options("owner", allow_no_mfa=True, totp_out=Path("totp"))


@pytest.mark.parametrize("value", [None, "", "zz" * 32, "ab" * 31, "ab" * 33])
def test_the_totp_key_must_be_32_bytes_of_hex_and_is_never_shown(value: str | None) -> None:
    with pytest.raises(SystemExit) as refused:
        seeder.totp_key(value)
    assert value is None or not value or value not in str(refused.value)
    assert seeder.totp_key(_KEY) == bytes.fromhex(_KEY)


def test_the_secret_goes_to_a_new_file_of_mode_0600_only(tmp_path: Path) -> None:
    out = tmp_path / "totp"
    seeder.write_secret(out, "JBSWY3DPEHPK3PXP")
    assert out.read_text(encoding="ascii") == "JBSWY3DPEHPK3PXP"
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        seeder.write_secret(out, "OTHER")
    assert out.read_text(encoding="ascii") == "JBSWY3DPEHPK3PXP"


def _env(monkeypatch: pytest.MonkeyPatch, **extra: str) -> None:
    for name, value in {
        "CV_ENVIRONMENT": "testnet",
        "CV_PG_DSN": "postgresql+asyncpg://x/y",
        "CV_SEED_USERNAME": "zap-viewer",
        "CV_SEED_PASSWORD": "p",
        **extra,
    }.items():
        monkeypatch.setenv(name, value)


def test_main_seeds_the_role_with_totp_under_the_apis_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env(monkeypatch, CV_AUTH_TOTP_KEY_HEX=_KEY)
    seen: dict[str, Any] = {}

    async def fake_seed(*args: object, **kwargs: Any) -> str:
        seen.update(kwargs)
        return "00000000-0000-4000-8000-000000000001"  # a new user

    monkeypatch.setattr(seeder, "seed", fake_seed)
    out = tmp_path / "totp"
    assert seeder.main(["--role", "viewer", "--totp-secret-out", str(out)]) == 0
    assert seen["role"] == "viewer" and seen["totp_out"] == out
    assert seen["allow_no_mfa"] is False
    assert isinstance(seen["totp"], TotpEncryptor) and seen["totp"].key_ref == LOCAL_KEY_REF


def test_main_refuses_totp_without_the_key_and_seeds_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env(monkeypatch)
    monkeypatch.delenv("CV_AUTH_TOTP_KEY_HEX", raising=False)
    called: list[object] = []
    monkeypatch.setattr(seeder, "seed", lambda *a, **k: called.append(a))
    with pytest.raises(SystemExit, match="CV_AUTH_TOTP_KEY_HEX"):
        seeder.main(["--role", "manager", "--totp-secret-out", str(tmp_path / "totp")])
    assert called == []


def test_main_refuses_an_existing_user_when_a_totp_secret_was_asked_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env(monkeypatch, CV_AUTH_TOTP_KEY_HEX=_KEY)

    async def existing(*args: object, **kwargs: Any) -> None:
        return None  # the seeder's answer for a username that is taken

    monkeypatch.setattr(seeder, "seed", existing)
    out = tmp_path / "totp"
    with pytest.raises(SystemExit, match="already exists, so no TOTP was enrolled") as refused:
        seeder.main(["--role", "manager", "--totp-secret-out", str(out)])
    assert str(out) in str(refused.value) and not out.exists()
    assert seeder.main([]) == 0  # an existing Owner, with no secret asked for, is no error


class _Conn:
    def __init__(self, *, existing: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.existing = existing  # the username is taken: the INSERT returns no row

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> Any:
        self.calls.append((str(statement), params or {}))
        conn = self

        class _Result:
            def first(self) -> tuple[str] | None:
                new = len(conn.calls) == 1 and not conn.existing
                return ("00000000-0000-4000-8000-000000000001",) if new else None

        return _Result()


class _Engine:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[_Conn]:
        yield self._conn

    async def dispose(self) -> None:
        return None


async def test_seed_enrols_a_confirmed_totp_whose_secret_only_the_file_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _Conn()
    monkeypatch.setattr(seeder, "create_async_engine", lambda dsn: _Engine(conn))
    encryptor, out = TotpEncryptor(bytes.fromhex(_KEY), key_ref=LOCAL_KEY_REF), tmp_path / "totp"
    user_id = await seeder.seed(
        "dsn", "zap-manager", "pw", role="manager", totp=encryptor, totp_out=out
    )
    assert user_id == "00000000-0000-4000-8000-000000000001"
    role = next(params for sql, params in conn.calls if "INSERT INTO user_roles" in sql)
    assert role == {"username": "zap-manager", "role": "manager"}
    (method,) = [params for sql, params in conn.calls if "INSERT INTO mfa_methods" in sql]
    text = out.read_text(encoding="ascii")
    secret = base32_to_secret(text)
    assert encryptor.decrypt(method["enc"]) == secret and method["ref"] == LOCAL_KEY_REF
    actions = [params["action"] for sql, params in conn.calls if "INSERT INTO audit_log" in sql]
    assert actions == ["users.create", "roles.grant", "auth.mfa_enrolled"]
    values = [value for _, params in conn.calls for value in params.values()]
    assert not any(text in str(value) for value in values)  # the base32 secret is in no column
    assert not any(isinstance(value, bytes) and secret in value for value in values)


async def test_seed_leaves_an_existing_user_as_it_is_and_writes_no_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _Conn(existing=True)
    monkeypatch.setattr(seeder, "create_async_engine", lambda dsn: _Engine(conn))
    encryptor, out = TotpEncryptor(bytes.fromhex(_KEY), key_ref=LOCAL_KEY_REF), tmp_path / "totp"
    user_id = await seeder.seed(
        "dsn", "zap-viewer", "pw", role="viewer", totp=encryptor, totp_out=out
    )
    assert user_id is None and not out.exists()
    assert [sql for sql, _ in conn.calls] == [str(seeder._INSERT)]  # nothing after the INSERT


async def test_seed_without_totp_enrols_no_method(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _Conn()
    monkeypatch.setattr(seeder, "create_async_engine", lambda dsn: _Engine(conn))
    assert await seeder.seed("dsn", "zap-owner", "pw") == "00000000-0000-4000-8000-000000000001"
    assert not any("INSERT INTO mfa_methods" in sql for sql, _ in conn.calls)
    actions = [params["action"] for sql, params in conn.calls if "INSERT INTO audit_log" in sql]
    assert actions == ["users.create", "roles.grant"]
