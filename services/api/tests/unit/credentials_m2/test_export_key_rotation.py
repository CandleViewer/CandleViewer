"""The audit export signing key's rotation in M2 (#889 S7; ADR-0039 decisions 4, 5 and 6, Q3): 22's
order of answers, the rotation committed with its record, a failed one's record, the latch it
clears with no restart, and the `verified` marks. Every key is generated in-process (C-13.5)."""

from __future__ import annotations

import asyncio
import pickle
from collections.abc import Iterable, Mapping
from typing import Any
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from structlog.testing import capture_logs

from candleviewer.observability.health import HealthStatus
from candleviewer.secrets import _export_custody as custody
from candleviewer.secrets import _metrics as m
from candleviewer.secrets import export_rotator as rot
from candleviewer.secrets import export_signer
from candleviewer.secrets.errors import CredentialUnavailable, ExportKeyRotationError
from candleviewer.secrets.export_rotator import SigningKeyRotator
from candleviewer.secrets.service import (
    mint_export_signer,
    mint_signing_key_rotator,
    mint_signing_keys,
)
from candleviewer.secrets.store import (
    EXPORT_KEY_PUBLIC,
    InMemoryAuthKeyStore,
    InMemoryExportKeyStore,
)
from tests.unit.credentials_m2._service_fakes import _ctx, _Src, _svc
from tests.unit.credentials_m2._vectors import KEK_V1, AuditLog
from tests.unit.credentials_m2.test_export_key_boot import _down
from tests.unit.credentials_m2.test_export_signer import DIGEST, MESSAGE, _made

OWNER, BODY = UUID(int=1), "b" * 64
_HOUR = 3600.0


class _Rig:
    """A demo process booted under KEK v1, which generated v1, its capabilities minted as wiring
    mints them, its rotation clock `now` and an export job running while `exporting`."""

    def __init__(self) -> None:
        self.keys, self.audit = InMemoryExportKeyStore(), AuditLog()
        self.now, self.exporting = 0.0, False
        self.svc = _svc(_Src(KEK_V1, 1), audit=self.audit, auth_keys=InMemoryAuthKeyStore(),
                        export_keys=self.keys)  # fmt: skip
        self.svc._clock = lambda: self.now
        self.rotator = mint_signing_key_rotator(self.svc)
        self.directory = mint_signing_keys(self.svc)

    async def start(self, **settings: Any) -> _Rig:
        self.ctx = _ctx(**settings)
        await self.svc.start(self.ctx)
        self.booted, self.v1 = len(self.audit.records), self.keys.rows[0]
        return self

    def written(self) -> list[tuple[str, dict[str, str]]]:
        return self.audit.records[self.booted :]  # M2's own records since boot

    async def rotate(
        self, reason: str = "scheduled", *, ref: UUID | None = None, owner: UUID = OWNER,
        body: str = BODY,
    ) -> tuple[rot.Rotation, bool]:  # fmt: skip
        return await self.rotator.rotate(
            reason, actor_user_id=owner, client_ref=ref or uuid4(), client_body_sha256=body,
            export_running=lambda: self.exporting,
        )  # fmt: skip

    async def refused(self, code: str, **call: Any) -> ExportKeyRotationError:
        rows = [dict(r) for r in self.keys.rows]
        with pytest.raises(ExportKeyRotationError, match=rf"^{code}$") as refused:
            await self.rotate(**call)
        assert self.keys.rows == rows and refused.value.__context__ is None  # nothing rotated
        return refused.value


async def _rig() -> _Rig:
    return await _Rig().start()


async def _swapped(rig: _Rig, version: int) -> str:
    """An active row replaced behind M2's back (AD-T02's class: a direct write, or another
    process): the store's own rotation, never M2's, so no check runs for its key."""
    kek, active = rig.svc._require()._held_keks()[0], rig.keys.rows[-1]["key_id"]
    record = custody.new_key(kek, version) | {"created_by": UUID(int=9), "client_ref": str(uuid4())}
    record["client_body_sha256"] = "d" * 64
    swap = rig.keys.rotate(record, retire=active, reason="compromise", audit=(rot.ROTATED, {}))
    assert await swap is not None and rig.keys.rows[-1]["status"] == "active"
    return str(rig.keys.rows[-1]["key_id"])


