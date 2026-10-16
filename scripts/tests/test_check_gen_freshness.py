"""Unit tests for tools/ci/check_gen_freshness.py (E03-T05, ADR-0013 rule 3).

Exercises the four Gherkin scenarios from the ticket by faking `subprocess.run`
so the test never actually invokes `pnpm generate` or touches real git state
(no network, deterministic, fast). The #2743 scenarios at the end run the real
gate in a throwaway git repository instead, with a stand-in for `pnpm generate`.
"""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci import check_gen_freshness as gen_gate

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _proc(returncode: int, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


_YAML = b"openapi: 3.1.0\npaths: {}\n"


def _subset(source: bytes) -> str:
    """A contract-subset artifact header recording the SHA-256 of `source`."""
    return json.dumps(
        {"x-cv-generated": {"source_sha256": hashlib.sha256(source).hexdigest()}}
    )


@pytest.fixture(autouse=True)
def bare_generate_cmd(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fakes match `pnpm generate`; shutil.which turns a pnpm on PATH absolute."""
    monkeypatch.setattr(gen_gate, "GENERATE_CMD", ["pnpm", "generate"])


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

    def fake_run(cmd, cwd=None, env=None):
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

    def fake_run(cmd, cwd=None, env=None):
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

    def fake_run(cmd, cwd=None, env=None):
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

    def fake_run(cmd, cwd=None, env=None):
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
    def fake_run(cmd, cwd=None, env=None):
        if cmd[:2] == ["pnpm", "generate"]:
            return _proc(1, stderr="boom")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(gen_gate, "_run", fake_run)
    assert gen_gate.main([]) == 1
    err = capsys.readouterr().err
    assert "CI-GEN-004" in err


def _clean_run(cmd, cwd=None, env=None):
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


def test_generator_runs_with_turbo_force_and_the_inherited_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#2783: each generator run bypasses the turbo cache, even over an exported
    TURBO_FORCE=false, and keeps the rest of the environment."""
    monkeypatch.setenv("TURBO_FORCE", "false")
    monkeypatch.setenv("CV_GEN_GATE_PROBE", "kept")
    generate_envs: list[dict[str, str] | None] = []

    def fake_run(cmd, cwd=None, env=None):
        if cmd[:2] == ["pnpm", "generate"]:
            generate_envs.append(env)
        return _clean_run(cmd, cwd, env)

    monkeypatch.setattr(gen_gate, "_run", fake_run)
    assert gen_gate.main([]) == 0
    assert len(generate_envs) == 2
    for env in generate_envs:
        assert env is not None
        assert env["TURBO_FORCE"] == "true"
        assert env["CV_GEN_GATE_PROBE"] == "kept"


# #2783: the turbo `generate` cache key must hash every repo-level file the protocol
# generators read, and its outputs must hold every repo-level file they write, or a
# cache hit replays output built from an older spec. The file lists below are derived
# from the generator scripts, never copied from the turbo configs they check.
_PROTOCOL = "packages/protocol"
_TURBO_ROOT = "$TURBO_ROOT$/"
_STR = r'"[^"\n]*"'
# `join(base, "a", "b")`: how the generator scripts build every path they touch.
_JOIN = re.compile(rf"(?<![.\w])join\(\s*(\w+)((?:\s*,\s*{_STR})+)\s*,?\s*\)")
# A literal argv such as ["tools", "gen", "export_x.py"]: a repo-level script run.
_ARGV = re.compile(rf"\[\s*({_STR}(?:\s*,\s*{_STR})+)\s*,?\s*\]")
_RELATIVE_IMPORT = re.compile(
    r"""(?:\bfrom|\bimport\s*\(?|\brequire\(|\bnew URL\()\s*["'](\.{1,2}/[^"'\n]+)["']"""
)
_RESOLVE_CONFIG = re.compile(r"\bresolveConfig\(\s*([^)]*)\)")
_PY_PATH = re.compile(rf"^(\w+)\s*=\s*REPO_ROOT((?:\s*/\s*{_STR})+)", re.MULTILINE)
_PY_IMPORT = re.compile(r"^\s*(?:from|import)\s+([\w.]+)", re.MULTILINE)
# Mentions of a path variable that do not read the file (VAR stands for the name).
_MJS_WRITE = r"\bwriteFileSync\(\s*VAR"
_MJS_NOT_READS = (
    r"\bconst\s+VAR\s*=",
    r"\b(?:mkdirSync|dirname|resolveConfig)\(\s*VAR",
    r"\bjoin\(\s*VAR\s*,",
    r"\b(?:filepath|cwd):\s*VAR",
    r"\$\{\s*VAR\s*\}",
)
_PY_WRITE = r"\bVAR\.write_(?:text|bytes)\("
_PY_NOT_READS = (r"^VAR\s*=", r"\bVAR\.parent\b", r"\{VAR\}")
# Where prettier.resolveConfig looks, in order, in each directory (prettier 3).
_PRETTIER_CONFIGS = (
    "package.json",
    "package.yaml",
    ".prettierrc",
    ".prettierrc.json",
    ".prettierrc.yaml",
    ".prettierrc.yml",
    ".prettierrc.json5",
    ".prettierrc.js",
    ".prettierrc.ts",
    ".prettierrc.mjs",
    ".prettierrc.mts",
    ".prettierrc.cjs",
    ".prettierrc.cts",
    "prettier.config.js",
    "prettier.config.ts",
    "prettier.config.mjs",
    "prettier.config.mts",
    "prettier.config.cjs",
    "prettier.config.cts",
    ".prettierrc.toml",
)


def _segments(literals: str) -> list[str]:
    return re.findall(r'"([^"\n]*)"', literals)


def _uses(source: str, name: str, write: str, not_reads: tuple[str, ...]) -> set[str]:
    """Whether a script reads and/or writes the file a path variable names.

    Any mention that is neither a write nor a known non-read (defining it, deriving
    another path from it, creating its directory, logging it) counts as a read.
    """
    var = rf"(?P<var>\b{re.escape(name)}\b)"
    accounted: set[int] = set()
    kinds: set[str] = set()
    for kind, pattern in (("write", write), *(("other", p) for p in not_reads)):
        for match in re.finditer(pattern.replace("VAR", var), source, re.MULTILINE):
            accounted.add(match.start("var"))
            if kind == "write":
                kinds.add("write")
    mentions = re.finditer(rf"\b{re.escape(name)}\b", source)
    if any(m.start() not in accounted for m in mentions):
        kinds.add("read")
    return kinds


def _imports(path: str) -> set[str]:
    """`path` plus every repo file it imports by a relative specifier, transitively."""
    found = {path}
    source = (_REPO_ROOT / path).read_text(encoding="utf-8")
    for spec in _RELATIVE_IMPORT.findall(source):
        target = posixpath.normpath(posixpath.join(posixpath.dirname(path), spec))
        if target not in found and (_REPO_ROOT / target).is_file():
            found |= _imports(target)
    return found


def _holds_prettier_config(config: Path) -> bool:
    """A package manifest counts only when it has a top-level `prettier` key."""
    text = config.read_text(encoding="utf-8")
    if config.name == "package.json":
        return "prettier" in json.loads(text)
    if config.name == "package.yaml":
        return re.search(r"^prettier\s*:", text, re.MULTILINE) is not None
    return True


def _prettier_config(formatted: str) -> set[str]:
    """The config prettier.resolveConfig(formatted) loads, with what it imports."""
    directory = posixpath.dirname(formatted)
    while True:
        for name in _PRETTIER_CONFIGS:
            candidate = posixpath.join(directory, name)
            config = _REPO_ROOT / candidate
            if config.is_file() and _holds_prettier_config(config):
                return _imports(candidate)
        if not directory:
            return set()
        directory = posixpath.dirname(directory)


def _python_access(script: str) -> tuple[set[str], set[str]]:
    """What a stdlib exporter run by `pnpm generate` reads (itself included) and writes."""
    source = (_REPO_ROOT / script).read_text(encoding="utf-8")
    reads: set[str] = {script}
    writes: set[str] = set()
    for match in _PY_PATH.finditer(source):
        path = posixpath.join(*_segments(match.group(2)))
        kinds = _uses(source, match.group(1), _PY_WRITE, _PY_NOT_READS)
        if "read" in kinds:
            reads.add(path)
        if "write" in kinds:
            writes.add(path)
    for module in _PY_IMPORT.findall(source):
        local = posixpath.join(posixpath.dirname(script), *module.split(".")) + ".py"
        if (_REPO_ROOT / local).is_file():
            reads.add(local)
    return reads, writes


def _script_access(script: Path) -> tuple[set[str], set[str]]:
    """Repo-relative files one generator script reads and writes."""
    source = script.read_text(encoding="utf-8")
    here = script.parent.relative_to(_REPO_ROOT).as_posix()
    paths = {"__dirname": here}
    reads = _imports(script.relative_to(_REPO_ROOT).as_posix())
    writes: set[str] = set()
    for match in _JOIN.finditer(source):
        base = match.group(1)
        assert base in paths, f"{script.name}: cannot resolve join({base}, ...)"
        path = posixpath.normpath(
            posixpath.join(paths[base], *_segments(match.group(2)))
        )
        before = source[: match.start()]
        bound = re.search(r"\bconst\s+(\w+)\s*=\s*\Z", before)
        if bound:
            paths[bound.group(1)] = path
            kinds = _uses(source, bound.group(1), _MJS_WRITE, _MJS_NOT_READS)
        else:  # an inline join(...): the call it is passed to decides
            callee = re.search(r"(\w+)\(\s*\Z", before)
            name = callee.group(1) if callee else ""
            kinds = {"writeFileSync": {"write"}, "mkdirSync": set()}.get(name, {"read"})
        if "read" in kinds:
            reads.add(path)
        if "write" in kinds:
            writes.add(path)
    for argument in _RESOLVE_CONFIG.findall(source):
        assert argument.strip() in paths, f"{script.name}: resolveConfig({argument})"
        reads |= _prettier_config(paths[argument.strip()])
    for match in _ARGV.finditer(source):
        argv = _segments(match.group(1))
        if argv[-1].endswith(".py"):
            exporter_reads, exporter_writes = _python_access(posixpath.join(*argv))
            reads |= exporter_reads
            writes |= exporter_writes
    return reads, writes


def _repo_level(paths: set[str]) -> set[str]:
    inside = (".", _PROTOCOL)
    return {p for p in paths if p not in inside and not p.startswith(_PROTOCOL + "/")}


def _generator_access() -> tuple[set[str], set[str]]:
    """Repo-level files (outside packages/protocol) the protocol generators read/write."""
    reads: set[str] = set()
    writes: set[str] = set()
    for script in sorted((_REPO_ROOT / _PROTOCOL / "scripts").glob("*.mjs")):
        script_reads, script_writes = _script_access(script)
        reads |= script_reads
        writes |= script_writes
    return _repo_level(reads), _repo_level(writes)


def _generate_globs(config: str, field: str) -> list[str]:
    """The `$TURBO_ROOT$/...` globs of a generate task field, made repo-relative."""
    tasks = json.loads((_REPO_ROOT / config).read_text(encoding="utf-8"))["tasks"]
    globs: list[str] = tasks["generate"].get(field, [])  # absent: package files only
    return [g.removeprefix(_TURBO_ROOT) for g in globs if g.startswith(_TURBO_ROOT)]


def _uncovered(paths: set[str], globs: list[str]) -> list[str]:
    def covered(path: str) -> bool:
        if (_REPO_ROOT / path).is_dir():
            return any(glob.startswith(path + "/") for glob in globs)
        return path in globs or any(
            glob.endswith("/**") and path.startswith(glob[:-2]) for glob in globs
        )

    return sorted(path for path in paths if not covered(path))


def test_generator_access_is_derived_from_the_scripts() -> None:
    """The derivation still sees what the generators are known to read and write."""
    reads, writes = _generator_access()
    assert {
        "docs/plan/22-api-openapi.yaml",
        "docs/plan/23-ws-protocol.md",
        "docs/plan/ws-schema.json",
        "packages/config/prettier.config.mjs",
        "prettier.config.mjs",
        "tools/gen/export_instrument_policy_corpus.py",
    } <= reads
    assert {
        "docs/plan/ws-schema.json",
        "packages/fixtures/golden/policy/corpus.json",
        "services/api/candleviewer/ws/_generated/cvwb_layout.py",
    } <= writes


@pytest.mark.parametrize("config", ["turbo.json", "packages/protocol/turbo.json"])
def test_generate_inputs_hash_every_repo_level_file_the_generators_read(
    config: str,
) -> None:
    """#2783: a read the cache key misses lets a cache hit replay stale output."""
    reads, _ = _generator_access()
    inputs = _generate_globs(config, "inputs")
    assert _uncovered(reads, inputs) == []
    assert [path for path in inputs if not (_REPO_ROOT / path).is_file()] == []


def test_generate_outputs_keep_every_repo_level_file_the_generators_write() -> None:
    """#2783: a cache hit restores only the outputs; anything else stays stale."""
    _, writes = _generator_access()
    outputs = _generate_globs("packages/protocol/turbo.json", "outputs")
    assert _uncovered(writes, outputs) == []


# #2743: packages/protocol no longer commits a manifest of generated-file hashes, so
# this gate alone must catch a committed hand edit of a generated file: regenerating
# overwrites the edit and `git diff` reports it (CI-GEN-001). These scenarios run the
# real gate against a throwaway git repository with the repo's own .gitignore; only
# `pnpm generate` is replaced, by a stand-in that rewrites two generated files and
# the git-ignored local manifest (no node toolchain, no network). The contract
# subset pair is the autouse `contract_pair`.
_HEADER = "// GENERATED FILE — DO NOT EDIT BY HAND.\n"
_GENERATED_DIR = "packages/protocol/src/generated"
_GENERATED = {
    f"{_GENERATED_DIR}/rest/index.ts": _HEADER + "export type Rest = 1;\n",
    f"{_GENERATED_DIR}/ws/index.ts": _HEADER + "export type Ws = 1;\n",
}
_LOCAL_MANIFEST = "packages/protocol/.cache/generated-manifest.json"
_GENERATOR = f"""
import json, pathlib
files = {_GENERATED!r}
for rel, text in files.items():
    path = pathlib.Path(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\\n")
manifest = pathlib.Path({_LOCAL_MANIFEST!r})
manifest.parent.mkdir(parents=True, exist_ok=True)
manifest.write_text(json.dumps(sorted(files)), encoding="utf-8")
"""


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


@pytest.fixture
def generated_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A freshly generated, committed tree; the gate's cwd for the test."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(name, raising=False)
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".gitignore").write_text(
        (_REPO_ROOT / ".gitignore").read_text(encoding="utf-8"), encoding="utf-8"
    )
    generator = tmp_path / "generate.py"
    generator.write_text(_GENERATOR, encoding="utf-8")
    monkeypatch.setattr(gen_gate, "GENERATE_CMD", [sys.executable, str(generator)])
    monkeypatch.chdir(root)
    subprocess.run(gen_gate.GENERATE_CMD, check=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "generated")
    return root


def test_fresh_tree_passes_and_the_local_manifest_stays_untracked(
    generated_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The real gate passes a fresh tree; the repo's .gitignore keeps the manifest out."""
    assert (generated_repo / _LOCAL_MANIFEST).is_file()
    assert _LOCAL_MANIFEST not in _git(generated_repo, "ls-files").splitlines()
    assert gen_gate.main([]) == 0
    assert "OK" in capsys.readouterr().out


@pytest.mark.parametrize("rel", sorted(_GENERATED))
def test_committed_hand_edit_of_a_generated_file_fails_ci_gen_001(
    generated_repo: Path, rel: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """A committed hand edit fails with no committed manifest to compare against."""
    path = generated_repo / rel
    path.write_text(
        path.read_text(encoding="utf-8") + "export type HandEdited = true;\n",
        encoding="utf-8",
        newline="\n",
    )
    _git(generated_repo, "commit", "-qam", "hand edit")
    assert gen_gate.main([]) == 1
    err = capsys.readouterr().err
    assert "CI-GEN-001" in err
    assert f"a/{rel}" in err and "-export type HandEdited = true;" in err


def test_local_manifest_would_fail_ci_gen_002_if_it_were_not_ignored(
    generated_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """With no ignore rule covering it (the test empties .gitignore; in the repo the
    generic `.cache/` line covers it), the local manifest is untracked output."""
    (generated_repo / ".gitignore").write_text("", encoding="utf-8")
    _git(generated_repo, "commit", "-qam", "no ignores")
    assert gen_gate.main([]) == 1
    err = capsys.readouterr().err
    assert "CI-GEN-002" in err and "packages/protocol/.cache/" in err
