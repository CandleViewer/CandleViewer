"""Auth SQL repositories with a fake unit of work (no docker: real-DB round
trip lives in tests/integration/auth, not run locally)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa
from pydantic import SecretStr

from candleviewer.app import build_auth_service
from candleviewer.auth.mfa_repository import MfaRepository
from candleviewer.settings import Environment, Settings
from candleviewer.storage.repositories import mfa_sqlalchemy
from candleviewer.storage.repositories.mfa_sqlalchemy import SqlAlchemyMfaRepository
from candleviewer.storage.repositories.users_sqlalchemy import SqlAlchemyUserRepository

_NOW = datetime(2026, 10, 1, tzinfo=UTC)


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def all(self) -> list[Any]:
        return self._rows


class _Rel:
    def __init__(self, rows: list[Any]) -> None:
        self.rows, self.calls = rows, []

    @asynccontextmanager
    async def unit_of_work(self) -> Any:
        async def execute(stmt: Any, params: dict[str, Any]) -> _Result:
            self.calls.append((str(stmt), params))
            return _Result(self.rows)

        async def commit() -> None:
            self.calls.append(("COMMIT", {}))

        async def rollback() -> None:
            self.calls.append(("ROLLBACK", {}))

        yield SimpleNamespace(
            session=SimpleNamespace(execute=execute), commit=commit, rollback=rollback
        )


def _row(**m: Any) -> Any:
    return SimpleNamespace(_mapping=m)


async def test_login_failure_is_one_atomic_conditional_update() -> None:
    rel = _Rel([_row(locked_until=_NOW)])
    repo = SqlAlchemyUserRepository(rel, dict, clock=lambda: _NOW)  # type: ignore[arg-type]  # fake
    got = await repo.record_login_failure(
        "u", lockout_threshold=5, lock_duration=timedelta(minutes=15), now=_NOW
    )
    sql, params = rel.calls[0]
    assert "failed_login_count + 1" in sql and "RETURNING" in sql
    assert params["threshold"] == 5 and got == _NOW


async def test_find_by_identifier_unknown_returns_none_and_is_parameterised() -> None:
    rel = _Rel([])
    repo = SqlAlchemyUserRepository(rel, dict, clock=lambda: _NOW)  # type: ignore[arg-type]  # fake
    assert await repo.find_by_identifier("x' OR 1=1 --") is None
    assert rel.calls[0][1] == {"ident": "x' OR 1=1 --"}


async def test_find_by_identifier_maps_json_params_and_methods() -> None:
    fields: dict[str, Any] = {
        "id": "i",
        "username": "u",
        "email": "e",
        "password_hash": "h",
        "password_algo_params": '{"m": 1}',
        "status": "active",
        "mfa_required": True,
        "failed_login_count": 0,
        "locked_until": None,
        "mfa_methods": ["totp"],
    }
    rel = _Rel([_row(**fields)])
    repo = SqlAlchemyUserRepository(rel, dict, clock=lambda: _NOW)  # type: ignore[arg-type]  # fake
    got = await repo.find_by_identifier("u")
    assert got["password_algo_params"] == {"m": 1} and got["mfa_methods"] == ("totp",)


class _Answers(_Rel):
    """`_Rel` whose statements answer in turn, one row list each, then no rows."""

    def __init__(self, *answers: list[Any]) -> None:
        super().__init__([])
        self.answers = list(answers)

    @asynccontextmanager
    async def unit_of_work(self) -> Any:
        async with super().unit_of_work() as uow:
            record = uow.session.execute

            async def execute(stmt: Any, params: dict[str, Any]) -> _Result:
                await record(stmt, params)
                return _Result(self.answers.pop(0) if self.answers else [])

            uow.session.execute = execute
            yield uow


async def test_complete_recovery_spends_satisfies_and_revokes_in_one_unit_of_work() -> None:
    """#2344: the code and the challenge are each won once, only as the user's own, and every
    method of the user is revoked in the same unit of work."""
    rel = _Answers([_row(x=1)], [_row(x=1)])
    repo = SqlAlchemyMfaRepository(rel, dict, dict)  # type: ignore[arg-type]  # fake
    assert await repo.complete_recovery("u", challenge_id="ch", code_id="c", now=_NOW) is True
    (use, p1), (satisfy, p2), (revoke, p3), commit = rel.calls
    assert use.startswith("UPDATE recovery_codes SET used_at = :now")
    assert "user_id = CAST(:u AS uuid) AND used_at IS NULL RETURNING 1" in use
    assert "user_id = CAST(:u AS uuid) AND satisfied_at IS NULL RETURNING 1" in satisfy
    assert revoke == (
        "UPDATE mfa_methods SET revoked_at = :now WHERE user_id = CAST(:u AS uuid) "
        "AND revoked_at IS NULL"
    )
    assert (p1, p2, p3) == (
        {"id": "c", "u": "u", "now": _NOW},
        {"id": "ch", "u": "u", "now": _NOW},
        {"u": "u", "now": _NOW},
    )
    assert commit == ("COMMIT", {})  # one commit, after every statement


@pytest.mark.parametrize("answers", [([],), ([_row(x=1)], [])], ids=["code_lost", "challenge_lost"])
async def test_complete_recovery_rolls_back_a_lost_race_and_spends_nothing(
    answers: tuple[list[Any], ...],
) -> None:
    rel = _Answers(*answers)
    repo = SqlAlchemyMfaRepository(rel, dict, dict)  # type: ignore[arg-type]  # fake
    assert await repo.complete_recovery("u", challenge_id="ch", code_id="c", now=_NOW) is False
    statements = [statement for statement, _ in rel.calls]
    assert statements[len(answers) :] == ["ROLLBACK"]  # nothing after the lost update commits


async def test_time_step_replay_rejected_when_no_row_updated() -> None:
    rel = _Rel([])
    repo = SqlAlchemyMfaRepository(rel, dict, dict)  # type: ignore[arg-type]  # fake
    assert await repo.record_time_step("m", time_step=5) is False
    assert "last_accepted_time_step < :step" in rel.calls[0][0]


async def test_complete_enrollment_claims_revokes_and_swaps_codes_in_one_unit_of_work() -> None:
    """#2295: the old method and codes stop working at the instant the new ones start."""
    rel = _Rel([_row(id="m", kind="totp")])
    repo = SqlAlchemyMfaRepository(rel, dict, dict)  # type: ignore[arg-type]  # fake
    got = await repo.complete_enrollment(
        "u", method_id="m", time_step=7, now=_NOW, code_hashes=("h1", "h2")
    )
    sql = [statement for statement, _ in rel.calls]
    assert got == {"id": "m", "kind": "totp"}
    for rule in ("m.confirmed_at IS NULL", "m.last_accepted_time_step IS NULL", "NOT EXISTS"):
        assert rule in sql[0] and sql[0].startswith("UPDATE mfa_methods m SET confirmed_at")
    assert rel.calls[0][1] == {"id": "m", "u": "u", "now": _NOW, "step": 7}
    assert "id <> CAST(:id AS uuid) AND kind = 'totp' AND revoked_at IS NULL" in sql[1]
    assert sql[2].startswith("DELETE FROM recovery_codes")
    assert [params["h"] for _, params in rel.calls[3:5]] == ["h1", "h2"]
    assert sql[5:] == ["COMMIT"]  # one commit, after every statement