def _unchecked(logs: Iterable[Mapping[str, Any]]) -> list[tuple[str, str]]:
    found = [e for e in logs if e["event"] == "secrets.export_key_not_checked"]
    assert all(e["log_level"] == "error" for e in found)
    return [(e["active_key_id"], e["checked_key_id"]) for e in found]


def _owner(**named: str) -> dict[str, str]:
    return {"actor_kind": "user", "actor_role": "owner", "actor_user_id": str(OWNER)} | named


async def test_a_rotation_retires_the_active_key_for_the_next_with_its_record_committed() -> None:
    """Decision 5 and Q3 in one transaction: v1 retired, its seed destroyed, v2 active from the
    record's time with its request, and `security.audit_signing_key_rotated` committed with them
    by the store, never through M2's own sink. The answer is public, each mark M2's."""
    rig, ref = await _rig(), uuid4()
    made, replayed = await rig.rotate("compromise", ref=ref)
    v1, v2 = rig.keys.rows
    retired = (v1["status"], v1["retired_reason"], v1["sealed_seed"])
    assert retired == ("retired", "compromise", None)  # Q3: the seed destroyed with the retire
    assert v1["valid_until"] == v2["valid_from"] and v2["status"] == "active" and not replayed
    assert (v2["created_by"], v2["client_ref"], v2["client_body_sha256"]) == (OWNER, str(ref), BODY)
    ids = {"active_key_id": v2["key_id"], "retired_key_id": v1["key_id"]}
    fps = {"active_fingerprint_sha256": v2["fingerprint_sha256"]}
    fps["retired_fingerprint_sha256"] = v1["fingerprint_sha256"]
    fields = _owner(env="demo", reason="compromise", retired_material_destroyed="true")
    assert rig.keys.audit[-1] == (rot.ROTATED, fields | ids | fps)
    assert rig.written() == []  # the record is the store's, in the rotation's own transaction
    expect = {k: v2[k] for k in EXPORT_KEY_PUBLIC} | {"verified": True}
    assert made == {"active": expect, "retired": {k: v1[k] for k in EXPORT_KEY_PUBLIC} | {
        "verified": False}}  # fmt: skip


@pytest.mark.parametrize(
    ("cause", "code", "answer"),
    [
        ({"no_kek", "rate", "busy", "exporting"}, "kek_unavailable", "kek_unavailable"),
        ({"rate", "busy", "exporting", "no_key"}, None, "rate_limited"),
        ({"busy", "exporting", "no_key"}, "rotation_in_progress", "conflict"),
        ({"exporting", "no_key"}, "export_in_progress", "conflict"),
        ({"no_key"}, "no_active_key", "conflict"),
    ],
)
async def test_the_refusals_come_in_22s_order_each_recorded_but_the_429(
    cause: set[str], code: str | None, answer: str
) -> None:
    """403 `kek_unavailable`, 429 (counted by the caller, never recorded), then 409 `conflict`
    while a rotation or an export job runs or with no key to retire: the first cause present
    wins, its record names why and the Owner's reason, and nothing rotates."""
    rig = await _rig()
    if "no_kek" in cause:
        rig.svc._broker = None
    if "rate" in cause:
        rig.svc._export_rotations.extend([rig.now - 60] * 3)
    if "busy" in cause:
        rig.svc._export_rotating = (str(uuid4()), str(uuid4()))
    rig.exporting = "exporting" in cause
    if "no_key" in cause:
        rig.v1["status"] = "retired"  # an out-of-band retire: keys exist, none active (Q4)
    refused = await rig.refused(answer, reason="unrecoverable")
    assert refused.retry_after_s == (3540 if answer == "rate_limited" else None)
    named = {"env": "demo", "reason": code, "requested_reason": "unrecoverable"}
    assert rig.written() == ([] if code is None else [(rot.REFUSED, _owner(**named))])


