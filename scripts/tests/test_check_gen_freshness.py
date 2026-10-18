"""Unit tests for tools/ci/check_gen_freshness.py (E03-T05, ADR-0013 rule 3).

Exercises the four Gherkin scenarios from the ticket by faking `subprocess.run`
so the test never actually invokes `pnpm generate` or touches real git state
(no network, deterministic, fast). The #2743 scenarios at the end run the real
gate in a throwaway git repository instead, with a stand-in for `pnpm generate`.
The contract-subset scenarios render with the generator's real renderer, which
needs PyYAML (scripts/requirements-ci.txt), as the gate does in CI.
"""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import shlex
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci import check_gen_freshness as gen_gate

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _proc(returncode: int, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _contract(*names: str) -> bytes:
    """A small contract: one GET per name, each with its own permission. The subset keeps
    `x-rbac` and drops the summary."""
    lines = ["openapi: 3.1.0", "paths:"]
    for name in names:
        lines += [
            f"  /{name}:",
            "    get:",
            f'      x-rbac: {{permissions: ["{name}:read"], scope: account}}',
            "      summary: cut from the subset",
        ]
    return "".join(f"{line}\n" for line in lines).encode()


_YAML = _contract("alpha", "middle", "omega")


def _render(source: bytes) -> bytes:
    """The artifact the generator writes for `source`: the real renderer (needs PyYAML)."""
    return gen_gate.render_contract_subset(source).encode("utf-8")


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
    artifact.write_bytes(_render(_YAML))
    monkeypatch.setattr(gen_gate, "CONTRACT_SOURCE", source)
    monkeypatch.setattr(gen_gate, "CONTRACT_ARTIFACT", artifact)
    return source, artifact


@pytest.fixture(autouse=True)
def scratch_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Step 1 removes tracked files from the cwd: never run the gate in the checkout."""
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)


# #3299: the gate fails closed when git tracks nothing under the outputs, so the fakes
# list one tracked output, in the scratch cwd, and their `pnpm generate` writes it back.
_TRACKED = "packages/protocol/src/generated/index.ts"


def _ls_files() -> SimpleNamespace:
    return _proc(0, stdout=f"{_TRACKED}\0")


def _generate() -> SimpleNamespace:
    Path(_TRACKED).parent.mkdir(parents=True, exist_ok=True)
    Path(_TRACKED).write_text("// GENERATED FILE\n", encoding="utf-8")
    return _proc(0)


def test_in_sync_tree_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scenario: An in-sync tree passes."""
    calls: list[list[str]] = []

    def fake_run(cmd, cwd=None, env=None):
        calls.append(cmd)
        if cmd[:2] == ["pnpm", "generate"]:
            return _generate()
        if cmd[:2] == ["git", "ls-files"]:
            return _ls_files()
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
            return _generate()
        if cmd[:2] == ["git", "ls-files"]:
            return _ls_files()
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
            return _generate()
        if cmd[:2] == ["git", "ls-files"]:
            return _ls_files()
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
            return _generate()
        if cmd[:2] == ["git", "ls-files"]:
            return _ls_files()
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
        if cmd[:2] == ["git", "ls-files"]:  # #3299: the outputs set aside first
            return _ls_files()
        if cmd[:2] == ["pnpm", "generate"]:
            return _proc(1, stderr="boom")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(gen_gate, "_run", fake_run)
    assert gen_gate.main([]) == 1
    err = capsys.readouterr().err
    assert "CI-GEN-004" in err


def _clean_run(cmd, cwd=None, env=None):
    if cmd[:2] == ["pnpm", "generate"]:
        return _generate()
    if cmd[:2] == ["git", "ls-files"]:
        return _ls_files()
    if cmd[:2] == ["git", "status"]:
        return _proc(0, stdout="")
    if cmd[:2] == ["git", "diff"]:
        return _proc(0)
    raise AssertionError(f"unexpected command: {cmd}")


def test_contract_subset_from_an_edited_yaml_fails_with_the_regenerate_command(
    contract_pair: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """#2555: a YAML edit without regenerating the packaged subset fails CI-GEN-001; the
    report shows what regenerating would change."""
    source, _ = contract_pair
    source.write_bytes(_contract("alpha", "beta", "middle", "omega"))
    monkeypatch.setattr(gen_gate, "_run", _clean_run)
    assert gen_gate.main([]) == 1
    err = capsys.readouterr().err
    assert "CI-GEN-001" in err and "is stale or hand-edited" in err
    assert "scripts/generate_protocol_models.py" in err
    assert '+    "/beta": {' in err


def test_regenerated_contract_subset_passes(
    contract_pair: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    source, artifact = contract_pair
    source.write_bytes(_contract("alpha", "beta", "middle", "omega"))
    artifact.write_bytes(_render(source.read_bytes()))
    monkeypatch.setattr(gen_gate, "_run", _clean_run)
    assert gen_gate.main([]) == 0


def _with_digest_line(text: str, digest: str = "0" * 64) -> str:
    """The pre-#2743 header: a digest of the whole YAML after `source`."""
    source = '    "source": "docs/plan/22-api-openapi.yaml"\n'
    assert source in text
    digest_line = f'    "source_sha256": "{digest}"\n'
    return text.replace(source, source.replace("\n", ",\n") + digest_line, 1)


@pytest.mark.parametrize(
    "edit",
    [
        pytest.param(_with_digest_line, id="digest-line"),
        pytest.param(lambda t: t.replace("alpha:read", "alpha:write"), id="value"),
        pytest.param(lambda t: json.dumps(json.loads(t)), id="reformatted"),
        pytest.param(lambda t: "", id="empty"),
        pytest.param(lambda t: "not json", id="not-json"),
    ],
)
def test_hand_edited_contract_subset_fails(
    edit: Callable[[str], str],
    contract_pair: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The committed artifact must be byte for byte what the generator renders."""
    _, artifact = contract_pair
    artifact.write_text(
        edit(artifact.read_text(encoding="utf-8")), encoding="utf-8", newline="\n"
    )
    monkeypatch.setattr(gen_gate, "_run", _clean_run)
    assert gen_gate.main([]) == 1
    err = capsys.readouterr().err
    assert "CI-GEN-001" in err and "is stale or hand-edited" in err


def test_missing_contract_subset_fails(
    contract_pair: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    contract_pair[1].unlink()
    monkeypatch.setattr(gen_gate, "_run", _clean_run)
    assert gen_gate.main([]) == 1
    err = capsys.readouterr().err
    assert "CI-GEN-001" in err and "is missing" in err


def test_contract_subset_check_ignores_crlf_checkouts(
    contract_pair: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The generator folds CRLF in the YAML, and the gate in the artifact."""
    for path in contract_pair:
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    monkeypatch.setattr(gen_gate, "_run", _clean_run)
    assert gen_gate.main([]) == 0


def test_contract_subset_check_without_pyyaml_fails_ci_gen_004(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(sys.modules, "yaml", None)  # `import yaml` raises
    monkeypatch.setattr(gen_gate, "_run", _clean_run)
    assert gen_gate.main([]) == 1
    err = capsys.readouterr().err
    assert "CI-GEN-004" in err and "'yaml'" in err
    assert gen_gate.PYYAML_INSTALL in err


@pytest.mark.parametrize(
    "source",
    [b"paths: []\n", b"paths: {\n", b""],
    ids=["no-paths-object", "syntax", "empty"],
)
def test_contract_that_cannot_be_rendered_fails_ci_gen_004(
    source: bytes,
    contract_pair: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    contract_pair[0].write_bytes(source)
    monkeypatch.setattr(gen_gate, "_run", _clean_run)
    assert gen_gate.main([]) == 1
    err = capsys.readouterr().err
    assert "CI-GEN-004" in err and "failed" in err


def test_unreadable_contract_fails_ci_gen_004(
    contract_pair: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    contract_pair[0].unlink()
    monkeypatch.setattr(gen_gate, "_run", _clean_run)
    assert gen_gate.main([]) == 1
    err = capsys.readouterr().err
    assert "CI-GEN-004" in err and "cannot read" in err


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


def test_generate_inputs_hash_every_repo_level_file_the_generators_read() -> None:
    """#2783: a read the cache key misses lets a cache hit replay stale output."""
    reads, _ = _generator_access()
    inputs = _generate_globs("packages/protocol/turbo.json", "inputs")
    assert _uncovered(reads, inputs) == []
    assert [path for path in inputs if not (_REPO_ROOT / path).is_file()] == []


@pytest.mark.parametrize("field", ["inputs", "outputs"])
def test_root_generate_task_stays_package_local(field: str) -> None:
    """#2743: every package inherits the root `generate` entry, and every package's
    typecheck and build depend on its `generate` (a task with no script still has a
    hash). A repo-level glob there would make a spec edit re-hash chart-engine, config
    and fixtures too; packages/protocol/turbo.json lists the protocol generators'."""
    tasks = json.loads((_REPO_ROOT / "turbo.json").read_text(encoding="utf-8"))["tasks"]
    globs = [g.removeprefix("!") for g in tasks["generate"].get(field, [])]
    repo_level = [g for g in globs if g.startswith("$") or ".." in g.split("/")]
    assert repo_level == []


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


def _git_run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


def _git(repo: Path, *args: str) -> str:
    result = _git_run(repo, *args)
    result.check_returncode()
    return result.stdout


@pytest.fixture
def isolated_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """Git ignores the global and system config and any repository it was run from."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def generated_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_git: None
) -> Path:
    """A freshly generated, committed tree; the gate's cwd for the test."""
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
    """The real gate passes a fresh tree and leaves it clean; the repo's .gitignore
    keeps the manifest out."""
    assert (generated_repo / _LOCAL_MANIFEST).is_file()
    assert _LOCAL_MANIFEST not in _git(generated_repo, "ls-files").splitlines()
    assert gen_gate.main([]) == 0
    assert "OK" in capsys.readouterr().out
    assert _git(generated_repo, "status", "--porcelain") == ""


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


# #3299: a committed file under the outputs `pnpm generate` writes that no generator
# writes passed every check above: it is tracked (no diff, not untracked), and the local
# manifest records whatever the directory holds. The gate removes the tracked outputs
# from the working tree before generating, and fails CI-GEN-005 on any not written back.
_ORPHANS = {
    f"{_GENERATED_DIR}/orphan.ts": _HEADER + "export type HandWritten = true;\n",
    f"{_GENERATED_DIR}/rest/extra.ts": _HEADER + "export type HandWritten = true;\n",
    # The Python twin of the CVWB layout, once no generator writes it.
    "services/api/candleviewer/ws/_generated/cvwb_layout.py": (
        '"""GENERATED FILE — DO NOT EDIT BY HAND."""\n'
    ),
}


def _commit_orphan(repo: Path, rel: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_ORPHANS[rel], encoding="utf-8", newline="\n")
    _git(repo, "add", rel)
    _git(repo, "commit", "-qm", "a hand-written file posing as generated")


@pytest.mark.parametrize("rel", sorted(_ORPHANS))
def test_committed_file_no_generator_writes_fails_ci_gen_005(
    generated_repo: Path, rel: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """The header does not save it, and its absence is not reported as drift."""
    _commit_orphan(generated_repo, rel)
    assert gen_gate.main([]) == 1
    err = capsys.readouterr().err
    assert err.startswith("CI-GEN-005: ")
    assert f"\n  - {rel}\n" in err
    assert "CI-GEN-001" not in err


def test_orphan_is_left_removed_from_the_working_tree_and_kept_in_the_index(
    generated_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The gate restores nothing and says so: the generated files are back as committed,
    the orphan is gone from the working tree only, and the report names both fixes."""
    rel = f"{_GENERATED_DIR}/orphan.ts"
    _commit_orphan(generated_repo, rel)
    assert gen_gate.main([]) == 1
    err = capsys.readouterr().err
    assert _git(generated_repo, "status", "--porcelain") == f" D {rel}\n"
    assert f"\n  git rm -- {rel}\n" in err and "`git restore -- <path>`" in err


def test_orphans_get_one_git_rm_command_and_the_gate_then_passes(
    generated_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """CI-GEN-005 prints one copy-pasteable `git rm` line that quotes every orphan; once
    it is pasted, only their deletion is staged and the gate passes."""
    spaced = f"{_GENERATED_DIR}/rest/hand written.ts"
    (generated_repo / spaced).write_text(_HEADER, encoding="utf-8")
    _git(generated_repo, "add", spaced)
    _git(generated_repo, "commit", "-qm", "an orphan with a space in its name")
    rel = f"{_GENERATED_DIR}/orphan.ts"
    _commit_orphan(generated_repo, rel)
    assert gen_gate.main([]) == 1
    lines = capsys.readouterr().err.splitlines()
    (command,) = [line for line in lines if line.startswith("  git rm -- ")]
    assert shlex.split(command) == ["git", "rm", "--", rel, spaced]
    _git(generated_repo, *shlex.split(command)[1:])
    assert gen_gate.main([]) == 0
    status = _git(generated_repo, "status", "--porcelain", "-z")
    assert status == f"D  {rel}\0D  {spaced}\0"


def test_nondeterminism_is_reported_before_an_orphan(
    generated_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Determinism stays first: two runs that differ fail CI-GEN-003 even with an orphan
    present, and the report still names the tracked file the gate left missing."""
    rel = f"{_GENERATED_DIR}/orphan.ts"
    _commit_orphan(generated_repo, rel)
    hashes = iter(["run-1", "run-2"])
    monkeypatch.setattr(gen_gate, "_hash_generated_tree", lambda roots: next(hashes))
    assert gen_gate.main([]) == 1
    err = capsys.readouterr().err
    assert err.startswith("CI-GEN-003: ") and "CI-GEN-005" not in err
    assert "1 tracked generated file(s) missing" in err and f"\n  - {rel}\n" in err


def test_generator_failure_after_the_removal_names_what_is_missing(
    generated_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A generator that fails once the gate has removed its outputs leaves them missing;
    the report lists them and one command that gets them all back from the index."""
    failing = [sys.executable, "-c", "raise SystemExit(3)"]
    monkeypatch.setattr(gen_gate, "GENERATE_CMD", failing)
    assert gen_gate.main([]) == 1
    err = capsys.readouterr().err
    assert err.startswith("CI-GEN-004: ")
    assert "2 tracked generated file(s) missing" in err
    assert "".join(f"  - {rel}\n" for rel in sorted(_GENERATED)) in err
    removed = "".join(f" D {rel}\n" for rel in sorted(_GENERATED))
    assert _git(generated_repo, "status", "--porcelain") == removed
    _paste_restore_command(generated_repo, err)
    assert _git(generated_repo, "status", "--porcelain") == ""


def _paste_restore_command(repo: Path, err: str) -> None:
    """Runs the one restore command the report prints, as pasted into a shell."""
    lines = err.splitlines()
    (command,) = [line for line in lines if line.startswith("  git restore -- ")]
    _git(repo, *shlex.split(command)[1:])


def test_a_removal_that_fails_partway_names_every_file_it_removed(
    generated_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Step 1 stops at a file it cannot remove: CI-GEN-004 names that file, and the note
    names each file already removed, with one restore command that quotes them."""
    spaced = f"{_GENERATED_DIR}/rest/a b.ts"
    (generated_repo / spaced).write_text(_HEADER, encoding="utf-8")
    _git(generated_repo, "add", spaced)
    _git(generated_repo, "commit", "-qm", "a name with a space")
    *removed, stuck = sorted([spaced, *_GENERATED])
    unlink = Path.unlink

    def unlink_or_fail(path: Path, missing_ok: bool = False) -> None:
        if path.as_posix() == stuck:
            raise PermissionError(13, "Permission denied", str(path))
        unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink_or_fail)
    assert gen_gate.main([]) == 1
    err = capsys.readouterr().err
    assert err.startswith(f"CI-GEN-004: cannot remove {stuck} before generating: ")
    assert "2 tracked generated file(s) missing" in err
    assert "".join(f"  - {rel}\n" for rel in removed) in err
    deleted = _git(generated_repo, "ls-files", "-z", "--deleted").split("\0")
    assert [rel for rel in deleted if rel] == removed
    _paste_restore_command(generated_repo, err)
    assert _git(generated_repo, "status", "--porcelain") == ""


@pytest.mark.parametrize("where", ["outputs-moved", "subdirectory"])
def test_nothing_tracked_under_the_outputs_fails_closed(
    generated_repo: Path,
    where: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With nothing to set aside the orphan check would check nothing: the gate stops
    before generating, whether the outputs moved or it runs below the repo root."""
    if where == "outputs-moved":
        moved = (Path(f"{_GENERATED_DIR}-moved"),)
        monkeypatch.setattr(gen_gate, "GENERATE_OUTPUTS", moved)
    else:
        monkeypatch.chdir(generated_repo / "packages")
    assert gen_gate.main([]) == 1
    err = capsys.readouterr().err
    assert err.startswith("CI-GEN-004: git tracks no file under ")
    assert "note:" not in err
    assert _git(generated_repo, "status", "--porcelain") == ""


def test_a_tracked_name_that_is_not_utf8_fails_ci_gen_004(
    generated_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No generator writes such a name. The gate reports it, coded, and removes nothing;
    it does not crash decoding `git ls-files`."""
    name = f"{_GENERATED_DIR}/rest/".encode() + b"\xff.ts"
    blob = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        input=b"x\n",
        cwd=generated_repo,
        capture_output=True,
        check=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "update-index", "--add", "--index-info"],
        input=b"100644 " + blob + b"\t" + name + b"\n",
        cwd=generated_repo,
        check=True,
    )
    assert gen_gate.main([]) == 1
    err = capsys.readouterr().err
    assert err.startswith("CI-GEN-004: ")
    assert f"\n  - {_GENERATED_DIR}/rest/\\xff.ts\n" in err
    assert all((generated_repo / rel).is_file() for rel in _GENERATED)


def test_orphan_check_covers_the_gated_outputs_of_pnpm_generate() -> None:
    """GENERATE_OUTPUTS are the protocol `generate` task's outputs (pinned above to what
    the generators write) that the gate covers. The local manifest is git-ignored, so
    never a tracked orphan; `pnpm generate` writes neither CVWB vectors nor corpus."""
    turbo = (_REPO_ROOT / _PROTOCOL / "turbo.json").read_text(encoding="utf-8")
    gated = [p.as_posix() for p in gen_gate.GENERATED_PATHS]
    covered: set[str] = set()
    for glob in json.loads(turbo)["tasks"]["generate"]["outputs"]:
        path = glob.removeprefix(_TURBO_ROOT)
        if path == glob:  # relative to the package
            path = f"{_PROTOCOL}/{glob}"
        path = path.removesuffix("/**")
        if any(path == g or path.startswith(f"{g}/") for g in gated):
            covered.add(path)
    covered.discard(_LOCAL_MANIFEST)
    assert {p.as_posix() for p in gen_gate.GENERATE_OUTPUTS} == covered


# #2743 acceptance 1, for the packaged contract subset: two PRs that each add a different
# operation merge back-to-back without a rebase. Each branch regenerates the artifact with
# the real renderer, as a contract PR does; the merged tree must pass the gate as merged.
def _merge_two_contract_prs(
    source: Path, artifact: Path, render: Callable[[bytes], bytes]
) -> subprocess.CompletedProcess[str]:
    repo = source.parent
    artifact.write_bytes(render(source.read_bytes()))
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", source.name, artifact.name)
    _git(repo, "commit", "-qm", "base")
    for branch, added in (("first", "beta"), ("second", "psi")):
        _git(repo, "checkout", "-q", "-b", branch, "main")
        source.write_bytes(_contract(*sorted({"alpha", "middle", "omega", added})))
        artifact.write_bytes(render(source.read_bytes()))
        _git(repo, "commit", "-qam", f"add GET /{added}")
    _git(repo, "checkout", "-q", "first")
    return _git_run(repo, "merge", "--no-edit", "second")


def test_contract_prs_adding_different_operations_merge_cleanly_and_pass(
    isolated_git: None, contract_pair: tuple[Path, Path]
) -> None:
    source, artifact = contract_pair
    merged = _merge_two_contract_prs(source, artifact, _render)
    assert merged.returncode == 0, merged.stdout + merged.stderr
    assert source.read_bytes() == _contract("alpha", "beta", "middle", "omega", "psi")
    gen_gate.check_contract_subset()  # raises GenGateError unless the merge is fresh


def test_a_digest_of_the_whole_yaml_in_the_subset_makes_them_conflict(
    isolated_git: None, contract_pair: tuple[Path, Path]
) -> None:
    """The control for the test above: the pre-#2743 header, with `source_sha256`."""

    def render_with_digest(source: bytes) -> bytes:
        text = _render(source).decode("utf-8")
        return _with_digest_line(text, hashlib.sha256(source).hexdigest()).encode()

    merged = _merge_two_contract_prs(*contract_pair, render_with_digest)
    assert merged.returncode != 0
    assert "CONFLICT" in merged.stdout and "contract_subset.json" in merged.stdout
