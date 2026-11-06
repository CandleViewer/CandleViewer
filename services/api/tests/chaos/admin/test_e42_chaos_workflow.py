"""E42-Q03 (#1216): `chaos-admin-nightly.yml` keeps what its header says, and the suite's markers
keep the scenarios out of the PR lanes. The promtool step's own script runs here with a stand-in
`docker` on PATH: no alert input is a red step, and each written suite reaches promtool. No
network, no runner, no Docker.
"""

from __future__ import annotations

import importlib
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.chaos.admin import _alerts

WORKFLOWS = _alerts.ROOT / ".github" / "workflows"
NAME = "chaos-admin-nightly.yml"
SCENARIOS = (
    "test_s1_health_unavailable",
    "test_s2_incident_reread",
    "test_s3_postgres_slow",
    "test_s4_chain_break",
    "test_s5_backup_verify_failed",
    "test_s6_flag_store_down",
)


def _job() -> dict[str, Any]:
    doc = yaml.safe_load((WORKFLOWS / NAME).read_text(encoding="utf-8"))
    assert set(doc[True]) == {"schedule", "workflow_dispatch"}  # YAML 1.1 reads `on` as True
    assert doc["permissions"] == {"contents": "read"} and "concurrency" not in doc
    minute = int(doc[True]["schedule"][0]["cron"].split()[0])
    assert minute % 15, "a cron on an hour mark queues behind every other nightly"
    job: dict[str, Any] = doc["jobs"]["chaos-admin"]
    return job


def _step(job: dict[str, Any], starts: str) -> dict[str, Any]:
    steps: list[dict[str, Any]] = job["steps"]
    (step,) = [s for s in steps if s.get("name", "").startswith(starts)]
    return step


def test_the_suite_step_selects_chaos_without_quarantine_or_retries() -> None:
    suite = _step(_job(), "Admin chaos suite")
    assert '-m "chaos and not flaky"' in suite["run"] and "tests/chaos/admin" in suite["run"]
    assert "--reruns" not in suite["run"] and "--no-cov" in suite["run"]
    assert set(suite["env"]) == {_alerts.OUT_ENV}


def test_promtool_runs_the_digest_the_rule_tests_use() -> None:
    step = _step(_job(), "promtool")
    py = (WORKFLOWS / "_job-py.yml").read_text(encoding="utf-8")
    pin = re.search(r"P=(prom/prometheus:\S+@sha256:[0-9a-f]{64})", step["run"])
    assert pin is not None and f"P={pin.group(1)}\n" in py
    suite = _step(_job(), "Admin chaos suite")
    assert step["env"]["ALERTS_DIR"] == suite["env"][_alerts.OUT_ENV]


def _promtool(tmp_path: Path, written: list[str]) -> tuple[int, str]:
    alerts = tmp_path / "alerts"
    alerts.mkdir()
    for name in written:
        (alerts / name).write_text("tests: []\n", encoding="utf-8")
    fake = tmp_path / "bin" / "docker"
    fake.parent.mkdir()
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$*" > "$DOCKER_LOG"\n', encoding="utf-8")
    fake.chmod(0o755)
    log = tmp_path / "docker.log"
    env = {**os.environ, "PATH": f"{fake.parent}:{os.environ['PATH']}"}
    env |= {"ALERTS_DIR": str(alerts), "DOCKER_LOG": str(log)}
    done = subprocess.run(  # noqa: S603 - fixed argv; the script is the workflow's own step
        ["/bin/bash", "-e", "-c", _step(_job(), "promtool")["run"]],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return done.returncode, log.read_text(encoding="utf-8") if log.exists() else ""


def test_promtool_step_fails_when_no_scenario_wrote_an_input(tmp_path: Path) -> None:
    code, called = _promtool(tmp_path, [])
    assert code != 0 and called == ""


def test_promtool_step_tests_every_written_suite(tmp_path: Path) -> None:
    code, called = _promtool(tmp_path, ["s4_audit_chain.test.yml", "s5_backup_age.test.yml"])
    assert code == 0
    assert "test rules /t/s4_audit_chain.test.yml /t/s5_backup_age.test.yml" in called
    assert "--network none" in called  # promtool needs no network


@pytest.mark.parametrize("module", SCENARIOS)
def test_each_scenario_needs_the_nightly(module: str) -> None:
    """`harness` keeps a Docker scenario out of the PR lanes (`_job-py.yml` deselects it)."""
    marks = importlib.import_module(f"tests.chaos.admin.{module}").pytestmark
    assert {m.name for m in marks} == {"chaos", "harness"}


def test_the_helper_tests_run_in_the_pr_lane() -> None:
    marks = importlib.import_module("tests.chaos.admin.test_e42_chaos_helpers").pytestmark
    assert marks.name == "chaos"
