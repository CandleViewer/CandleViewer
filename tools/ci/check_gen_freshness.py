#!/usr/bin/env python3
"""E03-T05: generated-code freshness gate for ``packages/protocol``.

ADR-0013 binding rule 3: "packages/protocol is regenerated from
22-api-openapi.yaml and the WS schema; any diff fails the build. Generated
files are committed so consumers need no codegen step." ADR-0005 reinforces
it for the binary WS framing constants.

This script is the single implementation invoked by the ``gen`` step of the
``gates`` job in ``.github/workflows/pr.yml`` and locally via ``make gen-check``:

1. Removes every tracked file under the outputs ``pnpm generate`` writes in
   full (``GENERATE_OUTPUTS``: ``packages/protocol/src/generated`` and the
   Python twin of the CVWB layout) from the working tree, never from the
   index, so the first generation run starts without them (#3299).
2. Runs the generator (``pnpm generate``, i.e. ``make gen``) twice in a row
   on the current checkout and hashes the generated tree after each run.
   Each run sets ``TURBO_FORCE=true``, so the generators really execute and a
   turbo cache entry is never replayed as fresh output (#2783).
   If the two hashes differ, generation is non-deterministic (CI-GEN-003)
   and we fail *before* even looking at git diff, so a flaky generator never
   masquerades as a "someone forgot to regenerate" freshness failure.
3. Fails CI-GEN-005, naming each path, when generation did not write back a
   file step 1 removed: a committed file that no generator writes. A
   hand-written file must not pose as generated (C-4.16), yet with the
   GENERATED header it passed every other check: it is tracked, so it shows
   no diff and is not untracked, and the guard's local manifest records
   whatever the directory holds. The gate restores nothing: such a file stays
   removed from the working tree (the index keeps it), and the report prints
   one `git rm` command that deletes them all. Every other failed run lists
   the tracked files it leaves missing, with one `git restore` command that
   brings them all back. Step 1 fails closed (CI-GEN-004) when git tracks
   nothing under the outputs, which would leave this step nothing to check.
4. Runs ``git diff --exit-code -- packages/protocol`` (CI-GEN-001: drift
   against a committed schema change). This is also the hand-edit guard for
   committed generated files: regenerating overwrites the edit, so it shows
   up as a diff. No committed manifest takes part (#2743).
5. Runs ``git status --porcelain -- packages/protocol`` (CI-GEN-002:
   untracked generated output the diff cannot see).
6. Renders the packaged contract subset (#2555) again from the committed
   ``docs/plan/22-api-openapi.yaml`` with the generator's own renderer and
   compares it with the committed artifact (CI-GEN-001), the way step 4 does
   for packages/protocol: a YAML edit that skipped regeneration and a hand
   edit of the artifact both fail. The artifact records no digest of the YAML
   (#2743), so two PRs that change different operations do not conflict on it.

Exit codes: 0 clean; 1 on any failure (each check reports a CI-GEN-* code on
stderr, CI-GEN-004 when the gate could not run a check: the generator, git or a
working-tree step failed); 2 only for a command-line usage error (argparse).

Stdlib only at import (subprocess/git/node are external processes, not
imports). Step 6's renderer imports PyYAML when it runs; the ``gen`` step installs
the version pinned in scripts/requirements-ci.txt.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib.util
import itertools
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

GENERATED_ROOT = Path("packages/protocol")
# Directory whose *contents* determinism/freshness we assert; kept narrow so
# unrelated protocol package churn (README edits, etc.) doesn't get pulled
# into the hash unnecessarily — though a diff there would also legitimately
# fail freshness, since it's still under packages/protocol.
# Generated outputs living OUTSIDE packages/protocol but produced by (or pinned
# alongside) `pnpm generate` (E17-T02): the Python twin of the CVWB layout,
# emitted by packages/protocol/scripts/generate-cvwb-layout.mjs, plus the
# committed CVWB vectors / SR-155 corpus (rendered by
# services/api/scripts/generate_cvwb_vectors.py and byte-checked by
# tests/unit/ws/test_cvwb_binary.py; included here so any stray churn fails).
CVWB_LAYOUT_TWIN = Path("services/api/candleviewer/ws/_generated/cvwb_layout.py")
EXTRA_GENERATED: tuple[Path, ...] = (
    CVWB_LAYOUT_TWIN,
    Path("packages/fixtures/golden/cvwb"),
    Path("tests/fuzz/ws-frames"),
)
GENERATED_PATHS: tuple[Path, ...] = (GENERATED_ROOT, *EXTRA_GENERATED)
# #3299: the gated outputs `pnpm generate` writes in full (step 1, CI-GEN-005). The
# orphan check cannot judge outputs that run does not produce, so three gated paths
# stay out: packages/protocol/generated/ (ws_constants.py, written only by `make gen`),
# and packages/fixtures/golden/cvwb and tests/fuzz/ws-frames (written by
# services/api/scripts/generate_cvwb_vectors.py). A committed file no generator writes
# can still pass there; #3392 tracks that gap.
GENERATE_OUTPUTS: tuple[Path, ...] = (
    GENERATED_ROOT / "src" / "generated",
    CVWB_LAYOUT_TWIN,
)
# #2555: services/api/scripts/generate_protocol_models.py writes the packaged
# contract subset the API reads at runtime. Its `--check` runs in the py lane only,
# so this always-on job renders the subset again as well, or a YAML-only PR could
# leave the runtime contract stale. The renderer is loaded by path from this
# script's checkout, as the generator loads it: it imports only the stdlib, and
# rendering needs PyYAML, not the backend venv.
CONTRACT_SOURCE = Path("docs/plan/22-api-openapi.yaml")
CONTRACT_ARTIFACT = Path(
    "services/api/candleviewer/api/_generated/contract_subset.json"
)
CONTRACT_RENDERER = (
    Path(__file__).resolve().parents[2]
    / "services/api/candleviewer/api/contract_conformance.py"
)
CONTRACT_REGENERATE = (
    "cd services/api && uv run python scripts/generate_protocol_models.py"
)
PYYAML_INSTALL = "python -m pip install -c scripts/requirements-ci.txt PyYAML"
# Lines of the artifact diff a CI-GEN-001 report shows.
CONTRACT_DIFF_LINES = 40
# shutil.which resolves pnpm.cmd on Windows (a bare "pnpm" is not executable there).
GENERATE_CMD = [shutil.which("pnpm") or "pnpm", "generate"]
# #2783: the gate judges what the generators produce from this checkout, never a
# turbo cache entry (the local cache is shared by every worktree on a machine).
# TURBO_FORCE=true skips cache reads only: turbo still stores the run under the task
# hash, which is sound because the generate inputs (packages/protocol/turbo.json)
# list every repo-level file the generators read. The overrides are merged last, so
# an exported TURBO_FORCE=false cannot switch the bypass off.
GENERATE_ENV_OVERRIDES: dict[str, str] = {"TURBO_FORCE": "true"}
# What surrogateescape (see _run) makes of each byte of output that is not UTF-8.
_NOT_UTF8 = re.compile("[\udc80-\udcff]")


class GenGateError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _run(
    cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    # surrogateescape: output that is not UTF-8 (a path name, a tool's message) decodes
    # to U+DC80..U+DCFF instead of crashing the gate; _tracked_files rejects such names.
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        capture_output=True,
        encoding="utf-8",
        errors="surrogateescape",
        check=False,
    )


def _tracked_files(roots: tuple[Path, ...]) -> list[str]:
    """Paths git tracks under ``roots`` (the index, not the working tree)."""
    listed = _run(["git", "ls-files", "-z", "--", *map(str, roots)])
    if listed.returncode != 0:
        raise GenGateError(
            "CI-GEN-004", f"git ls-files failed: {listed.stderr.strip()}"
        )
    tracked = [p for p in listed.stdout.split("\0") if p]
    not_utf8 = [p for p in tracked if _NOT_UTF8.search(p)]
    if not_utf8:
        shown = [
            p.encode("utf-8", "surrogateescape").decode("utf-8", "backslashreplace")
            for p in not_utf8
        ]
        raise GenGateError(
            "CI-GEN-004",
            "git tracks path(s) that are not valid UTF-8, so the gate cannot check "
            "them, and no generator writes such a name:\n"
            + _bullets(shown)
            + "Delete or rename each one.",
        )
    return tracked


def _missing(paths: list[str]) -> list[str]:
    return [rel for rel in paths if not os.path.lexists(rel)]


def _bullets(paths: list[str]) -> str:
    return "".join(f"  - {rel}\n" for rel in paths)


def _hash_generated_tree(roots: tuple[Path, ...]) -> str:
    """Deterministic content hash of every tracked file under ``root``.

    Uses ``git ls-files`` (not ``os.walk``) so `.gitignore`d build scratch
    (e.g. ``node_modules``, ``dist``) never perturbs the hash — only files
    git would actually track/diff are included, matching what the freshness
    check below inspects.
    """
    digest = hashlib.sha256()
    for rel in sorted(_tracked_files(roots)):
        path = Path(rel)
        if not path.is_file():
            continue
        data = path.read_bytes().replace(b"\r\n", b"\n")
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(data).digest())
    return digest.hexdigest()


def set_aside_outputs(removed: list[str]) -> None:
    """Step 1: removes the tracked files under GENERATE_OUTPUTS from the working
    tree, never the index, adding each to ``removed`` once it is gone, so a failure
    partway still reports every file it removed."""
    tracked = _tracked_files(GENERATE_OUTPUTS)
    if not tracked:
        raise GenGateError(
            "CI-GEN-004",
            "git tracks no file under "
            + ", ".join(map(str, GENERATE_OUTPUTS))
            + ", so the orphan check (CI-GEN-005) would check nothing. Run the gate "
            "from the repository root; if the outputs moved, update GENERATE_OUTPUTS.",
        )
    for rel in tracked:
        try:
            Path(rel).unlink(missing_ok=True)
        except OSError as exc:
            raise GenGateError(
                "CI-GEN-004", f"cannot remove {rel} before generating: {exc}"
            ) from exc
        removed.append(rel)


def run_generator() -> None:
    result = _run(GENERATE_CMD, env={**os.environ, **GENERATE_ENV_OVERRIDES})
    if result.returncode != 0:
        raise GenGateError(
            "CI-GEN-004",
            "generator toolchain failed to run "
            f"({' '.join(GENERATE_CMD)}):\n{result.stdout}\n{result.stderr}",
        )


def check_determinism() -> None:
    run_generator()
    first_hash = _hash_generated_tree(GENERATED_PATHS)
    run_generator()
    second_hash = _hash_generated_tree(GENERATED_PATHS)
    if first_hash != second_hash:
        raise GenGateError(
            "CI-GEN-003",
            "codegen is not deterministic: two consecutive `make gen` runs "
            f"produced different output under {GENERATED_ROOT} "
            f"(run 1 hash {first_hash}, run 2 hash {second_hash}). "
            "Reproduce locally with `make gen && make gen` and diff the tree.",
        )


def check_orphans(removed: list[str]) -> None:
    """CI-GEN-005: generation wrote back every tracked output step 1 removed."""
    orphans = _missing(removed)
    if orphans:
        raise GenGateError(
            "CI-GEN-005",
            "committed file(s) under the generated outputs that no generator writes: "
            "the gate removed them from the working tree and `pnpm generate` did not "
            "write them back. A hand-written file must not pose as generated (C-4.16), "
            "GENERATED header or not.\n"
            + _bullets(orphans)
            + "Delete them all with:\n"
            + f"  git rm -- {shlex.join(orphans)}\n"
            + "or add the generator that writes each one. The gate leaves them removed "
            "from the working tree; the index keeps them (`git restore -- <path>` "
            "brings one back).",
        )


def _note_missing(removed: list[str]) -> None:
    """After a failure, the tracked outputs step 1 removed that nothing wrote back,
    and one command that restores them all from the index."""
    missing = _missing(removed)
    if missing:
        print(
            f"note: {len(missing)} tracked generated file(s) missing from the working "
            "tree: the gate removed them and nothing wrote them back. The index keeps "
            "them:\n"
            + _bullets(missing)
            + f"Restore them all with:\n  git restore -- {shlex.join(missing)}\n",
            file=sys.stderr,
            end="",
        )


def check_freshness() -> None:
    """CI-GEN-001: the working tree must match `make gen`'s tracked output."""
    diff = _run(["git", "diff", "--exit-code", "--", *map(str, GENERATED_PATHS)])
    if diff.returncode != 0:
        raise GenGateError(
            "CI-GEN-001",
            "generated output is stale — `make gen` produced a diff "
            "against docs/plan/22-api-openapi.yaml / docs/plan/23-ws-protocol.md.\n"
            "Reproduce locally with `make gen`, review, and commit the result.\n\n"
            f"{diff.stdout}",
        )


