"""Auth keyring core (#2152 S3): formats, bindings, seals, digests, close, provisioning, no leaks.

Synthetic vectors only, built from integers (C-13.5); never a real key. Not wired until S5b.
"""

from __future__ import annotations

import copy
import hmac
import logging
import pickle
import re
import traceback
from base64 import b32encode, b64encode
from collections.abc import Callable
from hashlib import sha256
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from hypothesis import example, given, settings
from hypothesis import strategies as st
from pydantic import SecretStr
from structlog.testing import capture_logs

from candleviewer.auth.recovery_codes import hash_recovery_code, normalize_recovery_code
from candleviewer.secrets import _auth_keyring as ak
from candleviewer.secrets import _envelope as env
from candleviewer.secrets._kek import LoadedKek
from candleviewer.secrets.errors import (
    AuthKeyEnvForbidden,
    AuthKeyringUnavailable,
    AuthSealInvalid,
    KekUnavailable,
    SecretsError,
)
from tests.unit.credentials_m2._vectors import KEK_V1, KEK_V2, kek

AK_T, AK_R = bytes(range(140, 172)), bytes(range(172, 204))  # the two auth keys under test
SEED = bytes(range(1, 21))  # a 20-byte TOTP seed
CODE, NORM = "-".join(["7K3M"] * 7), b"7K3M" * 7  # grouped like a generated recovery code
RID, OTHER, ALICE, BOB = (UUID(int=n) for n in (0xA1, 0xA2, 0xA11CE, 0xB0B))
IOTA = "\N{GREEK SMALL LETTER IOTA WITH DIALYTIKA AND TONOS}"  # upper() makes it 6 UTF-8 bytes
Rows = list[dict[str, Any]]
Call = Callable[[ak.LoadedAuthKeyring, bytes, str], object]


def use_known_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """The M2 test seam: `generate_keyring` draws AK_T, then AK_R (then fresh bytes)."""
    pool = [bytearray(AK_T), bytearray(AK_R)]
    real = env.new_dek
    monkeypatch.setattr(env, "new_dek", lambda: pool.pop(0) if pool else real())


@pytest.fixture(autouse=True)
def known_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    use_known_keys(monkeypatch)


def generated() -> ak.LoadedAuthKeyring:
    return ak.generate_keyring(kek())[1]


def imported() -> ak.LoadedAuthKeyring:
    return ak.import_keyring(kek(), SecretStr(AK_T.hex()), SecretStr(AK_R.hex()))[1]


def _opened(holder: LoadedKek, rows: Rows) -> list[bytes]:
    return [bytes(holder.unwrap_auth_key(r["dek_ref"], key_id=r["id"], purpose=r["purpose"]))
            for r in rows]  # fmt: skip


def _unwrap(ref: str) -> Callable[[], object]:
    return lambda: kek().unwrap_auth_key(ref, key_id=RID, purpose="totp_seal")


def test_auth_formats_golden() -> None:
    ref = kek().wrap_auth_key(bytearray(AK_T), key_id=RID, purpose="totp_seal")
    assert re.fullmatch(r"ak1:[0-9a-f]{120}", ref) and AK_T.hex() not in ref
    assert kek().unwrap_auth_key(ref, key_id=RID, purpose="totp_seal") == AK_T
    assert env.akey_aad("live", "totp_seal", RID, 7) == (
        b"\x00\x0acv-akey-v1\x00\x04live\x00\x09totp_seal\x00\x10" + RID.bytes + b"\x00\x017"
    )
    assert env.totp_aad("demo", ALICE) == b"\x00\x0acv-totp-v1\x00\x04demo\x00\x10" + ALICE.bytes
    assert env.rc_preimage(ALICE, b"A") == b"\x00\x08cv-rc-v2\x00\x10" + ALICE.bytes + b"\x00\x01A"


