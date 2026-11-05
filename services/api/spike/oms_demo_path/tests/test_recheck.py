# ruff: noqa: S101  (pytest asserts: the project's tests/** ignore does not reach spike/)
"""The combined re-check's findings at `6cae9547` (#843 A4 fold 4), each pinned: R2-01 (no core
dumps), R2-02 (the m2 branch), R2-04 and R2-05 (the KEK source, the image), R2-06 (a stop during
the preflight or mid-cycle), R2-07 (the writer survives any failure), R2-08 (flat account-wide),
R2-09 (the owner DSN never named), R2-10 (the shared venv), R2-12 (a venue close counted), and
the README's and the report's words for the coordinator's rulings 3 and 4."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

from candleviewer.exchange.base.models import CancelOrderRequest
from spike.oms_demo_path import cycles, modes, report, run
from spike.oms_demo_path.config import RunConfig
from spike.oms_demo_path.harness import Harness
from spike.oms_demo_path.offline import Corpus, CorpusVenue, default_corpus
from spike.oms_demo_path.outputs import RunOutputs
from spike.oms_demo_path.scrub import Scrubber
from spike.oms_demo_path.tests.test_modes import _Rig
from spike.oms_demo_path.tests.test_safety import (
    _flatten,
    _Venue,
    bind,
    execution,
    guarded,
    mine,
    scoped,
)
from spike.oms_demo_path.tests.test_scope import TOUCHING, _refused_and_untouched

HERE = Path(run.__file__).parent
README = HERE / "README.md"
COMPOSE = HERE / "docker-compose.spike.yml"
KEY_INFO = "/v5/user/query-api"


def _venue() -> CorpusVenue:
    return CorpusVenue(Corpus(default_corpus()))


def _cfg(out: Path, **fields: Any) -> RunConfig:
    base: dict[str, Any] = {"mode": "cycles", "out": out, "cycles": 2, "min_hours": 0.0}
    return RunConfig(**(base | {"fill_wait_s": 0.2} | fields))


def _flat(text: str) -> str:
    return " ".join(text.split())


# -- R2-01, R2-04, R2-05, R2-09: the spike service, as compose reads it ------------------------


def test_the_spike_service_takes_no_core_dump_no_pull_and_the_kek_as_a_file() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    spike = yaml.safe_load(text)["services"]["spike"]
    assert spike["ulimits"] == {"core": 0}  # R2-01: its M2 holds the KEK for the run
    assert spike["pull_policy"] == "never"  # R2-05: the image built, or verified by digest
    assert spike["image"] == "${CV_SPIKE_API_IMAGE:-cv-demo-api}"
    env = spike["environment"]
    assert (env["CV_KEK_SOURCE"], env["CV_KEK_HANDLE"]) == ("file", "/run/secrets/cv_kek")
    assert env["CV_PG_DSN"].startswith("${CV_PG_DSN:?")  # the runtime role's DSN
    assert "CV_PG_OWNER_DSN" not in text  # R2-09: never named, not even in a comment


# -- the README and the report: what each ruling and finding asks them to say --------------------

NOTES = {
    "ruling 3": "the ledger row's write and fsync happen before the measured window opens",
    "ruling 2": "no signed use of a key that fails it, ever",
    "ruling 4": "restore it from the main checkout when the worktree goes, so no other checkout"
    " or machine inherits the pointer",
    "R2-01": "#4522's accepted swap deviation (swap on and not encrypted on this demo host, demo"
    " funds only) covers this container too",
    "R2-02": "check out `spike/oms-demo-path-m2` at the head named in the latest approve record on"
    " the draft pr, and confirm it with `git rev-parse head`",
    "R2-05 digest": "set `cv_spike_api_image=$image@$digest`",
    "R2-05 root": "run this and every compose command below as root, as all of #4522's commands"
    " are: its `infra/compose/.env` is root-owned, mode 0600",
    "R2-06": "a closed terminal sends sighup into the container only if the compose client"
    " forwards it",
    "R2-06 tmux": "tmux (step 5) is the supported way to keep a run alive",
    "R2-10": "use a virtualenv per worktree, or only commands that put the checkout's directory"
    " first (`python -m`, pytest from `services/api`)",
    "R2-12": "with a foreign position on the same side (a broken precondition: a manual trade"
    " during the run), the capped close then reduces that foreign position by up to the run's"
    " net",
}


@pytest.mark.parametrize("finding", sorted(NOTES))
def test_the_readme_says_what_each_ruling_and_finding_asks(finding: str) -> None:
    assert NOTES[finding] in _flat(README.read_text(encoding="utf-8")).lower()


def test_the_runbook_and_the_package_name_the_m2_branch_never_the_superseded_one() -> None:
    readme = README.read_text(encoding="utf-8")
    assert "spike/oms-demo-path-m2" in readme.splitlines()[2]
    assert "`spike/oms-demo-path`" not in readme  # 47bf71c2: the env-key harness, superseded
    assert "`spike/oms-demo-path-m2`." in (HERE / "__init__.py").read_text().splitlines()[0]


def test_the_report_and_the_addendum_print_where_the_ledger_row_falls(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    summary = {"mode": "cycles", "offline": True, "budget4": {"rule": run.BUDGET4_RULE}}
    (run_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    for text in (report.render(run_dir), report.addendum(run_dir)):
        table = text.index("| create, ms |")
        assert text.index(report.LEDGER_NOTE) > table  # under the budget table
    assert NOTES["ruling 3"] in report.LEDGER_NOTE


# -- R2-06: a stop during the preflight never arms; mid-run, it ends the waits and the creates --


@pytest.mark.parametrize("mode", ["cycles", "shapes"])
async def test_a_stop_during_the_preflight_never_arms_and_touches_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    measure = Harness.measure_offset

    async def stopped_meanwhile(h: Harness, samples: int = 5) -> int | None:
        h.shutdown.trip("signal:SIGTERM")  # the owner's stop lands during the preflight
        return await measure(h, samples)

    monkeypatch.setattr(Harness, "measure_offset", stopped_meanwhile)
    venue, out = _venue(), tmp_path / "out"
    assert await run.run(_cfg(out, mode=mode), venue=venue) == 0
    s = dict(run.summary_of(out))
    assert s["outcome"] == "stopped" and s["stopped"].startswith("a stop arrived before the run")
    assert s["shutdown"] == {"reason": "signal:SIGTERM", **run.NO_ACTION}
    assert venue.creates == [] and not TOUCHING & set(venue.paths) and mode not in s


@pytest.mark.parametrize(("stop", "creates"), [("before the first create", 0), ("second", 1)])
async def test_shapes_checks_for_a_stop_before_each_create(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stop: str, creates: int
) -> None:
    rig = _Rig(tmp_path, _venue())
    h, venue = rig.harness, rig.venue
    if creates == 0:  # armed, then stopped while it prices its opener
        reference = h.public.reference

        async def stopped_then_priced() -> Decimal:
            h.shutdown.trip("signal:SIGINT")
            return await reference()

        monkeypatch.setattr(h.public, "reference", stopped_then_priced)
    else:  # stopped while the venue takes its first create
        create = venue._order_create

        def then_stopped(body: dict[str, Any], params: dict[str, str]) -> dict[str, Any]:
            h.shutdown.trip("signal:SIGINT")
            return create(body, params)

        monkeypatch.setattr(venue, "_order_create", then_stopped)
    shapes = await modes.run_shapes(h, RunConfig(mode="shapes", out=tmp_path))
    assert h.armed and len(venue.creates) == creates and stop in str(shapes["stopped"])
    assert all(o.status == "Cancelled" for o in venue.orders.values())  # its one, cancelled
    assert 10002 not in rig.recorder.codes  # and no probe after the stop


async def test_a_stop_ends_a_fill_wait_at_once(tmp_path: Path) -> None:
    h = _Rig(tmp_path, _venue()).harness
    waiting = asyncio.create_task(h.wait(lambda: False, 3600.0))
    for _ in range(5):  # the wait is parked on the stream before the stop arrives
        await asyncio.sleep(0)
    assert not waiting.done()
    h.shutdown.trip("signal:SIGTERM")
    async with asyncio.timeout(5):  # never the hour it was given
        assert await waiting is False
    assert await h.wait(lambda: True, 3600.0) is True  # a stop never hides what holds


async def test_a_stop_mid_cycle_ends_its_fill_waits_and_reaches_the_flatten_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    venue, out = _venue(), tmp_path / "out"
    monkeypatch.setattr(venue, "_match", lambda _order: None)  # nothing fills: it would wait
    seen: list[Harness] = []
    amends: list[dict[str, Any]] = []
    one_cycle, amend = cycles.one_cycle, venue._order_amend

    async def kept(h: Harness, *args: Any, **kwargs: Any) -> str:
        seen.append(h)
        return await one_cycle(h, *args, **kwargs)

    def stopped_at_the_drive(body: dict[str, Any], params: dict[str, str]) -> dict[str, Any]:
        amends.append(body)
        if len(amends) == 2:  # the drive: the owner's Ctrl-C lands, its fill awaited next
            seen[0].shutdown.trip("signal:SIGINT")
        return amend(body, params)

    monkeypatch.setattr(cycles, "one_cycle", kept)
    monkeypatch.setattr(venue, "_order_amend", stopped_at_the_drive)
    async with asyncio.timeout(60):  # each of its fill waits alone is 600 s
        assert await run.run(_cfg(out, cycles=3, fill_wait_s=600.0), venue=venue) == 0
    s = dict(run.summary_of(out))
    assert s["outcome"] == "stopped" and s["cycles"]["outcomes"] == {"unfilled": 1}
    assert s["shutdown"]["action"] == "scoped flatten" and s["shutdown"]["flat"] is True
    assert len(amends) == 2 and all(o.status == "Cancelled" for o in venue.orders.values())


# -- R2-07: the writer counts any failure and goes on ----------------------------------------


async def test_a_work_item_that_raises_any_error_is_counted_and_the_writer_goes_on(
    tmp_path: Path,
) -> None:
    outputs = RunOutputs(tmp_path / "out", Scrubber())
    outputs.start()

    def broken() -> None:
        raise ValueError("a work item's own bug")

    assert outputs.later(broken) is True
    outputs.event("after", n=1)
    async with asyncio.timeout(5):  # `flush` and `stop` never wait forever
        await outputs.flush()
        await outputs.stop()
    assert outputs.write_errors == 1 and outputs.events == 1
    line = json.loads((tmp_path / "out" / "events.jsonl").read_text(encoding="utf-8"))
    assert line["kind"] == "after"


# -- R2-08: flat means every symbol's open orders, as positions are read ---------------------


async def test_a_foreign_order_on_another_symbol_refuses_the_start_and_is_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    venue, out = _venue(), tmp_path / "out"
    order = venue.rest_foreign_order(symbol="ETHUSDT")
    reads: list[dict[str, str]] = []
    handle = venue.handle

    async def kept(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v5/order/realtime":
            reads.append(dict(request.url.params))
        return await handle(request)

    monkeypatch.setattr(venue, "handle", kept)
    assert await run.run(_cfg(out), venue=venue) == 2
    _refused_and_untouched(out, venue, "open order")
    assert venue.paths == [KEY_INFO, "/v5/order/realtime", "/v5/position/list"]
    [params] = reads
    assert params["settleCoin"] == "USDT" and "symbol" not in params  # every USDT perpetual
    assert (order.symbol, order.status, order.filled) == ("ETHUSDT", "New", Decimal(0))


# -- R2-12: a venue close in the run's window is counted, the close rule unchanged ------------


async def test_the_flatten_counts_the_fills_in_its_window_that_are_not_the_runs() -> None:
    """A native stop's close is a `trade` no ledger lists and a liquidation a `bust_trade`: the
    run's own net stays what its fills opened, so with a foreign long beside it (a broken
    precondition) the capped close reduces that long. The record counts both closes."""
    links, scope = scoped()
    fake = _Venue("0.003")  # what the venue holds: a manual long, after the venue's closes
    guard, _ = guarded(fake)
    bind(guard, scope)
    fake.seed_execution(execution(await mine(links, scope), "buy", "0.002", 1))
    stop_close = execution(f"ext-{'1' * 32}", "sell", "0.001", 2)  # the native stop's
    liquidation = execution(f"ext-{'2' * 32}", "sell", "0.001", 3)
    fake.seed_execution(stop_close)
    fake.seed_execution(liquidation.model_copy(update={"exec_type": "bust_trade"}))
    report_ = await _flatten(guard, scope, links)
    assert report_["fills_not_ours_in_window"] == {"bust_trade": 1, "trade": 1}
    assert (report_["own_net_qty"], report_["closed_qty"]) == ("0.002", "0.002")
    assert fake.held == Decimal("0.001")  # the documented consequence: the foreign long reduced
    cancels = [c for c in fake.calls if isinstance(c.request, CancelOrderRequest)]
    assert cancels == []


async def test_the_scope_reads_only_btcusdt_fills_and_owns_only_their_trades() -> None:
    """Another symbol's fill nets nothing with the run's BTCUSDT position, and a fill that is no
    trade is never taken for the run's own, even under a link its ledger lists."""
    links, scope = scoped()
    own = await mine(links, scope)
    elsewhere = execution(own, "buy", "0.001", 1).model_copy(update={"symbol": "ETHUSDT"})
    settled = execution(own, "buy", "0.001", 2).model_copy(update={"exec_type": "settle"})
    scope.add([elsewhere, settled, execution(own, "buy", "0.002", 3)])
    assert scope.net() == Decimal("0.002") and list(scope.fills) == ["exec-0003"]
    assert scope.not_ours_by_type() == {}
