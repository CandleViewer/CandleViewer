#!/usr/bin/env python3
"""PreToolUse guard for Edit/Write/MultiEdit.

Blocks (exit 2, reason on stderr):
  1. Edits to an existing Alembic revision under services/api/candleviewer/migrations/versions/
     that is already applied, i.e. tracked in git on origin/main (or main) - C-5.4.
  2. Edits to an applied QuestDB DDL file under backend/db/questdb/, a `*.sql` file that is
     tracked on origin/main (or main) - C-5.4. A new file and the lock beside the files pass.
  3. Content that imports xstate_statemachine outside services/api/candleviewer/statechart/
     (CV-LINT-IMPORT; tests/xstate_contract/ is allowed for parity tests).
The path is normalised as text before it is matched (separators, `.` and `..` segments; no
filesystem access, so a symlink is not followed). The hook is an early warning: a shell edit
(sed -i, a heredoc) never reaches it, and the CI lock check is the gate for 2.
"""
from __future__ import annotations

import json
import os
import posixpath
import re
import subprocess
import sys

MIGRATIONS = "services/api/candleviewer/migrations/versions/"
QUESTDB_DDL = "backend/db/questdb/"
STATECHART = "services/api/candleviewer/statechart/"
ALLOWED_TEST_DIRS = ("services/api/tests/xstate_contract/", "tests/xstate_contract/")
# A worktree of the project sits under its directory: the files in it are the project's own paths.
WORKTREE_RE = re.compile(r"^\.claude/worktrees/[^/]+/")
IMPORT_RE = re.compile(r"^\s*(from\s+xstate_statemachine\b|import\s+xstate_statemachine\b)", re.M)


def norm(path: str) -> str:
    """`path` with its separators and its `.` and `..` segments resolved, as text only."""
    return posixpath.normpath(path.replace("\\", "/"))


def rel(path: str, root: str) -> str:
    p = path.replace("\\", "/")
    r = root.replace("\\", "/").rstrip("/") + "/"
    if r != "/" and p.lower().startswith(r.lower()):
        return WORKTREE_RE.sub("", p[len(r):])
    for top in ("/services/", "/apps/", "/packages/", "/tests/", "/docs/", "/backend/"):
        i = p.find(top)
        if i >= 0:
            return p[i + 1:]
    return p


def applied_on_main(relpath: str, root: str) -> bool:
    for ref in ("origin/main", "main"):
        try:
            out = subprocess.run(
                ["git", "cat-file", "-e", f"{ref}:{relpath}"],
                cwd=root, capture_output=True, timeout=10,
            )
            if out.returncode == 0:
                return True
        except Exception:
            continue
    return False


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    ti = data.get("tool_input", {}) or {}
    path = ti.get("file_path") or ""
    if not path:
        return 0
    root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    r = rel(norm(path), root)

    if r.startswith(MIGRATIONS) and r.endswith(".py") and applied_on_main(r, root):
        print(
            f"BLOCKED (C-5.4): {r} is an applied migration on main and is immutable. "
            "Create a new revision with `alembic revision -m ...` instead.",
            file=sys.stderr,
        )
        return 2

    if r.startswith(QUESTDB_DDL) and r.endswith(".sql") and applied_on_main(r, root):
        print(
            f"BLOCKED (C-5.4): {r} is an applied QuestDB DDL file on main and is immutable. "
            f"Add a new NNNN_*.sql file and its entry in {QUESTDB_DDL}lockfile.json instead.",
            file=sys.stderr,
        )
        return 2

    if r.endswith(".py") and not r.startswith(STATECHART) and not r.startswith(ALLOWED_TEST_DIRS):
        chunks = [ti.get("content") or "", ti.get("new_string") or ""]
        chunks += [e.get("new_string") or "" for e in ti.get("edits") or []]
        if any(IMPORT_RE.search(c) for c in chunks):
            print(
                f"BLOCKED (CV-LINT-IMPORT / ADR-0016): {r} imports xstate_statemachine. Only "
                f"{STATECHART}factory.py and persistence.py may import the runtime; use "
                "candleviewer.statechart.build()/restore() instead.",
                file=sys.stderr,
            )
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
