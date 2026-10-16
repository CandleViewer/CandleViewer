"""Real-git scenarios for tools/ci/check_gen_freshness.py (#2743).

packages/protocol no longer commits a manifest of generated-file hashes, so the
gate alone must catch a hand edit of a committed generated file: regenerating
overwrites the edit and `git diff` reports it (CI-GEN-001). These tests run the
real gate against a throwaway git repository with the repo's own .gitignore;
only `pnpm generate` is replaced, by a stand-in that rewrites two generated
files and the git-ignored local manifest (no node toolchain, no network).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci import check_gen_freshness as gen_gate

ROOT = Path(__file__).resolve().parents[2]
HEADER = "// GENERATED FILE — DO NOT EDIT BY HAND.\n"
GENERATED = {
    "packages/protocol/src/generated/rest/index.ts": HEADER + "export type Rest = 1;\n",
    "packages/protocol/src/generated/ws/index.ts": HEADER + "export type Ws = 1;\n",
}
LOCAL_MANIFEST = "packages/protocol/.cache/generated-manifest.json"
GENERATOR = f"""
import json, pathlib
files = {GENERATED!r}
for rel, text in files.items():
    path = pathlib.Path(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\\n")
manifest = pathlib.Path({LOCAL_MANIFEST!r})
manifest.parent.mkdir(parents=True, exist_ok=True)
manifest.write_text(json.dumps(sorted(files)), encoding="utf-8")
"""
_YAML = b"openapi: 3.1.0\npaths: {}\n"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A freshly generated, committed tree; the gate's cwd for the test."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".gitignore").write_text(
        (ROOT / ".gitignore").read_text(encoding="utf-8"), encoding="utf-8"
    )
    # The #2555 contract subset, generated from the committed YAML.
    (root / gen_gate.CONTRACT_SOURCE).parent.mkdir(parents=True)
    (root / gen_gate.CONTRACT_SOURCE).write_bytes(_YAML)
    (root / gen_gate.CONTRACT_ARTIFACT).parent.mkdir(parents=True)
    (root / gen_gate.CONTRACT_ARTIFACT).write_text(
        json.dumps(
            {"x-cv-generated": {"source_sha256": hashlib.sha256(_YAML).hexdigest()}}
        ),
        encoding="utf-8",
    )
    generator = tmp_path / "generate.py"
    generator.write_text(GENERATOR, encoding="utf-8")
    monkeypatch.setattr(gen_gate, "GENERATE_CMD", [sys.executable, str(generator)])
    monkeypatch.chdir(root)
    subprocess.run(gen_gate.GENERATE_CMD, check=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "generated")
    return root


def test_fresh_tree_passes_and_the_local_manifest_stays_untracked(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (repo / LOCAL_MANIFEST).is_file()
    assert LOCAL_MANIFEST not in _git(repo, "ls-files").splitlines()
    assert gen_gate.main([]) == 0
    assert "OK" in capsys.readouterr().out


@pytest.mark.parametrize("rel", sorted(GENERATED))
def test_committed_hand_edit_of_a_generated_file_fails_ci_gen_001(
    repo: Path, rel: str, capsys: pytest.CaptureFixture[str]
) -> None:
    path = repo / rel
    path.write_text(
        path.read_text(encoding="utf-8") + "export type HandEdited = true;\n",
        encoding="utf-8",
        newline="\n",
    )
    _git(repo, "commit", "-qam", "hand edit")
    assert gen_gate.main([]) == 1
    err = capsys.readouterr().err
    assert "CI-GEN-001" in err
    assert f"a/{rel}" in err and "-export type HandEdited = true;" in err


def test_local_manifest_would_fail_ci_gen_002_if_it_were_not_ignored(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The .gitignore entry is load-bearing: without it the manifest is untracked output."""
    (repo / ".gitignore").write_text("", encoding="utf-8")
    _git(repo, "commit", "-qam", "no ignores")
    assert gen_gate.main([]) == 1
    err = capsys.readouterr().err
    assert "CI-GEN-002" in err and "packages/protocol/.cache/" in err
