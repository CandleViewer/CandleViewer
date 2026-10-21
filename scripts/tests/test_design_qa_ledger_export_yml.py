"""#1330 has not committed the E49 design-QA ledger: `design-qa-ledger-export.yml` notes its
absence and succeeds on a scheduled or dispatched run, while a push run, which only a change to the
ledger triggers, still fails as the tool does (`E_LEDGER_MISSING`). A present ledger is exported on
every event. Each case runs the step's own `run:` script under `bash -e`, the runner's default
shell, with no pushgateway URL, so nothing is pushed."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.ga_defects import run

WORKFLOW = ROOT / ".github" / "workflows" / "design-qa-ledger-export.yml"
FIXTURE = ROOT / "tests" / "fixtures" / "ga_defects" / "ledger.csv"
EVENTS = ("schedule", "workflow_dispatch", "push")


def _export() -> tuple[dict[Any, Any], dict[str, Any]]:
    """The workflow (PyYAML reads `on:` as True) and its export step."""
    flow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return flow, flow["jobs"]["export"]["steps"][-1]


def _step(event: str, ledger: Path) -> subprocess.CompletedProcess[str]:
    path = os.pathsep.join((os.path.dirname(sys.executable), os.environ["PATH"]))
    env = {"PATH": path, "LEDGER": str(ledger), "GITHUB_EVENT_NAME": event}
    return subprocess.run(
        ["bash", "-e", "-c", _export()[1]["run"]],
        cwd=ROOT, env=env, capture_output=True, text=True, check=False,
    )  # fmt: skip


def test_the_export_reads_the_ledger_its_trigger_watches() -> None:
    flow, step = _export()
    assert (
        step["env"]["LEDGER"] == str(run.LEDGER_PATH) == flow[True]["push"]["paths"][0]
    )


@pytest.mark.parametrize("event", EVENTS)
def test_a_missing_ledger_is_skipped_unless_a_push_removed_it(
    tmp_path: Path, event: str
) -> None:
    out = _step(event, tmp_path / "none.csv")
    if event == "push":
        assert (out.returncode, "E_LEDGER_MISSING" in out.stderr) == (1, True)
    else:
        assert (out.returncode, "::notice::" in out.stdout) == (0, True)


@pytest.mark.parametrize("event", EVENTS)
def test_a_present_ledger_is_exported_on_every_event(event: str) -> None:
    # no URL: `--require-push` refuses to call a run that pushed nothing a success
    out = _step(event, FIXTURE)
    assert (out.returncode, "not found" in out.stdout) == (run.EXIT_NO_PUSH, False)
