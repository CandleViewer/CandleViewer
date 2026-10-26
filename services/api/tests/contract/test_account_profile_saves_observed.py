"""#906 D3b (E28-T02): each profile save counted once by its answer, a refused one once per distinct
rule, and timed from its handler's entry (`SaveMeasures`). The writes' router is built here through
the factory with its measures (the app binds them at the mount: the coordinator's ruling of
2026-10-25 23:35Z), over `_profile_writes_world`'s fakes and a clock only they move: no sleep, no
network (C-13.5, C-13.7). Replays, deletes, moves and admission refusals are no saves. The two
`perf` budgets, SCR-131's save p95 with a cold catalogue refresh and the list's 150 ms, run in
CI's perf lane only (C-13.9)."""

from __future__ import annotations

import dataclasses
import time
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.accounts.profile_validator import InstrumentLimitsUnavailable
from candleviewer.api.profile_writes import SAVE_RESULTS, SaveMeasures, make_profile_writes_router
from candleviewer.instrument_limits_wiring import CatalogueLimits
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import register_r0
from candleviewer.storage.repositories import account_profiles as port
from tests.contract._profile_writes_world import Writes, build
from tests.contract.rbac.rbac_harness import GRANTED, WS_ORIGIN, bearer
from tests.contract.test_account_profile_reads_provider import _row
from tests.contract.test_account_profile_writes_provider import (
    _INFINITE,
    _RISK,
    ALT,
    CREATE,
    DELETE,
    MOVE,
    REPLACE,
    send,
)
from tests.unit.ingestion.test_instruments_on_demand import HangingFetch, _scheduler, _warm

_FAMILIES = ("cv_profile_saves", "cv_profile_validation_failures", "cv_profile_save_seconds")
_GONE = uuid.UUID(int=99)  # no profile of any account


@dataclasses.dataclass
class Rig:
    """`w`, the world `build` makes, and `saves`: the same fakes behind this module's app, which
    serves the writes' router alone, measured over `metrics` and timed by `now`."""

    w: Writes
    saves: Writes
    metrics: Metrics
    now: list[float]


@pytest.fixture(scope="module")
def _rig() -> Iterator[Rig]:
    with pytest.MonkeyPatch.context() as mp:  # undone however the module ends
        w, metrics, now = build(mp), Metrics("demo"), [0.0]
        register_r0(metrics)
        measures = SaveMeasures.bound(metrics, clock=lambda: now[0])
        app = FastAPI()
        app.include_router(make_profile_writes_router(
            w.writes, w.world.audit, w.world.resolver, replays=w.replays, measures=measures
        ))  # fmt: skip
        saves = dataclasses.replace(w, world=dataclasses.replace(w.world, client=TestClient(app)))
        yield Rig(w, saves, metrics, now)


@pytest.fixture
def rig(_rig: Rig) -> Rig:
    _rig.w.reset()
    _rig.now[0] = 0.0
    return _rig


def _measured(rig: Rig, action: Callable[[], Any]) -> tuple[Any, dict[str, float]]:
    """`action`'s answer, and what it added to the three series: a save by its result, a refusal
    by its rules, the round trips' `count` and `sum`."""

    def samples() -> dict[str, float]:
        return {
            s.labels.get("result") or s.labels.get("rule") or s.name.rpartition("_")[2]: s.value
            for f in rig.metrics.registry.collect() if f.name in _FAMILIES
            for s in f.samples if s.name.endswith(("_total", "_count", "_sum"))
        }  # fmt: skip

    before = samples()
    out = action()
    return out, {k: v - before[k] for k, v in samples().items() if v != before[k]}


def _key_used_twice(w: Writes, body: dict[str, Any]) -> Any:
    """A create, then the same key with `body`: its replay, or 409 for another body (H8)."""
    key = str(uuid.uuid4())
    send(w, CREATE, key=key)
    return send(w, CREATE, key=key, body=body)


def _replace_key_used_twice(w: Writes) -> Any:
    """A replace, then the same key with another body: 409 (H8), so no second save."""
    key = str(uuid.uuid4())
    send(w, REPLACE, key=key)
    return send(w, REPLACE, key=key, body={**_RISK, "name": "Bob"})


def _catalogue_down(w: Writes) -> Any:
    w.limits.fails = InstrumentLimitsUnavailable("no listing in time")
    return send(w, CREATE)


