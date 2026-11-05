"""E29-X02 (#982): the abuse cases of the E29 threat model (`docs/security/threat-models/E29-oms.md`
section 8.2) that this suite proves beyond its cells, each named for its seed, through the routes
`create_app()` serves in the OMS world (`_world`). Each asserts the answer and what it records
under the request's own id (`X-Correlation-Id`, #3990), and, where nothing may be written, that no
store changed. Every seed's verdict, these included, is in `docs/security/abuse-cases/e29-oms.md`;
a case whose control another ticket owns is a strict xfail naming its owner and its accepted-risk
record there (BQ-5 as ruled). No network, no sleeps (C-13.5, C-13.7).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator, Mapping
from typing import Any, Final

import pytest

from candleviewer.api import position_close
from candleviewer.api.oms_reads import aggregate_document
from candleviewer.auth.csrf import CSRF_HEADER
from candleviewer.auth.metrics import auth_csrf_refused_total
from candleviewer.oms.reads import aggregate_positions
from candleviewer.oms_wiring import REFERENCE_DEMAND_NEW, ReferenceDemand
from tests.contract.rbac.rbac_harness import FOREIGN, GRANTED, bearer, observed
from tests.contract.rbac.test_scope_and_ws import _recv
from tests.security.e28._world import request_id, state
from tests.security.oms import _cells as cells
from tests.security.oms import test_rbac_matrix as matrix
from tests.security.oms import test_ws_scope as ws
from tests.security.oms._world import FILL, OPEN, ORDER, OmsWorld, tally

M = "manager_with_grant"
_NS: Final = uuid.UUID(int=0x982A)
_SAME: Final = ("content-type", "content-length", "etag", "cache-control")


def records(
    world: OmsWorld, actor: str, method: str, path: str, name: str, **kw: Any
) -> tuple[Any, list[dict[str, Any]]]:
    """One request, stamped with its own id (and a key of its own on a write): the answer and
    every record written under that id."""
    rid = request_id(f"abuse|{name}")
    headers = {**bearer(actor), "X-Correlation-Id": rid, **kw.pop("headers", {})}
    if method != "GET":
        headers.setdefault("Idempotency-Key", str(uuid.uuid5(_NS, name)))
    resp = world.client.request(method, path, headers=headers, **kw)
    return resp, world.by_request.get(rid, [])


def call(
    world: OmsWorld, actor: str, method: str, path: str, name: str, **kw: Any
) -> tuple[Any, list[tuple[str, Any]]]:
    """`records`, each record as `(action, reason)`."""
    resp, written = records(world, actor, method, path, name, **kw)
    return resp, [(r["action"], r.get("reason")) for r in written]


@pytest.fixture
def unchanged(world: OmsWorld) -> Iterator[OmsWorld]:
    """The case changes no store: every one walked before and after."""
    before = state(world.stores())
    yield world
    assert state(world.stores()) == before, "a refused call changed a store"


@pytest.mark.parametrize("key", sorted({*cells.NAMED, *cells.LISTS}))
def test_ac01_an_account_outside_the_grants_and_one_nothing_holds_are_refused_alike(
    world: OmsWorld, key: str
) -> None:
    """SR-E29-13: as M, a body or a filter naming the foreign account and one naming an id nothing
    holds get one answer, byte for byte and with the same headers, so no field tells them apart
    (the cells hold each refusal's status, records and stores)."""
    got = [matrix.send(world, cells.Cell(key, M, at, "")) for at in ("foreign", "absent")]
    assert [observed(r) for r in got] == ["403 account_scope_denied"] * 2, key
    assert got[0].content == got[1].content, key
    assert [{h: r.headers.get(h) for h in _SAME} for r in got] == [
        {h: got[1].headers.get(h) for h in _SAME}
    ] * 2


def _accounts(resp: Any) -> list[str]:
    assert resp.status_code == 200, resp.text
    return sorted(r["exchange_account_id"] for r in resp.json()["results"])


@pytest.mark.parametrize("path", ["/orders/cancel-all", "/positions/close-all"])
def test_ac03_an_empty_account_list_reaches_the_callers_trade_grants_alone(
    world: OmsWorld, path: str
) -> None:
    """SR-E29-13, 22 `CancelAllRequest`: `[]` is the caller's trade grants. M's answer and records
    name A alone, the Owner's both accounts (`[A, B]` refused whole is the `mixed` cell)."""
    got: dict[str, list[str]] = {}
    for actor in (M, "owner"):
        resp, written = records(world, actor, "POST", path, f"ac03|{path}|{actor}", json={
            "exchange_account_ids": []})  # fmt: skip
        got[actor] = _accounts(resp)
        if actor == M:
            seen = resp.text + json.dumps(written, default=str)
            assert not [i for i in matrix.unheld(M) if i in seen], seen
    assert got == {M: [str(GRANTED)], "owner": sorted(str(a) for a in (GRANTED, FOREIGN))}


#: Pings a read answers with no other frame between them before it fails, naming what it awaited,
#: where a ping-answering loop would otherwise run to the suite's per-test timeout.
_PINGS: Final = 10


def _reply(socket: Any) -> dict[str, Any]:
    """The next frame that is not a ping, each ping answered."""
    for _ in range(_PINGS):
        if (frame := _recv(socket))["t"] != "ping":
            return frame
        socket.send_json({"t": "pong", "id": frame["id"]})
    pytest.fail(f"no reply to the sub after {_PINGS} pings")


_REFUSED: Final = [
    (family, actor) for family in ws._FAMILIES
    for actor, outcome in cells.ws_outcomes(family).items() if outcome != "sub_ok"
]  # fmt: skip


@pytest.mark.parametrize(("family", "actor"), _REFUSED)
def test_ac06_a_refused_private_sub_holds_no_subscription_while_its_socket_is_open(
    world: OmsWorld, family: str, actor: str
) -> None:
    """The refusal is the server's, not only the frames a socket read: while the refused socket
    is open, the hub holds no more subscriptions of the topic than before it asked
    (`SequencingHub.subscriptions`), so no frame of it, paced or late, is ever routed to it."""
    hub = world.app.state.ws_registry.services.sequencing
    before = len(world.call(hub.subscriptions, family))
    asked = {"exchange_account_ids": [str(a) for a in ws._ASKED]}
    with ws._socket(world, actor) as socket:
        socket.send_json({"t": "sub", "id": "s", "p": {"topics": [{"ch": family, "opts": asked}]}})
        assert ws._code(_reply(socket)) == cells.ws_outcomes(family)[actor]
        assert len(world.call(hub.subscriptions, family)) == before


_KEYSET: Final[dict[str, Mapping[uuid.UUID, Any]]] = {
    "/orders": ORDER, "/executions": FILL, "/executions/closed-pnl": FILL,
}  # fmt: skip


def _pages(world: OmsWorld, actor: str, path: str) -> list[dict[str, Any]]:
    """Every page of `path` at one row a page, each cursor followed (a bound, not a time)."""
    pages: list[dict[str, Any]] = []
    cursor = None
    for n in range(4):
        query = f"{path}?limit=1" + (f"&cursor={cursor}" if cursor else "")
        resp, written = call(world, actor, "GET", query, f"ac05|{path}|{actor}|{n}")
        assert (resp.status_code, written) == (200, []), resp.text
        pages.append(resp.json())
        if (cursor := pages[-1]["meta"]["next_cursor"]) is None:
            return pages
    raise AssertionError(f"{path}: more pages than rows")


@pytest.mark.parametrize("path", list(_KEYSET))
def test_ac05_a_page_of_one_row_counts_and_continues_over_the_callers_rows_alone(
    world: OmsWorld, path: str
) -> None:
    """SR-E29-13, the ticket's accessibility note: M's one page holds A's row, and its count,
    `has_more` and cursor reflect no row of B, which is absent, not hidden. The Owner pages both
    rows, so the paging is real; the Owner's cursor sent by M is `400 invalid_cursor`, unaudited
    (a cursor is bound to its caller), and names nothing M may not see."""
    rows = _KEYSET[path]
    mine = _pages(world, M, path)
    assert [[i["id"] for i in p["items"]] for p in mine] == [[str(rows[GRANTED].id)]]
    assert mine[0]["meta"] == {"next_cursor": None, "has_more": False, "count": 1}
    owners = _pages(world, "owner", path)
    assert sorted(i["id"] for p in owners for i in p["items"]) == sorted(
        str(r.id) for r in rows.values()
    )
    foreign = owners[0]["meta"]["next_cursor"]
    resp, written = call(world, M, "GET", f"{path}?limit=1&cursor={foreign}", f"ac05|{path}|c")
    assert (observed(resp), written) == ("400 invalid_cursor", [])
    assert not [i for i in matrix.unheld(M) if i in resp.text]


def test_ac05_an_aggregate_sums_the_callers_own_positions_alone(world: OmsWorld) -> None:
    """`aggregate=true`: M's aggregates are those of A's open position alone, the Owner's of
    both."""
    got: dict[str, Any] = {}
    want: dict[str, Any] = {}
    for actor in (M, "owner"):
        resp, _ = call(world, actor, "GET", "/positions?aggregate=true", f"ac05|agg|{actor}")
        got[actor] = resp.json()["aggregates"]
        held = [OPEN[a] for a in sorted(cells.held(actor), key=str)]
        want[actor] = json.loads(json.dumps([aggregate_document(x) for x in
                                             aggregate_positions(held)]))  # fmt: skip
    assert got == want and got[M] != got["owner"]


def test_ac05_a_trade_group_spanning_both_accounts_lists_the_callers_rows_alone(
    world: OmsWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    group = uuid.UUID(int=0x6A0B)
    monkeypatch.setattr(world.reads, "orders", [(o, group) for o, _ in world.reads.orders])
    monkeypatch.setattr(world.reads, "fills", [(f, group) for f, _ in world.reads.fills])
    for path, rows in (("/orders", ORDER), ("/executions", FILL)):
        listed = {
            actor: sorted(i["id"] for i in call(world, actor, "GET", f"{path}?trade_group_id="
                          f"{group}", f"ac05|group|{path}|{actor}")[0].json()["items"])
            for actor in (M, "owner")
        }  # fmt: skip
        assert listed == {M: [str(rows[GRANTED].id)], "owner": sorted(str(r.id) for r in
                                                                       rows.values())}  # fmt: skip


#: A reduce-only order passes `trading.oms_enabled` (step 9), so its body is read (step 11).
_CLOSE: Final = {
    "exchange_account_id": str(GRANTED), "symbol": "BTCUSDT", "side": "sell",
    "order_type": "market", "sizing": {"mode": "fixed_qty", "qty": "0.010"}, "reduce_only": True,
}  # fmt: skip


@pytest.mark.parametrize("field", ["origin", "origin_ref", "order_link_id"])
def test_ac09_a_place_order_naming_a_field_the_server_sets_is_refused_and_persists_nothing(
    unchanged: OmsWorld, field: str
) -> None:
    """22 `PlaceOrderRequest` (no additional properties): the server alone sets an order's origin
    and its link id (24 Sec.8.3), so a body naming one is refused as an unknown field, recorded."""
    resp, written = call(unchanged, "owner", "POST", "/orders", f"ac09|{field}", json=_CLOSE | {
        field: "x"})  # fmt: skip
    errors = [(e["field"], e["rule"]) for e in resp.json().get("errors", [])]
    assert (observed(resp), errors) == ("400 validation_failed", [(field, "extra_forbidden")])
    assert written == [("orders.submit", "validation_failed")]


def test_ac09_the_same_body_without_it_passes_the_body_check(world: OmsWorld) -> None:
    resp, _ = call(world, "owner", "POST", "/orders", "ac09|control", json=_CLOSE)
    assert observed(resp) != "400 validation_failed", resp.text


_WRITES: Final = sorted(k for k in cells.rows("executed") if not k.startswith("GET "))
#: Each request that lacks its CSRF proof, and the reason the guard records (SR-041, SR-042).
_CSRF: Final = {
    "missing": "missing", "another_sessions": "wrong_session", "foreign_origin": "cross_origin",
    "cross_site": "cross_origin",
}  # fmt: skip


@pytest.mark.parametrize("variant", list(_CSRF))
@pytest.mark.parametrize("key", _WRITES)
def test_ac27_an_owners_write_without_its_csrf_proof_is_refused_before_the_handler(
    unchanged: OmsWorld, key: str, variant: str
) -> None:
    """SR-041, SR-042, OM-S01: the Owner, allowed every write, without the token, with another
    session's pair, from a foreign `Origin` or labelled `Sec-Fetch-Site: cross-site` with no
    `Origin`: 403 `csrf_token_invalid`, counted under its reason, no store changed, nothing sent.
    Its record is the guard's, within the guard's per-session audit budget (its own suite)."""
    cell = cells.Cell(key, "owner", "granted", "allow")
    path, kw, headers = matrix.sent(cell)
    rid = request_id(f"ac27|{cell.id}|{variant}")
    headers |= {**bearer("owner"), "X-Correlation-Id": rid}
    if variant == "missing":
        del headers[CSRF_HEADER]
    elif variant == "another_sessions":
        headers |= {k: v for k, v in bearer("viewer").items() if k != "Authorization"}
    elif variant == "foreign_origin":
        headers["Origin"] = "https://elsewhere.invalid"
    request = unchanged.client.build_request(key.split(" ")[0], path, headers=headers, **kw)
    if variant == "cross_site":
        del request.headers["origin"]
        request.headers["Sec-Fetch-Site"] = "cross-site"
    reason = _CSRF[variant]
    counted = tally(auth_csrf_refused_total, "auth_csrf_refused_total", reason=reason)
    resp = unchanged.client.send(request)
    written = [(r["action"], r.get("reason")) for r in unchanged.by_request.get(rid, [])]
    assert observed(resp) == "403 csrf_token_invalid", (variant, resp.text)
    assert tally(auth_csrf_refused_total, "auth_csrf_refused_total", reason=reason) - counted == 1
    assert written in ([], [("auth.csrf_refused", reason)]), written


# --- Pinned: the per-user limit (OM-D01, SR-044d) -------------------------------------------------

#: One past the position writes' per-user rate, the shipped rate the order routes are pinned to.
_BURST: Final = position_close.RATE_PER_MINUTE + 1
_PER_USER: Final = "X02-R{} (#1152): {} meets a per-user limit (OM-D01)"


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=_PER_USER.format(
    4, "a burst of orders from one session"))  # fmt: skip
@pytest.mark.parametrize("shape", ["entry", "refused_late"])
def test_ac19_a_burst_of_orders_from_one_session_meets_a_429_and_another_user_is_admitted(
    world: OmsWorld, shape: str
) -> None:
    """AC-19 and the rows posted on #982 on 2026-10-23 and 2026-10-24: a burst from one session,
    of entries or of requests refused late (a malformed `Idempotency-Key`), meets `429
    rate_limited` with `Retry-After`, and another user's order is still admitted."""
    late = {"headers": {"Idempotency-Key": "not-a-key"}} if shape == "refused_late" else {}
    entry = _CLOSE | {"reduce_only": False, "stop_loss": {"unit": "price", "value": "58000"}}
    answers = [
        call(world, M, "POST", "/orders", f"ac19|{shape}|{n}", json=entry, **late)[0]
        for n in range(_BURST)
    ]
    limited = [r for r in answers if observed(r) == "429 rate_limited"]
    assert limited and all(r.headers.get("Retry-After") for r in limited), {
        observed(r) for r in answers}  # fmt: skip
    other, _ = call(world, "owner", "POST", "/orders", f"ac19|{shape}|other", json=entry)
    assert observed(other) != "429 rate_limited"


class _Tickers:
    """The ticker stream's demand: the symbols each consumer holds, in the order taken."""

    def __init__(self) -> None:
        self.held: list[str] = []

    def acquire(self, consumer: str, symbol: str) -> None:
        self.held.append(symbol)

    def release(self, consumer: str, symbol: str) -> None:
        self.held.remove(symbol)


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=_PER_USER.format(
    5, "the reference price's demand for new symbols"))  # fmt: skip
def test_982_row_2_one_principals_new_symbols_leave_another_principals_demand_admitted() -> None:
    """The row posted on #982 on 2026-10-23 (CR-S3E4-02): the window's budget of new symbols is
    kept per principal, so one principal's cold symbols leave another's market order its price.
    `asked` names no principal: the pin asks as the runtime does."""
    tickers = _Tickers()
    demand = ReferenceDemand(tickers, monotonic=lambda: 0.0)
    symbols = [f"COLD{n}USDT" for n in range(REFERENCE_DEMAND_NEW + 1)]
    for symbol in symbols[:-1]:  # one principal's new symbols, the whole window's budget
        demand.asked(symbol, priced=False)
    demand.asked(symbols[-1], priced=False)  # another principal's
    assert tickers.held[-1:] == symbols[-1:], tickers.held
