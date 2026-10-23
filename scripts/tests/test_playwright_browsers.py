"""Tests for tools/ci/playwright_browsers.sh (CI-A11Y-005) and its use in _job-a11y.yml.

A fake `npx` on PATH, no network. The workflow tests pin that both a11y jobs restore the browser
cache before the install and key it by the runner OS and the lockfile's Playwright version."""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "tools" / "ci" / "playwright_browsers.sh"
VERSION = "1.64.1"

FAKE_PNPM = r"""#!/bin/bash
echo "$*" >> "$FAKE/calls.log"
[ "$1 $2" = "exec playwright" ] || { echo "unexpected pnpm call: $*" >&2; exit 99; }
shift 2
case "$1" in
  --version) echo "Version ${FAKE_VERSION:-1.64.1}" ;;
  install | install-deps)
    n=$(cat "$FAKE/runs" 2>/dev/null || echo 0); echo $((n + 1)) > "$FAKE/runs"
    [ "$((n + 1))" -gt "${INSTALL_FAILS:-0}" ] || { echo "download of chromium failed" >&2; exit 1; }
    ;;
  *) echo "unexpected playwright call: $*" >&2; exit 99 ;;
esac
"""


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in {
        "pnpm": FAKE_PNPM,
        "sleep": '#!/bin/bash\necho "$*" >> "$FAKE/sleeps.log"\n',
        "timeout": (
            '#!/bin/bash\nwhile [[ "$1" == --* ]]; do echo "$1" >> "$FAKE/timeout-flags.log"; shift; done\n'
            'echo "$1" >> "$FAKE/timeouts.log"\nshift\nexec "$@"\n'
        ),
    }.items():
        tool = bindir / name
        tool.write_text(body, encoding="utf-8")
        tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    state = tmp_path / "state"
    state.mkdir()
    return {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "FAKE": str(state),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
        "GITHUB_OUTPUT": str(tmp_path / "output.txt"),
    }


