"""#3244, #3272: every job that builds or tests apps/web without turbo builds its deps first.

turbo's `dependsOn: ["^build"]` builds `packages/ui` (and the other packages `apps/web` imports)
before `turbo run test`, but many jobs call pnpm, vitest, vite or Playwright on `apps/web`
directly, and the app's build resolves `@candleviewer/ui/theme.css` to a built file. The scan below
finds every such job in `.github/workflows/`. Each must build `@candleviewer/web^...` and check
that the built exports of `packages/ui`, `packages/chart-engine` and `packages/protocol` exist
before its first apps/web step, and AGENTS.md says so next to the web test command.

#3367: the scan reads a run script as the shell runs it. Backslash-continued lines are joined, the
commands are split at newlines, `;`, `&&`, `||`, `|` and a command substitution (`$(`, a
backtick), and a `cd` or `pushd` moves the folder of the commands after it, also after `(`, `{`,
`!` or a keyword such as `if`, `then` or `do`. A `-C`, `--dir` or `--prefix` flag runs one command
in a folder, whichever program takes it (`pnpm -C`, `npm --prefix`, `make -C`). A folder is one
shell word without its quotes (`"$GITHUB_WORKSPACE"/apps/web`) and counts when it is apps/web or
inside it, relative to the checkout or under the workspace path (`${{ github.workspace }}`,
`$GITHUB_WORKSPACE`). pnpm's `--filter`, `-F` or `--filter-prod` selects the app by its name, with
or without the scope (`web`), or by a path selector relative to where pnpm runs (`./apps/web`,
`{../web}`), which pnpm matches against the package folders: one inside the app selects nothing.
A job-level `continue-on-error`, or a job or workflow `defaults.run.shell`, would weaken the
pinned steps without touching them, so no scanned job may set one.

The scan errs towards a hit, which fails loudly in the build-and-guard pin: a cd in a subshell, a
pipeline or a command substitution is taken to persist. Out of scope, as a static scan cannot
resolve them and no workflow uses them: commands in a script file, a composite action or a
`bash -c` string, `case` arms, folders or filters held in variables (`cd "$DIR"`), and runs that
select the app among other packages (`pnpm -r`, `--filter "./apps/*"`,
`--filter "...@candleviewer/ui"`)."""

from __future__ import annotations

import json
import os
import posixpath
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, NamedTuple

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
# One shell word as the command receives it once its quotes go: `"$GITHUB_WORKSPACE"/apps/web`.
WORD = r"""((?:"[^"]*"|'[^']*'|[^\s<>])+)"""
# pnpm's --filter, -F or --filter-prod and its selector. It counts when it picks exactly the app,
# by name (`web` too) or by folder: not `@candleviewer/web^...` (its deps) or `...web...[ref]`.
FILTER = re.compile(rf"(?:--filter(?:-prod)?|-F)(?:=|\s+){WORD}")
WEB_NAMES = ("@candleviewer/web", "web")
# A build or test word (`pnpm run build`, `vite build`, `playwright test`, `pnpm e2e`) or vitest.
WEB_TASK = re.compile(r"(?:^|\s)(?:run\s+)?(?:build|test|test:cov|e2e)(?=\s|$)|\bvitest\b")
# One command run in another folder (`pnpm -C apps/web`, `--dir=apps/web`, `npm --prefix`).
DIR_FLAG = re.compile(rf"(?:^|\s)(?:-C|--dir|--prefix)(?:=|\s+){WORD}")
CD = re.compile(rf"(?:cd|pushd)\s+(?:--\s+)?{WORD}")
# What may precede a command's first word: a subshell, a group, `!` or a shell keyword.
LEAD = re.compile(r"^(?:[\s({]|(?:!|if|elif|while|until|then|else|do)(?=\s))+")
# GitHub writes `${{ github.workspace }}` into a script before the shell runs it.
GITHUB_WORKSPACE = re.compile(r"\$\{\{\s*github\.workspace\s*\}\}")
# The checkout root as a working-directory or a shell names it.
WORKSPACE = re.compile(r"^(?:\$\{\{\s*github\.workspace\s*\}\}|\$\{?GITHUB_WORKSPACE\}?)(?:/|$)")
Steps = list[dict[str, Any]]


