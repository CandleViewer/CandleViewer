"""E42-Q03 (#1216) harness self-tests: no network, no stack, run in the ordinary PR lane [BQ-9].

Pins the admin perf harness's guards (the Python and k6 copies agree on one table, and the API
target rule is E27's), the dataset driver's order (the guard refuses before any loader runs), the
runner's refusals and dry run, the results judge, the query matrix and its cursors against K01's
SQL and the server's own cursor decoder, and every gated number against its source. The k6 lib
modules import nothing from k6, so node runs them here; node is required, never skipped.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from bench.admin import REPO, datasets, load_harness, run
from bench.audit_index import ci_spike
from bench.ws import runner as ws_runner
from candleviewer.audit.cursor import decode_cursor, encode_cursor
from candleviewer.auth.session_service import ACCESS_TOKEN_TTL
from candleviewer.settings import Settings
from tests.chaos.accounts.test_e27_harness_guards import ACCEPT as E27_ACCEPT
from tests.chaos.accounts.test_e27_harness_guards import REFUSE as E27_REFUSE
from tests.fixtures.admin import audit_10m, seed

guard = load_harness("guard")
results = load_harness("results")
K6 = REPO / "tests/load/k6/admin"
DSN = "postgresql://cv:pw@127.0.0.1:55432/admin_perf_test"


def _node(module: Path, body: str) -> Any:
    node = shutil.which("node")
    assert node, "node is required: the k6 lib modules are checked with it (never skipped)"
    script = (
        f"import * as t from {json.dumps(module.as_uri())};\nconsole.log(JSON.stringify({body}))"
    )
    done = subprocess.run(  # noqa: S603 - fixed argv, a script built from constants here
        [node, "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _js_accepts(fn: str, values: list[str | None]) -> list[bool]:
    args = json.dumps(values)
    call = f"try {{ t.{fn}(v ?? undefined); return true; }} catch (e) {{ return false; }}"
    body = f"{args}.map((v) => {{ {call} }})"
    return [bool(x) for x in _node(K6 / "lib/guard.js", body)]


# -- the API target: E27's rule, in both copies ------------------------------------------------
# E27's own table (tests/chaos/accounts), so the two harnesses cannot drift apart.
ACCEPT, REFUSE = E27_ACCEPT, E27_REFUSE


def test_target_guard_is_the_e27_rule_in_both_copies() -> None:
    for url in ACCEPT:
        assert guard.check_target(url) == url.rstrip("/")
    for url in REFUSE:
        with pytest.raises(guard.TargetRefused) as err:
            guard.check_target(url)
        assert url not in str(err.value)
    expected = [True] * len(ACCEPT) + [False] * len(REFUSE)
    assert _js_accepts("guardedBase", [*ACCEPT, *REFUSE]) == expected
    assert _js_accepts("guardedBase", ["", None]) == [False, False]  # no default, as run.py
    allowed = re.compile(r"^const ALLOWED = (/.+/i);", re.MULTILINE)
    e27 = allowed.search((REPO / "tests/load/k6/accounts/lib/guard.js").read_text())
    ours = allowed.search((K6 / "lib/guard.js").read_text())
    assert e27 and ours and e27.group(1) == ours.group(1)


# -- the database and the environment: one table, both copies ----------------------------------
DSN_OK = [
    DSN,
    "postgresql+asyncpg://cv:pw@localhost/admin_perf1m_test",
    "postgresql://postgres/admin_perf_test",
]
DSN_BAD = [
    "postgresql://cv:pw@127.0.0.1/candleviewer",  # the product database
    "postgresql://cv:pw@db.example/admin_perf_test",  # not loopback
    "postgresql://cv:pw@127.0.0.1/admin_perf_test?dbname=candleviewer",  # overrides the path
    "postgresql://cv:pw@127.0.0.1/",  # libpq would fall back to PGDATABASE
    "mysql://cv:pw@127.0.0.1/admin_perf_test",
    "postgresql://cv:pw@127.0.0.1/other_test",  # a test database, but no dataset's own
    "postgresql://cv:pw@127.0.0.1:99999/admin_perf_test",
    "postgresql://cv:pw@db.example@127.0.0.1/admin_perf_test",
    "postgresql://db.example,@127.0.0.1/admin_perf_test",
    "postgresql://cv:pw%40db.example@127.0.0.1/admin_perf_test",
    "postgresql://cv:pw%2Cx@127.0.0.1/admin_perf_test",
]  # fmt: skip


@pytest.mark.parametrize("dsn", DSN_OK)
def test_database_guard_accepts_a_dataset_database_on_loopback(dsn: str) -> None:
    assert guard.check_dataset(dsn) in guard.DATASETS.values()
    assert guard.check_dataset(DSN, "bulk") == "admin_perf_test"


@pytest.mark.parametrize("dsn", DSN_BAD)
def test_database_guard_refuses_without_echoing_the_dsn(dsn: str) -> None:
    with pytest.raises(guard.TargetRefused) as err:
        guard.check_dataset(dsn)
    assert "pw" not in str(err.value) and "127.0.0.1" not in str(err.value)


def test_each_dataset_loads_only_into_its_own_database() -> None:
    with pytest.raises(guard.TargetRefused):
        guard.check_dataset(DSN, "chained")


def test_both_copies_hold_the_same_datasets_and_the_loaders_test_rule() -> None:
    names = ["admin_perf_test", "admin_perf1m_test", "other_test", "candleviewer", "test", "", None]
    assert _node(K6 / "lib/guard.js", "t.DATASETS") == guard.DATASETS
    py = [n in guard.DATASETS.values() for n in names]
    assert _js_accepts("guardedDatabase", names) == py
    for name in ["test", "x_test", "x_test2", "testing", "_test", "candleviewer"]:
        assert guard.is_test_database(name) == seed.is_test_database(name)
    assert all(seed.is_test_database(n) for n in guard.DATASETS.values())


def test_both_copies_refuse_a_live_environment() -> None:
    values = ["testnet", "demo", "live", "LIVE", "", None]
    py = []
    for value in values:
        try:
            py.append(guard.check_environment(value) == value)
        except guard.TargetRefused:
            py.append(False)
    assert py == [True, True, False, False, False, False]
    assert _js_accepts("guardedEnvironment", values) == py


# -- the dataset driver: the guard first, then the fixture loader -------------------------------
def test_driver_refuses_before_any_loader_runs_then_hands_it_the_mode_and_rows() -> None:
    seen: list[tuple[str, int, bool]] = []

    def loader(dsn: str, rows: int, *, chained: bool) -> int:
        seen.append((dsn, rows, chained))
        return rows

    for dsn in DSN_BAD:
        with pytest.raises(guard.TargetRefused):
            datasets.load(dsn, "bulk", 100, loader=loader)
    assert seen == []
    assert datasets.load(DSN, "bulk", 100_000, loader=loader) == ("admin_perf_test", 100_000)
    assert seen == [(DSN, 100_000, False)]
    assert datasets._audit_10m() is audit_10m.load_audit_10m  # imported, never copied
    assert datasets.DEFAULT_ROWS["bulk"] == datasets.MAX_ROWS == audit_10m.ROWS


def test_driver_cli_exits_2_on_a_refused_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(datasets.DSN_ENV, DSN_BAD[0])
    assert datasets.main(["load", "--mode", "bulk", "--rows", "10"]) == 2


# -- the runner: every guard before anything starts ----------------------------------------------
@pytest.mark.parametrize(
    ("dsn", "env", "base"),
    [(DSN_BAD[0], "testnet", ACCEPT[0]), (DSN, "live", ACCEPT[0]), (DSN, None, ACCEPT[0]),
     (DSN, "testnet", REFUSE[0])],
)  # fmt: skip
def test_runner_refuses_and_starts_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dsn: str, env: str | None, base: str
) -> None:
    monkeypatch.setenv("CV_ADMIN_PERF_DSN", dsn)
    if env is None:
        monkeypatch.delenv("CV_ENVIRONMENT", raising=False)
    else:
        monkeypatch.setenv("CV_ENVIRONMENT", env)
    monkeypatch.setattr(subprocess, "run", _never)
    assert run.main(["audit", "--out", str(tmp_path), "--base-url", base]) == 2


def _never(*_a: object, **_k: object) -> None:
    raise AssertionError("nothing may start before every guard passed")


def test_runner_dry_run_prints_the_plan_and_starts_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CV_ADMIN_PERF_DSN", DSN)
    monkeypatch.setenv("CV_ENVIRONMENT", "testnet")
    monkeypatch.setattr(subprocess, "run", _never)
    assert run.main(["audit", "--out", str(tmp_path), "--base-url", ACCEPT[0], "--dry-run"]) == 0
    out = capsys.readouterr().out
    plan = json.loads(out)
    assert plan["database"] == "admin_perf_test" and len(plan["runs"]) == 3
    assert "pw" not in out and str(run.SCRIPTS["audit"]) in plan["runs"][0]
    assert plan["runs"][0][0] == "$K6_BIN" and plan["mode"] == "bulk"


def test_runner_takes_k6_only_from_the_ws_harness_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert vars(run)["k6_binary"] is ws_runner.k6_binary  # imported, never copied (S-02)
    monkeypatch.setenv("CV_ADMIN_PERF_DSN", DSN)
    monkeypatch.setenv("CV_ENVIRONMENT", "testnet")
    monkeypatch.setattr(subprocess, "run", _never)
    for value in (None, "k6", str(tmp_path / "missing")):  # unset, a PATH lookup, not a file
        if value is None:
            monkeypatch.delenv("K6_BIN", raising=False)
        else:
            monkeypatch.setenv("K6_BIN", value)
        with pytest.raises(SystemExit):
            run.main(["audit", "--out", str(tmp_path), "--base-url", ACCEPT[0]])


def test_runner_has_no_default_target(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """S-1216P1-d01: omitting --base-url exits non-zero before any guard or process."""
    monkeypatch.setenv("CV_ADMIN_PERF_DSN", DSN)
    monkeypatch.setenv("CV_ENVIRONMENT", "testnet")
    monkeypatch.setattr(subprocess, "run", _never)
    with pytest.raises(SystemExit) as exc:
        run.main(["audit", "--out", str(tmp_path), "--dry-run"])
    assert exc.value.code == 2


PASSWORD = "generated-per-run"  # noqa: S105 - a test value, never a credential
K6_CALLER = ("K6_HTTP_DEBUG", "K6_NO_THRESHOLDS", "K6_OUT", "K6_CLOUD_TOKEN", "K6_SYSTEM_TAGS",
             "K6_INCLUDE_SYSTEM_ENV_VARS", "K6_BIN")  # fmt: skip


def test_k6_env_is_an_explicit_allow_list(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in (
        "CV_AUTH_PEPPER",
        "CV_ADMIN_PERF_DSN",
        "POSTGRES_PASSWORD",
        "CV_AUTH_CSRF_KEY_HEX",
        *K6_CALLER,
    ):
        monkeypatch.setenv(name, "x" * 32)
    monkeypatch.setenv("CV_ADMIN_PASSWORD", PASSWORD)
    monkeypatch.setenv("CV_ADMIN_USERS_FILE", "/run/users.json")
    monkeypatch.setenv("K6_NO_COLOR", "true")
    env = run.k6_env(ACCEPT[0], "admin_perf_test", 2, tmp_path)
    assert "CV_AUTH_PEPPER" not in env and "CV_ADMIN_PERF_DSN" not in env  # S-03
    assert "x" * 32 not in env.values() and "K6_BIN" not in env
    assert [name for name in K6_CALLER if name in env] == []
    assert env["CV_ADMIN_PASSWORD"] == PASSWORD and env["K6_NO_COLOR"] == "true"
    assert env["K6_NO_USAGE_REPORT"] == "true" and env["K6_AUTO_EXTENSION_RESOLUTION"] == "false"
    assert env["CV_ADMIN_USERS_FILE"] == "/run/users.json" and env["CV_ADMIN_RUN"] == "2"


def test_run_once_maps_a_timeout_to_124(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def slow(*_a: object, **_k: object) -> None:
        raise subprocess.TimeoutExpired("k6", run.RUN_TIMEOUT_S)

    monkeypatch.setattr(subprocess, "run", slow)
    assert run.run_once("/k6", "audit", 1, tmp_path, ACCEPT[0], "admin_perf_test") == 124


def test_a_timed_out_run_does_not_stop_the_next_ones(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`main` drives all three runs after run 1 times out, and exits with the worst code."""
    monkeypatch.setenv("CV_ADMIN_PERF_DSN", DSN)
    monkeypatch.setenv("CV_ENVIRONMENT", "testnet")
    monkeypatch.setattr(run, "k6_binary", lambda: "/k6")
    started: list[int] = []

    def stub(_k6: str, _profile: str, i: int, *_rest: object) -> int:
        started.append(i)
        return 124 if i == 1 else 0

    monkeypatch.setattr(run, "run_once", stub)
    argv = ["audit", "--out", str(tmp_path), "--base-url", ACCEPT[0]]
    assert run.main(argv) == 124  # the judge finds no points (2): the worst code wins
    assert started == [1, 2, 3]


