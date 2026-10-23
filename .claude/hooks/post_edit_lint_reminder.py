#!/usr/bin/env python3
"""PostToolUse reminder: tell the agent which package lint/typecheck to run for the edited file."""
from __future__ import annotations

import json
import os
import sys

MAP = [
    ("services/api/", "cd services/api && ruff check . && ruff format --check . && mypy --strict . && lint-imports"),
    ("packages/chart-engine/", "pnpm --filter @candleviewer/chart-engine lint && pnpm --filter @candleviewer/chart-engine typecheck (bench if render code changed)"),
    ("packages/ui/", "pnpm --filter @candleviewer/ui lint && pnpm --filter @candleviewer/ui typecheck"),
    ("packages/protocol/", "pnpm generate (generated package: do not hand-edit)"),
    ("apps/web/", "pnpm --filter @candleviewer/web lint && pnpm --filter @candleviewer/web typecheck"),
    ("apps/desktop/", "pnpm --filter @candleviewer/desktop lint && pnpm --filter @candleviewer/desktop typecheck"),
    ("docs/plan/backlog/", "python docs/plan/backlog/_tools/validate.py"),
]


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    path = ((data.get("tool_input") or {}).get("file_path") or "").replace("\\", "/")
    root = (os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or "").replace("\\", "/").rstrip("/") + "/"
    rel = path[len(root):] if root != "/" and path.lower().startswith(root.lower()) else path
    for top in ("/services/", "/apps/", "/packages/", "/docs/"):
        if rel == path and top in path:
            rel = path[path.find(top) + 1:]
    for prefix, cmd in MAP:
        if rel.startswith(prefix):
            out = {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                   "additionalContext": f"Reminder: before committing, run the package lint for {prefix}: {cmd} (AGENTS.md §4)."}}
            print(json.dumps(out))
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
