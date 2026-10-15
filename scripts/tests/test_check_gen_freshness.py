"""Unit tests for tools/ci/check_gen_freshness.py (E03-T05, ADR-0013 rule 3).

Exercises the four Gherkin scenarios from the ticket by faking `subprocess.run`
so the test never actually invokes `pnpm generate` or touches real git state
(no network, deterministic, fast).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci import check_gen_freshness as gen_gate


def _proc(returncode: int, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


_YAML = b"openapi: 3.1.0\npaths: {}\n"


def _subset(source: bytes) -> str:
    """A contract-subset artifact header recording the SHA-256 of `source`."""
    return json.dumps(
        {"x-cv-generated": {"source_sha256": hashlib.sha256(source).hexdigest()}}
    )


@pytest.fixture(autouse=True)
def contract_pair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Points the #2555 contract-subset check at a matching tmp pair (hermetic scenarios)."""
    source, artifact = (
        tmp_path / "22-api-openapi.yaml",
        tmp_path / "contract_subset.json",
    )
    source.write_bytes(_YAML)
    artifact.write_text(_subset(_YAML), encoding="utf-8")
    monkeypatch.setattr(gen_gate, "CONTRACT_SOURCE", source)
    monkeypatch.setattr(gen_gate, "CONTRACT_ARTIFACT", artifact)
    return source, artifact


def test_in_sync_tree_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scenario: An in-sync tree passes."""
    calls: list[list[str]] = []

    def fake_run(cmd, cwd=None):
        calls.append(cmd)
        if cmd[:2] == ["pnpm", "generate"]:
            return _proc(0)
        if cmd[:2] == ["git", "ls-files"]:
            return _proc(0, stdout="")
        if cmd[:2] == ["git", "diff"]:
            return _proc(0)
        if cmd[:2] == ["git", "status"]:
            return _proc(0, stdout="")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(gen_gate, "_run", fake_run)
    assert gen_gate.main([]) == 0


def test_schema_edit_without_regeneration_fails_with_diff_and_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Scenario: A schema edit without regeneration fails."""

    def fake_run(cmd, cwd=None):
        if cmd[:2] == ["pnpm", "generate"]:
            return _proc(0)
        if cmd[:2] == ["git", "ls-files"]:
            return _proc(0, stdout="")
        if cmd[:2] == ["git", "diff"]:
            return _proc(
                1, stdout="--- a/packages/protocol/src/generated/rest.ts\n+++ ..."
            )
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(gen_gate, "_run", fake_run)
    assert gen_gate.main([]) == 1
    err = capsys.readouterr().err
    assert "CI-GEN-001" in err
    assert "make gen" in err


def test_untracked_generated_output_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Scenario: Untracked generated output fails."""

    def fake_run(cmd, cwd=None):
        if cmd[:2] == ["pnpm", "generate"]:
            return _proc(0)
        if cmd[:2] == ["git", "ls-files"]:
            return _proc(0, stdout="")
        if cmd[:2] == ["git", "diff"]:
            return _proc(0)
        if cmd[:2] == ["git", "status"]:
            return _proc(0, stdout="?? packages/protocol/src/generated/new-file.ts\n")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(gen_gate, "_run", fake_run)
    assert gen_gate.main([]) == 1
    err = capsys.readouterr().err
    assert "CI-GEN-002" in err


def test_nondeterministic_generation_fails_before_diff_check(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Scenario: Non-deterministic generation is caught, before diff runs."""
    hash_calls = {"n": 0}
    diff_called = {"value": False}

    def fake_run(cmd, cwd=None):
        if cmd[:2] == ["pnpm", "generate"]:
            return _proc(0)
        if cmd[:2] == ["git", "ls-files"]:
            return _proc(0, stdout="")
        if cmd[:2] == ["git", "diff"]:
            diff_called["value"] = True
            return _proc(0)
        raise AssertionError(f"unexpected command: {cmd}")

    def fake_hash(root):
        hash_calls["n"] += 1
        return f"hash-{hash_calls['n']}"

    monkeypatch.setattr(gen_gate, "_run", fake_run)
    monkeypatch.setattr(gen_gate, "_hash_generated_tree", fake_hash)

    assert gen_gate.main([]) == 1
    err = capsys.readouterr().err
    assert "CI-GEN-003" in err
    assert "codegen is not deterministic" in err
    assert diff_called["value"] is False


def test_generator_toolchain_failure_reports_ci_gen_004(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_run(cmd, cwd=None):
        if cmd[:2] == ["pnpm", "generate"]:
            return _proc(1, stderr="boom")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(gen_gate, "_run", fake_run)
    assert gen_gate.main([]) == 1
    err = capsys.readouterr().err
    assert "CI-GEN-004" in err


def _clean_run(cmd, cwd=None):
    if cmd[:2] == ["pnpm", "generate"]:
        return _proc(0)
    if cmd[:2] in (["git", "ls-files"], ["git", "status"]):
        return _proc(0, stdout="")
    if cmd[:2] == ["git", "diff"]:
        return _proc(0)
    raise AssertionError(f"unexpected command: {cmd}")


def test_contract_subset_from_another_yaml_fails_with_the_regenerate_command(
    contract_pair: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """#2555: a YAML edit without regenerating the packaged subset fails CI-GEN-001."""
    source, _ = contract_pair
    source.write_bytes(_YAML + b"x-new: 1\n")
    monkeypatch.setattr(gen_gate, "_run", _clean_run)
    assert gen_gate.main([]) == 1
    err = capsys.readouterr().err
    assert "CI-GEN-001" in err and "is stale" in err
    assert "scripts/generate_protocol_models.py" in err


@pytest.mark.parametrize("body", ["", "{}", '{"x-cv-generated": {}}', "[]", "not json"])
def test_contract_subset_without_a_source_hash_fails(
    body: str,
    contract_pair: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, artifact = contract_pair
    artifact.write_text(body, encoding="utf-8")
    monkeypatch.setattr(gen_gate, "_run", _clean_run)
    assert gen_gate.main([]) == 1
    assert "records no source hash" in capsys.readouterr().err


def test_missing_contract_subset_fails(
    contract_pair: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    contract_pair[1].unlink()
    monkeypatch.setattr(gen_gate, "_run", _clean_run)
    assert gen_gate.main([]) == 1
    assert "CI-GEN-001" in capsys.readouterr().err


def test_contract_subset_hash_ignores_crlf_checkouts(
    contract_pair: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The generator hashes LF bytes; a CRLF checkout of the same YAML still matches."""
    source, _ = contract_pair
    source.write_bytes(_YAML.replace(b"\n", b"\r\n"))
    monkeypatch.setattr(gen_gate, "_run", _clean_run)
    assert gen_gate.main([]) == 0
