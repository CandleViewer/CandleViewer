"""E40-Q02 (#1203): perf-alerts-nightly.yml, the lane that runs the tests/load/k6/alerts kit.

The lane runs nightly and on dispatch, never on a pull request, and no required check reads it
(C-9.1). These pin what its header claims: read-only permissions, no repository secret, k6
installed exactly as perf-ws-load.yml installs it, a loopback target whose WS allow-list holds the
subscribers' Origin, the /notifications scenario running and gated (the four-source union is on
main; a recorded deviation from BQ-03's skip default), and the soak report-only behind its one
switch until #5745 (E35-T15) gives the rules metric source a producer. The kit's stdlib halves are pinned in
test_e40_alert_load_tools.py. No k6 run and no database here.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
KIT = ROOT / "tests" / "load" / "k6" / "alerts"


def _wf(name: str) -> dict[Any, Any]:
    doc: dict[Any, Any] = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    return doc


def _job() -> dict[str, Any]:
    job: dict[str, Any] = _wf("perf-alerts-nightly.yml")["jobs"]["alerts-load"]
    return job


def _step(prefix: str, job: dict[str, Any] | None = None) -> dict[str, Any]:
    steps = (job or _job())["steps"]
    return next(s for s in steps if s.get("name", "").startswith(prefix))


def test_runs_nightly_and_on_dispatch_never_on_a_pr_with_read_only_permissions() -> (
    None
):
    doc = _wf("perf-alerts-nightly.yml")
    assert set(doc[True]) == {"schedule", "workflow_dispatch"}
    assert doc["permissions"] == {"contents": "read"}
    assert doc[True]["workflow_dispatch"]["inputs"]["profile"]["options"] == [
        "smoke",
        "soak24h",
    ]
    text = (WORKFLOWS / "perf-alerts-nightly.yml").read_text(encoding="utf-8")
    assert "secrets." not in text and "pull_request" not in text
    assert _step("Refuse a 24 h soak")["if"] == "inputs.profile == 'soak24h'"


def test_k6_is_installed_exactly_as_perf_ws_load_installs_it() -> None:
    ws = _wf("perf-ws-load.yml")["jobs"]["ws-load"]
    name = "Install the pinned k6 (sha256 verified twice)"
    mine, theirs = _step(name)["run"], _step(name, ws)["run"]
    assert mine.replace('echo "$dir" >> "$GITHUB_PATH"', "") == theirs.replace(
        'echo "K6_BIN=$dir/k6" >> "$GITHUB_ENV"', ""
    )
    for key in (
        "K6_VERSION",
        "K6_SHA256",
        "K6_NO_USAGE_REPORT",
        "K6_AUTO_EXTENSION_RESOLUTION",
    ):
        assert _job()["env"][key] == ws["env"][key]


def test_targets_loopback_and_drops_the_checkout_token() -> None:
    assert _job()["env"]["BASE_URL"] == "http://127.0.0.1:8000"
    assert _step("Start the API")["env"]["CV_BIND_HOST"] == "127.0.0.1"
    checkout = next(
        s for s in _job()["steps"] if s.get("uses", "").startswith("actions/checkout@")
    )
    assert checkout["with"] == {"persist-credentials": False}


def test_the_notifications_scenario_runs_in_the_nightly_and_is_gated() -> None:
    step = _step("GET /notifications")
    assert step["run"] == "k6 run tests/load/k6/alerts/notifications_page.js"
    assert "smoke" in step["if"] and "cancelled()" in step["if"]
    assert step["env"]["CV_E40_SUMMARY"].endswith(
        "k6-summary-alerts-notifications.json"
    )
    gate = _step("Regression gate")["run"]
    assert "k6-summary-alerts-notifications.json" in gate


def test_the_api_allows_the_origin_the_ws_subscribers_send() -> None:
    script = (KIT / "ws_subscribers.js").read_text(encoding="utf-8")
    m = re.search(r'^const ORIGIN = "([^"]+)";', script, re.MULTILINE)
    assert m
    allowed = _step("Start the API")["env"]["CV_ALLOWED_ORIGINS"].split(",")
    assert m.group(1) in [o.strip() for o in allowed]


def test_the_soak_is_report_only_behind_one_switch_with_its_blocker_named() -> None:
    assert _job()["env"]["CV_E40_SOAK_GATE"] == "0"
    soak, checks = _step("Soak ("), _step("Soak checks")
    assert "continue-on-error" not in soak  # a crashed soak.js run is never hidden
    assert "report-only" in checks["name"]
    assert (
        "continue-on-error" not in checks
    )  # soak_check.py's exit code reads the switch
    assert "pipefail" in checks["run"]
    text = (WORKFLOWS / "perf-alerts-nightly.yml").read_text(encoding="utf-8")
    assert "PushedMetricSource" in text and "#5745 (E35-T15)" in text
    assert "#5745 (E35-T15)" in checks["name"]
    assert "alert evaluator on" not in text and "synthetic feed" not in text


def test_the_bench_guard_counts_this_workflows_other_24h_soaks_not_its_own_run() -> (
    None
):
    run = _step("Refuse a 24 h soak")["run"]
    assert "perf-alerts-nightly.yml:alerts-load" in run
    assert '[ "$id" = "$GITHUB_RUN_ID" ] && continue' in run
    assert 'any(.labels[]; . == "bench")' in run


def test_tear_down_removes_every_run_temp_dir() -> None:
    run = _step("Tear down")["run"]
    for d in ("cv-kek", "cv-lane", "cv"):
        assert f'"$RUNNER_TEMP/{d}"' in run


def test_the_artifact_is_kept_14_days() -> None:
    ups = [s for s in _job()["steps"] if "upload-artifact" in s.get("uses", "")]
    assert [u["with"]["retention-days"] for u in ups] == [14]