@pytest.mark.parametrize("cause", ["no_kek", "rate", "exporting", "busy"])
async def test_a_committed_key_and_body_get_their_200_while_a_refusals_cause_holds(
    cause: str,
) -> None:
    """22: the refusals apply only once the idempotency lookup finds no earlier answer, so a
    retry whose answer was lost gets the stored 200 with no KEK, the hour's cap used up, an export
    job or another rotation running; and the same key with another body is still reuse. Nothing
    recorded, nothing counted."""
    rig, ref = await _rig(), uuid4()
    first, _ = await rig.rotate(ref=ref)
    if cause == "no_kek":
        rig.svc._broker = None
    if cause == "rate":
        rig.svc._export_rotations.extend([rig.now] * 2)  # with the first: the cap of 3
    rig.exporting = cause == "exporting"
    if cause == "busy":
        rig.svc._export_rotating = (str(uuid4()), str(uuid4()))
    starts, records = list(rig.svc._export_rotations), list(rig.keys.audit)
    again, replayed = await rig.rotate(ref=ref)
    assert replayed and again["active"]["key_id"] == first["active"]["key_id"]
    await rig.refused("idempotency_key_reuse", ref=ref, body="c" * 64)
    assert (rig.written(), rig.keys.audit, list(rig.svc._export_rotations)) == ([], records, starts)


async def test_a_refusal_whose_record_cannot_be_written_is_audit_unavailable() -> None:
    rig = await _rig()
    rig.exporting, rig.audit.fail = True, True
    await rig.refused("audit_unavailable")


async def test_a_repeat_gets_its_200_at_any_age_and_rotates_nothing() -> None:
    """Decision 5: the 200 rebuilt from the key rows a day on, its key as it was then."""
    rig, ref = await _rig(), uuid4()
    first, _ = await rig.rotate(ref=ref)
    rig.now += 25 * _HOUR
    await rig.rotate()  # v3 retires v2
    rows, records = [dict(r) for r in rig.keys.rows], list(rig.keys.audit)
    again, replayed = await rig.rotate(ref=ref)
    assert replayed and (rig.keys.rows, rig.keys.audit) == (rows, records)
    assert again == {"active": first["active"] | {"verified": False}, "retired": first["retired"]}


async def test_the_key_with_another_body_is_reuse_and_another_owners_is_never_seen() -> None:
    """SR-E29-07 (IDOR): a request is read with its Owner only, so another Owner's same key is a
    first submission, while the same Owner's with another body is `idempotency_key_reuse`."""
    rig, ref = await _rig(), uuid4()
    await rig.rotate(ref=ref)
    await rig.refused("idempotency_key_reuse", ref=ref, body="c" * 64)
    other, replayed = await rig.rotate(ref=ref, owner=UUID(int=2))
    assert not replayed and other["active"]["version"] == 3 and len(rig.keys.rows) == 3


async def test_a_rotation_is_single_flight_and_its_own_repeat_is_in_flight() -> None:
    rig, ref, held, release = await _rig(), uuid4(), asyncio.Event(), asyncio.Event()
    real = rig.keys.rotate

    async def slow(*args: Any, **kw: Any) -> Any:
        held.set()
        async with asyncio.timeout(5):
            await release.wait()
        return await real(*args, **kw)

    async def meanwhile() -> None:
        async with asyncio.timeout(5):
            await held.wait()
        await rig.refused("idempotency_in_flight", ref=ref)  # unrecorded, as idempotency answers
        await rig.refused("conflict")
        release.set()

    setattr(rig.keys, "rotate", slow)  # noqa: B010 -- the first rotation holds its transaction
    (_, replayed), _ = await asyncio.gather(rig.rotate(ref=ref), meanwhile())
    assert not replayed and len(rig.keys.rows) == 2
    assert [f["reason"] for _, f in rig.written()] == ["rotation_in_progress"]


