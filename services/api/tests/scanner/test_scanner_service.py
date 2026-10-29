"""`ScannerService` (E08-T09 PR 2b, #4708; 22 `runScanner`): the 5 s cache and its key, single
flight (Gherkin 5: one evaluation per window), the bound on cache-cold evaluations (429, never
queued), the inputs (one `refresh()` per cold scan, `latest()` within its bound, the recorded set
by view, paged) and their failures (503), `aclose()` and the metrics."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from _scan_env import TS_US, Clock, Counter, FakeRecording, FakeUniverse, entry, service, ticker
from _scan_env import universe as tickers_of

from candleviewer.api import scanner_eval, scanner_service
from candleviewer.api.scanner_criteria import CRITERIA_BY_ID
from candleviewer.api.scanner_eval import ScanQuery, scan_query
from candleviewer.api.scanner_service import (
    ScannerBusyError,
    ScannerMetrics,
    ScannerService,
    ScannerUnavailableError,
)
from candleviewer.observability import context
from candleviewer.storage.errors import StorageTierUnavailable


def q(flt: dict[str, Any] | None = None, sort: str = "volume_24h", limit: int = 100) -> ScanQuery:
    return scan_query(flt or {}, sort, limit, CRITERIA_BY_ID)


def _src(*symbols: str) -> FakeUniverse:
    return FakeUniverse(tickers_of(ticker(s) for s in symbols or ("AAAUSDT", "BBBUSDT")))


@pytest.fixture
def evaluations(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Counts the calls of `evaluate` the service makes."""
    calls: list[int] = []
    real = scanner_eval.evaluate

    def counted(*args: Any, **kw: Any) -> Any:
        calls.append(1)
        return real(*args, **kw)

    monkeypatch.setattr(scanner_service, "evaluate", counted)
    return calls


def _symbols(body: bytes) -> list[str]:
    return [r["symbol"] for r in json.loads(body)["items"]]


async def test_a_scan_answers_the_ranked_body() -> None:
    svc = service(_src(), FakeRecording([entry("BBBUSDT")]))
    body = json.loads(await svc.scan(q(), restricted=False))
    assert [(r["symbol"], r["coverage"]) for r in body["items"]] == [
        ("AAAUSDT", "live_only"),
        ("BBBUSDT", "recorded"),
    ]
    assert body["meta"]["inputs"][0]["stale"] is False


async def test_a_repeat_inside_5s_is_a_cache_hit_and_after_5s_a_new_evaluation(
    evaluations: list[int],
) -> None:
    clock, src = Clock(), _src()
    svc = service(src, FakeRecording([]), clock=clock)
    first = await svc.scan(q(), restricted=False)
    clock.mono += 4.999
    assert await svc.scan(q(), restricted=False) is first
    assert (len(evaluations), src.refreshes) == (1, 1)
    clock.mono += 0.001
    await svc.scan(q(), restricted=False)
    assert (len(evaluations), src.refreshes) == (2, 2)


async def test_the_key_normalises_bounds_and_separates_the_views(evaluations: list[int]) -> None:
    svc = service(_src(), FakeRecording([]))
    await svc.scan(q({"funding_rate": {"min": "0.10"}}), restricted=False)
    await svc.scan(q({"funding_rate": {"min": "0.1"}}), restricted=False)
    assert len(evaluations) == 1
    await svc.scan(q({"funding_rate": {"min": "0.1"}}), restricted=True)
    assert len(evaluations) == 2
    await svc.scan(q({"funding_rate": {"min": "0.1"}}, limit=5), restricted=True)
    assert len(evaluations) == 3


