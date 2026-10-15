"""Unit (E16-T06 review H1/H3/M3): `retention_wiring` composition.

- H3: a build failure (any exception, e.g. a missing seed file in the image) or a non-real
  backend returns `None` — the purge answers 503 — and never raises into `create_app()`.
- M3: `1 <= CV_RECORDER_HOT_DAYS <= CV_RECORDER_RETENTION_DAYS <= 3650` else `None`.
- H1: `PgRetentionFacts.policies()` maps every DB `stream_kind` value (incl. `funding` ->
  `funding_rates`) to its §7 total horizon, and unknown DB streams are dropped (keep forever).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

import candleviewer.retention_wiring as rw
from candleviewer.recorder.retention import resolve_policy
from candleviewer.recorder.retention_defaults import STREAM_DEFAULTS


class _Settings:
    def __init__(self, hot: int = 7, total: int = 30, backend: str = "real") -> None:
        self.storage_backend = backend
        self.recorder_hot_days = hot
        self.recorder_retention_days = total


class _Audit:
    async def emit(self, action: str, **kwargs: object) -> None:
        return None


@pytest.mark.parametrize(("hot", "total"), [(0, 30), (31, 30), (7, 3651), (-1, 5)])
def test_invalid_recorder_days_refuse_to_build(hot: int, total: int) -> None:
    built = rw.build_retention_manager(_Settings(hot, total), _Audit(), object())  # type: ignore[arg-type]  # settings/relational stubs: refused before use
    assert built is None


def test_non_real_backend_or_no_db_returns_none() -> None:
    assert rw.build_retention_manager(_Settings(backend="fake"), _Audit(), object()) is None  # type: ignore[arg-type]  # stub
    assert rw.build_retention_manager(_Settings(), _Audit(), None) is None  # type: ignore[arg-type]  # stub


def test_build_failure_never_raises_into_create_app(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object) -> None:
        raise IndexError("seed path parents[5] outside the image")

    monkeypatch.setattr(rw, "_build", boom)
    assert rw.build_retention_manager(_Settings(), _Audit(), object()) is None  # type: ignore[arg-type]  # stub


class _Uow:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.session = self
        self._rows = rows

    async def execute(self, _stmt: object) -> _Uow:
        return self

    def mappings(self) -> _Uow:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows

    async def commit(self) -> None:
        return None


class _Rel:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[_Uow]:
        yield _Uow(self.rows)


#: The DB `stream_kind` enum (21 §2) plus the derived streams it lacks; `funding` is the DB name.
DB_STREAMS = [
    "trades", "orderbook_delta", "orderbook_snapshot", "tickers", "klines", "liquidations",
    "open_interest", "funding", "bars", "footprint_cells", "profiles", "orderflow_metrics",
    "heatmap_cells",
]  # fmt: skip


@pytest.mark.parametrize("db_stream", DB_STREAMS)
async def test_pg_facts_map_every_db_stream_to_its_section7_horizon(db_stream: str) -> None:
    rows = [{"scope": "default", "symbol": None, "stream": db_stream, "retain_days": 3}]
    pol = await rw.PgRetentionFacts(_Rel(rows)).policies()  # type: ignore[arg-type]  # fake rel
    stream = "funding_rates" if db_stream == "funding" else db_stream
    ((key, row),) = pol.items()
    assert key == (None, stream) and row.hot_days == 3
    assert row.total_days == STREAM_DEFAULTS[stream][1]
    eff = resolve_policy("BTCUSDT", stream, pinned=False, policies=pol, elevated=False)
    assert eff.total_days == STREAM_DEFAULTS[stream][1]  # never the 30-day hard default


async def test_pg_facts_drop_unknown_stream_and_never_shorten_below_hot() -> None:
    rows = [
        {"scope": "default", "symbol": None, "stream": "engine_metrics", "retain_days": 3},
        {"scope": "symbol", "symbol": "BTCUSDT", "stream": "heatmap_cells", "retain_days": 120},
    ]
    pol = await rw.PgRetentionFacts(_Rel(rows)).policies()  # type: ignore[arg-type]  # fake rel
    assert list(pol) == [("BTCUSDT", "heatmap_cells")]
    assert pol[("BTCUSDT", "heatmap_cells")].total_days == 120  # >= hot window, not 90
