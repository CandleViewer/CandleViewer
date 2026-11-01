#!/usr/bin/env python3
"""#4014 (C-5.4): an applied QuestDB DDL file is never edited, deleted or renamed.

`backend/db/questdb/lockfile.json` pins the SHA-256 of the bytes of every applied
`backend/db/questdb/*.sql` file. The runner records a file by its name and applies an unrecorded
one, so an edited file is not applied again and a renamed one is applied a second time. This check
compares the checked-out tree with the lock and with the tree at the merge base.

Findings, on stderr as `<code> [<file>]: <message>`:
  CI-QDB-LOCK-001  a locked file's bytes differ from its entry
  CI-QDB-LOCK-002  a top-level `*.sql` file has no entry
  CI-QDB-LOCK-003  an entry's file is not on disk
  CI-QDB-LOCK-004  a `*.sql` file at the merge base differs at HEAD, or is gone
  CI-QDB-LOCK-005  a `*.sql` entry is a symlink or not a regular file

Exit codes: 0 clean, 1 findings, 2 internal error (`CI-QDB-LOCK-000`: the lock is missing or
malformed, the merge base cannot be resolved, git cannot be read; a usage error too). Bytes are
compared, never statements: a comment or a line ending is a change. No option rewrites the lock; a
new file's entry is made with `sha256sum` and committed with the file. Stdlib only, no network.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DDL_DIR = Path("backend/db/questdb")
DEFAULT_LOCKFILE = DEFAULT_DDL_DIR / "lockfile.json"
DEFAULT_BASE_REF = "origin/main"
GIT_TIMEOUT_SECONDS = 60

#: A bare file name ending `.sql`: the shape of every lock key.
LOCK_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.sql")
SHA256 = re.compile(r"[0-9a-f]{64}")
#: A branch, tag or remote-tracking name: a plain word first, no range or revision syntax.
BASE_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/+-]*")
OBJECT_ID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
#: The modes of a regular file's blob; a symlink (120000) or a submodule (160000) is neither.
REGULAR_BLOB_MODES = frozenset({"100644", "100755"})


class LockError(Exception):
    """The check cannot run: the lock is unreadable or git cannot give the merge base."""


@dataclass(frozen=True)
class Violation:
    code: str
    file: str
    message: str


def render(violation: Violation) -> str:
    """`<code> [<file>]: <message>`, the file name escaped when it is not a plain `*.sql` name."""
    name = violation.file
    shown = name if LOCK_KEY.fullmatch(name) else ascii(name)
    return f"{violation.code} [{shown}]: {violation.message}"


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    if len({key for key, _ in pairs}) != len(pairs):
        raise ValueError("a key appears twice in one object")
    return dict(pairs)


def load_lock(path: Path) -> dict[str, str]:
    """The lock's `files` as name -> sha256; a missing or malformed lock is a `LockError`."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicate_keys)
    except FileNotFoundError as exc:
        raise LockError(f"the lock is missing: {path}") from exc
    except ValueError as exc:
        raise LockError(f"the lock cannot be read as JSON: {path}: {exc}") from exc
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, dict):
        raise LockError(f"the lock has no object 'files': {path}")
    lock: dict[str, str] = {}
    for name, entry in files.items():
        sha = entry.get("sha256") if isinstance(entry, dict) else None
        if not LOCK_KEY.fullmatch(name) or not (isinstance(sha, str) and SHA256.fullmatch(sha)):
            raise LockError(
                f"malformed lock entry {name!r}: a bare *.sql name and a lowercase 64-digit sha256"
            )
        lock[name] = sha
    return lock


def ddl_files(ddl_dir: Path) -> dict[str, Path]:
    """The top-level `*.sql` entries of `ddl_dir`, by name in name order: the runner's glob, with
    symlinks and directories included so that they can be refused."""
    with os.scandir(ddl_dir) as entries:
        names = sorted(entry.name for entry in entries if entry.name.endswith(".sql"))
    return {name: ddl_dir / name for name in names}


def _git(repo_root: Path, *args: str) -> bytes:
    """Run `git -C <repo_root> <args>`: a fixed argv, no shell. Its stdout, or a `LockError`."""
    argv = ["git", "-C", str(repo_root), *args]
    try:
        done = subprocess.run(argv, capture_output=True, check=True, timeout=GIT_TIMEOUT_SECONDS)  # noqa: S603
    except subprocess.CalledProcessError as exc:
        raise LockError(f"git {args[0]} exited with status {exc.returncode}") from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LockError(f"git {args[0]} did not run: {type(exc).__name__}") from exc
    return done.stdout


def _repo_relative(ddl_dir: Path, repo_root: Path) -> str:
    root, ddl = Path(os.path.abspath(repo_root)), Path(os.path.abspath(ddl_dir))
    if root not in ddl.parents:
        raise LockError("the DDL directory is not inside the repository root")
    return ddl.relative_to(root).as_posix()