async def test_gherkin_5_concurrent_and_sequential_identical_scans_share_one_evaluation(
    evaluations: list[int],
) -> None:
    src = _src()
    src.gate = asyncio.Event()
    svc = service(src, FakeRecording([]))
    running = [asyncio.create_task(svc.scan(q(), restricted=False)) for _ in range(3)]
    await asyncio.sleep(0)
    src.gate.set()
    bodies = await asyncio.gather(*running)
    bodies += [await svc.scan(q(), restricted=False) for _ in range(3)]
    assert len(set(bodies)) == 1 and len(evaluations) == 1 and src.refreshes == 1


async def test_past_the_cold_bound_the_next_distinct_scan_is_refused_at_once() -> None:
    src = _src()
    src.gate = asyncio.Event()
    outcomes = Counter()
    metrics = ScannerMetrics(outcomes, Counter(), Counter(), Counter())
    svc = service(src, FakeRecording([]), max_cold=2, metrics=metrics)
    running = [asyncio.create_task(svc.scan(q(limit=n), restricted=False)) for n in (1, 2)]
    await asyncio.sleep(0)
    assert svc.cold_running == 2
    with pytest.raises(ScannerBusyError):
        await svc.scan(q(limit=3), restricted=False)
    joiner = asyncio.create_task(svc.scan(q(limit=1), restricted=False))  # joins: not counted
    await asyncio.sleep(0)
    assert svc.cold_running == 2 and src.refreshes == 2
    src.gate.set()
    await asyncio.gather(*running, joiner)
    assert svc.cold_running == 0
    assert (outcomes.total("rate_limited"), outcomes.total("ok")) == (1, 2)
    await svc.scan(q(limit=3), restricted=False)  # the bound frees once they end


