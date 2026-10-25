# ruff: noqa: S101  (pytest asserts: the project's tests/** ignore does not reach spike/)
"""The coordinator's rulings on R1C-02 and R1S-04, offline end to end (#843 A4 fold 2).

(a) A run that touches orders is armed only once its preflight passed. Refused before that (an
account not flat, the limits unset, a failed instrument read, a failed key check, any error),
it touches nothing on the account, and its record says `refused` with the reason and a shutdown
block showing no action. (b) Once armed, the shutdown cancels only orders carrying the run's own
`orderLinkId` prefix and closes only what its own fills opened: a foreign order and a foreign
position survive both a refused start and a normal shutdown. `flatten`, the owner's retry of a
failed shutdown flatten, adopts that run's scope from its summary and is scoped the same way.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from spike.oms_demo_path import cycles, report, run
from spike.oms_demo_path.config import RunConfig
from spike.oms_demo_path.harness import Harness
from spike.oms_demo_path.ledger import LEDGER
from spike.oms_demo_path.offline import (
    Corpus,
    CorpusVenue,
    OfflineStack,
    VenueOrder,
    default_corpus,
    offline_stack,
)

#: The routes that touch the account: a refused run sends none of them.
TOUCHING = frozenset(
    {"/v5/order/create", "/v5/order/amend", "/v5/order/cancel", "/v5/order/cancel-all"}
)
FOREIGN = Decimal("0.003")


def _venue() -> CorpusVenue:
    return CorpusVenue(Corpus(default_corpus()))


def _cfg(out: Path, **fields: Any) -> RunConfig:
    base: dict[str, Any] = {"mode": "cycles", "out": out, "cycles": 2, "min_hours": 0.0}
    return RunConfig(**(base | {"fill_wait_s": 0.2} | fields))


def _summary(out: Path) -> dict[str, Any]:
    return dict(run.summary_of(out))


@pytest.fixture
def stacks(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[OfflineStack]]:
    seen: list[OfflineStack] = []
    original = offline_stack

    async def keep(*args: Any, **kwargs: Any) -> OfflineStack:
        stack = await original(*args, **kwargs)
        seen.append(stack)
        return stack

    monkeypatch.setattr(run, "offline_stack", keep)
    yield seen


def _foreign(venue: CorpusVenue) -> VenueOrder:
    """A manual order resting and a manual position held: the account's other user."""
    venue.hold_foreign_position(FOREIGN)
    return venue.rest_foreign_order()


def _untouched(venue: CorpusVenue, order: VenueOrder, size: Decimal) -> None:
    assert (order.status, order.qty, order.filled) == ("New", Decimal("0.003"), Decimal(0))
    assert venue.size == size


def _refused_and_untouched(out: Path, venue: CorpusVenue, reason: str) -> dict[str, Any]:
    s = _summary(out)
    assert s["outcome"] == "refused" and reason in s["refused"]
    assert s["shutdown"] == {
        "reason": "refused",
        "armed": False,
        "action": "none",
        "cancelled": 0,
        "flatten_orders": 0,
        "closed_qty": "0",
    }
    assert venue.creates == [] and not TOUCHING & set(venue.paths)
    return s


# -- (a) refused before the run is armed: nothing on the account is touched ------------------


async def test_a_non_flat_account_is_refused_and_its_foreign_rows_survive(
    tmp_path: Path, stacks: list[OfflineStack]
) -> None:
    venue = _venue()
    order = _foreign(venue)
    assert await run.run(_cfg(tmp_path / "out"), venue=venue) == 2
    _refused_and_untouched(tmp_path / "out", venue, "open order")
    # its preflight only: the key's rights (fold 3), then the flat check's two reads
    assert venue.paths == ["/v5/user/query-api", "/v5/order/realtime", "/v5/position/list"]
    _untouched(venue, order, FOREIGN)
    text = report.render(tmp_path / "out")
    assert "Refused, nothing touched: the account has an open order" in text


async def test_a_held_position_alone_is_refused(tmp_path: Path, stacks: list[OfflineStack]) -> None:
    venue = _venue()
    venue.hold_foreign_position(FOREIGN)
    assert await run.run(_cfg(tmp_path / "out", mode="shapes"), venue=venue) == 2
    _refused_and_untouched(tmp_path / "out", venue, "holds a position")
    assert venue.size == FOREIGN


