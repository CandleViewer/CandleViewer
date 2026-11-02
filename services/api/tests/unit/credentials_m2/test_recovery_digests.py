"""Break-glass's live digest session (#2152 S6, BQ-11, AC10, AC11; ADR-0009 Amendment 4
"Break-glass"): `open_recovery_digests` is `prove_kek_possession`'s proof plus, in the same
custody pass and only once every KEK is proven, the environment's keyring pair checked and its
recovery key alone opened into a digest-only session. Every KEK is zeroed before it returns; a
keyring problem is a failed proof with its reason, read before any digest can exist; outside live
it opens nothing. On M2's in-memory stores with the fixed test KEKs (C-13.5)."""

from __future__ import annotations

import asyncio
import copy
import inspect
import pickle
import traceback
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.secrets import RecoveryDigests, open_recovery_digests
from candleviewer.secrets import _auth_keyring as ak
from candleviewer.secrets import _envelope as env
from candleviewer.secrets import service as service_module
from candleviewer.secrets._kek import LoadedKek
from candleviewer.secrets.errors import AuthKeyringUnavailable
from candleviewer.secrets.service import SecretsService
from candleviewer.secrets.store import InMemoryAuthKeyStore, InMemoryCredentialStore
from tests.unit.credentials_m2._service_fakes import _bound_sources, _settings, _Src, _zeroed
from tests.unit.credentials_m2._vectors import KEK_V1, KEK_V2, kek

OWNER = UUID(int=0x0E)
CODE = "-".join(["7K3M"] * 7)  # a synthetic code (C-13.5)


def _enrolled(raw: bytes = KEK_V1, version: int = 1) -> InMemoryCredentialStore:
    """`kek_versions` as live's first boot left it: `raw` enrolled at `version`."""
    store, loaded = InMemoryCredentialStore(), kek(raw, version, "live")
    store.kcvs[("live", version)] = loaded.kcv()
    loaded.close()
    return store


def _live_keyring(raw: bytes = KEK_V1, version: int = 1) -> tuple[InMemoryAuthKeyStore, str]:
    """A generated live keyring's rows, and the digest it gives `CODE` for `OWNER`."""
    rows, ring = ak.generate_keyring(kek(raw, version, "live"))
    keys = InMemoryAuthKeyStore("live")
    keys.rows = rows
    (digest,) = ring.recovery_code_digests(CODE, OWNER)
    ring.close()
    return keys, digest


async def _open(
    keys: Any, kcv: InMemoryCredentialStore, src: _Src, env: str = "live", prev: _Src | None = None
) -> tuple[Any, RecoveryDigests | None]:
    sources = _bound_sources(src, prev)
    return await open_recovery_digests(
        _settings(environment=env), kcv, keys, sources=sources, harden=lambda: True
    )


async def test_a_proven_kek_opens_a_session_of_the_recovery_key_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keys, digest = _live_keyring()
    purposes: list[str] = []
    unwrap = LoadedKek.unwrap_auth_key

    def spied(self: LoadedKek, ref: str, *, key_id: UUID, purpose: str) -> bytearray:
        purposes.append(purpose)
        return unwrap(self, ref, key_id=key_id, purpose=purpose)

    monkeypatch.setattr(LoadedKek, "unwrap_auth_key", spied)
    src = _Src(KEK_V1, 1)
    proof, session = await _open(keys, _enrolled(), src)
    assert (proof.kcv_ok, proof.version) == (True, 1) and session is not None
    assert purposes == ["recovery_hmac"]  # the TOTP key stays wrapped
    assert _zeroed(src)  # every KEK zeroed before the session is handed over
    assert session.recovery_code_digests(CODE, OWNER) == (digest,)
    assert session.recovery_code_digests(CODE, UUID(int=0x0F)) != (digest,)  # it binds the user
    session.close()
    assert session._rd_key == bytearray(32)
    with pytest.raises(AuthKeyringUnavailable, match=r"^auth_keyring_closed$"):
        session.recovery_code_digests(CODE, OWNER)