@pytest.mark.parametrize(
    "call",
    [
        lambda: env.akey_aad("prod", "totp_seal", RID, 1),
        lambda: env.akey_aad("live", "dek", RID, 1),
        lambda: env.akey_aad("live", "totp_seal", RID, 0),
        lambda: env.akey_aad("live", "totp_seal", RID, True),
        lambda: env.totp_aad("prod", ALICE),
        lambda: kek().wrap_auth_key(bytearray(31), key_id=RID, purpose="totp_seal"),
        _unwrap("v2:" + "ab" * 60),  # an api_keys wrap
        _unwrap("ak1:" + "AB" * 60),
        _unwrap("ak1:" + "ab" * 59),
        _unwrap("ak1:" + "ab" * 60 + "\n"),
        lambda: generated().recovery_code_digests("A" * 513, ALICE),  # one byte over the cap
        lambda: generated().seal_totp_seed(b"", ALICE),
        lambda: ak.import_keyring(kek(), SecretStr(AK_T.hex()[2:]), SecretStr(AK_R.hex())),
        lambda: ak.import_keyring(kek(), SecretStr(AK_T.hex()), SecretStr("zz")),
    ],
)
def test_auth_formats_refuse_any_other_input_or_shape(call: Callable[[], object]) -> None:
    with pytest.raises(ValueError):
        call()


#: Open with exactly one AAD field changed, under the same KEK bytes: (version, env, id, purpose).
SWAPS = {
    "env": (1, "testnet", RID, "totp_seal"),
    "purpose": (1, "demo", RID, "recovery_hmac"),
    "id": (1, "demo", OTHER, "totp_seal"),
    "kek_version": (2, "demo", RID, "totp_seal"),
}


@pytest.mark.parametrize("field", sorted(SWAPS))
def test_wrap_opens_only_under_its_own_binding(field: str) -> None:
    ref = kek().wrap_auth_key(bytearray(AK_T), key_id=RID, purpose="totp_seal")
    version, env_name, key_id, purpose = SWAPS[field]
    with pytest.raises(InvalidTag):
        kek(KEK_V1, version, env_name).unwrap_auth_key(ref, key_id=key_id, purpose=purpose)


def test_totp_seal_round_trips_bound_to_environment_and_user() -> None:
    records, ring = ak.generate_keyring(kek())
    blob, ref = ring.seal_totp_seed(SEED, ALICE)
    assert ref == f"akey:{records[0]['id']}" and len(blob) == 12 + len(SEED) + 16
    assert ring.open_totp_seed(blob, ref, ALICE) == SEED
    aad = b"\x00\x0acv-totp-v1\x00\x04demo\x00\x10" + ALICE.bytes  # independent of `env`
    assert AESGCM(AK_T).decrypt(blob[:12], blob[12:], aad) == SEED


def _closed(ring: ak.LoadedAuthKeyring) -> ak.LoadedAuthKeyring:
    ring.close()
    return ring


SEAL, NOT_HELD, CLOSED = "auth_seal_invalid", "auth_key_not_held", "auth_keyring_closed"
_ERRORS = {SEAL: AuthSealInvalid, NOT_HELD: AuthKeyringUnavailable, CLOSED: AuthKeyringUnavailable}
TOO_LONG = "recovery code too long"
_METHODS = {"seal_totp_seed", "open_totp_seed", "recovery_code_digests"}
#: Each refused call on a ring that sealed SEED for ALICE as `(b, f)`, and its message: a moved or
#: tampered seal is a wrong code (AC9), a key not held here is never "no method" (AC6).
REFUSED: dict[str, tuple[Call, str]] = {
    "moved_seal": (lambda r, b, f: r.open_totp_seed(b, f, BOB), SEAL),
    "tampered": (lambda r, b, f: r.open_totp_seed(b[:-1] + bytes([b[-1] ^ 1]), f, ALICE), SEAL),
    "truncated": (lambda r, b, f: r.open_totp_seed(b[:27], f, ALICE), SEAL),
    "other_key_ref": (lambda r, b, f: r.open_totp_seed(b, f"akey:{OTHER}", ALICE), NOT_HELD),
    "legacy_ref": (lambda r, b, f: r.open_totp_seed(b, "local-dev-v1", ALICE), NOT_HELD),
    "empty_ref": (lambda r, b, f: r.open_totp_seed(b, "", ALICE), NOT_HELD),
    "empty_seed": (lambda r, b, f: r.seal_totp_seed(b"", ALICE), "empty TOTP seed"),
    "over_long_code": (lambda r, b, f: r.recovery_code_digests(CODE * 19, ALICE), TOO_LONG),
    "closed_seal": (lambda r, b, f: _closed(r).seal_totp_seed(SEED, ALICE), CLOSED),
    "closed_open": (lambda r, b, f: _closed(r).open_totp_seed(b, f, ALICE), CLOSED),
    "closed_digests": (lambda r, b, f: _closed(r).recovery_code_digests(CODE, ALICE), CLOSED),
}


