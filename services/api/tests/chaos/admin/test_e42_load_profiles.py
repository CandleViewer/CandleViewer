"""E42-Q03 (#1216) part 4 self-tests: the export, verify and flood profiles [BQ-8].

No network, no stack, run in the ordinary PR lane. Pins every number of `lib/loadPlan.js` against
its source and the judge, the export windows against AUDIT-10M's timeline, the flood's operations
against the rbac matrix, each script's guards, and the driver's order: every guard and the chained
dataset before anything starts, the WAL read beside each run. node runs the pure k6 modules.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from bench.admin import load, load_harness, run
from bench.audit_index import ci_spike
from bench.ws import runner as ws_runner
from candleviewer.settings import Settings
from tests.chaos.admin.test_e42_harness_guards import DSN, K6, _never, _node
from tests.chaos.admin.test_e42_load_judge import _wal

load_results = load_harness("load_results")
CHAINED = "postgresql://cv:pw@127.0.0.1:55432/admin_perf1m_test"


# -- lib/loadPlan.js against its sources and the judge -----------------------------------------
def _plan(body: str) -> Any:
    return _node(K6 / "lib/loadPlan.js", body)


def test_every_number_of_the_load_plan_is_its_sources_and_the_judges() -> None:
    body = (
        "{read: t.READ_P95_MS, ab: t.READ_AB_RATIO, p90: t.PROBE_P90_MS, ratio: t.PROBE_RATIO,"
        " n: t.PROBE_N, rps: t.FLOOD_RPS, fs: t.FLOOD_S, cap: t.WAL_CAP_BYTES,"
        " lim: t.WAL_LIMIT, span: t.VERIFY_MAX_SPAN, dl: t.VERIFY_DEADLINE_S,"
        " vr: t.VERIFY_RATE_PER_HOUR, er: t.EXPORT_RATE_PER_HOUR,"
        " dr: t.DOWNLOAD_RATE_PER_HOUR, days: t.EXPORT_MAX_DAYS, pace: t.PACE_S,"
        " bounds: Object.fromEntries(Object.entries(t.PROFILES).map(([k, v]) => [k, v.bounds]))}"
    )
    t = _plan(body)
    r = load_results
    assert (t["read"], t["ab"], t["p90"], t["ratio"], t["n"]) == (
        r.READ_P95_MS, r.READ_AB_RATIO, r.PROBE_P90_MS, r.PROBE_RATIO, r.PROBE_N)  # fmt: skip
    assert (t["rps"], t["fs"], t["cap"], t["lim"]) == (r.FLOOD_RPS, r.FLOOD_S, r.WAL_CAP_BYTES,
                                                       r.WAL_LIMIT)  # fmt: skip
    assert t["bounds"] == {k: list(v) for k, v in r.BOUNDS.items()}
    field = Settings.model_fields
    assert t["span"] == field["audit_verify_max_span"].default
    assert t["dl"] == field["audit_verify_deadline_s"].default
    assert t["vr"] == field["audit_verify_rate_per_hour"].default
    assert t["er"] == field["audit_export_rate_per_hour"].default
    assert t["dr"] == field["audit_download_rate_per_hour"].default
    assert t["days"] == field["audit_export_max_range_days"].default
    assert 60 / t["pace"] < field["audit_query_rate_per_minute"].default


def _rows_in(window: dict[str, str], rows: int) -> int:
    """AUDIT-10M's rows in [from, to), exactly: row g is at START + g / rows x SPAN_DAYS."""
    start = datetime.fromisoformat(ci_spike.START_TS.replace("Z", "+00:00"))
    span = Fraction(ci_spike.SPAN_DAYS * 86400)

    def first(at: str) -> int:
        offset = Fraction(int((datetime.fromisoformat(at.replace("Z", "+00:00")) - start)
                              .total_seconds()))  # fmt: skip
        g = -((-offset * rows) // span)  # ceil
        return int(min(rows, max(0, g)))

    return first(window["to"]) - first(window["from"])


def test_export_windows_their_lengths_and_the_rows_they_hold() -> None:
    t = _plan("{w: t.EXPORT_WINDOW, long: t.EXPORT_TOO_LONG, small: t.EXPORT_SMALL,"
              " rows: [1000000, 100000].map((n) => [t.expectedRows(t.EXPORT_WINDOW, n),"
              " t.expectedRows(t.EXPORT_SMALL, n)])}")  # fmt: skip

    def days(w: dict[str, str]) -> float:
        a, b = (datetime.fromisoformat(w[k].replace("Z", "+00:00")) for k in ("from", "to"))
        return (b - a) / timedelta(days=1)

    max_days = Settings.model_fields["audit_export_max_range_days"].default
    assert days(t["w"]) == max_days and days(t["long"]) == max_days + 1
    assert t["w"]["to"] < "2026-11-01"  # in the past: no record of the run falls inside it
    for (whole, small), n in zip(t["rows"], (1_000_000, 100_000), strict=True):
        assert whole == _rows_in(t["w"], n) and small == _rows_in(t["small"], n)
    assert t["rows"][0][0] == 84_932


def test_the_flood_is_every_admin_operation_the_matrix_refuses_a_manager() -> None:
    ops = load.flood_ops()
    names = {f"{o['method']} {o['path']}" for o in ops}
    assert {"POST /admin/audit/export", "POST /admin/recorder/purge", "GET /admin/health"} <= names
    assert "GET /admin/audit" not in names  # a Manager may read the audit log (scope self)
    assert all(o["path"].startswith("/admin/") for o in ops) and len(ops) >= 25
    reqs = _plan(f"t.floodRequests({json.dumps(ops)})")
    assert len(reqs) == len(ops) and not any("{" in r["url"] for r in reqs)
    by_name = {r["name"]: r for r in reqs}
    assert by_name["GET /admin/statecharts/{machineKey}"]["url"] == (
        "/admin/statecharts/kill_switch?environment=demo"
    )
    assert by_name["GET /admin/health"]["body"] is None
    assert json.loads(by_name["PUT /admin/capacity/subaccount-tier"]["body"]) == {
        "tier": "business_kyc"
    }


def test_the_reader_the_probe_and_the_export_lines() -> None:
    t = _plan("{reads: t.readerQueries(), body: t.probeBody(), ids: [t.callId(1, 0),"
              " t.callId(1, 1), t.callId(2, 0)], codes: t.PROBE_CODES,"
              " lines: [t.exportEntries('h\\na\\nb\\n'), t.exportEntries('h\\na'),"
              " t.exportEntries('h\\n')]}")  # fmt: skip
    combos = {r["combo"] for r in t["reads"]}
    assert "severity_actor" not in combos and not any(c.startswith("q_") for c in combos)
    assert len(combos) == 11 and all("limit=200" in r["query"] for r in t["reads"])
    assert t["body"]["stop_loss"] == {"unit": "price", "value": "58000"}  # C-2.6 on every entry
    assert len(set(t["ids"])) == 3
    assert t["codes"] == ["account_scope_denied", "trading_disabled"]
    assert t["lines"] == [2, 1, 0]


def test_only_the_refusal_is_a_probe_answer_and_only_testnet_runs_part_4() -> None:
    t = _plan("{none: [[403, 'account_scope_denied'], [403, 'trading_disabled'], [201, ''],"
              " [200, 'account_scope_denied'], [403, 'forbidden'], [422, 'validation'],"
              " [503, 'audit_unavailable'], [0, '']]"
              ".map(([s, c]) => t.isProbeRefusal(s, c, undefined)),"
              " set: [[403, 'trading_disabled'], [403, 'account_scope_denied'],"
              " [202, 'trading_disabled']]"
              ".map(([s, c]) => t.isProbeRefusal(s, c, 'acct')),"
              " env: ['testnet', 'demo', 'live', undefined].map((e) => { try {"
              " return t.part4Environment(e); } catch (err) { return null; } }),"
              " escape: [0, 200, 302, 399, 400, 403, 404, 503].map(t.rbacEscape)}")  # fmt: skip
    assert t["none"] == [True, True, False, False, False, False, False, False]
    assert t["set"] == [True, False, False]  # a granted account: only `trading_disabled`
    assert t["env"] == ["testnet", None, None, None]
    assert t["escape"] == [False, True, True, True, False, False, False, False]


def test_each_load_script_checks_its_target_and_writes_no_session() -> None:
    for name in ("export_under_load.js", "verify_span.js", "refusal_flood.js"):
        src = (K6 / name).read_text()
        assert "guardedBase(__ENV.BASE_URL)" in src and "DATASETS.chained" in src, name
        setup = src.split("export function setup() {", 1)[1].split("\n}\n", 1)[0]
        assert "checkProbe(BASE, probeSession, RUN);" in setup, name  # S-01: refused, or abort
        assert "checkHealth(BASE)" in src and "runUsers(loadUsers(), loadManagers(), RUN)" in src
        body = src.split("export function handleSummary(data) {", 1)[1]
        assert 0 <= body.find("delete data.setup_data;") < body.index("JSON.stringify(data)")
    flood = (K6 / "refusal_flood.js").read_text()
    assert "#2836" in flood and "if (rbacEscape(r.status)) {\n    exec.test.abort(" in flood
    assert "http.batch(" in (K6 / "verify_span.js").read_text()  # C-04: single flight, any length
    assert "compress: false" in (K6 / "export_under_load.js").read_text()
    calls = (K6 / "lib/loadCalls.js").read_text()
    assert 'r.status === 503 && code === "audit_unavailable"' in calls
    assert 'ok: r.status === 200 ? "1" : "0"' in calls and "maybeResign(" in calls
    once = calls.split("function probeOnce(", 1)[1].split("\n}\n", 1)[0]
    assert "if (!ok) exec.test.abort(" in once and "part4Environment(guardedEnvironment(" in calls


# -- the driver --------------------------------------------------------------------------------
@pytest.fixture
def chained(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("CV_ADMIN_PERF_DSN", CHAINED)
    monkeypatch.setenv("CV_ENVIRONMENT", "testnet")
    monkeypatch.setenv(load.WAL_ENV, str(tmp_path / "audit" / "audit.wal"))
    monkeypatch.setattr(subprocess, "run", _never)
    monkeypatch.setattr(subprocess, "Popen", _never)
    return tmp_path


def test_driver_refuses_the_bulk_set_and_a_missing_wal_and_starts_nothing(
    chained: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = str(chained / "o")
    monkeypatch.setenv("CV_ADMIN_PERF_DSN", DSN)  # the bulk set
    assert run.main(["flood", "--out", out, "--base-url", "http://127.0.0.1:58000"]) == 2
    monkeypatch.setenv("CV_ADMIN_PERF_DSN", CHAINED)
    for bad in ("", "relative/audit.wal"):
        monkeypatch.setenv(load.WAL_ENV, bad)
        assert run.main(["verify", "--out", out, "--base-url", "http://127.0.0.1:58000"]) == 2


@pytest.mark.parametrize("account", ["", "00000000-0000-4000-8000-0000000000bb"])
def test_driver_runs_part_4_on_testnet_only_and_starts_nothing(
    chained: Path, monkeypatch: pytest.MonkeyPatch, account: str
) -> None:
    monkeypatch.setenv("CV_ENVIRONMENT", "demo")  # S-1216P4-01, -03
    monkeypatch.setenv("CV_ADMIN_PROBE_ACCOUNT", account)
    argv = ["flood", "--out", str(chained / "o"), "--base-url", "http://127.0.0.1:58000"]
    assert run.main([*argv, "--dry-run"]) == 2
    monkeypatch.setenv("CV_ENVIRONMENT", "testnet")
    assert run.main([*argv, "--dry-run"]) == 0


def test_driver_dry_run_prints_the_plan_and_starts_nothing(
    chained: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["export", "--out", str(chained / "o"), "--base-url", "http://127.0.0.1:58000"]
    assert run.main([*argv, "--rows", "1000000", "--dry-run"]) == 0
    out = capsys.readouterr().out
    plan = json.loads(out)
    assert plan["profile"] == "export" and plan["mode"] == "chained" and len(plan["runs"]) == 3
    assert plan["runs"][0][-1] == str(load.SCRIPTS["export"]) and plan["runs"][0][0] == "$K6_BIN"
    assert plan["wal_dir"] == str(chained / "audit") and "pw" not in out
    assert vars(load)["k6_binary"] is ws_runner.k6_binary  # imported, never copied (S-02)


def test_the_wal_path_and_the_dsn_never_reach_k6(
    chained: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CV_ADMIN_MANAGERS_FILE", "/run/managers.json")
    env = run.k6_env("http://127.0.0.1:58000", "admin_perf1m_test", 1, chained)
    assert env["CV_ADMIN_MANAGERS_FILE"] == "/run/managers.json"
    assert load.WAL_ENV not in env and "CV_ADMIN_PERF_DSN" not in env


def test_a_sampled_run_writes_its_wal_readings_and_a_late_one_is_124(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wal = tmp_path / "audit"
    wal.mkdir()
    _wal(wal, "audit.wal", 7, 3)
    quick = [sys.executable, "-c", "import time; time.sleep(0.3)"]
    assert load.run_sampled(quick, {}, tmp_path, wal) == 0
    readings = json.loads((tmp_path / load_results.WAL_JSON).read_text())
    assert len(readings) >= 2 and readings[0]["wal"]["audit.wal"]["depth"] == 4
    monkeypatch.setattr(load, "RUN_TIMEOUT_S", 0)
    slow = [sys.executable, "-c", "import time; time.sleep(30)"]
    assert load.run_sampled(slow, {}, tmp_path, wal) == 124
