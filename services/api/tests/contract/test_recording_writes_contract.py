"""#492 S7 and S8 provider contract: the four recorded-set writes through the real
`create_app()` (the RBAC pack's world, with the fake control bound as the writer and every
symbol listed). Bodies validate against the schema 22 declares for their status, and every
status the routes answer is declared. Owner, Manager and Viewer against a read, a write and the
purge: the nine RBAC cases. G-04 (#484): `recording:write` is the Owner's alone, in the contract
and the seed, so a Manager's write is refused at authorisation and changes nothing."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from candleviewer import app as appmod
from candleviewer.api import recording_writes as writes
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.rbac_conformance import RBAC_SEED_PATH
from tests.contract._admin_support import validate_example
from tests.contract.rbac.rbac_harness import World, bearer, build_world, user_id_of
from tests.unit.recorder._control_fakes import FakeRecorder

_SPEC: Any = load_openapi_spec()
_LIST, _ONE = "/recording/symbols", "/recording/symbols/{recordedSymbolId}"
_PIN = f"{_ONE}/pin"
_ANSWERED = {
    (_LIST, "post"): ("200", "201", "401", "403", "409", "422", "429", "503"),
    (_PIN, "put"): ("200", "401", "403", "404", "409", "422", "429", "503"),
    (_ONE, "patch"): ("200", "401", "403", "404", "409", "422", "429", "503"),
    (_ONE, "delete"): ("204", "401", "403", "404", "409", "422", "429", "503"),
}
_CASES = [(p, m, s) for (p, m), statuses in _ANSWERED.items() for s in statuses]
_PROBLEMS = {"404": "NotFound", "409": "Conflict", "422": "UnprocessableEntity"}
_PROBLEMS |= {"429": "RateLimited", "503": "ServiceUnavailable"}


def _schema(path: str, method: str, status: str) -> str:
    operation = f"/paths/{path.replace('/', '~1')}/{method}/responses/{status}"
    return f"{operation}/content/application~1json/schema"


def _problem(status: str) -> str:
    return f"/components/responses/{_PROBLEMS[status]}/content/application~1problem+json/schema"


@pytest.fixture(scope="module")
def world() -> Iterator[World]:
    mp = pytest.MonkeyPatch()
    try:
        w, fake = build_world(mp), FakeRecorder()
        mp.setattr(appmod, "_catalogue_listed", lambda _ctx, symbol: symbol != "DOGEUSDT")
        fake.put("BTCUSDT")
        fake.put("XRPUSDT", "manual", "chart_open", refusals=("chart_open",))
        w.app.state.recording_control = w.app.state.recording_writer = fake
        # The fake stands in for a recorder whose startup has completed: no lifespan runs here,
        # so the runtime's readiness (#2188 S4b, SEC-4) is bound with the fake, as it is ready.
        w.app.state.recording_ready = lambda: True
        yield w
    finally:
        mp.undo()


@pytest.mark.parametrize(("path", "method", "status"), _CASES)
def test_the_operation_declares_every_status_the_route_answers(
    path: str, method: str, status: str
) -> None:
    assert status in _SPEC["paths"][path][method]["responses"]


def test_each_add_and_pin_body_is_its_declared_response(world: World) -> None:
    owner = bearer("owner")
    created = world.client.post(_LIST, json={"symbol": "SOLUSDT"}, headers=owner)
    again = world.client.post(_LIST, json={"symbol": "SOLUSDT"}, headers=owner)
    assert (created.status_code, again.status_code) == (201, 200)
    validate_example(_schema(_LIST, "post", "201"), created.json())
    validate_example(_schema(_LIST, "post", "200"), again.json())
    entry_id = created.json()["id"]
    pinned = world.client.put(_PIN.replace("{recordedSymbolId}", entry_id), json={"pinned": True},
                              headers=owner)  # fmt: skip
    assert pinned.status_code == 200
    validate_example(_schema(_PIN, "put", "200"), pinned.json())


def test_each_problem_body_is_its_declared_response(world: World) -> None:
    owner, fake = bearer("owner"), world.app.state.recording_writer
    key = {"Idempotency-Key": str(uuid.uuid4())} | owner
    world.client.post(_LIST, json={"symbol": "ETHUSDT"}, headers=key)
    answers = {
        "404": world.client.put(
            f"{_LIST}/{uuid.uuid4()}/pin", json={"pinned": True}, headers=owner
        ),
        "409": world.client.post(_LIST, json={"symbol": "BTCUSDT"}, headers=key),
        "422": world.client.post(_LIST, json={"symbol": "DOGEUSDT"}, headers=owner),
    }
    world.app.state.recording_writer = None  # no control with writes: 503
    answers["503"] = world.client.post(_LIST, json={"symbol": "ETHUSDT"}, headers=owner)
    world.app.state.recording_writer = fake
    for status, resp in answers.items():
        assert (str(resp.status_code), resp.headers["content-type"]) == (
            status, "application/problem+json")  # fmt: skip
        validate_example(_problem(status), resp.json())


def test_the_429_body_is_its_declared_response() -> None:
    limited = writes.Limited(12).response()
    assert (limited.status_code, limited.headers["Retry-After"]) == (429, "12")
    validate_example(_problem("429"), json.loads(limited.body))


def test_each_update_and_stop_answer_is_its_declared_response(world: World) -> None:
    owner, fake = bearer("owner"), world.app.state.recording_writer
    btc, xrp = (f"{_LIST}/{fake.entries[s].id}" for s in ("BTCUSDT", "XRPUSDT"))
    patched = world.client.patch(btc, json={"depth": 50}, headers=owner)
    assert patched.status_code == 200
    validate_example(_schema(_ONE, "patch", "200"), patched.json())
    answers = {
        "409": world.client.delete(xrp, headers=owner),
        "422": world.client.delete(btc, params={"purge_data": "true"}, headers=owner),
    }
    for status, resp in answers.items():
        assert (str(resp.status_code), resp.headers["content-type"]) == (
            status, "application/problem+json")  # fmt: skip
        validate_example(_problem(status), resp.json())
    assert world.client.delete(btc, headers=owner).status_code == 204


#: A valid `purgeRecordedData` body, so an allowed purge is refused for nothing but its handler's
#: later checks (the harness backend reads every symbol as pinned: nothing is planned).
_PURGE = {
    "symbol": "BTCUSDT",
    "confirm_symbol": "BTCUSDT",
    "reason": "free disk",
    "before": "2026-10-20T12:00:00Z",
}
_NINE = {  # actor -> (read, write, purge); allow = past authorisation (the handler may refuse)
    "owner": ("allow", "allow", "allow"),
    "manager_with_grant": ("allow", "403", "403"),  # G-04 (#484): the write is the Owner's alone
    "viewer": ("allow", "403", "403"),
}


@pytest.mark.parametrize("actor", sorted(_NINE))
def test_the_nine_rbac_cases_owner_manager_viewer_against_read_write_and_purge(
    world: World, actor: str
) -> None:
    headers, absent = bearer(actor), f"{_LIST}/{uuid.uuid4()}"
    answers = (
        world.client.get(_LIST, headers=headers),
        world.client.delete(absent, headers=headers),
        world.client.post(
            "/admin/recorder/purge",
            json=_PURGE,
            headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        ),
    )
    seen = tuple({401: "401", 403: "403"}.get(r.status_code, "allow") for r in answers)
    assert seen == _NINE[actor]
    assert all(r.status_code < 500 for r in answers)


def test_recording_write_is_the_owners_alone_in_the_contract_and_in_the_seed() -> None:
    """G-04 (#484; 04 §7.2.2 rows 8, 9, 9a and 51): no role but the Owner, through `*`, holds
    `recording:write`, in 22's `x-permissions` or in the seed the database is loaded from, and the
    code stays in the vocabulary. Revision 0060 revokes the Manager's grant that 0001 seeded."""
    seed = json.loads(RBAC_SEED_PATH.read_text(encoding="utf-8"))
    for source in (_SPEC["x-permissions"], seed["role_permissions"]):
        assert source["owner"] == ["*"]
        assert [role for role, codes in source.items() if "recording:write" in codes] == []
    assert "recording:write" in {p["code"] for p in seed["permissions"]}


@pytest.mark.parametrize(
    ("actor", "restricted"),
    [("owner", False), ("manager_with_grant", True), ("viewer", True)],
)
def test_reads_are_unchanged_the_owner_sees_the_full_list_the_others_the_restricted_one(
    world: World, actor: str, restricted: bool
) -> None:
    """G-04 (#484) takes no read away: `recording:read` stays with every role, and whether the
    view is restricted follows the Owner role, never `recording:write` (R-I2)."""
    resp = world.client.get(_LIST, headers=bearer(actor))
    assert resp.status_code == 200, resp.text
    assert resp.json()["role_restricted"] is restricted


#: Each write a Manager is refused (G-04, #484; 04 §7.2.2 rows 8, 9 and 51), with a valid body
#: and the record of its refusal: `enforce`'s for the four recorded-set writes, and the recorder
#: jobs' own for compact and import.
_MANAGER_WRITES = [
    ("POST", _LIST, {"symbol": "SOLUSDT"}, "rbac.denied"),
    ("DELETE", _ONE, None, "rbac.denied"),
    ("PATCH", _ONE, {"depth": 50}, "rbac.denied"),
    ("PUT", _PIN, {"pinned": True}, "rbac.denied"),
    ("POST", "/admin/recorder/compact", {}, "recorder.compact"),
    ("POST", "/admin/recorder/import", {"symbol": "BTCUSDT", "from": "2026-10-01",
                                        "to": "2026-10-02"}, "recorder.import"),
]  # fmt: skip


@pytest.mark.parametrize(
    ("method", "path", "body", "action"),
    _MANAGER_WRITES,
    ids=[f"{method} {path}" for method, path, *_ in _MANAGER_WRITES],
)
def test_a_manager_is_refused_each_recording_write_at_authorisation_and_changes_nothing(
    world: World, method: str, path: str, body: dict[str, Any] | None, action: str
) -> None:
    """G-04 (#484): a Manager with a grant is refused each write before its body is read, the
    refusal is audited once for the Manager, and the recorded set is unchanged."""
    fake = world.app.state.recording_writer
    before, audited = dict(fake.entries), len(world.audit.records)
    target = path.replace("{recordedSymbolId}", fake.entries["XRPUSDT"].id)
    headers = {**bearer("manager_with_grant"), "Idempotency-Key": str(uuid.uuid4())}
    resp = world.client.request(method, target, json=body, headers=headers)
    assert resp.status_code == 403, resp.text
    (record,) = world.audit.records[audited:]
    assert (record["action"], record["outcome"]) == (action, "denied")
    assert record["actor_user_id"] == user_id_of("manager_with_grant")
    assert record["reason"].startswith("missing_permission:recording:write")
    assert fake.entries == before
