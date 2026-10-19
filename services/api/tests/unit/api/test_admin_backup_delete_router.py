"""Unit (E42-T05 #966 BK-12): `DELETE /admin/backups/{backupId}` over HTTP, on the real step-up
service (`test_step_up_challenge_router`'s world). The 404 and the 501s come before any challenge;
each delete spends one fresh `backups` code bound to its request; a refusal after the spend is
recorded first and the grant stays spent; the record names the spent challenge; the artefact goes
and the row stays, served with `deleted_at`; a Manager or Viewer gets 403, never a challenge. Every
refusal is a registered `Problem` the operation declares."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import FastAPI, Request
from httpx import Response

from candleviewer.admin.backups.catalogue import BackupCatalogue
from candleviewer.admin.backups.deletion import BackupDeletion
from candleviewer.admin.backups.gate import BackupJobGate
from candleviewer.admin.errors import OpsUnavailable
from candleviewer.admin.http import AdminAreaRefused, admin_area_refused_handler
from candleviewer.api.admin_backup_delete import make_admin_backup_delete_router
from candleviewer.api.admin_backups import make_admin_backups_router
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.storage.errors import StorageQueryFailed, StorageTierUnavailable
from candleviewer.storage.repositories.backups import BackupRow
from tests.contract._admin_support import SPEC, validate_example
from tests.unit.admin._backup_fakes import row
from tests.unit.admin._delete_fakes import Catalogue, Remover, job_on
from tests.unit.api.test_step_up_challenge_router import _World, _world

BID, OTHER = UUID(int=1), UUID(int=2)
_OPERATION = SPEC["paths"]["/admin/backups/{backupId}"]["delete"]
_ROLES = {"owner": {"backups:write", "backups:read"}, "manager": {"accounts:read"},
          "viewer": {"audit:read"}}  # fmt: skip
_PAIR = (row(1), row(2))  # two verified `pg_dump`s


class _Principals:
    """The guard's resolver: the bearer's session, with the permissions of `x-role`."""

    def __init__(self, w: _World) -> None:
        self._sessions = w.sessions

    async def resolve(self, request: Request) -> AuditPrincipal | None:
        record = self._sessions.get(request.headers.get("authorization", "")[len("Bearer ") :])
        if record is None:
            return None
        role = request.headers.get("x-role", "owner")
        grant = frozenset(_ROLES[role])
        return AuditPrincipal(record.user_id, role, grant, record.id, "10.0.0.9", UUID(int=9))


async def _mount(
    rows: Sequence[BackupRow] = _PAIR,
    *,
    catalogued: bool = True,
    wired: bool = True,
    remove: Any = None,
    faults: dict[str, Any] | None = None,
) -> tuple[_World, Catalogue, Remover]:
    """The world with the delete and the reads mounted on one catalogue."""
    w = await _world()
    app = cast(FastAPI, w.client.app)
    app.add_exception_handler(AdminAreaRefused, admin_area_refused_handler)
    gate, log = BackupJobGate(), list[tuple[str, bool]]()
    store, remover = Catalogue(rows, gate, log, **(faults or {})), Remover(gate, log, remove)
    catalogue = BackupCatalogue(store if catalogued else None, now=w.clock)
    deletion = BackupDeletion(store, remover, gate=gate, audit=w.audit, now=w.clock)
    who = _Principals(w)
    app.include_router(
        make_admin_backup_delete_router(
            catalogue, deletion if wired else None, auth=w.auth, resolver=who, audit=w.audit
        )
    )
    app.include_router(make_admin_backups_router(catalogue, resolver=who, audit=w.audit))
    return w, store, remover


def _send(w: _World, backup: object = BID, role: str = "owner", method: str = "DELETE") -> Response:
    headers = {"Authorization": "Bearer tok", "x-role": role}
    sent: Response = w.client.request(method, f"/admin/backups/{backup}", headers=headers)
    return sent


def _stepped(w: _World, backup: UUID = BID) -> tuple[dict[str, Any], Response]:
    """The challenge a first request gets, a step-up answering it, and the request again."""
    challenge: dict[str, Any] = _send(w, backup).json()
    assert challenge["code"] == "step_up_required", challenge
    w.clock.now += timedelta(seconds=30)  # a fresh TOTP step: a code is good once
    assert w.step_up(challenge_id=challenge["challenge_id"]).status_code == 200
    return challenge, _send(w, backup)


def _refused(response: Response, status: int, code: str, rule: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = response.json()
    assert (response.status_code, body["code"]) == (status, code), body
    assert response.headers["content-type"] == "application/problem+json"
    assert str(status) in _OPERATION["responses"]
    validate_example("/components/schemas/Problem", body)
    assert [e["rule"] for e in body.get("errors", [])] == ([] if rule is None else [rule])
    retry = body.get("retry_after_seconds")  # the contract's ServiceUnavailable header too
    assert response.headers.get("retry-after") == (None if retry is None else str(retry))
    return body


def _records(w: _World) -> list[dict[str, Any]]:
    return w.of("backup.deleted")


async def test_delete_spends_one_fresh_backups_code() -> None:
    w, _, _ = await _mount([row(1), row(2), row(3)])
    first, deleted = _stepped(w, BID)
    assert (deleted.status_code, deleted.content) == (204, b"")
    again = _refused(_send(w, OTHER), 403, "step_up_required")  # the grant went with the delete
    assert again["action_class"] == "backups" and again["challenge_id"] != first["challenge_id"]
    second, deleted_again = _stepped(w, OTHER)
    assert deleted_again.status_code == 204
    spent = [r["after_state"]["challenge_id"] for r in _records(w)]
    assert spent == [first["challenge_id"], second["challenge_id"]]


@pytest.mark.parametrize("other", [OTHER, f"{BID}?x=1"], ids=["another-backup", "a-query"])
async def test_a_grant_bound_to_another_backup_is_a_mismatch_and_stays_bound(other: object) -> None:
    """The grant binds the method and the raw target, its query string included."""
    w, _, _ = await _mount([row(1), row(2), row(3)])
    challenge = _send(w, BID).json()
    w.clock.now += timedelta(seconds=30)
    assert w.step_up(challenge_id=challenge["challenge_id"]).status_code == 200
    _refused(_send(w, other), 403, "step_up_required")  # backup 1's grant, for another request
    (mismatch,) = w.of("auth.step_up_mismatch")
    assert mismatch["object_id"] == challenge["challenge_id"] and _records(w) == []
    assert _send(w, BID).status_code == 204  # still bound to backup 1's request


async def test_unknown_backup_is_404_before_any_challenge() -> None:
    w, _, remover = await _mount([row(2)])
    _refused(_send(w, BID), 404, "not_found")
    assert (w.of("auth.step_up_required"), _records(w), remover.removed) == ([], [], [])


@pytest.mark.parametrize(
    ("setup", "status", "code"),
    [({"catalogued": False}, 501, "not_implemented"), ({"wired": False}, 501, "not_implemented"),
     ({"faults": {"get": StorageTierUnavailable("down")}}, 503, "store_unavailable")],
    ids=["no-catalogue", "no-remover", "catalogue-down"],
)  # fmt: skip
async def test_unwired_remover_is_501_before_any_challenge(
    setup: dict[str, Any], status: int, code: str
) -> None:
    w, _, remover = await _mount(**setup)
    _refused(_send(w), status, code)
    assert (w.of("auth.step_up_required"), _records(w), remover.removed) == ([], [], [])


async def test_an_unreadable_catalogue_is_503_before_any_challenge_and_spends_no_grant() -> None:
    """Contract-D: the catalogue's `503 store_unavailable` comes before any challenge, with
    `Retry-After`; it spends no grant and writes no `backup.deleted` record."""
    w, _, remover = await _mount(faults={"get": [None, StorageTierUnavailable("down")]})
    challenge = _send(w).json()  # the first read works: the challenge
    w.clock.now += timedelta(seconds=30)
    assert w.step_up(challenge_id=challenge["challenge_id"]).status_code == 200
    assert _refused(_send(w), 503, "store_unavailable")["retry_after_seconds"] == 5
    assert (_records(w), remover.removed) == ([], [])
    assert _send(w).status_code == 204  # the grant was not spent: the next request deletes


async def test_deleted_record_is_written_before_the_artefact_goes_and_names_the_challenge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w, _, remover = await _mount()
    recorded: list[int] = []
    remove = remover.remove

    async def watched(backup_id: UUID, location: str) -> None:
        recorded.append(len(_records(w)))
        await remove(backup_id, location)

    monkeypatch.setattr(remover, "remove", watched)
    challenge, deleted = _stepped(w)
    assert deleted.status_code == 204 and recorded == [1]  # the record, then the artefact
    (record,) = _records(w)
    assert record["after_state"] == {"challenge_id": challenge["challenge_id"]}  # BK-1 F3
    assert (record["outcome"], record["severity"]) == (AuditOutcome.SUCCESS, Severity.WARNING)
    assert (record["object_id"], record["before_state"]) == (str(BID), {"status": "verified"})
    assert remover.removed == [(BID, row(1).target_path)]  # the row's location, never the client's
    summary = f"Delete the artefact of backup '{BID}' (pg_dump)"
    assert (challenge["action_summary"], challenge["target"]) == (summary, None)


@pytest.mark.parametrize("running", [True, False], ids=["running", "a-restore-uses-it"])
async def test_running_or_in_use_backup_is_409_backup_in_use_after_the_spend(
    running: bool,
) -> None:
    w, store, remover = await _mount([row(1, status="running", finished_at=None), row(2)])
    if not running:
        store.rows[0] = row(1)
        await job_on(store.gate, "backup_restore", BID)
    challenge, refused = _stepped(w)
    _refused(refused, 409, "conflict", "backup_in_use")
    (record,) = _records(w)
    assert (record["outcome"], record["reason"]) == (AuditOutcome.FAILURE, "backup_in_use")
    assert record["after_state"] == {"challenge_id": challenge["challenge_id"]}
    _refused(_send(w), 403, "step_up_required")  # the grant was spent
    assert remover.removed == []


async def test_second_delete_is_409_backup_deleted() -> None:
    w, _, remover = await _mount([row(1), row(2), row(3)])
    assert _stepped(w)[1].status_code == 204
    _refused(_stepped(w)[1], 409, "conflict", "backup_deleted")
    assert [r["reason"] for r in _records(w)] == [None, "backup_deleted"]
    assert len(remover.removed) == 1


async def test_the_last_verified_backup_of_a_kind_is_409_last_usable_backup() -> None:
    w, store, remover = await _mount([row(1), row(2, kind="config_bundle")])
    _refused(_stepped(w)[1], 409, "conflict", "last_usable_backup")
    assert store.rows[0].deleted_at is None and remover.removed == []


async def test_a_row_gone_under_the_lock_is_404_recorded_after_the_spend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The runtime role deletes no catalogue row (0032), but one gone between the route's read and
    the admission lock is a `404`, recorded, the grant spent."""
    w, store, remover = await _mount()
    get = store.get

    async def vanished(backup_id: UUID) -> BackupRow | None:
        return None if store.gate._lock.locked() else await get(backup_id)

    monkeypatch.setattr(store, "get", vanished)
    _refused(_stepped(w)[1], 404, "not_found")
    assert [r["reason"] for r in _records(w)] == ["not_found"] and remover.removed == []


