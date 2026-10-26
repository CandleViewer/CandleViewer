"""E16-T10 composition: `build_import_runner` fails closed without coverage or the recorder's disk
budget and, when composed, imports end to end into an existing cold root (fake archive, no network)
within that budget: its ladder and its headroom `min(cap - used, free)` (fake meter, fake clock)."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from prometheus_client import REGISTRY

from candleviewer.api.recorder_admin import ImportRunner
from candleviewer.domain.archive import ArchiveFile
from candleviewer.import_wiring import build_import_runner
from candleviewer.recorder.budget import BudgetConfig, DiskBudget
from candleviewer.recorder.coverage import CoverageService
from candleviewer.recorder.importer import (
    DiskUsage,
    ImportDiskBudgetExceeded,
    ImportDiskPressure,
    ImportRootMissing,
)
from candleviewer.recorder.models import DiskPressureLevel
from tests.unit.recorder._budget_fakes import FakeMeter, make_budget
from tests.unit.recorder._session_fakes import MemRecorderStore
from tests.unit.recorder.test_importer import FakeArchive

D1, D2 = date(2026, 6, 1), date(2026, 6, 2)


def _ROOMY() -> tuple[int, int]:
    return 1_000_000, 0


@dataclass
class _SmallVolume(FakeMeter):
    """The budget's meter on a 10 kB volume: one fake archive day (10 B, 20 B projected) can
    outgrow the headroom while the ladder stays below AUTOSTOP."""

    free: int = 9_000
    total: int = 10_000

    async def volume(self) -> tuple[int, int]:
        return self.total, self.free


def _unsampled(meter: FakeMeter | None = None, cap: int = 1_000) -> DiskBudget:
    return make_budget(meter or _SmallVolume(), config=BudgetConfig(cap_bytes=cap))[0]


async def _budget(
    *, cap: int = 1_000, used: int = 0, total: int = 10_000, free: int = 9_000
) -> DiskBudget:
    """A budget sampled once from a fake meter: `used` recorded bytes against `cap`."""
    budget = _unsampled(_SmallVolume(used=used, free=free, total=total), cap)
    await budget.sample_once()
    return budget


def _compose(
    root: Path, budget: DiskBudget, src: FakeArchive | None = None, meter: DiskUsage | None = _ROOMY
) -> ImportRunner:
    svc, archive = CoverageService(MemRecorderStore(), now_us=lambda: 0), src or FakeArchive()
    run = build_import_runner(
        archive, str(root), svc, backlog_rows=lambda: 0, disk_usage=meter, budget=budget
    )
    assert run is not None
    return run


def _refusals(reason: str) -> float:
    return REGISTRY.get_sample_value("import_refused_total", {"reason": reason}) or 0.0


def _untouched(root: Path) -> bool:
    return not any(root.iterdir())


def test_build_import_runner_none_without_coverage(tmp_path: Path) -> None:
    run = build_import_runner(FakeArchive(), str(tmp_path), None, lambda: 0, budget=_unsampled())
    assert run is None


async def test_build_import_runner_imports_into_cold_root(tmp_path: Path) -> None:
    svc, budget = CoverageService(MemRecorderStore(), now_us=lambda: 0), await _budget()
    run = build_import_runner(
        FakeArchive(), str(tmp_path), svc, backlog_rows=lambda: 0, disk_usage=_ROOMY, budget=budget
    )
    assert run is not None
    seen: list[float] = []
    result = await run("BTCUSDT", date(2026, 6, 1), date(2026, 6, 2), seen.append)
    assert result["rows_written"] == 48 and result["source"] == "archive"
    assert seen[-1] == 100.0
    assert _dirs(tmp_path) == [
        "dt=2026-06-01", "dt=2026-06-02"
    ]  # fmt: skip


def _dirs(root: Path) -> list[str]:
    return sorted(p.parent.name for p in (root / "trades").rglob("*.parquet"))


def test_build_import_runner_requires_backlog_provider() -> None:
    param = inspect.signature(build_import_runner).parameters["backlog_rows"]
    assert param.default is inspect.Parameter.empty


def test_build_import_runner_requires_the_running_disk_budget(tmp_path: Path) -> None:
    """A required keyword, and `None` composes no runner (the route answers 503): no budget is
    never an import without the budget's checks."""
    param = inspect.signature(build_import_runner).parameters["budget"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert param.default is inspect.Parameter.empty
    svc = CoverageService(MemRecorderStore(), now_us=lambda: 0)
    run = build_import_runner(FakeArchive(), str(tmp_path), svc, lambda: 0, budget=None)
    assert run is None


def test_app_wires_recorder_backlog_gauge_into_import_runner() -> None:
    """Production composition passes the live backlog source and the running disk budget, never
    None (review #1)."""
    import ast
    from pathlib import Path as _P

    import candleviewer.app as app_mod

    tree = ast.parse(_P(app_mod.__file__).read_text(encoding="utf-8"))
    calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "build_import_runner"
    ]  # fmt: skip
    assert len(calls) == 1
    kw = {k.arg: k.value for k in calls[0].keywords}
    assert isinstance(kw["backlog_rows"], ast.Name)
    assert kw["backlog_rows"].id == "current_write_backlog_rows"
    assert ast.unparse(kw["budget"]) == "app.state.disk_budget"