async def test_a_kek_that_fails_its_proof_reads_no_keyring_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC11: a KEK that is not the enrolled one refuses before any row is read, so no digest
    can be computed. The spy records a read rather than raising: `session()` would swallow it."""
    keys, _ = _live_keyring()
    read: list[str] = []

    async def unread(env: str) -> list[dict[str, Any]]:
        read.append(env)
        return []

    monkeypatch.setattr(keys, "rows_for", unread)
    proof, session = await _open(keys, _enrolled(KEK_V2), _Src(KEK_V1, 1))
    assert read == []  # no keyring row was read before the KEK was proven
    assert (proof.kcv_ok, proof.reason, session) == (False, "kek_mismatch", None)


def _swapped(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [rows[0] | {"dek_ref": rows[1]["dek_ref"]}, rows[1] | {"dek_ref": rows[0]["dek_ref"]}]


#: Each keyring problem fails the proof with its reason (BQ-11: `KEK_UNPROVEN` in the CLI).
PROBLEMS: dict[str, tuple[Any, str]] = {
    "no_rows": (lambda rows: [], "auth_keyring_missing"),
    "swapped": (_swapped, "auth_keyring_mismatch"),
    "imported": (
        lambda rows: [r | {"origin": "imported_env"} for r in rows], "auth_keyring_mismatch"
    ),
}  # fmt: skip


@pytest.mark.parametrize("case", sorted(PROBLEMS))
async def test_a_keyring_problem_is_a_failed_proof_with_its_reason(case: str) -> None:
    keys, _ = _live_keyring()
    change, reason = PROBLEMS[case]
    keys.rows = change(keys.rows)
    src = _Src(KEK_V1, 1)
    proof, session = await _open(keys, _enrolled(), src)
    assert (proof.kcv_ok, proof.reason, session) == (False, reason, None)
    assert _zeroed(src)


async def test_rows_left_under_the_previous_kek_without_it_are_stranded() -> None:
    keys, _ = _live_keyring(KEK_V1, 1)  # still under v1 when v2 is the KEK
    kcv = _enrolled(KEK_V2, 2)
    old = kek(KEK_V1, 1, "live")
    kcv.kcvs[("live", 1)] = old.kcv()
    old.close()
    proof, session = await _open(keys, kcv, _Src(KEK_V2, 2))
    assert (proof.kcv_ok, proof.reason, session) == (False, "auth_keyring_stranded", None)


async def test_rows_left_under_the_previous_kek_open_with_it_supplied() -> None:
    """After a failed re-wrap (BQ-4) the rows stay at v1 under a v2 KEK: a live break-glass run
    given both handles, both KCVs enrolled, opens the v1 ring's recovery key, so digests match."""
    keys, digest = _live_keyring(KEK_V1, 1)
    kcv = _enrolled(KEK_V2, 2)
    old = kek(KEK_V1, 1, "live")
    kcv.kcvs[("live", 1)] = old.kcv()
    old.close()
    src, prev = _Src(KEK_V2, 2), _Src(KEK_V1, 1)
    proof, session = await _open(keys, kcv, src, prev=prev)
    assert (proof.kcv_ok, proof.version, proof.reason) == (True, 2, None) and session is not None
    assert session.recovery_code_digests(CODE, OWNER) == (digest,)
    assert _zeroed(src) and _zeroed(prev)  # both KEKs zeroed before the session is handed over
    session.close()


async def test_a_keyring_store_that_fails_is_a_failed_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keys, _ = _live_keyring()

    async def down(env: str) -> list[dict[str, Any]]:
        raise OSError("store down")

    monkeypatch.setattr(keys, "rows_for", down)
    proof, session = await _open(keys, _enrolled(), _Src(KEK_V1, 1))
    assert (proof.kcv_ok, proof.reason, session) == (
        False, "auth_keyring_store_unavailable", None,
    )  # fmt: skip


