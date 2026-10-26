"""#3641: the pack's REST backend freezes its heap as the app's lifespan does, so the cold-read
figures of the smoke pack and of the k6 run come from the heap shape the app serves from.

`build_app` builds a bare FastAPI with no lifespan, so without its own freeze neither driver would
see what `main._lifespan` does once startup completes."""

from __future__ import annotations

import gc
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from bench.ingestion import fixture_app
from candleviewer.api.market_coverage import make_data_coverage_router
from tests._gc_freeze import Marker, is_frozen


@pytest.fixture
def clean_freeze() -> Iterator[None]:
    """The freeze is the test's own: a clean slate whatever ran before, nothing left after
    (`build_app` freezes the whole process and never undoes it)."""
    gc.unfreeze()
    yield
    gc.unfreeze()


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
