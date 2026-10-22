"""Audit export signing key core (#889 S5; ADR-0039 decisions 1, 2 and 4; SR-E42-15, AD-I16).

The RFC 8032 §7.1 vectors (public test data) go through the one signing path; every other key is
built from integers. No seed reaches a repr, a pickle, a traceback's frames or a log record, and
no M2 frame of a refusal holds the DEK, which the caller holds and zeroes, as S6 will.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import logging
import pickle
import traceback
import weakref
from base64 import b64encode
from collections.abc import Callable, Iterator
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NoReturn
from unittest.mock import MagicMock

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from hypothesis import given, seed, settings
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.secrets import _envelope as env
from candleviewer.secrets import _export_key as xk
from candleviewer.secrets.errors import CredentialUnavailable
from tests.unit.credentials_m2._helpers import _Spy
from tests.unit.credentials_m2._vectors import RFC8032

DEK, SEED, OTHER = bytes(range(200, 232)), bytes(range(1, 33)), bytes(range(33, 65))
DIGEST = hashlib.sha256(b"abc").digest()
#: The bytes a signature over DIGEST covers, written out independently of the module.
SIGNED = b"cv.audit.export.v1:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
#: The secrets package: the frames whose locals must never hold the DEK.
M2_DIR = str(Path(xk.__file__).parent)
#: The DEK as `bytes`, which every call refuses: the caller must hold a `bytearray` it can zero.
DEK_AS_BYTES: Any = DEK
#: The three calls that open a seal, each given the DEK, the row and the process environment.
OPENERS: dict[str, Callable[[Any, xk.SealedExportKey, str], object]] = {
    "_open_seed": lambda dek, k, e: xk._open_seed(dek, k, env_name=e),
    "check_key": lambda dek, k, e: xk.check_key(dek, k, env_name=e),
    "sign_export": lambda dek, k, e: xk.sign_export(dek, k, DIGEST, env_name=e),
}


def _forms(raw: bytes) -> tuple[str, ...]:
    """`raw` as a render could show it: hex, upper-case hex, a bytes repr's body and base64."""
    return raw.hex(), raw.hex().upper(), repr(raw)[2:-1], b64encode(raw).decode()


SEED_FORMS, DEK_FORMS = _forms(SEED), _forms(DEK)


@pytest.fixture
def dek() -> Iterator[bytearray]:
    """The row's DEK as S6 will hold it: a `bytearray` its caller zeroes in `finally`."""
    held = bytearray(DEK)
    try:
        yield held
    finally:
        env.zero(held)


def _key(raw: bytes = SEED, **binding: Any) -> xk.SealedExportKey:
    args = {"env_name": "demo", "version": 1, **binding}
    return xk.seal_seed(bytearray(DEK), bytearray(raw), **args)


def _resealed(key: xk.SealedExportKey, dek: bytes | bytearray = DEK) -> xk.SealedExportKey:
    """`key`'s row holding SEED, sealed under `dek` and the row's own binding."""
    aad = env.export_seed_aad(key.env_name, key.key_id, key.public_key)
    return replace(key, sealed_seed=env.seal(dek, SEED, aad))


def _throw(fault: BaseException, *held: object) -> NoReturn:
    raise fault  # this frame keeps `held`, the seed, until the frames are cleared


def _shown(exc: BaseException) -> str:
    """`exc` as a locals-capturing renderer (`dict_tracebacks`, a crash reporter) shows it."""
    return "".join(traceback.TracebackException.from_exception(exc, capture_locals=True).format())


def _m2_locals(*raised: BaseException) -> str:
    """The locals of every M2 frame in these tracebacks, rendered. The test's own frames are left
    out: like S6's, they hold the DEK until their `finally` zeroes it."""
    frames = [f for exc in raised for f, _ in traceback.walk_tb(exc.__traceback__)]
    return "".join(repr(f.f_locals) for f in frames if f.f_code.co_filename.startswith(M2_DIR))


