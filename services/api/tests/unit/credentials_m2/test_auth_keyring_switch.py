"""#2152 S5b, the switch-over (ADR-0009 Amendment 4, D3, BQ-2, BQ-3, BQ-7): the real-backend
wiring passes the keyring's store through the composition seam, so the first boot opens, imports
or generates the environment's keyring and `SecretsBundle.mfa_keyring` serves MFA; the fake
backend's wiring leaves it refusing. Through that keyring and `MfaService`, an imported keyring
keeps a demo database's enrolments and unused codes working (AC3: the dual-read window), a
generated one reads no old format, and each boot of an imported keyring logs the window's exit
test. In-memory stores, fixed test KEKs and integer-built keys only (C-13.5)."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from structlog.testing import capture_logs

from candleviewer.admin import wiring
from candleviewer.admin.wiring import build_secrets_service
from candleviewer.audit.service import AuditService
from candleviewer.auth.errors import MfaKeyringUnavailable, RecoveryCodeInvalid
from candleviewer.auth.mfa_keyring import KEY_NOT_HELD
from candleviewer.auth.mfa_service import MfaService, _hash_token
from candleviewer.auth.models import MfaMethodKind, MfaVerifyRequest
from candleviewer.auth.totp import generate_code, time_step_for
from candleviewer.secrets import _auth_custody as custody
from candleviewer.secrets.service import SecretsService
from candleviewer.secrets.store import InMemoryAuthKeyStore, InMemoryCredentialStore
from tests.unit.auth.auth_fakes import no_wait
from tests.unit.auth.mfa_fakes import FakeMfaRepository
from tests.unit.credentials_m2._service_fakes import _bound_sources, _ctx, _Src
from tests.unit.credentials_m2._vectors import KEK_V1, AuditLog
from tests.unit.credentials_m2.test_auth_keyring_boot import _ENV_KEYS, AK_R, AK_T, CODE, SEED

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
OTHER_CODE = "-".join(["9QWE"] * 7)  # a second synthetic code (C-13.5)
USER = uuid.UUID(int=0xA11CE)


def _real_backend(monkeypatch: pytest.MonkeyPatch) -> AuditLog:
    """`build_secrets_service`'s own `SecretsService`, with the test KEK in place of the host's
    and a recording sink in place of the audit writer; the sink."""
    defaults = SecretsService.__init__.__kwdefaults__
    assert defaults is not None
    monkeypatch.setitem(defaults, "sources", _bound_sources(_Src(KEK_V1, 1)))
    monkeypatch.setitem(defaults, "harden", lambda: True)
    sink = AuditLog()
    monkeypatch.setattr(wiring, "secrets_audit_sink", lambda _audit: sink)
    return sink


async def _switched(
    monkeypatch: pytest.MonkeyPatch, keyring: InMemoryAuthKeyStore, **settings: Any
) -> wiring.SecretsBundle:
    """M2 as the real backend wires it (the keyring's store passed), booted."""
    _real_backend(monkeypatch)
    store = InMemoryCredentialStore()
    audit = cast(AuditService, object())  # the service the patched sink stands for; never started
    bundle = build_secrets_service(store, store, audit, auth_keys=keyring)
    await bundle.lifecycle.start(_ctx(environment=keyring.env, **settings))
    return bundle


def _legacy_seal(seed: bytes) -> bytes:
    """A seed sealed as the env key sealed it before the switch: no AAD, `local-dev-v1`."""
    nonce = bytes(12)
    return nonce + AESGCM(AK_T).encrypt(nonce, seed, None)


def _legacy_digest(code: str) -> str:
    norm = code.strip().upper().replace("-", "").replace(" ", "").encode()
    return hmac.new(AK_R, norm, hashlib.sha256).hexdigest()


async def _demo_database() -> tuple[FakeMfaRepository, str]:
    """MFA material made under the env keys: a confirmed TOTP method and one unused code."""
    repo = FakeMfaRepository()
    old_ref = "local-dev-v1"  # the env key's `secret_key_ref`, not a secret
    method = await repo.create_pending_method(
        str(USER), secret_enc=_legacy_seal(SEED), secret_key_ref=old_ref, label="old"
    )
    await repo.seed_confirmed(str(method.id), now=NOW - timedelta(days=30))
    codes = (_legacy_digest(CODE), _legacy_digest(OTHER_CODE))
    await repo.replace_recovery_codes(str(USER), code_hashes=codes)
    return repo, str(method.id)


async def _token(repo: FakeMfaRepository) -> str:
    token = uuid.uuid4().hex
    expires = NOW + timedelta(minutes=5)
    await repo.create_challenge(
        str(USER), purpose="login", mfa_token_hash=_hash_token(token), expires_at=expires
    )
    return token


async def test_the_real_backend_wiring_turns_the_keyring_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The switch-over boot: a fresh demo environment generates its keyring at its first boot
    and MFA seals and opens through it."""
    keyring = InMemoryAuthKeyStore("demo")
    bundle = await _switched(monkeypatch, keyring)
    assert {r["origin"] for r in keyring.rows} == {"generated"}
    blob, ref = await bundle.mfa_keyring.seal_totp_seed(SEED, USER)
    assert bytes(await bundle.mfa_keyring.open_totp_seed(blob, ref, USER)) == SEED
    await bundle.lifecycle.stop(1.0)
    assert not await bundle.mfa_keyring.available()  # stop() closes it with the KEK


async def test_the_fake_backend_wiring_leaves_the_keyring_refusing() -> None:
    bundle = build_secrets_service()
    await bundle.lifecycle.start(_ctx(environment="demo"))
    assert not await bundle.mfa_keyring.available()
    with pytest.raises(MfaKeyringUnavailable):
        await bundle.mfa_keyring.seal_totp_seed(SEED, USER)


async def test_the_first_switch_over_boot_keeps_a_demo_database_s_enrolments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC3: both env keys are imported over existing material; the old seal still verifies its
    codes and the old unused code still matches once (the dual-read window); a new code stores
    the user-bound digest."""
    repo, _ = await _demo_database()
    keyring = InMemoryAuthKeyStore("demo", mfa_material=2)
    bundle = await _switched(monkeypatch, keyring, **_ENV_KEYS)
    assert {r["origin"] for r in keyring.rows} == {"imported_env"}
    mfa = MfaService(repo, bundle.mfa_keyring, clock=lambda: NOW, sleep=no_wait)
    code = generate_code(SEED, time_step_for(NOW.timestamp()))
    request = MfaVerifyRequest(mfa_token=await _token(repo), method=MfaMethodKind.TOTP, code=code)
    await mfa.verify(request)
    check = await mfa.check_recovery(await _token(repo), CODE)
    await mfa.complete_recovery(check)
    with pytest.raises(RecoveryCodeInvalid):  # once only
        await mfa.check_recovery(await _token(repo), CODE)
    fresh = (await mfa.regenerate_recovery_codes(str(USER))).recovery_codes[0]
    stored = {r["code_hash"] for r in repo.recovery_codes.values() if r["used_at"] is None}
    bound = (await bundle.mfa_keyring.recovery_code_digests(fresh, USER))[0]
    assert bound in stored and _legacy_digest(fresh) not in stored


async def test_a_generated_keyring_reads_no_old_format(monkeypatch: pytest.MonkeyPatch) -> None:
    """D3: a method sealed under the env key on a generated keyring is a `503`, never "no
    method" and never a code checked under the old format."""
    repo, _ = await _demo_database()
    bundle = await _switched(monkeypatch, InMemoryAuthKeyStore("demo"))
    mfa = MfaService(repo, bundle.mfa_keyring, clock=lambda: NOW, sleep=no_wait)
    code = generate_code(SEED, time_step_for(NOW.timestamp()))
    request = MfaVerifyRequest(mfa_token=await _token(repo), method=MfaMethodKind.TOTP, code=code)
    with pytest.raises(MfaKeyringUnavailable) as refused:
        await mfa.verify(request)
    assert refused.value.reason == KEY_NOT_HELD


@pytest.mark.parametrize(("material", "level"), [(3, "warning"), (0, "info")])
async def test_each_boot_of_an_imported_keyring_logs_the_exit_test(
    monkeypatch: pytest.MonkeyPatch, material: int, level: str
) -> None:
    """BQ-3: what the old formats still serve, at the import boot and every later one; zero is
    the exit test passing."""
    keyring = InMemoryAuthKeyStore("demo", legacy_material=material)
    with capture_logs() as logs:
        await _switched(monkeypatch, keyring, **_ENV_KEYS)  # imports
        await _switched(monkeypatch, keyring, **_ENV_KEYS)  # opens the imported rows
    lines = [e for e in logs if e["event"] == "secrets.auth_keyring_legacy_window"]
    shown = [(e["log_level"], e["material"], e["exit_test_passed"]) for e in lines]
    assert shown == [(level, material, material == 0)] * 2


async def test_a_generated_keyring_has_no_window_to_log(monkeypatch: pytest.MonkeyPatch) -> None:
    keyring = InMemoryAuthKeyStore("demo", legacy_material=3)
    with capture_logs() as logs:
        await _switched(monkeypatch, keyring)
    assert not [e for e in logs if "legacy_window" in e["event"]]


@pytest.mark.parametrize("failure", ["down", "hung"])
async def test_an_exit_test_that_cannot_count_never_stops_the_boot(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """A count that fails, or never answers and is ended by its bound (`_IO_TIMEOUT_S`, zero here
    so no time passes), is logged by its class, and the boot goes on."""
    keyring = InMemoryAuthKeyStore("demo")

    async def down(env: str) -> int:
        raise OSError("store down")

    async def hung(env: str) -> int:
        await asyncio.Event().wait()  # never set: only the count's bound ends it
        return 0

    if failure == "hung":
        monkeypatch.setattr(custody, "_IO_TIMEOUT_S", 0.0)  # the in-memory calls never wait
    monkeypatch.setattr(keyring, "count_legacy_material", down if failure == "down" else hung)
    with capture_logs() as logs:
        async with asyncio.timeout(30):  # fails a lost bound fast
            bundle = await _switched(monkeypatch, keyring, **_ENV_KEYS)
    assert await bundle.mfa_keyring.available()
    (line,) = [e for e in logs if e["event"] == "secrets.auth_keyring_legacy_window_unknown"]
    assert line["error"] == {"down": "OSError", "hung": "TimeoutError"}[failure]


async def test_an_error_the_exit_test_lets_out_is_never_an_audit_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exit test runs after the load's record, outside its `try`: an error it let out (it
    logs its own today) leaves MFA `auth_keyring_unopenable`, never `_audit_unavailable`."""
    keyring = InMemoryAuthKeyStore("demo")
    await _switched(monkeypatch, keyring, **_ENV_KEYS)  # the import boot

    async def raised(store: Any, env_name: str) -> None:
        raise RuntimeError("an exit test defect")

    monkeypatch.setattr(custody, "_legacy_window", raised)
    with capture_logs() as logs:
        bundle = await _switched(monkeypatch, keyring, **_ENV_KEYS)  # a later boot of the rows
    assert not await bundle.mfa_keyring.available()
    (line,) = [e for e in logs if e["event"] == "secrets.auth_keyring_unavailable"]
    assert line["reason"] == "auth_keyring_unopenable"


@pytest.mark.parametrize("boot", ["import", "later"])
async def test_a_boot_cancelled_at_the_exit_test_zeroes_the_keyring(
    monkeypatch: pytest.MonkeyPatch, boot: str
) -> None:
    """At the import boot, and at a later boot of the imported rows (the exit test runs once the
    load is recorded), a cancellation zeroes the opened keyring before it leaves."""
    from candleviewer.secrets import _auth_keyring as ak

    closed: list[object] = []
    real_close = ak.LoadedAuthKeyring.close
    monkeypatch.setattr(ak.LoadedAuthKeyring, "close", lambda ring: closed.append(real_close(ring)))
    keyring = InMemoryAuthKeyStore("demo")
    if boot == "later":
        await _switched(monkeypatch, keyring, **_ENV_KEYS)  # the import boot, which ends well
    assert closed == []

    async def cancelled(env: str) -> int:
        raise asyncio.CancelledError

    monkeypatch.setattr(keyring, "count_legacy_material", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await _switched(monkeypatch, keyring, **_ENV_KEYS)
    assert closed  # the opened keyring was zeroed before the cancellation left
