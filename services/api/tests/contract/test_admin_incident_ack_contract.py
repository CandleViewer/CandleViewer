"""Contract (E42-T05): `POST /admin/incidents/{incidentId}/acknowledge` on the real `create_app`
(the RBAC pack's world): the owner's record is written ahead and CSRF (SR-041) is refused before
any route runs. `scope: none`: no cross-account (IDOR) cell; the other roles' cells are the
matrix's own (`rbac/matrix.yaml`, `executed`)."""

from __future__ import annotations

from typing import Any

import pytest

import candleviewer.app as appmod
from candleviewer.admin.ops.incidents import AdminIncidentsService
from tests.contract.rbac.rbac_harness import bearer, build_world, user_id_of
from tests.unit.admin._ops_fakes import Store, row

_URL = f"/admin/incidents/{row(7).id}/acknowledge"


def _world(mp: pytest.MonkeyPatch, store: Store) -> Any:
    mp.setattr(appmod, "build_admin_incidents", lambda *_a, **_k: AdminIncidentsService(store))
    return build_world(mp)


def test_the_owner_acknowledges_on_the_real_app_and_the_record_is_written_ahead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _world(monkeypatch, Store([row(7)]))
    response = world.client.post(_URL, headers=bearer("owner"))
    assert response.status_code == 200
    assert response.json()["acknowledged_by"] == str(user_id_of("owner"))
    *_, entered, record = world.audit.records  # the guard's row, then ours: written ahead
    assert (entered["action"], record["action"]) == ("admin.area_entered", "incident.acknowledged")
    assert (record["object_id"], record["actor_user_id"]) == (str(row(7).id), user_id_of("owner"))


def test_a_write_without_the_csrf_pair_is_refused_before_any_route_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Store([row(7)])
    world = _world(monkeypatch, store)
    written = len(world.audit.records)
    headers = {"Authorization": bearer("owner")["Authorization"]}  # a bearer is no exemption
    response = world.client.post(_URL, headers=headers)
    assert (response.status_code, response.json()["code"]) == (403, "csrf_token_invalid")
    assert store.acks == []  # no route ran: the one record is the guard's own refusal
    assert [r["action"] for r in world.audit.records[written:]] == ["auth.csrf_refused"]