def load_base(base_ref: str, ddl_dir: Path, repo_root: Path) -> dict[str, str]:
    """name -> sha256 of the bytes of each top-level regular `*.sql` blob of `ddl_dir` at the merge
    base of HEAD and `base_ref`; `{}` when the directory is absent there.

    A merge base that cannot be resolved (a bad ref, a shallow clone, no shared history, no
    repository) is a `LockError`: an empty base would turn the comparison off.
    """
    if not BASE_REF.fullmatch(base_ref) or ".." in base_ref:
        raise LockError("the base ref must be a plain branch or tag name")
    where = _repo_relative(ddl_dir, repo_root)
    merge_base = _git(repo_root, "merge-base", "HEAD", base_ref).decode("ascii", "replace").strip()
    if not OBJECT_ID.fullmatch(merge_base):
        raise LockError("git merge-base printed no single commit")
    listing = _git(repo_root, "ls-tree", "-z", merge_base, "--", f"{where}/")
    base: dict[str, str] = {}
    for record in filter(None, listing.split(b"\0")):
        meta, _, raw_path = record.partition(b"\t")
        try:
            mode, kind, oid = meta.decode("ascii").split(" ")
            path = raw_path.decode("utf-8")
        except (UnicodeDecodeError, ValueError) as exc:
            raise LockError("git ls-tree printed an entry that cannot be read") from exc
        name = posixpath.basename(path)
        if posixpath.dirname(path) != where or not name.endswith(".sql"):
            continue
        if kind == "blob" and mode in REGULAR_BLOB_MODES and OBJECT_ID.fullmatch(oid):
            base[name] = hashlib.sha256(_git(repo_root, "cat-file", "blob", oid)).hexdigest()
    return base


def verify(lock: dict[str, str], ddl_dir: Path, base: dict[str, str] | None) -> list[Violation]:
    """Every finding for the files in `ddl_dir` against `lock` and, unless `base` is None, against
    the merge base's `base`. The directory is read, git is not."""
    found: list[Violation] = []
    on_disk = ddl_files(ddl_dir)
    actual: dict[str, str] = {}  # regular files only: nothing is read through a link
    for name, path in on_disk.items():
        if stat.S_ISREG(path.lstat().st_mode):
            actual[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            found.append(
                Violation(
                    "CI-QDB-LOCK-005",
                    name,
                    "not a regular file (a symlink, a directory or a device); the runner reads "
                    "a DDL file's own bytes.",
                )
            )
    for name in on_disk:
        if name not in lock:
            found.append(
                Violation(
                    "CI-QDB-LOCK-002",
                    name,
                    "no entry in the lock; the PR that adds a DDL file adds its entry "
                    "(the sha256sum of the file).",
                )
            )
    for name, locked in lock.items():
        if name not in on_disk:
            found.append(
                Violation(
                    "CI-QDB-LOCK-003",
                    name,
                    "listed in the lock but not on disk; an applied QuestDB DDL file is never "
                    "deleted or renamed (C-5.4).",
                )
            )
        elif name in actual and actual[name] != locked:
            found.append(
                Violation(
                    "CI-QDB-LOCK-001",
                    name,
                    f"bytes differ from the lock entry (locked {locked[:12]}, found "
                    f"{actual[name][:12]}); an applied QuestDB DDL file is never edited (C-5.4), "
                    "fix forward with a new file.",
                )
            )
    if base is not None:
        for name, applied in base.items():
            if name not in on_disk or (name in actual and actual[name] != applied):
                what = "is gone since" if name not in on_disk else "differs from"
                found.append(
                    Violation(
                        "CI-QDB-LOCK-004",
                        name,
                        f"{what} the merge base; an applied QuestDB DDL file is never edited, "
                        "deleted or renamed (C-5.4), whatever its lock entry says.",
                    )
                )
    return sorted(found, key=lambda violation: (violation.file, violation.code))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check the applied QuestDB DDL files against their lock and the merge base."
    )
    parser.add_argument(
        "--lockfile",
        type=Path,
        default=DEFAULT_LOCKFILE,
        help="the lock; a relative path is read under --repo-root",
    )
    parser.add_argument(
        "--ddl-dir",
        type=Path,
        default=DEFAULT_DDL_DIR,
        help="the directory of the *.sql files; a relative path is read under --repo-root",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="the top-level directory of the git work tree",
    )
    parser.add_argument(
        "--base-ref",
        default=DEFAULT_BASE_REF,
        help="the ref whose merge base with HEAD is the baseline (default: %(default)s)",
    )
    parser.add_argument(
        "--no-base-check",
        action="store_true",
        help="skip the merge-base comparison (CI-QDB-LOCK-004); local use only, CI never passes it",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ddl_dir = args.repo_root / args.ddl_dir
    lockfile = args.repo_root / args.lockfile
    try:
        lock = load_lock(lockfile)
        base = None if args.no_base_check else load_base(args.base_ref, ddl_dir, args.repo_root)
        findings = verify(lock, ddl_dir, base)
    except (LockError, OSError) as exc:
        print(f"CI-QDB-LOCK-000 internal error: {exc}", file=sys.stderr)
        return 2
    for finding in findings:
        print(render(finding), file=sys.stderr)
    if findings:
        return 1
    compared = (
        "the merge-base comparison was skipped"
        if base is None
        else f"none differs from the merge base with {args.base_ref}"
    )
    print(f"OK: {len(lock)} QuestDB DDL file(s) match {lockfile}; {compared}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