# -- the results judge -------------------------------------------------------------------------
Key = tuple[str, str, str]


def _points(path: Path, rows: dict[Key, list[float]], warm: float = 9e9) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    lines = []
    for (combo, pos, cls), values in rows.items():
        tags = {"combo": combo, "pos": pos, "cls": cls}
        for i, v in enumerate([warm, *values]):
            ok = "0" if math.isnan(v) else "1"  # NaN stands for a call that did not answer 200
            data = {"value": v, "tags": {**tags, "warm": "1" if i == 0 else "0", "ok": ok}}
            lines.append(json.dumps({"type": "Point", "metric": results.METRIC, "data": data}))
    lines.append(json.dumps({"type": "Point", "metric": "http_reqs", "data": {"value": 1}}))
    (path / "points.json").write_text("\n".join(lines) + "\n")
    return path


def _full(rows: dict[Key, list[float]]) -> dict[Key, list[float]]:
    """The whole plan at 3 ms a sample, `rows` over it: the judge reads every planned key."""
    return {key: [3.0] * results.SAMPLES for key in results.PLANNED} | rows


def _judged(out: Path) -> dict[tuple[str, str], dict[str, Any]]:
    doc = json.loads((out / results.RESULTS_JSON).read_text())
    return {(r["combo"], r["pos"]): r for r in doc["results"]}


