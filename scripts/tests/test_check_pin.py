"""Unit tests for tools/ci/check_pin.py (E50-T57: xstate-statemachine pin
must stay exact and hash-locked)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.check_pin import (
    PINNED_UPSTREAM_SHA,
    PINNED_WHEEL_SHA256,
    check_lock,
    check_pyproject,
    check_workflow,
    main,
)

VALID_PYPROJECT = """\
[project]
name = "candleviewer-api"
dependencies = [
  "fastapi>=0.115",
  "xstate-statemachine==0.9.1",
]
"""

VALID_LOCK = f"""\
[[package]]
name = "xstate-statemachine"
version = "0.9.1"
wheels = [
    {{ url = "https://example.invalid/x.whl", hash = "sha256:{PINNED_WHEEL_SHA256}" }},
]
"""

VALID_WORKFLOW = f"""\
env:
  UPSTREAM_REPO: basiltt/xstate-statemachine
  UPSTREAM_SHA: {PINNED_UPSTREAM_SHA}
jobs:
  pinned:
    steps:
      - uses: actions/checkout@abc # v7
        with:
          persist-credentials: false

      - name: Checkout upstream pinned commit
        uses: actions/checkout@abc # v7
        with:
          repository: ${{{{ env.UPSTREAM_REPO }}}}
          ref: ${{{{ env.UPSTREAM_SHA }}}}
          path: _upstream
          persist-credentials: false
"""

WORKFLOW_REL = ".github/workflows/xstate-nightly.yml"


def _write(root: Path, rel: str, content: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_check_pyproject_exact_pin_passes(tmp_path: Path) -> None:
    p = _write(tmp_path, "pyproject.toml", VALID_PYPROJECT)
    assert check_pyproject(p) == []


def test_check_pyproject_loose_specifier_fails(tmp_path: Path) -> None:
    loose = VALID_PYPROJECT.replace("==0.9.1", "~=0.9.1")
    p = _write(tmp_path, "pyproject.toml", loose)
    violations = check_pyproject(p)
    assert len(violations) == 1
    assert "~=0.9.1" in str(violations[0])


def test_check_pyproject_missing_entry_fails(tmp_path: Path) -> None:
    missing = """\
[project]
name = "candleviewer-api"
dependencies = ["fastapi>=0.115"]
"""
    p = _write(tmp_path, "pyproject.toml", missing)
    violations = check_pyproject(p)
    assert len(violations) == 1
    assert "no 'xstate-statemachine' entry" in str(violations[0])


def test_check_lock_matching_hash_passes(tmp_path: Path) -> None:
    p = _write(tmp_path, "uv.lock", VALID_LOCK)
    assert check_lock(p) == []


def test_check_lock_mismatched_hash_fails(tmp_path: Path) -> None:
    tampered = VALID_LOCK.replace(PINNED_WHEEL_SHA256, "f" * 64)
    p = _write(tmp_path, "uv.lock", tampered)
    violations = check_lock(p)
    assert len(violations) == 1
    assert "do not include the pinned hash" in str(violations[0])


def test_check_lock_missing_package_fails(tmp_path: Path) -> None:
    p = _write(
        tmp_path, "uv.lock", '[[package]]\nname = "other-package"\nversion = "1.0"\n'
    )
    violations = check_lock(p)
    assert len(violations) == 1
    assert "no locked 'xstate-statemachine' package entry" in str(violations[0])


def test_check_workflow_matching_sha_passes(tmp_path: Path) -> None:
    p = _write(tmp_path, WORKFLOW_REL, VALID_WORKFLOW)
    assert check_workflow(p) == []


def test_check_workflow_different_sha_fails(tmp_path: Path) -> None:
    p = _write(
        tmp_path, WORKFLOW_REL, VALID_WORKFLOW.replace(PINNED_UPSTREAM_SHA, "a" * 40)
    )
    violations = check_workflow(p)
    assert len(violations) == 1
    assert "UPSTREAM_SHA must be exactly" in str(violations[0])


def test_check_workflow_missing_line_fails(tmp_path: Path) -> None:
    p = _write(tmp_path, WORKFLOW_REL, "env:\n  UPSTREAM_REPO: x/y\n")
    violations = check_workflow(p)
    assert len(violations) == 1
    assert "no 'UPSTREAM_SHA:' line" in str(violations[0])


def test_check_workflow_ref_main_fails(tmp_path: Path) -> None:
    wf = VALID_WORKFLOW.replace("${{ env.UPSTREAM_SHA }}", "main")
    violations = check_workflow(_write(tmp_path, WORKFLOW_REL, wf))
    assert len(violations) == 1
    assert "'_upstream' checkout step must use" in str(violations[0])


def test_check_workflow_ref_tag_fails(tmp_path: Path) -> None:
    wf = VALID_WORKFLOW.replace("${{ env.UPSTREAM_SHA }}", "v0.9.1")
    violations = check_workflow(_write(tmp_path, WORKFLOW_REL, wf))
    assert len(violations) == 1
    assert "v0.9.1" in str(violations[0])


def test_check_workflow_duplicate_line_fails(tmp_path: Path) -> None:
    wf = VALID_WORKFLOW.replace("jobs:", f"  UPSTREAM_SHA: {'b' * 40}\njobs:", 1)
    violations = check_workflow(_write(tmp_path, WORKFLOW_REL, wf))
    assert len(violations) == 1
    assert "UPSTREAM_SHA must be exactly" in str(violations[0])


def test_check_workflow_comment_decoy_fails(tmp_path: Path) -> None:
    wf = VALID_WORKFLOW.replace(
        f"  UPSTREAM_SHA: {PINNED_UPSTREAM_SHA}",
        f"  # UPSTREAM_SHA: {PINNED_UPSTREAM_SHA}\n  UPSTREAM_SHA: {'c' * 40}",
        1,
    )
    violations = check_workflow(_write(tmp_path, WORKFLOW_REL, wf))
    assert len(violations) == 1
    assert "UPSTREAM_SHA must be exactly" in str(violations[0])


def test_main_exits_zero_on_clean_repo(tmp_path: Path) -> None:
    _write(tmp_path, "services/api/pyproject.toml", VALID_PYPROJECT)
    _write(tmp_path, "services/api/uv.lock", VALID_LOCK)
    _write(tmp_path, WORKFLOW_REL, VALID_WORKFLOW)
    assert main(["--root", str(tmp_path)]) == 0


def test_main_exits_one_on_violation(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "services/api/pyproject.toml",
        VALID_PYPROJECT.replace("==0.9.1", ">=0.9.1"),
    )
    _write(tmp_path, "services/api/uv.lock", VALID_LOCK)
    _write(tmp_path, WORKFLOW_REL, VALID_WORKFLOW)
    assert main(["--root", str(tmp_path)]) == 1