def _refused(call: Callable[[], object], code: str) -> None:
    """`call` refuses as `code`, typed with nothing chained; no frame shows the seed, and no M2
    frame the DEK."""
    with pytest.raises(CredentialUnavailable) as info:
        call()
    shown, m2 = _shown(info.value), _m2_locals(info.value)  # rendered before the search
    assert (str(info.value), info.value.__context__, info.value.__cause__) == (code, None, None)
    assert not [s for s in SEED_FORMS if s in shown] and not [d for d in DEK_FORMS if d in m2]


def _probes(
    mp: pytest.MonkeyPatch, fault: BaseException | None = None, at: str = ""
) -> tuple[list[weakref.ref[Any]], set[str]]:
    """Each private key object becomes a probe over a real one, weakly referenced to tell whether
    it outlives its call, recording every name read on it; `fault` strikes the name `at` from a
    frame that holds the seed."""
    made: list[weakref.ref[Any]] = []
    used: set[str] = set()

    class Probe:
        def __init__(self, data: bytes) -> None:
            self.data, self.real = data, Ed25519PrivateKey.from_private_bytes(data)
            made.append(weakref.ref(self))

        def __getattr__(self, name: str) -> Any:
            used.add(name)
            if fault is not None and name == at:
                _throw(fault, self.data)
            return getattr(self.real, name)

    mp.setattr(xk, "Ed25519PrivateKey", SimpleNamespace(from_private_bytes=Probe))
    return made, used


@pytest.mark.parametrize("name", sorted(RFC8032))
def test_rfc8032_seed_gives_the_vector_public_key_and_signature(
    name: str, monkeypatch: pytest.MonkeyPatch, dek: bytearray
) -> None:
    """Through the one signing path, with the vector's message in place of the export message."""
    seed_hex, public_hex, message_hex, signature_hex = RFC8032[name]
    key = _key(bytes.fromhex(seed_hex))
    monkeypatch.setattr(xk, "export_message", lambda _: bytes.fromhex(message_hex))
    assert key.public_key.hex() == public_hex
    assert xk.sign_export(dek, key, DIGEST, env_name="demo").hex() == signature_hex


def test_key_id_fingerprint_and_signed_bytes_follow_the_contract(dek: bytearray) -> None:
    """22 `AuditExportResult`: the key id and fingerprint hash the raw public key, and a signature
    covers `cv.audit.export.v1:` and the digest's lowercase hex, verified with the public key."""
    key = _key(version=12)
    fingerprint = hashlib.sha256(key.public_key).hexdigest()
    assert xk.fingerprint(key.public_key) == fingerprint
    assert key.key_id == "cv-audit-export-v12:" + fingerprint[:16]
    assert xk.generate(dek, env_name="demo", version=7).key_id.startswith("cv-audit-export-v7:")
    assert xk.export_message(DIGEST) == xk.export_message(bytearray(DIGEST)) == SIGNED
    signature = xk.sign_export(dek, key, DIGEST, env_name="demo")
    Ed25519PublicKey.from_public_bytes(key.public_key).verify(signature, SIGNED)


#: Not exactly 32 bytes in a `bytes` or `bytearray`: each refused before any key operation.
NOT_DIGESTS = {
    "31": DIGEST[:31], "33": DIGEST + b"\0", "empty": b"", "bytearray_33": bytearray(33),
    "hex": DIGEST.hex(), "memoryview": memoryview(DIGEST), "list": list(DIGEST), "none": None,
    "bytes_subclass": type("Sub", (bytes,), {})(DIGEST),
}  # fmt: skip


@pytest.mark.parametrize("case", sorted(NOT_DIGESTS))
def test_digest_is_refused_before_any_key_operation(
    case: str, monkeypatch: pytest.MonkeyPatch, dek: bytearray
) -> None:
    key, spy = _key(), _Spy(monkeypatch)
    monkeypatch.setattr(xk, "Ed25519PrivateKey", None)  # a key operation would fail otherwise
    with pytest.raises(TypeError, match=r"^export digest: exactly 32 bytes$") as info:
        xk.sign_export(dek, key, NOT_DIGESTS[case], env_name="demo")
    m2 = _m2_locals(info.value)
    assert spy.bufs == [] and not [d for d in DEK_FORMS if d in m2]  # nothing opened or kept


