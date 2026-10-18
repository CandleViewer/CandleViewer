"""Unit (E42-T05 #966 BK-4): the backup reads: paging, the payload, each refusal's problem and the
guard's cells on both routes (403 with a record and a count, 401; a known id gives nothing)."""

from __future__ import annotations

from dataclasses import asdict, replace
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from prometheus_client import REGISTRY

from candleviewer.admin.errors import OpsUnavailable
from candleviewer.admin.ops.incidents import encode_cursor
from candleviewer.api.admin_backups import _refusal, backup_payload
from candleviewer.storage.errors import StorageQueryFailed, StorageTierUnavailable
from candleviewer.storage.repositories.backups import BackupRow
from tests.unit.admin._backup_fakes import NOW, Store, area_record, make_app, row

_LIST, _ONE = "/admin/backups", f"/admin/backups/{UUID(int=1)}"
_SECRET = "postgresql://cv:" + "hunter2" + "@db/cv"  # concatenated: no scanner sees a credential


def _get(store: Store | None, path: str = _LIST, role: str = "owner", **params: Any) -> Response:
    """One request against a fresh app: the store keeps no state, so a cursor carries over."""
    app, _ = make_app(store)
    response: Response = TestClient(app).get(path, params=params, headers={"x-role": role})
    return response


def _denied() -> float:
    """`authz_denied_total` for `backups:read` (SR-125); a test asserts the delta."""
    labels = {"permission": "backups:read"}
    return float(REGISTRY.get_sample_value("authz_denied_total", labels) or 0.0)


def test_list_pages_newest_first_with_a_cursor_bound_to_its_filters() -> None:
    tied = row(2).started_at
    others = [row(5, status="failed"), row(6, kind="config_bundle")]
    store = Store([row(1), row(2), row(3, started_at=tied), row(4), *others])
    pages, metas, cursor = [], [], None
    for _ in range(4):  # bounded: a cursor that never ends must fail, not hang
        query: dict[str, Any] = {"kind": "pg_dump", "status": "verified", "limit": 2}
        body = _get(store, **query, **({"cursor": cursor} if cursor else {})).json()
        pages.append([UUID(item["id"]).int for item in body["items"]])
        metas.append((body["meta"]["has_more"], body["meta"]["count"]))
        if (cursor := body["meta"]["next_cursor"]) is None:
            break
    assert pages == [[1, 3], [2, 4]]  # 3 and 2 share a time: the larger id first
    assert metas == [(True, 2), (False, 2)]


@pytest.mark.parametrize(
    "replayed",
    [{}, {"kind": "pg_dump"}, {"status": "verified"},
     {"kind": "config_bundle", "status": "verified"}, {"kind": "pg_dump", "status": "ok"}, None],
    ids=["no-filters", "kind-only", "status-only", "other-kind", "other-status", "incident-list"],
)  # fmt: skip
def test_a_cursor_for_other_filters_is_400_and_never_echoed(
    replayed: dict[str, Any] | None,
) -> None:
    store = Store([row(1), row(2), row(3)])
    issued = _get(store, kind="pg_dump", status="verified", limit=1).json()["meta"]["next_cursor"]
    if replayed is None:  # the incident list's own cursor (no filter), at a valid position
        position = (row(1).started_at, row(1).id)
        issued, replayed = encode_cursor(None, position, int(NOW.timestamp())), {}
    response = _get(store, cursor=issued, limit=1, **replayed)
    assert (response.status_code, response.json()["code"]) == (400, "invalid_cursor")
    assert issued not in response.text and "retry-after" not in response.headers
    assert len(store.calls) == 1  # the replay never reached the store


def test_get_unknown_backup_is_404() -> None:
    store = Store([row(2)])
    response = _get(store, _ONE)
    body = response.json()
    assert (response.status_code, body["code"]) == (404, "not_found")
    assert body["detail"] == "no such backup" and "retry-after" not in response.headers
    assert store.calls == [("get", UUID(int=1))]


@pytest.mark.parametrize("bad", ["backup-1", str(UUID(int=1))[:-1], f"{UUID(int=1)}0"])
def test_a_malformed_backup_id_is_422_before_the_store_is_read(bad: str) -> None:  # V1
    store = Store([row(1)])
    response = _get(store, f"/admin/backups/{bad}")
    assert (response.status_code, response.json()["code"]) == (422, "validation_failed")
    assert store.calls == []


@pytest.mark.parametrize(
    ("path", "params"),
    [(_LIST, {}), (_LIST, {"cursor": "not-a-cursor"}), (_ONE, {})],
    ids=["list", "list-with-a-bad-cursor", "get"],
)
def test_unwired_catalogue_is_501_never_an_empty_page(path: str, params: dict[str, Any]) -> None:
    response = _get(None, path, **params)
    body = response.json()
    assert (response.status_code, body["code"]) == (501, "not_implemented")
    assert body["detail"] == "backups: no catalogue wired" and "items" not in body
    assert "retry-after" not in response.headers


