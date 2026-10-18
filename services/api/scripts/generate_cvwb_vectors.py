"""Regenerate (or ``--check``) the committed CVWB vectors + SR-155 fuzz corpus (E17-T02).

Usage: uv run python scripts/generate_cvwb_vectors.py [--check]; `make gen` runs it too.
The TS decoder consumes both files in packages/protocol/test/cvwb-vectors.test.ts. CI runs no
--check: tests/unit/ws/test_cvwb_binary.py byte-checks every file in TARGETS (#3452).
"""

from __future__ import annotations

import difflib
import sys
from collections.abc import Callable
from pathlib import Path

from candleviewer.ws.cvwb_vectors import render_corpus, render_structured, render_vectors

REPO = Path(__file__).resolve().parents[3]
TARGETS: dict[Path, Callable[[], str]] = {
    REPO / "packages" / "fixtures" / "golden" / "cvwb" / "vectors.json": render_vectors,
    REPO / "packages" / "fixtures" / "golden" / "cvwb" / "structured.json": render_structured,
    REPO / "tests" / "fuzz" / "ws-frames" / "corpus.json": render_corpus,
}


def main(argv: list[str]) -> int:
    rc = 0
    for path, render in TARGETS.items():
        name = path.name
        generated = render()
        if "--check" in argv:
            committed = path.read_text(encoding="utf-8") if path.exists() else ""
            if committed != generated:
                rc = 1
                sys.stderr.write(
                    f"{name} is stale; run scripts/generate_cvwb_vectors.py\n"
                    + "".join(
                        difflib.unified_diff(
                            committed.splitlines(True),
                            generated.splitlines(True),
                            "committed",
                            "generated",
                        )
                    )
                )
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(generated, encoding="utf-8", newline="\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
