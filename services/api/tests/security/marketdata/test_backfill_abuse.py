"""E21-X02 (#652): the backfill route's abuse cases (AC-HM-08, AC-HM-13, AC-HM-14; G-05, G-06; the
Gherkin scenarios "Path traversal refused" and "Oversized backfill"; chaos C-13.6 #10).

The real `GET /market/heatmap` router over the real `StoredHeatmapReader`: the real Parquet cold
tier on a temporary archive root, beside a directory outside it holding a canary, and a hot tier
that serves generated cells and records every call (QuestDB's own reads are E07's). Filesystem
spies on `open`, `scandir` and `listdir` (the SR-097 suite's) watch both tiers' reads: a refused
request touches no path and makes no call, and no request reads outside the root. Principals are
the real `AuditPrincipal` (`api/audit_principal.py` builds them), so view-as is the real field."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from candleviewer.api.market_heatmap import (
    MAX_PER_USER,
    MAX_WINDOW_DAYS,
    make_market_heatmap_router,
)
from candleviewer.audit.access import AuditPrincipal
from candleviewer.heatmap_wiring import StoredHeatmapReader
from candleviewer.orderflow.heatmap_history import ANCHOR_LOOKBACK_US, ANCHOR_STEP_US, MAX_COLUMNS
from candleviewer.storage.cold.layout import DatasetRegistry, stream_dir_name
from candleviewer.storage.cold.recorded_reader import ParquetRecordedReader
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import (
    HeatmapCell,
    RecordedBookSnapshot,
    RecordedEvent,
)
from tests.security.storage.test_sr097_path_traversal import FsSpy

T0 = 1_790_812_800_000_000  # 2026-10-01 00:00 UTC
S = 1_000_000
DAY = 86_400 * S
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
LISTED = frozenset({"BTCUSDT", "ETHUSDT"})
#: The streams a read's `first_available` lists in each tier (`heatmap_wiring._FIRST_STREAMS`).
_FIRST_STREAMS = (
    StreamKind.HEATMAP_CELLS,
    StreamKind.ORDERBOOK_SNAPSHOT,
    StreamKind.ORDERBOOK_DELTA,
)
#: The route's own request values crafted to leave the archive root (AC-HM-08): each a `422`.
SYMBOLS = [
    "../",
    "%2e%2e%2f",
    "BTCUSDT/..",
    "BTCUSDT/../ETHUSDT",
    "BTCUSDT\x00",
    "BTC" + chr(0x0661) + "USDT",  # an Arabic-Indic digit
    chr(0xFF22) + "TCUSDT",  # a fullwidth letter
    "../../etc/passwd",
    "/etc/passwd",
    "..\\..\\win.ini",
    ".hidden",
    "",
    "btcusdt",
    "A" * 300 + "USDT",
]


def iso(us: int) -> str:
    """`us` as an RFC 3339 instant, exact to the microsecond."""
    return (_EPOCH + timedelta(microseconds=us)).isoformat().replace("+00:00", "Z")


#: The year 2026 in Arabic-Indic digits.
_ARABIC_2026 = "".join(map(chr, (0x0662, 0x0660, 0x0662, 0x0666)))
#: Malformed `from` / `to` (`422 validation_failed`) and out-of-bounds ones (`400
#: invalid_time_range`), each refused before any read. `None` leaves `to` to the server's clock.
DATES: list[tuple[str, str | None, int, str]] = [
    ("../2026-10-01T00:00:00Z", None, 422, "validation_failed"),
    # three a lenient parser reads as a day before the clock: only the RFC 3339 shape refuses them
    ("2026-09-30T00:00:00Z\x00", None, 422, "validation_failed"),
    ("2026-09-30 00:00:00+00:00", None, 422, "validation_failed"),
    ("2026-09-30T00:00:00", None, 422, "validation_failed"),  # no offset
    ("2026-10-01T00:00:00Z/..", None, 422, "validation_failed"),
    (_ARABIC_2026 + "-10-01T00:00:00Z", None, 422, "validation_failed"),
    ("2026-13-01T00:00:00Z", None, 422, "validation_failed"),
    ("2026-09-30", None, 422, "validation_failed"),  # a date, not the date-time 22 types
    ("1e309", None, 422, "validation_failed"),
    ("-1", None, 422, "validation_failed"),
    ("2026-09-30T00:00:00Z", "../x", 422, "validation_failed"),
    ("2026-09-30T00:00:00Z", "2026-10-01T00:00:00Z%00", 422, "validation_failed"),
    ("0001-01-01T00:00:00Z", None, 400, "invalid_time_range"),
    ("2026-09-30T00:00:00Z", "9999-12-31T23:59:59Z", 400, "invalid_time_range"),
]


def _cell(ts: int, price: float, bid: float = 1.0) -> HeatmapCell:
    return (ts, price, bid, 0.5, 10, False)


def _snapshot(ts: int) -> RecordedEvent:
    """A recorded depth-200 book, ten levels a side around 60 000, sizes all distinct."""
    bids = tuple((Decimal("60000.0") - Decimal("0.1") * i, Decimal(1 + i)) for i in range(10))
    asks = tuple((Decimal("60000.1") + Decimal("0.1") * i, Decimal(2 + i)) for i in range(10))
    snap = RecordedBookSnapshot(200, 7, None, bids, asks)
    return RecordedEvent(ts, 0, "BTCUSDT", StreamKind.ORDERBOOK_SNAPSHOT, (0,), snap)


class HotTier:
    """The hot tier as `StoredHeatmapReader` reads it: generated cells and snapshots, every call
    recorded. A symbol in `hold` waits in `earliest` until its event is set; `fail` raises."""

    def __init__(
        self,
        *,
        first: int | None = None,
        cells: Sequence[HeatmapCell] = (),
        snapshots: Sequence[RecordedEvent] = (),
        fail: Exception | None = None,
    ) -> None:
        self.first, self.cells = first, sorted(cells)
        self.snapshots = sorted(snapshots, key=lambda e: e.ts_us)
        self.fail = fail
        self.calls: list[str] = []
        self.hold: dict[str, asyncio.Event] = {}
        self.inside: dict[str, int] = {}
        self.all_in = asyncio.Event()  # set once `MAX_PER_USER` held reads are inside

    async def earliest(self, symbol: str, stream: StreamKind) -> int | None:
        self.calls.append("earliest")
        if (gate := self.hold.get(symbol)) is not None and stream is StreamKind.HEATMAP_CELLS:
            self.inside[symbol] = self.inside.get(symbol, 0) + 1
            if self.inside[symbol] >= MAX_PER_USER:
                self.all_in.set()
            await gate.wait()
        if self.fail is not None:
            raise self.fail
        return self.first

    async def heatmap_cells(self, symbol: str, rng: TimeRange, *, limit: int) -> list[HeatmapCell]:
        self.calls.append("heatmap_cells")
        return [c for c in self.cells if rng.start_us <= c[0] < rng.end_us][:limit]

    async def snapshot_at(
        self, symbol: str, depth: int, at_us: int, *, not_before_us: int
    ) -> RecordedEvent | None:
        self.calls.append("snapshot_at")
        found = [e for e in self.snapshots if not_before_us <= e.ts_us <= at_us]
        return found[-1] if found else None

    async def read(
        self, symbol: str, stream: StreamKind, rng: TimeRange, *, depth: int, limit: int
    ) -> list[RecordedEvent]:
        self.calls.append("read")
        return []


@dataclass
class Rig:
    """The router over the real reader; `principals` by the `x-principal` header."""

    hot: HotTier
    cold: ParquetRecordedReader
    root: Path
    canary: Path
    app: FastAPI
    principals: dict[str, AuditPrincipal]

    async def resolve(self, request: Request) -> Any:
        return self.principals.get(request.headers.get("x-principal", "reader"))

    def get(self, params: dict[str, Any], *, who: str = "reader") -> httpx.Response:
        query = {"symbol": "BTCUSDT", "from": iso(T0 - DAY)} | params
        response: httpx.Response = TestClient(self.app).get(
            "/market/heatmap", params={k: v for k, v in query.items() if v is not None},
            headers={"x-principal": who},
        )  # fmt: skip
        return response


def _principal(user: uuid.UUID, *, actor: uuid.UUID | None = None) -> AuditPrincipal:
    return AuditPrincipal(
        user_id=user, username=str(user)[:8], permissions=frozenset({"marketdata:read"}),
        actor_user_id=actor, actor_username=None if actor is None else str(actor)[:8],
    )  # fmt: skip


def _rig(tmp_path: Path, hot: HotTier, now: int = T0) -> Rig:
    root, canary = tmp_path / "cold", tmp_path / "outside"
    root.mkdir()
    canary.mkdir()
    (canary / "secret.txt").write_text("x")
    registry = DatasetRegistry(root)
    registry.ensure_tree()
    for stream in _FIRST_STREAMS:  # an archive with nothing in it yet: its listings still run
        (root / "_manifests" / stream_dir_name(stream)).mkdir(parents=True)
    cold = ParquetRecordedReader(registry)
    rig = Rig(hot, cold, root, canary, FastAPI(), {"reader": _principal(uuid.uuid4())})
    rig.app.include_router(
        make_market_heatmap_router(
            lambda: StoredHeatmapReader(hot, cold),
            principal_resolver=rig,
            symbol_listed=lambda symbol: symbol in LISTED,
            tick_size=lambda symbol: Decimal("0.1"),
            now_us=lambda: now,
        )
    )
    return rig


@pytest.fixture
def rigs() -> Iterator[list[Rig]]:
    """Every rig a test builds has its cold reader shut down at the end."""
    made: list[Rig] = []
    yield made
    for rig in made:
        rig.cold.shutdown()


def _built(rigs: list[Rig], tmp_path: Path, hot: HotTier, now: int = T0) -> Rig:
    rig = _rig(tmp_path, hot, now)
    rigs.append(rig)
    return rig


def _sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


@pytest.mark.parametrize("symbol", SYMBOLS)
def test_path_traversal_refused_symbol_corpus(
    symbol: str, rigs: list[Rig], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scenario: Path traversal refused (the symbol): `422` during validation, and neither tier
    is called nor any path touched."""
    rig = _built(rigs, tmp_path, HotTier(first=T0 - DAY))
    spy = FsSpy(monkeypatch)
    r = rig.get({"symbol": symbol})
    assert (r.status_code, r.json()["code"]) == (422, "validation_failed")
    assert (rig.hot.calls, spy.touched) == ([], [])


