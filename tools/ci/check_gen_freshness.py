#!/usr/bin/env python3
"""E03-T05: generated-code freshness gate for ``packages/protocol``.

ADR-0013 binding rule 3: "packages/protocol is regenerated from
22-api-openapi.yaml and the WS schema; any diff fails the build. Generated
files are committed so consumers need no codegen step." ADR-0005 reinforces
it for the binary WS framing constants.

This script is the single implementation invoked by the ``gen`` step of the
``gates`` job in ``.github/workflows/pr.yml`` and locally via ``make gen-check``:

1. Runs the generator (``pnpm generate``, i.e. ``make gen``) twice in a row
   on the current checkout and hashes the generated tree after each run.
   Each run sets ``TURBO_FORCE=true``, so the generators really execute and a
   turbo cache entry is never replayed as fresh output (#2783).
   If the two hashes differ, generation is non-deterministic (CI-GEN-003)
   and we fail *before* even looking at git diff, so a flaky generator never
   masquerades as a "someone forgot to regenerate" freshness failure.
2. Runs ``git diff --exit-code -- packages/protocol`` (CI-GEN-001: drift
   against a committed schema change). This is also the hand-edit guard for
   committed generated files: regenerating overwrites the edit, so it shows
   up as a diff. No committed manifest takes part (#2743).
3. Runs ``git status --porcelain -- packages/protocol`` (CI-GEN-002:
   untracked generated output the first check cannot see).
4. Renders the packaged contract subset (#2555) again from the committed
   ``docs/plan/22-api-openapi.yaml`` with the generator's own renderer and
   compares it with the committed artifact (CI-GEN-001), the way step 2 does
   for packages/protocol: a YAML edit that skipped regeneration and a hand
   edit of the artifact both fail. The artifact records no digest of the YAML
   (#2743), so two PRs that change different operations do not conflict on it.

Exit codes: 0 clean, 1 a CI-GEN-* violation was found, 2 internal error
(generator command failed to run at all).

Stdlib only at import (subprocess/git/node are external processes, not
imports). Step 4's renderer imports PyYAML when it runs; the ``gen`` step installs
the version pinned in scripts/requirements-ci.txt.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib.util
import itertools
import os
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
EXTRA_GENERATED: tuple[Path, ...] = (
    Path("services/api/candleviewer/ws/_generated/cvwb_layout.py"),
    Path("packages/fixtures/golden/cvwb"),
    Path("tests/fuzz/ws-frames"),
)
GENERATED_PATHS: tuple[Path, ...] = (GENERATED_ROOT, *EXTRA_GENERATED)
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


class GenGateError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _run(
    cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _hash_generated_tree(roots: tuple[Path, ...]) -> str:
    """Deterministic content hash of every tracked file under ``root``.

    Uses ``git ls-files`` (not ``os.walk``) so `.gitignore`d build scratch
    (e.g. ``node_modules``, ``dist``) never perturbs the hash — only files
    git would actually track/diff are included, matching what the freshness
    check below inspects.
    """
    listed = _run(["git", "ls-files", "-z", "--", *map(str, roots)])
    if listed.returncode != 0:
        raise GenGateError(
            "CI-GEN-004", f"git ls-files failed: {listed.stderr.strip()}"
        )
    paths = [p for p in listed.stdout.split("\0") if p]
    digest = hashlib.sha256()
    for rel in sorted(paths):
        path = Path(rel)
        if not path.is_file():
            continue
        data = path.read_bytes().replace(b"\r\n", b"\n")
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(data).digest())
    return digest.hexdigest()


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

    try:
        # Order matters (ticket "Technical notes"): determinism first, so a
        # flaky generator never presents as a random freshness failure.
        check_determinism()
        check_freshness()
        check_untracked()
        check_contract_subset()
    except GenGateError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 1

    print("check_gen_freshness: OK — packages/protocol is fresh and deterministic")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
