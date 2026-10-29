"""E04-S01 tests: dashboards are valid, in sync with the generator, and lint-clean."""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import yaml

G = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(G))

import generate_dashboards as gen
import lint_dashboards as lint
import snapshot_export as snap


def _rules_with(expr: str, tmp_path: Path, uid: str = "cv-prometheus") -> list[str]:
    d = json.loads((G / "dashboards" / "rules.json").read_text("utf-8"))
    panel = next(p for p in d["panels"] if p["type"] == "timeseries")
    panel["targets"][0]["expr"] = expr
    panel["datasource"]["uid"] = uid
    f = tmp_path / "rules.json"
    f.write_text(json.dumps(d), "utf-8")
    return lint.lint_dashboard(f, lint.catalogue_names())


def test_all_registered_dashboards_committed_and_lint_clean() -> None:
    assert len(list((G / "dashboards").glob("*.json"))) == len(gen.BOARDS)
    assert lint.lint() == []


def test_committed_json_matches_generator_output() -> None:
    for name, text in gen.render().items():
        assert (G / "dashboards" / name).read_text("utf-8") == text, name


def test_lint_names_panel_and_typo_metric(tmp_path: Path) -> None:
    errs = _rules_with(
        'rate(rule_evaluatoins_total{env="$env"}[$__rate_interval])', tmp_path
    )
    assert any("rule_evaluatoins_total" in e and "Evaluations/s" in e for e in errs)


def test_lint_rejects_fixed_range_and_unknown_datasource(tmp_path: Path) -> None:
    errs = _rules_with(
        'rate(rule_evaluations_total{env="$env"}[1m])', tmp_path, "other"
    )
    assert any("fixed range" in e for e in errs)
    assert any("datasource" in e for e in errs)


def test_every_dashboard_has_env_variable_and_deploy_annotation() -> None:
    for f in (G / "dashboards").glob("*.json"):
        d = json.loads(f.read_text("utf-8"))
        assert d["templating"]["list"][0]["name"] == "env"
        assert d["annotations"]["list"][0]["expr"].startswith("changes(build_info")
        assert d["editable"] is False


def test_provider_is_read_only_and_datasource_uid_matches() -> None:
    prov = yaml.safe_load(
        (G / "provisioning/dashboards/dashboards.yml").read_text("utf-8")
    )
    assert prov["providers"][0]["allowUiUpdates"] is False
    ds = yaml.safe_load(
        (G / "provisioning/datasources/datasource.yml").read_text("utf-8")
    )
    assert ds["datasources"][0]["uid"] == lint.DATASOURCE_UID


def test_snapshot_export_writes_stripped_models(tmp_path: Path) -> None:
    def fetch(path: str) -> dict:
        if path.startswith("/api/search"):
            return [{"uid": "cv-rules"}]  # type: ignore[return-value]
        return {"dashboard": {"uid": "cv-rules", "id": 7, "version": 3}}

    out = snap.export(fetch, tmp_path, dt.date(2026, 10, 1))
    assert out == [tmp_path / "2026-10-01" / "cv-rules.json"]
    assert json.loads(out[0].read_text("utf-8")) == {"uid": "cv-rules"}


def test_lint_env_filter_not_bypassed_by_external_name(tmp_path: Path) -> None:
    errs = _rules_with(
        "rate(rule_evaluations_total[$__rate_interval]) + ALERTS", tmp_path
    )
    assert any("env filter" in e for e in errs)


def test_lint_requires_thresholds_and_catalogue_non_empty(tmp_path: Path) -> None:
    d = json.loads((G / "dashboards" / "rules.json").read_text("utf-8"))
    panel = next(p for p in d["panels"] if p["type"] == "timeseries")
    panel["fieldConfig"]["defaults"].pop("thresholds")
    f = tmp_path / "rules.json"
    f.write_text(json.dumps(d), "utf-8")
    assert any(
        "no thresholds" in e for e in lint.lint_dashboard(f, lint.catalogue_names())
    )
    assert len(lint.catalogue_names()) >= 10


def test_snapshot_export_end_to_end_over_http(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            assert self.headers["Authorization"].startswith("Basic ")
            body = (
                [{"uid": "cv-rules"}]
                if self.path.startswith("/api/search")
                else {"dashboard": {"uid": "cv-rules", "id": 1, "version": 2}}
            )
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a: object) -> None:
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("GF_SECURITY_ADMIN_USER", "u")
    monkeypatch.setenv("GF_SECURITY_ADMIN_PASSWORD", "p")
    try:
        out = snap.export(
            snap._http_fetch(f"http://127.0.0.1:{srv.server_port}"),
            tmp_path,
            dt.date(2026, 10, 1),
        )
    finally:
        srv.shutdown()
    assert json.loads(out[0].read_text("utf-8")) == {"uid": "cv-rules"}
    assert "snapshot_export.py" in (G / "snapshot-export.cron").read_text("utf-8")


