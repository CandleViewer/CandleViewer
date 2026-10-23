"""#492 S5: `RecordingStatusCache`, one recording status a second (injected clock and sleep, no
wall clock, no real sleep). One computation a second whatever the readers; the age gauge;
`not_deployed` until a runtime is bound; the policy integers and their bounds (hand-off item 3);
`storage.level` is `DiskBudget.effective_level` (item 5); the R-I2 view for all but the Owner."""

from __future__ import annotations

import asyncio
import json
import math
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.recorder import control as rc
from candleviewer.recorder.budget import BudgetConfig, DiskBudget
from candleviewer.recorder.metrics import recorder_status_cache_age_seconds
from candleviewer.recorder.policy import PolicyConfig
from candleviewer.recorder.status import RecordingStatusCache, policy_settings
from tests.unit.recorder._budget_fakes import CAP, GB, FakeMeter, make_budget
from tests.unit.recorder._control_fakes import FakeRecorder

_STATUS: Any = load_openapi_spec()["paths"]["/recording/status"]["get"]["responses"]["200"]
HEALTHY: dict[str, Any] = _STATUS["content"]["application/json"]["examples"]["healthy"]["value"]
WALL = datetime(2026, 9, 14, 10, 31, 2, 900_000, tzinfo=UTC)


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text)


class _Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


class _Counting(FakeRecorder):
    def __init__(self) -> None:
        super().__init__()
        self.calls, self.fail = 0, False

    async def status(self) -> rc.ControlStatus:
        self.calls += 1
        if self.fail:
            raise RuntimeError("runtime down")
        return await super().status()


def _budget(**kw: Any) -> DiskBudget:
    return make_budget(FakeMeter(used=200 * GB), **kw)[0]


def _cache(
    source: FakeRecorder | None, budget: DiskBudget | None = None, **kw: Any
) -> RecordingStatusCache:
    return RecordingStatusCache(lambda: source, budget, wall=lambda: WALL, **kw)


def _healthy() -> FakeRecorder:
    """A runtime whose status is 22's `healthy` example."""
    fake = FakeRecorder(max_symbols=2)
    row = {"lag_ms": 42, "rows_last_hour": 41_220_118, "dropped_messages": 0}
    fake.put("BTCUSDT", lingering=None, resyncs_last_hour=1, **row,
             last_event_at=_at("2026-09-14T10:31:02.104Z"))  # fmt: skip
    fake.put("ETHUSDT", "chart_open", lingering=True, linger_until=_at("2026-09-14T11:00:30Z"),
             **row | {"lag_ms": 31, "rows_last_hour": 8_122_004}, resyncs_last_hour=0,
             last_event_at=_at("2026-09-14T10:31:02.098Z"))  # fmt: skip
    fake.put("SOLUSDT", "chart_open", state="idle", lingering=None, refusals=("symbol_cap",))
    link = rc.Connection("wss://stream.bybit.com/v5/public/linear", "connected", 14,
                         _at("2026-09-14T06:00:02Z"), 0, 18)  # fmt: skip
    fake.status_fields = {"connections": (link,), "ingest_rate_msgs_per_sec": 18_422,
                          "policy": PolicyConfig(max_symbols=2)}  # fmt: skip
    return fake


async def test_the_owner_body_is_the_contracts_healthy_example() -> None:
    cache = _cache(_healthy(), _budget())
    await cache.refresh_once()
    assert cache.body(restricted=False) == HEALTHY | {"role_restricted": False}


async def test_the_restricted_body_leaves_out_position_only_rows_and_every_path() -> None:
    fake = _healthy()
    fake.put("XRPUSDT", "position_open", refusals=("position_open",))
    fake.put("ADAUSDT", "position_open", "chart_open", refusals=("position_open", "chart_open"))
    cache = _cache(fake, _budget())
    await cache.refresh_once()
    full, restricted = cache.body(restricted=False), cache.body(restricted=True)
    assert full is not None and restricted is not None
    assert {"XRPUSDT", "ADAUSDT"} <= {row["symbol"] for row in full["symbols"]}
    rows = {row["symbol"]: row for row in restricted["symbols"]}
    assert "XRPUSDT" not in rows and rows["ADAUSDT"]["refusal"] == "chart_open"
    assert restricted["role_restricted"] is True and "position_open" not in json.dumps(restricted)
    assert all("endpoint" not in link for link in restricted["connections"])
    assert "/" not in json.dumps(restricted) and "\\" not in json.dumps(restricted)


