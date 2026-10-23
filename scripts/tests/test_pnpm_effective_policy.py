"""#3277: pnpm 12 reads the install policy from `pnpm-workspace.yaml`, not from `.npmrc`.

C-12.3's install policy sat in `.npmrc` (`ignore-scripts=true` and four more keys) and pnpm 12
ignored it: every `pnpm install` ran the root `prepare` and each workspace package's lifecycle
scripts, and `pnpm config get` printed `undefined` for every key. These cases run the pinned pnpm,
offline, in a scratch workspace built from COPIES of the repo's `.npmrc` and `pnpm-workspace.yaml`
(`packages:` pointed at one scratch package), and assert what pnpm does, not what the files say.
`.npmrc` keeps `ignore-scripts=true` for npm run at the repo root, which still reads it; one case
pins that.

CI must run them: `governance-tests` sets up the pinned pnpm (governance.yml), so without it they
fail there, and skip only on a developer machine. A pnpm other than the pin answers for another
program, so that counts as absent. Nothing here touches the network: `--offline`, a registry
nothing listens on, and corepack told not to download. pnpm 12 fetches its native binary on first
use, so provisioning runs `pnpm --version` once with network access (governance.yml does).
"""

from __future__ import annotations

import functools
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "tools" / "ci" / "run-allowed-postinstall.mjs"
HOOKS = ("preinstall", "install", "postinstall", "prepare")
PINNED = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["packageManager"]
PINNED_VERSION = PINNED.split("@", 1)[1].split("+", 1)[0]
#: What `pnpm config get` must say for each setting the comments promise.
POLICY = {
    "ignore-scripts": "true",
    "frozen-lockfile": "true",
    "save-exact": "true",
    "strict-peer-dependencies": "false",
}
#: What `.npmrc` keeps for npm, not pnpm: npm run at the repo root, for example an accidental
#: `npm install`, reads this file (not in global mode, `-g`, and not inside a workspace package).
#: pnpm 12 reads `ignoreScripts` from the workspace file instead.
NPM_ONLY = {"ignore-scripts": "true"}
#: A dependency whose postinstall writes `built.txt` beside itself, installed from a local tarball.
DEP = "dep-with-script"
TARBALL = f"{DEP}-1.0.0.tgz"


def _env(tmp_path: Path, *, dead_registry: bool = True) -> dict[str, str]:
    """The environment pnpm and npm run in: pnpm 12 takes settings from `pnpm_config_*` variables,
    so none of the caller's may carry over, and the store and both caches live under `tmp_path`,
    so no case writes into the user's home."""
    settings = ("npm_config_", "pnpm_config_")
    env = {k: v for k, v in os.environ.items() if not k.lower().startswith(settings)}
    env.update(
        COREPACK_ENABLE_NETWORK="0",  # a pnpm that is not cached fails here, it does not download
        COREPACK_ENABLE_DOWNLOAD_PROMPT="0",
        pnpm_config_store_dir=str(tmp_path / "store"),
        pnpm_config_cache_dir=str(tmp_path / "pnpm-cache"),
        npm_config_cache=str(tmp_path / "npm-cache"),
    )
    if dead_registry:  # nothing listens: a registry call fails at once
        env["pnpm_config_registry"] = "http://127.0.0.1:9/"
    return env