@pytest.mark.parametrize("race", ["taken", "retired", "lost"])
async def test_a_retry_that_raced_its_first_try_reads_it_again(race: str) -> None:
    """Looked up before the first try committed: `ExportKeyRequestTaken`, or the key retired (None),
    reads the rotation again; a key another request retired is `conflict`."""
    rig, ref = await _rig(), uuid4()
    first, _ = await rig.rotate(ref=uuid4() if race == "lost" else ref)
    stale, real = dict(rig.v1, status="active"), rig.keys.rotation
    calls: list[object] = []

    async def late(*args: Any, **kw: Any) -> Any:
        calls.append(args)
        return None if len(calls) == 1 else await real(*args, **kw)

    setattr(rig.keys, "rotation", late)  # noqa: B010 -- the lookup ran before the commit
    if race != "taken":
        setattr(rig.keys, "active", lambda _env: asyncio.sleep(0, stale))  # noqa: B010
    if race == "lost":
        await rig.refused("conflict", ref=ref)
        assert rig.written()[-1][1]["reason"] == "rotation_in_progress"
        return
    again, replayed = await rig.rotate(ref=ref)
    assert replayed and again["active"]["key_id"] == first["active"]["key_id"]
    assert len(rig.keys.rows) == 2 and rig.written() == []


_FAILS = {"store": "store_unavailable", "record": "audit_unavailable", "both": "audit_unavailable"}


@pytest.mark.parametrize(("fails", "code"), _FAILS.items())
async def test_a_rotation_that_does_not_commit_appends_its_failed_record(
    fails: str, code: str
) -> None:
    """Nothing commits and no `rotated` record exists; `security.audit_signing_key_rotation_failed`
    names why, the Owner's reason and the key it would have retired, at error (wiring); a lost
    one is counted and the answer is `audit_unavailable`."""
    rig, lost = await _rig(), m.credential_outcome_audit_failures_total._value.get()

    async def down(*_: object, **__: object) -> Any:
        raise RuntimeError("store down")

    if fails in ("store", "both"):
        setattr(rig.keys, "rotate", down)  # noqa: B010
    rig.keys.audit_fails, rig.audit.fail = fails == "record", fails == "both"
    await rig.refused(code)
    assert [a for a, _ in rig.keys.audit] == ["security.audit_signing_key_generated"]  # boot's
    failed = _owner(env="demo", reason=code if fails != "both" else "store_unavailable")
    failed |= {"requested_reason": "scheduled", "retired_key_id": rig.v1["key_id"]}
    assert rig.written() == ([] if fails == "both" else [(rot.FAILED, failed)])
    assert m.credential_outcome_audit_failures_total._value.get() == lost + (fails == "both")