def test_percentile_is_nearest_rank() -> None:
    values = [float(v) for v in range(1, 21)]
    assert [results.percentile(values, q) for q in (50, 95, 99)] == [10.0, 19.0, 20.0]


def test_judge_takes_the_median_of_runs_and_drops_the_warm_up(tmp_path: Path) -> None:
    ok = [10.0] * 19 + [500.0]  # p95 is the 19th of 20: 10 ms; the warm-up (9e9 ms) is dropped
    slow = [450.0] * 20
    runs = [_points(tmp_path / f"r{i}", _full({("actor", "page1", "common"): ok,
            ("severity_actor", "page1", "common"): slow if i else ok}))
            for i in range(3)]  # fmt: skip
    assert results.main(["judge", *map(str, runs), "--out", str(tmp_path / "out")]) == 1
    rows = _judged(tmp_path / "out")
    actor, severity_actor = rows["actor", "page1"], rows["severity_actor", "page1"]
    assert actor["verdict"] == "PASS" and actor["p95"] == 10.0 and actor["waits_on"] == ""
    assert actor["max"] == 500.0
    assert severity_actor["verdict"] == "FAIL" and severity_actor["p95"] == 450.0
    assert severity_actor["waits_on"] == "#1710"  # [BQ-1], still a FAIL
    table = (tmp_path / "out" / results.RESULTS_MD).read_text()
    assert "| severity_actor | page1 | common | 400 ms |" in table
    assert [r["verdict"] for k, r in rows.items() if k != ("severity_actor", "page1")] == (
        ["PASS"] * 27
    )


