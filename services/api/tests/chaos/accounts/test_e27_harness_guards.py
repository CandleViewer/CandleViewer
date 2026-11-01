"""E27-Q03 (#892) harness self-tests: no network, no stack, run in the ordinary PR lane (BQ-11).

BQ-nn markers here: RULED (orchestrator, 2026-11-01, #892 ruling of record 6555033109).

Pins the load-target guard (Python and k6 copies agree, and the allow-list itself), the switch
argument rule of the chaos helper, the soak sampler's slope fit and judge, the request-log check on
small tables, and every number the scripts gate on against its documented source (06, 23, the
plan's PROPOSED rows, the pack manifest). The k6 numbers live in `lib/thresholds.js`, which imports
nothing from k6, so node runs it here; node is required, never skipped.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
from pathlib import Path

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
    "http://LOCALHOST:8000",  # host and scheme compare without case, in both guards
    "HTTP://API:8000",
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


#: BQ-11: loopback and the compose service name, and nothing else.
ALLOW_LIST = {"127.0.0.1", "localhost", "::1", "api"}


def _k6_allowed() -> re.Match[str]:
    src = (REPO / "tests/load/k6/accounts/lib/guard.js").read_text()
    js = re.search(r"const ALLOWED = /(.+)/i;", src)
    assert js, "the k6 guard no longer defines ALLOWED (case-insensitive)"
    return js


def test_k6_guard_allows_the_same_hosts_as_the_python_guard() -> None:
    pattern = re.compile(_k6_allowed().group(1).replace("\\/", "/"), re.IGNORECASE)
    for url in ACCEPT:
        assert pattern.match(url.rstrip("/")), url
    for url in REFUSE:
        assert not pattern.match(url.rstrip("/")), url


def test_both_guards_hold_exactly_the_ruled_allow_list() -> None:
    assert guard.ALLOWED_HOSTS == ALLOW_LIST
    hosts = re.fullmatch(r"\^http:\\/\\/\((.+)\)\(:\\d\{1,5\}\)\?\$", _k6_allowed().group(1))
    assert hosts, "the k6 ALLOWED regex changed shape: update this parse"
    k6 = {h.replace("\\", "").strip("[]") for h in hosts.group(1).split("|")}
    assert k6 == ALLOW_LIST


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


T0, T1 = 1792141200.0, 1792141260.0  # 2026-10-16T09:00:00Z .. 09:01:00Z
IN_WINDOW = "2026-10-16T09:00:01+00:00"


def test_burst_check_refuses_an_order_call_and_a_key_over_its_cap() -> None:
    rows = [_line(IN_WINDOW, path="/v5/order/create") | {"method": "POST"}]
    assert any("non-GET" in m for m in logcheck.check_burst(rows, T0, T1, 5))
    many = [_line(IN_WINDOW)] * 6
    assert any("calls in the burst" in m for m in logcheck.check_burst(many, T0, T1, 5))
    assert logcheck.check_burst([_line(IN_WINDOW)] * 5, T0, T1, 5) == []


@pytest.mark.parametrize("path", ["/v5/position/set-leverage", "/v5/account/set-margin-mode"])
def test_burst_check_refuses_a_signed_non_get_call_to_any_path(path: str) -> None:
    rows = [_line(IN_WINDOW, path=path) | {"method": "POST"}]
    assert logcheck.check_burst(rows, T0, T1, 5) == [
        f"a non-GET call reached the exchange during the burst: POST {path}"
    ]


@pytest.mark.parametrize("path", ["/v5/order/realtime", "/v5/asset/transfer/query-account-coin"])
def test_burst_check_refuses_an_order_or_fund_path_even_as_a_get(path: str) -> None:
    rows = [_line(IN_WINDOW, path=path)]
    assert logcheck.check_burst(rows, T0, T1, 5) == [
        f"an order or fund path was called during the burst: GET {path}"
    ]


def test_log_checks_never_pass_on_nothing_to_judge() -> None:
    assert logcheck.check_cache([], 60.0, 2) != []
    unsigned = [_line(IN_WINDOW) | {"signing_key_id": None}]
    assert logcheck.check_cache(unsigned, 60.0, 2) != []
    assert logcheck.check_burst([], T0, T1, 5) != []
    outside = [_line("2026-10-16T09:05:00+00:00")]
    assert logcheck.check_burst(outside, T0, T1, 5) != []


@pytest.mark.parametrize("mode", [["cache"], ["burst", "--t0", IN_WINDOW, "--t1", IN_WINDOW]])
def test_log_check_exits_unusable_on_an_empty_log(tmp_path: Path, mode: list[str]) -> None:
    log = tmp_path / "requests.jsonl"
    log.write_text("")
    extra = ["--per-key-max", "5"] if mode[0] == "burst" else []
    assert logcheck.main([mode[0], str(log), *mode[1:], *extra]) == 2


# -- the soak judge ---------------------------------------------------------------------------
def _soak(
    path: Path,
    rss: list[float],
    tasks: bool = True,
    health: str = "state=healthy",
    step_s: float = 60.0,
) -> Path:
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["t_s", "rss_bytes", "open_fds", "connections", "tasks", "health"])
        for i, r in enumerate(rss):
            w.writerow([i * step_s, r, 40, 5, 300 if tasks else "", health])
    return path


def test_soak_judge_passes_a_flat_run(tmp_path: Path) -> None:
    flat = _soak(tmp_path / "s.csv", [200e6] * 120)
    assert sampler.main(["judge", "--csv", str(flat), "--expect", "compliant=healthy"]) == 0


def test_soak_judge_fails_rising_memory(tmp_path: Path) -> None:
    rising = _soak(tmp_path / "s.csv", [200e6 + i * 1e6 for i in range(120)])  # 60 MB/h
    assert sampler.main(["judge", "--csv", str(rising), "--expect", "compliant=healthy"]) == 1


def test_soak_judge_fails_an_empty_task_column(tmp_path: Path) -> None:
    blind = _soak(tmp_path / "s.csv", [200e6] * 120, tasks=False)
    assert sampler.main(["judge", "--csv", str(blind), "--expect", "compliant=healthy"]) == 1


def test_soak_judge_fails_a_wrong_end_state(tmp_path: Path) -> None:
    red = _soak(tmp_path / "s.csv", [200e6] * 120, health="state=down")
    assert sampler.main(["judge", "--csv", str(red), "--expect", "compliant=healthy"]) == 1


def test_soak_judge_refuses_a_run_with_no_expectation(tmp_path: Path) -> None:
    flat = _soak(tmp_path / "s.csv", [200e6] * 120)
    with pytest.raises(SystemExit) as refused:
        sampler.main(["judge", "--csv", str(flat)])
    assert refused.value.code == 2


def test_soak_judge_fits_only_the_last_12_hours(tmp_path: Path) -> None:
    # 24 h every 6 min: a 100 MB/h rise in the first 12 h, flat after; the fit sees the plateau
    rss = [100e6 + min(i, 120) * 10e6 for i in range(240)]
    run = _soak(tmp_path / "s.csv", rss, step_s=360.0)
    assert sampler.main(["judge", "--csv", str(run), "--expect", "compliant=healthy"]) == 0


# -- every gated number against its documented source ------------------------------------------
PLAN = (REPO / "qa/plans/e27/chaos.md").read_text()
DOC_06 = (REPO / "docs/plan/06-performance-and-load-standard.md").read_text().splitlines()
DOC_23 = (REPO / "docs/plan/23-ws-protocol.md").read_text().splitlines()
THRESHOLDS = REPO / "tests/load/k6/accounts/lib/thresholds.js"


def _node(body: str) -> str:
    node = shutil.which("node")
    assert node, "node is required: the k6 threshold module is checked with it (never skipped)"
    script = f"import * as t from {json.dumps(THRESHOLDS.as_uri())};\n{body}"
    done = subprocess.run(  # noqa: S603 - fixed argv, a script built from constants here
        [node, "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def _k6() -> dict[str, object]:
    out = _node(
        "console.log(JSON.stringify({read: t.READ_P95_MS, tol: t.PROBE_TOLERANCE,"
        " throttle: t.WALLET_THROTTLE_MS, slack: t.WALLET_THROTTLE_TOL_MS,"
        " period: t.COMPLIANT_WALLET_PERIOD_MS, floor: t.walletFloor(),"
        " pacing: t.walletPacing(t.COMPLIANT_WALLET_PERIOD_MS),"
        " exercised: [t.throttleExercised(5000), t.throttleExercised(400)],"
        " probe: t.probeThreshold('120')}))"
    )
    return dict(json.loads(out))


def test_ruled_numbers_match_06_and_23() -> None:
    k6 = _k6()
    assert k6["tol"] == 1.05 and "by **more than 5%**" in DOC_06[178]  # 06 line 179, section 7.4
    assert k6["read"] == 150 and "<150ms p95 for read endpoints" in DOC_06[36]  # 06 row 13
    assert k6["throttle"] == 500 and "`wallet`" in DOC_23[860] and "500 ms" in DOC_23[860]
    assert k6["probe"] == "p(95)<=126"


def test_wallet_gates_follow_the_compliant_manifest_period() -> None:
    k6 = _k6()
    manifest = json.loads((REPO / "packages/fixtures/accounts/compliant/manifest.json").read_text())
    periods = [
        step["every_ms"]
        for step in _steps(manifest)
        if step.get("payload") == "_base/ws_wallet.json" and "every_ms" in step
    ]
    assert periods == [k6["period"]] == [5000]
    assert k6["floor"] == ["p(5)>=450"]
    assert k6["pacing"] == ["p(50)>=4500", "p(50)<=5500"]
    assert k6["exercised"] == [False, True]  # a 5 s stream cannot exercise the throttle (F9)


def _steps(node: object) -> list[dict[str, object]]:
    """Every dict under `node` that names a payload: the manifest's scripted WS steps."""
    if isinstance(node, dict):
        own = [node] if "payload" in node else []
        return own + [s for v in node.values() for s in _steps(v)]
    if isinstance(node, list):
        return [s for v in node for s in _steps(v)]
    return []