async def test_complete_enrollment_rolls_back_when_the_method_is_no_longer_confirmable() -> None:
    rel = _Rel([])
    repo = SqlAlchemyMfaRepository(rel, dict, dict)  # type: ignore[arg-type]  # fake
    got = await repo.complete_enrollment("u", method_id="m", time_step=7, now=_NOW, code_hashes=())
    assert got is None
    assert [statement for statement, _ in rel.calls][1:] == ["ROLLBACK"]


def test_every_statement_that_confirms_a_method_requires_it_to_be_confirmable() -> None:
    """#2295 DoR: no `UPDATE ... SET confirmed_at` by id alone survives (`confirm_method` is
    gone), so nothing can re-activate a method a recovery sign-in un-confirmed. The one
    confirming statement is the claim, guarded by the confirmable-method predicate."""
    statements = [v.text for v in vars(mfa_sqlalchemy).values() if isinstance(v, sa.TextClause)]
    confirming = [text for text in statements if "SET confirmed_at = :now" in text]
    assert confirming == [mfa_sqlalchemy._CLAIM.text]
    assert mfa_sqlalchemy._CONFIRMABLE in confirming[0]
    assert not hasattr(SqlAlchemyMfaRepository, "confirm_method")
    assert not hasattr(MfaRepository, "confirm_method")


