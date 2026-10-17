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
from uuid import UUID

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr
from structlog.testing import capture_logs

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
from candleviewer.secrets.store import InMemoryAuthKeyStore
from tests.unit.credentials_m2._vectors import KEK_V1, KEK_V2, kek

AK_T, AK_R = bytes(range(140, 172)), bytes(range(172, 204))  # the two auth keys under test
SEED = bytes(range(1, 21))  # a 20-byte TOTP seed
CODE, NORM = "-".join(["7K3M"] * 7), b"7K3M" * 7  # grouped like a generated recovery code
RID, OTHER, ALICE, BOB = (UUID(int=n) for n in (0xA1, 0xA2, 0xA11CE, 0xB0B))
Rows = list[dict[str, Any]]


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
        lambda: generated().recovery_code_digests("A" * 257, ALICE),
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


def test_totp_seal_moved_to_another_user_is_refused() -> None:
    ring = generated()
    blob, ref = ring.seal_totp_seed(SEED, ALICE)
    with pytest.raises(AuthSealInvalid):
        ring.open_totp_seed(blob, ref, BOB)


@pytest.mark.parametrize("tamper", [lambda b: b[:-1] + bytes([b[-1] ^ 1]), lambda b: b[:27]])
def test_tampered_totp_seal_is_refused(tamper: Callable[[bytes], bytes]) -> None:
    ring = generated()
    blob, ref = ring.seal_totp_seed(SEED, ALICE)
    with pytest.raises(AuthSealInvalid):
        ring.open_totp_seed(tamper(blob), ref, ALICE)


@pytest.mark.parametrize("ref", [f"akey:{OTHER}", "local-dev-v1", ""])
def test_seal_under_a_key_not_held_is_unavailable_never_no_method(ref: str) -> None:
    ring = generated()
    blob, _ = ring.seal_totp_seed(SEED, ALICE)
    with pytest.raises(AuthKeyringUnavailable, match=r"^auth_key_not_held$"):
        ring.open_totp_seed(blob, ref, ALICE)


def test_imported_keyring_reads_the_env_keys_old_formats() -> None:
    ring, old = imported(), bytes(12) + AESGCM(AK_T).encrypt(bytes(12), SEED, None)
    assert ring.open_totp_seed(old, "local-dev-v1", ALICE) == SEED
    v2, unbound = ring.recovery_code_digests(CODE, ALICE)
    assert unbound == hmac.new(AK_R, NORM, sha256).hexdigest() != v2


def test_generated_keyring_digest_is_the_bound_v2_golden() -> None:
    preimage = b"\x00\x08cv-rc-v2\x00\x10" + ALICE.bytes + b"\x00\x1c" + NORM
    golden = hmac.new(AK_R, preimage, sha256).hexdigest()
    assert generated().recovery_code_digests(f" {CODE.lower()} ", ALICE) == (golden,)


def test_same_code_for_two_users_gives_different_digests() -> None:
    ring = generated()
    alice, bob = (set(ring.recovery_code_digests(CODE, u)) for u in (ALICE, BOB))
    assert not alice & bob


def test_keyring_of_the_wrong_shape_is_zeroed_and_refused() -> None:
    totp, recovery = bytearray(AK_T[:31]), bytearray(AK_R)
    with pytest.raises(ValueError):
        ak.LoadedAuthKeyring("demo", imported=False, totp_id=RID, totp=totp, recovery=recovery)
    assert not any(totp + recovery)


@pytest.mark.parametrize("op", ["seal", "open", "digests"])
def test_close_zeroes_both_keys_and_later_calls_refuse(op: str) -> None:
    ring = generated()
    blob, ref = ring.seal_totp_seed(SEED, ALICE)
    calls: dict[str, Callable[[], object]] = {
        "seal": lambda: ring.seal_totp_seed(SEED, ALICE),
        "open": lambda: ring.open_totp_seed(blob, ref, ALICE),
        "digests": lambda: ring.recovery_code_digests(CODE, ALICE),
    }
    ring.close()
    assert not ring.available() and not any(ring._totp_key + ring._rc_key)
    with pytest.raises(AuthKeyringUnavailable, match=r"^auth_keyring_closed$"):
        calls[op]()


def test_keyring_is_masked_unpicklable_uncopyable_and_final() -> None:
    ring = generated()
    assert repr(ring) == str(ring) == f"{ring}" == "***"
    for op in (pickle.dumps, copy.copy, copy.deepcopy):
        with pytest.raises(TypeError):
            op(ring)
    with pytest.raises(TypeError, match="may not be subclassed"):
        type("Evil", (ak.LoadedAuthKeyring,), {"__module__": "candleviewer.auth.evil"})


def test_wrap_verification_compares_in_constant_time(monkeypatch: pytest.MonkeyPatch) -> None:
    compared: list[int] = []
    real = hmac.compare_digest

    def spy(a: bytearray, b: bytearray) -> bool:
        compared.append(len(a))
        return real(a, b)

    monkeypatch.setattr(hmac, "compare_digest", spy)
    ak.generate_keyring(kek())
    assert compared == [32, 32]


