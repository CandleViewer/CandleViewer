"""E21-X02 (#652): the ticket's RBAC assertions, at the protocol level (the Gherkin scenario "Cross-
account subscription refused at the protocol level"; AC-HM-01, AC-HM-17's route leg; the model's
HM-S01, HM-E05). Over the E17-X02 raw rig on the real `/ws` router with real sessions, under both
subprotocols (`conftest.py`); the REST leg on the real `GET /market/heatmap` router.

`marketdata:read` gates every market-data topic. The families come from the registry
(`FAMILIES`): each whose channel names a symbol and no account, read from its shapes and never
from its permission or a list written here, so a family registered later, or with another
permission, is covered at once; each is sent with the RBAC matrix's own sample
(`tests/contract/rbac/matrix.yaml`)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pytest
import yaml
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.market_heatmap import make_market_heatmap_router
from candleviewer.audit.access import AuditPrincipal
from candleviewer.auth.generated_permissions import Permission
from candleviewer.orderflow.heatmap_history import BookAnchor, BookChange, CellSpan
from candleviewer.ws.topics import FAMILIES
from tests.security.marketdata.conftest import QuotaWorld
from tests.security.ws._raw import (
    answers,
    authenticated,
    delta,
    drained,
    naming,
    publish,
    raw_connect,
    topic,
)
from tests.unit.ws._seq_support import ACC_A, ACC_B

_MATRIX: Final = Path(__file__).resolve().parents[2] / "contract" / "rbac" / "matrix.yaml"
#: Every market-data family: one whose channel names a symbol (23 §6.1) and no account.
MARKET_DATA: Final = sorted(
    name
    for name, fam in FAMILIES.items()
    if not fam.account_scoped and any("symbol" in shape for shape in fam.shapes)
)


def _samples() -> list[dict[str, Any]]:
    """One `sub` entry a market-data family, as the RBAC matrix samples it."""
    rows = yaml.safe_load(_MATRIX.read_text(encoding="utf-8"))["topics"]
    missing = [f for f in MARKET_DATA if f not in rows]
    assert missing == [], f"no RBAC matrix row for {missing}"
    return [
        {"ch": rows[f]["sample"], **({"opts": rows[f]["opts"]} if rows[f].get("opts") else {})}
        for f in MARKET_DATA
    ]


def test_every_market_data_topic_requires_marketdata_read(world: QuotaWorld) -> None:
    assert {"book", "heatmap", "trades", "bars"} <= set(MARKET_DATA)
    assert len(MARKET_DATA) >= 10  # the registry was read: ten when this was written
    wrong = {f: FAMILIES[f].permission for f in MARKET_DATA}
    assert {f for f, p in wrong.items() if p is not Permission.MARKETDATA_READ} == set(), wrong
    entries = _samples()
    every = frozenset(Permission)
    bare = world.login("bare", ACC_A, perms=every - {Permission.MARKETDATA_READ})
    reader = world.login("reader", ACC_A, perms=every)
    for login, refused in ((bare, True), (reader, False)):
        with raw_connect(world) as c:
            authenticated(c, login)
            results = answers(c, *entries)
        codes = [r.get("error", {}).get("code") for r in results]
        if refused:
            assert codes == ["forbidden"] * len(MARKET_DATA), dict(
                zip(MARKET_DATA, codes, strict=True)
            )
        else:
            assert "forbidden" not in codes, dict(zip(MARKET_DATA, codes, strict=True))


def test_cross_account_subscription_refused_at_the_protocol_level(world: QuotaWorld) -> None:
    """Scenario: Cross-account subscription refused at the protocol level. A Manager granted
    account A alone hand-crafts `sub positions` and `sub orders` naming B: both are refused
    `account_scope_denied`, counted and audited; naming A and B, both are narrowed to A; and
    while B's rows are published, not one frame on the socket names B."""
    m1 = world.login("m1", ACC_A)
    denied = delta("cv_ws_subscribe_total", topic="positions", result="account_scope_denied")
    with raw_connect(world) as c:
        authenticated(c, m1)
        refused = answers(c, topic("positions", ACC_B), topic("orders", ACC_B))
        assert [(r["ch"], r["error"]["code"]) for r in refused] == [
            ("positions", "account_scope_denied"),
            ("orders", "account_scope_denied"),
        ]
        assert denied() == 1  # the series `WsAccountScopeDenied` reads
        narrowed = answers(c, topic("positions", ACC_B, ACC_A), topic("orders", ACC_B, ACC_A))
        assert [r["effective"]["exchange_account_ids"] for r in narrowed] == [[str(ACC_A)]] * 2
        drained(c)  # their snapshots
        assert [publish(world, f, ACC_B) for f in ("positions", "orders")] == [0, 0]
        assert [publish(world, f, ACC_A) for f in ("positions", "orders")] == [1, 1]
        got = drained(c)
    assert sorted(f["ch"] for f in got) == ["orders", "positions"]  # A's rows reach it
    assert naming(c.seen, ACC_B) == []  # not one frame of the whole stream names B
    rows = world.audit.of("ws.subscribe.denied")  # one record a frame (SR-192)
    assert [r["reason"] for r in rows] == ["account_scope_denied", "narrowed"]
    assert {r["actor_user_id"] for r in rows} == {m1.user_id}


class _Reader:
    """A `HeatmapHistoryReader` that records whether it was read at all."""

    def __init__(self) -> None:
        self.reads = 0

    async def first_available(self, symbol: str) -> int | None:
        self.reads += 1
        return None

    async def cells(self, symbol: str, lo_us: int, hi_us: int) -> Any:  # pragma: no cover
        self.reads += 1
        yield CellSpan(lo_us, hi_us, "hot", [])

    async def book_anchor(  # pragma: no cover - no history: never asked
        self, symbol: str, depth: int, at_us: int, *, not_before_us: int
    ) -> BookAnchor | None:
        return None

    async def book_changes(  # pragma: no cover - no history: never asked
        self, symbol: str, depth: int, lo_us: int, hi_us: int
    ) -> list[BookChange]:
        return []


@pytest.mark.parametrize(
    ("permissions", "status"),
    [(frozenset(), 403), (frozenset({"orders:read", "settings:write"}), 403), (None, 401)],
    ids=["none", "others", "unauthenticated"],
)
def test_market_heatmap_requires_marketdata_read(
    permissions: frozenset[str] | None, status: int
) -> None:
    """`x-rbac` `marketdata:read`: without it the route answers before any read (C-12.4); with
    it, the same request is served."""
    reader = _Reader()
    held: dict[str, AuditPrincipal | None] = {"who": None}

    class _Resolver:
        async def resolve(self, request: Request) -> AuditPrincipal | None:
            return held["who"]

    app = FastAPI()
    app.include_router(
        make_market_heatmap_router(
            lambda: reader,
            principal_resolver=_Resolver(),
            symbol_listed=lambda symbol: True,
            tick_size=lambda symbol: Decimal("0.1"),
            now_us=lambda: 1_790_812_800_000_000,
        )
    )
    user = uuid.uuid4()
    params = {"symbol": "BTCUSDT", "from": "2026-09-30T00:00:00Z"}
    if permissions is not None:
        held["who"] = AuditPrincipal(user_id=user, username="u", permissions=permissions)
    r = TestClient(app).get("/market/heatmap", params=params)
    assert r.status_code == status and reader.reads == 0
    held["who"] = AuditPrincipal(
        user_id=user, username="u", permissions=frozenset({"marketdata:read"})
    )
    assert TestClient(app).get("/market/heatmap", params=params).status_code == 200
    assert reader.reads == 1
