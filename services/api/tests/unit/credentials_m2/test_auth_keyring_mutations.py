"""Seeded mutants for the auth keyring (#2152 S3; repo convention, see `test_mutations.py`).

Each case injects one plausible defect via monkeypatch, runs the real oracle test under it and
asserts the oracle fails (mutant killed). Every oracle passes unmutated, with the same seam.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any
from uuid import UUID

import pytest

from candleviewer.secrets import _auth_keyring as ak
from candleviewer.secrets import _envelope as env
from tests.unit.credentials_m2 import test_auth_keyring as core

_KILLED = (AssertionError, pytest.fail.Exception)
_AKEY, _TOTP, _RC = env.akey_aad, env.totp_aad, env.rc_preimage
_INIT, _ZERO = ak.LoadedAuthKeyring.__init__, UUID(int=0)
_SWAP = core.test_wrap_opens_only_under_its_own_binding
_MOVED = core.test_totp_seal_moved_to_another_user_is_refused
_TAMPER = core.test_load_fails_closed_on_a_tampered_row
_STRANDED = core.test_rows_at_an_older_kek_version_without_its_kek_are_stranded
_FRAMES = core.test_keyring_failure_leaves_no_key_seed_or_code_in_its_frames
_OPEN, _ALL_ENVS = ak.LoadedAuthKeyring.open_totp_seed, frozenset({"demo", "testnet", "live"})


def _always_imported(self: ak.LoadedAuthKeyring, env_name: str, **kw: Any) -> None:
    _INIT(self, env_name, **{**kw, "imported": True})


def _close_flag_only(self: ak.LoadedAuthKeyring) -> None:
    self._ak_closed = True


def _aliased_open(self: ak.LoadedAuthKeyring, blob: bytes, ref: str, user: UUID) -> bytearray:
    key = self._totp_key  # the alias the #2152 review removed: a live key in a raising frame
    return _OPEN(self, blob, ref, user) if key else bytearray()


#: name -> (target, attribute, mutant, oracle): the #2152 test plan's mutants of the core.
MUTANTS: dict[str, tuple[object, str, object, Callable[[], None]]] = {
    "aad_env": (env, "akey_aad", lambda e, p, i, v: _AKEY("demo", p, i, v), partial(_SWAP, "env")),
    "aad_purpose": (env, "akey_aad", lambda e, p, i, v: _AKEY(e, "totp_seal", i, v),
                    partial(_SWAP, "purpose")),
    "aad_id": (env, "akey_aad", lambda e, p, i, v: _AKEY(e, p, _ZERO, v), partial(_SWAP, "id")),
    "aad_kek_version": (env, "akey_aad", lambda e, p, i, v: _AKEY(e, p, i, 1),
                        partial(_SWAP, "kek_version")),
    "totp_no_aad": (env, "totp_aad", lambda e, u: b"", _MOVED),
    "totp_no_user": (env, "totp_aad", lambda e, u: _TOTP(e, _ZERO), _MOVED),
    "digest_no_user": (env, "rc_preimage", lambda u, n: _RC(_ZERO, n),
                       core.test_same_code_for_two_users_gives_different_digests),
    "no_version_check": (ak, "_holder", lambda v, k, p: k,
                         partial(_TAMPER, "kek_version_relabelled")),
    "no_version_check_stranded": (ak, "_holder", lambda v, k, p: k, _STRANDED),
    "import_in_live": (ak, "IMPORT_ENVIRONMENTS", _ALL_ENVS, core.test_import_is_refused_in_live),
    "load_imported_in_live": (ak, "IMPORT_ENVIRONMENTS", _ALL_ENVS,
                              partial(_TAMPER, "imported_in_live")),
    "key_alias_in_frame": (ak.LoadedAuthKeyring, "open_totp_seed", _aliased_open,
                           partial(_FRAMES, "moved_seal")),
    "close_no_zero": (ak.LoadedAuthKeyring, "close", _close_flag_only,
                      partial(core.test_close_zeroes_both_keys_and_later_calls_refuse, "digests")),
    "old_formats_generated": (ak.LoadedAuthKeyring, "__init__", _always_imported,
                              core.test_generated_keyring_digest_is_the_bound_v2_golden),
}  # fmt: skip


@pytest.fixture(autouse=True)
def known_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    core.use_known_keys(monkeypatch)


@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_mutant_killed(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    target, attribute, mutant, oracle = MUTANTS[name]
    monkeypatch.setattr(target, attribute, mutant)
    with pytest.raises(_KILLED):
        oracle()