def test_judge_names_the_issue_each_by_design_fail_waits_on_and_passes_at_the_budget(
    tmp_path: Path,
) -> None:
    runs = [_points(tmp_path / f"r{i}", _full({("q_selective", "page1", "q"): [4000.0] * 20,
            ("unfiltered", "page1", "common"): [400.0] * 20})) for i in range(3)]  # fmt: skip
    assert results.main(["judge", *map(str, runs), "--out", str(tmp_path / "out")]) == 1
    rows = _judged(tmp_path / "out")
    assert rows["q_selective", "page1"]["verdict"] == "FAIL"
    assert rows["q_selective", "page1"]["waits_on"] == "#1711"
    assert rows["unfiltered", "page1"]["verdict"] == "PASS"  # "<=400 ms": the budget passes


def test_judge_never_counts_a_failed_call_as_a_duration(tmp_path: Path) -> None:
    rows = _full({("actor", "page1", "common"): [3.0] * 19 + [math.nan]})
    run_dir = _points(tmp_path / "r", rows)
    assert results.main(["judge", str(run_dir), "--out", str(tmp_path / "out")]) == 1
    assert _judged(tmp_path / "out")["actor", "page1"]["verdict"] == "ERRORS"


def _line(ok: object, value: str) -> str:
    tags = {"combo": "actor", "pos": "page1", "cls": "common", "warm": "0", "ok": ok}
    point = {"type": "Point", "metric": results.METRIC, "data": {"value": "<v>", "tags": tags}}
    return json.dumps(point).replace('"<v>"', value)  # the raw JSON token k6 could write