async def test_no_runtime_is_not_deployed_and_names_nothing_it_does_not_know() -> None:
    cache = _cache(None, _budget())
    assert cache.body(restricted=False) is None  # before the first computation
    await cache.refresh_once()
    for restricted in (False, True):
        assert cache.body(restricted) == {
            "overall": "not_deployed", "connections": [], "symbols": [],
            "generated_at": "2026-09-14T10:31:02.900Z", "role_restricted": restricted,
        }  # fmt: skip
    snapshot = cache.snapshot()
    assert snapshot is not None and snapshot.status is None and snapshot.policy is None


async def test_one_computation_a_second_whatever_the_number_of_readers() -> None:
    source, clock, slept, reads = _Counting(), _Clock(), [], []
    source.put("BTCUSDT")
    done = asyncio.Event()

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        clock.t += seconds
        reads.extend(cache.body(restricted=n % 2 == 1) for n in range(200))  # 200 readers a tick
        if len(slept) == 5:
            done.set()
            await asyncio.Event().wait()  # until `stop` cancels it

    cache = _cache(source, _budget(), clock=clock, sleep=sleep)
    cache.start()
    cache.start()  # idempotent: still one task
    await done.wait()
    await cache.stop()
    await cache.stop()  # idempotent
    assert (source.calls, slept) == (5, [1.0] * 5)
    assert len(reads) == 1_000 and all(body is not None for body in reads)


async def test_a_failed_computation_keeps_the_last_snapshot_and_its_age_grows() -> None:
    clock, slept, fake, done = _Clock(), [], _Counting(), asyncio.Event()

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        clock.t += seconds
        if len(slept) == 2:
            done.set()
            await asyncio.Event().wait()

    def age() -> float:
        return float(recorder_status_cache_age_seconds.collect()[0].samples[0].value)

    cache = _cache(fake, _budget(), clock=clock, sleep=sleep)
    assert age() == math.inf  # never computed
    await cache.refresh_once()
    first = cache.snapshot()
    clock.t += 2.5
    assert age() == 2.5
    fake.fail = True  # every later status read fails
    cache.start()
    await done.wait()
    await cache.stop()
    assert cache.snapshot() is first and fake.calls == 3 and age() == 4.5


def test_the_policy_is_integers_within_their_bounds() -> None:
    cfg = PolicyConfig(autostart_delay_s=59.2, autostop_grace_s=-3.0, max_symbols=0)
    wild = cast(BudgetConfig, SimpleNamespace(warn_pct=0, autostop_pct=101, halt_pct=95))
    policy = policy_settings(cfg, wild)
    assert policy == {
        "autostart_delay_s": 60, "autostop_grace_s": 0, "max_symbols": 1, "warn_pct": 1,
        "autostop_pct": 100, "halt_pct": 95, "autorecord_enabled": True,
    }  # fmt: skip
    assert all(type(v) is int for k, v in policy.items() if k != "autorecord_enabled")
    defaults = policy_settings(PolicyConfig(), BudgetConfig(cap_bytes=CAP))
    assert defaults == HEALTHY["policy"] | {"max_symbols": 20}


async def test_no_budget_means_no_policy_and_no_storage() -> None:
    cache = _cache(_healthy(), None)
    await cache.refresh_once()
    snapshot, body = cache.snapshot(), cache.body(restricted=False)
    assert snapshot is not None and snapshot.policy is None and snapshot.storage is None
    assert body is not None and "policy" not in body


async def test_storage_level_is_the_effective_level_a_refused_volume_included() -> None:
    budget = _budget()
    cache = _cache(_healthy(), budget)
    await cache.refresh_once()
    snapshot = cache.snapshot()
    assert snapshot is not None and snapshot.storage == {
        "level": 0, "write_gate": "open", "write_gate_reason": None,
        "accelerate_retention": False,
    }  # fmt: skip
    await budget.sample_once()  # a report: the measured fields join
    budget.recording_refused = True  # the ladder's own level stays 0
    await cache.refresh_once()
    snapshot = cache.snapshot()
    assert snapshot is not None and snapshot.storage is not None
    assert int(budget.level) == 0 and int(budget.effective_level) == 3
    assert snapshot.storage == {
        "level": 3, "write_gate": "closed", "write_gate_reason": "volume_refused",
        "accelerate_retention": False, "disk_free_bytes": 500 * GB, "daily_growth_bytes": 0,
        "cap_bytes": CAP, "used_bytes": 200 * GB, "projected_full_at_ms": None,
    }  # fmt: skip