@pytest.mark.parametrize("raw", [None, "", "  ", "abc", "0", "-5", "Infinity"])
def test_probe_gate_refuses_a_missing_or_bad_baseline(raw: str | None) -> None:
    arg = "undefined" if raw is None else json.dumps(raw)
    out = _node(f"try {{ t.probeThreshold({arg}); console.log('ran'); }} catch (e) {{"
                " console.log('refused'); }")  # fmt: skip
    assert out == "refused"


def test_the_burst_script_has_no_baseline_fallback() -> None:
    src = (REPO / "tests/load/k6/accounts/key_verify_burst.js").read_text()
    assert "probeThreshold(__ENV.CV_E27_PROBE_BASELINE_P95_MS)" in src
    assert "CV_E27_PROBE_BASELINE_P95_MS ||" not in src and "1.05" not in src


def test_proposed_numbers_match_the_plan_and_say_proposed() -> None:
    k6 = _k6()
    band = sampler.BAND_PER_H
    assert band == {"rss_bytes": 512 * 1024, "open_fds": 0.5, "connections": 0.5, "tasks": 0.5}
    assert "PROPOSED bands (512 KiB/h, 0.5/h, 0.5/h, 0.5/h;" in PLAN
    assert k6["slack"] == 50 and "tolerance 50 ms, PROPOSED" in PLAN
    assert sampler.MIN_SAMPLES == 100 and sampler.WINDOW_S == 12 * 3600
    assert "last 12h ≤0.18MB/h over ≥100 samples" in DOC_06[212]  # 06 line 213
