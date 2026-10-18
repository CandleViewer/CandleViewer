"""`AdminService.rewrap_kek` (#2266 PR D1): one KEK re-wrap run for the Owner through M2's metadata
facade, answered with the `rewrapKek` counts (no key id, no KCV), and each M2 refusal or failure
mapped to the contract's error code. Nothing outside `admin/` calls it yet (the route is D2)."""

from __future__ import annotations

import dataclasses
from typing import Any, get_args
from uuid import UUID

import pytest

from candleviewer.admin.errors import KekRewrapError
from candleviewer.admin.models import KekRewrapResult
from candleviewer.admin.service import AdminService
from candleviewer.secrets import (
    KekCheckResult,
    KekRotationError,
    KekUnavailable,
    RewrapReport,
    SecretsMetadataFacade,
)
from candleviewer.secrets.errors import RotationCode
from candleviewer.secrets.store import InMemoryAuthKeyStore, InMemoryCredentialStore
from tests.contract._admin_support import SPEC
from tests.unit.credentials_m2._service_fakes import _staged
from tests.unit.credentials_m2._vectors import AuditLog


async def _admin(auth: InMemoryAuthKeyStore) -> tuple[AdminService, InMemoryCredentialStore, Any]:
    """The rotation boot (`_staged`) behind M2's metadata facade."""
    audit = AuditLog()
    svc, _, store = await _staged(audit, auth)
    return AdminService(secrets=SecretsMetadataFacade(svc)), store, audit


def test_the_result_has_exactly_the_contract_members() -> None:
    schema = SPEC["components"]["schemas"]["KekRewrapResult"]
    assert [f.name for f in dataclasses.fields(KekRewrapResult)] == schema["required"]


async def test_a_staged_run_answers_counts_and_no_key_id_or_kcv() -> None:
    admin, store, audit = await _admin(InMemoryAuthKeyStore())
    result = await admin.rewrap_kek("demo", 2, "owner-1")
    assert dataclasses.astuple(result)[1:] == ("demo", 1, 2, False, 2, 0, 0, True)
    assert str(result.run_id) == audit.records[-1][1]["run_id"]
    hidden = [str(k) for k in store.rows] + [kcv.hex() for kcv in store.kcvs.values()]
    assert not [h for h in hidden if h in repr(result)]
    assert audit.records[-1][1]["actor_role"] == "owner"


async def test_a_keyring_row_left_answers_incomplete_with_the_row_counted() -> None:
    """#3505: API key rows all moved, an auth keyring row still at v1: no `kek_rotated`."""
    auth = InMemoryAuthKeyStore()
    auth.rows.append({"env": "demo", "kek_version": 1})
    admin, _, audit = await _admin(auth)
    result = await admin.rewrap_kek("demo", 2, "owner-1")
    assert (result.rewrapped, result.remaining, result.complete) == (2, 1, False)
    assert "security.kek_rotated" not in audit.actions()


async def test_a_row_that_cannot_be_rewrapped_is_counted_as_failed_with_no_key_id() -> None:
    admin, store, _ = await _admin(InMemoryAuthKeyStore())
    store.rows[min(store.rows)]["dek_ref"] = "v2:" + bytes(40).hex()  # v1 cannot open this wrap
    result = await admin.rewrap_kek("demo", 2, "owner-1")
    assert (result.rewrapped, result.remaining, result.failed, result.complete) == (1, 1, 1, False)
    assert not [k for k in store.rows if str(k) in repr(result)]


async def test_a_call_after_a_run_that_moved_a_row_and_aborted_answers_resumed() -> None:
    admin, store, _ = await _admin(InMemoryAuthKeyStore())
    cas = store.rewrap

    async def down_after_one_row(key_id: UUID, **kw: Any) -> bool:
        if store.rewrap_audit:
            raise RuntimeError("store down")
        return await cas(key_id, **kw)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(store, "rewrap", down_after_one_row)
        with pytest.raises(KekRewrapError, match="store_unavailable"):
            await admin.rewrap_kek("demo", 2, "owner-1")
    result = await admin.rewrap_kek("demo", 2, "owner-1")
    assert (result.resumed, result.rewrapped, result.remaining) == (True, 1, 0)


class _Refusing:
    """A metadata capability whose re-wrap raises `exc`."""

    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def verify_kek_possession(self) -> KekCheckResult:
        return KekCheckResult(None, False, "kek_unavailable")

    async def rewrap_deks(
        self, to_version: int, *, environment: str, actor_user_id: str, actor_role: str
    ) -> RewrapReport:
        raise self.exc


@pytest.mark.parametrize(
    ("exc", "code"),
    [(KekUnavailable("kek_unavailable"), "kek_unavailable")]
    + [(KekRotationError(c), c) for c in get_args(RotationCode)],
    ids=["kek_unavailable", *get_args(RotationCode)],
)
async def test_each_m2_refusal_or_failure_maps_to_its_contract_code(
    exc: Exception, code: str
) -> None:
    with pytest.raises(KekRewrapError) as err:
        await AdminService(secrets=_Refusing(exc)).rewrap_kek("demo", 2, "owner-1")
    assert err.value.code == code


async def test_no_m2_capability_records_no_refusal_and_answers_audit_unavailable() -> None:
    with pytest.raises(KekRewrapError) as err:
        await AdminService().rewrap_kek("demo", 2, "owner-1")
    assert err.value.code == "audit_unavailable"
