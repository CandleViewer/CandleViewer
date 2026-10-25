# ruff: noqa: S101  (pytest asserts: the project's tests/** ignore does not reach spike/)
"""No row, no order (#843 A4 fold 3; the coordinator's ruling of 2026-10-25 11:46Z): each create's
scrubbed intent is in the run's ledger before the create is sent, a row not written sends no
create, and a kill between the two leaves the row and no order. The ledger is the run's own state
for the scoped flatten (ruling R1C-02 (b)): an order it does not list survives the flatten, as a
foreign order and a foreign position do, and `flatten` adopts a failed run's from its ledger."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from candleviewer.exchange.base.models import PlaceOrderRequest
from spike.oms_demo_path import cycles, run
from spike.oms_demo_path.config import RunConfig
from spike.oms_demo_path.harness import Harness
from spike.oms_demo_path.ledger import LEDGER
from spike.oms_demo_path.offline import Corpus, CorpusVenue, VenueOrder, default_corpus
from spike.oms_demo_path.outputs import write_file
from spike.oms_demo_path.safety import QtyLimits, Refused, digest
from spike.oms_demo_path.tests.test_modes import _Rig
from spike.oms_demo_path.tests.test_safety import guarded, opener
from spike.oms_demo_path.tests.test_scope import _failed_run, _refused_and_untouched

FOREIGN = Decimal("0.003")
CREATE = "/v5/order/create"


class _Killed(BaseException):
    """The process dying where it stands (SIGKILL, the OOM killer): nothing after it runs."""


def _venue() -> CorpusVenue:
    return CorpusVenue(Corpus(default_corpus()))


def _cfg(out: Path, **fields: Any) -> RunConfig:
    base: dict[str, Any] = {"mode": "cycles", "out": out, "cycles": 2, "min_hours": 0.0}
    return RunConfig(**(base | {"fill_wait_s": 0.2} | fields))


def _rows(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / LEDGER
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _refusing(_path: Path, _data: bytes, _append: bool) -> None:
    raise OSError("no space left on device")


async def test_each_create_is_in_the_ledger_scrubbed_before_the_venue_sees_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    venue, out = _venue(), tmp_path / "out"
    create = venue._order_create
    listed_first: list[bool] = []

    def seen(body: dict[str, Any], params: dict[str, str]) -> dict[str, Any]:
        handles = {row["link_digest"] for row in _rows(out)}
        listed_first.append(digest(str(body["orderLinkId"])) in handles)
        return create(body, params)

    monkeypatch.setattr(venue, "_order_create", seen)
    assert await run.run(_cfg(out), venue=venue) == 0
    assert len(venue.creates) == 4 and listed_first == [True] * 4  # 2 openers, 2 closes
    rows = _rows(out)
    for row, body in zip(rows, venue.creates, strict=True):
        assert row["link_digest"] == digest(body["orderLinkId"])
        assert re.fullmatch(r"link#\d+", row["order_link_id"])
        assert (row["side"], row["reduce_only"]) == (body["side"].lower(), body["reduceOnly"])
        assert Decimal(row["qty"]) == Decimal(body["qty"])
        if body["reduceOnly"]:
            assert row["price"] is None and row["stop_loss"] is None
        else:
            assert Decimal(row["price"]) == Decimal(body["price"])
            assert Decimal(row["stop_loss"]) == Decimal(body["stopLoss"])
    text = (out / LEDGER).read_text(encoding="utf-8")
    assert not [b["orderLinkId"] for b in venue.creates if b["orderLinkId"] in text]
    assert oct((out / LEDGER).stat().st_mode & 0o777) == "0o600"
    summary = dict(run.summary_of(out))
    assert summary["ledger"] == {"file": LEDGER, "intents": 4, "adopted": 0, "orders": 4}


async def test_a_kill_between_the_intent_and_the_send_leaves_the_intent_and_no_order(
    tmp_path: Path,
) -> None:
    """The real port over the corpus venue: the row is written, then the process dies."""
    rig = _Rig(tmp_path, _venue())
    h = rig.harness
    h.port.limits, qty = QtyLimits.of(await h.public.instrument(), multiple=2, max_multiple=2)

    def written_then_killed(path: Path, data: bytes, append: bool) -> None:
        write_file(path, data, append)
        raise _Killed

    h.ledger.write = written_then_killed
    link = h.links.new()
    ref = rig.venue.ref
    req = PlaceOrderRequest(
        account=h.account,
        symbol="BTCUSDT",
        side="buy",
        order_type="limit",
        qty=qty,
        price=ref - 600,
        order_link_id=link,
        stop_loss=ref - 1800,
    )
    with pytest.raises(_Killed):
        await h.port.place_order(req)
    assert rig.venue.creates == [] and CREATE not in rig.venue.paths  # no order
    [row] = _rows(tmp_path / "out")  # and its intent
    assert (row["order_link_id"], row["link_digest"]) == ("link#1", digest(link))
    assert (row["side"], row["qty"], row["reduce_only"]) == ("buy", "0.002", False)
    assert Decimal(row["stop_loss"]) == ref - 1800 and link not in json.dumps(row)


async def test_a_failed_intent_write_sends_no_create() -> None:
    guard, fake = guarded()
    assert guard.ledger is not None
    guard.ledger.write = _refusing
    with pytest.raises(Refused, match="no row, no order"):
        await guard.place_order(opener())
    assert fake.calls == [] and guard.openers == 0 and guard.ledger.intents == 0
    guard.ledger = None
    with pytest.raises(Refused, match="no intent ledger"):
        await guard.place_order(opener())
    assert fake.calls == []


async def test_a_run_whose_intent_write_fails_sends_no_create_and_ends_flat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    venue = _venue()
    original = cycles.one_cycle

    async def disk_full(h: Harness, *args: Any, **kwargs: Any) -> str:
        h.ledger.write = _refusing  # the disk refuses the first intent
        return await original(h, *args, **kwargs)

    monkeypatch.setattr(cycles, "one_cycle", disk_full)
    assert await run.run(_cfg(tmp_path / "out"), venue=venue) == 1
    s = dict(run.summary_of(tmp_path / "out"))
    assert s["error"] == "Refused" and s["outcome"] == "error"
    assert venue.creates == [] and CREATE not in venue.paths
    assert (s["shutdown"]["cancelled"], s["shutdown"]["flat"]) == (0, True)
    assert s["ledger"]["intents"] == 0 and not (tmp_path / "out" / LEDGER).exists()


async def test_the_shutdown_flatten_owns_what_the_ledger_lists_and_the_rest_survives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    venue = _venue()
    seeded: list[VenueOrder] = []

    async def boom(h: Harness, link: str) -> None:
        unlisted = venue.rest_foreign_order()
        unlisted.link = h.links.new()  # the run's own prefix, never sent by it: no row
        seeded.extend([venue.rest_foreign_order(), unlisted])  # and a manual order
        venue.hold_foreign_position(FOREIGN)
        raise RuntimeError("mid-cycle")

    monkeypatch.setattr(cycles, "read_order", boom)
    assert await run.run(_cfg(tmp_path / "out"), venue=venue) == 1
    shutdown = dict(run.summary_of(tmp_path / "out"))["shutdown"]
    assert (shutdown["cancelled"], shutdown["closed_qty"], shutdown["flat"]) == (1, "0.001", True)
    assert shutdown["not_ours_left"] == {"open_orders": 2, "venue_position_less_own_net": "0.003"}
    assert [(o.status, o.filled) for o in seeded] == [("New", Decimal(0))] * 2
    assert venue.size == FOREIGN
    own = [o for o in venue.orders.values() if o not in seeded]
    assert own and all(o.status not in ("New", "PartiallyFilled") for o in own)


async def test_flatten_refuses_a_failed_run_whose_ledger_is_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    venue, account = _venue(), uuid4()
    failed = await _failed_run(tmp_path, venue, account, monkeypatch)
    (failed / LEDGER).unlink()
    venue.paths.clear()
    venue.creates.clear()
    out = tmp_path / "flatten"
    cfg = RunConfig(mode="flatten", out=out, run_dir=failed, account_id=account)
    assert await run.run(cfg, venue=venue) == 2
    _refused_and_untouched(out, venue, "no readable intent ledger")
    assert venue.paths == [] and venue.size == Decimal("0.001")
