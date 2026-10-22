"""The audit export signing key at boot (#889 S6a-2b; ADR-0039 decisions 2 and 6, Q3): generated
when the environment has none, opened and checked otherwise, re-wrapped at the rotation boot, and
never a reason to latch order entry. On M2's in-memory stores, with the fixed test KEKs; every
signing key is generated in-process, never a fixture (C-13.5)."""

from __future__ import annotations

import asyncio
import copy
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.admin.wiring import secrets_audit_row
from candleviewer.observability.health import HealthStatus
from candleviewer.secrets import _envelope as env
from candleviewer.secrets import _export_custody as custody
from candleviewer.secrets import _export_key
from candleviewer.secrets import _metrics as m
from candleviewer.secrets._kek import LoadedKek
from candleviewer.secrets._rotation import RotatingBroker
from candleviewer.secrets.errors import CredentialUnavailable
from candleviewer.secrets.service import SecretsService
from candleviewer.secrets.store import (
    InMemoryAuthKeyStore,
    InMemoryCredentialStore,
    InMemoryExportKeyStore,
)
from tests.unit.credentials_m2._service_fakes import KEK_V3, _ctx, _Src, _svc
from tests.unit.credentials_m2._vectors import KEK_V1, KEK_V2, AuditLog, kek
from tests.unit.credentials_m2.test_export_key_kek import _real
from tests.unit.credentials_m2.test_export_key_store import ROTATED, rotation_request

_OWNER = {"actor_kind": "system", "actor_role": "secrets"}
_BOOLEANS = {"retired_material_destroyed"}  # the audit port's JSON booleans


async def _booted(
    keys: InMemoryExportKeyStore, cur: _Src, prev: _Src | None = None, *,
    store: InMemoryCredentialStore, audit: AuditLog | None = None,
) -> tuple[SecretsService, Any]:  # fmt: skip
    keyring, ctx = InMemoryAuthKeyStore(), _ctx()
    svc = _svc(cur, prev, store=store, audit=audit, auth_keys=keyring, export_keys=keys)
    await svc.start(ctx)
    return svc, ctx


async def _first() -> tuple[InMemoryExportKeyStore, InMemoryCredentialStore]:
    """A demo environment whose first boot, under KEK v1, generated its signing key."""
    keys, store = InMemoryExportKeyStore(), InMemoryCredentialStore()
    await _booted(keys, _Src(KEK_V1, 1), store=store)
    return keys, store


async def _retired_with_seed() -> tuple[InMemoryExportKeyStore, InMemoryCredentialStore]:
    """v1 retired by a rotation to v2 (wrapped under KEK v1) that kept its seed: Q3's finding."""
    keys, store = await _first()
    v1, kept, v2 = keys.rows[0]["key_id"], keys.rows[0]["sealed_seed"], _real(2, kek(KEK_V1, 1))
    await keys.rotate(v2 | rotation_request(), retire=v1, reason="scheduled", audit=ROTATED)
    keys.rows[0]["sealed_seed"] = kept
    return keys, store


async def _down_io(*_: object) -> Any:
    raise RuntimeError("store down")


def _down(svc: SecretsService, ctx: Any) -> tuple[str, bool, float]:
    """Why export is unavailable (`""` once it opens), whether order entry is latched, and the
    page's gauge."""
    gauge = float(m.export_key_unavailable_state._value.get())
    return svc.health().detail, ctx.oms_read_only_gate.is_read_only, gauge


def _steps_failed() -> tuple[float, float]:
    """`cv_audit_signing_key_boot_failures_total` for Q3's destroy and the re-wrap."""
    count = m.export_key_boot_failures_total
    return count.labels(step="destroy")._value.get(), count.labels(step="rewrap")._value.get()