_CASES = [
    pytest.param(lambda w: send(w, CREATE), 201, {"saved": 1}, id="created"),
    pytest.param(lambda w: send(w, REPLACE), 200, {"saved": 1}, id="replaced"),
    pytest.param(lambda w: send(w, CREATE, body={**_RISK, "colour": "red"}), 422, {"refused": 1},
                 id="refused"),
    pytest.param(lambda w: send(w, REPLACE, tags=[f'W/"{ALT}:1"']), 412, {"stale": 1}, id="stale"),
    pytest.param(lambda w: send(w, REPLACE, tags=[]), 428, {"stale": 1}, id="untagged"),
    pytest.param(lambda w: send(w, CREATE, body={**_RISK, "name": "alt"}), 409, {"conflict": 1},
                 id="name-taken"),
    pytest.param(lambda w: send(w, REPLACE, profile=_GONE, tags=[f'W/"{_GONE}:1"']), 404,
                 {"not_found": 1}, id="no-profile"),
    pytest.param(_catalogue_down, 503, {"unavailable": 1}, id="catalogue-down"),
    pytest.param(lambda w: _key_used_twice(w, _RISK), 201, {"saved": 1}, id="replayed"),
    pytest.param(lambda w: _key_used_twice(w, {**_RISK, "name": "Bob"}), 409, {"saved": 1},
                 id="key-reused"),
    pytest.param(lambda w: send(w, DELETE), 204, {}, id="deleted"),
    pytest.param(lambda w: send(w, MOVE), 200, {}, id="moved"),
    pytest.param(lambda w: send(w, CREATE, raw=b"[" * 65_537), 413, {}, id="over-cap"),
    pytest.param(lambda w: send(w, CREATE, key="not-a-uuid"), 422, {}, id="bad-key"),
    pytest.param(lambda w: send(w, REPLACE, key="not-a-uuid"), 422, {}, id="replace-bad-key"),
    pytest.param(_replace_key_used_twice, 409, {"saved": 1}, id="replace-key-reused"),
    pytest.param(lambda w: send(w, REPLACE, at=uuid.uuid4()), 404, {}, id="no-account"),
    pytest.param(lambda w: send(w, CREATE, "manager_with_grant"), 403, {}, id="forbidden"),
]  # fmt: skip


@pytest.mark.parametrize(("case", "status", "counted"), _CASES)
def test_each_save_counts_once_by_its_result(
    rig: Rig, case: Callable[[Writes], Any], status: int, counted: dict[str, int]
) -> None:
    """2xx `saved`, 422 `refused`, 412 and 428 `stale`, 409 `conflict`, 404 `not_found` and 503
    `unavailable`, from C1/U1 on; an admission refusal (H1 to H8: the account, the 413, the key and
    its reuse), a replay, a delete and a move are no save."""
    resp, delta = _measured(rig, lambda: case(rig.saves))
    results = {result: n for result, n in delta.items() if result in SAVE_RESULTS}
    assert (resp.status_code, results) == (status, counted)


def test_a_refused_save_counts_each_distinct_rule_once_and_any_other_type_as_schema(
    rig: Rig,
) -> None:
    """Three unlisted symbols and SOLUSDT past its 20x count `symbol_not_listed` and `max_leverage`
    once each; a model's own types (`int_type`; a control character and an unknown member
    together) count `schema` once a refusal; the store's CHECKs count as the passes answer them,
    `ap_native_sl` as `native_stop_mandatory` and any other as `schema`."""
    caps = {**_RISK["risk_caps"], "max_leverage_cap": "25"}
    symbols = ["SOLUSDT", "Q1USDT", "Q2USDT", "Q3USDT"]
    limits = {**_RISK, "leverage": "25", "risk_caps": caps, "allowed_symbols": symbols}
    shaped = {**_RISK, "name": "Alice\x00", "colour": "red"}

    def refused() -> list[Any]:
        sent = [send(rig.saves, CREATE, body=body) for body in (limits, shaped)]
        sent.append(send(rig.saves, CREATE, raw=_INFINITE))
        for rule in ("ap_native_sl", "ap_trading_caps"):
            rig.w.rows.fails["profiles"] = port.AccountProfileStoreRuleError(rule)
            sent.append(send(rig.saves, CREATE))
        return sent

    sent, delta = _measured(rig, refused)
    rules = [sorted({e["rule"] for e in resp.json()["errors"]}) for resp in sent]
    assert rules == [
        ["max_leverage", "symbol_not_listed"], ["extra_forbidden", "string_pattern_mismatch"],
        ["int_type"], ["native_stop_mandatory"], ["ap_trading_caps"],
    ]  # fmt: skip
    counted = {"refused": 5, "max_leverage": 1, "symbol_not_listed": 1, "schema": 3}
    counted |= {"native_stop_mandatory": 1}
    assert {k: v for k, v in delta.items() if k not in ("count", "sum")} == counted