async def test_a_failed_instrument_read_is_refused_with_nothing_touched(
    tmp_path: Path, stacks: list[OfflineStack], monkeypatch: pytest.MonkeyPatch
) -> None:
    venue = _venue()
    order = venue.rest_foreign_order()

    async def unanswered(*_args: object, **_kwargs: object) -> None:
        raise ConnectionError("the public host did not answer")

    monkeypatch.setattr(venue, "get_public", unanswered)
    assert await run.run(_cfg(tmp_path / "out"), venue=venue) == 2
    _refused_and_untouched(tmp_path / "out", venue, "an error before the run was armed")
    assert venue.paths == []  # not even a read: the instrument comes first
    _untouched(venue, order, Decimal(0))


async def test_a_failed_key_check_is_refused_with_nothing_touched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def revoked(*args: Any, **kwargs: Any) -> OfflineStack:
        stack = await offline_stack(*args, **kwargs)
        stack.store.activate(UUID(stack.key_ref), status="revoked")  # M2 refuses to sign with it
        return stack

    monkeypatch.setattr(run, "offline_stack", revoked)
    venue = _venue()
    order = venue.rest_foreign_order()
    assert await run.run(_cfg(tmp_path / "out"), venue=venue) == 2
    _refused_and_untouched(tmp_path / "out", venue, "an error before the run was armed")
    _untouched(venue, order, Decimal(0))


