"""A KEK re-wrap run (#2266 PR B2): its opening record, the round-5 fence, one `run_id` on every
record and the auth keyring rows `complete` waits for (e27-kek.md §5), on M2's in-memory store."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from candleviewer.secrets._rotation import RotatingBroker
from candleviewer.secrets.errors import CredentialUnavailable
from candleviewer.secrets.store import InMemoryAuthKeyStore, InMemoryCredentialStore
from tests.unit.credentials_m2._helpers import _store
from tests.unit.credentials_m2._vectors import KEK_V1, KEK_V2, AuditLog, kek

_STARTED, _RESUMED = "security.kek_rotation_started", "security.kek_rotation_resumed"
_ROTATED, _INCOMPLETE = "security.kek_rotated", "security.kek_rotation_incomplete"


async def _seed(n: int) -> tuple[InMemoryCredentialStore, list[UUID]]:
    """`n` keys at KEK v1, then v2 enrolled, as the rotation boot enrols it before any run."""
    s = InMemoryCredentialStore()
    b = RotatingBroker(s, AuditLog(), kek(KEK_V1, 1))
    ids = [(await _store(b, f"KEY{i:04d}ABCDEFGH")).key_id for i in range(n)]
    await s.record_kcv("demo", 2, kek(KEK_V2, 2).kcv())
    return s, sorted(ids)


def _rot(s: InMemoryCredentialStore, audit: AuditLog | None = None) -> RotatingBroker:
    return RotatingBroker(s, audit or AuditLog(), kek(KEK_V2, 2), prev_kek=kek(KEK_V1, 1))


async def _aborted(s: InMemoryCredentialStore, moves: int) -> AuditLog:
    """A run whose store fails at its compare-and-set after `moves` rows moved."""
    real, audit = s.rewrap, AuditLog()

    async def cas(key_id: UUID, **kw: Any) -> bool:
        if len(s.rewrap_audit) == moves:
            raise RuntimeError("store down")
        return await real(key_id, **kw)

    s.rewrap = cas  # type: ignore[method-assign]
    with pytest.raises(CredentialUnavailable):
        await _rot(s, audit).rewrap_all(2, batch=2)
    del s.rewrap  # the next run uses the store's own CAS again
    return audit


def _opening(audit: AuditLog) -> tuple[str, str | None, str | None]:
    action, fields = audit.records[0]
    return action, fields.get("remaining"), fields.get("already_rewrapped")


async def test_a_fresh_run_and_a_run_after_the_last_row_moved_open_as_started() -> None:
    s, _ = await _seed(3)
    first, again = AuditLog(), AuditLog()
    rep = await _rot(s, first).rewrap_all(2)
    assert (first.records[0][0], first.records[0][1]["rows"], rep.resumed) == (_STARTED, "3", False)
    rep = await _rot(s, again).rewrap_all(2)
    assert (again.records[0][0], again.records[0][1]["rows"], rep.resumed) == (_STARTED, "0", False)


async def test_a_rerun_after_a_run_that_moved_rows_opens_as_resumed() -> None:
    s, _ = await _seed(5)
    aborted = await _aborted(s, 2)
    assert [a for a, _ in aborted.records] == [_STARTED, _INCOMPLETE]
    audit = AuditLog()
    rep = await _rot(s, audit).rewrap_all(2)
    assert _opening(audit) == (_RESUMED, "3", "2") and rep.resumed
    assert (rep.rewrapped, rep.remaining, audit.actions()[-1]) == (3, 0, _ROTATED)


async def test_a_rerun_after_a_run_that_moved_no_row_opens_as_started() -> None:
    s, _ = await _seed(2)
    await _aborted(s, 0)
    audit = AuditLog()
    assert not (await _rot(s, audit).rewrap_all(2)).resumed
    assert _opening(audit) == (_STARTED, None, None)


@pytest.mark.parametrize(
    "revoked", [{"revoked": True}, {"status": "revoked"}], ids=["revoked_at", "status"]
)
async def test_a_row_moved_and_then_revoked_still_counts_as_progress(
    revoked: dict[str, Any],
) -> None:
    """The contract's `resumed`: an earlier run moved rows, whatever became of them since."""
    s, _ = await _seed(3)
    await _aborted(s, 1)
    (moved,) = [k for k, row in s.rows.items() if row["kek_version"] == 2]
    s.rows[moved].update(revoked)
    audit = AuditLog()
    assert (await _rot(s, audit).rewrap_all(2)).resumed
    assert _opening(audit) == (_RESUMED, "2", "1")


async def test_a_row_stored_under_the_new_kek_is_no_progress() -> None:
    """`store()` writes the current version only after it was enrolled: no re-wrap moved it."""
    s, _ = await _seed(2)
    await _store(RotatingBroker(s, AuditLog(), kek(KEK_V2, 2)), "KEY9999ABCDEFGH")
    audit = AuditLog()
    assert not (await _rot(s, audit).rewrap_all(2)).resumed
    assert _opening(audit) == (_STARTED, None, None)


