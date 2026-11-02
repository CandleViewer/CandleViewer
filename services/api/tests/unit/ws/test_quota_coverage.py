"""E21-X02 (#652): the quota is enforced at the gateway for every topic of the catalogue (the
ticket's technical note): a family registered in `topics.FAMILIES` without an entry in the quota's
weight table, 0 included, fails here, and a lookup of a family the table lacks raises, never reads
as a weight of 0."""

from __future__ import annotations

import pytest

from candleviewer.ws import quota
from candleviewer.ws.quota import FREE, WEIGHTS, charge_of
from candleviewer.ws.topics import FAMILIES, parse_topic


def test_every_catalogue_family_has_an_explicit_weight() -> None:
    assert sorted(WEIGHTS) == sorted(FAMILIES)
    weighed = {name for name, fn in WEIGHTS.items() if fn is not quota._free}
    assert weighed == {"book", "heatmap"}  # every other family weighs 0, bounded by its own caps


def test_a_family_with_no_weight_entry_fails_instead_of_weighing_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topic = parse_topic("trades.BTCUSDT")
    assert charge_of(topic, {"throttle_ms": 100}) == FREE
    monkeypatch.delitem(quota.WEIGHTS, "trades")
    with pytest.raises(KeyError, match="trades"):
        charge_of(topic, {"throttle_ms": 100})
