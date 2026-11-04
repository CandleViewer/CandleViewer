"""E29-Q03 (#977): the stdlib halves of the tests/load/k6/oms kit.

The k6 script runs against the account fixture stack, never on a pull request. These pin the
parts that need neither k6 nor a stack: the ack matcher and the histogram reading (lib/frames.js),
the budget numbers and the calibration profile (lib/thresholds.js) and the target guard
(lib/guard.js), each run with node; and the +5 % gate (compare_baseline.py).
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "tests" / "load" / "k6" / "oms"
STANDARD = ROOT / "docs" / "plan" / "06-performance-and-load-standard.md"


def _cmp() -> Any:
    spec = importlib.util.spec_from_file_location("e29_cmp", KIT / "compare_baseline.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _js(lib: str, *exprs: str, env: dict[str, str] | None = None, pre: str = "") -> Any:
    """Each expression's value, or {"error": message} for one that throws."""
    node = shutil.which("node")
    assert node, "node is required: the k6 lib modules are checked with it (never skipped)"
    run = ", ".join(
        f"(() => {{ try {{ return {e}; }} catch (x) {{ return {{error: x.message}}; }} }})()"
        for e in exprs
    )
    script = (
        f"globalThis.__ENV = {json.dumps(env or {})};\n"
        f"const f = await import({json.dumps((KIT / 'lib' / lib).as_uri())});\n"
        f"{pre}\nconsole.log(JSON.stringify([{run}]));"
    )
    out = subprocess.run(
        [node, "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)


def _d(*items: Any, ch: str = "orders", t: str = "d") -> str:
    return json.dumps({"t": t, "ch": ch, "s": 2, "p": {"orders": list(items)}})


def test_only_an_ack_or_reject_delta_stops_the_timer() -> None:
    ack = {"order_link_id": "a", "change": "ack"}
    others = [{"order_link_id": "c", "change": k} for k in ("created", "submitted", "fill")]
    got = _js(
        "frames.js",
        f"f.acksOf({_d(ack, {'order_link_id': 'b', 'change': 'reject'})}, 7)",
        f"f.acksOf({_d(*others)}, 7)",
        f"f.acksOf({_d(ack, t='snap')}, 7)",
        f"f.acksOf({_d(ack, ch='executions')}, 7)",
        f"f.acksOf({_d({'change': 'ack'})}, 7)",
    )
    pair = [
        {"link": "a", "kind": "ack", "at": 7},
        {"link": "b", "kind": "reject", "at": 7},
    ]
    assert got == [pair, [], [], [], []]


def test_the_202_names_the_order_alone_or_in_its_entry_leg() -> None:
    leg = {"legs": [{"order_details": [{"order_link_id": "y"}]}]}
    bodies = [{"order": {"order_link_id": "x"}}, {"order": None, "trade_group": leg},
              {"order": None, "trade_group": {"legs": []}}, None]  # fmt: skip
    assert _js("frames.js", *(f"f.linkOf({json.dumps(b)})" for b in bodies)) == [
        "x", "y", None, None,
    ]  # fmt: skip


def test_the_matcher_pairs_either_order_expires_the_lost_and_bounds_the_unclaimed() -> None:
    pre = """const mt = f.newMatcher();
    const r = [f.addAck(mt, {link: "a", kind: "ack", at: 140}), f.addSent(mt, "a", 100),
      f.addSent(mt, "b", 200), f.addAck(mt, {link: "b", kind: "reject", at: 260})];
    f.addAck(mt, {link: "b", kind: "ack", at: 270}); f.addSent(mt, "c", 300);
    const big = f.newMatcher();
    for (let i = 0; i <= f.MAX_SEEN; i++) f.addAck(big, {link: `l${i}`, kind: "ack", at: i});"""
    got = _js(
        "frames.js",
        "r",
        "[mt.seen.size, f.expire(mt, 5301, 5000), mt.sent.size]",
        "[big.seen.size === f.MAX_SEEN, big.seen.has('l0')]",
        "f.uuidV4(new Uint8Array(16).fill(255))",
        pre=pre,
    )
    assert got == [
        [None, {"ms": 40, "kind": "ack"}, None, {"ms": 60, "kind": "reject"}],
        [1, 1, 0],
        [True, False],
        "ffffffff-ffff-4fff-bfff-ffffffffffff",
    ]


METRICS = """# TYPE order_submit_seconds histogram
order_submit_seconds_bucket{transport="rest",le="0.05"} 80
order_submit_seconds_bucket{transport="rest",le="0.1"} 95
order_submit_seconds_bucket{transport="rest",le="+Inf"} 100
order_submit_seconds_bucket{transport="ws",le="0.05"} 0
order_submit_seconds_bucket{transport="ws",le="+Inf"} 0
order_submit_seconds_count{transport="rest"} 100
"""


def test_the_histogram_is_summed_over_labels_and_read_as_a_run_delta() -> None:
    before = METRICS.replace(" 80\n", " 40\n").replace(" 95\n", " 45\n").replace(" 100", " 50")
    pre = f"""const a = f.histogram({json.dumps(before)}, "order_submit_seconds");
    const b = f.histogram({json.dumps(METRICS)}, "order_submit_seconds");
    const d = f.delta(a, b);"""
    got = _js(
        "frames.js",
        "d.map(([le, c]) => [String(le), c])",
        "f.quantile(0.95, d)",
        'f.histogram("x 1", "order_submit_seconds")',
        "f.quantile(0.95, f.delta(b, b))",
        "f.quantile(0.99, [[0.05, 1], [0.1, 2], [Infinity, 10]])",
        pre=pre,
    )
    assert got[0] == [["0.05", 40], ["0.1", 50], ["Infinity", 50]]
    # rank 47.5 of 50 lies in (0.05, 0.1]: 0.05 + 0.05 * 7.5 / 10, linear in the bucket
    assert got[1] == pytest.approx(0.0875)
    assert got[2:] == [None, None, 0.1]  # past the last bound: that bound  # fmt: skip


def test_the_budget_numbers_are_the_standards() -> None:
    lines = STANDARD.read_text(encoding="utf-8").splitlines()
    (row,) = [x for x in lines if x.startswith("| 4 | Order submit")]
    assert "p95 < 300ms (demo/paper" in row
    sec = next(i for i, x in enumerate(lines) if x.startswith("### 5.2 Order submit"))
    (added,) = [x for x in lines[sec:] if "backend-added overhead" in x and "≤50ms" in x][:1]
    assert "Demo/paper" in added
    got = _js("thresholds.js", "[f.SUBMIT_ACK_P95_MS, f.BACKEND_ADDED_P95_MS]")
    assert got == [[300, 50]]


def test_the_profiles_hold_budget_4_or_the_calibration_floor() -> None:
    off, on, cal, low = _js(
        "thresholds.js",
        'f.thresholdsFor("gate", 40, false)',
        'f.thresholdsFor("gate", 40, true)',
        'f.thresholdsFor("calibrate", 100, true)',
        'f.thresholdsFor("calibrate", 99, false)',
    )
    assert off["oms_submit_ack_ms"] == ["p(95)<300"] and "oms_backend_added_p95_ms" not in off
    assert on["oms_backend_added_p95_ms"] == ["value<=50"]  # opt-in until the metric is live
    assert on["oms_backend_added_missing"] == ["count==0"]  # a missing measurement fails the gate
    assert "oms_backend_added_missing" not in off
    assert cal["oms_submit_ack_ms"] == ["p(95)>=100"] and "oms_backend_added_p95_ms" not in cal
    assert "at least 100" in low["error"]
    for t in (off, on, cal):
        assert t["oms_ack_missing"] == t["oms_submit_refused"] == ["count==0"]


def test_the_pack_delay_profile_and_backend_figure_parse() -> None:
    bad = ["", "-1", "1.5", "10001", "x", None]
    got = _js(
        "thresholds.js",
        *(f"f.packDelayMs({json.dumps(b)})" for b in bad),
        'f.profileOf("Gate")',
        '[f.profileOf(undefined), f.profileOf("calibrate"), f.packDelayMs(" 40 ")]',
    )
    assert all("CV_E29_PACK_DELAY_MS" in g["error"] for g in got[: len(bad)])
    assert "CV_E29_PROFILE" in got[len(bad)]["error"]
    assert got[-1] == ["gate", "calibrate", 40]


# The two lists of services/api/tests/chaos/accounts/test_e27_harness_guards.py (C-13.5).
ACCEPT = [
    "http://127.0.0.1:8000",
    "http://localhost:8000/",
    "http://api:8000",
    "http://[::1]:8000",
    "http://LOCALHOST:8000",
    "HTTP://API:8000",
]
REFUSE = [
    "https://api.bybit.com", "http://api-demo.bybit.com:8000", "http://stream.bytick.com",
    "https://127.0.0.1:8000", "http://evil.example", "http://127.0.0.1.evil.example",
    "http://user:pw@127.0.0.1:8000", "http://127.0.0.1:8000/v5", "ftp://localhost", "not a url",
]  # fmt: skip


def _guard(base: str, **extra: str) -> Any:
    env = {"CV_E29_FIXTURE_STACK": "1", "BASE_URL": base, **extra}
    (got,) = _js("guard.js", "f.guardedWsUrl(f.guardedBase())", env=env)
    return got


@pytest.mark.parametrize("url", ACCEPT)
def test_the_guard_accepts_loopback_and_the_compose_service(url: str) -> None:
    got = _guard(url)
    assert got.lower().startswith("ws://") and got.endswith("/ws")


@pytest.mark.parametrize("url", REFUSE)
def test_the_guard_refuses_everything_else(url: str) -> None:
    got = _guard(url)
    assert isinstance(got, dict) and "refusing" in got["error"]


@pytest.mark.parametrize(
    ("env", "ok"),
    [
        ({"CV_E29_FIXTURE_STACK": "1"}, True),
        ({}, False),
        ({"CV_E29_FIXTURE_STACK": "0"}, False),
        ({"CV_E29_FIXTURE_STACK": "1", "BASE_URL": "http://10.0.0.5:8000"}, False),
        ({"CV_E29_FIXTURE_STACK": "1", "WS_PATH": "/ws@evil"}, False),
    ],
)
def test_the_guard_needs_the_flag_and_a_plain_ws_path(env: dict[str, str], ok: bool) -> None:
    (got,) = _js("guard.js", "f.guardedWsUrl(f.guardedBase())", env=env)
    assert isinstance(got, str) == ok


CFG = (
    '{symbol: "BTCUSDT", price: "100", qty: "0.001", slPct: "1", maxOrders: 3, runS: 1, rateMs: 10}'
)


def test_every_order_has_a_native_stop_and_buys_never_cross_sells() -> None:
    got = _js(
        "order.js",
        f"f.orderBody({CFG}, 'acc', 0)",
        f"f.orderBody({CFG}, 'acc', 1)",
        'f.prices("100")',
        'f.prices("0.5")',
    )
    buy, sell, px, small = got
    for o in (buy, sell):  # C-2.6: no order without its stop
        assert o["stop_loss"] == {"unit": "percent", "value": "1"}
        assert o["order_type"] == "limit" and o["exchange_account_id"] == "acc"
    assert (buy["side"], sell["side"]) == ("buy", "sell")
    assert (buy["price"], sell["price"]) == ("99", "101")
    assert float(px["buy"]) < 100 < float(px["sell"]) and float(small["buy"]) < 0.5


def test_the_cap_stops_firing_and_a_missing_scrape_is_counted() -> None:
    got = _js(
        "order.js",
        "[f.mayFire(true, 1, 9, 2, 3), f.mayFire(true, 1, 9, 3, 3), f.mayFire(false, 1, 9, 0, 3)]",
        "[f.mayFire(true, 9, 9, 0, 3)]",
        "[f.backendReading(null, 40), f.backendReading(0.075, 40), f.backendReading(0.02, 40)]",
    )
    assert got[0] == [True, False, False] and got[1] == [False]
    assert got[2] == [
        {"missing": 1, "added": None},
        {"missing": 0, "added": pytest.approx(35)},
        {"missing": 0, "added": 0},
    ]


def test_the_summary_drops_the_token_and_names_its_profile() -> None:
    (got,) = _js(
        "order.js", 'f.summaryOf({setup_data: {session: {token: "t"}}, metrics: {}}, "gate")'
    )
    assert got == {"metrics": {}, "cv_profile": "gate"}


def test_the_env_numbers_are_validated() -> None:
    good = {"CV_E29_PRICE": "100"}
    got = _js(
        "order.js",
        "f.orderEnv(__ENV)",
        *(f"f.orderEnv({{...__ENV, CV_E29_{k}: {json.dumps(v)}}})"
          for k, v in [("RUN_S", "0"), ("RATE_MS", "1.5"), ("MAX_ORDERS", "x"), ("PRICE", "")]),
        env=good,
    )  # fmt: skip
    assert (got[0]["maxOrders"], got[0]["runS"], got[0]["rateMs"]) == (200, 120, 500)
    assert all("must" in g["error"] for g in got[1:])


def test_the_script_wires_the_pure_parts_and_names_no_exchange() -> None:
    script = (KIT / "oms_submit_ack.js").read_text(encoding="utf-8")
    assert "orderBody(CFG, account, i)" in script and "summaryOf(data, PROFILE)" in script
    assert "mayFire(" in script and "backendReading(p95, DELAY_MS)" in script
    assert "acksOf(m, at)" in script and 'histogram(body, "order_submit_seconds")' in script
    assert "bybit" not in script.lower() and "bytick" not in script.lower()


def _runs(*p95: float) -> list[dict[str, Any]]:
    return [{"cv_profile": "gate", "metrics": {"oms_submit_ack_ms": {"values": {"p(95)": v}}}}
            for v in p95]  # fmt: skip


def test_the_baseline_is_warn_only_with_null_values() -> None:
    base = json.loads((KIT / "baseline.json").read_text(encoding="utf-8"))
    assert base["mode"] == "warn-only"
    assert all(m["value"] is None for m in base["metrics"].values())
    report = _cmp().compare(_runs(120.0, 125.0, 130.0), base)
    assert report["status"] == "PASS"
    assert [r["verdict"] for r in report["rows"]] == [
        "NO-BASELINE",
        "MISSING",
        "MISSING",
    ]


def test_the_gate_fails_over_five_percent_or_short_of_three_runs() -> None:
    cmp = _cmp()
    spec = {"ack": {"metric": "oms_submit_ack_ms", "stat": "p(95)", "value": 100.0}}
    over, two = _runs(106.0, 106.0, 106.0), _runs(90.0, 90.0)
    assert cmp.compare(over, {"mode": "warn-only", "metrics": spec})["rows"][0]["verdict"] == "WARN"
    assert cmp.compare(over, {"mode": "gate", "metrics": spec})["status"] == "FAIL"
    short = cmp.compare(two, {"mode": "gate", "metrics": spec})
    assert short["status"] == "FAIL" and "(2 of 3 runs)" in cmp.markdown(short)
    assert cmp.compare(two, {"mode": "warn-only", "metrics": spec})["status"] == "PASS"
    spec["ack"]["value"] = 101.0
    assert cmp.compare(over, {"mode": "gate", "metrics": spec})["status"] == "PASS"
    for mode in ("Gate", "gated", "", None):
        with pytest.raises(ValueError):
            cmp.compare([], {"mode": mode, "metrics": {}})


@pytest.mark.parametrize(
    "summary",
    [
        {"cv_profile": "gate", "setup_data": {}},
        {"cv_profile": "calibrate"},
        {"metrics": {}},
    ],
)
def test_the_gate_refuses_a_token_or_a_calibration_summary(
    tmp_path: Path, summary: dict[str, Any]
) -> None:
    (tmp_path / "s.json").write_text(json.dumps(summary), encoding="utf-8")
    args = ["--baseline", str(KIT / "baseline.json"), "--out-dir", str(tmp_path / "o")]
    assert _cmp().main([*args, str(tmp_path / "s.json")]) == 1
    assert not (tmp_path / "o").exists()


def test_the_gate_writes_its_report(tmp_path: Path) -> None:
    files = [tmp_path / f"run-{i}.json" for i in range(3)]
    for f, run in zip(files, _runs(90.0, 91.0, 92.0), strict=True):
        f.write_text(json.dumps(run), encoding="utf-8")
    args = ["--baseline", str(KIT / "baseline.json"), "--out-dir", str(tmp_path / "o")]
    assert _cmp().main([*args, *map(str, files)]) == 0
    report = json.loads((tmp_path / "o" / "compare.json").read_text(encoding="utf-8"))
    assert report["rows"][0]["median"] == 91.0
    assert "submit_ack_p95_ms" in (tmp_path / "o" / "compare.md").read_text(encoding="utf-8")