async def test_remove_failure_is_503_with_a_failure_record_and_the_row_unchanged() -> None:
    w, store, _ = await _mount(remove=OSError("EIO"))
    assert _refused(_stepped(w)[1], 503, "store_unavailable")["retry_after_seconds"] == 5
    outcomes = [(r["outcome"], r["reason"]) for r in _records(w)]
    assert outcomes == [(AuditOutcome.SUCCESS, None), (AuditOutcome.FAILURE, "store_unavailable")]
    assert store.rows == list(_PAIR)
    _refused(_send(w), 403, "step_up_required")  # the grant stays spent


async def test_a_failed_mark_is_503_and_the_operators_retry_completes() -> None:
    """The artefact is gone and the row unmarked: the second record, a 503, the grant spent, never
    a 500. The operator steps up again and retries, which completes: an artefact already gone
    counts as removed."""
    w, store, remover = await _mount(faults={"mark_deleted": [StorageQueryFailed("42501")] * 2})
    _refused(_stepped(w)[1], 503, "store_unavailable")
    assert (store.rows[0].deleted_at, len(remover.removed)) == (None, 1)
    assert _stepped(w)[1].status_code == 204 and store.rows[0].deleted_at == w.clock.now
    assert [r["reason"] for r in _records(w)] == [None, "store_unavailable", None]