@pytest.mark.parametrize("env", ["demo", "testnet"])
async def test_outside_live_no_session_is_opened_and_no_kek_loaded(env: str) -> None:
    src = _Src(KEK_V1, 1)
    with pytest.raises(ValueError, match="live only"):
        await _open(InMemoryAuthKeyStore(env), _enrolled(), src, env)
    assert src.handed == []


async def test_the_session_shows_no_key_and_cannot_be_copied() -> None:
    keys, _ = _live_keyring()
    _, session = await _open(keys, _enrolled(), _Src(KEK_V1, 1))
    assert session is not None and repr(session) == str(session) == "***"
    for op in (pickle.dumps, copy.copy):
        with pytest.raises(TypeError):
            op(session)
    with pytest.raises(TypeError, match="may not be subclassed"):
        type("Evil", (RecoveryDigests,), {"__module__": "candleviewer.auth.evil"})
    session.close()


def test_a_key_of_the_wrong_shape_is_zeroed_and_refused() -> None:
    key = bytearray(b"\x07" * 31)
    with pytest.raises(ValueError, match="recovery key shape"):
        RecoveryDigests(key)
    assert key == bytearray(31)


def test_an_imported_pair_never_opens_a_digest_session() -> None:
    """Live never imports (D3), and even where an import is legal the session refuses an imported
    pair before any key is unwrapped: no old-format digest is ever this session's."""
    rows, ring = ak.generate_keyring(kek(KEK_V1, 1, "demo"))
    ring.close()
    imported = [r | {"origin": "imported_env"} for r in rows]
    with pytest.raises(AuthKeyringUnavailable, match=r"^auth_keyring_mismatch$"):
        ak.recovery_digests(kek(KEK_V1, 1, "demo"), imported)


async def test_a_cancelled_custody_pass_closes_the_session_it_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cancellation after the session opened (here, at the KEKs' close) zeroes its key before
    it propagates: no session outlives a pass that did not return it."""
    keys, _ = _live_keyring()
    made: list[RecoveryDigests] = []
    real, close = service_module.recovery_digests, SecretsService._close

    def kept(*args: Any, **kwargs: Any) -> RecoveryDigests:
        made.append(session := real(*args, **kwargs))
        return session

    def cancelled(*keks: LoadedKek) -> None:
        close(*keks)
        raise asyncio.CancelledError

    monkeypatch.setattr(service_module, "recovery_digests", kept)
    monkeypatch.setattr(SecretsService, "_close", staticmethod(cancelled))
    with pytest.raises(asyncio.CancelledError):
        await _open(keys, _enrolled(), _Src(KEK_V1, 1))
    assert len(made) == 1 and made[0]._rd_key == bytearray(32)
    with pytest.raises(AuthKeyringUnavailable, match=r"^auth_keyring_closed$"):
        made[0].recovery_code_digests(CODE, OWNER)


async def test_no_key_or_code_reaches_a_log_or_a_failure_s_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC13 for break-glass: the custody pass logs no key, and a digest that fails (a code over
    the cap) leaves neither the code nor the key in any frame of its traceback."""
    made: list[bytearray] = []
    new_dek = env.new_dek

    def captured() -> bytearray:
        made.append(key := new_dek())
        return key

    monkeypatch.setattr(env, "new_dek", captured)  # the keys generate_keyring makes
    keys, _ = _live_keyring()
    with capture_logs() as logs:
        _, session = await _open(keys, _enrolled(), _Src(KEK_V1, 1))
    assert session is not None
    code = "Q" * 600
    with pytest.raises(ValueError) as failed:
        session.recovery_code_digests(code, OWNER)
    here = inspect.currentframe()
    frames = [f for f, _ in traceback.walk_tb(failed.tb) if f is not here]
    shown = [repr(v) for f in frames for v in f.f_locals.values()] + [repr(logs)]
    secrets = [code, code.encode().hex(), *(bytes(k).hex() for k in made), KEK_V1.hex()]
    assert [s for s in secrets for text in shown if s in text] == []
    session.close()
