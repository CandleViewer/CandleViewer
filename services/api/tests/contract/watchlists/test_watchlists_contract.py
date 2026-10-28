"""E08-T07 (#4706): the four `/watchlists*` operations through the real app (session, CSRF, RBAC,
the router over an in-memory store, the recorded instrument catalogue) answer only what
22-api-openapi.yaml documents: each status a documented one, each body valid against its schema,
each problem with its catalogued `code`, each `ETag` a `WatchlistETag`; a Manager's probe of the
Owner's list is the 404 of a missing one, audited `rbac.denied`. Not reached here: `401` on a
write (with no session the CSRF guard answers first, `403 csrf_token_invalid`; the router tests
check the route's `401`) and `403` on the list (every role holds `workspaces:read`)."""

from __future__ import annotations

from collections.abc import Iterator
from functools import cache
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from jsonschema import Draft202012Validator
from referencing import Registry
from referencing.jsonschema import DRAFT202012

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.exchange.bybit.instruments import parse_instruments
from candleviewer.ingestion.instruments import CatalogueSnapshot
from tests._corpus import rest
from tests.contract.rbac.rbac_harness import World, bearer, build_world, user_id_of
from tests.watchlists._watchlists_env import MAJORS, MISSING, FakeWatchlistStore, tag

SPEC: dict[str, Any] = load_openapi_spec()
CODES = {e["code"]: e["status"] for e in SPEC["x-error-codes"]}
OPS = {
    op["operationId"]: (method.upper(), path)
    for path, item in SPEC["paths"].items() if path.startswith("/watchlists")
    for method, op in item.items() if method in ("get", "put", "post", "delete")
}  # fmt: skip
_BASE = "urn:cv:22-api-openapi"


_REGISTRY: Registry[Any] = Registry().with_resource(_BASE, DRAFT202012.create_resource(SPEC))
_PAGE = parse_instruments(rest("rest/instruments_after.json")["result"]["list"], fetched_at_us=0)
_HUGE = b"{" + b" " * (64 * 1024) + b"}"  # past 22's 64 KiB


@cache
def _validator(pointer: str) -> Draft202012Validator:
    schema = {"$ref": f"{_BASE}#{pointer}"}
    checker = Draft202012Validator.FORMAT_CHECKER
    return Draft202012Validator(schema, registry=_REGISTRY, format_checker=checker)


def _invalid(pointer: str, doc: Any) -> list[str]:
    return sorted(e.message for e in _validator(pointer).iter_errors(doc))


