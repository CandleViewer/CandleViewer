"""E12-X02 observability (#452 "Observability"): each refusal of `/market/bars` and `/market/klines`
is counted and logged, with the offending value escaped and truncated, and an alert watches the
rejection and rebuild rates.

Since #452 F4a every refusal the handlers make is counted in `api_request_rejected_total{route,
reason}` (the ticket's `endpoint` label is `route`: the Semgrep allow-list has no `endpoint`) and in
`bars_endpoint_param_rejected_total{reason}`, and logged once as `market_request_refused`. A `limit`
outside 1..5000 is refused by FastAPI before the handler and is not counted (F4a-limit, NOT
COVERED); no alert rule names a `bars_*` series (F4b).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

import pytest
import yaml
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from tests.contract._market_world import KLINES_NOW_US, NOW, T0
from tests.security.bars.conftest import Stores
from tests.security.bars.test_caps_and_cost import DAY_US, bars, klines

F4A_LIMIT: Final = "#452 F4a: a `limit` refusal is FastAPI's 422, before the handler: not counted"
F4B: Final = "#452 findings row F4 (F4b): an alert on the bars rejection and rebuild rates"
_ALERTS: Final = Path(__file__).resolve().parents[5] / "infra" / "prometheus" / "alerts"
_PROBE: Final = "\x1b[31m" + "A" * 100


def _param_rejected(reason: str) -> float:
    return REGISTRY.get_sample_value("bars_endpoint_param_rejected_total", {"reason": reason}) or 0


def _rejected(endpoint: str) -> float:
    """`api_request_rejected_total` for the route `endpoint`, summed over its reasons."""
    return sum(
        s.value
        for metric in REGISTRY.collect()
        if metric.name == "api_request_rejected"
        for s in metric.samples
        if s.name.endswith("_total") and s.labels.get("route") == endpoint
    )


def test_observability_param_refusal_is_counted_by_reason(stores: Stores) -> None:
    before = _param_rejected("out_of_range")
    stores.get("getBars", bars("tick", "1", T0, NOW))
    assert _param_rejected("out_of_range") == before + 1


_REFUSALS: Final = [
    ("bars", "getBars", bars("time", "D", NOW - 401 * DAY_US, NOW)),
    ("bars", "getBars", {**bars("tick", "100", T0, NOW), "from": "not-a-time"}),
    ("bars", "getBars", {**bars("tick", "100", T0, NOW), "cursor": "e30"}),
    ("bars", "getBars", {**bars("tick", "100", T0, NOW), "symbol": "NOPEUSDT"}),
    ("klines", "getKlines", klines(KLINES_NOW_US - 401 * DAY_US, KLINES_NOW_US)),
]
#: `limit` is declared `ge=1, le=MAX_LIMIT` on the Query, so FastAPI refuses it first.
_LIMIT_REFUSALS: Final = [
    pytest.param("bars", "getBars", {**bars("tick", "100", T0, NOW), "limit": 5_001}),
    pytest.param("klines", "getKlines", {**klines(T0, KLINES_NOW_US), "limit": 5_001}),
]


@pytest.mark.parametrize(
    ("endpoint", "op", "query"),
    [
        *_REFUSALS,
        *[
            pytest.param(*p.values, marks=pytest.mark.xfail(strict=True, raises=AssertionError,
                                                              reason=F4A_LIMIT))
            for p in _LIMIT_REFUSALS
        ],
    ],
)  # fmt: skip
def test_observability_every_refusal_path_is_counted(
    stores: Stores, endpoint: str, op: str, query: dict[str, object]
) -> None:
    before = _rejected(endpoint)
    assert stores.get(op, query).status_code in (400, 422)
    assert _rejected(endpoint) == before + 1


def test_observability_refusal_is_logged_with_the_value_escaped_and_truncated(
    stores: Stores,
) -> None:
    with capture_logs() as events:
        stores.get("getBars", {**bars("tick", "100", T0, NOW), "param": _PROBE})
    refusals = [e for e in events if e.get("event") == "market_request_refused"]
    assert len(refusals) == 1, events
    logged = " ".join(str(v) for v in refusals[0].values())
    assert "\x1b" not in logged and "A" * 33 not in logged
    everything = " ".join(
        str(v) for e in events for v in e.values()
    )  # a second event must not echo the probe either
    assert "\x1b" not in everything and "A" * 33 not in everything


def _rules() -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for path in sorted(_ALERTS.glob("*.yml")):
        for group in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("groups", []):
            rules += group.get("rules", [])
    return rules


def test_observability_alert_rules_are_read() -> None:
    assert len(_rules()) > 10  # the meta-test below is not vacuous: rules are found and parsed


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=F4B)
@pytest.mark.parametrize(
    "series", ["api_request_rejected_total|bars_endpoint_param_rejected_total", "bars_rebuild_"]
)
def test_observability_an_alert_watches_the_rate(series: str) -> None:
    names = series.split("|")
    assert any(name in str(r.get("expr", "")) for r in _rules() for name in names)