@pytest.mark.parametrize("case", sorted(REFUSED))
def test_refused_call_raises_its_error_and_leaves_no_secret(case: str) -> None:
    """C-12.6: no frame keeps a key, nothing is chained, a locals render shows no secret."""
    call, message = REFUSED[case]
    ring = generated()
    blob, ref = ring.seal_totp_seed(SEED, ALICE)
    exc = _raised(lambda: call(ring, blob, ref))
    held, shown = {id(ring._totp_key), id(ring._rc_key)}, _with_locals(exc)
    frames = [f for f, _ in traceback.walk_tb(exc.__traceback__)]
    assert (type(exc), str(exc)) == (_ERRORS.get(message, ValueError), message)
    assert not [n for f in frames for n, v in f.f_locals.items() if id(v) in held]
    assert {f.f_code.co_name for f in frames} & _METHODS and exc.__context__ is None
    assert not [s for s in SENTINELS if s in shown]


def test_imported_keyring_reads_the_env_keys_old_formats() -> None:
    ring, old = imported(), bytes(12) + AESGCM(AK_T).encrypt(bytes(12), SEED, None)
    assert ring.open_totp_seed(old, "local-dev-v1", ALICE) == SEED
    v2, unbound = ring.recovery_code_digests(CODE, ALICE)
    assert unbound == hmac.new(AK_R, NORM, sha256).hexdigest() != v2


def test_generated_keyring_digest_is_the_bound_v2_golden() -> None:
    preimage = b"\x00\x08cv-rc-v2\x00\x10" + ALICE.bytes + b"\x00\x1c" + NORM
    golden = hmac.new(AK_R, preimage, sha256).hexdigest()
    assert generated().recovery_code_digests(f" {CODE.lower()} ", ALICE) == (golden,)


#: Presented code -> normalised bytes (21 §3.1.5a: strip, upper-case, drop `-` and spaces, UTF-8).
NORMALISED = {
    " 7k3m 7k3m-7k3m\n": b"7K3M7K3M7K3M",  # outer whitespace, an interior space and dash
    "7K3M\t7K3M": b"7K3M\t7K3M",  # an interior tab stays
    "\xa07K3M\xa07K3M\xa0": b"7K3M\xc2\xa07K3M",  # NBSP: stripped at the ends only
    "stra\N{LATIN SMALL LETTER SHARP S}e \N{LATIN SMALL LIGATURE FI}": b"STRASSEFI",
    IOTA: b"\xce\x99\xcc\x88\xcc\x81",
}


@pytest.mark.parametrize("code", sorted(NORMALISED))
def test_normalised_code_is_golden_and_the_legacy_form(code: str) -> None:
    assert ak.normalise_code(code) == NORMALISED[code] == normalize_recovery_code(code).encode()


@settings(max_examples=150, deadline=None)
@given(code=st.text(max_size=64))
@example(code=IOTA * 64).via("the contract's longest code: 384 bytes, under the cap")
def test_imported_keyring_old_digest_is_the_legacy_hash(code: str) -> None:
    """AC3: an unused code made under the env key still matches after the import."""
    assert ak.normalise_code(code) == normalize_recovery_code(code).encode()
    assert imported().recovery_code_digests(code, ALICE)[1] == hash_recovery_code(code, key=AK_R)


def test_same_code_for_two_users_gives_different_digests() -> None:
    ring = generated()
    alice, bob = (set(ring.recovery_code_digests(CODE, u)) for u in (ALICE, BOB))
    assert not alice & bob


def test_keyring_of_the_wrong_shape_is_zeroed_and_refused() -> None:
    totp, recovery = bytearray(AK_T[:31]), bytearray(AK_R)
    with pytest.raises(ValueError):
        ak.LoadedAuthKeyring("demo", imported=False, totp_id=RID, totp=totp, recovery=recovery)
    assert not any(totp + recovery)


def test_close_zeroes_both_keys() -> None:
    ring = generated()
    ring.close()
    assert not ring.available() and not any(ring._totp_key + ring._rc_key)