@pytest.mark.parametrize("path", [_LIST, _ONE], ids=["list", "get"])
@pytest.mark.parametrize(
    "error", [StorageTierUnavailable(_SECRET), TimeoutError(_SECRET)], ids=["outage", "timeout"]
)
def test_store_outage_is_503_with_retry_after_and_a_fixed_detail(
    path: str, error: Exception
) -> None:
    app, _ = make_app(Store([row(1)], error=error))
    response = TestClient(app).get(path, headers={"x-role": "owner"})
    body = response.json()
    assert (response.status_code, body["code"]) == (503, "store_unavailable")
    assert body["detail"] == "backups: store unavailable"  # the read model's, never the store's
    assert (response.headers["retry-after"], body["retry_after_seconds"]) == ("5", 5)
    assert "hunter2" not in response.text


@pytest.mark.parametrize("path", [_LIST, _ONE], ids=["list", "get"])
def test_a_query_failure_is_the_apps_redacted_500_never_a_retryable_503(path: str) -> None:
    app, _ = make_app(Store([row(1)], error=StorageQueryFailed("42P01")))
    response = TestClient(app, raise_server_exceptions=False).get(path, headers={"x-role": "owner"})
    assert (response.status_code, response.json()["code"]) == (500, "internal_error")
    assert "retry-after" not in response.headers and "42P01" not in response.text


def test_a_refusal_subclass_answers_as_its_base() -> None:
    class Later(OpsUnavailable): ...  # a refusal a later slice may add

    response = _refusal(Later("backups: store unavailable"))
    assert (response.status_code, response.headers["retry-after"]) == (503, "5")


def test_payload_never_carries_encryption_ref_and_maps_location_and_error() -> None:
    deleted = row(1, status="failed", error_message="checksum_mismatch", deleted_at=NOW)
    assert backup_payload(deleted) == {
        "id": str(UUID(int=1)), "kind": "pg_dump", "status": "failed",
        "started_at": "2026-10-18T08:00:00Z", "finished_at": "2026-10-18T08:04:00Z",
        "size_bytes": 1001, "location": "/backups/pg/1.dump.age", "checksum_sha256": f"{1:064x}",
        "encrypted": True, "retention_until": "2027-01-16T09:00:00Z",
        "verified_at": "2026-10-18T08:09:00Z", "error": "checksum_mismatch",
        "deleted_at": "2026-10-18T09:00:00Z",
    }  # fmt: skip
    # An allow-list: a row that also held the key alias and who deleted it serves the same body.
    leaky = SimpleNamespace(**asdict(deleted), encryption_ref="age-alias", deleted_by=UUID(int=7))
    assert backup_payload(cast(BackupRow, leaky)) == backup_payload(deleted)
    stray = replace(deleted, error_message="pg_dump exited 1 at /srv/cv/backups/1.dump.age")
    assert backup_payload(stray)["error"] == "internal_error"  # a code, never the stored text
    assert backup_payload(row(2))["error"] is None


@pytest.mark.parametrize(
    "params",
    [{"kind": "pg_dumpall"}, {"status": "deleted"}, {"limit": 0}, {"limit": 501},
     {"limit": "ten"}, {"cursor": "A" * 513}],
    ids=["kind", "status", "limit-low", "limit-high", "limit-text", "cursor-long"],
)  # fmt: skip
def test_bad_kind_status_or_limit_is_422(params: dict[str, Any]) -> None:
    store = Store([row(1)])
    response = _get(store, **params)
    assert (response.status_code, response.json()["code"]) == (422, "validation_failed")
    assert store.calls == []  # refused before the store is asked


@pytest.mark.parametrize("role", ["manager", "viewer"])
@pytest.mark.parametrize(
    ("path", "route"),
    [(_LIST, _LIST), (_ONE, "/admin/backups/{backupId}"),
     ("/admin/backups/backup-1", "/admin/backups/{backupId}")],
    ids=["list", "get-a-known-id", "get-a-malformed-id"],
)  # fmt: skip
def test_manager_and_viewer_get_403_with_a_denied_area_record(
    role: str, path: str, route: str
) -> None:
    store = Store([row(1)])  # backup 1 exists: knowing its id reads nothing
    app, spy = make_app(store)
    before = _denied()
    response = TestClient(app).get(path, headers={"x-role": role})
    body = response.json()
    assert (response.status_code, body["code"]) == (403, "forbidden")
    assert body["detail"] == "requires backups:read" and "location" not in response.text
    assert spy.records == [area_record(role, route)]  # written before the refusal
    assert _denied() - before == 1 and store.calls == []


@pytest.mark.parametrize("path", [_LIST, _ONE], ids=["list", "get"])
def test_unauthenticated_get_is_401(path: str) -> None:
    store = Store([row(1)])
    app, spy = make_app(store)
    before = _denied()
    response = TestClient(app).get(path)  # no verified session
    assert (response.status_code, response.json()["code"]) == (401, "unauthenticated")
    assert (spy.records, store.calls, _denied() - before) == ([], [], 0)