@pytest.mark.parametrize(
    ("ok", "value"),
    [("1", "NaN"), ("1", "Infinity"), ("1", "-Infinity"), ("1", "true"), ("1", "-1"),
     ("1", '"5"'), ("1", "null"), ("0", "5"), ("1.0", "5"), (True, "5"), (1, "5"), (None, "5")],
)  # fmt: skip
def test_a_sample_is_a_duration_only_with_ok_1_and_a_real_value(ok: object, value: str) -> None:
    key = ("actor", "page1", "common")
    assert results.read_points([_line("1", "5")]) == {key: [5.0]}
    assert results.read_points([_line(ok, value)]) == {key: [None]}


def test_a_key_with_no_200_sample_is_null_in_json_and_n_a_in_the_table(tmp_path: Path) -> None:
    """C-1216P1-d02: q_selective's 4 s stop (503) leaves no duration: ERRORS, never a bare NaN."""
    run_dir = _points(tmp_path / "r", _full({("q_selective", "page1", "q"): [math.nan] * 20}))
    out = tmp_path / "out"
    assert results.main(["judge", str(run_dir), "--out", str(out)]) == 1

    def refuse(token: str) -> None:
        raise AssertionError(f"not strict JSON: {token}")

    text = (out / results.RESULTS_JSON).read_text()
    doc = json.loads(text, parse_constant=refuse)["results"]
    (row,) = [r for r in doc if (r["combo"], r["pos"]) == ("q_selective", "page1")]
    assert row["verdict"] == "ERRORS" and row["waits_on"] == "#1711"
    assert [row[s] for s in results.STATS] == [None] * 4
    md = (out / results.RESULTS_MD).read_text().splitlines()
    line = next(x for x in md if "| q_selective | page1 |" in x)
    assert line.count("n/a") == 4 and "nan" not in line.lower()


def test_results_name_what_they_measured_and_mark_a_control(tmp_path: Path) -> None:
    run_dir = _points(tmp_path / "r", _full({}))
    cases = [("admin_perf_test", "bulk", audit_10m.ROWS, "verdict"),
             ("admin_perf_test", "bulk", 100_000, "CONTROL, not a verdict"),
             ("admin_perf1m_test", "chained", 1_000_000, "CONTROL, not a verdict")]  # fmt: skip
    assert results.FULL_ROWS == audit_10m.ROWS
    for i, (database, mode, rows, kind) in enumerate(cases):
        out = tmp_path / f"o{i}"
        argv = ["judge", str(run_dir), "--out", str(out), "--database", database, "--mode", mode]
        assert results.main([*argv, "--rows", str(rows)]) == 0
        doc = json.loads((out / results.RESULTS_JSON).read_text())
        measured = (doc["database"], doc["mode"], doc["rows"], doc["kind"])
        assert measured == (database, mode, rows, kind)
        head = (out / results.RESULTS_MD).read_text().splitlines()[0]
        assert head == f"Dataset: {database} ({mode}, {rows} rows): {kind}"


def test_judge_never_passes_a_short_run_or_a_missing_key(tmp_path: Path) -> None:
    short = _points(tmp_path / "s", _full({("actor", "deep", "common"): [1.0] * 19}))
    assert results.main(["judge", str(short), "--out", str(tmp_path / "o1")]) == 1
    assert _judged(tmp_path / "o1")["actor", "deep"]["verdict"] == "INCOMPLETE"
    rows = _full({})
    del rows["range", "deep", "common"]
    lacking = _points(tmp_path / "m", rows)
    for i, argv in enumerate([[lacking], [_points(tmp_path / "f", _full({})), lacking]]):
        out = tmp_path / f"m{i}"
        assert results.main(["judge", *map(str, argv), "--out", str(out)]) == 1
        judged = _judged(out)
        assert len(judged) == 28 and judged["range", "deep"]["verdict"] == "INCOMPLETE"
        assert [k for k, r in judged.items() if r["verdict"] != "PASS"] == [("range", "deep")]