async def test_a_boot_with_no_key_generates_version_1_with_its_record() -> None:
    keys, store = InMemoryExportKeyStore(), InMemoryCredentialStore()
    svc, ctx = await _booted(keys, _Src(KEK_V1, 1), store=store)
    assert _down(svc, ctx) == ("", False, 0) and svc.health().status is HealthStatus.OK
    [row], [(action, fields)] = keys.rows, keys.audit
    assert (row["version"], row["kek_version"], row["status"]) == (1, 1, "active")
    ids = {"key_id": row["key_id"], "fingerprint_sha256": row["fingerprint_sha256"]}
    assert (action, fields) == (custody.GENERATED, _OWNER | {"env": "demo", "version": "1"} | ids)
    custody._check(kek(KEK_V1, 1), row)  # the stored key opens to its public key
    svc, ctx = await _booted(keys, _Src(KEK_V1, 1), store=store)  # a later boot opens it
    assert (len(keys.rows), len(keys.audit), _down(svc, ctx)) == (1, 1, ("", False, 0))


async def test_a_lost_generation_race_checks_the_winner_s_key() -> None:
    """Another boot stored its key between our read and our insert: ours is not stored, no record
    is ours, and the winner's key, read again, is checked like ours."""
    keys, store = await _first()  # the winner's key
    real, reads = keys.active, []

    async def raced(env_name: str) -> dict[str, Any] | None:
        reads.append(env_name)
        return None if len(reads) == 1 else await real(env_name)

    setattr(keys, "active", raced)  # noqa: B010 -- read before the winner committed
    with capture_logs() as logs:
        svc, ctx = await _booted(keys, _Src(KEK_V1, 1), store=store)
    assert (len(reads), len(keys.rows), len(keys.audit), _down(svc, ctx)) == (
        2, 1, 1, ("", False, 0)
    )  # fmt: skip
    lost = [e["log_level"] for e in logs if e["event"] == "secrets.export_key_generation_lost"]
    assert lost == ["debug"]


async def test_a_generation_record_that_fails_at_boot_leaves_no_latch_and_no_key() -> None:
    keys, store, audit = InMemoryExportKeyStore(), InMemoryCredentialStore(), AuditLog()
    keys.audit_fails = True  # the key and its record commit together, or neither does
    with capture_logs() as logs:
        svc, ctx = await _booted(keys, _Src(KEK_V1, 1), store=store, audit=audit)
    assert (keys.rows, keys.audit) == ([], [])
    assert _down(svc, ctx) == ("export_key_generation_failed", False, 1)
    record = {"env": "demo", "reason": "export_key_generation_failed"}  # at error: it pages
    assert audit.records[-1] == (custody.UNAVAILABLE, _OWNER | record)
    paged = [e["log_level"] for e in logs if e["event"] == "secrets.export_key_unavailable"]
    assert paged == ["critical"] and (await svc.verify_kek_possession()).kcv_ok
    [failed] = [e for e in logs if e["event"] == "secrets.export_key_open_failed"]
    assert (failed["reason"], failed["error"]) == ("export_key_generation_failed", "RuntimeError")


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"sealed_seed": bytes(60)}, "export_key_unopenable"),
        ({"dek_ref": "ek1:" + "00" * 60}, "export_key_unopenable"),
        ({"status": "retired", "sealed_seed": None}, "export_key_inactive"),
        ({"kek_version": 2}, "export_key_mismatch"),  # above any KEK it holds, as `_auth_keyring`
    ],
    ids=["seal", "wrap", "none_active", "version_above"],
)
async def test_a_key_that_cannot_be_used_is_never_generated_over_and_pages(
    change: dict[str, Any], reason: str
) -> None:
    """Its seal or its wrap does not open, keys exist and none is active (an out-of-band
    retire), or it names a KEK version above this process's."""
    keys, store = await _first()
    keys.rows[0] |= change
    before = copy.deepcopy((keys.rows, keys.audit))
    svc, ctx = await _booted(keys, _Src(KEK_V1, 1), store=store)
    assert (keys.rows, keys.audit) == before
    assert _down(svc, ctx) == (reason, False, 1)


