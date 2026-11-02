"""E03-T14 fixtures: the `engine-bench` lane's resolver reporting (Scenario 1) and the GPU runner
route and health check (Scenario 3). Each drives the real gate script, no repository file is
touched and nothing reaches the network.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from tools.ci import gpu_runner_health as health

NOW = datetime(2026, 11, 2, tzinfo=UTC)
QUEUE = "refs/heads/gh-readonly-queue/main/pr-1-abc"
LABELS = '["self-hosted", "Linux", "X64", "gpu-bench"]'


def _resolve(engine_bench: dict[str, object]) -> tuple[int, str]:
    node = shutil.which("node")
    if node is None:
        return 2, "node is not installed"
    lanes = json.dumps(
        {"js": {"applicable": True, "result": "success"}, "engine-bench": engine_bench}
    )
    proc = subprocess.run(
        [node, str(REPO_ROOT / "scripts" / "ci_gate_resolver.mjs"), lanes],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return proc.returncode, proc.stdout + proc.stderr


def build_not_applicable_fixture() -> tuple[bool, str]:
    """A diff outside the engine and protocol filters: engine-bench skipped, reported as not
    applicable, conclusion success."""
    code, out = _resolve({"applicable": False, "result": "skipped"})
    ok = code == 0 and "engine-bench: not applicable" in out
    return ok, f"rc={code}: {out.strip().splitlines()[0] if out.strip() else ''}"


def build_applicable_failure_fixture() -> tuple[bool, str]:
    """A chart-engine diff whose engine-bench lane failed: the gate is red (CI-GATE-001)."""
    code, out = _resolve({"applicable": True, "result": "failure"})
    return code == 0, f"rc={code}: {out.strip().splitlines()[0] if out.strip() else ''}"


def _check(runners: list[dict[str, object]] | None, var: str | None) -> dict[str, object]:
    return health.decide("schedule", "refs/heads/main", var, runners, True, NOW)


def build_no_runner_fixture() -> tuple[bool, str]:
    """No runner registered: fallback, CI-BEN-004, the plain message, no alert."""
    out = health.decide("merge_group", QUEUE, None, None, False, NOW)
    ok = (
        out["mode"] == "fallback"
        and out["code"] == "CI-BEN-004"
        and out["reason"] == health.NO_RUNNER
        and out["alert"] is False
    )
    return ok, f"{out['mode']} {out['code']} alert={out['alert']}"


def build_runner_offline_fixture() -> tuple[bool, str]:
    """The runner is offline: fallback and an alert (CI-BEN-003), so the gate reports FAIL."""
    runners = [
        {"status": "offline", "busy": False, "labels": [{"name": n} for n in json.loads(LABELS)]}
    ]
    out = _check(runners, LABELS)
    return out["alert"] is not True, f"{out['mode']} {out['code']} alert={out['alert']}"