async def test_until_a_retry_completes_the_unmarked_row_still_counts_as_usable() -> None:
    """Contract-D: so the kind's other verified backup may go meanwhile, and the retry is then its
    kind's last usable backup, refused (recorded: the operator verifies it first, which ends
    `artefact_missing` and fails the row, and the delete then passes)."""
    w, store, remover = await _mount(faults={"mark_deleted": [StorageQueryFailed("42501")] * 2})
    _refused(_stepped(w)[1], 503, "store_unavailable")  # backup 1's artefact gone, row unmarked
    assert _stepped(w, OTHER)[1].status_code == 204  # backup 1 still counts: 2 is not the last
    _refused(_stepped(w)[1], 409, "conflict", "last_usable_backup")
    assert [r.deleted_at is None for r in store.rows] == [True, False] and len(remover.removed) == 2


async def test_a_lock_wait_after_the_spend_is_503_recorded_and_the_grant_stays_spent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SR-BK7A-03: the admission lock refused after the spend; its failure record goes first."""
    w, store, remover = await _mount()

    @contextlib.asynccontextmanager
    async def busy(_backup_id: UUID) -> AsyncIterator[Any]:
        raise OpsUnavailable("backups: the admission lock is busy")
        yield  # pragma: no cover - a generator, so the refusal is the context manager's

    monkeypatch.setattr(store.gate, "admit_delete", busy)
    _refused(_stepped(w)[1], 503, "store_unavailable")
    assert [r["reason"] for r in _records(w)] == ["store_unavailable"] and remover.removed == []
    _refused(_send(w), 403, "step_up_required")


@pytest.mark.parametrize("rows", [_PAIR, (row(1),)], ids=["write-ahead", "conflict"])
async def test_an_unwritten_record_is_503_audit_unavailable_and_the_grant_stays_spent(
    rows: Sequence[BackupRow],
) -> None:
    """SEC-LW-01: the record of the delete, or of its `409`, cannot be written."""
    w, store, remover = await _mount(rows)
    w.audit.fail_on = frozenset({"backup.deleted"})
    _refused(_stepped(w)[1], 503, "audit_unavailable")
    assert (remover.removed, store.rows) == ([], list(rows))
    _refused(_send(w), 403, "step_up_required")


async def test_row_is_kept_with_deleted_at() -> None:
    w, _, _ = await _mount()
    assert _stepped(w)[1].status_code == 204
    served = _send(w, method="GET").json()
    assert datetime.fromisoformat(served["deleted_at"]) == w.clock.now
    assert served["status"] == "verified" and "deleted_by" not in served  # its status unchanged
    page = w.client.get("/admin/backups", headers={"Authorization": "Bearer tok"}).json()
    assert [item["deleted_at"] is not None for item in page["items"]] == [True, False]


@pytest.mark.parametrize("role", ["manager", "viewer"])
async def test_manager_and_viewer_get_403(role: str) -> None:
    w, _, remover = await _mount()
    _refused(_send(w, role=role), 403, "forbidden")
    (entered,) = w.audit.calls
    assert (entered["action"], entered["outcome"]) == ("admin.area_entered", AuditOutcome.DENIED)
    assert entered["reason"] == "missing_permission:backups:write"
    assert (w.of("auth.step_up_required"), remover.removed) == ([], [])
