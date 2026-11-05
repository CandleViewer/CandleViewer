"""E35-T15 PR 2 (#5745): `24` §7.2.2, the metric source register, pinned against the code.

The register is the doc every epic reads to learn which metric has a live source; this test fails
the moment the registry, the bridge's producers or the trigger catalogue move without it.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from candleviewer.bus.bus import Bus
from candleviewer.exchange.bybit.public_ws import stream_for_topic
from candleviewer.rules.manager import EvaluableRule
from candleviewer.rules.vocabulary import default_registry
from candleviewer.rules.vocabulary.catalogue import TRIGGERS
from candleviewer.rules_producers_wiring import BarFieldProducer, build_bridge

DOC = Path(__file__).resolve().parents[4] / "docs" / "plan" / "24-internal-schemas.md"
GOLDEN = (
    Path(__file__).resolve().parents[2]
    / "candleviewer" / "rules" / "vocabulary" / "metric_names.golden.txt"
)  # fmt: skip
BLOCKED = "blocked by #1204 Part B's binding rule"
_ROW = re.compile(r"^\| `([a-z_0-9]+)` +\|(.*)\|$")


def _section() -> str:
    text = DOC.read_text(encoding="utf-8")
    start = text.index("#### 7.2.2 ")
    return text[start : text.index("\n### 7.3 ", start)]


def _rows() -> list[tuple[str, list[str]]]:
    """``(name, [scope, status, owner, cadence])`` per backticked first cell, both tables."""
    rows = []
    for line in _section().splitlines():
        if (m := _ROW.match(line.strip())) is not None:
            rows.append((m.group(1), [c.strip() for c in m.group(2).split("|")]))
    return rows


def _metric_rows() -> dict[str, list[str]]:
    rows = [(n, cells) for n, cells in _rows() if n not in TRIGGERS]
    counts = Counter(n for n, _ in rows)
    assert [n for n, c in counts.items() if c > 1] == []  # each metric exactly once
    return dict(rows)


async def _none() -> list[EvaluableRule]:
    return []


def _bound_set() -> frozenset[str]:
    bars = BarFieldProducer(lambda: None, lambda _s: None)
    bridge = build_bridge(
        Bus(), "demo", _none, bars=bars, books=lambda: None, topics=stream_for_topic
    )
    return bridge.bound


def test_the_register_cannot_drift_from_the_registry() -> None:
    """Scenario: The register cannot drift from the registry."""
    rows = _metric_rows()
    registry = {d.name: d.scope for d in default_registry()}
    golden = set(GOLDEN.read_text(encoding="utf-8").split())
    assert set(rows) == set(registry) == golden and len(rows) == 105
    bound = {n for n, (_scope, status, *_) in rows.items() if status == "`bound`"}
    assert bound == _bound_set()
    triggers = [n for n, _ in _rows() if n in TRIGGERS]
    assert sorted(triggers) == sorted(TRIGGERS) and len(triggers) == 13


def test_register_statuses_match_the_ticket_inventory() -> None:
    statuses = Counter(cells[1] for cells in _metric_rows().values())
    assert statuses == {"`bound`": 13, "`source`": 34, "`gap`": 58}


def test_register_scope_column_is_the_registry_scope() -> None:
    registry = {d.name: d.scope for d in default_registry()}
    assert {n: cells[0] for n, cells in _metric_rows().items()} == registry


def test_register_account_and_position_rows_are_blocked_by_the_binding_rule() -> None:
    for name, (scope, status, owner, _cadence) in _metric_rows().items():
        market = scope in ("symbol", "global")
        assert (BLOCKED in owner) is not market, name
        assert market or status != "`bound`", name


def test_register_trigger_table_names_a_producer_for_the_three_wired_triggers_only() -> None:
    wired = {n for n, cells in _rows() if n in TRIGGERS and cells[0] != "none"}
    assert wired == {"on_price_update", "on_bar_close", "on_book_update"}
