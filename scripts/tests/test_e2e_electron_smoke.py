"""#3366: `_job-e2e.yml`'s `e2e-electron` runs only for `release/*` heads and nightly, so a gap in
it first shows when a release is cut (C-13.4). Its specs launch `apps/desktop/dist/main/index.js`,
the shell serves `apps/web/dist` over its `app://candleviewer` handler (#3410), and the Playwright
config's webServer serves `apps/web/dist` with `vite preview` for the specs that load it through
`CV_DEV_SERVER_URL`: the job builds both apps before the suite. Electron needs an X display on the
runner, so the suite runs under `xvfb-run -a`, as the `build` job's Electron-hardening
gate does. #1819: Electron 42 and later ship no postinstall, so `pnpm install` leaves no binary:
every job that launches Electron runs the SR-138 runner, which fetches it through electron's own
`install-electron` bin, after its install and before its first launch."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
SUITE = "pnpm run e2e --retries=1"
RUNNER = "node tools/ci/run-allowed-postinstall.mjs"
WORKFLOWS = ROOT / ".github" / "workflows"
Steps = list[dict[str, Any]]


def _steps() -> Steps:
    doc = yaml.safe_load((ROOT / ".github/workflows/_job-e2e.yml").read_text(encoding="utf-8"))
    steps: Steps = doc["jobs"]["e2e-electron"]["steps"]
    return steps


def _index(steps: Steps, folder: str, run: str) -> int:
    """The one step in `folder` whose command ends with `run` (xvfb-run may wrap it)."""
    hits = [
        i
        for i, step in enumerate(steps)
        if step.get("working-directory") == folder and str(step.get("run", "")).endswith(run)
    ]
    assert len(hits) == 1, f"expected one {folder} step running {run!r}, found {len(hits)}"
    return hits[0]


def test_e2e_electron_builds_the_web_app_and_the_shell_before_its_suite() -> None:
    steps = _steps()
    suite = _index(steps, "apps/desktop", SUITE)
    assert _index(steps, "apps/web", "pnpm run build") < suite
    assert _index(steps, "apps/desktop", "pnpm run build") < suite


def test_e2e_electron_runs_its_suite_on_a_virtual_display() -> None:
    steps = _steps()
    assert steps[_index(steps, "apps/desktop", SUITE)]["run"] == f"xvfb-run -a {SUITE}"


def test_e2e_electron_fetches_the_electron_binary_right_after_its_install() -> None:
    steps = _steps()
    runs = [str(step.get("run", "")) for step in steps]
    install = runs.index("pnpm install --frozen-lockfile")
    assert runs.index(RUNNER) == install + 1
    assert "working-directory" not in steps[install + 1]


def test_every_job_that_launches_electron_runs_the_allowlist_runner_after_its_install() -> None:
    # Electron needs an X display on the runner, so each launch runs under xvfb-run.
    launching: list[tuple[str, str]] = []
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        doc = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        for name, job in (doc.get("jobs") or {}).items():
            runs = [str(step.get("run", "")) for step in job.get("steps") or []]
            launches = [i for i, run in enumerate(runs) if "xvfb-run" in run]
            if not launches:
                continue
            launching.append((workflow.name, name))
            installs = [i for i, run in enumerate(runs) if run.startswith("pnpm install")]
            fetches = [i for i, run in enumerate(runs) if run == RUNNER]
            where = f"{workflow.name} {name}"
            assert installs and fetches, f"{where}: no pnpm install or no allowlist runner step"
            assert max(installs) < min(fetches) and max(fetches) < min(launches), where
    assert launching == [
        ("_job-e2e.yml", "e2e-electron"),
        ("_job-js.yml", "build"),
        ("perf-engine-matrix.yml", "electron"),
    ]