async def test_composed_runner_pauses_while_recorder_backlog_nonzero(tmp_path: Path) -> None:
    """The composed runner polls the recorder's published backlog and waits until it drains
    before fetching (one 0.25 s poll here; the live writer drains on the second read)."""
    from candleviewer.recorder.metrics import (
        current_write_backlog_rows,
        recorder_write_backlog_rows,
    )

    polls: list[int] = []
    src = FakeArchive()

    def backlog() -> int:
        value = current_write_backlog_rows()
        polls.append(value)
        if value:
            assert src.fetches == [], "fetched while the live backlog was non-zero"
            recorder_write_backlog_rows.set(0)  # live writer drains during the pause
        return value

    recorder_write_backlog_rows.set(500)
    try:
        svc = CoverageService(MemRecorderStore(), now_us=lambda: 0)
        run = build_import_runner(src, str(tmp_path), svc, backlog, _ROOMY, budget=await _budget())
        assert run is not None
        await run("BTCUSDT", date(2026, 6, 1), date(2026, 6, 1), lambda _p: None)
    finally:
        recorder_write_backlog_rows.set(0)
    assert polls[:2] == [500, 0] and src.fetches == [date(2026, 6, 1)]


async def test_composed_runner_disk_guard_defaults_on_and_refuses(tmp_path: Path) -> None:
    """The cold volume's own 80 % guard still refuses under a roomy budget."""
    full = _compose(tmp_path, await _budget(), meter=lambda: (100, 95))
    with pytest.raises(ImportDiskBudgetExceeded):
        await full("BTCUSDT", date(2026, 6, 1), date(2026, 6, 1), lambda _p: None)
    assert not _dirs(tmp_path)


async def test_composed_runner_refuses_a_missing_cold_root_and_never_creates_it(
    tmp_path: Path,
) -> None:
    """With the production volume meter (no `disk_usage` given): refused before any fetch, and
    nothing is created, the root included."""
    root, src, before = tmp_path / "cold", FakeArchive(), _refusals("root_missing")
    run = _compose(root, await _budget(), src, meter=None)
    with pytest.raises(ImportRootMissing) as refused:
        await run("BTCUSDT", D1, D2, lambda _p: None)
    assert refused.value.code == "import_root_missing"
    assert _refusals("root_missing") == before + 1
    assert not root.exists() and _untouched(tmp_path) and src.fetches == []


