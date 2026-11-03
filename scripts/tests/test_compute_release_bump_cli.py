"""Tests for tools/ci/compute_release_bump.py and check_changelog_fragment.py
CLI entry points (E03-T11)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.check_changelog_fragment import main as fragment_main
from tools.ci.compute_release_bump import main as bump_main


def _write_commits(tmp_path: Path, commits: list[dict[str, str]]) -> Path:
    p = tmp_path / "commits.json"
    p.write_text(json.dumps(commits), encoding="utf-8")
    return p


def test_compute_release_bump_pre_1_0_breaking_without_flag_bumps_minor(
    tmp_path: Path, capsys
) -> None:
    """C-15.5 (#3099): pre-1.0 a breaking change bumps MINOR; 1.0.0 needs the declaration."""
    commits_path = _write_commits(
        tmp_path, [{"sha": "s1", "message": "feat(auth-rbac)!: drop legacy cookie"}]
    )
    version_path = tmp_path / "version.txt"
    version_path.write_text("0.9.4\n", encoding="utf-8")

    rc = bump_main(["--commits-json", str(commits_path), "--current-version", str(version_path)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "next_version=0.10.0" in captured.out
    assert "bump=major" in captured.out


def test_compute_release_bump_major_with_flag_succeeds(tmp_path: Path, capsys) -> None:
    commits_path = _write_commits(
        tmp_path, [{"sha": "s1", "message": "feat(auth-rbac)!: drop legacy cookie"}]
    )
    version_path = tmp_path / "version.txt"
    version_path.write_text("0.9.4\n", encoding="utf-8")

    rc = bump_main(
        [
            "--commits-json",
            str(commits_path),
            "--current-version",
            str(version_path),
            "--allow-1-0-0",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert "next_version=1.0.0" in captured.out
    assert "bump=major" in captured.out


def test_compute_release_bump_no_commits_returns_none(tmp_path: Path, capsys) -> None:
    commits_path = _write_commits(tmp_path, [])
    version_path = tmp_path / "version.txt"
    version_path.write_text("0.9.4\n", encoding="utf-8")

    rc = bump_main(["--commits-json", str(commits_path), "--current-version", str(version_path)])
    assert rc == 2
    captured = capsys.readouterr()
    assert "bump=none" in captured.out


def test_check_changelog_fragment_cli_passes_for_conventional_title(capsys) -> None:
    rc = fragment_main(["--title", "feat(chart): add volume pane", "--body", ""])
    assert rc == 0


def test_check_changelog_fragment_cli_fails_for_wip_title(capsys) -> None:
    rc = fragment_main(["--title", "wip fixes", "--body", ""])
    assert rc == 1
    captured = capsys.readouterr()
    assert "CI-REL-001" in captured.err


def test_check_changelog_fragment_cli_passes_for_docs_only(capsys) -> None:
    rc = fragment_main(["--title", "docs: fix typo in sitemap", "--body", ""])
    assert rc == 0
