"""Integration (E28-T05 S3d, #909): AC 7 and SR-E28-22 over the E28 seed on Postgres 16.
`previewTradeGroup` (`make_trade_group_preview_router`) reads the legs' rows and profiles through
the real stores on a pool whose engine refuses writes (`postgresql_readonly`: every transaction is
`READ ONLY`, so a write fails with SQLSTATE 25006), and writes its audit rows through a real
`AuditWriter` on a pool of its own. The OMS's preview parts are the order path's own classes: the
leg guard over the interim risk gate, the stop resolver, the listing of the 2026-10-05 capture's
BTCUSDT, prices with no ticker composed, and `PreviewFigures` over the account binding and
`DayRiskFigures`, whose venue is a recording `FakeTradingPort` (C-13.5); cold, the binding reads
each account over the read-only pool, as the lane reads it. `serving` composes it for the golden
module too. Needs Docker; CI's `integration` job runs it."""

from __future__ import annotations

import itertools
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import httpx
import psycopg
import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from psycopg import sql
from sqlalchemy import event
from sqlalchemy import exc as sa_exc
from structlog.testing import capture_logs

from candleviewer.accounts.profile_cache import EffectiveProfiles
from candleviewer.accounts.repository import AccountsRepository
from candleviewer.api.order_principal import TradingPrincipal
from candleviewer.api.preview_limiter import PreviewLimiter
from candleviewer.api.trade_group_preview import PREVIEW_PATH, PreviewReads
from candleviewer.api.trade_group_preview import make_trade_group_preview_router as router
from candleviewer.api.trade_groups_gate import TradeGroupsGate
from candleviewer.audit.writer import AuditWriter
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.fakes import FakeTradingPort
from candleviewer.exchange.base.models import AccountRef, FeeRate, RiskLimitTier, Wallet
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.day_figures import DayRiskFigures
from candleviewer.oms.fanout.guard import S4SGuard
from candleviewer.oms.ports import InterimRiskGate, InterimStopResolver
from candleviewer.oms_wiring import (
    InstrumentsBinding,
    PreviewFigures,
    PreviewParts,
    ReferencePricesBinding,
    TradingAccountsBinding,
)
from candleviewer.storage.repositories.account_profiles_sqlalchemy import (
    SqlAlchemyAccountProfileStore,
)
from candleviewer.storage.repositories.accounts_sqlalchemy import SqlAlchemyAccountsStore
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.orders_sqlalchemy import OMS_STATEMENT_TIMEOUT_MS
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
    sqlstate_of,
)
from candleviewer.storage.repositories.trading_accounts import (
    InMemoryTradingAccountReads,
    TradingAccountReads,
    TradingAccountRow,
)
from candleviewer.storage.repositories.trading_accounts_sqlalchemy import (
    SqlAlchemyTradingAccountReads,
)
from tests.integration import _refused
from tests.unit.accounts.test_sizer import instrument

pytestmark = pytest.mark.integration

pg_dsn = _refused.pg_dsn  # the module-scoped Postgres 16, migrated; its database is named `test`
_E28 = Path(__file__).resolve().parents[5] / "tests" / "fixtures" / "e28"
OWNER = UUID("e28f0000-0000-4000-8000-000000000001")
A, B, C, D = (AccountId(UUID(f"e28f0000-0000-4000-8000-0000000000d{n}")) for n in range(1, 5))
LIVE, MISSING = AccountId(UUID("e28f0000-0000-4000-8000-0000000000f1")), AccountId(UUID(int=7))
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
#: The key id the account binding gives every account (no seed row has one), as a key ref.
KEY = str(UUID(int=5))
#: The tables a preview leaves as they were (AC 7): groups, legs, orders, definitions, profiles.
KEPT = ("trade_groups", "trade_group_legs", "orders", "trade_group_definitions",
        "trade_group_definition_members", "account_profiles")  # fmt: skip
_TIER = RiskLimitTier(
    tier_id=1, risk_limit_value=Decimal(2_000_000), initial_margin_rate=Decimal("0.01"),
    maintenance_margin_rate=Decimal("0.005"), max_leverage=Decimal(100),
)  # fmt: skip