async def test_limits_unset_refuses_before_anything_is_read(
    tmp_path: Path, stacks: list[OfflineStack], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def preflight_only(h: Harness, _cfg: RunConfig) -> dict[str, object]:
        await h.preflight()  # a mode that forgot the instrument read
        return {}

    monkeypatch.setitem(run.MODES, "cycles", preflight_only)
    venue = _venue()
    assert await run.run(_cfg(tmp_path / "out"), venue=venue) == 2
    _refused_and_untouched(tmp_path / "out", venue, "no size limits")
    assert venue.paths == []


# -- (b) armed: the shutdown flatten is scoped to the run's own state ------------------------


async def test_foreign_rows_survive_an_error_shutdown_and_the_runs_own_are_flattened(
    tmp_path: Path, stacks: list[OfflineStack], monkeypatch: pytest.MonkeyPatch
) -> None:
    venue = _venue()
    seeded: list[VenueOrder] = []

    async def boom(h: Harness, link: str) -> None:
        seeded.append(_foreign(venue))  # someone trades the account mid-run
        raise RuntimeError("mid-cycle")

    monkeypatch.setattr(cycles, "read_order", boom)
    assert await run.run(_cfg(tmp_path / "out"), venue=venue) == 1
    s = _summary(tmp_path / "out")
    shutdown = s["shutdown"]
    assert shutdown["cancelled"] == 1 and shutdown["own_net_qty"] == "0.001"
    assert shutdown["closed_qty"] == "0.001" and shutdown["flat"] is True
    assert shutdown["not_ours_left"] == {"open_orders": 1, "venue_position_less_own_net": "0.003"}
    [order] = seeded
    _untouched(venue, order, FOREIGN)
    own = [o for o in venue.orders.values() if o is not order]
    assert own and all(o.status not in ("New", "PartiallyFilled") for o in own)
    assert "/v5/order/cancel-all" not in venue.paths


async def test_foreign_rows_survive_a_normal_shutdown(
    tmp_path: Path, stacks: list[OfflineStack], monkeypatch: pytest.MonkeyPatch
) -> None:
    venue = _venue()
    seeded: list[VenueOrder] = []
    original = cycles.one_cycle

    async def then_trade(*args: Any, **kwargs: Any) -> str:
        outcome = await original(*args, **kwargs)
        if not seeded:
            seeded.append(_foreign(venue))  # between the run's two cycles
        return outcome

    monkeypatch.setattr(cycles, "one_cycle", then_trade)
    # Buys only: the venue's one-way position nets the run's fills with the foreign long, so a
    # sell of the run's would reduce that long, and undoing it would open (the README says so).
    assert await run.run(_cfg(tmp_path / "out", cycles=3, side="buy"), venue=venue) == 0
    s = _summary(tmp_path / "out")
    assert s["cycles"]["completed"] == 3 and "residual_flatten" not in s["cycles"]["actions"]
    assert s["shutdown"]["flat"] is True and s["shutdown"]["flatten_orders"] == 0
    [order] = seeded
    _untouched(venue, order, FOREIGN)
    assert "/v5/order/cancel-all" not in venue.paths


# -- R1S-04: the owner's flatten, scoped to the failed run -----------------------------------


async def _failed_run(
    tmp_path: Path, venue: CorpusVenue, account: UUID, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """A cycles run whose shutdown flatten failed: its entry rests part-filled, its position
    held (a venue outage at exit, say)."""

    async def boom(h: Harness, link: str) -> None:
        raise RuntimeError("mid-cycle")

    async def failed(_h: Harness) -> dict[str, object]:
        return {"flat": False, "errors": ["close:TransportError"]}

    with monkeypatch.context() as patch:
        patch.setattr(cycles, "read_order", boom)
        patch.setattr(Harness, "flatten", failed)
        out = tmp_path / "failed"
        assert await run.run(_cfg(out, account_id=account), venue=venue) == 1
    assert _summary(out)["shutdown"]["flat"] is False
    assert venue.size == Decimal("0.001")
    assert [o.status for o in venue.orders.values()] == ["PartiallyFilled"]
    return out


async def test_flatten_takes_the_failed_runs_scope_and_ends_it_flat(
    tmp_path: Path, stacks: list[OfflineStack], monkeypatch: pytest.MonkeyPatch
) -> None:
    venue, account = _venue(), uuid4()
    failed = await _failed_run(tmp_path, venue, account, monkeypatch)
    order = _foreign(venue)
    out = tmp_path / "flatten"
    cfg = RunConfig(mode="flatten", out=out, run_dir=failed, account_id=account)
    assert await run.run(cfg, venue=venue) == 0
    s = _summary(out)
    report = s["flatten"]
    assert report["flat"] is True and report["cancelled"] == 1
    assert (report["own_net_qty"], report["closed_qty"], report["flatten_orders"]) == (
        "0.001",
        "0.001",
        1,
    )
    assert s["shutdown"]["action"] == "the mode's own (summary.flatten)"
    assert s["outcome"] == "completed" and s["safety"]["openers"] == 0
    _untouched(venue, order, FOREIGN)
    assert all(
        o.status not in ("New", "PartiallyFilled") for o in venue.orders.values() if o is not order
    )
    failed_rows = _ledger(failed)
    assert [r["reduce_only"] for r in failed_rows] == [False]  # its one opener, before its send
    adopted = [r for r in _ledger(out) if r.get("adopted")]
    assert [r["link_digest"] for r in adopted] == [failed_rows[0]["link_digest"]]
    assert s["ledger"] == {"file": "intents.jsonl", "intents": 1, "adopted": 1, "orders": 2}


def _ledger(run_dir: Path) -> list[dict[str, Any]]:
    text = (run_dir / LEDGER).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


async def test_flatten_refuses_another_accounts_run_with_nothing_touched(
    tmp_path: Path, stacks: list[OfflineStack], monkeypatch: pytest.MonkeyPatch
) -> None:
    venue = _venue()
    failed = await _failed_run(tmp_path, venue, uuid4(), monkeypatch)
    venue.paths.clear()
    venue.creates.clear()
    out = tmp_path / "flatten"
    cfg = RunConfig(mode="flatten", out=out, run_dir=failed, account_id=uuid4())
    assert await run.run(cfg, venue=venue) == 2
    _refused_and_untouched(out, venue, "not the account of that run")
    assert venue.size == Decimal("0.001")


async def test_flatten_refuses_a_summary_with_no_scope(
    tmp_path: Path, stacks: list[OfflineStack]
) -> None:
    refused, account = tmp_path / "refused", uuid4()
    venue = _venue()
    venue.rest_foreign_order()
    assert await run.run(_cfg(refused, account_id=account), venue=venue) == 2  # no window
    for run_dir, reason in ((refused, "no run scope"), (tmp_path / "none", "no readable summary")):
        out = tmp_path / f"flatten-{run_dir.name}"
        cfg = RunConfig(mode="flatten", out=out, run_dir=run_dir, account_id=account)
        assert await run.run(cfg, venue=venue) == 2
        assert reason in _summary(out)["refused"]


async def test_the_armed_run_writes_its_scope_before_any_order(
    tmp_path: Path, stacks: list[OfflineStack], monkeypatch: pytest.MonkeyPatch
) -> None:
    """R1C-14: a run killed past its grace period still leaves its record and scope."""
    seen: list[dict[str, Any]] = []
    original = cycles.one_cycle

    async def look(h: Harness, *args: Any, **kwargs: Any) -> str:
        seen.append(_summary(h.outputs.directory))
        return await original(h, *args, **kwargs)

    monkeypatch.setattr(cycles, "one_cycle", look)
    assert await run.run(_cfg(tmp_path / "out", cycles=1), venue=_venue()) == 0
    [early] = seen
    assert early["provisional"] == "armed" and early["run_scope"]["window_start_ms"] > 0
    final = _summary(tmp_path / "out")
    assert "provisional" not in final and final["run_scope"] == early["run_scope"]