@pytest.mark.parametrize(("start", "end", "status", "code"), DATES)
def test_path_traversal_refused_date_corpus(
    start: str,
    end: str | None,
    status: int,
    code: str,
    rigs: list[Rig],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scenario: Path traversal refused (the dates): a malformed `from` or `to` is `422`, an
    extreme one `400 invalid_time_range` (22 "Bounds"), each before any read or path."""
    rig = _built(rigs, tmp_path, HotTier(first=T0 - DAY))
    spy = FsSpy(monkeypatch)
    r = rig.get({"from": start, "to": end})
    assert (r.status_code, r.json()["code"]) == (status, code)
    assert (rig.hot.calls, spy.touched) == ([], [])


def test_path_traversal_refused_touches_no_path_outside_the_archive_root(
    rigs: list[Rig], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scenario: Path traversal refused: across the whole corpus and the requests served beside
    it, the cold tier reads only under its root, and the canary beside it is never touched."""
    rig = _built(rigs, tmp_path, HotTier(first=T0 - DAY))
    spy = FsSpy(monkeypatch)
    for symbol in SYMBOLS:
        assert rig.get({"symbol": symbol}).status_code == 422
    for start, end, status, _ in DATES:
        assert rig.get({"from": start, "to": end}).status_code == status
    for symbol in sorted(LISTED):  # served: each read lists the cold tier, under the root only
        assert rig.get({"symbol": symbol, "to": iso(T0)}).status_code == 200
    assert spy.touched, "the served reads listed the cold tier"
    assert spy.outside(rig.root, rig.canary) == []
    assert not any("secret.txt" in t for t in spy.touched)


def test_oversized_backfill_30_days_at_100ms_is_clamped_disclosed_and_counted(
    rigs: list[Rig], tmp_path: Path
) -> None:
    """Scenario: Oversized backfill: 30 days at 100 ms is served clamped, newest first, its
    effective resolution disclosed, the rest behind a cursor, and the clamp counted."""
    first = T0 - 30 * DAY
    cells = [_cell(T0 - k * 60 * S, 60_000.0 + k % 3) for k in range(1, 100)]
    rig = _built(rigs, tmp_path, HotTier(first=first, cells=cells))
    clamps = _sample("heatmap_backfill_clamped_total")
    r = rig.get({"from": iso(first), "to": iso(T0), "time_bucket_ms": 100})
    body = r.json()
    assert r.status_code == 200 and body["clamped"] is True
    assert body["effective_time_bucket_ms"] == 60_000 and len(body["times"]) == MAX_COLUMNS
    assert {s["effective_resolution_ms"] for s in body["segments"]} == {60_000}
    assert body["next_cursor"] is not None  # the older remainder, newest first
    assert _sample("heatmap_backfill_clamped_total") == clamps + 1


def test_a_span_past_400_days_is_refused_before_any_read(
    rigs: list[Rig], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """22 "Bounds" (BQ-7): `to - from` of exactly 400 days, 22's row, is served; a microsecond
    more is `400 invalid_time_range`, refused before either tier is read."""
    span = 400 * DAY  # the contract's number, never the code's constant
    assert MAX_WINDOW_DAYS == 400
    rig = _built(rigs, tmp_path, HotTier(first=T0 - DAY))
    spy = FsSpy(monkeypatch)
    r = rig.get({"from": iso(T0 - span - 1), "to": iso(T0)})
    assert (r.status_code, r.json()["code"]) == (400, "invalid_time_range")
    assert (rig.hot.calls, spy.touched) == ([], [])
    assert rig.get({"from": iso(T0 - span), "to": iso(T0)}).status_code == 200


def test_a_window_end_past_now_plus_one_bucket_is_refused_before_any_read(
    rigs: list[Rig], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """22 "Bounds" (BQ-7's rider): `to` at most one `time_bucket_ms` past the server's clock; a
    microsecond past it is `400 invalid_time_range` before any read, at every bucket."""
    rig = _built(rigs, tmp_path, HotTier(first=T0 - DAY))
    spy = FsSpy(monkeypatch)
    for bucket in (100, 1000, 60_000):
        past = rig.get({"to": iso(T0 + bucket * 1000 + 1), "time_bucket_ms": bucket})
        assert (past.status_code, past.json()["code"]) == (400, "invalid_time_range"), bucket
    assert (rig.hot.calls, spy.touched) == ([], [])
    for bucket in (100, 1000, 60_000):
        edge = rig.get({"to": iso(T0 + bucket * 1000), "time_bucket_ms": bucket})
        assert edge.status_code == 200, bucket


def test_no_minute_is_rebuilt_outside_the_recorded_range(rigs: list[Rig], tmp_path: Path) -> None:
    """22 "Bounds", 24 §6.3: a window with no stored cell is rebuilt only where a recorded
    snapshot can anchor it. One snapshot a minute into a day: the minutes past its reach are not
    looked up, and their buckets read `samples` 0; the ones it anchors are rebuilt."""
    snapshot = _snapshot(T0 + 60 * S)
    rig = _built(rigs, tmp_path, HotTier(first=T0, snapshots=[snapshot]), now=T0 + DAY)
    r = rig.get({"from": iso(T0), "to": iso(T0 + DAY), "time_bucket_ms": 60_000})
    body = r.json()
    assert r.status_code == 200 and [s["source"] for s in body["segments"]] == ["reconstructed"]
    reach = (snapshot.ts_us + ANCHOR_LOOKBACK_US - T0) // ANCHOR_STEP_US + 1  # minutes it anchors
    assert rig.hot.calls.count("snapshot_at") <= reach + 1  # and one read for the newest snapshot
    samples = body["samples"]
    assert len(samples) == 1440 and all(n == 0 for n in samples[reach:])
    assert all(n > 0 for n in samples[1:reach])  # the anchored minutes are rebuilt


async def test_ac_hm_14_a_third_concurrent_read_is_429_and_an_abort_releases_its_slot(
    rigs: list[Rig], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-HM-14: `MAX_PER_USER` reads at once; another is `429` with `Retry-After`, and a read
    whose client has gone (a symbol switch aborts it) stops at its next checkpoint and gives its
    slot back, so the next read is served."""
    hot = HotTier(first=T0 - DAY)
    hot.hold["ETHUSDT"] = asyncio.Event()
    rig = _built(rigs, tmp_path, hot)
    params = {"symbol": "ETHUSDT", "from": iso(T0 - DAY), "to": iso(T0)}
    transport = httpx.ASGITransport(app=rig.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        held = [asyncio.create_task(client.get("/market/heatmap", params=params))
                for _ in range(MAX_PER_USER)]  # fmt: skip
        await hot.all_in.wait()
        refused = await client.get("/market/heatmap", params=params)
        assert (refused.status_code, refused.json()["code"]) == (429, "rate_limited")
        assert refused.headers["Retry-After"] == "1"
        hot.hold["ETHUSDT"].set()
        assert [r.status_code for r in await asyncio.gather(*held)] == [200] * MAX_PER_USER

    async def gone(self: Request) -> bool:
        return True

    with monkeypatch.context() as patched:
        patched.setattr(Request, "is_disconnected", gone)
        for _ in range(MAX_PER_USER + 1):  # each abort gave its slot back, or the last is 429
            assert rig.get({"symbol": "BTCUSDT", "to": iso(T0)}).status_code == 499
    assert rig.get({"symbol": "BTCUSDT", "to": iso(T0)}).status_code == 200


def test_a_backfill_503_releases_its_slot(rigs: list[Rig], tmp_path: Path) -> None:
    """C-13.6 #10 (a datastore outage): a read the hot tier fails answers `503
    store_unavailable` and gives its slot back, read after read; once the store is back, the
    next read is served."""
    hot = HotTier(first=T0 - DAY, fail=StorageTierUnavailable("questdb down"))
    rig = _built(rigs, tmp_path, hot)
    for _ in range(MAX_PER_USER + 1):  # a 503 that kept its slot would make the last one 429
        r = rig.get({"to": iso(T0)})
        assert (r.status_code, r.json()["code"]) == (503, "store_unavailable")
    hot.fail = None
    assert rig.get({"to": iso(T0)}).status_code == 200


async def test_the_concurrency_limit_keys_by_the_acting_user(
    rigs: list[Rig], tmp_path: Path
) -> None:
    """BQ-3's rider (#3085): an Owner viewing as a Manager reads with the Owner's own slots. With
    the Owner's `MAX_PER_USER` reads of the view held, the Manager's own read is served, and
    the Owner's next read is `429`, whether through the view or as the Owner."""
    owner, manager = uuid.uuid4(), uuid.uuid4()
    hot = HotTier(first=T0 - DAY)
    hot.hold["ETHUSDT"] = asyncio.Event()
    rig = _built(rigs, tmp_path, hot)
    rig.principals |= {
        "view": _principal(manager, actor=owner),  # the Owner viewing as the Manager
        "manager": _principal(manager),
        "owner": _principal(owner),
    }
    held_params = {"symbol": "ETHUSDT", "from": iso(T0 - DAY), "to": iso(T0)}
    params = {"symbol": "BTCUSDT", "from": iso(T0 - DAY), "to": iso(T0)}
    transport = httpx.ASGITransport(app=rig.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:

        async def get(who: str, query: dict[str, str]) -> httpx.Response:
            return await client.get("/market/heatmap", params=query, headers={"x-principal": who})

        held = [asyncio.create_task(get("view", held_params)) for _ in range(MAX_PER_USER)]
        await hot.all_in.wait()
        assert (await get("manager", params)).status_code == 200  # the target's slots are free
        for who in ("view", "owner"):
            refused = await get(who, params)
            assert (refused.status_code, refused.json()["code"]) == (429, "rate_limited"), who
        hot.hold["ETHUSDT"].set()
        assert [r.status_code for r in await asyncio.gather(*held)] == [200] * MAX_PER_USER
