"""Seeded mutations for M2 (AGENTS §6 safety-critical; repo convention, cf. bars E12-Q02).

Each test injects one plausible defect via monkeypatch, runs the *real* oracle test under the
mutant and asserts the oracle fails (mutant killed). This is not a mutation-testing tool run;
no such tool is pinned in `uv.lock` (adding one is a dependency decision, not made here).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from candleviewer.secrets import _envelope as env
from candleviewer.secrets import _kek
from candleviewer.secrets import _permissions as perms
from candleviewer.secrets._rotation import RotatingBroker
from candleviewer.secrets.broker import CredentialBroker
from candleviewer.secrets.errors import CredentialUnavailable, WithdrawPermissionRejected
from candleviewer.secrets.service import SecretsService
from candleviewer.secrets.store import InMemoryCredentialStore
from tests.unit.credentials_m2 import test_broker_safety as safety_oracle
from tests.unit.credentials_m2 import test_envelope_rows as env_oracle
from tests.unit.credentials_m2 import test_kek as kek_oracle
from tests.unit.credentials_m2 import test_kek_lineage_per_env as lineage_oracle
from tests.unit.credentials_m2 import test_permissions as perm_oracle
from tests.unit.credentials_m2 import test_rotation as rot_oracle
from tests.unit.credentials_m2 import test_service_boot as svc_oracle
from tests.unit.credentials_m2._vectors import KEK_LIVE, AuditLog, FakeClock, kek

_KILLED = (AssertionError, pytest.fail.Exception)
#: Round 3 adds custody/boundary mutants at the end of the file (each killed by an oracle).


def _fresh() -> tuple[InMemoryCredentialStore, CredentialBroker]:
    s = InMemoryCredentialStore()
    return s, CredentialBroker(s, AuditLog(), kek(), clock=FakeClock())


async def test_mutant_constant_nonce_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(env, "new_nonce", lambda: bytes(12))
    s, b = _fresh()
    with pytest.raises(_KILLED):
        await env_oracle.test_broker_each_encryption_gets_fresh_nonce(b, s)


async def test_mutant_aad_ignores_account_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    real = env.cred_aad
    monkeypatch.setattr(env, "cred_aad", lambda e, a, c, f: real(e, UUID(int=0), c, f))
    s, b = _fresh()
    with pytest.raises(_KILLED):
        await env_oracle.test_broker_aad_inputs_bound(b, s, "exchange_account_id")


async def test_mutant_aad_uses_row_env_not_process_env_killed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutant: the namespaced read and the process-env check are dropped, so only the row's
    own (relabelled) env reaches the AAD — the oracle must still refuse."""
    real_check = CredentialBroker._check_row

    def lax(self: CredentialBroker, row: Any, key_id: Any, purpose: str, **kw: Any) -> Any:
        self._env = row.env if row is not None else self._env
        return real_check(self, row, key_id, purpose, **kw)

    async def any_env(self: InMemoryCredentialStore, key_id: Any, env_: str) -> Any:
        row = self.rows.get(key_id)
        return dict(row) if row is not None else None

    monkeypatch.setattr(CredentialBroker, "_check_row", lax)
    monkeypatch.setattr(InMemoryCredentialStore, "get", any_env)
    with pytest.raises(_KILLED):
        await safety_oracle.test_demo_bound_broker_never_reads_a_live_row(InMemoryCredentialStore())


async def test_mutant_name_only_withdraw_check_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    def name_only(permissions: Any) -> None:
        if any("withdraw" in k.lower() for k in permissions):
            raise WithdrawPermissionRejected("x")

    monkeypatch.setattr(perms, "reject_withdraw", name_only)
    monkeypatch.setattr(perm_oracle, "reject_withdraw", name_only)
    with pytest.raises(_KILLED):
        perm_oracle.test_reject_withdraw_refuses_transfer_and_non_json(
            {"Wallet": ["AccountTransfer"]}
        )


async def test_mutant_no_prev_kek_fallback_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    real_init = CredentialBroker.__init__

    def no_prev(self: CredentialBroker, *a: Any, **k: Any) -> None:
        k["prev_kek"] = None
        real_init(self, *a, **k)

    monkeypatch.setattr(CredentialBroker, "__init__", no_prev)
    with pytest.raises(CredentialUnavailable):
        await rot_oracle.test_borrow_mid_rotation_uses_prev_kek()