class Listed(dict[str, Any]):
    """The catalogue's snapshot: the capture's BTCUSDT and its lowest risk-limit tier."""

    def risk_limit_tiers(self, symbol: str) -> tuple[RiskLimitTier, ...] | None:
        return (_TIER,) if symbol in self else None


LISTED = Listed(BTCUSDT=instrument("BTCUSDT"))


class Readiness:
    """The seed's readiness: E28-B's key self-check disarmed it, unless `ready` overrides it."""

    def __init__(self, *, ready: bool = False) -> None:
        self.not_ready = {} if ready else {B: "account_disabled"}

    def reason(self, account_id: UUID, environment: Any, *, account_enabled: bool) -> Any:
        return self.not_ready.get(AccountId(account_id))


def buy(*legs: UUID | tuple[UUID, dict[str, Any]]) -> dict[str, Any]:
    """A BTCUSDT limit buy at 64000.0, the vectors' intent, one leg per account named."""
    named = [{"exchange_account_id": str(leg)} if isinstance(leg, UUID) else
             {"exchange_account_id": str(leg[0]), "overrides": leg[1]} for leg in legs]  # fmt: skip
    return {"symbol": "BTCUSDT", "side": "buy", "order_type": "limit",
            "defaults": {"price": "64000.0"}, "legs": named}  # fmt: skip


@dataclass
class Served:
    """One process's preview: its client and metrics, every statement its read-only pool and its
    audit writer's pool ran, that read-only pool, and its audit writer."""

    client: httpx.AsyncClient
    metrics: Metrics
    reads: list[str]
    writes: list[str]
    pool: SqlAlchemyRelationalRepository
    writer: AuditWriter

    async def post(self, body: dict[str, Any]) -> httpx.Response:
        return await self.client.post(PREVIEW_PATH, json=body)


@asynccontextmanager
async def serving(dsn: str, wal: Path, figures: Any, readiness: Any) -> AsyncIterator[Served]:
    """The route as the root composes it, but its reads' pool refuses writes and its audit
    writer's pool is its own; the seed's Owner sends every request. `figures` are the preview's,
    or, called with that read-only pool, build them over it."""
    pool, audit = (SqlAlchemyRelationalRepository(dsn, name) for name in ("ro", "audit"))
    pool.engine.update_execution_options(postgresql_readonly=True)  # every transaction READ ONLY
    logs: tuple[list[str], list[str]] = ([], [])
    for each, log in zip((pool, audit), logs, strict=True):
        event.listen(each.engine.sync_engine, "before_cursor_execute",
                     lambda *ran, log=log: log.append(str(ran[2])))  # fmt: skip
    writer = AuditWriter(SqlAlchemyAuditRepository(audit), str(wal))
    profiles = EffectiveProfiles(SqlAlchemyAccountProfileStore(pool))
    reads = PreviewReads(AccountsRepository(SqlAlchemyAccountsStore(pool)), profiles, readiness,
                         "demo")  # fmt: skip
    listing = InstrumentsBinding(cast(Any, SimpleNamespace(snapshot=lambda: LISTED)))
    parts = PreviewParts(
        S4SGuard(InterimRiskGate(now=lambda: NOW), SimpleNamespace(refusal=lambda *_: None)),
        InterimStopResolver(), listing, ReferencePricesBinding(None),
        figures(pool) if callable(figures) else figures,
    )  # fmt: skip
    owner = TradingPrincipal(UUID(int=1), PrincipalSnapshot(OWNER, frozenset({"owner"}),
                                                            frozenset(Permission)))  # fmt: skip
    app, metrics = FastAPI(), Metrics("demo")
    app.include_router(router(
        SimpleNamespace(resolve=lambda _request: owner),
        lambda: cast(Any, SimpleNamespace(readiness="ok", preview=parts)), reads=reads,
        gate=TradeGroupsGate(lambda: True, preview_ready=True), audit=cast(Any, writer),
        limiter=PreviewLimiter(100, clock=itertools.count().__next__),  # a second a request
        metrics=metrics,
    ))  # fmt: skip
    await writer.start()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://cv") as client:
            yield Served(client, metrics, *logs, pool, writer)
    finally:
        await writer.stop(5.0)
        await profiles.aclose()
        for each in (pool, audit):
            await each.dispose()