def _resolve(node: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """(its JSON pointer, the node) for a `$ref`; ("", node) for an inline node."""
    if "$ref" not in node:
        return "", node
    target: Any = SPEC
    for part in node["$ref"].removeprefix("#/").split("/"):
        target = target[part]
    return node["$ref"].removeprefix("#"), target


def conforms(op: str, r: httpx.Response) -> None:
    method, path = OPS[op]
    responses = SPEC["paths"][path][method.lower()]["responses"]
    where = f"{op} -> {r.status_code}: {r.text[:300]}"
    assert str(r.status_code) in responses, f"undocumented status: {where}"
    pointer, documented = _resolve(responses[str(r.status_code)])
    if not pointer:
        escaped = path.replace("~", "~0").replace("/", "~1")
        pointer = f"/paths/{escaped}/{method.lower()}/responses/{r.status_code}"
    for name, header in documented.get("headers", {}).items():
        if name == "ETag":
            assert not _invalid(_resolve(header)[0] + "/schema", r.headers[name]), where
    if "content" not in documented:
        assert r.text == "", where
        return
    media = r.headers["content-type"].split(";")[0]
    assert media in documented["content"], where
    assert not _invalid(f"{pointer}/content/{media.replace('/', '~1')}/schema", r.json()), where
    if media == "application/problem+json":  # `validation_failed` is catalogued 400, served 422
        code = r.json()["code"]
        allowed = {CODES[code]} | ({422} if code == "validation_failed" else set())
        assert r.status_code in allowed, where


@pytest.fixture(scope="module")
def world() -> Iterator[World]:
    mp = pytest.MonkeyPatch()
    try:
        built = build_world(mp)
        snap = CatalogueSnapshot({i.symbol: i for i in _PAGE.instruments}, 0)
        ingestion = built.app.state.app_context.ingestion
        mp.setattr(ingestion, "instruments", SimpleNamespace(snapshot=lambda: snap))
        yield built
    finally:
        mp.undo()


@pytest.fixture
def api(world: World) -> Any:
    world.audit.records.clear()
    world.app.state.watchlists_repository = FakeWatchlistStore()

    def send(actor: str, op: str, body: Any = None, wid: object = "", **headers: str) -> Any:
        method, path = OPS[op]
        url = path.replace("{watchlistId}", str(wid))
        sent: dict[str, Any] = {"content": body} if isinstance(body, bytes) else {"json": body}
        r = world.client.request(method, url, headers=bearer(actor) | headers, **sent)
        conforms(op, r)
        return r

    return send


def test_list_watchlists_conforms_at_200_401_and_503(api: Any, world: World) -> None:
    mine = api("manager_with_grant", "createWatchlist", MAJORS).json()
    assert api("manager_with_grant", "listWatchlists").json() == {"items": [mine]}
    assert api("owner", "listWatchlists").json() == {"items": []}  # whatever the caller's role
    unauthenticated = api("unauthenticated", "listWatchlists")
    world.app.state.watchlists_repository = None
    down = api("viewer", "listWatchlists")
    assert [unauthenticated.status_code, down.status_code] == [401, 503]


def test_create_watchlist_conforms_and_is_audited_through_the_app(api: Any, world: World) -> None:
    made = api("manager_with_grant", "createWatchlist", MAJORS)
    (record,) = [r for r in world.audit.records if r["action"] == "watchlist.created"]
    assert record["object_id"] == made.json()["id"]
    assert record["actor_user_id"] == user_id_of("manager_with_grant")
    taken = api("manager_with_grant", "createWatchlist", MAJORS | {"name": "MAJORS"})
    invalid = api("manager_with_grant", "createWatchlist", MAJORS | {"symbols": ["XRPUSDT"]})
    viewer = api("viewer", "createWatchlist", MAJORS | {"name": "V"})
    csrf = api("unauthenticated", "createWatchlist", MAJORS | {"name": "U"})
    huge = api("manager_with_grant", "createWatchlist", _HUGE, **{"content-type": "x"})
    world.app.state.watchlists_repository = None
    down = api("manager_with_grant", "createWatchlist", MAJORS | {"name": "D"})
    statuses = [r.status_code for r in (made, taken, invalid, viewer, csrf, huge, down)]
    assert statuses == [201, 409, 422, 403, 403, 413, 503]


def test_update_watchlist_conforms_at_every_reachable_status(api: Any, world: World) -> None:
    made = api("owner", "createWatchlist", MAJORS).json()
    other = api("owner", "createWatchlist", MAJORS | {"name": "Alts"}).json()
    new = MAJORS | {"symbols": ["ETHUSDT"]}
    ok = api("owner", "updateWatchlist", new, made["id"], **tag(made))
    idor = api("manager_with_grant", "updateWatchlist", new, made["id"], **tag(ok.json()))
    missing = api("owner", "updateWatchlist", new, MISSING, **tag(made))
    assert idor.content == missing.content  # a Manager's view of the Owner's list: no such list
    probes = [r for r in world.audit.records if r.get("object_kind") == "watchlist"
              and r["action"] == "rbac.denied"]  # fmt: skip
    assert [(r["object_id"], r["reason"]) for r in probes] == [
        (made["id"], "not_owner:workspaces:write:self")
    ]
    answers = [
        api("owner", "updateWatchlist", _HUGE, made["id"], **{"content-type": "x"}),
        ok, idor, missing,
        api("owner", "updateWatchlist", new, made["id"]),  # no If-Match
        api("owner", "updateWatchlist", new, made["id"], **tag(made)),  # stale
        api("owner", "updateWatchlist", {"name": "Alts", "symbols": ["LUNAUSDT"]}, other["id"],
            **tag(other)),
        api("owner", "updateWatchlist", MAJORS, other["id"], **tag(other)),  # Majors is taken
        api("viewer", "updateWatchlist", new, made["id"], **tag(ok.json())),
    ]  # fmt: skip
    world.app.state.watchlists_repository = None
    answers.append(api("owner", "updateWatchlist", new, made["id"], **tag(ok.json())))
    assert [r.status_code for r in answers] == [413, 200, 404, 404, 428, 412, 422, 409, 403, 503]


def test_delete_watchlist_conforms_at_204_403_404_and_503(api: Any, world: World) -> None:
    made = api("owner", "createWatchlist", MAJORS).json()
    viewer = api("viewer", "deleteWatchlist", wid=made["id"])
    idor = api("manager_with_grant", "deleteWatchlist", wid=made["id"])
    gone = api("owner", "deleteWatchlist", wid=made["id"])
    again = api("owner", "deleteWatchlist", wid=made["id"])
    world.app.state.watchlists_repository = None
    down = api("owner", "deleteWatchlist", wid=MISSING)
    assert [r.status_code for r in (viewer, idor, gone, again, down)] == [403, 404, 204, 404, 503]