class WebJob(NamedTuple):
    steps: Steps
    first: int  # the first step that builds or tests apps/web
    weakeners: tuple[str, ...]  # keys outside the steps that change how every step runs


def _folder(path: object, here: str = ".") -> str:
    """`path` relative to the checkout; a relative path resolves against `here`."""
    text = str(path or "").strip()
    if WORKSPACE.match(text):
        here, text = ".", WORKSPACE.sub("", text)
    elif text.startswith(("/", "$", "~")):  # outside the checkout, or not known statically
        return text
    return posixpath.normpath(posixpath.join(here, text))


def _in_web(folder: str) -> bool:
    return folder == "apps/web" or folder.startswith("apps/web/")


def _word(text: str) -> str:
    return re.sub(r"""["']""", "", text)


def _selects_web(selector: str, here: str) -> bool:
    """Whether a pnpm selector picks apps/web when pnpm runs in `here`: pnpm matches a path
    selector (`./`, `../`, braces) against the package folders, and any other one as a name."""
    if selector.startswith("{") and selector.endswith("}"):
        selector = selector[1:-1]
    elif not selector.startswith("."):
        return selector in WEB_NAMES
    return _folder(selector, here) == "apps/web"


def _commands(run: object) -> list[str]:
    """A run script's commands: continued lines joined, split at newlines, ;, &&, || and |, and
    where a command substitution (`$(`, a backtick) starts one."""
    script = GITHUB_WORKSPACE.sub("$GITHUB_WORKSPACE", re.sub(r"\\\r?\n", " ", str(run or "")))
    parts = re.split(r"&&|\|\|?|;|\n|\$\(|`", script)
    return [re.sub(r"""(?:\)"|[\s)])+$""", "", LEAD.sub("", part)) for part in parts]


def _builds_or_tests_web(step: dict[str, Any], cwd: object = None) -> bool:
    """A build, test or Playwright run of apps/web that turbo does not drive."""
    here = _folder(step.get("working-directory", cwd))
    for command in _commands(step.get("run")):
        if (cd := CD.match(command)) is not None:
            here = _folder(_word(cd[1]), here)
        elif "turbo" not in command and WEB_TASK.search(command) is not None:
            flag = DIR_FLAG.search(command)
            folder = here if flag is None else _folder(_word(flag[1]), here)
            selectors = [_word(selector) for selector in FILTER.findall(command)]
            if _in_web(folder) or any(_selects_web(s, folder) for s in selectors):
                return True
    return False


def _weakeners(doc: dict[str, Any], name: str, job: dict[str, Any]) -> tuple[str, ...]:
    """The job- and workflow-level keys that change how every step of the job runs."""
    keys = [f"jobs.{name}.continue-on-error"] if "continue-on-error" in job else []
    for prefix, owner in ((f"jobs.{name}.", job), ("", doc)):
        if "shell" in ((owner.get("defaults") or {}).get("run") or {}):
            keys.append(f"{prefix}defaults.run.shell")
    return tuple(keys)


