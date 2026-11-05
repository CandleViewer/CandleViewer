# ruff: noqa: S101  (pytest asserts: the project's tests/** ignore does not reach spike/)
"""The delta re-check's findings at `596de30a` (#843 A4 fold 5), each pinned: R3-02 (a stop
before a cycle's opener or its drive sends nothing more), R3-03 (the KEK mount as #4522's KEK
services carry it), R3-04 (a row the adapter set aside during the flat check's reads refuses the
start), and the README's words for them and for R3-05 (the host-window rebase). R3-01 (each
fsync after its row's write) is pinned in `test_ledger.py`."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import yaml

from candleviewer.domain.order_link import account_tag
from candleviewer.domain.primitives import AccountId, GroupId
from candleviewer.oms.order_link import OrderLinkIdParts
from spike.oms_demo_path import cycles, run
from spike.oms_demo_path.config import RunConfig
from spike.oms_demo_path.harness import Harness
from spike.oms_demo_path.safety import rows_set_aside
from spike.oms_demo_path.tests.test_recheck import (
    COMPOSE,
    HERE,
    KEY_INFO,
    README,
    _cfg,
    _flat,
    _venue,
)
from spike.oms_demo_path.tests.test_scope import _refused_and_untouched

#: #4522's overlay (`infra/compose/docker-compose.demo-host.yml`), whose KEK services the spike's
#: mount follows line for line.
DEMO_HOST = HERE.parents[3] / "infra" / "compose" / "docker-compose.demo-host.yml"
KEK_MOUNT = {"source": "cv_kek", "target": "cv_kek", "uid": "10001", "gid": "10001", "mode": 0o400}
RUN_ACCOUNT = UUID("00000000-0000-4000-8000-000000000001")
OTHER_ACCOUNT = UUID("00000000-0000-4000-8000-000000000002")


def _events(out: Path, kind: str) -> list[dict[str, Any]]:
    lines = (out / "events.jsonl").read_text(encoding="utf-8").splitlines()
    return [e for e in map(json.loads, lines) if e["kind"] == kind]


# -- R3-02: a stop before a cycle's opener or its drive: nothing more is sent ------------------


@pytest.mark.parametrize("lands", ["in the reference read", "in the periodic offset read"])
async def test_a_stop_before_a_cycles_opener_sends_nothing_more(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lands: str
) -> None:
    venue, out = _venue(), tmp_path / "out"
    one_cycle, measure = cycles.one_cycle, Harness.measure_offset
    reads: list[Harness] = []

    async def measured(h: Harness, samples: int = 5) -> int | None:
        reads.append(h)  # the preflight's read, then one before each later cycle
        if len(reads) == 2 and lands == "in the periodic offset read":
            h.shutdown.trip("signal:SIGINT")
        return await measure(h, samples)

    async def priced(h: Harness, cfg: RunConfig, n: int, *args: Any) -> str:
        if n == 1 and lands == "in the reference read":
            reference = h.public.reference

            async def stopped_meanwhile() -> Decimal:
                h.shutdown.trip("signal:SIGINT")
                return await reference()

            monkeypatch.setattr(h.public, "reference", stopped_meanwhile)
        return await one_cycle(h, cfg, n, *args)

    monkeypatch.setattr(Harness, "measure_offset", measured)
    monkeypatch.setattr(cycles, "one_cycle", priced)
    assert await run.run(_cfg(out, cycles=3, offset_every=1), venue=venue) == 0
    s = dict(run.summary_of(out))
    assert s["outcome"] == "stopped" and s["shutdown"]["reason"] == "signal:SIGINT"
    block = s["cycles"]
    assert block["outcomes"] == {"partial": 1, "stopped": 1} and block["completed"] == 1
    assert block["actions"]["place"] == 1 and len(venue.creates) == 2  # cycle 0's opener, close
    shutdown = s["shutdown"]
    assert (shutdown["action"], shutdown["cancelled"], shutdown["flatten_orders"]) == (
        "scoped flatten",
        0,
        0,
    )
    assert shutdown["flat"] is True and venue.size == 0
    stopped = [(e["n"], e["stopped"]) for e in _events(out, "cycle") if e["outcome"] == "stopped"]
    assert stopped == [(1, "before the opener")]


async def test_a_stop_after_a_cycles_opener_sends_no_drive_and_the_flatten_cancels_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    venue, out = _venue(), tmp_path / "out"
    seen: list[Harness] = []
    amends: list[dict[str, Any]] = []
    one_cycle, amend = cycles.one_cycle, venue._order_amend

    async def kept(h: Harness, *args: Any) -> str:
        seen.append(h)
        return await one_cycle(h, *args)

    def stopped_at_the_first_amend(body: dict[str, Any], params: dict[str, str]) -> dict[str, Any]:
        amends.append(body)
        seen[0].shutdown.trip("signal:SIGTERM")  # it lands as the venue takes the one-tick amend
        return amend(body, params)

    monkeypatch.setattr(cycles, "one_cycle", kept)
    monkeypatch.setattr(venue, "_order_amend", stopped_at_the_first_amend)
    assert await run.run(_cfg(out, fill_mode="cross"), venue=venue) == 0  # a drive: a taker
    s = dict(run.summary_of(out))
    assert s["outcome"] == "stopped" and s["cycles"]["outcomes"] == {"stopped": 1}
    assert s["cycles"]["actions"] == {"amend": 1, "place": 1} and len(amends) == 1  # no drive
    assert s["cycles"]["completed"] == 0 and venue.fills == 0 and venue.size == 0
    shutdown = s["shutdown"]
    assert (shutdown["cancelled"], shutdown["flatten_orders"], shutdown["flat"]) == (1, 0, True)
    assert [o.status for o in venue.orders.values()] == ["Cancelled"]  # by the flatten
    stopped = [(e["n"], e["stopped"]) for e in _events(out, "cycle") if e["outcome"] == "stopped"]
    assert stopped == [(0, "before the drive")]


# -- R3-03: the KEK mount and the healthcheck, as #4522's KEK services have them ---------------


def test_the_spike_mounts_the_kek_as_4522s_kek_services_do_with_no_healthcheck() -> None:
    spike = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]["spike"]
    host = yaml.safe_load(DEMO_HOST.read_text(encoding="utf-8"))["services"]
    assert spike["secrets"] == [KEK_MOUNT]
    for name in ("api", "bootstrap-owner"):  # line for line
        assert host[name]["secrets"] == spike["secrets"], name
    assert spike["healthcheck"] == {"disable": True} == host["bootstrap-owner"]["healthcheck"]


# -- R3-04: a row the adapter set aside during the flat check's reads refuses the start --------


@pytest.mark.parametrize("names", ["another account", "another environment"])
async def test_an_order_of_ours_naming_another_account_refuses_the_start_and_is_untouched(
    tmp_path: Path, names: str
) -> None:
    """The adapter drops a row whose `orderLinkId` is one of ours naming another account or
    environment (`trading_parse.owner_refusal`), so the flat check never sees that order; the
    count it keeps of such rows moved during the reads, and the run is refused."""
    assert account_tag(AccountId(RUN_ACCOUNT)) != account_tag(AccountId(OTHER_ACCOUNT))
    venue, out = _venue(), tmp_path / "out"
    hidden = venue.rest_foreign_order()
    elsewhere = names == "another environment"
    hidden.link = OrderLinkIdParts.generate(
        mode="exchange",
        environment="live" if elsewhere else "demo",
        group_id=GroupId(uuid4()),
        account_id=AccountId(RUN_ACCOUNT if elsewhere else OTHER_ACCOUNT),
        seq=0,
        purpose="entry",
    ).value
    reason = "environment" if elsewhere else "account"
    before = rows_set_aside().get(reason, 0.0)
    assert await run.run(_cfg(out, account_id=RUN_ACCOUNT), venue=venue) == 2
    _refused_and_untouched(out, venue, f"set aside ({reason} +1)")
    assert venue.paths == [KEY_INFO, "/v5/order/realtime", "/v5/position/list"]
    assert (hidden.status, hidden.filled) == ("New", Decimal(0))
    assert rows_set_aside()[reason] == before + 1  # the adapter's own count, read, never set


# -- the README's words for R3-02 to R3-05 -----------------------------------------------------

NOTES = {
    "R3-02": "a cycle checks for a stop before its opener's create and before its drive",
    "R3-03": "compose ignores those three mount keys outside swarm and bind-mounts the host file"
    " as it is, so the host file carries them",
    "R3-04": "the harness reads that counter before and after the flat check's reads, and a count"
    " that moved refuses the run",
    "R3-05 range-diff": "its range-diff is `=` for every commit",
    "R3-05 tree": "`git rev-parse head:services/api/spike` prints the same tree hash as `git"
    " rev-parse <approved head>:services/api/spike`",
    "R3-05 gates": "the offline gates are re-run on the rebased head, from its `services/api`, and"
    " pass: `ruff check spike/`, `ruff format --check spike/`, `mypy --strict --platform linux"
    " --explicit-package-bases spike`, the harness's tests (`pytest spike/oms_demo_path/tests`",
}


@pytest.mark.parametrize("finding", sorted(NOTES))
def test_the_readme_says_what_each_delta_finding_asks(finding: str) -> None:
    assert NOTES[finding] in _flat(README.read_text(encoding="utf-8")).lower()