def _run(
    cmd: list[str], cwd: Path, tmp_path: Path, *, dead_registry: bool = True
) -> subprocess.CompletedProcess[str]:
    exe = shutil.which(cmd[0]) or cmd[0]
    return subprocess.run(
        [exe, *cmd[1:]],
        cwd=cwd,
        env=_env(tmp_path, dead_registry=dead_registry),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@functools.cache
def _pnpm_problem() -> str | None:
    """Why this machine cannot run the cases (None when the pinned pnpm answers)."""
    if shutil.which("pnpm") is None or shutil.which("node") is None:
        return (
            "pnpm or node is not on PATH: set Node up (setup-node) and run corepack enable and "
            f"corepack prepare pnpm@{PINNED_VERSION} --activate, as governance.yml does"
        )
    with tempfile.TemporaryDirectory() as scratch:  # no package.json: corepack's default pnpm
        got = _run(["pnpm", "--version"], Path(scratch), Path(scratch))
    version = got.stdout.strip()
    if got.returncode == 0 and version == PINNED_VERSION:
        return None
    return (
        f"package.json pins pnpm {PINNED_VERSION}, `pnpm --version` says "
        f"{version or got.stderr.strip()!r}: run corepack prepare pnpm@{PINNED_VERSION} "
        "--activate, then pnpm --version once with network access (pnpm 12 downloads its binary "
        "on first use)"
    )


def _need_pnpm() -> None:
    problem = _pnpm_problem()
    if problem:  # CI must run these proofs: they fail there and skip only on a developer machine
        (pytest.fail if os.environ.get("CI") else pytest.skip)(problem)


def _need_npm() -> None:
    if shutil.which("npm") is None:  # CI sets Node up and npm comes with it: fail there, skip here
        (pytest.fail if os.environ.get("CI") else pytest.skip)(
            "npm is not on PATH: setup-node brings it (governance.yml sets Node up)"
        )


def _manifest(name: str, dependencies: dict[str, str] | None = None) -> str:
    """A package whose every lifecycle hook writes `<hook>.marker` in its own directory. No
    `packageManager`: offline, pnpm then tries to resolve itself and fails."""
    scripts = {
        hook: f"node -e \"require('fs').writeFileSync('{hook}.marker', '')\"" for hook in HOOKS
    }
    manifest: dict[str, Any] = {
        "name": name,
        "version": "1.0.0",
        "private": True,
        "scripts": scripts,
    }
    return json.dumps({**manifest, "dependencies": dependencies or {}})


def _workspace(tmp_path: Path, allow_builds: dict[str, bool] | None = None) -> Path:
    """The repo's `.npmrc` and `pnpm-workspace.yaml`, copied, with `packages:` pointed at `pkg`."""
    root = tmp_path / "ws"
    (root / "pkg").mkdir(parents=True)
    shutil.copy(ROOT / ".npmrc", root / ".npmrc")
    policy = yaml.safe_load((ROOT / "pnpm-workspace.yaml").read_text(encoding="utf-8"))
    policy["packages"] = ["pkg"]
    policy.setdefault("allowBuilds", {}).update(allow_builds or {})
    (root / "pnpm-workspace.yaml").write_text(yaml.safe_dump(policy), encoding="utf-8")
    (root / "package.json").write_text(_manifest("policy-root"), encoding="utf-8")
    (root / "pkg" / "package.json").write_text(_manifest("policy-pkg"), encoding="utf-8")
    return root


def _install(root: Path, tmp_path: Path) -> None:
    """What CI runs: a lockfile first (nothing to fetch), then `pnpm install --frozen-lockfile`."""
    for flags in (["--lockfile-only", "--no-frozen-lockfile"], ["--frozen-lockfile"]):
        done = _run(["pnpm", "install", "--offline", *flags], root, tmp_path)
        assert done.returncode == 0, done.stdout + done.stderr


def _markers(root: Path) -> list[str]:
    found = root.glob("**/*.marker")
    return sorted(p.relative_to(root).as_posix() for p in found if "node_modules" not in p.parts)


def test_install_runs_no_lifecycle_script_of_the_root_or_a_workspace_package(
    tmp_path: Path,
) -> None:
    _need_pnpm()
    root = _workspace(tmp_path)
    _install(root, tmp_path)
    # Under .npmrc's ignore-scripts=true, pnpm 12 wrote all eight (four hooks, two projects).
    assert _markers(root) == []


def test_pnpm_reports_each_install_setting_the_comments_promise(tmp_path: Path) -> None:
    _need_pnpm()
    root = _workspace(tmp_path)
    got = {
        key: _run(["pnpm", "config", "get", key], root, tmp_path).stdout.strip() for key in POLICY
    }
    # `undefined` for every key while they lived in .npmrc.
    assert got == POLICY


def test_install_is_frozen_by_the_workspace_file_alone(tmp_path: Path) -> None:
    _need_pnpm()
    root = _workspace(tmp_path)
    done = _run(["pnpm", "install", "--offline"], root, tmp_path)  # no lockfile and no flag
    assert done.returncode != 0 and "ERR_PNPM_NO_LOCKFILE" in done.stdout + done.stderr
    assert not (root / "pnpm-lock.yaml").exists()


def _npmrc_settings(npmrc: Path = ROOT / ".npmrc") -> dict[str, str]:
    """The settings in `npmrc` that pnpm 12 would have to read: not its auth entries (`//host/:...`)
    or registries (`registry`, `@scope:registry`), which it still takes from that file."""
    lines = npmrc.read_text(encoding="utf-8").splitlines()
    pairs = (ln.partition("=") for ln in lines if ln.strip() and ln.lstrip()[0] not in "#;")
    settings = {key.strip(): value.strip() for key, sep, value in pairs if sep}
    return {k: v for k, v in settings.items() if k[:2] != "//" and k.split(":")[-1] != "registry"}


def test_every_other_npmrc_setting_is_one_pnpm_reads(tmp_path: Path) -> None:
    _need_pnpm()
    # pr.yml's path filters name .npmrc (pnpm still reads its registry and auth entries).
    assert (ROOT / ".npmrc").is_file()
    shutil.copy(ROOT / ".npmrc", tmp_path / ".npmrc")
    (tmp_path / "package.json").write_text('{"name": "npmrc", "private": true}', encoding="utf-8")
    wanted = {k: v for k, v in _npmrc_settings().items() if k not in NPM_ONLY}
    got = {k: _run(["pnpm", "config", "get", k], tmp_path, tmp_path).stdout.strip() for k in wanted}
    assert got == wanted, "pnpm 12 ignores these .npmrc settings: set them in pnpm-workspace.yaml"


def test_npm_at_the_repo_root_reads_ignore_scripts_from_the_npmrc(tmp_path: Path) -> None:
    """npm run at the root (an accidental `npm install`) reads the line `.npmrc` keeps for it."""
    _need_npm()
    root = _workspace(tmp_path)  # the repo's .npmrc, copied
    got = {k: _run(["npm", "config", "get", k], root, tmp_path).stdout.strip() for k in NPM_ONLY}
    # `false` once the line is gone: npm then runs the install scripts of what it installs.
    assert got == NPM_ONLY


def test_a_registry_line_is_one_pnpm_reads_so_the_guard_leaves_it_alone(tmp_path: Path) -> None:
    _need_pnpm()
    npmrc = tmp_path / ".npmrc"
    lines = [
        "registry=https://registry.example.invalid/",
        "@scope:registry=https://scope.example.invalid/",
    ]
    npmrc.write_text("\n".join([*lines, "save-exact=true"]) + "\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name": "npmrc", "private": true}', encoding="utf-8")
    got = _run(["pnpm", "config", "get", "registry"], tmp_path, tmp_path, dead_registry=False)
    assert got.stdout.strip() == "https://registry.example.invalid/"  # pnpm 12 reads it from .npmrc
    assert _npmrc_settings(npmrc) == {"save-exact": "true"}  # so only the other line is checked


def _pack_dependency(tarball: Path) -> None:
    script = "node -e \"require('fs').writeFileSync('built.txt', '')\""
    manifest = {"name": DEP, "version": "1.0.0", "scripts": {"postinstall": script}}
    files = {
        "package/package.json": json.dumps(manifest),
        "package/index.js": "module.exports = 1;",
    }
    with tarfile.open(tarball, "w:gz") as tar:
        for name, text in files.items():
            data = text.encode()
            member = tarfile.TarInfo(name)
            member.size = len(data)
            tar.addfile(member, io.BytesIO(data))


def test_install_builds_no_dependency_and_the_runner_builds_an_allowlisted_one(
    tmp_path: Path,
) -> None:
    _need_pnpm()
    root = _workspace(tmp_path, {f"{DEP}@file:{TARBALL}": True})
    _pack_dependency(root / TARBALL)
    (root / "package.json").write_text(
        _manifest("policy-root", {DEP: f"file:{TARBALL}"}), encoding="utf-8"
    )
    # The real runner, in a scratch repository whose allowlist names only the fixture dependency.
    ci = root / "tools" / "ci"
    ci.mkdir(parents=True)
    shutil.copy(RUNNER, ci / RUNNER.name)
    entry = {"name": DEP, "reason": "fixture", "reviewedBy": "fixture"}
    (ci / "allowed-postinstall.json").write_text(
        json.dumps({"packages": [entry]}), encoding="utf-8"
    )

    _install(root, tmp_path)
    built = root / "node_modules" / DEP / "built.txt"
    assert not built.exists()  # allowBuilds lets it build, ignoreScripts keeps pnpm install from it
    ran = _run(["node", str(ci / RUNNER.name)], root, tmp_path)
    assert ran.returncode == 0, ran.stderr
    # `pnpm rebuild` honours ignoreScripts too, so the runner must opt in to be the build path.
    assert built.is_file()


def test_governance_shards_fetch_the_pnpm_binary_before_the_cases_run() -> None:
    # pnpm 12 downloads its native binary on first use, and the cases run with corepack's network off.
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/governance.yml").read_text(encoding="utf-8")
    )
    runs = [str(step.get("run", "")) for step in workflow["jobs"]["governance-tests"]["steps"]]
    (provision,) = [i for i, run in enumerate(runs) if "corepack prepare" in run]
    assert f"corepack prepare pnpm@{PINNED_VERSION} --activate && pnpm --version" in runs[provision]
    first_cases = next(i for i, run in enumerate(runs) if "governance_shards.py" in run)
    assert provision < first_cases