async def test_mutant_tofu_kcv_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def tofu(self: RotatingBroker, k: Any, kcvs: Any, *, must_exist: bool) -> bool:
        if await kcvs.kcv_for(self._env, k.version) is None:
            enrolment: tuple[str, dict[str, str]] = ("security.kek_enrolled", {})
            await kcvs.record_kcv(self._env, k.version, k.kcv(), audit=enrolment)
        return False

    monkeypatch.setattr(RotatingBroker, "verify_kcv", tofu)
    with pytest.raises(_KILLED):
        await rot_oracle.test_kcv_wrong_kek_not_pinned_when_rows_exist()


# --- round 3: custody / boundary mutants (each must be killed by its real oracle) -------


@pytest.mark.parametrize("fs", [kek_oracle._EXT4])
def test_mutant_ram_check_dropped_killed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fs: int
) -> None:
    monkeypatch.setattr(_kek, "_RAM_FS", frozenset({fs, kek_oracle._TMPFS}))  # RAM check off
    with pytest.raises(_KILLED):
        kek_oracle.test_live_regular_file_rule_is_ram_and_prefix(
            monkeypatch, tmp_path, fs, True, False
        )


def test_mutant_prefix_dropped_killed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(_kek, "_fd_path", lambda fd: _kek.LIVE_FILE_PREFIX + "x")
    with pytest.raises(_KILLED):
        kek_oracle.test_live_regular_file_rule_is_ram_and_prefix(
            monkeypatch, tmp_path, kek_oracle._TMPFS, False, False
        )


async def test_mutant_ack_before_previous_handle_killed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Ack written right after the current handle (before the previous one is drained)."""
    from candleviewer.secrets import service as svc_mod

    real_load = svc_mod.SecretsService._load
    acked = {"done": False}

    async def early(self: svc_mod.SecretsService, source: Any) -> Any:
        k = await real_load(self, source)
        if not acked["done"]:
            acked["done"] = True
            _kek.write_ack("nonce-1234abcd", tmp_path / "ack")
        return k

    monkeypatch.setattr(svc_mod.SecretsService, "_load", early)
    with pytest.raises(_KILLED):
        await svc_oracle.test_ack_written_once_after_all_handles(monkeypatch, tmp_path)


async def test_mutant_fence_recheck_dropped_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    real = CredentialBroker._check_row
    calls = {"n": 0}

    def once(self: CredentialBroker, row: Any, key_id: Any, purpose: str, **kw: Any) -> Any:
        calls["n"] += 1
        return row if calls["n"] % 2 == 0 else real(self, row, key_id, purpose, **kw)

    monkeypatch.setattr(CredentialBroker, "_check_row", once)
    with pytest.raises(_KILLED):
        await safety_oracle.test_destroy_fences_in_flight_borrow(InMemoryCredentialStore())


# --- #2338: the environment comparisons of the KEK lineage (each killed by its oracle) ------


@pytest.mark.parametrize(
    "oracle",
    [
        lambda: lineage_oracle.test_live_kek_refused_outside_live("demo", (KEK_LIVE, 1), None),
        lineage_oracle.test_other_environment_versions_do_not_affect_a_live_boot,
    ],
    ids=["AC-02", "AC-31"],
)
async def test_mutant_version_policy_ignores_environment_killed(
    monkeypatch: pytest.MonkeyPatch, oracle: Callable[[], Awaitable[None]]
) -> None:
    """Mutant: `_check_versions` reads every row as its own environment's (one lineage)."""
    real = SecretsService._check_versions

    async def one_lineage(self: SecretsService, env_name: str, kek: Any, prev: Any) -> None:
        store: Any = self._kcv
        rows = await store.kcv_versions()

        async def relabelled() -> list[Any]:
            return [(env_name, v, kcv, retired) for _, v, kcv, retired in rows]

        store.kcv_versions = relabelled
        try:
            await real(self, env_name, kek, prev)
        finally:
            del store.kcv_versions

    monkeypatch.setattr(SecretsService, "_check_versions", one_lineage)
    with pytest.raises(_KILLED):
        await oracle()


async def test_mutant_dek_aad_ignores_environment_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    real = env.dek_aad
    monkeypatch.setattr(env, "dek_aad", lambda e, c, v: real("demo", c, v))
    with pytest.raises(_KILLED):
        await lineage_oracle.test_wrap_binds_the_process_environment()