async def test_the_rotation_boot_rewraps_the_key_with_its_record() -> None:
    """The final check opens the key as stored, under the new KEK, not the row read before."""
    keys, store = await _first()
    old, checked, check = keys.rows[0]["dek_ref"], [], custody._check

    def spied(holder: LoadedKek, rec: Any) -> None:
        checked.append((holder.version, rec["kek_version"], rec["dek_ref"] == old))
        check(holder, rec)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(custody, "_check", spied)
        svc, _ = await _booted(keys, _Src(KEK_V2, 2), _Src(KEK_V1, 1), store=store)
    [row], (action, fields) = keys.rows, keys.audit[-1]
    assert (row["kek_version"], row["dek_ref"] != old, svc.health().status) == (
        2, True, HealthStatus.OK
    )  # fmt: skip
    assert (action, fields["key_id"], fields["from"], fields["to"]) == (
        custody.REWRAPPED, row["key_id"], "1", "2"
    )  # fmt: skip
    assert checked == [(2, 2, False)]
    alone, _ = await _booted(keys, _Src(KEK_V2, 2), store=store)  # v1 is gone: v2 opens it
    assert alone.health().status is HealthStatus.OK


async def test_a_key_left_under_the_previous_kek_strands_and_latches_no_order_entry() -> None:
    """The rotation boot's re-wrap fails (its record): the key still opens under v1, the re-wrap
    run is incomplete with it counted, and the next rotation strands it; nothing latches."""
    keys, store = await _first()
    keys.audit_fails, audit, before = True, AuditLog(), _steps_failed()
    with capture_logs() as logs:
        svc, _ = await _booted(keys, _Src(KEK_V2, 2), _Src(KEK_V1, 1), store=store, audit=audit)
    assert (keys.rows[0]["kek_version"], svc.health().status) == (1, HealthStatus.OK)
    assert _steps_failed() == (before[0], before[1] + 1)
    [step] = [e for e in logs if e["event"] == "secrets.export_key_boot_step_failed"]
    assert (step["step"], step["error"], step["log_level"]) == ("rewrap", "RuntimeError", "error")
    report = await svc.rewrap_deks(2, environment="demo", actor_user_id="o", actor_role="owner")
    assert (report.remaining, report.complete, audit.records[-1][1]["export_left"]) == (
        1, False, "1"
    )  # fmt: skip
    svc, ctx = await _booted(keys, _Src(KEK_V3, 3), _Src(KEK_V2, 2), store=store)
    assert _down(svc, ctx) == ("export_key_stranded", False, 1)


async def test_a_retired_key_still_holding_its_seed_loses_it_at_boot_with_its_record() -> None:
    """Q3, at the rotation boot: the finding is logged, and the destroy and the re-wrap each
    commit with their record, as every production call to them must (S6a-1's security lens, F1)."""
    keys, store = await _retired_with_seed()
    v1 = (keys.rows[0]["key_id"], keys.rows[0]["fingerprint_sha256"])
    with capture_logs() as logs:
        svc, _ = await _booted(keys, _Src(KEK_V2, 2), _Src(KEK_V1, 1), store=store)
    assert [r["sealed_seed"] is None for r in keys.rows] == [True, False]
    (destroyed, fields), (rewrapped, _) = keys.audit[-2:]
    assert (destroyed, rewrapped, fields["destroyed"], fields["retired_material_destroyed"]) == (
        custody.DESTROYED, custody.REWRAPPED, "1", "true"
    )  # fmt: skip
    assert (fields["key_ids"], fields["fingerprints_sha256"]) == v1  # S6b, security F3
    found = [
        (e["log_level"], e["retired_with_seed"])
        for e in logs
        if e["event"] == "secrets.export_key_retired_with_seed"
    ]
    assert found == [("error", 1)] and svc.health().status is HealthStatus.OK


async def test_every_boot_record_is_registered_and_kept_whole_at_its_severity() -> None:
    """SR-E42-11: each record as the boot emits it, through the audit row builder, is registered
    and keeps every member (names the redactor keeps); the key's at info, Q3's and the page's at
    error."""
    keys, store = await _retired_with_seed()  # generated
    await _booted(keys, _Src(KEK_V2, 2), _Src(KEK_V1, 1), store=store)  # destroyed, re-wrapped
    keys.rows[1]["sealed_seed"], audit = bytes(60), AuditLog()
    await _booted(keys, _Src(KEK_V2, 2), store=store, audit=audit)  # unavailable
    emitted = dict(keys.audit) | dict(audit.records)
    levels = {custody.GENERATED: "info", custody.REWRAPPED: "info"}
    levels |= {custody.DESTROYED: "error", custody.UNAVAILABLE: "error"}
    for action, severity in levels.items():
        fields = emitted[action]
        whole = {k: v == "true" if k in _BOOLEANS else v for k, v in fields.items()}
        row = secrets_audit_row("demo")(action, fields)
        assert (row["object_kind"], row["severity"], row["after_state"]) == (
            "audit_signing_key", severity, whole
        ), action  # fmt: skip