def test_seal_opens_to_its_seed_after_a_constant_time_key_check(
    monkeypatch: pytest.MonkeyPatch, dek: bytearray
) -> None:
    key, spy = _key(), MagicMock(wraps=hmac.compare_digest)
    monkeypatch.setattr(hmac, "compare_digest", spy)
    assert xk._open_seed(dek, key, env_name="demo") == SEED
    spy.assert_called_once_with(key.public_key, key.public_key)


#: Seals that must not open, from the good row and DEK: one moved to another environment, a row
#: naming another environment than the process's (either way round), a changed key id or public
#: key, a tampered seal, a wrong DEK, a `bytes` DEK, and DEKs of 16 or 24 bytes (whose AES would
#: open seals made under them) or 33.
NOT_OPENING: dict[
    str, Callable[[xk.SealedExportKey, bytearray], tuple[Any, xk.SealedExportKey, str]]
] = {
    "env": lambda k, d: (d, replace(k, env_name="testnet"), "testnet"),
    "row_env_not_process": lambda k, d: (d, replace(k, env_name="testnet"), "demo"),
    "process_env_not_row": lambda k, d: (d, k, "testnet"),
    "key_id": lambda k, d: (d, replace(k, key_id=k.key_id.replace("-v1:", "-v2:")), "demo"),
    "public_key": lambda k, d: (d, replace(k, public_key=_key(OTHER).public_key), "demo"),
    "tampered": lambda k, d: (d, replace(k, sealed_seed=k.sealed_seed[::-1]), "demo"),
    "wrong_dek": lambda k, d: (bytearray(range(32)), k, "demo"),
    "bytes_dek": lambda k, d: (DEK_AS_BYTES, k, "demo"),
    "dek_16": lambda k, d: (d[:16], _resealed(k, d[:16]), "demo"),
    "dek_24": lambda k, d: (d[:24], _resealed(k, d[:24]), "demo"),
    "dek_33": lambda k, d: (d + b"\0", k, "demo"),
}


@pytest.mark.parametrize("opener", sorted(OPENERS))
@pytest.mark.parametrize("case", sorted(NOT_OPENING))
def test_seal_opens_only_under_its_own_binding(case: str, opener: str, dek: bytearray) -> None:
    held, row, env_name = NOT_OPENING[case](_key(), dek)
    _refused(lambda: OPENERS[opener](held, row, env_name), "credential_unavailable")


@pytest.mark.parametrize("opener", sorted(OPENERS))
def test_row_whose_public_key_is_not_its_seeds_is_refused(
    opener: str, monkeypatch: pytest.MonkeyPatch, dek: bytearray
) -> None:
    """Decision 4: at boot (`check_key`) and before every signature, the opened seed zeroed."""
    row, spy = _resealed(_key(OTHER)), _Spy(monkeypatch)
    _refused(lambda: OPENERS[opener](dek, row, "demo"), "export_key_mismatch")
    assert spy.all_zero()


def test_seal_aad_golden() -> None:
    """No KEK version: the DEK's own wrap binds it, so a KEK rotation never touches the seal."""
    public = bytes(range(32))
    assert env.export_seed_aad("live", "cv-audit-export-v3:" + "a" * 16, public) == (
        b"\x00\x11cv-export-seed-v1\x00\x04live\x00\x23cv-audit-export-v3:" + b"a" * 16
        + b"\x00\x20" + public
    )  # fmt: skip