def test_lint_cli_exits_nonzero_on_typo_metric(tmp_path: Path) -> None:
    import subprocess

    d = tmp_path / "dashboards"
    d.mkdir()
    for f in (G / "dashboards").glob("*.json"):
        (d / f.name).write_text(f.read_text("utf-8"), "utf-8")
    bad = json.loads((d / "rules.json").read_text("utf-8"))
    panel = next(p for p in bad["panels"] if p["type"] == "timeseries")
    panel["targets"][0]["expr"] = (
        'rate(no_such_metric_total{env="$env"}[$__rate_interval])'
    )
    (d / "rules.json").write_text(json.dumps(bad), "utf-8")
    code = (
        "import sys; sys.path.insert(0, %r); import lint_dashboards as l; "
        "from pathlib import Path; "
        "e = l.lint(Path(%r)); print(e); sys.exit(1 if e else 0)"
    ) % (str(G), str(d))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 1 and "no_such_metric_total" in r.stdout


def test_lint_flags_unknown_recording_rule(tmp_path: Path) -> None:
    d = json.loads((G / "dashboards" / "frontend.json").read_text("utf-8"))
    next(p for p in d["panels"] if "targets" in p)["targets"][0]["expr"] = (
        'cv:slo_x:burn_rate_1h{env="$env"}'
    )
    f = tmp_path / "frontend.json"
    f.write_text(json.dumps(d), "utf-8")
    errs = lint.lint_dashboard(f, lint.catalogue_names(), {"cv:other:rule"})
    assert any("cv:slo_x:burn_rate_1h" in e for e in errs)
    assert (
        lint.lint_dashboard(f, lint.catalogue_names(), {"cv:slo_x:burn_rate_1h"}) == []
    )


def test_dashboards_do_not_depend_on_recording_rules() -> None:
    for f in (G / "dashboards").glob("*.json"):
        assert "cv:" not in f.read_text("utf-8"), f.name


def test_trading_board_shows_the_account_and_api_key_row_gauges() -> None:
    """#2314 (E27-T01 DoD): both M13 row gauges are on a provisioned board, env-filtered."""
    d = json.loads((G / "dashboards" / "trading.json").read_text("utf-8"))
    exprs = [t["expr"] for p in d["panels"] for t in p.get("targets", [])]
    for metric in ("cv_accounts_rows", "cv_api_keys_rows"):
        assert any(metric in e and 'env="$env"' in e for e in exprs), metric
        assert metric in lint.catalogue_names()


def test_trading_board_shows_account_health_wallet_freshness_and_key_age() -> None:
    """#837 (E27-T04): its series are on the trading board, env-filtered, and each panel of
    theirs with a threshold draws it as a dashed line: colour is never the only signal."""
    d = json.loads((G / "dashboards" / "trading.json").read_text("utf-8"))
    names = (
        "cv_account_health_state",
        "cv_account_health_transitions_total",
        "cv_wallet_snapshot_age_seconds",
        "cv_wallet_reconcile_total",
        "cv_wallet_sizing_old_snapshot_total",
        "cv_keys_rotation_state",
    )
    ours = [
        p
        for p in d["panels"]
        if any(n in t["expr"] for t in p.get("targets", []) for n in names)
    ]
    exprs = [t["expr"] for p in ours for t in p["targets"]]
    for metric in names:
        assert any(metric in e and 'env="$env"' in e for e in exprs), metric
    lined = [p for p in ours if len(p["fieldConfig"]["defaults"]["thresholds"]["steps"]) > 1]
    styles = [p["fieldConfig"]["defaults"]["custom"]["thresholdsStyle"] for p in lined]
    assert styles and all(style == {"mode": "dashed"} for style in styles)


def test_recorder_board_has_the_ticket_panels_env_filtered_with_the_disk_ladder() -> None:
    """#567 (E16-T09): each listed panel reads its series env-filtered; the disk panel draws the
    80 / 90 / 95 % ladder as dashed lines."""
    d = json.loads((G / "dashboards" / "recorder.json").read_text("utf-8"))
    panels = [p for p in d["panels"] if "targets" in p]
    exprs = [" ".join(t["expr"] for t in p["targets"]) for p in panels]
    for metric in ("recorder_bytes_written_total", "recorder_rows_total", "ingest_lag_seconds",
                   "trade_writes_dropped_total", "recorder_write_backlog_rows", "recorder_spill_bytes",
                   "disk_used_ratio", "recorder_projected_full_timestamp", "trade_gaps_total",
                   "recorder_watermark_lag_days"):  # fmt: skip
        assert any(metric in e for e in exprs), metric
    assert all(e.count('env="$env"') == e.count("{") for e in exprs)
    disk = next(p for p in panels if p["title"].startswith("Disk used"))["fieldConfig"]["defaults"]
    assert [s["value"] for s in disk["thresholds"]["steps"]] == [None, 0.8, 0.9, 0.95]
    assert disk["custom"]["thresholdsStyle"] == {"mode": "dashed"}


