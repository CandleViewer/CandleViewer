"""Frozen format vectors for the auth keyring (#2152 BQ-16, AGENTS.md §6.9): today's formats,
which the env-backed keyring keeps and an imported keyring still reads, and the new ones M2 writes.
Integer-built synthetic inputs only, never a key (C-13.5); each vector is checked here against the
live code that makes it, so they survive the switch-over's removal of `TotpEncryptor` and
`hash_recovery_code`, and a format can only change with them (S3 Deviation 6)."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest
from cryptography.exceptions import InvalidTag
from pydantic import SecretStr

from candleviewer.auth import envelope
from candleviewer.auth.env_keyring import EnvMfaKeyring
from candleviewer.auth.envelope import TotpEncryptor
from candleviewer.auth.recovery_codes import hash_recovery_code
from candleviewer.auth.totp import generate_code, verify_code
from candleviewer.secrets import _auth_keyring as ak
from candleviewer.secrets import _envelope as env
from candleviewer.secrets.errors import AuthSealInvalid
from tests.unit.credentials_m2._vectors import kek

AK_T, AK_R = bytes(range(140, 172)), bytes(range(172, 204))
SEED, CODE = bytes(range(1, 21)), "-".join(["7K3M"] * 7)
ALICE, BOB, RID = UUID(int=0xA11CE), UUID(int=0xB0B), UUID(int=0xA1)
#: Today's TOTP seal: a zero nonce, AES-256-GCM of SEED under AK_T, no AAD (`local-dev-v1`).
LEGACY_SEAL = bytes.fromhex(
    "00000000000000000000000008f5322efad3f692b716137839488cfed60f5a055c371f0d4e28d080"
    "3064360892c69aab"
)
#: Today's recovery-code digest: HMAC-SHA256 under AK_R of the normalised CODE, no user.
LEGACY_DIGEST = "b436228aea066d94ffaae29992c2a0d6836e7bd42dfbd08a49465ea65747fd2f"
#: M2's wrap of AK_T under the KEK of ("demo", 1) for row RID, purpose `totp_seal`, zero nonce.
AK1_WRAP = (
    "ak1:00000000000000000000000082313b5125bd112e9c3d3fa280b50b024edec8cc8820c28c243b"
    "15246d56f7fd5b4153077e5f3c605f76e85b0b4f951e"
)
#: M2's TOTP seal of SEED for ALICE in demo (`cv-totp-v1`), zero nonce.
TOTP_V1_SEAL = bytes.fromhex(
    "00000000000000000000000008f5322efad3f692b716137839488cfed60f5a0588b46454565aafc4"
    "de07d6a7f139ec0e"
)
#: M2's recovery-code digest of CODE for ALICE (`cv-rc-v2`), the one a new code stores.
RC_V2_DIGEST = "957b1c447c4635c92b72caba4dde7a00f49f17f34c6e1b816d13c1d8dce8cc8b"
#: RFC 6238 Appendix B (SHA-1, seed "12345678901234567890"): unix time -> the last 6 digits.
RFC6238 = {59: "287082", 1111111109: "081804", 1234567890: "005924", 2000000000: "279037"}


@pytest.fixture
def zero_nonce(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every seal and wrap drawn here takes a zero nonce, so its bytes are fixed."""
    monkeypatch.setattr(env, "new_nonce", lambda: bytes(12))
    monkeypatch.setattr(envelope, "os", SimpleNamespace(urandom=lambda n: bytes(n)))


@pytest.fixture
def known_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = [bytearray(AK_T), bytearray(AK_R)]
    monkeypatch.setattr(env, "new_dek", lambda: pool.pop(0))


@pytest.mark.usefixtures("zero_nonce")
async def test_today_s_formats_are_the_frozen_vectors() -> None:
    """The env-backed keyring keeps them (#2152 S5a): its seal, open and digest, and the live code
    it wraps (`TotpEncryptor`, `hash_recovery_code`), give the frozen bytes."""
    keyring = EnvMfaKeyring(AK_T, AK_R)
    assert await keyring.seal_totp_seed(SEED, ALICE) == (LEGACY_SEAL, "local-dev-v1")
    assert TotpEncryptor(AK_T).encrypt(SEED) == LEGACY_SEAL
    assert await keyring.open_totp_seed(LEGACY_SEAL, "local-dev-v1", BOB) == SEED  # no user bound
    assert await keyring.recovery_code_digests(CODE, ALICE) == (LEGACY_DIGEST,)
    assert hash_recovery_code(CODE.lower(), key=AK_R) == LEGACY_DIGEST


def test_an_imported_keyring_reads_today_s_formats_and_writes_the_new_ones() -> None:
    """AC3: after the import, a seed and an unused code made under the env keys still work; a new
    code stores the user-bound digest first."""
    _, ring = ak.import_keyring(kek(), SecretStr(AK_T.hex()), SecretStr(AK_R.hex()))
    assert ring.open_totp_seed(LEGACY_SEAL, "local-dev-v1", ALICE) == SEED
    assert ring.recovery_code_digests(CODE, ALICE) == (RC_V2_DIGEST, LEGACY_DIGEST)


@pytest.mark.usefixtures("zero_nonce", "known_keys")
def test_the_new_formats_are_the_frozen_vectors() -> None:
    assert kek().wrap_auth_key(bytearray(AK_T), key_id=RID, purpose="totp_seal") == AK1_WRAP
    assert kek().unwrap_auth_key(AK1_WRAP, key_id=RID, purpose="totp_seal") == AK_T
    _, ring = ak.generate_keyring(kek())
    blob, _ = ring.seal_totp_seed(SEED, ALICE)
    assert blob == TOTP_V1_SEAL and ring.recovery_code_digests(CODE, ALICE) == (RC_V2_DIGEST,)


@pytest.mark.usefixtures("known_keys")
def test_a_frozen_vector_moved_to_another_binding_does_not_open() -> None:
    """AC8 and AC9 on the frozen bytes: a wrap under another purpose, a seal for another user, a
    digest for another user, and today's unbound seal on a generated keyring."""
    with pytest.raises(InvalidTag):
        kek().unwrap_auth_key(AK1_WRAP, key_id=RID, purpose="recovery_hmac")
    rows, ring = ak.generate_keyring(kek())
    ref = f"akey:{rows[0]['id']}"
    with pytest.raises(AuthSealInvalid):
        ring.open_totp_seed(TOTP_V1_SEAL, ref, BOB)
    assert RC_V2_DIGEST not in ring.recovery_code_digests(CODE, BOB)
    assert not ring.available("local-dev-v1")  # D3: never on a generated keyring


@pytest.mark.parametrize(("unix_time", "code"), sorted(RFC6238.items()))
def test_a_bytearray_seed_verifies_the_rfc_6238_vectors(unix_time: int, code: str) -> None:
    """The verifier takes the seed as the `bytearray` the keyring opens and zeroes (BQ-6)."""
    seed = bytearray(b"12345678901234567890")
    assert generate_code(seed, unix_time // 30) == code
    assert verify_code(seed, code, unix_time=unix_time) == unix_time // 30