async def test_composed_runner_measures_an_existing_cold_root_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The production volume meter reads the existing root (a fake statvfs): 790 of 1 000 B used
    plus a 20 B day passes 80 %, so the day is refused before it is written."""
    seen: list[Path] = []

    def statvfs(path: Path) -> SimpleNamespace:
        seen.append(path)
        return SimpleNamespace(total=1_000, used=790, free=210)

    monkeypatch.setattr("candleviewer.import_wiring.shutil.disk_usage", statvfs)
    with pytest.raises(ImportDiskBudgetExceeded):
        await _compose(tmp_path, await _budget(), meter=None)("BTCUSDT", D1, D1, lambda _p: None)
    assert seen == [tmp_path] * 2 and _untouched(tmp_path)  # pytest's tmp_path is resolved


@pytest.mark.parametrize(
    ("used", "refused", "level"),
    [
        (900, False, DiskPressureLevel.AUTOSTOP),
        (950, False, DiskPressureLevel.HALT),
        (0, True, DiskPressureLevel.NORMAL),
    ],
    ids=["autostop", "halt", "refused-volume"],
)
async def test_composed_runner_refuses_at_autostop_or_on_a_refused_volume_before_any_write(
    tmp_path: Path, used: int, refused: bool, level: DiskPressureLevel
) -> None:
    budget, src = await _budget(used=used), FakeArchive()
    budget.recording_refused = refused  # as composed at boot for a refused recording volume
    assert budget.level is level
    before = _refusals("disk_pressure")
    with pytest.raises(ImportDiskPressure) as caught:
        await _compose(tmp_path, budget, src)("BTCUSDT", D1, D2, lambda _p: None)
    assert caught.value.code == "import_disk_pressure"
    assert _refusals("disk_pressure") == before + 1
    assert src.fetches == [] and _untouched(tmp_path)


@pytest.mark.parametrize(
    ("used", "level"),
    [(0, DiskPressureLevel.NORMAL), (800, DiskPressureLevel.WARN)],
    ids=["normal", "warn"],
)
async def test_composed_runner_imports_at_normal_and_warn(
    tmp_path: Path, used: int, level: DiskPressureLevel
) -> None:
    budget = await _budget(used=used)
    assert budget.level is level
    result = await _compose(tmp_path, budget)("BTCUSDT", D1, D2, lambda _p: None)
    assert result["rows_written"] == 48
    assert _dirs(tmp_path) == ["dt=2026-06-01", "dt=2026-06-02"]


class _AutostopAfterOneDay(FakeArchive):
    """One day at a time; before the second day is fetched, the recorder reaches 90 % of its cap
    and the budget takes a sample (AUTOSTOP)."""

    def __init__(self, meter: _SmallVolume, budget: DiskBudget) -> None:
        super().__init__()
        self.meter, self.budget = meter, budget

    @property
    def max_concurrency(self) -> int:
        return 1

    async def fetch(self, file: ArchiveFile) -> bytes:
        if self.fetches:
            self.meter.used = 900
            await self.budget.sample_once()
        return await super().fetch(file)


async def test_composed_runner_stops_the_next_day_once_the_budget_reaches_autostop(
    tmp_path: Path,
) -> None:
    meter = _SmallVolume()
    budget = _unsampled(meter)
    await budget.sample_once()
    run = _compose(tmp_path, budget, _AutostopAfterOneDay(meter, budget))
    with pytest.raises(ImportDiskPressure):
        await run("BTCUSDT", D1, D2, lambda _p: None)
    assert budget.level is DiskPressureLevel.AUTOSTOP
    assert _dirs(tmp_path) == ["dt=2026-06-01"]


@pytest.mark.parametrize(
    ("cap", "used", "total", "free"),
    [(100, 85, 10_000, 9_000), (1_000, 0, 100, 19)],
    ids=["cap-minus-used-short", "free-space-short"],
)
async def test_composed_runner_refuses_a_day_beyond_the_budget_headroom(
    tmp_path: Path, cap: int, used: int, total: int, free: int
) -> None:
    """A day projected at 20 B against 15 B or 19 B of `min(cap - used, free)`, the other term
    ample and the ladder below AUTOSTOP: refused once downloaded, before it is written."""
    budget, src = await _budget(cap=cap, used=used, total=total, free=free), FakeArchive()
    assert budget.level < DiskPressureLevel.AUTOSTOP
    with pytest.raises(ImportDiskBudgetExceeded):
        await _compose(tmp_path, budget, src)("BTCUSDT", D1, D1, lambda _p: None)
    assert src.fetches == [D1] and _untouched(tmp_path)


async def test_composed_runner_imports_a_day_that_fits_the_headroom_exactly(
    tmp_path: Path,
) -> None:
    budget = await _budget(cap=100, used=80, total=100, free=20)  # min(100 - 80, 20) = 20 B
    assert budget.level is DiskPressureLevel.WARN
    result = await _compose(tmp_path, budget)("BTCUSDT", D1, D1, lambda _p: None)
    assert result["rows_written"] == 24


@pytest.mark.parametrize("breakdown_fails", [False, True], ids=["no-sample", "no-breakdown"])
async def test_composed_runner_refuses_until_the_budget_has_measured_the_recorder(
    tmp_path: Path, breakdown_fails: bool
) -> None:
    """Fails closed with no sample yet, or with a sample whose recorded tiers were never measured
    (an unmeasured use is never 0 B of the cap)."""
    budget, src = _unsampled(_SmallVolume(breakdown_fail=breakdown_fails)), FakeArchive()
    if breakdown_fails:
        await budget.sample_once()
        assert budget.report() is not None
    with pytest.raises(ImportDiskBudgetExceeded):
        await _compose(tmp_path, budget, src)("BTCUSDT", D1, D1, lambda _p: None)
    assert src.fetches == [] and _untouched(tmp_path)