def test_judge_refuses_nothing_to_judge_or_an_unplanned_key(tmp_path: Path) -> None:
    empty = _points(tmp_path / "e", {})
    assert results.main(["judge", str(empty), "--out", str(tmp_path / "o1")]) == 2
    other = _points(tmp_path / "x", _full({("actor", "page1", "q"): [1.0] * 20}))
    assert results.main(["judge", str(other), "--out", str(tmp_path / "o2")]) == 2


# -- the query matrix, its cursors and the gated numbers, against their sources -----------------
def _matrix() -> dict[str, Any]:
    return dict(
        _node(
            K6 / "lib/combos.js",
            "{combos: t.COMBOS, plan: t.plan(200), start: t.SPAN_START, days: t.SPAN_DAYS}",
        )
    )


def test_matrix_is_k01s_combinations_with_k01s_values() -> None:
    m = _matrix()
    combos = {c["name"]: c for c in m["combos"]}
    assert len(combos) == 14 and {c["cls"] for c in combos.values()} == {"common", "q"}
    assert set(ci_spike.FILTERS) - set(combos) == {"object", "env_action"}  # object is `subject`
    assert (m["start"], m["days"]) == (ci_spike.START_TS, ci_spike.SPAN_DAYS)
    sql = {**ci_spike.FILTERS, "subject": ci_spike.FILTERS["object"]}
    sql["q_selective"], sql["q_common"] = ci_spike.FULLTEXT.values()
    sql["severity_actor"] += ci_spike._ACTOR  # K01 named user_07 by its label, the API by its id
    for name, c in combos.items():
        for key, value in c["params"].items():
            if key != "ip":  # K01 has no IP row; the API takes one exact address
                assert value.removesuffix("T00:00:00Z") in sql[name], (name, key)
    assert combos["ip"]["params"]["ip"].startswith("192.0.2.")  # the set's RFC 5737 addresses


def test_matrix_classes_and_sparse_rows_are_the_judges_plan() -> None:
    m = _matrix()
    sparse = {"subject", "q_selective"}  # selective by construction: a deep page may be empty
    table = {c["name"]: (c["cls"], c.get("sparse", False)) for c in m["combos"]}
    assert table == {name: (cls, name in sparse) for name, cls in results.COMBOS.items()}
    assert {(p["combo"], p["pos"], p["cls"]) for p in m["plan"]} == results.PLANNED
    assert len(results.PLANNED) == 28 and all(
        p["sparse"] == (p["combo"] in sparse) for p in m["plan"]
    )


def test_every_cursor_is_one_the_server_issues_90_percent_into_its_window() -> None:
    m = _matrix()
    deep = [p for p in m["plan"] if p["pos"] == "deep"]
    assert len(m["plan"]) == 28 and len(deep) == 14
    assert all("limit=200" in p["query"] for p in m["plan"])
    for row in deep:
        token = re.search(r"cursor=([A-Za-z0-9_-]+)", row["query"])
        assert token, row["combo"]
        position = decode_cursor(token.group(1))
        assert encode_cursor(position) == token.group(1) and position.id == 2**63 - 1
    by_name = {
        p["combo"]: decode_cursor(p["query"].split("cursor=")[1].split("&")[0]) for p in deep
    }
    assert by_name["unfiltered"].ts.isoformat() == ci_spike.cursor_literal(0.9)
    assert by_name["range"].ts.isoformat() == "2026-06-04T00:00:00+00:00"


