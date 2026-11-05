"""E29-X02 (#982): every E29 route x every role x every scope situation, as R3 exit criterion #10
asks: a disallowed cell asserts its status and problem code (the contract's code per refusal
class, `_cells`), that no store of the world changed (a walk of the OMS's order store, the venue's
port, the read store and the pack's stores, before and after: a refusal that wrote first is still
a breach, whichever store it wrote), its records, looked up by the request's own id
(`X-Correlation-Id`, #3990) across the serving loop's audit writer and the order lane's
(`rbac.denied` naming the caller for a role, scope or foreign refusal, `auth.csrf_refused` for
CSRF, none for a 401 or the `missing` 404), and the SR-125 counters (`authz_denied_total`,
`authz_denied_by_route_total`) moving once for an audited denial and never otherwise (BQ-4, as
built: `AS_BUILT`). An allowed cell is not refused (no 401, no RBAC or scope 403, no
`rbac.denied`) and answers below 500; an allowed read answers 200 with the object it names. No
cell's answer names an account the caller does not hold or a row of one: out-of-scope rows are
absent, not hidden (the ticket's accessibility note), and a list shows exactly the caller's own
rows, its page counting them alone. Parametrised by route, so the matrix shards (`-k`). No
network, no sleeps (C-13.5, C-13.7).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from contextlib import closing
from typing import Any, Final

import pytest
from fastapi.testclient import TestClient

from candleviewer.auth.metrics import authz_denied_total
from tests.contract.rbac.rbac_harness import ROLE_OF, WS_ORIGIN, bearer, observed
from tests.contract.rbac.rbac_harness import user_id_of as uid
from tests.security.e28._world import request_id, state
from tests.security.oms import _cells as cells
from tests.security.oms._world import (
    FILL,
    FLAT,
    MISSING,
    OPEN,
    ORDER,
    SITUATIONS,
    OmsWorld,
    tally,
)

_RBAC_CODES: Final = frozenset({"forbidden", "account_scope_denied"})
_NS: Final = uuid.UUID(int=0x982)  # each cell's `Idempotency-Key`, named by the cell
_SR125: Final = ("authz_denied_total", "authz_denied_by_route_total")
#: SR-125 as built (BQ-4; E29-T09 #1029 owns the series): these cells assert the series as they
#: stand, with oms_exit_refused_total{operation,code} beside them.
AS_BUILT: Final = {
    ("DELETE /orders/{orderId}", "foreign"): ("cancel", _SR125),
    ("PATCH /orders/{orderId}", "foreign"): ("amend", _SR125),
    ("POST /orders/cancel-all", "scope"): ("cancel_all", _SR125[1:]),
}
#: What each list shows of an account it may read.
_LISTED: Final[dict[str, Mapping[uuid.UUID, Any]]] = {
    "GET /orders": ORDER, "GET /positions": OPEN, "GET /executions": FILL,
    "GET /executions/closed-pnl": FILL,
}  # fmt: skip


def _object(template: str, at: str) -> str:
    accounts = SITUATIONS[at]
    if at == "absent" or not accounts:
        return str(MISSING)
    store = ORDER if template.startswith("/orders") else FLAT
    return str(store[accounts[0]].id)


def sent(cell: cells.Cell) -> tuple[str, dict[str, Any], dict[str, str]]:
    """The cell's path, its query and body, and its headers, well formed: a refusal is the
    cell's, not the body's, so every write carries its key and the body its route reads first."""
    method, template = cell.key.split(" ", 1)
    accounts = [str(a) for a in SITUATIONS[cell.at]]
    path = template.replace("{orderId}", _object(template, cell.at))
    path = path.replace("{positionId}", _object(template, cell.at))
    params = {"exchange_account_ids": accounts} if cell.key in cells.LISTS and accounts else {}
    body: Any = None
    if (field := cells.NAMED.get(cell.key)) is not None:
        body = {field: accounts[0] if field == "exchange_account_id" else accounts}
    elif method != "GET":
        body = {"PATCH": {"price": "63000"}, "PUT": {"leverage": "10"}}.get(method, {})
        body = {"order_type": "market", "pct": "100"} if path.endswith("/close") else body
    headers = {} if method == "GET" else {"Idempotency-Key": str(uuid.uuid5(_NS, cell.id))}
    return path, {"params": params, "json": body}, headers


def send(world: OmsWorld, cell: cells.Cell, n: int = 0) -> Any:
    """`cell` as its actor sends it, on the world's loop; an unauthenticated caller from a source
    of its own (`n`), so the CSRF guard's per-source budget never skips a record (#2090), on a
    client of its own, closed once it has answered."""
    path, kw, headers = sent(cell)
    headers |= {**bearer(cell.actor), "X-Correlation-Id": request_id(cell.id)}
    method = cell.key.split(" ", 1)[0]
    if cell.actor != "unauthenticated":
        return world.client.request(method, path, headers=headers, **kw)
    source = (f"127.0.{n // 250}.{n % 250 + 1}", 50000)
    with closing(TestClient(world.app, client=source, raise_server_exceptions=False)) as client:
        client.headers["origin"] = WS_ORIGIN
        client.portal = world.portal
        return client.request(method, path, headers=headers, **kw)


def _refused(resp: Any, written: list[dict[str, Any]]) -> bool:
    code = observed(resp).partition(" ")[2]
    denied = any(r["action"] == "rbac.denied" for r in written)
    return resp.status_code == 401 or (resp.status_code == 403 and code in _RBAC_CODES) or denied


def unheld(actor: str) -> set[str]:
    """Every id the actor may not see: the accounts it does not hold and each row on them."""
    out: set[str] = set()
    for account in {*SITUATIONS["granted"], *SITUATIONS["foreign"]} - cells.held(actor):
        out |= {str(account), *(str(s[account].id) for s in (ORDER, FLAT, OPEN, FILL))}
    return out


def _page(cell: cells.Cell) -> dict[str, Any]:
    """An allowed list's answer: the ids of exactly the caller's own rows the cell names, and the
    rest of its page, a keyset list's `meta` (one page, so no cursor) or the positions' unasked
    `aggregates`. A count, a `has_more` or a cursor that reflects a row the caller may not see is
    hiding it, not leaving it absent."""
    held, named = cells.held(cell.actor), set(SITUATIONS[cell.at])
    rows = _LISTED[cell.key].items()
    ids = sorted(str(r.id) for a, r in rows if a in held and (not named or a in named))
    if cell.key == "GET /positions":
        return {"ids": ids, "aggregates": []}
    return {"ids": ids, "meta": {"next_cursor": None, "has_more": False, "count": len(ids)}}


def _listed(resp: Any) -> dict[str, Any]:
    """A list's answer as `_page` gives one: its items' ids, sorted, beside the rest of the page."""
    body: dict[str, Any] = resp.json()
    return {"ids": sorted(item["id"] for item in body.pop("items", [])), **body}


def counters(world: OmsWorld, cell: cells.Cell) -> dict[str, float]:
    """SR-125's two series (the per-route one under the caller's role) and, for an `AS_BUILT`
    cell, the exit counter under its operation and code."""
    registry, role = world.app.state.app_context.metrics, ROLE_OF.get(cell.actor, "other")
    out = {"authz_denied_total": tally(authz_denied_total, "authz_denied_total")}
    out["authz_denied_by_route_total"] = tally(registry, _SR125[1], role=role)
    if (exit_ := AS_BUILT.get((cell.key, cell.expect))) is not None:
        code = cells.ANSWER[cell.expect].split(" ")[1]
        out["exit"] = tally(registry, "oms_exit_refused_total", operation=exit_[0], code=code)
    return out


_CELLS = [pytest.param(c, n, id=c.id) for n, c in enumerate(cells.cells())]


@pytest.mark.parametrize(("cell", "n"), _CELLS)
def test_every_e29_cell_is_answered_as_the_matrix_and_the_scope_rule_say(
    world: OmsWorld, cell: cells.Cell, n: int
) -> None:
    before, logged, counted = state(world.stores()), world.count(), counters(world, cell)
    resp = send(world, cell, n)
    after, written = state(world.stores()), world.by_request.get(request_id(cell.id), [])
    assert world.count() - logged == len(written), "a record without the request's own id"
    leaked = sorted(i for i in unheld(cell.actor) if i in resp.text)
    assert not leaked, f"{cell.id}: the answer names what the caller may not see: {leaked}"
    actions = [(r["action"], r.get("outcome")) for r in written]
    if not cell.denied:
        assert not _refused(resp, written), f"{cell.id}: refused ({observed(resp)}, {actions})"
        assert resp.status_code < 500, f"{cell.id}: {observed(resp)}"
        if cell.key in cells.LISTS:  # exactly the caller's own rows: absent, not hidden
            assert _listed(resp) == _page(cell), f"{cell.id}: {resp.text}"
        elif cell.key.startswith("GET "):  # a read it may make answers the object it names
            body, wanted = resp.json(), _object(cell.key.split(" ", 1)[1], cell.at)
            got = (resp.status_code, body.get("order", body).get("id"))
            assert got == (200, wanted), f"{cell.id}: {resp.text}"
        return
    assert observed(resp) == cells.ANSWER[cell.expect], cell.id
    assert after == before, f"{cell.id}: a refused call changed a store"
    assert [a for a, _ in actions] == cells.AUDITED[cell.expect], f"{cell.id}: {actions}"
    if cells.AUDITED[cell.expect] == ["rbac.denied"]:
        record = written[0]
        assert (record.get("outcome"), str(record["actor_user_id"])) == (
            "denied", str(uid(cell.actor)),
        ), cell.id  # fmt: skip
    moved = {k: v - counted[k] for k, v in counters(world, cell).items()}
    as_built = AS_BUILT.get((cell.key, cell.expect), ("", ()))[1]
    audited = cells.AUDITED[cell.expect] == ["rbac.denied"]
    assert moved == {k: float(audited and k not in as_built) for k in moved}, cell.id


_BY_ID = sorted(k for k in cells.rows("executed") if "Id}" in k and cells.expect(
    k, "manager_with_grant", "foreign") == "foreign")  # fmt: skip
_SAME: Final = ("content-type", "content-length", "etag", "cache-control")


@pytest.mark.parametrize("key", _BY_ID)
def test_an_ungranted_id_is_answered_byte_for_byte_as_an_absent_one(
    world: OmsWorld, key: str
) -> None:
    """SR-E29-13: the 404 for an order or a position on an account outside the caller's grants is
    the 404 for one nothing holds: the same status, body and headers, so no field differs."""
    got = [
        send(world, cells.Cell(key, "manager_with_grant", at, "")) for at in ("foreign", "absent")
    ]
    assert [observed(r) for r in got] == ["404 not_found"] * 2, key
    assert got[0].content == got[1].content, key
    assert [{h: r.headers.get(h) for h in _SAME} for r in got] == [
        {h: got[1].headers.get(h) for h in _SAME}
    ] * 2