def check_untracked() -> None:
    """CI-GEN-002: catch new generated files `git diff` cannot see."""
    status = _run(["git", "status", "--porcelain", "--", *map(str, GENERATED_PATHS)])
    if status.returncode != 0:
        raise GenGateError("CI-GEN-004", f"git status failed: {status.stderr.strip()}")
    untracked = [line for line in status.stdout.splitlines() if line.startswith("??")]
    if untracked:
        raise GenGateError(
            "CI-GEN-002",
            "`make gen` produced untracked output under packages/protocol "
            "(new generated file not committed, possibly git-ignored by "
            "mistake). Reproduce locally with `make gen && git status "
            "--porcelain -- packages/protocol`.\n\n" + "\n".join(untracked),
        )


def render_contract_subset(source: bytes) -> str:
    """The artifact the generator writes for the YAML bytes ``source``."""
    spec = importlib.util.spec_from_file_location(
        "_cv_contract_renderer", CONTRACT_RENDERER
    )
    if spec is None or spec.loader is None:
        raise GenGateError("CI-GEN-004", f"cannot load {CONTRACT_RENDERER}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        rendered = module.render_contract_subset(source)
    except ModuleNotFoundError as exc:
        raise GenGateError(
            "CI-GEN-004",
            f"the contract subset renderer cannot import {exc.name!r} in "
            f"{sys.executable}; it needs PyYAML: `{PYYAML_INSTALL}`.",
        ) from exc
    except Exception as exc:  # a YAML syntax error, a dangling $ref: no artifact
        raise GenGateError(
            "CI-GEN-004",
            f"rendering {CONTRACT_ARTIFACT} from {CONTRACT_SOURCE} failed: {exc!r}",
        ) from exc
    if not isinstance(rendered, str):
        raise GenGateError("CI-GEN-004", f"{CONTRACT_RENDERER} rendered no text")
    return rendered


def check_contract_subset() -> None:
    """CI-GEN-001: the packaged contract subset is what the generator renders from the
    committed YAML, byte for byte apart from CRLF line ends."""
    try:
        source = CONTRACT_SOURCE.read_bytes()
    except OSError as exc:
        raise GenGateError(
            "CI-GEN-004", f"cannot read {CONTRACT_SOURCE}: {exc}"
        ) from exc
    rendered = render_contract_subset(source)
    try:
        committed = CONTRACT_ARTIFACT.read_bytes().replace(b"\r\n", b"\n")
    except OSError as exc:
        raise GenGateError(
            "CI-GEN-001",
            f"{CONTRACT_ARTIFACT} is missing ({exc}). "
            f"Regenerate it with `{CONTRACT_REGENERATE}` and commit the result.",
        ) from exc
    if committed == rendered.encode("utf-8"):
        return
    diff = difflib.unified_diff(
        committed.decode("utf-8", errors="replace").splitlines(keepends=True),
        rendered.splitlines(keepends=True),
        f"a/{CONTRACT_ARTIFACT} (committed)",
        f"b/{CONTRACT_ARTIFACT} (rendered from {CONTRACT_SOURCE})",
    )
    shown = list(itertools.islice(diff, CONTRACT_DIFF_LINES + 1))
    if len(shown) > CONTRACT_DIFF_LINES:
        shown[CONTRACT_DIFF_LINES:] = ["... (diff truncated)\n"]
    raise GenGateError(
        "CI-GEN-001",
        f"{CONTRACT_ARTIFACT} is stale or hand-edited: it is not what the generator "
        f"renders from the committed {CONTRACT_SOURCE}. Regenerate it with "
        f"`{CONTRACT_REGENERATE}` and commit the result.\n\n" + "".join(shown),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)

    removed: list[str] = []  # step 1 adds each file as it removes it
    try:
        # Order matters (ticket "Technical notes"): determinism first, so a
        # flaky generator never presents as a random freshness failure. The
        # orphan check comes before `git diff`, which would report a removed
        # orphan as a deleted file (CI-GEN-001).
        set_aside_outputs(removed)
        check_determinism()
        check_orphans(removed)
        check_freshness()
        check_untracked()
        check_contract_subset()
    except GenGateError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        if exc.code != "CI-GEN-005":  # its own report lists them
            _note_missing(removed)
        return 1

    print("check_gen_freshness: OK — packages/protocol is fresh and deterministic")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
