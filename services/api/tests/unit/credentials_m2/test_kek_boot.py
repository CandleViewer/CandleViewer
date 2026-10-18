"""KEK boot (#2266 PR C): the previous KEK is verified before a new KCV is enrolled, an enrolment
commits with its `security.kek_enrolled` record, and unrevoked rows at a KEK version the process
did not load degrade it while it keeps the broker (e27-kek.md §6), on M2's in-memory store."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from candleviewer.observability.health import HealthStatus
from candleviewer.secrets import _metrics as m
from candleviewer.secrets.errors import CredentialUnavailable, KekUnavailable
from candleviewer.secrets.service import SecretsService
from candleviewer.secrets.store import InMemoryCredentialStore
from tests.unit.credentials_m2._service_fakes import (
    KEK_V3,
    _borrow,
    _ctx,
    _Src,
    _store_one,
    _svc,
    _zeroed,
)
from tests.unit.credentials_m2._vectors import KEK_V1, KEK_V2, AuditLog

_LOADED, _STRANDED = "security.kek_loaded", "security.kek_rows_stranded"
_SYSTEM = {"actor_kind": "system", "actor_role": "secrets", "env": "demo"}


async def _start(
    store: InMemoryCredentialStore, *srcs: _Src, audit: AuditLog | None = None
) -> tuple[SecretsService, Any]:
    svc, ctx = _svc(*srcs, store=store, audit=audit), _ctx()
    await svc.start(ctx)
    return svc, ctx


async def _mid_rotation() -> tuple[InMemoryCredentialStore, UUID, UUID]:
    """A key stored under v1, the rotation boot (v2 beside v1), a key stored under v2 and no
    re-wrap: the first key is still at v1."""
    store = InMemoryCredentialStore()
    old = await _store_one((await _start(store, _Src(KEK_V1, 1)))[0])
    new = await _store_one((await _start(store, _Src(KEK_V2, 2), _Src(KEK_V1, 1)))[0])
    return store, old.key_id, new.key_id


class _NoStrandedRecord(AuditLog):
    async def __call__(self, action: str, fields: dict[str, str]) -> None:
        if action == _STRANDED:
            raise RuntimeError("audit down")
        await super().__call__(action, fields)


async def test_a_wrong_previous_kek_is_refused_before_the_new_kcv_is_enrolled() -> None:
    """#2266 item 6: verified first, a wrong previous KEK never pins v(n+1)."""
    store = InMemoryCredentialStore()
    await _start(store, _Src(KEK_V1, 1))
    enrolled, audit = list(store.kcv_audit), AuditLog()
    svc, _ = await _start(store, _Src(KEK_V2, 2), _Src(KEK_V3, 1), audit=audit)
    assert svc.health().detail == "kek_mismatch" and ("demo", 2) not in store.kcvs
    assert store.kcv_audit == enrolled and audit.actions() == ["security.kek_load_failed"]


async def test_an_enrolment_commits_its_record_with_the_kcv_row_not_through_the_sink() -> None:
    store, audit = InMemoryCredentialStore(), AuditLog()
    await _start(store, _Src(KEK_V1, 1), audit=audit)
    await _start(store, _Src(KEK_V1, 1))  # enrolled already: no second record
    fields = {**_SYSTEM, "kek_version": "1", "kcv": store.kcvs[("demo", 1)].hex()}
    assert store.kcv_audit == [("security.kek_enrolled", fields)] and audit.actions() == [_LOADED]