#: Any other input: the AAD's environment and key length, the key id's version and public key,
#: the fingerprint's key, the seed's length, and a seal or a generation for an unknown environment
#: or under a DEK that is not a 32-byte `bytearray`.
REFUSED: list[Callable[[], object]] = [
    lambda: env.export_seed_aad("prod", "k", bytes(32)),
    lambda: env.export_seed_aad("live", "k", bytes(31)),
    lambda: xk.derive_key_id(0, bytes(32)), lambda: xk.derive_key_id(True, bytes(32)),
    lambda: xk.derive_key_id(1, bytes(33)), lambda: xk.fingerprint(bytes(31)),
    lambda: xk.derive_public_key(bytearray(31)), lambda: _key(env_name="prod"),
    lambda: xk.seal_seed(bytearray(DEK[:16]), bytearray(SEED), env_name="demo", version=1),
    lambda: xk.seal_seed(bytearray(DEK[:24]), bytearray(SEED), env_name="demo", version=1),
    lambda: xk.seal_seed(bytearray(DEK + b"\0"), bytearray(SEED), env_name="demo", version=1),
    lambda: xk.seal_seed(DEK_AS_BYTES, bytearray(SEED), env_name="demo", version=1),
    lambda: xk.generate(DEK_AS_BYTES, env_name="demo", version=1),
    lambda: xk.generate(bytearray(DEK[:16]), env_name="demo", version=1),
]  # fmt: skip


@pytest.mark.parametrize("call", REFUSED)
def test_formats_refuse_any_other_input(call: Callable[[], object]) -> None:
    with pytest.raises(ValueError):
        call()


def test_each_generation_draws_a_fresh_seed(dek: bytearray) -> None:
    keys = [xk.generate(dek, env_name="live", version=1) for _ in range(2)]
    seeds = {bytes(xk._open_seed(dek, k, env_name="live")) for k in keys}
    assert len(seeds) == 2 and {len(s) for s in seeds} == {32}


@pytest.mark.parametrize("fails", [False, True], ids=["sealed", "failed"])
def test_generate_zeroes_its_seed_and_leaves_no_copy_in_a_frame(
    fails: bool, monkeypatch: pytest.MonkeyPatch, dek: bytearray
) -> None:
    drawn, fault = bytearray(SEED), RuntimeError("boom")
    monkeypatch.setattr(xk, "new_seed", lambda: drawn)
    _, used = _probes(monkeypatch, fault if fails else None, "public_key")  # a frame with a copy
    with pytest.raises(RuntimeError) if fails else contextlib.nullcontext():
        xk.generate(dek, env_name="demo", version=1)
    shown, m2 = _shown(fault), _m2_locals(fault)
    assert not any(drawn) and not [s for s in SEED_FORMS if s in shown]
    assert not [d for d in DEK_FORMS if d in m2]
    assert used == {"public_key"}  # the seal's and its proof's derivations; no private bytes


def test_generate_drops_the_dek_when_no_seed_can_be_drawn(
    monkeypatch: pytest.MonkeyPatch, dek: bytearray
) -> None:
    monkeypatch.setattr(xk, "new_seed", lambda: _throw(OSError("no entropy")))
    with pytest.raises(OSError, match=r"^no entropy$") as info:
        xk.generate(dek, env_name="demo", version=1)
    m2 = _m2_locals(info.value)
    assert not [d for d in DEK_FORMS if d in m2]


def test_generate_returns_no_seal_that_does_not_open_to_its_key(
    monkeypatch: pytest.MonkeyPatch, dek: bytearray
) -> None:
    """As `_auth_keyring.wrap_verified` proves a wrap: here the seal holds another seed."""
    real = env.seal
    monkeypatch.setattr(env, "seal", lambda held, _seed, aad: real(held, OTHER, aad))
    _refused(lambda: xk.generate(dek, env_name="demo", version=1), "export_key_mismatch")


#: The only names a successful call may read on a private key object: never `private_bytes`.
READS = {"check_key": {"public_key"}, "sign_export": {"public_key", "sign"}}


@pytest.mark.parametrize("path", sorted(READS))
def test_success_zeroes_the_seed_keeps_no_key_object_and_reads_no_private_bytes(
    path: str, monkeypatch: pytest.MonkeyPatch, dek: bytearray
) -> None:
    (made, used), spy = _probes(monkeypatch), _Spy(monkeypatch)
    OPENERS[path](dek, _key(), "demo")
    assert spy.all_zero() and used == READS[path]
    assert made and not [r for r in made if r() is not None]