async def test_a_store_failure_whose_read_back_fails_too_is_recorded_as_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-check A1: `rotate()` fails and so does the read-back that looks for its commit: unread,
    it is recorded as failed (`store_unavailable`), the read-back's failure logged and no
    read-back found (delta A5)."""
    rig = await _rig()
    real, lookups = rig.keys.rotation, []

    async def down(*_: object, **__: object) -> Any:
        raise RuntimeError("store down")

    async def late(*args: Any, **kw: Any) -> Any:
        lookups.append(1)
        if len(lookups) > 1:  # the first lookup answers; the read-back finds the store down
            raise RuntimeError("store down")
        return await real(*args, **kw)

    monkeypatch.setattr(rig.keys, "rotate", down)
    monkeypatch.setattr(rig.keys, "rotation", late)
    with capture_logs() as logs:
        await rig.refused("store_unavailable")
    failed = _owner(env="demo", reason="store_unavailable")
    failed |= {"requested_reason": "scheduled", "retired_key_id": rig.v1["key_id"]}
    assert rig.written() == [(rot.FAILED, failed)] and len(lookups) == 2
    events = [e["event"] for e in logs]
    assert events.count("secrets.export_key_rotation_lookup_failed") == 1
    assert "secrets.export_key_rotation_read_back" not in events


async def test_a_cancelled_read_back_is_never_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Delta A1: the read-back's suppress takes `ExportKeyRotationError` alone, so a cancel passes
    through it unrecorded, and the single-flight is released."""
    rig = await _rig()
    real, lookups = rig.keys.rotation, []

    async def down(*_: object, **__: object) -> Any:
        raise RuntimeError("store down")

    async def cancelled(*args: Any, **kw: Any) -> Any:
        lookups.append(1)
        if len(lookups) > 1:  # the read-back is cancelled
            raise asyncio.CancelledError
        return await real(*args, **kw)

    monkeypatch.setattr(rig.keys, "rotate", down)
    monkeypatch.setattr(rig.keys, "rotation", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await rig.rotate()
    assert (rig.written(), len(lookups), rig.svc._export_rotating) == ([], 2, None)


async def test_a_rotation_whose_answer_is_lost_after_its_commit_is_read_back_not_failed() -> None:
    """Security Low 1, code C2-4: a store failure after the COMMIT (its timeout, say) is read back
    before it is recorded: the rotation's own 200, the new key checked (so a latch clears), and
    no failed record beside the rotated one."""
    rig = await _rig()
    real = rig.keys.rotate

    async def committed_then_timed_out(*args: Any, **kw: Any) -> Any:
        await real(*args, **kw)
        raise TimeoutError

    setattr(rig.keys, "rotate", committed_then_timed_out)  # noqa: B010
    await rig.svc._export_unavailable("export_key_unopenable")  # latched before the rotation
    booted = len(rig.audit.records)
    with capture_logs() as logs:
        made, replayed = await rig.rotate("unrecoverable")
    found = [e for e in logs if e["event"] == "secrets.export_key_rotation_read_back"]
    assert [(e["found"], e["log_level"]) for e in found] == [(True, "info")]  # re-check A5
    v2 = rig.keys.rows[1]
    assert not replayed and (made["active"]["key_id"], made["active"]["verified"]) == (
        v2["key_id"], True
    )  # fmt: skip
    assert rig.keys.audit[-1][0] == rot.ROTATED and rig.audit.records[booted:] == []
    assert _down(rig.svc, rig.ctx) == ("", False, 0)


async def test_an_unrecoverable_rotation_after_a_latch_serves_the_new_key_with_no_restart() -> None:
    """Q4 and decision 6's recovery: a key found unusable at signing time latches export; the
    rotation retires it, and once the new key passes `check_key` the directory names it, the
    signer signs with it, the gauge reads 0 and `secrets` is healthy, in the same process."""
    rig = await _rig()
    signer = mint_export_signer(rig.svc)
    rig.v1["sealed_seed"] = bytes(60)
    with pytest.raises(CredentialUnavailable, match=r"^export_key_unopenable$"):
        await signer.sign_audit_export(rig.v1["key_id"], DIGEST, uuid4(), OWNER)
    assert _down(rig.svc, rig.ctx) == ("export_key_unopenable", False, 1)
    assert await rig.directory.active() is None
    made, _ = await rig.rotate("unrecoverable")
    v2 = rig.keys.rows[1]
    assert made["active"]["verified"] and _down(rig.svc, rig.ctx) == ("", False, 0)
    named = (v2["key_id"], v2["public_key"], v2["fingerprint_sha256"])
    assert await rig.directory.active() == named
    signature = await signer.sign_audit_export(v2["key_id"], DIGEST, uuid4(), OWNER)
    Ed25519PublicKey.from_public_bytes(v2["public_key"]).verify(signature, MESSAGE)
    assert rig.svc.health().status is HealthStatus.OK
    v1 = rig.keys.rows[0]  # the retire is a new row in the fake, as a new tuple is in Postgres
    assert (v1["retired_reason"], v1["sealed_seed"]) == ("unrecoverable", None)


async def _down_io(*_: object, **__: object) -> Any:
    raise RuntimeError("store down")


@pytest.mark.parametrize(
    ("fault", "reason"),
    [("mismatch", "export_key_mismatch"), ("unreadable", "export_key_store_unavailable")],
)
async def test_a_new_key_that_fails_its_check_stays_latched_as_at_boot(
    fault: str, reason: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rotation committed and is answered; its key, failing the read-back, is latched."""
    rig = await _rig()
    real = rig.keys.rotate

    def mismatch(*_: object) -> None:
        raise CredentialUnavailable("export_key_mismatch")

    async def then_unreadable(*args: Any, **kw: Any) -> Any:
        made = await real(*args, **kw)
        setattr(rig.keys, "active", _down_io)  # noqa: B010
        return made

    if fault == "mismatch":
        monkeypatch.setattr(rot, "_check", mismatch)
    else:
        setattr(rig.keys, "rotate", then_unreadable)  # noqa: B010
    made, _ = await rig.rotate()
    assert not made["active"]["verified"] and await rig.directory.active() is None
    assert _down(rig.svc, rig.ctx) == (reason, False, 1)
    assert rig.written()[-1][0] == "security.audit_signing_key_unavailable"
    assert rig.svc._export_checked is None  # latched, so nothing is checked (re-check A4)


@pytest.mark.parametrize(
    ("unreadable", "logged"),
    [
        ("rotation", "secrets.export_key_rotation_lookup_failed"),
        ("active", "secrets.export_key_rotation_active_read_failed"),
    ],
)
async def test_a_store_that_cannot_be_read_is_store_unavailable_and_unrecorded(
    unreadable: str, logged: str
) -> None:
    """The lookup, or the active key before the rotation starts: nothing written or counted,
    and the log names which read failed (code C2-5), by its class only."""
    rig = await _rig()
    setattr(rig.keys, unreadable, _down_io)
    with capture_logs() as logs:
        await rig.refused("store_unavailable")
    assert (rig.written(), list(rig.svc._export_rotations)) == ([], [])
    assert [(e["event"], e["error"]) for e in logs] == [(logged, "RuntimeError")]


def test_a_refused_or_failed_records_reason_is_one_of_a_closed_set() -> None:
    """Code C2-5: the records' `reason` values (ADR-0039's S7 notes list them)."""
    refused = {"kek_unavailable", "rotation_in_progress", "export_in_progress", "no_active_key"}
    assert (rot.REFUSAL_REASONS, rot.FAILURE_REASONS) == (
        refused, {"store_unavailable", "audit_unavailable"}
    )  # fmt: skip


async def test_the_cap_counts_only_rotations_that_start_in_a_rolling_hour() -> None:
    rig = await _rig()
    rig.exporting = True
    await rig.refused("conflict")  # refused before it started: not counted
    rig.exporting = False
    for _ in range(3):
        await rig.rotate()
        rig.now += 600
    assert (await rig.refused("rate_limited")).retry_after_s == 1800
    rig.now += 1800  # the first start leaves the hour
    assert (await rig.rotate())[1] is False and len(rig.keys.rows) == 5


async def test_the_cap_is_the_settings_audit_signing_rotate_rate_per_hour() -> None:
    """Code C2-3: booted with a cap of 1, the second start in the hour is refused."""
    rig = await _Rig().start(audit_signing_rotate_rate_per_hour=1)
    await rig.rotate()
    rig.now += 60
    assert (await rig.refused("rate_limited")).retry_after_s == 3540


async def test_a_stop_during_a_rotation_answers_its_200_and_leaves_the_check_to_boot() -> None:
    """A rotation committed as `stop()` closed the KEK is answered; the next boot checks it."""
    rig = await _rig()
    real = rig.keys.rotate

    async def then_stopped(*args: Any, **kw: Any) -> Any:
        made = await real(*args, **kw)
        await rig.svc.stop(0)
        return made

    setattr(rig.keys, "rotate", then_stopped)  # noqa: B010
    made, replayed = await rig.rotate()
    assert not replayed and made["active"]["version"] == 2 and not made["active"]["verified"]


async def test_a_stop_during_the_new_keys_check_is_no_verdict_and_pages_nothing() -> None:
    """Security Info: `stop()` closing the KEK while the read-back is checked is no verdict on the
    new key: nothing latched, paged or recorded, the 200 answered, and the next boot checks it."""
    rig = await _rig()
    real_rotate, real_active = rig.keys.rotate, rig.keys.active

    async def stopping(env: str) -> Any:  # the read-back: stop() lands while it awaits
        await rig.svc.stop(0)
        return await real_active(env)

    async def then_stopping(*args: Any, **kw: Any) -> Any:
        made = await real_rotate(*args, **kw)
        setattr(rig.keys, "active", stopping)  # noqa: B010
        return made

    setattr(rig.keys, "rotate", then_stopping)  # noqa: B010
    made, replayed = await rig.rotate()
    assert not replayed and made["active"]["version"] == 2 and not made["active"]["verified"]
    assert (rig.written(), rig.svc._export_reason) == ([], None)
    assert m.export_key_unavailable_state._value.get() == 0


async def test_an_active_row_swapped_out_of_band_is_named_by_nothing_until_a_check() -> None:
    """Security Low 2, code C3-1 (decision 4): M2 names, and marks `verified`, only the key it
    checked, at boot or after a rotation. An active row replaced behind its back (AD-T02's class:
    a direct write, or another process) is named by nothing until a rotation here checks its key;
    then the directory names that key."""
    rig = await _rig()
    v2 = await _swapped(rig, 2)
    with capture_logs() as logs:
        assert await rig.directory.active() is None  # a sound key, but not the one M2 checked
        assert await rig.directory.active() is None
        v3 = await _swapped(rig, 3)  # another, swapped the same way: logged too (delta A2-b)
        assert await rig.directory.active() is None
    assert _unchecked(logs) == [(v2, rig.v1["key_id"]), (v3, rig.v1["key_id"])]  # once a key (A2)
    made, _ = await rig.rotate()
    v4 = rig.keys.rows[3]["key_id"]
    assert made["active"]["verified"] and (await rig.directory.active() or ("",))[0] == v4


async def test_a_read_that_overlaps_a_rotation_here_logs_no_unchecked_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Delta A2-a: a read that started before a rotation's check moved the checked key, or one
    made while a rotation runs here, names nothing and logs nothing; once settled, it logs."""
    rig, real = await _rig(), export_signer.active_key

    async def moved(*args: Any) -> Any:
        named = await real(*args)
        rig.svc._export_checked = "cv-audit-export-v9:" + "0" * 16  # its `_rotated` meanwhile
        return named

    with capture_logs() as overlapping:
        monkeypatch.setattr(export_signer, "active_key", moved)
        assert await rig.directory.active() is None  # v1, read before the check moved
        monkeypatch.setattr(export_signer, "active_key", real)
        rig.svc._export_checked = rig.v1["key_id"]
        v2 = await _swapped(rig, 2)
        rig.svc._export_rotating = ("o", "r")  # committed, its check still to run
        assert await rig.directory.active() is None
    rig.svc._export_rotating = None
    with capture_logs() as settled:
        assert await rig.directory.active() is None
    assert (_unchecked(overlapping), _unchecked(settled)) == ([], [(v2, rig.v1["key_id"])])


async def test_a_malformed_request_is_refused_before_any_read_or_record() -> None:
    rig = await _rig()
    for call in ({"reason": "weekly"}, {"body": "B" * 64}):
        with pytest.raises(ValueError):
            await rig.rotate(**call)
    assert rig.written() == [] and len(rig.keys.rows) == 1


async def test_the_rotator_holds_a_closure_only_and_is_m2s() -> None:
    rotator = (await _rig()).rotator
    assert type(rotator) is SigningKeyRotator and not hasattr(rotator, "__dict__")
    assert {n for n in dir(rotator) if not n.startswith("__")} == {
        "rotate", "_SigningKeyRotator__rotate"
    }  # fmt: skip
    with pytest.raises(TypeError, match="may not be subclassed"):
        type("Sub", (SigningKeyRotator,), {})
    with pytest.raises((TypeError, AttributeError, pickle.PicklingError)):
        pickle.dumps(rotator)


async def test_no_seed_or_dek_is_in_an_answer_a_log_or_a_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-12.6, AD-I16: no seed or DEK made here reaches a rotation's answer, its repeat, the
    listing, a refusal, a log or a record."""
    made = _made(monkeypatch)
    with capture_logs() as logs:
        rig, ref = await _rig(), uuid4()
        answers = [await rig.rotate(ref=ref), await rig.rotate(ref=ref)]
        rig.keys.audit_fails = True
        with pytest.raises(ExportKeyRotationError) as failed:
            await rig.rotate()
    seen = repr((answers, logs, rig.audit.records, rig.keys.audit, failed.value, rig.rotator))
    assert len(made) == 6 and not [s for s in made if s.hex() in seen or repr(s) in seen]