def test_the_trading_board_shows_the_profile_save_series() -> None:
    """#906 (E28-T02 D3c): the Account profiles row draws D3b's save series and the catalogue's
    refresh counter, each env-filtered and summed by result or rule only, never per account,
    profile or principal; the save p95 draws its 1.5 s deadline and SCR-131's 2 s budget as
    dashed lines."""
    d = json.loads((G / "dashboards" / "trading.json").read_text("utf-8"))
    at = next(i for i, p in enumerate(d["panels"]) if p["title"] == "Account profiles")
    ours = []
    for p in d["panels"][at + 1 :]:  # the row's panels, up to the next row
        if p["type"] == "row":
            break
        ours.append(p)
    sums_by = {
        "cv_profile_saves_total": "result",
        "cv_profile_validation_failures_total": "rule",
        "cv_profile_save_seconds_bucket": "le",
        "instruments_refresh_total": "result",
    }
    drawn = {}
    for p in ours:
        (expr,) = [t["expr"] for t in p["targets"]]
        (metric,) = [m for m in sums_by if m in expr]
        # the "(" before rate keeps irate( (or any other prefix) from passing
        assert f'(rate({metric}{{env="$env"}}[$__rate_interval]))' in expr, expr
        assert f"sum by ({sums_by[metric]}) (" in expr and expr.count("by (") == 1, expr
        drawn[metric] = p
    assert (len(ours), sorted(drawn)) == (4, sorted(sums_by))
    # saves/s, refusals/s, the p95, refreshes/s: the p95 alone is in seconds
    units = [p["fieldConfig"]["defaults"]["unit"] for p in ours]
    assert units == ["ops", "ops", "s", "ops"]
    assert all(m.removesuffix("_bucket") in lint.catalogue_names() for m in sums_by)
    p95 = drawn["cv_profile_save_seconds_bucket"]
    defaults = p95["fieldConfig"]["defaults"]
    assert p95["targets"][0]["expr"].startswith("histogram_quantile(0.95, ")
    assert defaults["unit"] == "s"
    assert [s["value"] for s in defaults["thresholds"]["steps"]] == [None, 1.5, 2.0]
    assert defaults["custom"]["thresholdsStyle"] == {"mode": "dashed"}
    assert p95.get("description")
    assert drawn["instruments_refresh_total"].get("description")


def test_the_trading_board_shows_the_trade_group_and_sizer_series() -> None:
    """#909 (E28-T05): the Trade groups row draws the preview's three series, the widenings
    refused by cap and E28-T03's four sizer series, each env-filtered and summed by its own labels
    alone (outcome, reason or cap), never per account, profile or principal; the preview p95 draws
    SCR-061's 300 ms and the sizing p95 the 1 ms per-leg budget as dashed lines."""
    d = json.loads((G / "dashboards" / "trading.json").read_text("utf-8"))
    at = next(i for i, p in enumerate(d["panels"]) if p["title"] == "Trade groups")
    ours = []
    for p in d["panels"][at + 1 :]:  # the row's panels, up to the next row
        if p["type"] == "row":
            break
        ours.append(p)
    sums_by = {
        "cv_tradegroup_preview_total": "outcome",
        "cv_tradegroup_preview_seconds_bucket": "le",
        "cv_tradegroup_legs_skipped_total": "reason",
        "cv_override_refused_total": "cap",
        "cv_sizer_duration_seconds_bucket": "le",
        "cv_sizer_outcomes_total": "outcome, reason",
        "cv_sizer_clamped_total": "cap",
        "cv_sizer_stop_fallback_total": "",  # one series: summed over replicas
    }
    drawn = {}
    for p in ours:
        (expr,) = [t["expr"] for t in p["targets"]]
        (metric,) = [m for m in sums_by if m in expr]
        # the "(" before rate keeps irate( (or any other prefix) from passing
        assert f'(rate({metric}{{env="$env"}}[$__rate_interval]))' in expr, expr
        by = sums_by[metric]
        summed = f"sum by ({by}) (" if by else "sum(rate("
        assert summed in expr and expr.count("by (") == (1 if by else 0), expr
        drawn[metric] = p
    assert (len(ours), sorted(drawn)) == (8, sorted(sums_by))
    # previews/s, its p95, skipped legs/s, refusals/s, sizing p95, sized legs/s, clamps/s, falls/s
    units = [p["fieldConfig"]["defaults"]["unit"] for p in ours]
    assert units == ["ops", "s", "ops", "ops", "s", "ops", "ops", "ops"]
    assert all(m.removesuffix("_bucket") in lint.catalogue_names() for m in sums_by)
    for metric, budget in (
        ("cv_tradegroup_preview_seconds_bucket", 0.3),
        ("cv_sizer_duration_seconds_bucket", 0.001),
    ):
        p95 = drawn[metric]
        defaults = p95["fieldConfig"]["defaults"]
        assert p95["targets"][0]["expr"].startswith("histogram_quantile(0.95, ")
        assert [s["value"] for s in defaults["thresholds"]["steps"]] == [None, budget]
        assert defaults["custom"]["thresholdsStyle"] == {"mode": "dashed"}
        assert p95.get("description")