async def test_stranded_rows_latch_first_then_page_and_audit_then_publish_the_broker() -> None:
    store, _, _ = await _mid_rotation()
    audit, ctx = AuditLog(), _ctx()
    svc = _svc(_Src(KEK_V2, 2), store=store, audit=audit)
    at_latch: list[tuple[str | None, bool, list[str]]] = []
    ctx.oms_read_only_gate.subscribe(
        lambda _ro, code, _text: at_latch.append((code, svc._broker is None, audit.actions()))
    )
    failures = m.kek_load_failures_total.labels(reason="kek_rows_stranded")
    before = failures._value.get()
    m.kek_degraded_state.set(0)
    await svc.start(ctx)
    assert at_latch == [("secrets.kek_rows_stranded", True, [_LOADED])]
    assert audit.records[1:] == [(_STRANDED, {**_SYSTEM, "kek_version": "2", "stranded": "1"})]
    report, text = svc.health(), ctx.oms_read_only_gate.reason_text or ""
    assert (report.status, report.detail) == (HealthStatus.DEGRADED, "kek_rows_stranded")
    assert "CV_KEK_PREV_HANDLE" in text and "revoke" in text
    assert failures._value.get() == before + 1 and m.kek_degraded_state._value.get() == 1
    assert m.kek_version._value.get() == 2


async def test_a_stranded_key_fails_closed_while_the_other_keys_sign() -> None:
    store, old, new = await _mid_rotation()
    svc, _ = await _start(store, _Src(KEK_V2, 2))
    with pytest.raises(CredentialUnavailable):
        await _borrow(svc, old)
    assert await _borrow(svc, new) == "ABCD1234"
    check = await svc.verify_kek_possession()
    assert (check.version, check.kcv_ok, check.reason) == (2, True, "kek_rows_stranded")


async def test_a_stranded_key_is_destroyed_with_its_record_and_the_next_boot_is_ok() -> None:
    """Recovery (b), v(n) lost: `destroy` needs no KEK, so the revoke path stays reachable."""
    store, old, _ = await _mid_rotation()
    audit = AuditLog()
    svc, _ = await _start(store, _Src(KEK_V2, 2), audit=audit)
    await svc._require().destroy(old)
    assert audit.actions()[-1] == "security.credential_destroyed" and store.rows[old]["revoked"]
    again, ctx = await _start(store, _Src(KEK_V2, 2))
    assert again.health().status is HealthStatus.OK and not ctx.oms_read_only_gate.is_read_only


@pytest.mark.parametrize(
    ("change", "loaded"),
    [({}, 2), ({"revoked": True}, 1), ({"status": "revoked"}, 1), ({"env": "live"}, 1)],
    ids=["previous_kek_loaded", "revoked_at", "status_revoked", "other_environment"],
)
async def test_no_row_is_stranded_that_the_boot_can_open_or_never_signs(
    change: dict[str, Any], loaded: int
) -> None:
    store, old, _ = await _mid_rotation()
    store.rows[old].update(change)
    svc, ctx = await _start(store, *[_Src(KEK_V2, 2), _Src(KEK_V1, 1)][:loaded])
    assert svc.health().status is HealthStatus.OK and not ctx.oms_read_only_gate.is_read_only
    assert (await svc.verify_kek_possession()).reason is None


async def _down(env: str, *loaded_versions: int) -> int:
    raise RuntimeError("db down")


@pytest.mark.parametrize(
    ("count", "audit", "reason", "records"),
    [
        (_down, AuditLog, "kcv_store_unavailable", []),
        (None, _NoStrandedRecord, "audit_unavailable", [_LOADED]),
    ],
    ids=["count_fails", "record_fails"],
)
async def test_a_stranded_boot_that_cannot_count_or_record_it_degrades_fully(
    count: Any, audit: type[AuditLog], reason: str, records: list[str]
) -> None:
    """The count runs before `security.kek_loaded`; the KEK is published only after both."""
    store, _, new = await _mid_rotation()
    store.count_stranded = count or store.count_stranded  # type: ignore[method-assign]
    src, log = _Src(KEK_V2, 2), audit()
    svc, ctx = await _start(store, src, audit=log)
    gate = ctx.oms_read_only_gate
    assert svc.health().detail == reason and gate.reason_code == "secrets.kek_unavailable"
    assert log.actions() == [*records, "security.kek_load_failed"] and _zeroed(src)
    with pytest.raises(KekUnavailable):
        await _borrow(svc, new)