def test_wrap_that_does_not_open_is_never_stored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(LoadedKek, "unwrap_auth_key", lambda *a, **k: bytearray(32))
    with pytest.raises(AuthKeyringUnavailable, match=r"^auth_keyring_mismatch$"):
        ak.generate_keyring(kek())


@pytest.mark.parametrize("env_name", ["live", "demo", "testnet"])
async def test_generated_keyring_round_trips_through_the_store(env_name: str) -> None:
    store = InMemoryAuthKeyStore()
    records, ring = ak.generate_keyring(kek(env=env_name))
    assert await store.insert_keyring(records)
    rows = await store.rows_for(env_name)
    shape = {(r["purpose"], r["origin"], r["key_version"], r["kek_version"]) for r in rows}
    assert shape == {("totp_seal", "generated", 1, 1), ("recovery_hmac", "generated", 1, 1)}
    loaded = ak.load_keyring(kek(env=env_name), rows)
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


#: Each fails closed as `auth_keyring_mismatch`, and nothing is regenerated over it (AC8).
TAMPERED: dict[str, Callable[[Rows], Rows]] = {
    "missing_row": lambda r: r[:1],
    "extra_row": lambda r: [*r, {**r[0], "id": OTHER, "key_version": 2}],
    "swapped_wraps": lambda r: [{**r[0], "dek_ref": r[1]["dek_ref"]}, r[1]],
    "moved_to_another_id": lambda r: [{**r[0], "id": OTHER}, r[1]],
    "another_environment": lambda r: [{**r[0], "env": "testnet"}, r[1]],
    "mixed_origins": lambda r: [{**r[0], "origin": "imported_env"}, r[1]],
    "api_keys_wrap": lambda r: [{**r[0], "dek_ref": _v2(r[0])}, r[1]],
    "tampered_tag": lambda r: [{**r[0], "dek_ref": _flip(r[0]["dek_ref"])}, r[1]],
    "kek_version_relabelled": lambda r: [{**r[0], "kek_version": 2}, r[1]],
}


@pytest.mark.parametrize("case", sorted(TAMPERED))
def test_load_fails_closed_on_a_tampered_row(case: str) -> None:
    rows = TAMPERED[case](ak.generate_keyring(kek())[0])
    with pytest.raises(AuthKeyringUnavailable, match=r"^auth_keyring_mismatch$"):
        ak.load_keyring(kek(), rows)


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


async def test_store_fake_inserts_all_or_nothing_reads_by_env_and_rewraps_by_cas() -> None:
    store, first = InMemoryAuthKeyStore(mfa_material=2), ak.generate_keyring(kek())[0]
    assert await store.insert_keyring(first)
    assert not await store.insert_keyring(ak.generate_keyring(kek())[0])
    assert [r["id"] for r in await store.rows_for("demo")] == [r["id"] for r in first]
    assert await store.rows_for("live") == [] and await store.count_mfa_material() == 2
    row = first[0]
    move: dict[str, Any] = {"from_version": 1, "dek_ref": "ak1:new", "kek_version": 2}
    assert not await store.rewrap(row["id"], env="live", **move)
    assert await store.rewrap(row["id"], env="demo", **move)
    assert not await store.rewrap(row["id"], env="demo", **move)
    assert store.rows[row["id"]]["dek_ref"] == "ak1:new"


def _raised(call: Callable[[], object]) -> BaseException:
    try:
        call()
    except (SecretsError, ValueError) as exc:
        return exc
    raise AssertionError("did not raise")


def test_no_kek_auth_key_seed_or_code_reaches_a_repr_exception_or_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC13 for the core: every flow, failures included, under stdlib and structlog capture."""
    caplog.set_level(logging.DEBUG)
    with capture_logs() as logs:
        records, ring = ak.generate_keyring(kek())
        rows, closed = [dict(r) for r in records], imported()
        blob, ref = ring.seal_totp_seed(SEED, ALICE)
        closed.close()
        shown = [repr(ring), str(ring), repr(records), *ring.recovery_code_digests(CODE, ALICE)]
        failures: list[Callable[[], object]] = [
            lambda: ring.open_totp_seed(blob, ref, BOB),
            lambda: ring.open_totp_seed(blob, "local-dev-v1", ALICE),
            lambda: ak.load_keyring(kek(), [rows[0], {**rows[1], "dek_ref": rows[0]["dek_ref"]}]),
            lambda: ak.load_keyring(kek(KEK_V2, 2), rows),
            lambda: ak.import_keyring(kek(env="live"), SecretStr(AK_T.hex()), SecretStr("00")),
            lambda: ak.import_keyring(kek(), SecretStr(AK_T.hex()), SecretStr(AK_R.hex()[2:])),
            lambda: closed.recovery_code_digests(CODE, ALICE),
        ]
        shown += ["".join(traceback.format_exception(_raised(f))) for f in failures]
    text = "\n".join([*shown, *(r.getMessage() for r in caplog.records), repr(logs)])
    for raw in (KEK_V1, AK_T, AK_R, SEED, NORM):
        forms = (raw.hex(), raw.hex().upper(), b64encode(raw).decode(), b32encode(raw).decode())
        assert not [f for f in (*forms, repr(raw)) if f in text]
    assert CODE not in text
