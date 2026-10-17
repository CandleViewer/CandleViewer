"""#3244: lanes that run apps/web's tests with pnpm directly build its workspace deps first.

turbo's `dependsOn: ["^build"]` builds `packages/ui` (and the other packages `apps/web` imports)
before `turbo run test`, but the `a11y-axe` job and `cold-cache.yml` call pnpm directly. So each
must build `@candleviewer/web^...` and check that `packages/ui`'s exports exist before the tests
run, and AGENTS.md says so next to the web test command."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
BUILD = 'pnpm --filter "@candleviewer/web^..." run build'
GUARD = "node tools/ci/check_built_exports.mjs packages/ui"
LANES = [
    (".github/workflows/_job-e2e.yml", "a11y-axe", "pnpm --filter @candleviewer/web --filter"),
    (
        ".github/workflows/cold-cache.yml",
        "cold-web",
        "pnpm --filter @candleviewer/web run test:cov",
    ),
]


def _steps(workflow: str, job: str) -> list[dict[str, Any]]:
    jobs: dict[str, Any] = yaml.safe_load((ROOT / workflow).read_text(encoding="utf-8"))["jobs"]
    steps: list[dict[str, Any]] = jobs[job]["steps"]
    return steps


def _index(steps: list[dict[str, Any]], needle: str) -> int:
    hits = [i for i, s in enumerate(steps) if needle in str(s.get("run", ""))]
    assert len(hits) == 1, f"expected one step running {needle!r}, found {len(hits)}"
    return hits[0]


@pytest.mark.parametrize(("workflow", "job", "tests"), LANES)
def test_lane_builds_web_deps_and_guards_before_web_tests(
    workflow: str, job: str, tests: str
) -> None:
    steps = _steps(workflow, job)
    install = _index(steps, "pnpm install --frozen-lockfile")
    assert install < _index(steps, BUILD) < _index(steps, GUARD) < _index(steps, tests)


def test_agents_md_states_the_build_prerequisite_of_the_web_tests() -> None:
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "`pnpm --filter @candleviewer/web test`" in text
    assert f"`{BUILD}` first" in text


def _guard(package: Path) -> subprocess.CompletedProcess[str]:
    node = shutil.which("node")
    if node is None:  # CI must run this behavioural check
        (pytest.fail if os.environ.get("CI") else pytest.skip)("node runs the guard")
    script = ROOT / "tools" / "ci" / "check_built_exports.mjs"
    argv = [str(node), str(script), str(package)]
    return subprocess.run(argv, capture_output=True, text=True, timeout=60, check=False)


def test_guard_fails_fast_when_a_built_export_is_missing(tmp_path: Path) -> None:
    exports = {".": {"types": "./dist/index.d.ts", "import": "./dist/index.js"}}
    (tmp_path / "package.json").write_text(json.dumps({"exports": exports}), encoding="utf-8")
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "index.js").write_text("", encoding="utf-8")

    missing = _guard(tmp_path)
    assert missing.returncode == 1
    assert "CI-BUILD-001" in missing.stderr and "index.d.ts" in missing.stderr

    (tmp_path / "dist" / "index.d.ts").write_text("", encoding="utf-8")
    assert _guard(tmp_path).returncode == 0