async def test_a_row_destroyed_between_batches_is_not_rewrapped() -> None:
    """`destroy()` fences a key in this process first, even when its revoke never commits."""
    s, ids = await _seed(3)
    rot, listing = _rot(s), s.ids_at_kek_version

    async def listed(version: int, limit: int, env: str, after: UUID | None = None) -> list[UUID]:
        if after is not None:
            rot._destroyed.add(ids[2])  # between the first batch and the second
        return await listing(version, limit, env, after)

    s.ids_at_kek_version = listed  # type: ignore[method-assign]
    rep = await rot.rewrap_all(2, batch=2)
    assert [s.rows[k]["kek_version"] for k in ids] == [2, 2, 1]
    assert (rep.rewrapped, rep.remaining) == (2, 1)


@pytest.mark.parametrize(
    "change",
    [{"revoked": True}, {"status": "revoked"}, {"kek_version": 2}],
    ids=["revoked_at", "status", "moved"],
)
async def test_a_row_fenced_after_it_was_listed_never_reaches_the_cas(
    change: dict[str, Any],
) -> None:
    """Revoked by either signal, or moved by another run: the row is fenced before its new wrap
    is made, and it is not left to move."""
    s, ids = await _seed(2)
    get, real, wrap = s.get, s.rewrap, s.rows[ids[0]]["dek_ref"]
    tried: list[UUID] = []

    async def reread(key_id: UUID, env: str) -> dict[str, Any] | None:
        if key_id == ids[0]:
            s.rows[key_id].update(change)  # after the run listed it, before it reads it again
        return await get(key_id, env)

    async def cas(key_id: UUID, **kw: Any) -> bool:
        tried.append(key_id)
        return await real(key_id, **kw)

    s.get, s.rewrap = reread, cas  # type: ignore[method-assign]
    audit = AuditLog()
    rep = await _rot(s, audit).rewrap_all(2)
    assert tried == [ids[1]] and s.rows[ids[0]]["dek_ref"] == wrap
    assert (rep.rewrapped, rep.remaining, audit.actions()[-1]) == (1, 0, _ROTATED)


async def test_a_status_revoked_row_is_neither_listed_nor_counted() -> None:
    s, ids = await _seed(2)
    s.activate(ids[0], "revoked")  # `revoked_at` stays unset
    assert await s.ids_at_kek_version(1, 10, "demo") == [ids[1]]
    assert await s.count_at_kek_version(1, "demo") == 1


async def test_rows_of_every_other_status_are_rewrapped_and_none_is_left() -> None:
    s, ids = await _seed(5)
    statuses = ("pending", "active", "rotating", "expired", "invalid")
    for key_id, status in zip(ids, statuses, strict=True):
        s.activate(key_id, status)
    audit = AuditLog()
    rep = await _rot(s, audit).rewrap_all(2)
    assert (rep.rewrapped, rep.remaining, audit.actions()[-1]) == (5, 0, _ROTATED)


async def test_every_record_of_a_run_carries_its_run_id() -> None:
    s, ids = await _seed(3)
    s.rows[ids[1]]["dek_ref"] = "v2:" + bytes(40).hex()  # this row's new wrap fails
    audit = AuditLog()
    rep = await _rot(s, audit).rewrap_all(2, batch=2)
    assert audit.actions() == [_STARTED, "security.kek_rotation_failed", _INCOMPLETE]
    records = audit.records + s.rewrap_audit
    assert len(records) == 5 and {f["run_id"] for _, f in records} == {str(rep.run_id)}
    assert (await _rot(s).rewrap_all(2)).run_id not in (rep.run_id, None)


async def test_an_aborted_run_closes_with_its_run_id() -> None:
    s, _ = await _seed(2)
    aborted = await _aborted(s, 1)
    assert aborted.records[-1][1]["aborted"] == "true"
    assert len({f["run_id"] for _, f in aborted.records + s.rewrap_audit}) == 1


async def test_an_auth_keyring_row_left_keeps_the_run_incomplete_until_it_moves() -> None:
    """ADR-0009 Amendment 4: only the rotation boot moves them, so a rerun cannot."""
    s, _ = await _seed(1)
    auth = InMemoryAuthKeyStore()
    auth.rows += [
        {"env": "demo", "kek_version": 1},
        {"env": "demo", "kek_version": 2},
        {"env": "live", "kek_version": 1},  # another environment's keyring is not this run's
    ]
    audit = AuditLog()
    rep = await _rot(s, audit).rewrap_all(2, auth_keys=auth)
    assert (rep.rewrapped, rep.remaining, rep.failed) == (1, 1, ())
    assert (audit.actions()[-1], audit.records[-1][1]["auth_left"]) == (_INCOMPLETE, "1")
    auth.rows[0]["kek_version"] = 2  # the next rotation boot re-wrapped it
    again = AuditLog()
    rep = await _rot(s, again).rewrap_all(2, auth_keys=auth)
    assert (rep.remaining, again.actions()[-1]) == (0, _ROTATED)
    assert again.records[-1][1]["auth_left"] == "0"


async def test_a_run_whose_last_count_fails_is_closed_as_aborted() -> None:
    s, _ = await _seed(1)
    auth = InMemoryAuthKeyStore()

    async def down(version: int, env: str) -> int:
        raise RuntimeError("store down")

    auth.count_at_kek_version = down  # type: ignore[method-assign]
    audit = AuditLog()
    with pytest.raises(CredentialUnavailable):
        await _rot(s, audit).rewrap_all(2, auth_keys=auth)
    assert (audit.actions()[-1], audit.records[-1][1]["aborted"]) == (_INCOMPLETE, "true")
