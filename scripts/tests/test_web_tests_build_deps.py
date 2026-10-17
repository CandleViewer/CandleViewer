"""#3244: lanes that run apps/web's tests with pnpm directly build its workspace deps first.

turbo's `dependsOn: ["^build"]` builds `packages/ui` (and the other packages `apps/web` imports)
before `turbo run test`, but the `a11y-axe` job and `cold-cache.yml` call pnpm directly. So each
must build `@candleviewer/web^...` and check that the built exports of `packages/ui`,
`packages/chart-engine` and `packages/protocol` exist before the tests run, and AGENTS.md says so
next to the web test command."""

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
GUARD = "node tools/ci/check_built_exports.mjs packages/ui packages/chart-engine packages/protocol"
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
    build, guard = _index(steps, BUILD), _index(steps, GUARD)
    assert install < build < guard < _index(steps, tests)
    assert (str(steps[build]["run"]).strip(), str(steps[guard]["run"]).strip()) == (BUILD, GUARD)
    for step in (steps[build], steps[guard]):  # both always run and always gate
        assert "if" not in step and not step.get("continue-on-error", False), step


def test_agents_md_states_the_build_prerequisite_of_the_web_tests() -> None:
    text = " ".join((ROOT / "AGENTS.md").read_text(encoding="utf-8").split())
    assert "`pnpm --filter @candleviewer/web test`" in text
    assert "the web `test` or `test:cov` script with pnpm directly" in text
    assert f"`{BUILD}` first" in text


def _guard(package: Path) -> subprocess.CompletedProcess[str]:
    node = shutil.which("node")
    if node is None:  # CI must run this behavioural check
        (pytest.fail if os.environ.get("CI") else pytest.skip)("node runs the guard")
    script = ROOT / "tools" / "ci" / "check_built_exports.mjs"
    argv = [str(node), str(script), str(package)]
    return subprocess.run(argv, capture_output=True, text=True, timeout=60, check=False)


def _package(root: Path, exports: object, files: list[str]) -> Path:
    (root / "package.json").write_text(json.dumps({"exports": exports}), encoding="utf-8")
    for name in files:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text("", encoding="utf-8")
    return root


CONDITIONAL = {".": {"types": "./dist/index.d.ts", "import": "./dist/index.js"}}


def test_guard_fails_fast_when_a_built_export_is_missing(tmp_path: Path) -> None:
    result = _guard(_package(tmp_path, CONDITIONAL, ["dist/index.js"]))
    assert result.returncode == 1
    assert "CI-BUILD-001" in result.stderr and "index.d.ts" in result.stderr


def test_guard_passes_when_every_export_is_built(tmp_path: Path) -> None:
    built = _package(tmp_path, CONDITIONAL, ["dist/index.js", "dist/index.d.ts"])
    assert _guard(built).returncode == 0


PATTERN = {"./theme.css": "./dist/theme.css", "./tokens.*.css": "./dist/tokens.*.css"}


def test_guard_accepts_a_pattern_export_that_matches_a_file(tmp_path: Path) -> None:
    built = _package(tmp_path, PATTERN, ["dist/theme.css", "dist/tokens.dark.css"])
    assert _guard(built).returncode == 0


@pytest.mark.parametrize(
    "near_miss",
    [
        "dist/theme.css",  # nothing else is built
        "dist/tokensXdarkXcss",  # a "." in the pattern is literal
        "dist/tokens..css",  # "*" matches at least one character, as in Node
        "dist/tokens.dark.css.map",  # the match is anchored at the end
        "dist/old-tokens.dark.css",  # and at the start
    ],
)
def test_guard_fails_when_no_file_matches_a_pattern_export(tmp_path: Path, near_miss: str) -> None:
    result = _guard(_package(tmp_path, PATTERN, ["dist/theme.css", near_miss]))
    assert result.returncode == 1 and "tokens.*.css" in result.stderr


def test_guard_does_not_accept_a_directory_matching_a_pattern_export(tmp_path: Path) -> None:
    (tmp_path / "dist" / "tokens.dark.css").mkdir(parents=True)
    result = _guard(_package(tmp_path, PATTERN, ["dist/theme.css"]))
    assert result.returncode == 1 and "tokens.*.css" in result.stderr


def test_guard_reports_a_pattern_in_a_folder_segment_as_unsupported(tmp_path: Path) -> None:
    exports = {"./locales/*": "./dist/locales/*/index.js"}
    result = _guard(_package(tmp_path, exports, ["dist/locales/en/index.js"]))
    assert result.returncode == 1 and "unsupported pattern exports" in result.stderr


def test_guard_does_not_accept_a_directory_for_an_export(tmp_path: Path) -> None:
    (tmp_path / "dist" / "index.js").mkdir(parents=True)
    result = _guard(_package(tmp_path, {".": "./dist/index.js"}, []))
    assert result.returncode == 1 and "CI-BUILD-001" in result.stderr


def test_guard_reports_an_unreadable_manifest_with_its_code(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{", encoding="utf-8")
    result = _guard(tmp_path)
    assert result.returncode == 1 and "CI-BUILD-001" in result.stderr


def test_guard_reports_a_manifest_that_is_not_an_object_with_its_code(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("null", encoding="utf-8")
    result = _guard(tmp_path)
    assert result.returncode == 1 and "CI-BUILD-001" in result.stderr
