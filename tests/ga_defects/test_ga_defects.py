"""E49-T02 unit tests: forecasts, ledger exporter, metrics/push, snapshot, dashboard+alert pins. Offline."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped,unused-ignore]  # stubs not a dependency (as tools/triage/sla.py)

from tools.ga_defects import forecast as fc
from tools.ga_defects import ledger, metrics, run

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures" / "ga_defects"
D0 = date(2027, 3, 1)


def series(values: list[float], step: int = 7) -> list[fc.Point]:
    return [(D0 + timedelta(days=i * step), v) for i, v in enumerate(values)]


# ---- forecasts ----------------------------------------------------------------------
def test_linear_converging_projects_zero_date() -> None:
    f = fc.linear_zero_date(series([30, 20, 10, 5], step=7))
    assert f.reason == "ok" and f.when is not None and f.when > D0 + timedelta(days=21)


def test_linear_exact_line_hits_expected_day() -> None:
    f = fc.linear_zero_date(
        [(D0 + timedelta(days=i), 20.0 - i) for i in range(0, 15, 2)]
    )
    assert f.when == D0 + timedelta(days=20)


def test_flat_series_is_undefined() -> None:
    for fn in (fc.linear_zero_date, fc.trailing_rate_zero_date):
        assert fn(series([10, 10, 10])) == fc.Forecast(None, "not-converging")


def test_diverging_series_is_undefined() -> None:
    for fn in (fc.linear_zero_date, fc.trailing_rate_zero_date):
        assert fn(series([5, 10, 20])).when is None


def test_sparse_and_single_point_are_undefined() -> None:
    assert fc.linear_zero_date(series([9])).reason == "insufficient-data"
    assert fc.trailing_rate_zero_date(series([9])).reason == "insufficient-data"
    assert (
        fc.linear_zero_date(series([9, 8])).reason == "insufficient-data"
    )  # < 3 points
    short = [(D0, 9.0), (D0 + timedelta(days=2), 5.0), (D0 + timedelta(days=3), 1.0)]
    assert fc.linear_zero_date(short).reason == "insufficient-data"  # < 7 day span
    assert fc.linear_zero_date([]).when is None


def test_already_zero_reports_zero_reached() -> None:
    f = fc.trailing_rate_zero_date(series([4, 2, 0]))
    assert f.reason == "zero-reached" and f.when == D0 + timedelta(days=14)


def test_trailing_rate_projection_and_window() -> None:
    f = fc.trailing_rate_zero_date(series([30, 20, 10]))  # 10/week
    assert f.when == D0 + timedelta(days=14 + 7)
    old = [
        (D0 - timedelta(days=200), 99.0),
        *series([30, 20, 10]),
    ]  # outside window, ignored
    assert fc.trailing_rate_zero_date(old) == f


def test_linear_fit_below_zero_clamps_to_last_point() -> None:
    pts = [(D0, 10.0), (D0 + timedelta(days=7), 0.5), (D0 + timedelta(days=14), 0.6)]
    assert fc.linear_zero_date(pts).reason in {"ok", "not-converging"}
    steep = [(D0, 50.0), (D0 + timedelta(days=8), 1.0), (D0 + timedelta(days=9), 1.0)]
    assert fc.linear_zero_date(steep).when is not None


def test_excess_open_and_days_to_zero() -> None:
    assert fc.excess_open(0, 0, 10) == 0 and fc.excess_open(1, 2, 14) == 7
    assert fc.days_to_zero(fc.Forecast(None, "x"), D0) is None
    assert fc.days_to_zero(fc.Forecast(D0 + timedelta(days=3), "ok"), D0) == 3


# ---- ledger -------------------------------------------------------------------------
def test_ledger_counts_open_by_severity_and_skips_malformed() -> None:
    c = ledger.parse_ledger(FIX / "ledger.csv")
    assert c is not None
    assert c.open_by_severity == {"P0": 0, "P1": 1, "P2": 2, "P3": 0}
    assert c.malformed_rows == 3  # bad severity, short row, blank id


def test_ledger_missing_file_is_none_not_zero(tmp_path: Path) -> None:
    assert ledger.parse_ledger(tmp_path / "nope.csv") is None


def test_ledger_bad_header_raises(tmp_path: Path) -> None:
    f = tmp_path / "l.csv"
    f.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="header"):
        ledger.parse_ledger(f)
    f.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="header"):
        ledger.parse_ledger(f)


def test_ledger_ignores_blank_lines(tmp_path: Path) -> None:
    f = tmp_path / "l.csv"
    f.write_text(
        ",".join(ledger.HEADER) + "\n\nX,P1,open,c,2026-10-01\n", encoding="utf-8"
    )
    c = ledger.parse_ledger(f)
    assert c is not None and c.open_by_severity["P1"] == 1 and c.malformed_rows == 0


# ---- metrics / push -----------------------------------------------------------------
def test_render_ledger_and_defects_text() -> None:
    assert 'design_qa_findings_open{severity="P1"} 1' in metrics.render_ledger(
        {"P1": 1}
    )
    s = metrics.DefectSnapshot(
        open_by_severity={"P1": 2},
        open_by_component={"oms": 1},
        arrived_7d=3,
        closed_7d=1,
        untriaged=1,
        sla={("P1", "sla-breached"): 1},
        ages_days={"P1": [0.5, 10.0]},
        forecast_days={"linear": 12},
    )
    t = metrics.render_defects(s)
    assert 'ga_defects_open{severity="P1"} 2' in t
    assert 'ga_defect_age_days_bucket{severity="P1",le="1"} 1' in t
    assert 'ga_defect_age_days_bucket{severity="P1",le="+Inf"} 2' in t
    assert 'ga_defect_forecast_days_to_zero{method="linear"} 12' in t
    assert "trailing_3w" not in t  # undefined forecast is absent, never 0


def test_push_retries_then_succeeds() -> None:
    calls: list[str] = []
    sleeps: list[float] = []

    def flaky(url: str, body: bytes) -> None:
        calls.append(url)
        if len(calls) < 3:
            raise OSError("down")

    metrics.push("http://pg:9091/", "j", "x 1\n", flaky, sleep=sleeps.append)
    assert calls[-1] == "http://pg:9091/metrics/job/j" and sleeps == [1, 2]


def test_push_unavailable_raises_loudly() -> None:
    def down(url: str, body: bytes) -> None:
        raise OSError("down")

    with pytest.raises(metrics.PushError):
        metrics.push("http://pg", "j", "x 1\n", down, sleep=lambda _s: None)


def test_cmd_ledger_paths(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sent: list[bytes] = []
    assert (
        run.cmd_ledger(FIX / "ledger.csv", "http://pg", lambda u, b: sent.append(b))
        == 0
    )
    assert b'design_qa_findings_open{severity="P2"} 2' in sent[0]
    assert "malformed" in capsys.readouterr().err
    assert (
        run.cmd_ledger(tmp_path / "x.csv", "http://pg", lambda u, b: sent.append(b))
        == 1
    )
    assert len(sent) == 1  # missing ledger pushes nothing


def test_main_unset_pushgateway_skips_with_notice(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("PUSHGATEWAY_URL", raising=False)
    path = str(FIX / "ledger.csv")
    assert run.main(["ledger", "--path", path]) == 0
    assert "::notice::" in capsys.readouterr().out
    assert run.main(["ledger", "--path", path, "--require-push"]) == run.EXIT_NO_PUSH


def test_main_bad_ledger_header_clean_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "l.csv"
    bad.write_text("a,b\n", encoding="utf-8")
    monkeypatch.setenv("PUSHGATEWAY_URL", "http://pg")
    assert run.main(["ledger", "--path", str(bad)]) == run.EXIT_LEDGER_SCHEMA
    assert "E_LEDGER_SCHEMA" in capsys.readouterr().err


def test_main_ledger_push_failure_exit_1(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(url: str, body: bytes) -> None:
        raise OSError("x")

    monkeypatch.setenv("PUSHGATEWAY_URL", "http://pg")
    monkeypatch.setattr(metrics, "http_transport", boom)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    assert run.main(["ledger", "--path", str(FIX / "ledger.csv")]) == 1


# ---- snapshot -----------------------------------------------------------------------
NOW = datetime(2027, 3, 8, 12, tzinfo=timezone.utc)


def issue(
    n: int, sev: str, created: str, closed: str | None = None, *labels: str
) -> dict[str, Any]:
    return {
        "number": n,
        "body": "",
        "created_at": created,
        "closed_at": closed,
        "labels": [
            {"name": x} for x in ("type/bug", f"priority/{sev.lower()}", *labels)
        ],
    }


def test_build_snapshot_counts_and_history() -> None:
    issues = [
        issue(1, "P1", "2027-02-10T00:00:00Z", None, "area/oms", "triaged"),
        issue(2, "P2", "2027-03-06T00:00:00Z", None, "area/oms"),
        issue(3, "P0", "2027-02-01T00:00:00Z", "2027-03-07T00:00:00Z"),
    ]
    snap = run.build_snapshot(
        issues, NOW, lambda i: "sla-breached" if i["number"] == 2 else "ok"
    )
    assert snap.open_by_severity["P1"] == 1 and snap.open_by_severity["P2"] == 1
    assert snap.open_by_component == {"oms": 2}
    assert (snap.arrived_7d, snap.closed_7d, snap.untriaged) == (1, 1, 1)
    assert snap.sla == {("P2", "sla-breached"): 1}
    assert run.history(issues, NOW.date())[0][1] == 2.0  # P0 + P1 open 21 days ago


def test_weekly_section_and_idempotent_append(tmp_path: Path) -> None:
    snap = metrics.DefectSnapshot(
        open_by_severity={"P1": 1}, forecast_days={"linear": 10}
    )
    text = run.weekly_section(snap, NOW, run.GA_DATE)
    assert "2027-03-18" in text and "trailing_3w: undefined" in text
    log = tmp_path / "log.md"
    log.write_text("# log\n", encoding="utf-8")
    assert run.append_weekly(log, text, "2027-03-08") is True
    assert run.append_weekly(log, text, "2027-03-08") is False
    assert log.read_text(encoding="utf-8").count("GA defect snapshot") == 1


class FakeApi:
    def __init__(self) -> None:
        self.paths: list[str] = []

    def call(self, method: str, path: str) -> list[dict[str, Any]]:
        self.paths.append(path)
        if "state=open" in path:
            return [issue(1, "P1", "2027-03-07T00:00:00Z", None, "area/oms")]
        return [issue(2, "P2", "2027-03-01T00:00:00Z", "2027-03-07T00:00:00Z")]


def test_cmd_defects_pushes_and_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRIAGE_CALENDAR_PATH", str(ROOT / "tools/triage/calendar.yml"))
    log = tmp_path / "log.md"
    log.write_text("# log\n", encoding="utf-8")
    sent: list[bytes] = []
    api = FakeApi()
    assert (
        run.cmd_defects(api, "http://pg", lambda u, b: sent.append(b), log, run.GA_DATE)
        == 0
    )
    assert b'ga_defects_open{severity="P1"} 1' in sent[0]
    assert "GA defect snapshot" in log.read_text(encoding="utf-8")
    assert len(api.paths) == 2


def test_cmd_defects_unset_url_still_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRIAGE_CALENDAR_PATH", str(ROOT / "tools/triage/calendar.yml"))
    log = tmp_path / "log.md"
    log.write_text("# log\n", encoding="utf-8")
    assert run.cmd_defects(FakeApi(), "", lambda u, b: None, log, run.GA_DATE) == 0
    assert "GA defect snapshot" in log.read_text(encoding="utf-8")
    assert (
        run.cmd_defects(
            FakeApi(), "", lambda u, b: None, log, run.GA_DATE, require_push=True
        )
        == run.EXIT_NO_PUSH
    )


def test_fetch_bugs_since_only_on_closed() -> None:
    api = FakeApi()
    run.fetch_bugs(api)
    open_q = next(p for p in api.paths if "state=open" in p)
    closed_q = next(p for p in api.paths if "state=closed" in p)
    assert "since=" not in open_q  # an untouched old open bug must still be counted
    assert "since=" in closed_q


# ---- dashboard + alerts pinned to the roadmap --------------------------------------
def test_dashboard_has_target_stale_and_forecast() -> None:
    d = json.loads(
        (ROOT / "infra/grafana/dashboards/ga-defects.json").read_text("utf-8")
    )
    panels = [p for p in d["panels"] if p["type"] not in ("row", "text")]
    assert len(panels) == 9  # 7 required views; forecast is two stats, burn-down one
    burn = panels[0]
    exprs = {t["expr"] for t in burn["targets"]}
    assert "vector(0)" in exprs and "vector(10)" in exprs  # roadmap 9.3 item 3
    assert "2027-03-25" in json.dumps(burn["targets"])
    assert any(
        p["type"] == "stat" and "linear" in json.dumps(p["targets"]) for p in panels
    )
    for p in panels:
        assert (
            "push_time_seconds" in " ".join(t["expr"] for t in p["targets"][-1:])
            or p is burn
        )
        assert p["fieldConfig"]["defaults"]["noValue"].startswith("STALE")


def test_alert_rules_present_with_runbook_and_ga_boundary() -> None:
    doc = yaml.safe_load(
        (ROOT / "infra/prometheus/alerts/ga_defects.yml").read_text("utf-8")
    )
    rules = {r["alert"]: r for r in doc["groups"][0]["rules"]}
    assert set(rules) == {
        "GADefectForecastSlipping",
        "GADefectArrivalExceedsClosure",
        "GADefectSLABreached",
    }
    assert rules["GADefectForecastSlipping"]["for"] == "3d"
    assert (
        "1805932800" in rules["GADefectForecastSlipping"]["expr"]
    )  # 2027-03-25T00:00Z
    assert int(datetime(2027, 3, 25, tzinfo=timezone.utc).timestamp()) == 1805932800
    assert (
        "ga_defects_open_by_component"
        in rules["GADefectArrivalExceedsClosure"]["annotations"]["description"]
    )
    for name in ("GADefectArrivalExceedsClosure", "GADefectSLABreached"):
        assert 'push_time_seconds{job="ga_defects"}' in rules[name]["expr"]
    for r in rules.values():
        assert "e49-triage-ritual.md" in r["annotations"]["description"]