async def test_a_store_that_cannot_be_read_degrades_export_alone() -> None:
    """Its record at error lost too, to an audit outage: the page stands, and the loss counts."""
    keys, store = await _first()

    class Lost(AuditLog):
        async def __call__(self, action: str, fields: dict[str, str]) -> None:
            if action == custody.UNAVAILABLE:
                raise RuntimeError("audit down")

    setattr(keys, "active", _down_io)  # noqa: B010 -- a store that cannot be read
    lost = m.credential_outcome_audit_failures_total._value.get()
    svc, ctx = await _booted(keys, _Src(KEK_V1, 1), store=store, audit=Lost())
    assert _down(svc, ctx) == ("export_key_store_unavailable", False, 1)
    assert m.credential_outcome_audit_failures_total._value.get() == lost + 1


async def test_a_wrap_not_proven_to_open_stores_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(LoadedKek, "unwrap_export_dek", lambda *_, **__: bytearray(32))
    with pytest.raises(CredentialUnavailable, match=r"^export_key_wrap_mismatch$"):
        custody._wrap_verified(kek(KEK_V1, 1), env.new_dek(), "cv-audit-export-v1:" + "a" * 16)
    keys, store = InMemoryExportKeyStore(), InMemoryCredentialStore()
    svc, ctx = await _booted(keys, _Src(KEK_V1, 1), store=store)
    assert keys.rows == [] and _down(svc, ctx) == ("export_key_generation_failed", False, 1)


@pytest.mark.parametrize(
    ("change", "error", "code"),
    [
        ({"dek_ref": "ek1:" + "00" * 60}, "InvalidTag", "error"),
        ({"sealed_seed": bytes(60)}, "CredentialUnavailable", "credential_unavailable"),
    ],
    ids=["wrap", "seal"],
)
async def test_a_key_the_rotation_boot_cannot_open_is_neither_moved_nor_used(
    change: dict[str, Any], error: str, code: str
) -> None:
    """Q3's step fails too: each failed step is counted and logged by its error's class and its
    bounded reason, an M2 refusal's code, alone."""
    keys, store = await _first()
    keys.rows[0] |= change
    setattr(keys, "count_retired_with_seed", _down_io)  # noqa: B010 -- Q3's step fails too
    before = _steps_failed()
    with capture_logs() as logs:
        svc, ctx = await _booted(keys, _Src(KEK_V2, 2), _Src(KEK_V1, 1), store=store)
    assert keys.rows[0]["kek_version"] == 1
    assert _down(svc, ctx) == ("export_key_unopenable", False, 1)
    assert _steps_failed() == (before[0] + 1, before[1] + 1)
    events = [e for e in logs if e["event"] == "secrets.export_key_boot_step_failed"]
    failed = [(e["step"], e["error"], e["code"]) for e in events]
    assert failed == [("destroy", "RuntimeError", "error"), ("rewrap", error, code)]


async def test_a_key_whose_seed_derives_another_public_key_is_a_mismatch() -> None:
    """Decision 4: a row whose public key is not its seed's is refused, even when its seal binds
    that public key (a forged row), and it is never generated over."""
    keys, store = await _first()
    dek, seed, other = env.new_dek(), _export_key.new_seed(), _real(1, kek(KEK_V1, 1))
    pk, key_id = other["public_key"], other["key_id"]  # another key's public key and id
    forged = env.seal(dek, seed, env.export_seed_aad("demo", key_id, pk))
    ref = kek(KEK_V1, 1).wrap_export_dek(dek, key_id=key_id)
    keys.rows[0] |= {"key_id": key_id, "public_key": pk, "sealed_seed": forged, "dek_ref": ref}
    svc, ctx = await _booted(keys, _Src(KEK_V1, 1), store=store)
    assert _down(svc, ctx) == ("export_key_mismatch", False, 1) and len(keys.rows) == 1


