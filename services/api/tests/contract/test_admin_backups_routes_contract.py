"""Contract (E42-T05 #966 BK-4): `listBackups` and `getBackup` over HTTP: the owner's 200s against
`Page` and `Backup` (default page, `deleted_at`); each refusal a registered, declared problem."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from candleviewer.api._generated import openapi_models as api
from candleviewer.storage.errors import StorageTierUnavailable
from tests.contract._admin_support import SPEC, validate_example
from tests.unit.admin._backup_fakes import NOW, Store, area_record, make_app, row

_LIST, _ITEM = "/admin/backups", "/admin/backups/{backupId}"
_OK = "responses/200/content/application~1json/schema"
_REGISTERED = {entry["code"] for entry in SPEC["x-error-codes"]}
_STORES: dict[str, Callable[[], Store | None]] = {
    "wired": lambda: Store([row(1)]),
    "unwired": lambda: None,
    "down": lambda: Store(error=StorageTierUnavailable("down")),
}


def test_every_200_validates_against_page_and_backup_and_round_trips() -> None:
    failed = row(2, status="failed", error_message="verify_failed", verified_at=None)
    deleted = row(3, kind="config_bundle", deleted_at=NOW)
    store = Store([row(1), failed, deleted])
    app, spy = make_app(store)
    client = TestClient(app)
    listed = client.get(_LIST, headers={"x-role": "owner"})  # the contract's default `limit`
    one = client.get(f"{_LIST}/{deleted.id}", headers={"x-role": "owner"})
    assert (listed.status_code, one.status_code) == (200, 200)
    assert store.calls[0] == ("page", None, None, None, 101)  # `Limit` 100, and one more
    validate_example(f"/paths/~1admin~1backups/get/{_OK}", listed.json())
    validate_example(f"/paths/~1admin~1backups~1{{backupId}}/get/{_OK}", one.json())
    page = listed.json()
    assert api.Page.model_validate(page).model_dump(mode="json", exclude_unset=True) == page
    for item in [*page["items"], one.json()]:
        assert api.Backup.model_validate(item).model_dump(mode="json", exclude_unset=True) == item
    assert one.json()["deleted_at"] == "2026-10-18T09:00:00Z"
    assert not {"deleted_by", "encryption_ref"} & {*one.json(), *page["items"][0]}
    assert spy.records == [area_record("owner", _LIST), area_record("owner", _ITEM)]


@pytest.mark.parametrize(
    ("path", "params", "role", "store", "status"),
    [(_LIST, {"cursor": "junk"}, "owner", "wired", 400), (_LIST, {}, "", "wired", 401),
     (f"{_LIST}/{UUID(int=1)}", {}, "viewer", "wired", 403),
     (f"{_LIST}/{UUID(int=9)}", {}, "owner", "wired", 404),
     (_LIST, {"limit": 0}, "owner", "wired", 422), (f"{_LIST}/backup-1", {}, "owner", "wired", 422),
     (_LIST, {}, "owner", "unwired", 501), (f"{_LIST}/{UUID(int=1)}", {}, "owner", "unwired", 501),
     (_LIST, {}, "owner", "down", 503), (f"{_LIST}/{UUID(int=1)}", {}, "owner", "down", 503)],
    ids=["list-400", "list-401", "get-403", "get-404", "list-422", "get-422", "list-501",
         "get-501", "list-503", "get-503"],
)  # fmt: skip
def test_every_refusal_is_a_registered_problem_its_operation_declares(
    path: str, params: dict[str, Any], role: str, store: str, status: int
) -> None:
    app, _ = make_app(_STORES[store]())
    response = TestClient(app).get(path, params=params, headers={"x-role": role})
    body = response.json()
    assert (response.status_code, response.headers["content-type"]) == (
        status,
        "application/problem+json",
    )
    validate_example("/components/schemas/Problem", body)
    assert body["type"].rsplit("/", 1)[1] == body["code"] and body["code"] in _REGISTERED
    declared = SPEC["paths"][_LIST if path == _LIST else _ITEM]["get"]["responses"]
    assert str(status) in declared
