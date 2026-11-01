"""E27-Q03 (#892) harness self-tests: no network, no stack, run in the ordinary PR lane (BQ-11).

BQ-nn markers here: RULED (orchestrator, 2026-11-01, #892 ruling of record 6555033109).

Pins the load-target guard (Python and k6 copies agree), the switch argument rule of the chaos
helper, the soak sampler's slope fit and the request-log check on small tables.
"""

from __future__ import annotations

import re

import pytest

from tests.chaos.accounts._e27_stack import REPO, _validated, load_module

guard = load_module("e27_guard_t", "tests/load/accounts/guard.py")
sampler = load_module("e27_sampler_t", "tests/load/accounts/soak_sampler.py")
logcheck = load_module("e27_logcheck_t", "tests/load/accounts/request_log_check.py")

ACCEPT = [
    "http://127.0.0.1:8000",
    "http://localhost:8000/",
    "http://api:8000",
    "http://[::1]:8000",
]
REFUSE = [
    "https://api.bybit.com", "http://api-demo.bybit.com:8000", "http://stream.bytick.com",
    "https://127.0.0.1:8000", "http://evil.example", "http://127.0.0.1.evil.example",
    "http://user:pw@127.0.0.1:8000", "http://127.0.0.1:8000/v5", "ftp://localhost", "not a url",
]  # fmt: skip


@pytest.mark.parametrize("url", ACCEPT)
def test_guard_accepts_loopback_and_the_compose_service(url: str) -> None:
    assert guard.check_target(url) == url.rstrip("/")


@pytest.mark.parametrize("url", REFUSE)
def test_guard_refuses_everything_else_without_echoing_the_url(url: str) -> None:
    with pytest.raises(guard.TargetRefused) as err:
        guard.check_target(url)
    assert url not in str(err.value)


def test_k6_guard_allows_the_same_hosts_as_the_python_guard() -> None:
    src = (REPO / "tests/load/k6/accounts/lib/guard.js").read_text()
    js = re.search(r"const ALLOWED = /(.+)/;", src)
    assert js, "the k6 guard no longer defines ALLOWED"
    pattern = re.compile(js.group(1).replace("\\/", "/"))
    for url in ACCEPT:
        assert pattern.match(url.rstrip("/")), url
    for url in REFUSE:
        assert not pattern.match(url.rstrip("/")), url


BAD_SWITCH = [
    ("fixture-compliant-0001; rm", "compliant"),
    ("fixture-x-1", "ok"),
    ("fixture-compliant-0001", "a b"),
    ("fixture-compliant-0001", "../x"),
]


@pytest.mark.parametrize(("key", "scenario"), BAD_SWITCH)
def test_switch_refuses_anything_but_a_pack_key_and_a_scenario_name(
    key: str, scenario: str
) -> None:
    with pytest.raises(ValueError):
        _validated(key, scenario)


def test_theil_sen_reads_a_flat_series_as_flat_and_a_rising_one_as_rising() -> None:
    xs = [float(i * 60) for i in range(120)]
    assert sampler.theil_sen(xs, [100.0] * 120) == 0.0
    assert sampler.theil_sen(xs, [100.0 + i for i in range(120)]) == pytest.approx(1 / 60)


def _line(
    ts: str,
    key: str = "fixture-compliant-0001",
    path: str = "/v5/account/wallet-balance",
) -> dict[str, str]:
    return {
        "ts": ts,
        "method": "GET",
        "path": path,
        "outcome": "served",
        "signing_key_id": key,
    }


def test_cache_check_passes_one_read_a_minute_and_fails_two_in_a_window() -> None:
    ok = [_line(f"2026-10-16T09:{m:02d}:00+00:00") for m in range(0, 6)]
    assert logcheck.check_cache(ok, 60.0, 2) == []
    bad = [*ok, _line("2026-10-16T09:03:20+00:00")]
    assert logcheck.check_cache(bad, 60.0, 2) != []


def test_burst_check_refuses_an_order_call_and_a_key_over_its_cap() -> None:
    rows = [_line("2026-10-16T09:00:01+00:00", path="/v5/order/create") | {"method": "POST"}]
    t0, t1 = 1792141200.0, 1792141260.0  # 2026-10-16T09:00:00Z .. 09:01:00Z
    assert any("order call" in m for m in logcheck.check_burst(rows, t0, t1, 5))
    many = [_line("2026-10-16T09:00:01+00:00")] * 6
    assert any("calls in the burst" in m for m in logcheck.check_burst(many, t0, t1, 5))
