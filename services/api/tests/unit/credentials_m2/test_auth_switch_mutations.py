"""Seeded mutants for the switch-over (#2152 S5b; repo convention, see `test_mutations.py` and
`test_auth_custody_mutations.py`): the boot the real-backend wiring turns on, the first boot's
import, the dual-read window and its exit test (BQ-3). Each case injects one plausible defect via
monkeypatch, runs the real oracle under it and asserts the oracle fails (mutant killed); every
oracle passes unmutated, with the same seams."""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa

from candleviewer.admin import wiring
from candleviewer.auth.errors import MfaCodeInvalid, RecoveryCodeInvalid
from candleviewer.secrets import _auth_custody as custody
from candleviewer.secrets import _auth_keyring as ak
from candleviewer.secrets.service import SecretsService
from candleviewer.storage.repositories import auth_keys_sqlalchemy as store_module
from tests.unit.credentials_m2 import test_auth_keyring_switch as switch
from tests.unit.storage import test_auth_keys_sqlalchemy as store_oracle

#: An oracle fails by assertion, or with the refusal the defect causes: the old unused code no
#: longer found (`RecoveryCodeInvalid`), an old seal read as a wrong code (`MfaCodeInvalid`).
_KILLED = (AssertionError, pytest.fail.Exception, RecoveryCodeInvalid, MfaCodeInvalid)
Oracle = Callable[[pytest.MonkeyPatch], Awaitable[None] | None]
_DIGESTS = ak.LoadedAuthKeyring.recovery_code_digests


def _unwired(**kwargs: Any) -> SecretsService:
    kwargs.pop("auth_keyring", None)  # the seam left unpassed: the keyring stays dormant
    return SecretsService(**kwargs)


def _env_keys_unread(settings: Any) -> custody.EnvKeys:
    return None, None  # the first boot never sees the settings it should import


def _bound_only(self: ak.LoadedAuthKeyring, code: str, user_id: UUID) -> tuple[str, ...]:
    return _DIGESTS(self, code, user_id)[:1]  # the old digest is dropped from the lookup


def _legacy_everywhere(self: ak.LoadedAuthKeyring, key_ref: str) -> bool:
    return key_ref in (self._totp_ref, ak.LEGACY_TOTP_REF)  # old seals read on a generated one


async def _no_window(store: Any, env_name: str) -> None:
    return None  # the exit test is never taken


#: The exit test without its age bound: every unused code counts, so it never passes.
_UNBOUNDED = sa.text(
    "SELECT (SELECT count(*) FROM mfa_methods WHERE kind = 'totp' AND revoked_at IS NULL "
    "AND secret_key_ref = 'local-dev-v1') + (SELECT count(*) FROM recovery_codes "
    "WHERE used_at IS NULL) AS legacy"
)


def _static(oracle: Callable[[], None]) -> Oracle:
    def run(_monkeypatch: pytest.MonkeyPatch) -> None:
        oracle()

    return run


MUTANTS: dict[str, tuple[object, str, object, Oracle]] = {
    "seam_unwired": (
        wiring, "SecretsService", _unwired, switch.test_the_real_backend_wiring_turns_the_keyring_on
    ),
    "import_skipped": (
        custody, "env_keys", _env_keys_unread,
        switch.test_the_first_switch_over_boot_keeps_a_demo_database_s_enrolments,
    ),
    "old_digest_dropped": (
        ak.LoadedAuthKeyring, "recovery_code_digests", _bound_only,
        switch.test_the_first_switch_over_boot_keeps_a_demo_database_s_enrolments,
    ),
    "old_seal_read_on_a_generated_keyring": (
        ak.LoadedAuthKeyring, "_holds", _legacy_everywhere,
        switch.test_a_generated_keyring_reads_no_old_format,
    ),
    "exit_test_skipped": (
        custody, "_legacy_window", _no_window,
        functools.partial(
            switch.test_each_boot_of_an_imported_keyring_logs_the_exit_test,
            material=3, level="warning",
        ),
    ),
    "exit_test_unbounded": (
        store_module, "_LEGACY_MATERIAL", _UNBOUNDED,
        _static(store_oracle.test_the_exit_test_counts_only_what_the_old_formats_still_serve),
    ),
}  # fmt: skip


async def _run(oracle: Oracle, monkeypatch: pytest.MonkeyPatch) -> None:
    outcome = oracle(monkeypatch)
    if outcome is not None:
        await outcome


@pytest.mark.parametrize("name", sorted(MUTANTS))
async def test_mutant_killed(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    target, attribute, mutant, oracle = MUTANTS[name]
    monkeypatch.setattr(target, attribute, mutant)
    with pytest.raises(_KILLED):
        await _run(oracle, monkeypatch)


@pytest.mark.parametrize("name", sorted(MUTANTS))
async def test_every_oracle_passes_unmutated(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """The kill above comes from the mutant: the same oracle, with the same seams, passes."""
    await _run(MUTANTS[name][3], monkeypatch)