#: A fault inside a key operation: the name it strikes, the call it goes through and the caller's
#: code (`None`: the fault itself, an interrupt, which is not the key's doing and propagates).
FAULTS: dict[str, tuple[Callable[[], BaseException], str, str, str | None]] = {
    "error_in_sign": (RuntimeError, "sign", "sign_export", "signing_failed"),
    "interrupt_in_sign": (KeyboardInterrupt, "sign", "sign_export", None),
    **{
        f"error_in_open/{o}": (RuntimeError, "public_key", o, "credential_unavailable")
        for o in OPENERS
    },
    **{f"interrupt_in_open/{o}": (KeyboardInterrupt, "public_key", o, None) for o in OPENERS},
}


@pytest.mark.parametrize("case", sorted(FAULTS))
def test_failed_key_operation_leaves_no_seed_behind(
    case: str, monkeypatch: pytest.MonkeyPatch, dek: bytearray
) -> None:
    """Typed and unchained, the opened seed zeroed, no key object kept, and neither the error nor
    the fault (as a hook would keep it), rendered with its frames' locals, shows the seed, nor any
    of their M2 frames the DEK."""
    make_fault, at, opener, code = FAULTS[case]
    key, fault = _key(), make_fault()
    (made, _), spy = _probes(monkeypatch, fault, at), _Spy(monkeypatch)
    with pytest.raises((CredentialUnavailable, KeyboardInterrupt)) as info:
        OPENERS[opener](dek, key, "demo")
    if code is None:
        assert info.value is fault
    else:
        assert (type(info.value), str(info.value)) == (CredentialUnavailable, code)
        assert info.value.__context__ is None and info.value.__cause__ is None
    assert spy.all_zero() and made and not [r for r in made if r() is not None]
    shown, m2 = _shown(info.value) + _shown(fault), _m2_locals(info.value, fault)
    assert not [s for s in SEED_FORMS if s in shown] and not [d for d in DEK_FORMS if d in m2]


def test_sealed_key_is_frozen_and_its_repr_hides_the_seal() -> None:
    key = _key()
    shown, seal = repr(key), key.sealed_seed
    assert not [f for f in ("sealed_seed", repr(seal), seal.hex()) if f in shown]
    with pytest.raises(FrozenInstanceError):
        key.env_name = "live"  # type: ignore[misc]  # frozen: this assignment must be refused


def test_no_seed_or_dek_in_a_repr_pickle_or_log_record(
    caplog: pytest.LogCaptureFixture, dek: bytearray
) -> None:
    """AD-I16: every flow, refusals included, under stdlib and structlog capture; the DEK is
    searched for outside the test's own frames, which hold it until it is zeroed."""
    caplog.set_level(logging.DEBUG)
    raised: list[BaseException] = []
    with capture_logs() as logs:
        key = _key()
        signature = xk.sign_export(dek, key, DIGEST, env_name="demo")
        public = [repr(key), str(key), repr(pickle.dumps(key)), signature.hex()]
        for row in (_resealed(_key(OTHER)), replace(key, env_name="testnet")):
            with pytest.raises(CredentialUnavailable) as info:
                xk.sign_export(dek, row, DIGEST, env_name="demo")
            raised.append(info.value)
    logged = [*(r.getMessage() for r in caplog.records), repr(logs)]
    text = "\n".join([*public, *map(_shown, raised), *logged])
    plain = "\n".join([*public, _m2_locals(*raised), *logged])
    assert not [s for s in SEED_FORMS if s in text] and not [d for d in DEK_FORMS if d in plain]


@seed(889)
@settings(max_examples=20, deadline=None)
@given(digest=st.binary(min_size=32, max_size=32))
def test_any_digest_signs_and_verifies_with_the_public_key(digest: bytes) -> None:
    key, dek = _key(), bytearray(DEK)
    try:
        signature = xk.sign_export(dek, key, digest, env_name="demo")
    finally:
        env.zero(dek)
    public = Ed25519PublicKey.from_public_bytes(key.public_key)
    public.verify(signature, b"cv.audit.export.v1:" + digest.hex().encode())
