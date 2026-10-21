#!/usr/bin/env python3
"""Bugfix #1556 (parent E07-T02, issue #168): migration lockfile integrity gate.

Enforces `docs/plan/21-database-schema.md` §9.3 rule 9, "migrations are
forward-only in production": once a revision file has been recorded in
`services/api/candleviewer/migrations/lockfile.json`, editing it is a CI
failure. Also catches a new `versions/*.py` file landing without a matching
lockfile entry, and a `down_revision` chain that disagrees between the
lockfile and the file's own `revision`/`down_revision` assignments.

Exit codes: 0 clean, 1 a violation was found, 2 internal error (lockfile
missing/malformed). Stdlib only — no network, no third-party imports, so
this runs identically in CI and locally with a bare `python3`.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_LOCKFILE = Path("services/api/candleviewer/migrations/lockfile.json")
DEFAULT_VERSIONS_DIR = Path("services/api/candleviewer/migrations/versions")
DEFAULT_BASE_REF = "origin/main"

RULE_9_MESSAGE = "migrations are forward-only in production"


class LockfileError(Exception):
    pass


@dataclass(frozen=True)
class Violation:
    code: str
    revision: str
    message: str


def _load_lockfile(path: Path) -> dict[str, dict[str, object]]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise LockfileError(f"lockfile not found: {path}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LockfileError(f"lockfile is not valid JSON: {path}: {exc}") from exc
    revisions = data.get("revisions")
    if not isinstance(revisions, dict):
        raise LockfileError(f"lockfile missing object 'revisions': {path}")
    return revisions


def _sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_base_lockfile(base_ref: str, lockfile_path: Path) -> dict[str, dict[str, object]]:
    """Return the `revisions` map from `lockfile_path` as it existed at the
    merge-base with `base_ref`.

    This is rule 9's real enforcement point: a PR that edits an already-locked
    revision *and* rewrites its own sha256 in the same PR must still fail,
    because comparing the lockfile only against the PR's own tree (as before)
    makes such a self-consistent edit invisible.

    Resolving `base_ref` is required to succeed — if the merge-base can't be
    found (bad ref, shallow clone, not a git repo at all) this raises
    `LockfileError` rather than silently skipping CI-MIG-LOCK-006: a fail-open
    here would let a PR edit an already-applied revision and rewrite its own
    sha256 undetected whenever the base ref happens to be unresolvable.

    If the lockfile simply didn't exist yet at the merge-base (a brand new
    lockfile), that's a legitimate empty baseline, not a resolution failure,
    so it returns `{}` rather than raising.
    """
    # Fixed argv, literal `git` executable, no shell — not untrusted input.
    try:
        merge_base = subprocess.run(  # noqa: S603
            ["git", "merge-base", "HEAD", base_ref],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise LockfileError(
            f"could not resolve merge-base with {base_ref!r} to enforce "
            f"CI-MIG-LOCK-006 ({RULE_9_MESSAGE}); pass --no-base-check only "
            "for local/offline use: "
            f"{exc}"
        ) from exc

    show = subprocess.run(
        ["git", "show", f"{merge_base}:{lockfile_path.as_posix()}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if show.returncode != 0:
        # No lockfile at the merge-base at all (e.g. it was added in this PR)
        # is a legitimate empty baseline, not a resolution failure.
        return {}

    try:
        data = json.loads(show.stdout)
    except json.JSONDecodeError as exc:
        raise LockfileError(
            f"lockfile at {base_ref}:{lockfile_path} is not valid JSON: {exc}"
        ) from exc
    revisions = data.get("revisions")
    if not isinstance(revisions, dict):
        raise LockfileError(f"lockfile at {base_ref}:{lockfile_path} is missing object 'revisions'")
    return revisions


#: What an id that is not a string constant (or None) reads as: never a lockfile key, so the
#: comparison fails, as it must; Alembic reads the runtime value, which this tool cannot (#4032).
NON_CONSTANT = "<not a string constant>"


def _extract_revision_ids(path: Path) -> tuple[str | None, str | None]:
    """Return (revision, down_revision) string literals from an Alembic
    version file's module-level assignments, without importing it. The
    last assignment wins, as at import; one whose value is not a string
    constant or None reads as `NON_CONSTANT`."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    revision: str | None = None
    down_revision: str | None = None
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign) and not isinstance(node, ast.Assign):
            continue
        targets = [node.target] if isinstance(node, ast.AnnAssign) else node.targets
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            value = node.value
            literal: str | None
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                literal = value.value
            elif isinstance(value, ast.Constant) and value.value is None:
                literal = None
            else:
                literal = NON_CONSTANT
            if target.id == "revision":
                revision = literal
            elif target.id == "down_revision":
                down_revision = literal
    return revision, down_revision