async def test_an_ended_evaluation_frees_the_bound_before_its_callbacks_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S-2: the bound counts running evaluations, so the loop turn between an evaluation's end
    and its done-callbacks never refuses a scan."""
    seen: list[int] = []
    real = context.spawn

    def spawned(coro: Any, **kw: Any) -> Any:
        task = real(coro, **kw)
        task.add_done_callback(lambda _t: seen.append(svc.cold_running))  # runs first
        return task

    monkeypatch.setattr(scanner_service, "spawn", spawned)
    svc = service(_src(), FakeRecording([]), max_cold=1)
    await svc.scan(q(limit=1), restricted=False)
    assert seen == [0]


async def test_the_recorded_set_is_read_once_per_view_per_window_whatever_the_filter() -> None:
    """S-1: a caller varying a bound costs an evaluation, not a store read."""
    clock, reads = Clock(), FakeRecording([entry("AAAUSDT")])
    svc = service(_src(), reads, clock=clock)
    for n in range(1, 6):
        await svc.scan(q({"funding_rate": {"min": f"0.00000{n}"}}), restricted=True)
    assert reads.calls == 1
    await svc.scan(q(), restricted=False)  # the other view reads its own
    assert reads.calls == 2
    clock.mono += 5.0
    await svc.scan(q(limit=7), restricted=True)
    assert reads.calls == 3


async def test_a_body_never_outlives_the_recorded_set_it_was_built_on(
    evaluations: list[int],
) -> None:
    """The memoised recorded set does not stretch a cached body past 5 s from its read."""
    clock, reads = Clock(), FakeRecording([])
    svc = service(_src(), reads, clock=clock)
    await svc.scan(q(limit=1), restricted=False)
    clock.mono += 4.0
    await svc.scan(q(limit=2), restricted=False)  # built on the set read 4 s ago
    clock.mono += 1.0
    await svc.scan(q(limit=2), restricted=False)
    assert (len(evaluations), reads.calls) == (3, 2)


async def test_an_outage_is_not_remembered_as_a_recorded_set() -> None:
    reads = FakeRecording([entry("AAAUSDT")], fail=StorageTierUnavailable("postgres down"))
    svc = service(_src(), reads)
    with pytest.raises(ScannerUnavailableError):
        await svc.scan(q(), restricted=False)
    reads.fail = None
    body = json.loads(await svc.scan(q(), restricted=False))
    assert body["items"][0]["coverage"] == "recorded" and reads.calls == 2


async def test_invalidate_drops_the_cached_bodies_and_the_recorded_set(
    evaluations: list[int],
) -> None:
    reads = FakeRecording([])
    svc = service(_src(), reads)
    await svc.scan(q(), restricted=False)
    svc.invalidate()
    await svc.scan(q(), restricted=False)
    assert (len(evaluations), reads.calls) == (2, 2)


async def test_no_snapshot_within_its_bound_is_unavailable() -> None:
    src = FakeUniverse(None)
    svc = service(src, FakeRecording([]))
    with pytest.raises(ScannerUnavailableError):
        await svc.scan(q(), restricted=False)
    assert src.refreshes == 1
    with pytest.raises(ScannerUnavailableError):
        await service(None, FakeRecording([])).scan(q(), restricted=False)


async def test_a_failed_refresh_still_answers_from_the_snapshot_and_marks_it_stale() -> None:
    src = FakeUniverse(tickers_of([ticker("AAAUSDT")]), received_at_us=TS_US)
    src.fail = RuntimeError("venue down")
    clock = Clock(wall_us=TS_US + 6_000_000)
    body = json.loads(
        await service(src, FakeRecording([]), clock=clock).scan(q(), restricted=False)
    )
    assert [r["symbol"] for r in body["items"]] == ["AAAUSDT"]
    assert body["meta"]["inputs"] == [
        {"input": "tickers", "as_of": "2026-10-26T07:33:20.000000Z", "stale": True}
    ]
    assert src.refreshes == 1


async def test_a_refresh_past_its_bound_is_abandoned_for_the_snapshot_in_hand() -> None:
    src = _src()
    src.gate = asyncio.Event()  # never set
    svc = service(src, FakeRecording([]), refresh_timeout_s=0.01)
    assert _symbols(await svc.scan(q(), restricted=False)) == ["AAAUSDT", "BBBUSDT"]


async def test_a_recording_store_outage_or_no_store_is_unavailable_never_live_only() -> None:
    down = FakeRecording([entry("AAAUSDT")], fail=StorageTierUnavailable("postgres down"))
    with pytest.raises(ScannerUnavailableError):
        await service(_src(), down).scan(q(), restricted=False)
    with pytest.raises(ScannerUnavailableError):
        await service(_src(), None).scan(q(), restricted=False)


async def test_an_outage_of_another_input_is_unavailable_and_counted_so() -> None:
    def listed() -> frozenset[str]:
        raise StorageTierUnavailable("catalogue down")

    counts = Counter()
    metrics = ScannerMetrics(counts, Counter(), Counter(), Counter())
    svc = service(_src(), FakeRecording([]), listed=listed, metrics=metrics)
    with pytest.raises(ScannerUnavailableError):
        await svc.scan(q(), restricted=False)
    assert (counts.total("unavailable"), counts.total("error")) == (1, 0)


async def test_a_store_bug_is_not_an_outage() -> None:
    broken = FakeRecording([], fail=KeyError("bug"))
    errors = Counter()
    svc = service(_src(), broken, metrics=ScannerMetrics(errors, Counter(), Counter(), Counter()))
    with pytest.raises(KeyError):
        await svc.scan(q(), restricted=False)
    assert errors.total("error") == 1


async def test_a_restricted_view_does_not_count_a_hidden_cause_as_recorded() -> None:
    held = [
        entry("AAAUSDT", reasons=("position_open",)),
        entry("BBBUSDT", state="stopped"),
        entry("CCCUSDT", state="degraded", reasons=("chart_open", "position_open")),
    ]
    src = _src("AAAUSDT", "BBBUSDT", "CCCUSDT")
    owner = json.loads(await service(src, FakeRecording(held)).scan(q(), restricted=False))
    viewer = json.loads(await service(src, FakeRecording(held)).scan(q(), restricted=True))
    assert [r["coverage"] for r in owner["items"]] == ["recorded", "live_only", "recorded"]
    assert [r["coverage"] for r in viewer["items"]] == ["live_only", "live_only", "recorded"]


async def test_the_recorded_set_is_read_page_by_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scanner_service, "COVERAGE_PAGE", 2)
    symbols = [f"S{i}USDT" for i in range(5)]
    reads = FakeRecording([entry(s) for s in symbols])
    body = json.loads(await service(_src(*symbols), reads).scan(q(), restricted=False))
    assert [r["coverage"] for r in body["items"]] == ["recorded"] * 5 and reads.calls == 3


async def test_the_catalogue_snapshot_narrows_the_scan() -> None:
    src = _src("AAAUSDT", "BBBUSDT")
    svc = service(src, FakeRecording([]), listed=lambda: frozenset({"BBBUSDT"}))
    assert _symbols(await svc.scan(q(), restricted=False)) == ["BBBUSDT"]


async def test_aclose_cancels_a_running_scan() -> None:
    src = _src()
    src.gate = asyncio.Event()
    svc = service(src, FakeRecording([]))
    running = asyncio.create_task(svc.scan(q(), restricted=False))
    await asyncio.sleep(0)
    await svc.aclose()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert svc.cold_running == 0


async def test_a_cancelled_request_leaves_the_evaluation_to_the_others() -> None:
    src = _src()
    src.gate = asyncio.Event()
    svc = service(src, FakeRecording([]))
    leader = asyncio.create_task(svc.scan(q(), restricted=False))
    await asyncio.sleep(0)
    joiner = asyncio.create_task(svc.scan(q(), restricted=False))
    await asyncio.sleep(0)
    leader.cancel()
    await asyncio.sleep(0)
    src.gate.set()
    assert _symbols(await joiner) == ["AAAUSDT", "BBBUSDT"]


async def test_an_evaluation_past_its_bound_is_a_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Slow(FakeRecording):
        async def list(self, query: Any) -> Any:
            await asyncio.Event().wait()

    counts = Counter()
    svc = service(
        _src(),
        _Slow([]),
        timeout_s=0.01,
        metrics=ScannerMetrics(counts, Counter(), Counter(), Counter()),
    )
    with pytest.raises(ScannerUnavailableError):
        await svc.scan(q(), restricted=False)
    assert counts.total("timeout") == 1


async def test_each_metric_moves() -> None:
    outcomes, seconds, hits, capped = Counter(), Counter(), Counter(), Counter()
    svc = service(
        _src(), FakeRecording([]), metrics=ScannerMetrics(outcomes, seconds, hits, capped)
    )
    await svc.scan(q(limit=1), restricted=False)
    await svc.scan(q(limit=1), restricted=False)
    assert (outcomes.total("ok"), hits.total(), capped.total()) == (1, 1, 1)
    assert len(seconds.observed) == 1 and seconds.observed[0] >= 0
    with pytest.raises(ScannerUnavailableError):
        await service(None, None, metrics=ScannerMetrics(outcomes, seconds, hits, capped)).scan(
            q(), restricted=False
        )
    assert outcomes.total("unavailable") == 1


async def test_the_cache_keeps_at_most_max_entries_dropping_the_oldest(
    evaluations: list[int],
) -> None:
    svc = service(_src(), FakeRecording([]), max_entries=2)
    for limit in (1, 2, 3):
        await svc.scan(q(limit=limit), restricted=False)
    await svc.scan(q(limit=3), restricted=False)
    await svc.scan(q(limit=2), restricted=False)
    assert len(evaluations) == 3
    await svc.scan(q(limit=1), restricted=False)
    assert len(evaluations) == 4


async def test_start_and_stop_are_the_lifespan_pair() -> None:
    svc: ScannerService = service(_src(), FakeRecording([]))
    svc.start()
    await svc.scan(q(), restricted=False)
    await svc.stop()
