"""E29-Q03 (#977): perf-oms-nightly.yml, the lane that runs the tests/load/k6/oms kit.

The lane runs nightly and on dispatch, never on a pull request, and no required check reads it
(C-9.1). These pin what its header claims: read-only permissions, no repository secret, k6
installed exactly as perf-ws-load.yml installs it, a loopback target on demo with the account
fixture armed (the synthetic feed, no `CV_BYBIT_API_*`, `order_lane.json` in pack mode), a WS
allow-list holding the script's Origin, the calibration profile once and the gate profile three
times, the +5 % compare on those three, and the artifact kept 14 days. The kit's stdlib halves are
pinned in test_e29_oms_load_tools.py. No k6 run and no database here.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
NAME = "perf-oms-nightly.yml"
KIT = ROOT / "tests" / "load" / "k6" / "oms"


def _wf(name: str) -> dict[Any, Any]:
    doc: dict[Any, Any] = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    return doc


def _job() -> dict[str, Any]:
    job: dict[str, Any] = _wf(NAME)["jobs"]["oms-load"]
    return job


def _step(prefix: str, job: dict[str, Any] | None = None) -> dict[str, Any]:
    steps = (job or _job())["steps"]
    return next(s for s in steps if s.get("name", "").startswith(prefix))


def _launcher() -> str:
    run: str = _step("Start the API")["run"]
    return run[run.index("<<'SH'\n") : run.index("\nSH\n")]


def test_runs_nightly_and_on_dispatch_never_on_a_pr_with_read_only_permissions() -> (
    None
):
    doc = _wf(NAME)
    assert set(doc[True]) == {"schedule", "workflow_dispatch"}
    assert doc["permissions"] == {"contents": "read"}
    assert "permissions" not in _job()
    assert "concurrency" not in doc  # #3449
    text = (WORKFLOWS / NAME).read_text(encoding="utf-8")
    assert "secrets." not in text and "pull_request" not in text


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
    assert "export CV_BIND_HOST=127.0.0.1 " in _launcher()
    checkout = next(
        s for s in _job()["steps"] if s.get("uses", "").startswith("actions/checkout@")
    )
    assert checkout["with"] == {"persist-credentials": False}


def test_the_api_boots_on_demo_with_the_account_fixture_in_pack_mode() -> None:
    sh = _launcher()
    assert "export CV_ENVIRONMENT=demo CV_FEED=synthetic CV_STORAGE_BACKEND=real" in sh
    assert (
        'CV_ACCOUNT_FIXTURE=compliant CV_ACCOUNT_FIXTURE_DIR="$RUNNER_TEMP/cv-fixture"'
        in sh
    )
    assert (
        '{"mode": "pack", "delay_ms": %d' in sh
        and '"$CV_ACCOUNT_FIXTURE_DIR/order_lane.json"' in sh
    )
    text = (WORKFLOWS / NAME).read_text(encoding="utf-8")
    assert not re.search(r"^\s*(export )?CV_BYBIT_API_\w*[:=]", text, re.MULTILINE)
    assert "CV_TEST_CLOCK" not in text
    assert _job()["env"]["CV_E29_FIXTURE_STACK"] == "1"


def test_the_seed_step_runs_on_testnet_because_the_seeder_refuses_anything_else() -> None:
    seed = _step("Migrate")
    assert seed["env"]["CV_ENVIRONMENT"] == "testnet"
    assert "scripts/seed_fixture_user.py" in seed["run"]


def test_every_run_credential_is_masked() -> None:
    creds = _step("Make this run's synthetic credentials")["run"]
    assert 'echo "::add-mask::$v"' in creds and "CV_E29_PASSWORD" in creds
    assert (
        'echo "::add-mask::$(cat "$RUNNER_TEMP/cv/owner.totp")"'
        in _step("Migrate")["run"]
    )


def test_the_api_allows_the_origin_the_script_sends() -> None:
    script = (KIT / "oms_submit_ack.js").read_text(encoding="utf-8")
    m = re.search(r'^const ORIGIN = "([^"]+)";', script, re.MULTILINE)
    assert m
    allowed = re.search(r"^export CV_ALLOWED_ORIGINS=(\S+)$", _launcher(), re.MULTILINE)
    assert allowed and m.group(1) in allowed.group(1).split(",")


def test_the_arm_writes_only_the_account_and_price_and_derives_the_pack_secret() -> (
    None
):
    js = (KIT / "arm_account.js").read_text(encoding="utf-8")
    assert (
        "fixture-compliant-secret" not in js
    )  # derived by the pack's rule, never a literal
    assert '"-secret-not-real")' in js
    assert "return { account_id: account, price:" in js
    assert "JSON.stringify(data.setup_data || {})" in js
    run = _step("Arm the demo account")["run"]
    assert (
        "k6 run --quiet tests/load/k6/oms/arm_account.js" in run and "sleep 31" in run
    )


def test_calibrate_runs_once_then_the_gate_three_times_on_a_restarted_pack() -> None:
    env = _job()["env"]
    assert (env["CALIBRATE_DELAY_MS"], env["GATE_DELAY_MS"]) == ("100", "40")
    # four runs of CV_E29_MAX_ORDERS stay inside the profile's 500 concurrent orders
    assert 4 * int(env["CV_E29_MAX_ORDERS"]) <= 500
    cal = _step("Calibration profile")
    assert cal["env"]["CV_E29_PROFILE"] == "calibrate"
    assert cal["env"]["CV_E29_PACK_DELAY_MS"] == "${{ env.CALIBRATE_DELAY_MS }}"
    assert cal["run"] == "k6 run tests/load/k6/oms/oms_submit_ack.js"
    restart = _step("Restart the API on the gate pack")
    assert 'bash "$RUNNER_TEMP/cv/api.sh" "$GATE_DELAY_MS" 10' in restart["run"]
    gate = _step("Gate profile")
    assert gate["env"]["CV_E29_PROFILE"] == "gate"
    assert gate["env"]["CV_E29_PACK_DELAY_MS"] == "${{ env.GATE_DELAY_MS }}"
    assert "for i in 1 2 3; do" in gate["run"] and "steps.restart.outcome" in gate["if"]
    assert "continue-on-error" not in gate and "continue-on-error" not in cal


def test_the_regression_gate_compares_the_three_gate_runs() -> None:
    step = _step("Regression gate")
    assert "steps.gate.outcome" in step["if"]
    run = step["run"]
    assert (
        "tests/load/k6/oms/compare_baseline.py --baseline tests/load/k6/oms/baseline.json"
        in run
    )
    for i in (1, 2, 3):
        assert f'"$OUT"/run-{i}/k6-summary-oms-submit-ack.json' in run
    assert "calibrate" not in run
    assert 'cat "$OUT/compare.md" >> "$GITHUB_STEP_SUMMARY"' in run


def test_tear_down_stops_the_api_and_removes_every_run_temp_dir() -> None:
    run = _step("Tear down")["run"]
    assert "api.pid" in run
    for d in ("cv-kek", "cv-lane", "cv-fixture", "cv"):
        assert f'"$RUNNER_TEMP/{d}"' in run


def test_the_artifact_is_kept_14_days() -> None:
    ups = [s for s in _job()["steps"] if "upload-artifact" in s.get("uses", "")]
    assert [u["with"]["retention-days"] for u in ups] == [14]
    assert ups[0]["with"]["path"] == "oms-load/"