def test_gated_numbers_match_their_sources() -> None:
    t = _node(K6 / "lib/thresholds.js", "{c: t.COMMON_P95_MS, q: t.Q_P95_MS, limit: t.PAGE_LIMIT,"
              " pace: t.PACE_S, n: t.SAMPLES, th: t.thresholds()}")  # fmt: skip
    assert (t["c"], t["q"]) == (ci_spike.COMMON_P95_BUDGET_MS, ci_spike.WORST_CASE_BUDGET_MS)
    assert results.BUDGET_MS == {"common": t["c"], "q": t["q"]} and results.SAMPLES == t["n"]
    rate = Settings.model_fields["audit_query_rate_per_minute"].default
    assert 60 / t["pace"] < rate == 60  # the shipped limiter is never what is measured
    assert t["th"]["http_req_failed"] == ["rate==0"]
    assert t["th"]["cv_admin_audit_ms{cls:common,warm:0}"] == ["p(95)<=400"]  # SCR-135 "<=400 ms"
    src = (K6 / "audit_first_page.js").read_text()
    assert "guardedBase(__ENV.BASE_URL)" in src and "guardedEnvironment(health.json(" in src
    body = src.split("export function handleSummary(data) {", 1)[1]
    assert 0 <= body.find("delete data.setup_data;") < body.index("JSON.stringify(data)")


def test_the_session_is_signed_in_again_before_its_token_can_expire() -> None:
    body = (
        "{ttl: t.SESSION_TTL_S, stop: t.STOP_S, at: t.RESIGN_AFTER_S, calls: t.WARMUP + t.SAMPLES,"
        " pace: t.PACE_S, due: [479, 480].map(t.needsSignIn)}"
    )
    t = _node(K6 / "lib/thresholds.js", body)
    assert t["ttl"] == ACCESS_TOKEN_TTL.total_seconds()
    assert t["stop"] * 1000 == Settings.model_fields["audit_query_timeout_ms"].default
    assert t["due"] == [False, True]
    # The worst a session lives: signed in just before RESIGN_AFTER_S, then one row of calls each
    # at the server's stop plus a second of slack, and a TOTP step's wait (30 s); a minute spare.
    worst_s = t["at"] + t["calls"] * (t["stop"] + 1) + 30
    assert worst_s + 60 <= t["ttl"]
    # Without it, the profile (28 rows) at its slowest outlives the token (C-1216P1-01).
    assert 28 * t["calls"] * t["pace"] > t["at"]
    src = (K6 / "audit_first_page.js").read_text()
    loop = src.split("export function profile(data) {", 1)[1].split("for (let i", 1)[0]
    assert "maybeResign({ session, signedAt }, Date.now()," in loop  # the loop calls the decision
    assert "signIn(BASE, USERS[RUN - 1], step)" in loop
    assert "auth(session," in src


def test_a_sample_is_ok_only_for_a_200_with_a_usable_page() -> None:
    full, over = [1] * 200, [1] * 201
    cases = [[200, [1], False], [200, full, False], [200, [], True], [200, [], False],
             [200, None, True], [200, over, True], [503, [1], False], [429, [], True]]  # fmt: skip
    body = f"{json.dumps(cases)}.map(([s, p, sp]) => t.pageOk(s, p, 200, sp))"
    assert _node(K6 / "lib/thresholds.js", body) == [True, True, True] + [False] * 5
    loop = (K6 / "audit_first_page.js").read_text().split("export function profile(data) {")[1]
    page = loop.index("const page = items(r);")
    ok = loop.index('const ok = pageOk(r.status, page, PAGE_LIMIT, row.sparse) ? "1" : "0";')
    assert page < ok < loop.index("auditMs.add(r.timings.duration, { ...tags, warm: i < WARMUP")
    assert loop.count("auditMs.add(") == 1 and "ok });" in loop


def test_the_loop_signs_in_again_when_the_session_is_old_under_a_fake_clock() -> None:
    """C-1216P1-d01: the decision `profile` calls, run with a fake clock and a stand-in signIn."""
    body = """(() => {
      const calls = [];
      const signIn = (step) => { calls.push(step); return { step: step + 1, id: calls.length }; };
      let state = { session: { step: 7, id: 0 }, signedAt: 1000 };
      const at = (s) => (state = t.maybeResign(state, 1000 + s * 1000, signIn));
      at(0); at(479);
      const before = { calls: calls.length, signedAt: state.signedAt };
      at(480);
      const after = { calls: calls.length, signedAt: state.signedAt, id: state.session.id };
      at(480 + 479);
      return { before, after, last: calls.length, steps: calls };
    })()"""
    r = _node(K6 / "lib/thresholds.js", body)
    assert r["before"] == {"calls": 0, "signedAt": 1000}
    assert r["after"] == {"calls": 1, "signedAt": 481000, "id": 1}  # age restarts at the sign-in
    assert r["last"] == 1 and r["steps"] == [7]  # not again until 480 s old; lastStep passed on
