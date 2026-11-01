"""Seeded mutants for the auth keyring's lifecycle and capability (#2152 S4; repo convention, see
`test_mutations.py` and `test_auth_keyring_mutations.py`).

Each case injects one plausible defect via monkeypatch, runs the real oracle test under it and
asserts the oracle fails (mutant killed). Every oracle passes unmutated, with the same seams.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa

from candleviewer.admin import wiring
from candleviewer.auth.errors import MfaKeyringUnavailable, MfaSealInvalid
from candleviewer.secrets import _auth_custody as custody
from candleviewer.secrets import service as service_module
from candleviewer.secrets._kek import LoadedKek
from candleviewer.secrets._rotation import RotatingBroker
from candleviewer.secrets.errors import AuthKeyringUnavailable, AuthSealInvalid
from candleviewer.secrets.service import SecretsService
from candleviewer.storage.repositories import auth_keys_sqlalchemy as store_module
from tests.unit.credentials_m2 import test_auth_keyring_boot as boot
from tests.unit.credentials_m2._vectors import KEK_V2
from tests.unit.storage import test_auth_keys_sqlalchemy as store_oracle

_KILLED = (AssertionError, pytest.fail.Exception)
_MINT = service_module.mint_auth_keyring


async def _not_rewrapped(store: Any, rows: list[dict[str, Any]], kek: Any, prev: Any) -> Any:
    return rows  # the rotation boot skips the auth rows


def _unverified(kek: LoadedKek, key: bytearray, key_id: UUID, purpose: str) -> str:
    return kek.wrap_auth_key(key, key_id=key_id, purpose=purpose)  # stored without its proof


#: The CAS without `from_version`: a stale or replayed re-wrap moves the row again.
_NO_FROM = sa.text(
    "UPDATE auth_keys SET dek_ref = :dek_ref, kek_version = :to_v "
    "WHERE id = :id AND env = CAST(:env AS exchange_env)"
)


async def _no_trial(self: RotatingBroker, kek: LoadedKek, keys: Any) -> bool:
    return False  # the KCV trial skips `auth_keys`


def _kept(self: SecretsService) -> None:
    return None  # `stop()` and a cancelled boot leave the keyring open


async def _nothing_held_back(store: Any) -> bool:
    return True  # the material probe is not consulted: a key is generated over it


class _Holding:
    """The capability holding what it serves as an attribute, behaving otherwise as minted."""

    def __init__(self, svc: SecretsService) -> None:
        self.svc, self._real = svc, _MINT(svc)

    async def available(self, *refs: str) -> bool:
        return await self._real.available(*refs)

    async def seal_totp_seed(self, seed: bytes, user_id: UUID) -> tuple[bytes, str]:
        return await self._real.seal_totp_seed(seed, user_id)

    async def open_totp_seed(self, blob: bytes, ref: str, user_id: UUID) -> bytearray:
        return await self._real.open_totp_seed(blob, ref, user_id)

    async def recovery_code_digests(self, code: str, user_id: UUID) -> tuple[str, ...]:
        return await self._real.recovery_code_digests(code, user_id)


async def _chained_open(
    self: wiring._MfaKeyring, blob: bytes, key_ref: str, user_id: UUID
) -> bytearray:
    """The adapter raising `auth`'s error inside the handler: M2's error chained to it."""
    try:
        return await self._keyring.open_totp_seed(blob, key_ref, user_id)
    except AuthSealInvalid as exc:
        raise MfaSealInvalid("auth_seal_invalid") from exc
    except AuthKeyringUnavailable as exc:
        raise MfaKeyringUnavailable(exc.reason)  # noqa: B904 -- the defect under test


Oracle = Callable[[pytest.MonkeyPatch], Awaitable[None] | None]


def _rotated(mp: pytest.MonkeyPatch) -> Awaitable[None]:
    return boot.test_the_rotation_boot_rewraps_both_rows_with_their_records()


def _unproven(mp: pytest.MonkeyPatch) -> Awaitable[None]:
    return boot.test_a_new_wrap_not_proven_to_open_is_never_stored(mp)


def _cas(mp: pytest.MonkeyPatch) -> None:
    store_oracle.test_the_rewrap_is_a_compare_and_set_on_the_row_s_environment_and_kek_version()


def _trialled(mp: pytest.MonkeyPatch) -> Awaitable[None]:
    return boot.test_an_auth_row_is_the_evidence_before_a_kcv_is_enrolled(KEK_V2, False)


def _material(mp: pytest.MonkeyPatch) -> Awaitable[None]:
    return boot.test_material_without_a_keyring_is_never_generated_over()


def _one_setting(mp: pytest.MonkeyPatch) -> Awaitable[None]:
    totp_only = (boot.TOTP_HEX, custody.SETTINGS[1])
    return boot.test_one_env_setting_alone_is_missing_and_names_the_other(*totp_only)


def _closures(mp: pytest.MonkeyPatch) -> Awaitable[None]:
    return boot.test_the_capability_holds_closures_only_and_resolves_per_call()


def _unchained(mp: pytest.MonkeyPatch) -> Awaitable[None]:
    return boot.test_the_wiring_adapter_maps_every_m2_refusal_with_nothing_chained()


#: name -> (target, attribute, mutant, oracle): #2152 S4's mutants (the scout's PR A list).
MUTANTS: dict[str, tuple[object, str, object, Oracle]] = {
    "rewrap_skipped": (custody, "_rewrapped", _not_rewrapped, _rotated),
    "rewrap_unverified": (custody, "wrap_verified", _unverified, _unproven),
    "cas_no_from_version": (store_module, "_REWRAP", _NO_FROM, _cas),
    "kcv_trial_skips_auth": (RotatingBroker, "_trial_auth", _no_trial, _trialled),
    "stop_keeps_keyring": (
        SecretsService, "_drop_auth_keyring", _kept,
        boot.test_stop_closes_the_keyring_and_the_capability_refuses,
    ),
    "degrade_keeps_keyring": (
        SecretsService, "_drop_auth_keyring", _kept,
        boot.test_a_boot_cancelled_after_the_keyring_opened_closes_it,
    ),
    "generate_over_material": (custody, "_nothing_held_back", _nothing_held_back, _material),
    "import_one_setting": (custody, "_one_alone", lambda keys: None, _one_setting),
    "capability_holds_keyring": (service_module, "mint_auth_keyring", _Holding, _closures),
    "adapter_chains": (wiring._MfaKeyring, "open_totp_seed", _chained_open, _unchained),
}  # fmt: skip


@pytest.mark.parametrize("name", sorted(MUTANTS))
async def test_mutant_killed(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    target, attribute, mutant, oracle = MUTANTS[name]
    monkeypatch.setattr(target, attribute, mutant)
    with pytest.raises(_KILLED):
        outcome = oracle(monkeypatch)
        if outcome is not None:
            await outcome


@pytest.mark.parametrize("name", sorted(MUTANTS))
async def test_every_oracle_passes_unmutated(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """The kill above comes from the mutant: the same oracle, with the same seams, passes."""
    outcome = MUTANTS[name][3](monkeypatch)
    if outcome is not None:
        await outcome