def test_keyring_is_masked_unpicklable_uncopyable_and_final() -> None:
    ring = generated()
    assert repr(ring) == str(ring) == f"{ring}" == "***"
    for op in (pickle.dumps, copy.copy, copy.deepcopy):
        with pytest.raises(TypeError):
            op(ring)
    with pytest.raises(TypeError, match="may not be subclassed"):
        type("Evil", (ak.LoadedAuthKeyring,), {"__module__": "candleviewer.auth.evil"})


def test_wrap_verification_compares_in_constant_time(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = MagicMock(wraps=hmac.compare_digest)
    monkeypatch.setattr(hmac, "compare_digest", spy)
    ak.generate_keyring(kek())
    assert [len(c.args[0]) for c in spy.call_args_list] == [32, 32]


def test_wrap_that_does_not_open_is_never_stored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(LoadedKek, "unwrap_auth_key", lambda *a, **k: bytearray(32))
    with pytest.raises(AuthKeyringUnavailable, match=r"^auth_keyring_mismatch$"):
        ak.generate_keyring(kek())


@pytest.mark.parametrize("env_name", ["live", "demo", "testnet"])
def test_generated_keyring_round_trips_through_its_rows(env_name: str) -> None:
    records, ring = ak.generate_keyring(kek(env=env_name))
    shape = {(r["purpose"], r["origin"], r["key_version"], r["kek_version"]) for r in records}
    assert shape == {("totp_seal", "generated", 1, 1), ("recovery_hmac", "generated", 1, 1)}
    loaded = ak.load_keyring(kek(env=env_name), [dict(r) for r in records])
    blob, ref = ring.seal_totp_seed(SEED, ALICE)
    assert loaded.open_totp_seed(blob, ref, ALICE) == SEED
    assert loaded.recovery_code_digests(CODE, ALICE) == ring.recovery_code_digests(CODE, ALICE)


def test_each_generation_draws_two_fresh_keys() -> None:
    keys = _opened(kek(), ak.generate_keyring(kek())[0] + ak.generate_keyring(kek())[0])
    assert len(set(keys)) == 4 and bytes(32) not in keys


def test_closed_kek_generates_nothing() -> None:
    closed = kek()
    closed.close()
    with pytest.raises(KekUnavailable):
        ak.generate_keyring(closed)


@pytest.mark.parametrize("env_name", ["demo", "testnet"])
def test_import_wraps_the_env_keys_once_as_imported_env(env_name: str) -> None:
    records, _ = ak.import_keyring(kek(env=env_name), SecretStr(AK_T.hex()), SecretStr(AK_R.hex()))
    assert {r["origin"] for r in records} == {"imported_env"}
    assert _opened(kek(env=env_name), records) == [AK_T, AK_R]


def test_import_is_refused_in_live() -> None:
    with pytest.raises(AuthKeyEnvForbidden):
        ak.import_keyring(kek(env="live"), SecretStr(AK_T.hex()), SecretStr(AK_R.hex()))


def test_rotation_boot_opens_rows_still_at_the_previous_kek_version() -> None:
    rows = ak.generate_keyring(kek())[0]
    assert ak.load_keyring(kek(KEK_V2, 2), rows, prev=kek(KEK_V1, 1)).available()


def test_rows_at_an_older_kek_version_without_its_kek_are_stranded() -> None:
    rows = ak.generate_keyring(kek())[0]
    with pytest.raises(AuthKeyringUnavailable, match=r"^auth_keyring_stranded$"):
        ak.load_keyring(kek(KEK_V2, 2), rows)


def _v2(row: dict[str, Any]) -> str:
    """An `api_keys` wrap of the same row id, relabelled as an auth key wrap."""
    return "ak1:" + kek().wrap_dek(bytearray(32), credential_id=row["id"]).removeprefix("v2:")


def _flip(ref: str) -> str:
    """Flip one bit of the GCM tag (the last byte)."""
    return f"{ref[:-2]}{int(ref[-2:], 16) ^ 1:02x}"


#: Each fails closed in `live` as `auth_keyring_mismatch`; nothing is regenerated over it (AC8).
TAMPERED: dict[str, Callable[[Rows], Rows]] = {
    "missing_row": lambda r: r[:1],
    "extra_row": lambda r: [*r, {**r[0], "id": OTHER, "key_version": 2}],
    "swapped_wraps": lambda r: [{**r[0], "dek_ref": r[1]["dek_ref"]}, r[1]],
    "moved_to_another_id": lambda r: [{**r[0], "id": OTHER}, r[1]],
    "another_environment": lambda r: [{**r[0], "env": "testnet"}, r[1]],
    "mixed_origins": lambda r: [{**r[0], "origin": "imported_env"}, r[1]],
    "imported_in_live": lambda r: [{**row, "origin": "imported_env"} for row in r],  # D3
    "api_keys_wrap": lambda r: [{**r[0], "dek_ref": _v2(r[0])}, r[1]],
    "tampered_tag": lambda r: [{**r[0], "dek_ref": _flip(r[0]["dek_ref"])}, r[1]],
    "kek_version_relabelled": lambda r: [{**r[0], "kek_version": 2}, r[1]],
}


@pytest.mark.parametrize("case", sorted(TAMPERED))
def test_load_fails_closed_on_a_tampered_row(case: str) -> None:
    rows = TAMPERED[case](ak.generate_keyring(kek(env="live"))[0])
    with pytest.raises(AuthKeyringUnavailable, match=r"^auth_keyring_mismatch$"):
        ak.load_keyring(kek(env="live"), rows)


def test_failed_load_zeroes_the_key_it_had_opened(monkeypatch: pytest.MonkeyPatch) -> None:
    rows, opened = ak.generate_keyring(kek())[0], list[bytearray]()
    real = LoadedKek.unwrap_auth_key

    def spy(self: LoadedKek, ref: str, **kw: Any) -> bytearray:
        opened.append(real(self, ref, **kw))
        return opened[-1]

    monkeypatch.setattr(LoadedKek, "unwrap_auth_key", spy)
    with pytest.raises(AuthKeyringUnavailable):
        ak.load_keyring(kek(), [rows[0], {**rows[1], "id": OTHER}])
    assert len(opened) == 1 and not any(opened[0])


def _raised(call: Callable[[], object]) -> BaseException:
    try:
        call()
    except (SecretsError, ValueError) as exc:
        return exc
    raise AssertionError("did not raise")


def _with_locals(exc: BaseException) -> str:
    """As a locals-capturing renderer shows it (structlog `dict_tracebacks`, a crash reporter)."""
    return "".join(traceback.TracebackException.from_exception(exc, capture_locals=True).format())


_FORMS: tuple[Callable[[bytes], str], ...] = (
    lambda b: b.decode("latin-1"), repr, bytes.hex, lambda b: b.hex().upper(),
    lambda b: b64encode(b).decode(), lambda b: b32encode(b).decode(),
)  # fmt: skip
#: The KEK, both auth keys, the seed and the normalised code in every form, and the code as typed.
SENTINELS = [f(raw) for raw in (KEK_V1, AK_T, AK_R, SEED, NORM) for f in _FORMS] + [
    CODE, CODE.lower(), NORM.decode().lower()
]  # fmt: skip


def test_no_kek_auth_key_seed_or_code_reaches_a_repr_exception_or_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC13 for the core: every flow, failures included, under stdlib and structlog capture."""
    caplog.set_level(logging.DEBUG)
    with capture_logs() as logs:
        records, ring = ak.generate_keyring(kek())
        rows, (blob, ref) = [dict(r) for r in records], ring.seal_totp_seed(SEED, ALICE)
        shown = [repr(ring), str(ring), repr(records), *imported().recovery_code_digests(CODE, BOB)]
        failures: list[Callable[[], object]] = [
            lambda: ring.open_totp_seed(blob, ref, BOB),
            lambda: ak.load_keyring(kek(), [rows[0], {**rows[1], "dek_ref": rows[0]["dek_ref"]}]),
            lambda: ak.load_keyring(kek(KEK_V2, 2), rows),
            lambda: ak.import_keyring(kek(env="live"), SecretStr(AK_T.hex()), SecretStr("00")),
            lambda: ak.import_keyring(kek(), SecretStr(AK_T.hex()), SecretStr(AK_R.hex()[2:])),
        ]
        raised = [_raised(f) for f in failures]
    logged = [r.getMessage() for r in caplog.records]
    text = "\n".join([*shown, *map(_with_locals, raised), *logged, repr(logs)])
    assert not [s for s in SENTINELS if s in text]
    assert not [e for e in raised if e.__context__ is not None]  # nothing chained, nothing hidden
