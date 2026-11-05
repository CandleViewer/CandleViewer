"""E42-Q03 (#1216) part 4: the audit WAL's depth before, during and after a load profile [BQ-8].

    python3 -I tests/load/admin/wal_check.py check DIR

The audit writer buffers every record in a bounded on-disk WAL (`candleviewer/audit/wal.py`,
`AuditWal`, 64 MiB): a frame is appended before Postgres has it, the `<wal>.committed` cursor
marks how far Postgres has it, and a full file is compacted to its uncommitted tail. So the file
size alone is not the risk: a file at its cap compacts. The bytes no compaction can free, the
size less the committed offset, are; once they and the next frame pass the cap the writer raises
`AuditUnavailable` and every audited action is refused (C-2.9). There is no depth series on
main, so this reads the files: every WAL in the directory of `CV_AUDIT_WAL_PATH` (a file with a
`.committed` cursor beside it: the audit WAL, the machine-events WAL, the order lanes'), its
size and its depth. A profile fails when any depth passes `LIMIT` of `CAP_BYTES` (plan 4.5).

A compaction resets the cursor to 0 and then swaps the file: a cursor read across it would show
the old size as all uncommitted. A reading whose cursor moved between its two reads is taken
again; one that falls between the reset and the swap still over-reads, so the check can fail
safe, never pass a full WAL. Stdlib only; it reads, never writes, and never opens a frame.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

CAP_BYTES: Final = 64 * 1024 * 1024  # AuditWal's max_bytes (the harness tests pin it)
LIMIT: Final = 0.8
CURSOR: Final = ".committed"
TRIES: Final = 5

Reading = dict[str, dict[str, int]]


def wal_files(directory: Path) -> list[Path]:
    """The WAL files in `directory`: each has its `.committed` cursor beside it."""
    if not directory.is_dir():
        return []
    return sorted(
        p
        for p in directory.iterdir()
        if p.is_file() and not p.name.endswith(CURSOR) and p.with_name(p.name + CURSOR).is_file()
    )


def _cursor(path: Path) -> int:
    text = path.with_name(path.name + CURSOR).read_text(encoding="ascii").strip()
    return int(text) if text.isdigit() else 0


def read_one(path: Path) -> dict[str, int]:
    """One WAL's size, committed offset and depth (the bytes no compaction can free)."""
    for _ in range(TRIES):
        try:
            before = _cursor(path)
            size = path.stat().st_size
            after = _cursor(path)
        except (OSError, ValueError):
            continue  # mid-swap: read again
        if before == after:
            return {"size": size, "committed": after, "depth": max(0, size - after)}
    raise OSError(f"{path.name}: the cursor kept moving")


def sample(directory: Path) -> Reading:
    return {p.name: read_one(p) for p in wal_files(directory)}


def judge(readings: Sequence[Reading], cap: int = CAP_BYTES) -> dict[str, object]:
    """The deepest any WAL got over the readings, and whether it stayed within `LIMIT` of `cap`.
    No reading, or a reading with no WAL, is never a pass: the check was blind."""
    depths = [w["depth"] for r in readings for w in r.values()]
    sizes = [w["size"] for r in readings for w in r.values()]
    if not readings or any(not r for r in readings):
        return {"max_depth": None, "max_size": None, "limit": LIMIT * cap, "verdict": "BLIND"}
    worst = max(depths)
    return {
        "max_depth": worst,
        "max_size": max(sizes),
        "limit": LIMIT * cap,
        "verdict": "PASS" if worst <= LIMIT * cap else "FAIL",
    }


def watch(
    directory: Path,
    done: Callable[[float], bool],
    interval: float = 1.0,
    clock: Callable[[], float] = time.time,
) -> list[dict[str, object]]:
    """Readings before, every `interval` while `done(interval)` is false (it waits), and after.
    A reading that cannot be taken (`OSError`: a cursor that kept moving, an unreadable file) is
    an empty one, BLIND to `judge`, and the watch goes on (C-1216P4-05)."""

    def blind_or(at: float) -> dict[str, object]:
        try:
            return {"at": at, "wal": sample(directory)}
        except OSError:
            return {"at": at, "wal": {}}

    out = [blind_or(clock())]
    while not done(interval):
        out.append(blind_or(clock()))
    out.append(blind_or(clock()))
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The audit WAL's depth (E42-Q03).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    check = sub.add_parser("check")
    check.add_argument("directory", type=Path)
    args = parser.parse_args(argv)
    reading = sample(args.directory)
    verdict = judge([reading])
    print(json.dumps({"wal": reading, **verdict}, indent=2))
    return 0 if verdict["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