def test_a_refused_replace_counts_its_rules_as_a_create_does(rig: Rig) -> None:
    """The replace's exit collects its refusal's rules too: an unknown member is one `schema`
    (round 1's R1C-01; the create's are B4's)."""
    body = {**_RISK, "colour": "red"}
    resp, delta = _measured(rig, lambda: send(rig.saves, REPLACE, body=body))
    counted = {k: v for k, v in delta.items() if k != "sum"}
    assert (resp.status_code, counted) == (422, {"refused": 1, "schema": 1, "count": 1})


def test_every_counted_save_observes_its_round_trip(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """From the handler's entry: the account read of admission (0.25 s here) and a catalogue read
    (1.25 s) are inside it. One sample per counted save, a refusal's and a stale one's too; none
    for a replay or a refusal of admission."""
    account, listing = rig.w.rows.get_account, rig.w.limits.listed

    async def slow_account(*args: Any) -> Any:
        rig.now[0] += 0.25
        return await account(*args)

    async def slow_listing(**bounds: float) -> Any:
        rig.now[0] += 1.25
        return await listing(**bounds)

    monkeypatch.setattr(rig.w.rows, "get_account", slow_account)
    monkeypatch.setattr(rig.w.limits, "listed", slow_listing)
    key = str(uuid.uuid4())
    sent, delta = _measured(rig, lambda: [
        send(rig.saves, CREATE, key=key), send(rig.saves, CREATE, key=key),
        send(rig.saves, REPLACE, tags=[]), send(rig.saves, CREATE, body={**_RISK, "colour": "x"}),
        send(rig.saves, CREATE, key="not-a-uuid"),
    ])  # fmt: skip
    assert [resp.status_code for resp in sent] == [201, 201, 428, 422, 422]
    assert {k: delta[k] for k in ("count", "sum")} == {"count": 3, "sum": 1.5 + 0.25 + 0.25}
    assert delta["count"] == sum(delta.get(result, 0) for result in SAVE_RESULTS)


def _p95(samples: list[float]) -> float:
    return sorted(samples)[int(len(samples) * 0.95) - 1]


def _app(rig: Rig) -> httpx.AsyncClient:
    """The app as `build` makes it, on the test's loop: no thread for each request (C-13.9)."""
    transport = httpx.ASGITransport(app=rig.w.world.app, client=("127.0.0.1", 50000))
    return httpx.AsyncClient(transport=transport, base_url=WS_ORIGIN, headers={"origin": WS_ORIGIN})


@pytest.mark.perf  # SCR-131's 2 s (C-13.9): P10 and N5 of the completeness map
async def test_a_profile_save_with_a_cold_catalogue_round_trips_within_two_seconds_p95(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """20 creates as the app serves them, each through `CatalogueLimits` over C's scheduler and its
    instant fetcher, the catalogue aged past 15 minutes before each: one refresh a save."""
    fetch = HangingFetch()
    fetch.up.set()
    scheduler = _scheduler(fetch)
    monkeypatch.setattr(rig.w.limits, "listed", CatalogueLimits("demo", lambda: scheduler).listed)
    took, path = [], f"/exchange-accounts/{GRANTED}/profiles"
    async with _app(rig) as client:
        for n in range(20):
            _warm(scheduler, age_s=901.0)
            body, began = {**_RISK, "name": f"Cold {n}"}, time.perf_counter()
            resp = await client.post(path, json=body, headers=bearer("owner"))
            took.append(time.perf_counter() - began)
            assert resp.status_code == 201
    print(f"\ncold-catalogue save: p95 {_p95(took) * 1e3:.1f} ms over {len(took)}")
    assert fetch.calls == 20 and 0 < _p95(took) <= 2.0


@pytest.mark.perf  # 06's 150 ms read p95 (C-13.9): N6 of the completeness map (M2)
async def test_a_list_of_fifty_profiles_answers_within_150_ms_p95(rig: Rig) -> None:
    """D1c's list as the app serves it, over 50 profiles of one account."""
    rig.w.rows.rows[GRANTED] = tuple(
        _row("risk_based", GRANTED, n, is_default=n == 1, name=f"P{n}") for n in range(1, 51)
    )
    took, path = [], f"/exchange-accounts/{GRANTED}/profiles"
    async with _app(rig) as client:
        for _ in range(40):
            began = time.perf_counter()
            resp = await client.get(path, headers=bearer("owner"))
            took.append(time.perf_counter() - began)
            assert (resp.status_code, len(resp.json()["items"])) == (200, 50)
    print(f"\nlist of 50: p95 {_p95(took) * 1e3:.1f} ms over {len(took)}")
    assert 0 < _p95(took) <= 0.150
