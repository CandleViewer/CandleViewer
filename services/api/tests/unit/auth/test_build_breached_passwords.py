"""`scripts/build_breached_passwords.py` (#5269, SR-028): the header records the SecLists commit and
each source's path under the SecLists root and SHA-256, the output is deterministic, and a list
below the floor is refused. Local files only (C-13.5)."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from candleviewer.auth import password_policy as pp

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "build_breached_passwords.py"
_COMMIT = "00f80ec9cc39bed63ee40cf6805a6b1b77e87644"


def _generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_breached_passwords", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_header_names_the_commit_and_each_source_and_the_output_is_deterministic(
    tmp_path: Path,
) -> None:
    gen = _generator()
    root = tmp_path / "SecLists"
    (root / "Passwords" / "Leaked-Databases").mkdir(parents=True)
    first = root / "Passwords" / "a.txt"
    second = root / "Passwords" / "Leaked-Databases" / "b.txt"
    first.write_text("short\nCorrect-Horse-Battery\n")
    second.write_text("correct-horse-battery\nanother-long-entry\n")
    out, again = tmp_path / "out.sha1", tmp_path / "again.sha1"
    for target in (out, again):
        args = ["--commit", _COMMIT, "--root", str(root), "--allow-small"]
        args += ["--source", str(first), "--source", str(second), "--out", str(target)]
        assert gen.main(args) == 0
    text = out.read_text()
    assert text == again.read_text()
    assert f"# SecLists commit: {_COMMIT}\n" in text
    for path in (first, second):  # each recorded by its path under the root, not a fixed dir
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        assert f"# Source file: {path.relative_to(root).as_posix()} sha256 {sha}\n" in text
    expected = {pp.digest("correct-horse-battery"), pp.digest("another-long-entry")}
    assert pp.parse_breached_list(text) == expected  # case-folded, de-duplicated, short dropped


@pytest.mark.parametrize("commit", ["", "00f80ec9", "Z" * 40])
def test_a_source_without_a_full_commit_sha_is_refused(tmp_path: Path, commit: str) -> None:
    source = tmp_path / "a.txt"
    source.write_text("another-long-entry\n")
    args = ["--commit", commit, "--root", str(tmp_path), "--allow-small", "--source", str(source)]
    with pytest.raises(SystemExit):
        _generator().main([*args, "--out", str(tmp_path / "out.sha1")])


def test_a_source_outside_the_root_is_refused(tmp_path: Path) -> None:
    (tmp_path / "root").mkdir()
    source = tmp_path / "a.txt"
    source.write_text("another-long-entry\n")
    out = tmp_path / "out.sha1"
    args = ["--commit", _COMMIT, "--root", str(tmp_path / "root"), "--allow-small"]
    with pytest.raises(SystemExit):
        _generator().main([*args, "--source", str(source), "--out", str(out)])
    assert not out.exists()


def test_a_list_below_the_floor_is_refused_without_allow_small(tmp_path: Path) -> None:
    """#5269: a sub-floor list would make the policy fail closed, so it is never written by
    default (here 1 digest, far below `BREACHED_LIST_MIN`)."""
    source = tmp_path / "a.txt"
    source.write_text("another-long-entry\n")
    out = tmp_path / "out.sha1"
    args = ["--commit", _COMMIT, "--root", str(tmp_path), "--source", str(source)]
    with pytest.raises(SystemExit):
        _generator().main([*args, "--out", str(out)])
    assert not out.exists()


def test_the_seed_option_is_gone(tmp_path: Path) -> None:
    """#5269: the 8-entry seed always fails closed, so the generator no longer writes it."""
    with pytest.raises(SystemExit):
        _generator().main(["--seed", "--out", str(tmp_path / "out.sha1")])
