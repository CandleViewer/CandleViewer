"""`python -m spike.oms_demo_path <mode> ...` (#843 A4); `--help` lists the options."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable, Sequence

from spike.oms_demo_path.config import parse
from spike.oms_demo_path.run import run
from spike.oms_demo_path.safety import Refused


def main(argv: Sequence[str] | None = None, *, read_line: Callable[[str], str] = input) -> int:
    """The run's exit code: 0 completed, 1 an error, 2 refused (nothing sent)."""
    cfg = parse(sys.argv[1:] if argv is None else argv)
    try:
        return asyncio.run(run(cfg, read_line=read_line))
    except Refused as exc:
        sys.stderr.write(f"refused: {exc}\n")
        return 2
    except Exception as exc:  # its class only: a setup error's text may echo a setting's value
        sys.stderr.write(f"failed: {type(exc).__name__}\n")
        return 1


if __name__ == "__main__":  # pragma: no cover - the process entry
    sys.exit(main())
