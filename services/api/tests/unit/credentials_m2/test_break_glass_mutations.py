"""Seeded mutants for break-glass's live digest session (#2152 S6, BQ-11; repo convention, see
`test_mutations.py` and `test_auth_custody_mutations.py`): a session opened before the KEK is
proven, the TOTP key unwrapped with it, the KEKs kept after the pass, and the session left open
after the run. Each case injects one plausible defect via monkeypatch, runs the real oracle under
it and asserts the oracle fails (mutant killed); every oracle passes unmutated."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

import pytest

from candleviewer.admin.breakglass import BreakGlassExit
from candleviewer.auth.break_glass import BreakGlassResetService
from candleviewer.secrets import _auth_keyring as ak
from candleviewer.secrets import service as service_module
from candleviewer.secrets._kek import LoadedKek
from candleviewer.secrets.models import KekCheckResult
from candleviewer.secrets.service import SecretsService
from tests.unit.admin import test_breakglass_flow as flow
from tests.unit.credentials_m2 import test_recovery_digests as digests

_KILLED = (AssertionError, pytest.fail.Exception)
Oracle = Callable[[pytest.MonkeyPatch], Awaitable[None] | None]


async def _session_first(self: SecretsService, settings: Any, then: Any = None) -> KekCheckResult:
    """The digest session opened in the custody pass before the KEK is proven."""
    held: list[LoadedKek] = []
    try:
        kek, prev = await self._acquire_keks(settings, self._sources(settings), held)
        if then is not None and (refused := await then(kek, prev)) is not None:
            return KekCheckResult(None, False, refused)
        await self._check_versions(settings.environment.value, kek, prev)
        return KekCheckResult(kek.version, True, None)
    except Exception:
        return KekCheckResult(None, False, "kek_mismatch")
    finally:
        self._close(*held)


def _both_keys(
    kek: LoadedKek, rows: Sequence[Mapping[str, Any]], *, prev: LoadedKek | None = None
) -> ak.RecoveryDigests:
    """The whole keyring opened for a digest: the TOTP key leaves its wrap too."""
    ring = ak.load_keyring(kek, rows, prev=prev)
    session = ak.RecoveryDigests(bytearray(ring._rc_key))
    ring.close()
    return session


def _kept(*keks: LoadedKek) -> None:
    return None  # the KEKs stay in memory after the pass


def _left_open(self: BreakGlassResetService) -> None:
    return None  # the run ends with the session's key still in memory


async def _a_reset_run(_monkeypatch: pytest.MonkeyPatch) -> None:
    """The flow's oracle on a live run that resets."""
    oracle = flow.test_the_live_digest_session_is_closed_whatever_the_run_s_end
    await oracle({}, BreakGlassExit.RESET)


MUTANTS: dict[str, tuple[object, str, object, Oracle]] = {
    "session_before_the_proof": (
        SecretsService, "_prove_possession", _session_first,
        digests.test_a_kek_that_fails_its_proof_reads_no_keyring_row,
    ),
    "totp_key_unwrapped_too": (
        service_module, "recovery_digests", _both_keys,
        digests.test_a_proven_kek_opens_a_session_of_the_recovery_key_alone,
    ),
    "keks_kept_after_the_pass": (
        SecretsService, "_close", staticmethod(_kept),
        digests.test_a_proven_kek_opens_a_session_of_the_recovery_key_alone,
    ),
    "session_left_open": (BreakGlassResetService, "close", _left_open, _a_reset_run),
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
