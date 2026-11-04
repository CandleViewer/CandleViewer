"""E40-Q02 (#1203): the stdlib halves of the tests/load/k6/alerts kit.

The k6 scripts and their Python helpers run in the perf nightly, never on a pull request. These pin
the parts that need neither k6 nor a database: the frame checks (lib/frames.js, run with node), the
+5 % gate and its mode check (compare_baseline.py), the soak verdict and its one report-only switch
(soak_check.py), and the seed plan and its refusals (seed_alerts.py).
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import json
import shutil
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "tests" / "load" / "k6" / "alerts"


def _module(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"e40_{name}", KIT / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_seed_fills_all_four_notification_sources() -> None:
    text = (KIT / "seed_alerts.py").read_text(encoding="utf-8")
    for table in ("alert_deliveries", "system_events", "rule_events", "order_events"):
        assert f"INSERT INTO {table}" in text


def test_the_notifications_script_is_always_on_and_its_baseline_row_is_kept_apart() -> (
    None
):
    script = (KIT / "notifications_page.js").read_text(encoding="utf-8")
    assert "__ENV.CV_E40_NOTIFICATIONS !==" not in script and "disabled" not in script
    assert "p(95)<${BUDGET_MS}" in script and "BUDGET_MS = 200" in script
    base = json.loads((KIT / "baseline.json").read_text(encoding="utf-8"))
    n = base["metrics"]["notifications_p95_ms"]
    assert n["metric"] == "http_req_duration{endpoint:notifications}"
    assert n["value"] is None
    assert base["metrics"]["http_p95_ms"]["skip_if_has"] == n["metric"]


def test_the_notifications_metric_is_kept_apart_from_the_ws_http_metric() -> None:
    cmp = _module("compare_baseline")
    key = "http_req_duration{endpoint:notifications}"
    ws = {"metrics": {"http_req_duration": {"values": {"p(95)": 10.0}}}}
    nt = {
        "metrics": {
            "http_req_duration": {"values": {"p(95)": 900.0}},
            key: {"values": {"p(95)": 150.0}},
        }
    }
    base = json.loads((KIT / "baseline.json").read_text(encoding="utf-8"))
    rows = {r["name"]: r for r in cmp.compare([ws, nt], base)["rows"]}
    assert rows["http_p95_ms"]["runs"] == [10.0]
    assert rows["notifications_p95_ms"]["runs"] == [150.0]


def _frames(body: str) -> Any:
    node = shutil.which("node")
    assert node, (
        "node is required: the k6 lib modules are checked with it (never skipped)"
    )
    script = f"import * as f from {json.dumps((KIT / 'lib' / 'frames.js').as_uri())};\n{body}"
    out = subprocess.run(
        [node, "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)


def _d(s: int, items: int = 1, unacked: int = 5) -> dict[str, Any]:
    item = {"id": 1, "alert_id": "a", "channel": "in_app", "status": "acked", "message": "m",
            "fired_at_ms": 1}  # fmt: skip
    return {"t": "d", "ch": "alerts", "s": s, "p": {"deliveries": [item] * items,
                                                    "unacked_count": unacked}}  # fmt: skip


@pytest.mark.parametrize(
    ("frames", "issues"),
    [
        ([_d(2, unacked=4), _d(3, unacked=3)], [[], []]),
        ([_d(3)], [["gap"]]),
        ([_d(2), _d(2)], [[], ["out_of_order"]]),
        ([_d(2, items=101)], [["truncated"]]),
        ([_d(2, items=0)], [["truncated"]]),
        ([_d(2, unacked=6)], [["unacked_rose"]]),
    ],
)
def test_frames_flags_order_gaps_truncation_and_rises(
    frames: list[Any], issues: list[Any]
) -> None:
    snap = {
        "t": "snap",
        "ch": "alerts",
        "s": 1,
        "p": {"deliveries": [], "unacked_count": 5},
    }
    body = f"""const st = f.newState(); f.onFrame(st, {json.dumps(snap)}, 0);
    console.log(JSON.stringify({json.dumps(frames)}.map((m, i) => f.onFrame(st, m, 300 * (i + 1)).issues)));"""
    assert _frames(body) == issues


def test_frames_reads_a_burst_as_one_window_and_measures_the_window_gap() -> None:
    body = f"""const st = f.newState(); f.onFrame(st, {{t: "snap", ch: "alerts", s: 1, p: {{}}}}, 0);
    const at = [1000, 1005, 1260, 1262, 1500];
    const m = {json.dumps([_d(s) for s in range(2, 7)])};
    console.log(JSON.stringify(m.map((x, i) => f.onFrame(st, x, at[i]).windowGapMs)));"""
    assert _frames(body) == [None, None, 260, None, 240]


def test_the_gate_warns_until_a_baseline_is_recorded_and_fails_over_five_percent() -> (
    None
):
    cmp = _module("compare_baseline")
    runs = [{"metrics": {"alerts_ack_ms": {"values": {"p(95)": 106.0}}}}] * 3
    spec = {"ack": {"metric": "alerts_ack_ms", "stat": "p(95)", "value": 100.0}}
    assert (
        cmp.compare(runs, {"mode": "warn-only", "metrics": spec})["rows"][0]["verdict"]
        == "WARN"
    )
    assert cmp.compare(runs, {"mode": "gate", "metrics": spec})["status"] == "FAIL"
    spec["ack"]["value"] = 101.0
    assert cmp.compare(runs, {"mode": "gate", "metrics": spec})["status"] == "PASS"
    baseline = json.loads((KIT / "baseline.json").read_text(encoding="utf-8"))
    assert baseline["mode"] == "warn-only"
    assert all(m["value"] is None for m in baseline["metrics"].values())


def _ack_runs(*p95: float) -> list[dict[str, Any]]:
    return [{"metrics": {"alerts_ack_ms": {"values": {"p(95)": v}}}} for v in p95]


@pytest.mark.parametrize("n", [1, 2])
def test_the_gate_fails_on_fewer_than_three_runs_and_warns_in_warn_only(n: int) -> None:
    cmp = _module("compare_baseline")
    spec = {"ack": {"metric": "alerts_ack_ms", "stat": "p(95)", "value": 100.0}}
    gate = cmp.compare(_ack_runs(*[90.0] * n), {"mode": "gate", "metrics": spec})
    assert gate["status"] == "FAIL" and gate["rows"][0]["verdict"] == "FAIL"
    assert f"({n} of 3 runs)" in cmp.markdown(gate)
    warn = cmp.compare(_ack_runs(*[90.0] * n), {"mode": "warn-only", "metrics": spec})
    assert warn["status"] == "PASS" and warn["rows"][0]["verdict"] == "WARN"
    spec["ack"]["value"] = None  # no baseline yet
    three = cmp.compare(_ack_runs(90.0, 95.0, 99.0), {"mode": "gate", "metrics": spec})
    assert three["status"] == "PASS" and three["rows"][0]["verdict"] == "NO-BASELINE"


def test_the_gate_counts_a_run_that_wrote_no_summary(tmp_path: Path) -> None:
    cmp, base = _module("compare_baseline"), tmp_path / "b.json"
    spec = {"ack": {"metric": "alerts_ack_ms", "stat": "p(95)", "value": 100.0}}
    base.write_text(json.dumps({"mode": "gate", "metrics": spec}), encoding="utf-8")
    files = [tmp_path / f"run-{i}.json" for i in range(3)]
    for f, run in zip(files, _ack_runs(90.0, 91.0, 92.0), strict=True):
        f.write_text(json.dumps(run), encoding="utf-8")
    args = ["--baseline", str(base), "--out-dir", str(tmp_path / "o"), *map(str, files)]
    assert cmp.main(args) == 0
    files[2].unlink()  # the third run crashed before it wrote its summary
    assert cmp.main(args) == 1


def test_only_the_single_notifications_run_lowers_the_minimum() -> None:
    base = json.loads((KIT / "baseline.json").read_text(encoding="utf-8"))
    lowered = {k: m["min_runs"] for k, m in base["metrics"].items() if "min_runs" in m}
    assert lowered == {"notifications_p95_ms": 1}
    one = {"metrics": {"http_req_duration{endpoint:notifications}": {"p(95)": 1.0}}}
    row = _module("compare_baseline").compare([one], base)["rows"][2]
    assert (row["runs"], row["verdict"]) == ([1.0], "NO-BASELINE")


def test_the_gate_refuses_a_summary_that_holds_setup_data(tmp_path: Path) -> None:
    summary = tmp_path / "s.json"
    summary.write_text(json.dumps({"setup_data": {}, "metrics": {}}), encoding="utf-8")
    args = [
        "--baseline",
        str(KIT / "baseline.json"),
        "--out-dir",
        str(tmp_path),
        str(summary),
    ]
    assert _module("compare_baseline").main(args) == 1


@pytest.mark.parametrize("mode", ["Gate", "gated", "", None])
def test_the_gate_refuses_an_unknown_mode(tmp_path: Path, mode: str | None) -> None:
    cmp = _module("compare_baseline")
    base = {"mode": mode, "metrics": {}}
    with pytest.raises(ValueError):
        cmp.compare([], base)
    (tmp_path / "b.json").write_text(json.dumps(base), encoding="utf-8")
    (tmp_path / "s.json").write_text(json.dumps({"metrics": {}}), encoding="utf-8")
    args = [
        "--baseline",
        str(tmp_path / "b.json"),
        "--out-dir",
        str(tmp_path),
        str(tmp_path / "s.json"),
    ]
    assert cmp.main(args) == 1


def test_the_soak_verdict_names_each_check() -> None:
    v = _module("soak_check").verdict
    ok = {"armed": 200, "fires": 40, "rows": 40, "dead": 0}
    assert v(ok, None)["status"] == "PASS"
    assert (
        v({**ok, "rows": 39}, None)["checks"]["fire_count_equals_delivery_rows"]
        == "FAIL"
    )
    assert v({**ok, "dead": 1}, None)["checks"]["no_dead_outbox_rows"] == "FAIL"
    assert v({**ok, "fires": 0, "rows": 0}, None)["checks"]["alerts_fired"] == "FAIL"
    assert (
        v(ok, {"min": 1.0, "max": 2.0, "growth": 1.0})["memory_envelope"]["mode"]
        == "report-only"
    )


def test_the_soak_names_its_blocker_and_its_one_switch() -> None:
    body = (KIT / "soak.js").read_text(encoding="utf-8")
    assert "alert evaluator on" not in body and "synthetic feed" not in body
    doc = (ROOT / "docs" / "qa" / "perf" / "e40-alerts-baseline.md").read_text(
        encoding="utf-8"
    )
    assert "PushedMetricSource" in doc and "CV_E40_SOAK_GATE" in doc
    assert "#5745 (E35-T15)" in doc and "#5745 (E35-T15)" in body


@pytest.mark.parametrize(("gate", "code"), [(None, 0), ("0", 0), ("1", 1)])
def test_the_soak_checks_still_compute_and_only_the_switch_fails_the_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gate: str | None, code: int
) -> None:
    mod = _module("soak_check")

    async def silent(dsn: str) -> dict[str, int]:
        return {"armed": 200, "fires": 0, "rows": 0, "dead": 0}

    monkeypatch.setattr(mod, "counts", silent)
    monkeypatch.setenv("CV_PG_DSN", "postgresql://unused")
    if gate is None:
        monkeypatch.delenv("CV_E40_SOAK_GATE", raising=False)
    else:
        monkeypatch.setenv("CV_E40_SOAK_GATE", gate)
    out = tmp_path / "soak-check.json"
    assert (
        mod.main(["--summary", str(tmp_path / "none.json"), "--out", str(out)]) == code
    )
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["status"] == "FAIL" and result["checks"]["alerts_fired"] == "FAIL"
    if gate == "1":
        assert result["gate"] == "on"
    else:
        assert "PushedMetricSource" in result["gate"]
        assert "#5745 (E35-T15)" in result["gate"]


def test_the_seed_plan_reaches_a_million_rows() -> None:
    p = _module("seed_alerts").plan(1_000_000, 10, 5_000)
    total = 10 * (p["sent_per_owner"] + p["acked_per_owner"]) + p["system_events"]
    assert total >= 1_000_000 and p["system_events"] == 400_000
    with pytest.raises(ValueError):
        _module("seed_alerts").plan(1_000_000, 0, 5_000)


@pytest.mark.parametrize("pattern", ["perf-0123abcd-%"])
def test_the_seed_accepts_only_the_per_run_pattern(pattern: str) -> None:
    _module("seed_alerts").check_users_like(pattern)


@pytest.mark.parametrize(
    "pattern",
    ["%", "perf-%", "perf-0123abcd-%%", "perf-0123ABCD-%", "perf-0123abcd-_", "perf-0123abc-%",
     "x-perf-0123abcd-%", "perf-0123abcd-%\n"],
)  # fmt: skip
def test_the_seed_refuses_a_broad_users_pattern(pattern: str) -> None:
    with pytest.raises(SystemExit, match="users-like"):
        _module("seed_alerts").check_users_like(pattern)


@pytest.mark.parametrize(
    "host", ["127.0.0.1", "localhost", "[::1]", "postgres", "LOCALHOST", "Postgres"]
)
def test_the_seed_accepts_a_loopback_or_compose_dsn(host: str) -> None:
    seed = _module("seed_alerts")
    seed.check_dsn(f"postgresql+asyncpg://cv:pw@{host}:5432/candleviewer")
    seed.check_dsn(f"postgresql+asyncpg://cv@{host}/candleviewer")
    # the nightly's DSN: a 64-hex password (openssl rand -hex 32)
    seed.check_dsn(f"postgresql+asyncpg://cv:{'0a' * 32}@{host}:5432/candleviewer")


# Each literal names the check that must refuse it, so deleting any one check fails its case.
_A = "postgresql+asyncpg://cv"


@pytest.mark.parametrize(
    ("dsn", "match"),
    [(f"{_A}:pw@db.example.com:5432/candleviewer", "not loopback or compose"),
     (f"{_A}:pw@10.0.0.5/candleviewer", "not loopback or compose"),
     (f"{_A}@[::ffff:127.0.0.1]/candleviewer", "not loopback or compose"),
     ("postgresql:///candleviewer", "host part is ambiguous"),
     (f"{_A}@/candleviewer", "missing or not plain"),
     (f"{_A}:pw@127.0.0.1/candleviewer?host=db.example.com", "query string or fragment"),
     (f"{_A}@127.0.0.1/candleviewer?", "query string or fragment"),
     (f"{_A}@127.0.0.1/candleviewer#x", "query string or fragment"),
     (f"{_A}:pw@127.0.0.1:5432,db.example.com:5432/candleviewer", "more than one host"),
     (f"{_A}:p@db.example.com@127.0.0.1/candleviewer", "more than one @"),
     (f"{_A}:p@[db.example.com]@[::1]:5432/candleviewer", "more than one @"),
     (f"{_A}:p%40db.example.com@127.0.0.1/candleviewer", "host part is ambiguous"),
     (f"{_A}@%6c%6fcalhost/candleviewer", "host part is ambiguous"),
     (f"{_A}@127.0.0.1%2Fdb.example.com/candleviewer", "host part is ambiguous"),
     (f"{_A}@[::1%25eth0]/candleviewer", "host part is ambiguous"),
     (f"{_A}@127.0.0.1\\.example.com/candleviewer", "host part is ambiguous"),
     (f"{_A}@127.0.0.1:/candleviewer", "host part is ambiguous"),
     (f"{_A}@localhost./candleviewer", "missing or not plain"),
     (f"{_A}@[::1/candleviewer", "does not parse"),
     (f"{_A}@127.0.0.1:x/candleviewer", "port is not a number"),
     ("mysql://cv@127.0.0.1/candleviewer", "not Postgres")],
)  # fmt: skip
def test_the_seed_refuses_a_non_local_or_ambiguous_dsn(dsn: str, match: str) -> None:
    with pytest.raises(SystemExit, match=f"refusing: .*{match}"):
        _module("seed_alerts").check_dsn(dsn)


@pytest.mark.parametrize(
    ("counts", "match"),
    [
        ((1, 0, 0), "outside the perf pattern"),
        ((0, 1, 0), "live or demo"),
        ((0, 0, 1), "api_keys"),
    ],
)
def test_the_seed_refuses_a_stack_that_is_not_a_perf_stack(
    counts: tuple[int, int, int], match: str
) -> None:
    with pytest.raises(SystemExit, match=match):
        _module("seed_alerts").check_stack(*counts)
    _module("seed_alerts").check_stack(0, 0, 0)


class _Conn:
    """A stub asyncpg connection: records each call, in order, and never writes anything."""

    def __init__(self, log: list[str], stack: dict[str, int]) -> None:
        self.log, self.stack = log, stack

    async def fetchrow(self, query: str, *args: object) -> dict[str, int]:
        self.log.append("stack" if "FROM api_keys" in query else "fetchrow")
        return self.stack

    @contextlib.asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        self.log.append("transaction")
        yield

    async def fetch(self, query: str, *args: object) -> list[dict[str, int]]:
        await self.execute(query)
        return [{"id": 1, "owner_user_id": 2}]

    async def execute(self, query: str, *args: object) -> None:
        self.log.append("write")

    async def close(self) -> None:
        self.log.append("close")


_GOOD_DSN = "postgresql+asyncpg://cv@127.0.0.1:5432/candleviewer"
_CLEAN = {"others": 0, "real_accounts": 0, "api_keys": 0}


def _run_seed(
    monkeypatch: pytest.MonkeyPatch, dsn: str, users_like: str, stack: dict[str, int]
) -> list[str]:
    log: list[str] = []

    async def connect(dsn: str) -> _Conn:
        log.append(f"connect {dsn}")
        return _Conn(log, stack)

    monkeypatch.setitem(sys.modules, "asyncpg", SimpleNamespace(connect=connect))
    try:
        asyncio.run(_module("seed_alerts").seed(dsn, users_like, 1_000, 10, 10, 10))
    except SystemExit as exc:
        log.append(f"refused {exc}")
    return log


@pytest.mark.parametrize(
    ("dsn", "users_like", "match"),
    [(_GOOD_DSN, "perf-%", "users-like"),
     ("postgresql+asyncpg://cv@db.example.com/candleviewer", "perf-0123abcd-%", "DSN host")],
)  # fmt: skip
def test_seed_refuses_before_it_connects(
    monkeypatch: pytest.MonkeyPatch, dsn: str, users_like: str, match: str
) -> None:
    log = _run_seed(monkeypatch, dsn, users_like, _CLEAN)
    assert len(log) == 1 and log[0].startswith("refused") and match in log[0]


@pytest.mark.parametrize("bad", ["others", "real_accounts", "api_keys"])
def test_seed_reads_the_stack_and_refuses_before_any_write(
    monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    log = _run_seed(monkeypatch, _GOOD_DSN, "perf-0123abcd-%", {**_CLEAN, bad: 1})
    assert log[:2] == [f"connect {_GOOD_DSN.replace('+asyncpg', '')}", "stack"]
    assert log[2] == "close" and log[3].startswith("refused") and len(log) == 4


def test_seed_checks_the_stack_before_its_one_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _run_seed(monkeypatch, _GOOD_DSN, "perf-0123abcd-%", _CLEAN)
    assert log[1:3] == ["stack", "transaction"]
    assert log.index("write") > log.index("transaction")
    assert log[-1] == "close" and not any(x.startswith("refused") for x in log)


def test_the_seed_queries_the_tables_its_refusal_reads() -> None:
    q = _module("seed_alerts")._STACK
    assert "FROM exchange_accounts WHERE env IN ('live', 'demo')" in q
    assert "FROM api_keys" in q and "username NOT LIKE $1" in q


@pytest.mark.parametrize("gate", [None, "0", "1"])
def test_the_soak_always_fails_when_the_alerts_were_not_armed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gate: str | None
) -> None:
    mod = _module("soak_check")

    async def unarmed(dsn: str) -> dict[str, int]:
        return {"armed": 0, "fires": 5, "rows": 5, "dead": 0}

    monkeypatch.setattr(mod, "counts", unarmed)
    monkeypatch.setenv("CV_PG_DSN", "postgresql://unused")
    if gate is None:
        monkeypatch.delenv("CV_E40_SOAK_GATE", raising=False)
    else:
        monkeypatch.setenv("CV_E40_SOAK_GATE", gate)
    out = tmp_path / "soak-check.json"
    code = mod.main(["--summary", str(tmp_path / "none.json"), "--out", str(out)])
    assert code == 1
    assert (
        json.loads(out.read_text(encoding="utf-8"))["checks"]["alerts_armed"] == "FAIL"
    )
