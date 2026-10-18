"""#3244, #3272: every job that builds or tests apps/web without turbo builds its deps first.

turbo's `dependsOn: ["^build"]` builds `packages/ui` (and the other packages `apps/web` imports)
before `turbo run test`, but many jobs call pnpm, vitest, vite or Playwright on `apps/web`
directly, and the app's build resolves `@candleviewer/ui/theme.css` to a built file. The scan below
finds every such job in `.github/workflows/`. Each must build `@candleviewer/web^...` and check
that the built exports of `packages/ui`, `packages/chart-engine` and `packages/protocol` exist
before its first apps/web step, and AGENTS.md says so next to the web test command."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
BUILD = 'pnpm --filter "@candleviewer/web^..." run build'
GUARD = "node tools/ci/check_built_exports.mjs packages/ui packages/chart-engine packages/protocol"
BUILD_STEP = {"name": "Build the workspace packages apps/web depends on", "run": BUILD}
GUARD_STEP = {
    "name": "Guard: the packages apps/web imports are built (fails fast, CI-BUILD-001)",
    "run": GUARD,
}
# pnpm selecting exactly the app, not `@candleviewer/web^...` (its deps) or `...web...[ref]`.
WEB_FILTER = re.compile(r"""(?:--filter|-F)[= ](["']?)@candleviewer/web\1(?=\s|$)""")
# A build or test word (`pnpm run build`, `vite build`, `playwright test`, `pnpm e2e`) or vitest.
WEB_TASK = re.compile(r"(?:^|\s)(?:run\s+)?(?:build|test|test:cov|e2e)(?=\s|$)|\bvitest\b")
Steps = list[dict[str, Any]]


def _builds_or_tests_web(step: dict[str, Any], cwd: object = None) -> bool:
    """A build, test or Playwright run of apps/web that turbo does not drive."""
    folder = str(step.get("working-directory", cwd) or "").removeprefix("./").rstrip("/")
    return any(
        "turbo" not in line
        and WEB_TASK.search(line) is not None
        and (folder == "apps/web" or WEB_FILTER.search(line) is not None)
        for line in str(step.get("run", "")).splitlines()
    )


def _web_jobs(
    folder: Path = ROOT / ".github" / "workflows",
) -> dict[tuple[str, str], tuple[Steps, int]]:
    """(workflow, job) -> (steps, index of the first apps/web step), over every workflow."""
    found: dict[tuple[str, str], tuple[Steps, int]] = {}
    for path in sorted(folder.glob("*.y*ml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        default = ((doc.get("defaults") or {}).get("run") or {}).get("working-directory")
        for name, job in (doc.get("jobs") or {}).items():
            cwd = ((job.get("defaults") or {}).get("run") or {}).get("working-directory", default)
            steps: Steps = job.get("steps") or []
            hits = [i for i, step in enumerate(steps) if _builds_or_tests_web(step, cwd)]
            if hits:
                found[(path.name, name)] = (steps, hits[0])
    return found


WEB_JOBS = _web_jobs()
# deploy-staging runs Playwright only once apps/web/e2e/demo-rest-only/ exists (R3) and installs
# nothing yet. The day that folder lands this exemption lapses: install, build and guard go there.
DORMANT = {("deploy-staging.yml", "deploy-staging"): "apps/web/e2e/demo-rest-only"}
# An empty scan proves nothing: these jobs build or test apps/web today.
KNOWN = {
    ("_job-e2e.yml", "e2e-web"),
    ("_job-e2e.yml", "e2e-staging"),
    ("_job-e2e.yml", "a11y-axe"),
    ("_job-e2e.yml", "e2e-electron"),
    ("_job-a11y.yml", "a11y"),
    ("a11y-nightly.yml", "sweep"),
    ("_job-js.yml", "build"),
    ("cold-cache.yml", "cold-web"),
}


def _index(steps: Steps, needle: str) -> int:
    hits = [i for i, s in enumerate(steps) if needle in str(s.get("run", ""))]
    assert len(hits) == 1, f"expected one step running {needle!r}, found {len(hits)}"
    return hits[0]


def test_the_scan_finds_every_job_that_builds_or_tests_apps_web() -> None:
    assert KNOWN | DORMANT.keys() <= WEB_JOBS.keys()


@pytest.mark.parametrize(
    ("cwd", "run", "web"),
    [
        ("apps/web", "pnpm run build", True),
        ("./apps/web/", "npx playwright test -c e2e/playwright.config.ts", True),
        ("apps/web", "npx vitest run", True),
        ("apps/web", "pnpm e2e", True),
        (None, "pnpm --filter @candleviewer/web --filter @candleviewer/desktop build", True),
        (None, 'pnpm --filter "@candleviewer/web" run test:cov', True),
        (None, "pnpm --filter=@candleviewer/web exec playwright test", True),
        (None, "pnpm -F @candleviewer/web test", True),
        ("apps/web", "npx playwright install --with-deps chromium", False),
        ("apps/desktop", "pnpm run e2e --retries=1", False),
        (None, BUILD, False),
        (None, "pnpm turbo run test:cov --filter=@candleviewer/web", False),
        (None, "pnpm --filter @candleviewer/web-kit run build", False),
        (None, "pnpm --filter @candleviewer/web run lint", False),
        ("apps/web", "ls dist/latest", False),
    ],
)
def test_the_scan_classifies_apps_web_steps(cwd: str | None, run: str, web: bool) -> None:
    assert _builds_or_tests_web({"run": run}, cwd) is web


def test_the_scan_reads_a_default_working_directory(tmp_path: Path) -> None:
    web = {"defaults": {"run": {"working-directory": "apps/web"}}}
    job = {"steps": [{"run": "pnpm install --frozen-lockfile"}, {"run": "pnpm test"}]}
    for name, doc in {
        "workflow.yml": {**web, "jobs": {"j": job}},
        "job.yml": {"jobs": {"j": {**web, **job}}},
        "none.yml": {"jobs": {"j": job}},
    }.items():
        (tmp_path / name).write_text(yaml.safe_dump(doc), encoding="utf-8")
    assert set(_web_jobs(tmp_path)) == {("workflow.yml", "j"), ("job.yml", "j")}


@pytest.mark.parametrize(("workflow", "job"), sorted(WEB_JOBS.keys() - DORMANT.keys()))
def test_lane_builds_web_deps_and_guards_before_web_tests(workflow: str, job: str) -> None:
    steps, first_web = WEB_JOBS[(workflow, job)]
    install = _index(steps, "pnpm install --frozen-lockfile")
    build, guard = _index(steps, BUILD), _index(steps, GUARD)
    assert install < build < guard < first_web
    # Exactly these keys: no `if`, `continue-on-error`, `shell` or `working-directory`.
    assert (steps[build], steps[guard]) == (BUILD_STEP, GUARD_STEP)


@pytest.mark.parametrize(("workflow", "job"), sorted(DORMANT))
def test_a_dormant_web_step_is_still_dormant(workflow: str, job: str) -> None:
    folder = DORMANT[(workflow, job)]
    assert not (ROOT / folder).exists(), f"{folder} exists: {job} needs install, build and guard"
    steps, first_web = WEB_JOBS[(workflow, job)]
    assert f"[ -d {folder} ]" in str(steps[first_web].get("run", ""))


def test_agents_md_states_the_build_prerequisite_of_the_web_tests() -> None:
    text = " ".join((ROOT / "AGENTS.md").read_text(encoding="utf-8").split())
    assert "`pnpm --filter @candleviewer/web test`" in text
    assert "the web `test` or `test:cov` script with pnpm directly" in text
    assert f"`{BUILD}` first" in text


def _guard(package: Path, *node_options: str) -> subprocess.CompletedProcess[str]:
    node = shutil.which("node")
    if node is None:  # CI must run this behavioural check
        (pytest.fail if os.environ.get("CI") else pytest.skip)("node runs the guard")
    script = ROOT / "tools" / "ci" / "check_built_exports.mjs"
    argv = [str(node), *node_options, str(script), str(package)]
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


MISSING = f"CI-BUILD-001: built exports are missing; build the workspace packages first ({BUILD}):"


def test_guard_reports_an_unbuilt_pattern_export_as_missing(tmp_path: Path) -> None:
    # A fresh checkout has no dist/: ENOENT on a pattern's folder is "not built", not an error.
    result = _guard(_package(tmp_path, PATTERN, []))
    missing = [f"  {tmp_path / 'dist' / name}" for name in ("theme.css", "tokens.*.css")]
    assert (result.returncode, result.stderr.splitlines()) == (1, [MISSING, *missing])


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


FS_ERROR = "CI-BUILD-001: cannot check built exports, the filesystem returned an error:"


def _assert_reported(result: subprocess.CompletedProcess[str], path: Path, errno: str) -> None:
    """Exit 1, the CI-BUILD-001 header, then one `<export>: <ERRNO>: ...` line: no stack trace."""
    lines = result.stderr.splitlines()
    assert result.returncode == 1, result.stderr
    # Exactly two lines: an uncaught error prints `Error: ...`, `    at` frames and `Node.js v...`.
    assert lines[:1] == [FS_ERROR] and len(lines) == 2, result.stderr
    assert lines[1].startswith(f"  {path}: {errno}: "), result.stderr


LONG = "x" * 256  # one path segment longer than NAME_MAX (255 bytes)


@pytest.mark.parametrize(
    ("target", "layout", "errno"),
    [
        pytest.param("./dist/index.js", "file", "ENOTDIR", id="parent-is-a-file"),
        pytest.param("./dist/tokens.*.css", "file", "ENOTDIR", id="pattern-folder-is-a-file"),
        pytest.param("./dist/index.js", "loop", "ELOOP", id="symlink-loop"),
        pytest.param("./dist/tokens.*.css", "loop", "ELOOP", id="pattern-symlink-loop"),
        pytest.param("./dist/tokens.*.css", "match-loop", "ELOOP", id="pattern-match-loop"),
        pytest.param(f"./{LONG}.js", None, "ENAMETOOLONG", id="name-too-long"),
        pytest.param(f"./{LONG}/tokens.*.css", None, "ENAMETOOLONG", id="pattern-too-long"),
    ],
)
def test_guard_reports_a_filesystem_error_with_its_errno(
    tmp_path: Path, target: str, layout: str | None, errno: str
) -> None:
    dist = tmp_path / "dist"
    if layout == "file":  # a file where the folder should be
        dist.write_text("", encoding="utf-8")
    elif layout == "loop":  # dist -> dist
        dist.symlink_to("dist")
    elif layout == "match-loop":  # one match is a file, another a symlink to itself
        dist.mkdir()
        (dist / "tokens.dark.css").write_text("", encoding="utf-8")
        (dist / "tokens.loop.css").symlink_to("tokens.loop.css")
    _assert_reported(_guard(_package(tmp_path, {".": target}, [])), tmp_path / target, errno)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores folder permissions")
@pytest.mark.parametrize(
    ("target", "mode"),
    [
        pytest.param("./dist/index.js", 0o600, id="folder-not-searchable"),
        pytest.param("./dist/tokens.*.css", 0o300, id="pattern-folder-not-readable"),
    ],
)
def test_guard_reports_a_permission_error_with_its_errno(
    tmp_path: Path, target: str, mode: int
) -> None:
    built = _package(tmp_path, {".": target}, ["dist/index.js", "dist/tokens.dark.css"])
    (built / "dist").chmod(mode)
    try:
        result = _guard(built)
    finally:
        (built / "dist").chmod(0o755)
    _assert_reported(result, tmp_path / target, "EACCES")


def test_guard_keeps_the_stack_of_an_error_that_has_no_code(tmp_path: Path) -> None:
    # Only an error with a code (ENOTDIR, EACCES, ...) is reported as a CI-BUILD-001 line: a bug
    # in the guard, such as a TypeError, keeps its stack and still exits 1.
    bug = tmp_path / "bug.cjs"  # preloaded with --require: statSync throws a code-less TypeError
    bug.write_text(
        'require("node:fs").statSync = () => { throw new TypeError("bug"); };\n'
        'require("node:module").syncBuiltinESMExports();\n',
        encoding="utf-8",
    )
    result = _guard(_package(tmp_path, CONDITIONAL, []), "--require", str(bug))
    assert result.returncode == 1
    assert "TypeError: bug" in result.stderr and "\n    at " in result.stderr
    assert "CI-BUILD-001" not in result.stderr