def verify(
    lockfile_path: Path,
    versions_dir: Path,
    repo_root: Path,
    base_revisions: dict[str, dict[str, object]] | None = None,
) -> list[Violation]:
    violations: list[Violation] = []
    revisions = _load_lockfile(lockfile_path)

    on_disk = {f.stem: f for f in sorted(versions_dir.glob("*.py")) if f.name != "__init__.py"}

    # CI-MIG-LOCK-002: a versions/*.py file exists with no lockfile entry.
    for rev_id, file_path in on_disk.items():
        if rev_id not in revisions:
            violations.append(
                Violation(
                    code="CI-MIG-LOCK-002",
                    revision=rev_id,
                    message=(
                        f"{file_path} has no entry in {lockfile_path}; add one in this PR "
                        f"({RULE_9_MESSAGE})."
                    ),
                )
            )

    for rev_id, entry in revisions.items():
        rel_path = entry.get("path")
        expected_sha = entry.get("sha256")
        expected_down = entry.get("down_revision")
        if not isinstance(rel_path, str) or not isinstance(expected_sha, str):
            raise LockfileError(f"malformed lockfile entry for {rev_id!r} in {lockfile_path}")

        file_path = repo_root / rel_path
        if not file_path.is_file():
            # CI-MIG-LOCK-003: lockfile references a revision that no longer
            # exists on disk. Deleting an applied revision is itself a
            # forward-only violation, not a lockfile-maintenance shortcut.
            violations.append(
                Violation(
                    code="CI-MIG-LOCK-003",
                    revision=rev_id,
                    message=f"{rel_path} is recorded in {lockfile_path} but is missing from disk.",
                )
            )
            continue

        actual_sha = _sha256_of(file_path)
        if actual_sha != expected_sha:
            # CI-MIG-LOCK-001: the core rule-9 gate — an applied revision's
            # bytes changed since it was locked.
            violations.append(
                Violation(
                    code="CI-MIG-LOCK-001",
                    revision=rev_id,
                    message=(
                        f"{rel_path} has been edited since it was locked "
                        f"(expected sha256={expected_sha}, got {actual_sha}): {RULE_9_MESSAGE}."
                    ),
                )
            )

        actual_revision, actual_down = _extract_revision_ids(file_path)
        if actual_revision != rev_id:
            violations.append(
                Violation(
                    code="CI-MIG-LOCK-004",
                    revision=rev_id,
                    message=(
                        f"{rel_path} declares revision={actual_revision!r} but the lockfile "
                        f"key is {rev_id!r}."
                    ),
                )
            )
        if actual_down != expected_down:
            violations.append(
                Violation(
                    code="CI-MIG-LOCK-005",
                    revision=rev_id,
                    message=(
                        f"{rel_path} declares down_revision={actual_down!r} but the lockfile "
                        f"records down_revision={expected_down!r}."
                    ),
                )
            )

    # CI-MIG-LOCK-006: the real rule-9 gate. Compare each already-recorded
    # revision's sha256/down_revision against the merge-base lockfile, not
    # just the PR's own tree — otherwise editing an applied revision *and*
    # updating its own sha256 in the same PR is self-consistent and passes.
    if base_revisions is not None:
        for rev_id, base_entry in base_revisions.items():
            base_sha = base_entry.get("sha256")
            base_down = base_entry.get("down_revision")
            current_entry = revisions.get(rev_id)
            if current_entry is None:
                violations.append(
                    Violation(
                        code="CI-MIG-LOCK-006",
                        revision=rev_id,
                        message=(
                            f"{rev_id} was recorded in the base lockfile but is missing from "
                            f"this PR's lockfile: {RULE_9_MESSAGE}."
                        ),
                    )
                )
                continue
            if (
                current_entry.get("sha256") != base_sha
                or current_entry.get("down_revision") != base_down
            ):
                violations.append(
                    Violation(
                        code="CI-MIG-LOCK-006",
                        revision=rev_id,
                        message=(
                            f"{rev_id}'s lockfile entry changed since the base branch "
                            f"(base sha256={base_sha}, PR sha256={current_entry.get('sha256')}): "
                            f"{RULE_9_MESSAGE}. Editing an applied revision's file and its own "
                            "lockfile entry in the same PR is not permitted."
                        ),
                    )
                )

    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lockfile", type=Path, default=DEFAULT_LOCKFILE)
    parser.add_argument("--versions-dir", type=Path, default=DEFAULT_VERSIONS_DIR)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--base-ref", default=DEFAULT_BASE_REF)
    parser.add_argument(
        "--no-base-check",
        action="store_true",
        help="Skip the merge-base comparison (rule 9 enforcement); local/offline use only.",
    )
    args = parser.parse_args(argv)

    base_revisions = None
    try:
        if not args.no_base_check:
            base_revisions = _load_base_lockfile(args.base_ref, args.lockfile)

        violations = verify(args.lockfile, args.versions_dir, args.repo_root, base_revisions)
    except LockfileError as exc:
        print(f"CI-MIG-LOCK-000 internal error: {exc}", file=sys.stderr)
        return 2

    if violations:
        for v in violations:
            print(f"{v.code} [{v.revision}]: {v.message}", file=sys.stderr)
        return 1

    print(f"OK: {len(_load_lockfile(args.lockfile))} revision(s) verified against {args.lockfile}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
