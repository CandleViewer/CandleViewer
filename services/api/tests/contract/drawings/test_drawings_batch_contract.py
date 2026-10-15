"""E14-Q04 (#431) batch pack for `POST /drawings/batch` through the real app: ordered mixed
operations with exact `created`/`updated`/`deleted`, all-or-nothing application proven by a GET
diff (never by trusting the response), the documented 200-operation cap, the per-operation id and
token rules, a foreign target, and `Idempotency-Key` replay. Tests taking `store` run on the
in-memory E14-T01 repository (`contract` lane) and on real Postgres 16 through testcontainers
(`integration`; CI only, there is no docker socket on the dev laptops).
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from _drawings_contract import MISSING, SCHEMAS, Api, drawing
from anyio.from_thread import start_blocking_portal
from testcontainers.postgres import PostgresContainer

from candleviewer.storage.repositories.drawings_sqlalchemy import SqlAlchemyDrawingRepository
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from tests.contract.rbac.rbac_harness import user_id_of

OWNER, MANAGER = "owner", "manager_with_grant"
CAP: int = SCHEMAS["DrawingBatchRequest"]["properties"]["operations"]["maxItems"]
STALE = "2020-01-01T00:00:00.000000Z"
_API_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    """Postgres 16 at the migration head with the RBAC pack's actors as users, as
    `tests/integration/storage/test_drawings_repository.py` builds it."""
    with PostgresContainer("postgres:16-alpine") as container:
        url = container.get_connection_url()
        env = {**os.environ, "CV_PG_DSN": url.replace("+psycopg2", "+psycopg")}
        argv = [sys.executable, "-m", "alembic", "upgrade", "head"]
        subprocess.run(argv, cwd=_API_ROOT, env=env, check=True)  # noqa: S603 -- fixed argv
        with psycopg.connect(url.replace("+psycopg2", ""), autocommit=True) as conn:
            for actor in (OWNER, MANAGER):
                conn.execute(
                    "INSERT INTO users (id, email, username, password_hash) "
                    "VALUES (%s, %s, %s, '$argon2id$x') ON CONFLICT (id) DO NOTHING",
                    (str(user_id_of(actor)), f"{actor}@x.io", actor),
                )
        yield url.replace("+psycopg2", "+asyncpg")


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.integration)])
def store(request: pytest.FixtureRequest, api: Api) -> Iterator[Api]:
    """`api` on the in-memory repository, or on Postgres with every call of the test on one
    event loop: the SQLAlchemy pool binds a connection to the loop that opened it, and a bare
    TestClient starts a loop per request."""
    if request.param == "memory":
        yield api
        return
    dsn: str = request.getfixturevalue("pg_dsn")
    with psycopg.connect(dsn.replace("+asyncpg", ""), autocommit=True) as conn:
        conn.execute("TRUNCATE drawings")
    relational = SqlAlchemyRelationalRepository(dsn, "drawings-contract")
    with start_blocking_portal() as portal:
        api.world.client.portal = portal
        api.world.app.state.drawings_repository = SqlAlchemyDrawingRepository(relational)
        try:
            yield api
        finally:
            api.world.client.portal = None
            portal.call(relational.dispose)


def _batch(api: Api, actor: str, *ops: dict[str, Any], **kw: Any) -> Any:
    return api.send(actor, "batchUpsertDrawings", {"operations": list(ops)}, **kw)


def _update(d: dict[str, Any], **over: Any) -> dict[str, Any]:
    return {"op": "update", "id": d["id"], "if_match": d["updated_at"], "drawing": drawing(**over)}


def _delete(d: dict[str, Any]) -> dict[str, Any]:
    return {"op": "delete", "id": d["id"], "if_match": d["updated_at"]}


def test_mixed_operations_apply_in_order_with_exact_results(store: Api) -> None:
    a, b = store.create(OWNER), store.create(OWNER)
    cid = str(uuid.uuid4())  # a client-chosen create id is allowed (decision record 6)
    res = _batch(store, OWNER, {"op": "create", "id": cid, "drawing": drawing(label=" c ")},
                 _update(a, label="a2"), _delete(b), {"op": "create", "drawing": drawing("ray")},
                 ).json()  # fmt: skip
    assert res["created"][0]["id"] == cid and len(res["created"]) == 2
    assert [d["id"] for d in res["updated"]] == [a["id"]] and res["deleted"] == [b["id"]]
    assert [d["label"] for d in res["created"] + res["updated"]] == [" c ", None, "a2"]
    assert res["updated"][0]["updated_at"] > a["updated_at"]
    stored = {d["id"]: d for d in store.listed(OWNER)}  # the response is what was persisted
    assert stored == {d["id"]: d for d in res["created"] + res["updated"]}


@pytest.mark.parametrize("rule", ["version_conflict", "target_unavailable", "id_unavailable"])
def test_one_failing_operation_rolls_the_whole_batch_back(store: Api, rule: str) -> None:
    a, b, c = (store.create(OWNER) for _ in range(3))
    failing = {
        "version_conflict": {"op": "delete", "id": c["id"], "if_match": STALE},
        "target_unavailable": {"op": "delete", "id": MISSING, "if_match": STALE},
        "id_unavailable": {"op": "create", "id": c["id"], "drawing": drawing()},
    }[rule]
    later = {"op": "delete", "id": str(uuid.uuid4()), "if_match": STALE}  # fails too, later
    before = store.listed(OWNER)
    ops = ({"op": "create", "drawing": drawing()}, _update(a), _delete(b), failing, later)
    r = _batch(store, OWNER, *ops)
    assert store.listed(OWNER) == before, "a rolled-back batch left writes behind"
    assert (r.status_code, r.json()["code"]) == (409, "conflict")
    assert [(e["field"], e["rule"]) for e in r.json()["errors"]] == [("operations.3", rule)]


def test_gherkin_a_partially_invalid_batch_is_fully_rejected(api: Api) -> None:
    a = api.create(OWNER)
    before = api.listed(OWNER)
    no_id = {"op": "update", "if_match": a["updated_at"], "drawing": drawing()}
    r = _batch(api, OWNER, {"op": "create", "drawing": drawing()}, no_id, _delete(a), invalid=True)
    assert (r.status_code, r.json()["code"]) == (422, "validation_failed")
    assert ("operations.1.id", "missing") in {(e["field"], e["rule"]) for e in r.json()["errors"]}
    assert api.listed(OWNER) == before


@pytest.mark.parametrize(
    ("op", "field"),
    [({"op": "update", "if_match": STALE, "drawing": drawing()}, "id"),
     ({"op": "delete", "if_match": STALE}, "id"),
     ({"op": "update", "id": MISSING, "drawing": drawing()}, "if_match"),
     ({"op": "delete", "id": MISSING}, "if_match")],
)  # fmt: skip
def test_update_and_delete_need_an_id_and_a_token(api: Api, op: dict[str, Any], field: str) -> None:
    r = _batch(api, OWNER, op, invalid=True)
    assert r.status_code == 422
    assert [(e["field"], e["rule"]) for e in r.json()["errors"]] == [(f"operations.0.{field}",
                                                                      "missing")]  # fmt: skip
    assert api.repo.calls == []  # refused before the store was touched


def test_the_cap_is_200_operations_and_one_more_is_413_before_any_write(store: Api) -> None:
    op = {"op": "create", "drawing": drawing()}
    over = _batch(store, OWNER, *[op] * (CAP + 1), invalid=True)
    assert (over.status_code, over.json()["code"]) == (413, "payload_too_large")
    assert store.listed(OWNER) == []
    at_cap = _batch(store, OWNER, *[op] * CAP)
    assert (at_cap.status_code, len(at_cap.json().get("created", []))) == (200, CAP)
    assert len(store.listed(OWNER)) == CAP


def test_another_users_drawing_is_an_unavailable_target_like_a_missing_one(store: Api) -> None:
    theirs = store.create(OWNER)
    before = store.listed(OWNER)
    probe = _batch(store, MANAGER, _delete(theirs))
    missing = _batch(store, MANAGER, _delete(theirs | {"id": MISSING}))
    assert (probe.status_code, probe.json()) == (409, missing.json())  # no existence oracle
    assert probe.json()["errors"][0]["rule"] == "target_unavailable"
    assert store.listed(OWNER) == before


def test_gherkin_a_replayed_key_returns_the_original_and_creates_nothing(store: Api) -> None:
    key = {"Idempotency-Key": str(uuid.uuid4())}
    ops = [{"op": "create", "drawing": drawing()} for _ in range(200)]
    first = _batch(store, OWNER, *ops, headers=key)
    again = _batch(store, OWNER, *ops, headers=key)  # the client timed out and retried
    assert (again.status_code, again.content) == (200, first.content)
    assert again.headers["idempotency-replayed"] == "true"
    assert len(store.listed(OWNER)) == 200  # not 400


def test_the_same_key_with_another_body_is_409_and_writes_nothing(store: Api) -> None:
    key = {"Idempotency-Key": str(uuid.uuid4())}
    _batch(store, OWNER, {"op": "create", "drawing": drawing()}, headers=key)
    r = _batch(store, OWNER, {"op": "create", "drawing": drawing("ray")}, headers=key)
    assert (r.status_code, r.json()["code"]) == (409, "idempotency_key_reuse")
    assert [d["tool"] for d in store.listed(OWNER)] == ["trendline"]


def test_the_same_key_from_another_user_never_returns_the_first_users_result(store: Api) -> None:
    key, op = {"Idempotency-Key": str(uuid.uuid4())}, {"op": "create", "drawing": drawing()}
    (mine,) = _batch(store, OWNER, op, headers=key).json()["created"]
    theirs = _batch(store, MANAGER, op, headers=key)
    assert theirs.status_code == 200 and "idempotency-replayed" not in theirs.headers
    (made,) = theirs.json()["created"]
    assert made["owner_user_id"] == str(user_id_of(MANAGER)) and made["id"] != mine["id"]
    assert store.listed(MANAGER) == [made] and store.listed(OWNER) == [mine]