def _web_jobs(folder: Path = ROOT / ".github" / "workflows") -> dict[tuple[str, str], WebJob]:
    """(workflow, job) -> the job's steps, its first apps/web step and its weakening keys."""
    found: dict[tuple[str, str], WebJob] = {}
    for path in sorted(folder.glob("*.y*ml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        default = ((doc.get("defaults") or {}).get("run") or {}).get("working-directory")
        for name, job in (doc.get("jobs") or {}).items():
            cwd = ((job.get("defaults") or {}).get("run") or {}).get("working-directory", default)
            steps: Steps = job.get("steps") or []
            hits = [i for i, step in enumerate(steps) if _builds_or_tests_web(step, cwd)]
            if hits:
                found[(path.name, name)] = WebJob(steps, hits[0], _weakeners(doc, name, job))
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
        # #3367: pnpm or npm run in apps/web from elsewhere, `cd` into it (also over lines and in
        # a subshell), a path selector, --filter-prod, a folder in apps/web or under the workspace
        # path, and backslash-continued lines.
        (None, "pnpm -C apps/web run build", True),
        (None, "pnpm --dir apps/web test", True),
        (None, "pnpm --dir=./apps/web e2e", True),
        (None, "npm --prefix apps/web run build", True),
        (None, "cd apps/web && pnpm run build", True),
        (None, "cd ./apps/web; npx vitest run", True),
        (None, 'cd "$GITHUB_WORKSPACE/apps/web"\nnpx playwright test', True),
        (None, "cd apps\ncd web/e2e && npx playwright test", True),
        (None, "(cd apps/web && pnpm build)", True),
        (None, "pnpm --filter ./apps/web run build", True),
        (None, "pnpm --filter=./apps/web/ test:cov", True),
        (None, 'pnpm --filter "{./apps/web}" build', True),
        (None, "pnpm -F {apps/web} test", True),
        (None, "pnpm --filter-prod @candleviewer/web run build", True),
        (None, "pnpm --filter-prod=./apps/web build", True),
        ("apps/web/e2e", "npx playwright test", True),
        ("${{ github.workspace }}/apps/web", "pnpm run build", True),
        (None, "pnpm --filter @candleviewer/web \\\n  run build", True),
        (None, "pnpm \\\n  -C apps/web \\\n  test", True),
        # The workspace path as GitHub writes it in a script, and as the shell names it alone.
        (None, "cd ${{ github.workspace }}/apps/web && pnpm run build", True),
        (None, 'cd "${{ github.workspace }}/apps/web"\nnpx vitest run', True),
        (None, "pnpm -C ${{ github.workspace }}/apps/web run build", True),
        (None, 'pnpm --dir "${{ github.workspace }}/apps/web" test', True),
        (None, "cd $GITHUB_WORKSPACE\ncd apps/web && pnpm build", True),
        # `cd --`, a cd under a shell keyword, each separator, pushd, a brace group, and a -C
        # folder relative to the working-directory.
        (None, "cd -- apps/web && pnpm run build", True),
        (None, "if true; then cd apps/web; fi; pnpm run build", True),
        (None, "if ! cd apps/web; then exit 1; fi\npnpm run build", True),
        (None, "false || cd apps/web && pnpm run build", True),
        (None, "pnpm -C apps/desktop run lint | pnpm -C apps/web test", True),
        (None, "pushd apps/web\npnpm build", True),
        (None, "{ cd apps/web; pnpm build; }", True),
        ("apps", "pnpm -C web run build", True),
        # A word read without its quotes or a redirect, a tab or spaces after a flag, the name
        # without its scope, a path selector relative to where pnpm runs, a command substitution.
        (None, 'cd "$GITHUB_WORKSPACE"/apps/web && pnpm run build', True),
        (None, 'cd "${{ github.workspace }}"/apps/web && pnpm run build', True),
        (None, 'pnpm -C "$GITHUB_WORKSPACE"/apps/web run build', True),
        (None, "pushd apps/web>/dev/null\npnpm build", True),
        (None, "pnpm -C\tapps/web test", True),
        (None, "pnpm --filter  web test", True),
        (None, "pnpm --filter web run build", True),
        (None, "pnpm -F web test", True),
        (None, "pnpm --filter=web test:cov", True),
        ("apps/desktop", "pnpm --filter ../web build", True),
        (None, "pnpm -C apps/desktop --filter {../web} test", True),
        (None, "out=$(cd apps/web && pnpm run build)", True),
        (None, 'echo "$(pnpm -C apps/web test)"', True),
        (None, "log=`pnpm --filter web test`", True),
        (None, "cd apps/desktop && pnpm run build", False),
        (None, "pnpm -C ${{ github.workspace }}/apps/desktop run build", False),
        ("apps/web-kit", "pnpm run build", False),
        ("apps/web", "cd ../desktop && pnpm run e2e", False),
        (None, "pnpm -C apps/desktop run build", False),
        (None, "pnpm --filter ./apps/web-kit run build", False),
        (None, "cd apps/web && pnpm turbo run test", False),
        ("${{ github.workspace }}/apps/desktop", "pnpm run build", False),
        (None, 'cd "$GITHUB_WORKSPACE"/apps/desktop && pnpm run build', False),
        (None, 'cd "apps/web kit" && pnpm run build', False),
        (None, 'pnpm --filter "web^..." run build', False),
        (None, "pnpm --filter web-kit run build", False),
        ("apps/desktop", "pnpm --filter ./web build", False),
        (None, "pnpm --filter ./apps/web/e2e test", False),  # no package has that folder
        # The cd's `e2e` names a folder: a cd is never also scored as a web task.
        ("apps/web", "cd e2e && npx playwright install --with-deps chromium", False),
    ],
)
def test_the_scan_classifies_apps_web_steps(cwd: str | None, run: str, web: bool) -> None:
    assert _builds_or_tests_web({"run": run}, cwd) is web