async def test_pending_lookup_supersede_and_mfa_required_are_parameterised() -> None:
    rel = _Rel([])
    mfa = SqlAlchemyMfaRepository(rel, dict, dict)  # type: ignore[arg-type]  # fake
    users = SqlAlchemyUserRepository(rel, dict, clock=lambda: _NOW)  # type: ignore[arg-type]  # fake
    assert await mfa.find_pending_method("m", "u") is None
    await mfa.supersede_pending_methods("u", now=_NOW)
    await users.set_mfa_required("u")
    (find, p1), (supersede, p2), (require, p3) = [c for c in rel.calls if c[0] != "COMMIT"]
    assert "m.last_accepted_time_step IS NULL" in find and p1 == {"id": "m", "u": "u"}
    assert "confirmed_at IS NULL AND revoked_at IS NULL" in supersede
    assert p2 == {"u": "u", "now": _NOW}
    assert "SET mfa_required = true" in require and p3 == {"id": "u"}


def test_build_auth_service_fake_backend_is_scaffold() -> None:
    assert build_auth_service(Settings()).is_active is False


def _real_settings(**over: Any) -> Settings:
    from pydantic import SecretStr

    base: dict[str, Any] = {
        "storage_backend": "real",
        "auth_totp_key_hex": SecretStr("11" * 32),
        "auth_recovery_hmac_key_hex": SecretStr("22" * 32),
        "auth_pepper": SecretStr("pepper"),
    }
    return Settings(**{**base, **over})


def test_build_auth_service_real_backend_wires_repositories() -> None:
    svc = build_auth_service(_real_settings())
    assert svc._repository is not None and svc._mfa_repository is not None
    assert svc._session_repository is not None


def test_build_auth_service_live_without_keys_refuses() -> None:
    with pytest.raises(ValueError, match="CV_AUTH_TOTP_KEY_HEX"):
        build_auth_service(
            Settings(
                storage_backend="real",
                environment=Environment.LIVE,
                questdb_pg_password=SecretStr("not-the-dev-default"),
            )
        )


@pytest.mark.parametrize("env", ["live", "demo"])
@pytest.mark.parametrize("allow_no_mfa", [False, True])
def test_seeder_refuses_outside_testnet(env: str, allow_no_mfa: bool) -> None:
    from scripts.seed_fixture_user import check_environment

    with pytest.raises(SystemExit, match=r"C-2\.11"):
        check_environment(env, allow_no_mfa=allow_no_mfa)


def test_seeder_accepts_testnet() -> None:
    from scripts.seed_fixture_user import check_environment

    check_environment("testnet")
    check_environment("testnet", allow_no_mfa=True)