@pytest.fixture(scope="module")
def seeded(pg_dsn: str) -> str:
    """`pg_dsn` with the E28 seed loaded once, as its README loads it."""
    with psycopg.connect(pg_dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True) as c:
        c.execute((_E28 / "seed.sql").read_bytes())  # the file's own BEGIN ... COMMIT
    return pg_dsn


def _rows(dsn: str, query: sql.Composed | str, *args: object) -> list[tuple[Any, ...]]:
    with psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True) as c:
        return c.execute(query, args).fetchall()


def _kept(dsn: str) -> dict[str, list[tuple[Any, ...]]]:
    """Each kept table's every row, as text: a change to any one of them shows."""
    each = sql.SQL("SELECT t::text FROM {} t ORDER BY 1")
    return {table: _rows(dsn, each.format(sql.Identifier(table))) for table in KEPT}


class Venue(FakeTradingPort):
    """The demo venue `DayRiskFigures` reads through: each figure's account with 10000 USDT,
    no fee, nothing open and no loss today; every call is recorded (`calls`), and so is every
    port asked of it (`asked`)."""

    def __init__(self) -> None:
        super().__init__(environment="demo")
        self.asked: list[str] = []
        cash, none = Decimal(10000), Decimal(0)
        for account in (A, B, C, D):
            self.set_wallet(Wallet(
                account_id=account, equity=cash, wallet_balance=cash, available_to_withdraw=None,
                available_margin=cash, used_margin=none, unrealised_pnl=none,
                cum_realised_pnl=none, account_im_rate=none, account_mm_rate=none, updated_at=0,
            ))  # fmt: skip
            self.set_fee_rate(account, FeeRate(symbol="BTCUSDT", maker=none, taker=none,
                                               fetched_at=0))  # fmt: skip

    def port_for(self, environment: str) -> Venue:
        self.asked.append(environment)
        return self


def _figures(
    venue: Venue, reads: TradingAccountReads | None = None
) -> tuple[PreviewFigures, DayRiskFigures]:
    """The order path's figures over `venue`, on a clock that never moves, and the preview's
    peek of them through the account binding over `reads`: by default, rows that give each account
    a key, as no seed row has."""
    kept = DayRiskFigures("demo", port_for=venue.port_for, tiers=LISTED.risk_limit_tiers,
                          now=lambda: NOW, monotonic=lambda: 100.0)  # fmt: skip
    rows = (TradingAccountRow(a, "demo", "928", False, UUID(KEY)) for a in (A, B, C, D))
    keyed = InMemoryTradingAccountReads(*rows) if reads is None else reads
    return PreviewFigures(TradingAccountsBinding(keyed, environment="demo"), kept), kept


def _lane_on(pool: SqlAlchemyRelationalRepository) -> PreviewFigures:
    """Cold: nothing kept, and each account read by the lane's own read over `pool`, as the root
    composes it (`oms_wiring.pg_stores`); no seed row has a key, so each leg is `figure_unknown`."""
    reads = SqlAlchemyTradingAccountReads(pool, statement_timeout_ms=OMS_STATEMENT_TIMEOUT_MS)
    return _figures(Venue(), reads)[0]


