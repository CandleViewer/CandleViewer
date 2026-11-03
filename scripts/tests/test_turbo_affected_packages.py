"""Tests for tools/ci/turbo-affected-packages.mjs (E03-T04 follow-up).

The pure `affectedDirectories()` parser is exercised through node so the
manifest the JS lanes upload always matches what coverage_gate.py reads.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "ci" / "turbo-affected-packages.mjs"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _affected(dry_run: dict[str, object]) -> list[str]:
    js = (
        "import('"
        + SCRIPT.resolve().as_uri()
        + "').then(m => { let d=''; process.stdin.on('data', c => d += c);"
        " process.stdin.on('end', () => console.log(JSON.stringify(m.affectedDirectories(JSON.parse(d))))); })"
    )
    out = subprocess.run(
        ["node", "--input-type=module", "-e", js],
        input=json.dumps(dry_run),
        capture_output=True,
        text=True,
        check=True,
    )
    result: list[str] = json.loads(out.stdout.strip().splitlines()[-1])
    return result


def test_only_test_cov_tasks_are_listed_with_forward_slashes() -> None:
    dry_run = {
        "tasks": [
            {
                "package": "@candleviewer/chart-engine",
                "directory": "packages\\chart-engine",
                "task": "test:cov",
            },
            {
                "package": "@candleviewer/config",
                "directory": "packages\\config",
                "task": "build",
            },
            {
                "package": "@candleviewer/protocol",
                "directory": "packages/protocol",
                "task": "test:cov",
            },
        ]
    }
    assert _affected(dry_run) == ["packages/chart-engine", "packages/protocol"]


def test_no_scheduled_tasks_yields_empty_manifest() -> None:
    assert _affected({"tasks": []}) == []
    assert _affected({}) == []


def test_cli_without_separator_exits_2(tmp_path: Path) -> None:
    proc = subprocess.run(
        ["node", str(SCRIPT), str(tmp_path / "out.txt")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "usage" in proc.stderr


def _fake_pnpm(tmp_path: Path, body: str) -> dict[str, str]:
    """An environment whose `pnpm` is a node script printing `body` (#5596)."""
    import os

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "pnpm"
    fake.write_text("#!/usr/bin/env node\n" + body, encoding="utf-8")
    fake.chmod(0o755)
    return {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}


@pytest.mark.skipif(sys.platform == "win32", reason="the fake pnpm is a POSIX script")
def test_a_dry_run_over_one_mebibyte_is_recorded_without_echoing_it(tmp_path: Path) -> None:
    # Node's execFileSync pipe buffer is 1 MiB; a large affected set used to die with ENOBUFS.
    payload = json.dumps(
        {
            "tasks": [
                {"task": "test:cov", "directory": "packages/chart-engine", "hash": "a" * 600_000},
                {"task": "test:cov", "directory": "apps/web", "hash": "b" * 600_000},
                {"task": "build", "directory": "packages/config"},
            ]
        }
    )
    assert len(payload) > 1024 * 1024
    data = tmp_path / "dry-run.json"
    data.write_text(payload, encoding="utf-8")
    env = _fake_pnpm(
        tmp_path, f"process.stdout.write(require('fs').readFileSync({str(data)!r}, 'utf8'));\n"
    )
    out = tmp_path / "affected.txt"
    proc = subprocess.run(
        ["node", str(SCRIPT), str(out), "--", "--filter=...[origin/main]"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr[-500:]
    assert out.read_text(encoding="utf-8") == "apps/web\npackages/chart-engine\n"
    assert "a" * 100 not in proc.stdout + proc.stderr


@pytest.mark.skipif(sys.platform == "win32", reason="the fake pnpm is a POSIX script")
def test_a_failed_turbo_dry_run_prints_one_short_line_and_exits_non_zero(tmp_path: Path) -> None:
    env = _fake_pnpm(
        tmp_path, "process.stdout.write('{\"tasks\": [' + 'x'.repeat(5000)); process.exit(3);\n"
    )
    out = tmp_path / "affected.txt"
    proc = subprocess.run(
        ["node", str(SCRIPT), str(out), "--", "--filter=...[origin/main]"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode != 0
    assert "turbo dry-run failed (3; 5011 bytes read)" in proc.stderr
    assert "x" * 100 not in proc.stdout + proc.stderr
    assert not out.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="the fake pnpm is a POSIX script")
def test_an_invalid_dry_run_json_is_refused_without_echoing_it(tmp_path: Path) -> None:
    # turbo exits 0 but the output is cut short: a parse error would quote the whole line.
    env = _fake_pnpm(tmp_path, "process.stdout.write('{\"tasks\": [' + 'y'.repeat(200000));\n")
    out = tmp_path / "affected.txt"
    proc = subprocess.run(
        ["node", str(SCRIPT), str(out), "--", "--filter=...[origin/main]"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode != 0
    assert "turbo dry-run JSON invalid (200011 bytes)" in proc.stderr
    assert "y" * 100 not in proc.stdout + proc.stderr
    assert not out.exists()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