async def test_a_row_of_another_environment_never_opens() -> None:
    """C-2.11: the seed opens under the process environment, never the row's: a live key whose DEK
    a demo KEK wraps, served to a demo process by a store that strayed, is refused."""
    keys, store = await _first()
    live = _real(1, kek(KEK_V1, 1), env_name="live")

    async def strayed(env: str) -> dict[str, Any] | None:
        return keys.rows[0] | live

    keys.active = strayed  # type: ignore[method-assign]
    svc, ctx = await _booted(keys, _Src(KEK_V1, 1), store=store)
    assert _down(svc, ctx) == ("export_key_unopenable", False, 1)


async def test_a_cancelled_check_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Not the key's doing: the check lets it through, never a mismatch."""
    keys, _ = await _first()

    def cancelled(*_: object, **__: object) -> bytearray:
        raise asyncio.CancelledError

    monkeypatch.setattr(LoadedKek, "unwrap_export_dek", cancelled)
    with pytest.raises(asyncio.CancelledError):
        custody._check(kek(KEK_V1, 1), keys.rows[0])


async def test_a_boot_cancelled_at_the_signing_key_zeroes_and_unpublishes_the_kek(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Code lens m6: the KEK is published before the signing key opens; a cancellation there
    zeroes both KEKs and latches, as any cancelled boot does, and propagates."""
    keys, store = await _first()
    dropped: list[RotatingBroker] = []
    drop = RotatingBroker.drop_kek

    def spied(self: RotatingBroker) -> None:
        dropped.append(self)
        drop(self)

    async def cancelled(*_: object) -> str | None:
        raise asyncio.CancelledError

    monkeypatch.setattr(RotatingBroker, "drop_kek", spied)
    monkeypatch.setattr(custody, "open_at_boot", cancelled)
    svc, ctx = _svc(_Src(KEK_V2, 2), _Src(KEK_V1, 1), store=store, export_keys=keys), _ctx()
    with pytest.raises(asyncio.CancelledError):
        await svc.start(ctx)
    [broker] = dropped
    assert (broker._kek, broker._prev, svc.health().detail) == (None, None, "kek_unavailable")
    assert ctx.oms_read_only_gate.is_read_only
    assert not (await svc.verify_kek_possession()).kcv_ok  # the broker is unpublished


async def test_a_boot_step_that_raises_degrades_export_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(custody, "open_at_boot", _down_io)  # say, a record M2 cannot read
    keys, store = InMemoryExportKeyStore(), InMemoryCredentialStore()
    with capture_logs() as logs:
        svc, ctx = await _booted(keys, _Src(KEK_V1, 1), store=store)
    assert _down(svc, ctx) == ("export_key_unopenable", False, 1)
    [failed] = [e for e in logs if e["event"] == "secrets.export_key_open_failed"]
    assert failed["error"] == "RuntimeError"


async def test_no_seed_or_dek_is_in_a_log_a_record_or_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-12.6: every seed and DEK made here, copied as made (M2 zeroes its own), is in no log,
    no record, no health detail, and no failure of the check, which chains nothing."""
    made: list[bytes] = []

    def recorded(make: Any) -> Any:
        def wrapper() -> bytearray:
            out: bytearray = make()
            made.append(bytes(out))
            return out

        return wrapper

    monkeypatch.setattr(env, "new_dek", recorded(env.new_dek))
    monkeypatch.setattr(_export_key, "new_seed", recorded(_export_key.new_seed))
    with capture_logs() as logs:
        keys, store = await _first()
        svc, _ = await _booted(keys, _Src(KEK_V2, 2), _Src(KEK_V1, 1), store=store)
        keys.rows[0]["sealed_seed"] = bytes(60)
        broken, _ = await _booted(keys, _Src(KEK_V2, 2), store=store)
    with pytest.raises(CredentialUnavailable) as failed:
        custody._check(kek(KEK_V2, 2), keys.rows[0])
    assert failed.value.__context__ is None and failed.value.__cause__ is None
    seen = repr((logs, keys.audit, svc.health(), broken.health(), failed.value))
    assert len(made) == 2 and not [s for s in made if s.hex() in seen or repr(s) in seen]
