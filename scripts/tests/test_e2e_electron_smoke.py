"""#3366: `_job-e2e.yml`'s `e2e-electron` runs only for `release/*` heads and nightly, so a gap in
it first shows when a release is cut (C-13.4). Its specs launch `apps/desktop/dist/main/index.js`,
the shell serves `apps/web/dist` over its `app://candleviewer` handler (#3410), and the Playwright
config's webServer serves `apps/web/dist` with `vite preview` for the specs that load it through
`CV_DEV_SERVER_URL`: the job builds both apps before the suite. Electron needs an X display on the
runner, so the suite runs under `xvfb-run -a`, as the `build` job's Electron-hardening
gate does."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
SUITE = "pnpm run e2e --retries=1"
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
