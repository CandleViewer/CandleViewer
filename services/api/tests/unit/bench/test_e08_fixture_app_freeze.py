"""#3641: the pack's REST backend freezes its heap as the app's lifespan does, so the cold-read
figures of the smoke pack and of the k6 run come from the heap shape the app serves from. The
scenario that built the app hands the process back unfrozen.

`build_app` builds a bare FastAPI with no lifespan, so without its own freeze neither driver would
see what `main._lifespan` does once startup completes. `runner all` runs the seven scenarios in one
process, and `rest_k6` is the fifth: `latency_internal` and `ratelimit_headroom` follow it. The
first-read leg's second app (#2523) is a second `build_app`, frozen in its turn."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from bench.ingestion import fixture_app, rest_load
from bench.ingestion.config import load
from bench.ingestion.fixture_app import requests_plan
from candleviewer.api.market_coverage import make_data_coverage_router
from candleviewer.observability import metrics_runtime
from candleviewer.storage.cold.kline_reader import ParquetKlineReader
from tests._gc_freeze import Marker, is_frozen


async def test_build_app_freezes_the_heap_as_its_last_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_freeze: None
) -> None:
    marker = Marker()
    frozen_while_building: list[bool] = []

    def last_router(*args: Any, **kwargs: Any) -> Any:
        frozen_while_building.append(is_frozen(marker))  # the last of the five routes
        return make_data_coverage_router(*args, **kwargs)

    monkeypatch.setattr(fixture_app, "make_data_coverage_router", last_router)

    await fixture_app.build_app(tmp_path)  # nothing reads the lake while it builds

    assert frozen_while_building == [False]
    assert is_frozen(marker)


async def test_the_first_read_app_is_a_second_build_frozen_as_the_app_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_freeze: None
) -> None:
    """#2523: the first-read leg's app is built as the app is, over a reader of its own, so the
    heap it serves from is frozen too; the one `unfreeze_startup_heap` that `run_rest` ends with
    undoes both freezes."""
    readers: list[ParquetKlineReader] = []

    def reader(*args: Any, **kwargs: Any) -> ParquetKlineReader:
        readers.append(made := ParquetKlineReader(*args, **kwargs))
        return made

    monkeypatch.setattr(fixture_app, "ParquetKlineReader", reader)
    app = await fixture_app.build_app(tmp_path)  # nothing reads the lake while they build
    first = await fixture_app.build_first_read_app(tmp_path)

    assert first is not app and len(readers) == 2 and readers[0] is not readers[1]
    assert is_frozen(app) and is_frozen(first)
    metrics_runtime.unfreeze_startup_heap()
    assert not is_frozen(app) and not is_frozen(first)


@pytest.mark.parametrize("fails", [False, True], ids=["after a run", "after a failed run"])
async def test_run_rest_hands_the_process_back_unfrozen(
    monkeypatch: pytest.MonkeyPatch, clean_freeze: None, fails: bool
) -> None:
    marker = Marker()

    async def drive(*_: int) -> dict[str, list[float]]:
        metrics_runtime.freeze_startup_heap()  # what `build_app` ends with, for real
        assert is_frozen(marker)
        if fails:
            raise RuntimeError("the driver failed")
        return {route: [1.0] for route in requests_plan()}

    monkeypatch.setattr(rest_load, "drive_inprocess", drive)

    if fails:
        with pytest.raises(RuntimeError, match="the driver failed"):
            await rest_load.run_rest(load("rest_k6", "smoke"))
    else:
        await rest_load.run_rest(load("rest_k6", "smoke"))

    assert not is_frozen(marker)