def _run(
    env: dict[str, str], *args: str, **extra: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        env={**env, **extra},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _calls(env: dict[str, str]) -> list[str]:
    log = Path(env["FAKE"]) / "calls.log"
    return log.read_text().splitlines() if log.exists() else []


def _installs(env: dict[str, str]) -> list[str]:
    return [c for c in _calls(env) if c.startswith("exec playwright install")]


def _summary(env: dict[str, str]) -> str:
    return Path(env["GITHUB_STEP_SUMMARY"]).read_text()


KEY = f"pw-browsers-Linux-{VERSION}"


def test_version_is_written_for_the_cache_key(env: dict[str, str]) -> None:
    r = _run(env, "version")
    assert r.returncode == 0, r.stderr
    assert Path(env["GITHUB_OUTPUT"]).read_text() == f"version={VERSION}\n"


def test_version_that_is_not_a_plain_version_is_refused(env: dict[str, str]) -> None:
    r = _run(env, "version", FAKE_VERSION="1.64.1; echo pwned")
    assert r.returncode == 1 and "CI-A11Y-005" in r.stderr
    assert not Path(env["GITHUB_OUTPUT"]).exists()


def test_miss_runs_the_full_install_with_deps_and_says_miss(
    env: dict[str, str],
) -> None:
    r = _run(env, "install", PW_CACHE_KEY=KEY, PW_CACHE_HIT="false", PW_VERSION=VERSION)
    assert r.returncode == 0, r.stderr
    assert _installs(env) == ["exec playwright install --with-deps chromium"]
    assert f"`{KEY}`" in _summary(env) and "miss" in _summary(env)


def test_hit_runs_only_install_deps_and_says_hit(env: dict[str, str]) -> None:
    r = _run(env, "install", PW_CACHE_KEY=KEY, PW_CACHE_HIT="true", PW_VERSION=VERSION)
    assert r.returncode == 0, r.stderr
    assert _installs(env) == ["exec playwright install-deps chromium"]
    assert f"`{KEY}`" in _summary(env) and "hit" in _summary(env)


def test_an_empty_hit_flag_counts_as_a_miss(env: dict[str, str]) -> None:
    r = _run(env, "install", PW_CACHE_KEY=KEY, PW_CACHE_HIT="", PW_VERSION=VERSION)
    assert r.returncode == 0, r.stderr
    assert _installs(env) == ["exec playwright install --with-deps chromium"]


def test_hit_for_another_playwright_version_is_refused(env: dict[str, str]) -> None:
    r = _run(env, "install", PW_CACHE_KEY=KEY, PW_CACHE_HIT="true", PW_VERSION="1.63.0")
    assert r.returncode == 1 and "CI-A11Y-005" in r.stderr
    assert _installs(env) == []


def test_download_fails_then_works_within_five_attempts(env: dict[str, str]) -> None:
    r = _run(
        env,
        "install",
        PW_CACHE_KEY=KEY,
        PW_CACHE_HIT="false",
        PW_VERSION=VERSION,
        INSTALL_FAILS="4",
    )
    assert r.returncode == 0, r.stderr
    assert len(_installs(env)) == 5
    assert (Path(env["FAKE"]) / "sleeps.log").read_text().split() == [
        "10",
        "20",
        "40",
        "60",
    ]


def test_download_always_fails_ends_with_the_code_naming_the_download(
    env: dict[str, str],
) -> None:
    r = _run(
        env,
        "install",
        PW_CACHE_KEY=KEY,
        PW_CACHE_HIT="false",
        PW_VERSION=VERSION,
        INSTALL_FAILS="99",
    )
    assert r.returncode == 1
    assert "CI-A11Y-005" in r.stderr and "download" in r.stderr
    assert len(_installs(env)) == 5


def test_each_attempt_is_bounded_and_the_bound_is_a_whole_number(
    env: dict[str, str],
) -> None:
    ok = _run(
        env, "install", PW_CACHE_KEY=KEY, PW_CACHE_HIT="false", PW_VERSION=VERSION
    )
    assert ok.returncode == 0 and (
        Path(env["FAKE"]) / "timeouts.log"
    ).read_text().split() == ["120"]
    bad = _run(
        env,
        "install",
        PW_CACHE_KEY=KEY,
        PW_CACHE_HIT="false",
        PW_VERSION=VERSION,
        PW_INSTALL_TIMEOUT="soon",
    )
    assert bad.returncode == 1 and "CI-A11Y-005" in bad.stderr


def test_the_lockfile_binary_is_run_never_fetched_from_a_registry() -> None:
    text = SCRIPT.read_text()
    code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    assert "npx" not in code and "pnpm exec playwright" in code


def test_a_stuck_download_is_killed_after_its_bound(env: dict[str, str]) -> None:
    r = _run(env, "install", PW_CACHE_KEY=KEY, PW_CACHE_HIT="false", PW_VERSION=VERSION)
    assert r.returncode == 0
    flags = (Path(env["FAKE"]) / "timeout-flags.log").read_text().split()
    assert flags == ["--kill-after=10"]


def test_failed_apt_install_on_a_hit_does_not_blame_the_download(
    env: dict[str, str],
) -> None:
    r = _run(
        env,
        "install",
        PW_CACHE_KEY=KEY,
        PW_CACHE_HIT="true",
        PW_VERSION=VERSION,
        INSTALL_FAILS="99",
    )
    assert r.returncode == 1 and "CI-A11Y-005" in r.stderr
    (line,) = [ln for ln in r.stderr.splitlines() if ln.startswith("::error::")]
    assert "dependency" in line and "download" not in line


def test_empty_backoff_list_ends_with_the_code(env: dict[str, str]) -> None:
    r = _run(
        env,
        "install",
        PW_CACHE_KEY=KEY,
        PW_CACHE_HIT="false",
        PW_VERSION=VERSION,
        PW_BACKOFF="",
        INSTALL_FAILS="1",
    )
    assert r.returncode == 1 and "CI-A11Y-005" in r.stderr and "PW_BACKOFF" in r.stderr


def test_failure_is_annotated_for_the_run_page(env: dict[str, str]) -> None:
    r = _run(env, "version", FAKE_VERSION="x")
    assert r.stderr.startswith("::error::CI-A11Y-005")


def test_pr_workflow_runs_the_e2e_filter_for_the_script() -> None:
    text = (REPO / ".github" / "workflows" / "pr.yml").read_text()
    assert "- 'tools/ci/playwright_browsers.sh'" in text


# --- the workflow: both jobs restore the cache before the install, keyed by OS + version ---

PINNED = re.compile(r"[\w.-]+/[\w.-]+(?:/[\w.-]+)?@[0-9a-f]{40}")


def _steps(job: str) -> list[dict[str, Any]]:
    doc = yaml.safe_load((REPO / ".github" / "workflows" / "_job-a11y.yml").read_text())
    steps: list[dict[str, Any]] = doc["jobs"][job]["steps"]
    return steps


def _index(steps: list[dict[str, Any]], pick: str) -> int:
    (found,) = [
        i
        for i, s in enumerate(steps)
        if pick in (s.get("name", "") + s.get("uses", ""))
    ]
    return found


@pytest.mark.parametrize("job", ["a11y", "storybook"])
def test_job_restores_the_browser_cache_before_the_install(job: str) -> None:
    steps = _steps(job)
    install_deps = _index(steps, "Install dependencies")
    version = _index(steps, "Resolve the Playwright version")
    cache = _index(steps, "actions/cache/restore@")
    install = _index(steps, "Install Playwright browsers")
    save = _index(steps, "actions/cache/save@")
    assert install_deps < version < cache < install < save
    # The version comes from the installed lockfile's Playwright, after `pnpm install`.
    assert steps[version]["working-directory"] == "apps/web"
    assert steps[version]["run"].strip() == (
        '"$GITHUB_WORKSPACE/tools/ci/playwright_browsers.sh" version'
    )
    for at in (cache, save):
        assert PINNED.fullmatch(steps[at]["uses"].split(" ")[0]), steps[at]["uses"]
    cache_with = steps[cache]["with"]
    assert cache_with["path"] == "~/.cache/ms-playwright"
    vid, cid = steps[version]["id"], steps[cache]["id"]
    # OS + version only; no `restore-keys`, so a bump never restores another version's browsers.
    assert (
        cache_with["key"]
        == f"pw-browsers-${{{{ runner.os }}}}-${{{{ steps.{vid}.outputs.version }}}}"
    )
    assert set(cache_with) == {"path", "key"}
    # The save is its own step right after a successful install (the post step of a combined
    # cache action would not run when a later step failed, so a cold run that breaches the
    # budget would never seed the cache), only on a miss, with the same path and key.
    assert steps[save]["with"] == cache_with
    assert steps[save]["if"] == f"steps.{cid}.outputs.cache-hit != 'true'"
    step = steps[install]
    assert step["working-directory"] == "apps/web"
    assert (
        step["run"].strip()
        == '"$GITHUB_WORKSPACE/tools/ci/playwright_browsers.sh" install'
    )
    assert step["env"] == {
        "PW_CACHE_KEY": cache_with["key"],
        "PW_CACHE_HIT": f"${{{{ steps.{cid}.outputs.cache-hit }}}}",
        "PW_VERSION": f"${{{{ steps.{vid}.outputs.version }}}}",
    }
    assert all("${{" not in s.get("run", "") for s in steps)