@pytest.mark.parametrize("cold", [False, True], ids=["warm", "cold"])
async def test_preview_runs_in_a_read_only_transaction(
    seeded: str, tmp_path: Path, cold: bool
) -> None:
    """AC 7: the preview's reads run on an engine whose every write fails with 25006, and 100
    previews (sized, skipped and refused alike) leave the groups, legs, orders, definitions and
    profiles as they were; none answers 500. What lands is their audit rows alone, through the
    writer's own pool, and every statement of theirs ran on the read-only engine. Warm, the legs'
    figures are kept as the order path keeps them; cold (R1C-04), nothing is kept and the lane's
    own account read runs on that engine too, once for each leg the request does not skip."""
    figures, kept = _figures(Venue())
    for account in () if cold else (A, C):  # warm, as the order path keeps them
        ref = AccountRef(account_id=account, uid="928", environment="demo", key_ref=KEY)
        await kept.read(ref, ("BTCUSDT",), fallback_sl_offset_pct=Decimal("0.02"))
    cases = [
        (200, buy(A, C)),
        (200, buy(A, (B, {"skip": True}), D)),
        (403, buy((A, {"leverage": "11"}))),
        (400, buy(A, LIVE)),
        (403, buy(A, MISSING)),
    ]
    audited, before = "SELECT action, count(*) FROM audit_log GROUP BY 1", _kept(seeded)
    was = Counter(dict(_rows(seeded, audited)))
    composed = _lane_on if cold else figures
    async with serving(seeded, tmp_path / "audit.wal", composed, Readiness()) as served:
        async with served.pool.unit_of_work() as uow:  # what any write of the reads meets
            with pytest.raises(sa_exc.DBAPIError) as refused:
                await uow.session.execute(
                    sa.text("UPDATE trade_groups SET closed_at = closed_at WHERE false")
                )
        served.reads.clear()  # the probe's own statements
        with capture_logs() as logged:
            answers = [await served.post(body) for _ in range(20) for _, body in cases]
        await served.writer.flush(30.0)
    assert sqlstate_of(refused.value) == "25006"
    assert [r.status_code for r in answers] == [status for status, _ in cases] * 20
    first = "blocked" if cold else "ready"
    assert [[leg["status"] for leg in r.json()["legs"]] for r in answers[:2]] == [
        [first, "blocked" if cold else "warn"], [first, "skipped", "skipped"],
    ]  # fmt: skip
    unknown = [leg["rejection"]["code"] for leg in answers[0].json()["legs"] if cold]
    assert unknown == ["figure_unknown"] * (2 if cold else 0)  # cold: no seed row has a key
    assert _kept(seeded) == before
    assert Counter(dict(_rows(seeded, audited))) - was == {
        "rbac.denied": 20, "trade_group.override_refused": 20, "trade_group.previewed": 100,
    }  # fmt: skip
    assert {s.split(None, 1)[0].upper() for s in served.reads} == {"SET", "SELECT"}
    read = ("exchange_accounts", "account_profiles")
    assert all(any(table in s for s in served.reads) for table in read)
    assert not [s for s in served.writes if any(t in s for t in (*KEPT, *read))]
    lane = [s for s in served.reads if "active_key_id" in s]  # A and C, then A and D, a round
    unread = [e for e in logged if e["event"] == "oms_account_unread"]  # one the engine refused
    assert (len(lane), unread) == (4 * 20 if cold else 0, [])


async def test_preview_makes_no_exchange_call(seeded: str, tmp_path: Path) -> None:
    """SR-E28-22: the venue sees no call and the figures ask it for no port, cold (nothing kept:
    each leg `figure_unknown`) or warm (kept by the order path's read: each leg sized)."""
    venue = Venue()
    figures, kept = _figures(venue)
    async with serving(seeded, tmp_path / "audit.wal", figures, Readiness()) as served:
        cold = await served.post(buy(A, C))
        assert (venue.calls, venue.asked) == ([], [])
        for account in (A, C):
            ref = AccountRef(account_id=account, uid="928", environment="demo", key_ref=KEY)
            await kept.read(ref, ("BTCUSDT",), fallback_sl_offset_pct=Decimal("0.02"))
        calls, asked = len(venue.calls), len(venue.asked)
        warm = await served.post(buy(A, C))
    assert [leg["rejection"]["code"] for leg in cold.json()["legs"]] == ["figure_unknown"] * 2
    assert [leg["status"] for leg in warm.json()["legs"]] == ["ready", "warn"]
    assert (venue.calls[calls:], venue.asked[asked:]) == ([], [])