@pytest.mark.parametrize("keyword", ["if", "elif", "while", "until", "then", "else", "do", "!"])
def test_the_scan_follows_a_cd_after_a_shell_keyword(keyword: str) -> None:
    # A cd in a condition or a branch moves the shell: `then`, `else` and `do` open no subshell.
    assert _builds_or_tests_web({"run": f"{keyword} cd apps/web\npnpm run build"})


@pytest.mark.parametrize(("workflow", "job"), sorted(WEB_JOBS))
def test_no_job_or_workflow_key_weakens_the_web_steps(workflow: str, job: str) -> None:
    # The {name, run} pin on the build and guard steps cannot see these: a job-level
    # `continue-on-error` (even `false`, an expression can turn it on) passes the job when the
    # guard fails, and a default `shell` replaces `bash -e {0}` for every step of the job.
    assert WEB_JOBS[(workflow, job)].weakeners == ()


def test_the_scan_reports_the_keys_that_weaken_every_step(tmp_path: Path) -> None:
    shell = {"defaults": {"run": {"shell": "bash {0}"}}}
    job = {"steps": [{"run": "pnpm --filter @candleviewer/web run build"}]}
    for name, doc in {
        "plain.yml": {"jobs": {"j": job}},
        "job-continue.yml": {"jobs": {"j": {"continue-on-error": False, **job}}},
        "job-shell.yml": {"jobs": {"j": {**shell, **job}}},
        "workflow-shell.yml": {**shell, "jobs": {"j": job}},
    }.items():
        (tmp_path / name).write_text(yaml.safe_dump(doc), encoding="utf-8")
    found = {workflow: web.weakeners for (workflow, _), web in _web_jobs(tmp_path).items()}
    assert found == {
        "plain.yml": (),
        "job-continue.yml": ("jobs.j.continue-on-error",),
        "job-shell.yml": ("jobs.j.defaults.run.shell",),
        "workflow-shell.yml": ("defaults.run.shell",),
    }


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
    steps, first_web, _ = WEB_JOBS[(workflow, job)]
    install = _index(steps, "pnpm install --frozen-lockfile")
    build, guard = _index(steps, BUILD), _index(steps, GUARD)
    assert install < build < guard < first_web
    # Exactly these keys: no `if`, `continue-on-error`, `shell` or `working-directory`.
    assert (steps[build], steps[guard]) == (BUILD_STEP, GUARD_STEP)


@pytest.mark.parametrize(("workflow", "job"), sorted(DORMANT))
def test_a_dormant_web_step_is_still_dormant(workflow: str, job: str) -> None:
    folder = DORMANT[(workflow, job)]
    assert not (ROOT / folder).exists(), f"{folder} exists: {job} needs install, build and guard"
    steps, first_web, _ = WEB_JOBS[(workflow, job)]
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