@pytest.mark.parametrize("env", ["live", "demo"])
def test_seeder_main_allow_no_mfa_refused_outside_testnet(
    env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import seed_fixture_user

    monkeypatch.setenv("CV_ENVIRONMENT", env)
    called: list[object] = []
    monkeypatch.setattr(seed_fixture_user, "seed", lambda *a, **k: called.append(a))
    with pytest.raises(SystemExit, match="MFA-less"):
        seed_fixture_user.main(["--allow-no-mfa"])
    assert called == []


def test_seeder_main_default_seeds_with_mfa_required(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import seed_fixture_user

    for k, v in {
        "CV_ENVIRONMENT": "testnet",
        "CV_PG_DSN": "postgresql+asyncpg://x/y",
        "CV_SEED_USERNAME": "u",
        "CV_SEED_PASSWORD": "p",
    }.items():
        monkeypatch.setenv(k, v)
    seen: dict[str, object] = {}

    async def fake_seed(*args: object, allow_no_mfa: bool = False) -> None:
        seen["allow_no_mfa"] = allow_no_mfa

    monkeypatch.setattr(seed_fixture_user, "seed", fake_seed)
    assert seed_fixture_user.main([]) == 0
    assert seen == {"allow_no_mfa": False}


@pytest.mark.parametrize("env", [Environment.DEMO, Environment.TESTNET])
def test_build_auth_service_fake_backend_scaffold_all_inactive(env: Environment) -> None:
    svc = build_auth_service(Settings(environment=env))
    assert svc.is_active is False and svc.mfa_is_active is False
    assert svc.sessions_is_active is False
    assert svc._repository is None and svc._mfa_repository is None
    assert svc._session_repository is None


def test_build_auth_service_live_fake_backend_with_keys_still_scaffold() -> None:
    """Live + fake backend: keys are validated (fail closed), and the result
    stays an inert scaffold, never a half-wired service."""
    from pydantic import SecretStr

    svc = build_auth_service(
        Settings(
            environment=Environment.LIVE,
            auth_totp_key_hex=SecretStr("11" * 32),
            auth_recovery_hmac_key_hex=SecretStr("22" * 32),
            auth_pepper=SecretStr("pepper"),
        )
    )
    assert svc.is_active is False and svc._repository is None


def test_build_auth_service_live_fake_backend_empty_pepper_refuses() -> None:
    from pydantic import SecretStr

    with pytest.raises(ValueError, match="CV_AUTH_PEPPER"):
        build_auth_service(
            Settings(
                environment=Environment.LIVE,
                auth_totp_key_hex=SecretStr("11" * 32),
                auth_recovery_hmac_key_hex=SecretStr("22" * 32),
            )
        )


def test_build_auth_service_non_hex_key_refuses() -> None:
    from pydantic import SecretStr

    with pytest.raises(ValueError, match="hex-encoded"):
        build_auth_service(_real_settings(auth_recovery_hmac_key_hex=SecretStr("zz" * 32)))


def test_identity_and_audit_wiring_follow_storage_backend() -> None:
    from candleviewer.app import _build_audit, build_identity_provider

    assert build_identity_provider(Settings()) is None
    assert _build_audit(Settings())._repository is None
    assert build_identity_provider(_real_settings()) is not None
    assert _build_audit(_real_settings())._repository is not None


def test_build_auth_service_live_fake_backend_still_refuses() -> None:
    with pytest.raises(ValueError, match="CV_AUTH_TOTP_KEY_HEX"):
        build_auth_service(Settings(environment=Environment.LIVE))


def test_build_auth_service_live_empty_pepper_refuses() -> None:
    from pydantic import SecretStr

    with pytest.raises(ValueError, match="CV_AUTH_PEPPER"):
        build_auth_service(
            Settings(
                storage_backend="real",
                environment=Environment.LIVE,
                questdb_pg_password=SecretStr("not-the-dev-default"),
                auth_totp_key_hex=SecretStr("11" * 32),
                auth_recovery_hmac_key_hex=SecretStr("22" * 32),
            )
        )


def test_build_auth_service_wrong_key_length_refuses() -> None:
    from pydantic import SecretStr

    with pytest.raises(ValueError, match="32 bytes"):
        build_auth_service(_real_settings(auth_totp_key_hex=SecretStr("11" * 16)))


def test_build_auth_service_non_live_real_missing_keys_refuses() -> None:
    with pytest.raises(ValueError, match="CV_AUTH_TOTP_KEY_HEX"):
        build_auth_service(Settings(storage_backend="real"))


def test_build_auth_service_non_live_real_empty_pepper_refuses() -> None:
    from pydantic import SecretStr

    with pytest.raises(ValueError, match="CV_AUTH_PEPPER"):
        build_auth_service(_real_settings(auth_pepper=SecretStr("")))


def test_build_csrf_codec_dedicated_key_required_on_real_backend_and_rotatable() -> None:
    """#2090 (SR-041): `auth_csrf_key_hex` is loaded like the other auth keys."""
    from pydantic import SecretStr

    from candleviewer.app import build_csrf_codec
    from candleviewer.auth.csrf import CsrfCodec, CsrfVerdict

    with pytest.raises(ValueError, match="CV_AUTH_CSRF_KEY_HEX"):
        build_csrf_codec(_real_settings())
    with pytest.raises(ValueError, match="CV_AUTH_CSRF_KEY_HEX"):
        build_csrf_codec(_real_settings(auth_csrf_key_hex=SecretStr("aa" * 16)))
    old = bytes.fromhex("aa" * 32)
    codec = build_csrf_codec(
        _real_settings(
            auth_csrf_key_hex=SecretStr("bb" * 32),
            auth_csrf_previous_key_hex=SecretStr(old.hex()),
        )
    )
    assert codec.verify(CsrfCodec(old).issue("s"), "s") is CsrfVerdict.OK  # previous verifies
    # fake backend, no key configured: a process-local key, never a constant
    a = build_csrf_codec(Settings())
    b = build_csrf_codec(Settings())
    assert a.verify(b.issue("s"), "s") is CsrfVerdict.WRONG_SESSION


def test_build_csrf_codec_refuses_reusing_the_totp_or_recovery_key() -> None:
    """Review #2238: the CSRF key must be dedicated (contract), checked at startup."""
    from pydantic import SecretStr

    from candleviewer.app import build_csrf_codec

    for reused in ("11" * 32, "22" * 32):  # _real_settings' TOTP / recovery keys
        with pytest.raises(ValueError, match="dedicated"):
            build_csrf_codec(_real_settings(auth_csrf_key_hex=SecretStr(reused)))
        with pytest.raises(ValueError, match="dedicated"):
            build_csrf_codec(
                _real_settings(
                    auth_csrf_key_hex=SecretStr("cc" * 32),
                    auth_csrf_previous_key_hex=SecretStr(reused),
                )
            )
