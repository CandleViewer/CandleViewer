"""E22-X02 (#756) ticket cases 1 and 2 on REST (model AC1, AC2, AC8; D14, D16; SR-E22-01/02/04):
an enormous window, `limit` past its bounds, an over-long cursor and out-of-range cluster
options on `GET /market/trades` are refused in the `22` problem shape before the tape is read
("no query" reads "no tape read": the route serves the in-memory hot tape), and nothing is
clamped. The legs `main`'s unit tests already hold are cited in the catalogue, not repeated."""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.orderflow.bigtrade_metrics import bigtrade_range_rejected_total
from tests.security.bigtrade._app import client, recorded_tape


def _rejected() -> float:
    return float(bigtrade_range_rejected_total.labels("trades")._value.get())


def test_ac1_a_window_from_the_epoch_is_400_counted_and_reads_nothing() -> None:
    tape = recorded_tape()
    before = _rejected()
    params = {"symbol": "BTCUSDT", "from": "1970-01-01T00:00:00Z", "to": "2026-11-04T00:00:00Z"}
    r = client(tape).get("/market/trades", params=params)
    assert (r.status_code, r.json()["code"]) == (400, "invalid_time_range")
    assert _rejected() - before == 1
    assert tape.acquired == []  # no tape read, no demand taken


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"limit": 0}, "query.limit"),
        ({"limit": -1}, "query.limit"),
        ({"limit": "1.5"}, "query.limit"),
        ({"cursor": "a" * 513}, "query.cursor"),
        ({"cluster_window_ms": 999_999}, "query.cluster_window_ms"),
        ({"cluster_window_ms": -1}, "query.cluster_window_ms"),
        ({"cluster_window_ms": "2.5"}, "query.cluster_window_ms"),
        ({"cluster_tolerance_ticks": 999}, "query.cluster_tolerance_ticks"),
        ({"cluster_tolerance_ticks": -1}, "query.cluster_tolerance_ticks"),
        ({"cluster_tolerance_ticks": "x"}, "query.cluster_tolerance_ticks"),
    ],
)
def test_ac2_ac8_an_out_of_schema_parameter_is_422_naming_it_and_reads_nothing(
    params: dict[str, Any], field: str
) -> None:
    tape = recorded_tape()
    r = client(tape).get("/market/trades", params={"symbol": "BTCUSDT", **params})
    body = r.json()
    assert (r.status_code, body["code"]) == (422, "validation_failed")
    assert [e["field"] for e in body["errors"]] == [field]
    assert "items" not in body  # refused, never clamped to the bound and served
    assert tape.acquired == []


def test_ac2_a_cursor_at_its_length_bound_is_not_a_validation_refusal() -> None:
    params = {"symbol": "BTCUSDT", "cursor": "a" * 512}
    r = client(recorded_tape()).get("/market/trades", params=params)
    assert r.status_code == 400  # not `422`: the length is allowed; the text does not decode
