#!/usr/bin/env python3
"""E03-T04: apply ratchet proposals (package -> new baseline) produced by
`coverage_gate.py --ratchet --ratchet-out <file>` to
`tools/ci/coverage-baselines.json`, in place.

Only ever raises a `baseline` value (never lowers one — a proposal whose
value is not strictly greater than the current baseline is ignored, which
should never happen given `compute_ratchet_proposals`'s own >=1pp-increase
requirement, but this guard keeps the invariant true even if a stale/hand-
edited proposals file is fed in). Writes GitHub Actions `changed` and
`summary` outputs (via `$GITHUB_OUTPUT` when set, else stdout) so the
calling workflow step can decide whether to open a PR.

The proposals document derives from downloaded artifacts, so `load_proposals`
reads it as untrusted input (#3508); a refused one prints CI-COV-004, changes
nothing and exits 1.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

MAX_PROPOSALS_BYTES = 64 * 1024
MAX_PROPOSALS = 64


class ProposalsRefusedError(Exception):
    """The proposals document failed an untrusted-input check (CI-COV-004)."""


def load_proposals(path: Path) -> dict[str, float]:
    """Read `coverage_gate.py --ratchet-out` output: a regular file (not a link)
    of at most MAX_PROPOSALS_BYTES holding one JSON object that maps at most
    MAX_PROPOSALS package names to percentages in [0, 100]."""
    if path.is_symlink() or not path.is_file():
        raise ProposalsRefusedError(f"{path} is not a regular file")
    with path.open("rb") as fh:
        data = fh.read(MAX_PROPOSALS_BYTES + 1)
    if len(data) > MAX_PROPOSALS_BYTES:
        raise ProposalsRefusedError(f"{path} is over {MAX_PROPOSALS_BYTES} bytes")
    try:
        document = json.loads(data.decode("utf-8"))
    except (ValueError, RecursionError) as exc:  # JSON and UTF-8 errors are ValueErrors
        raise ProposalsRefusedError(f"{path} is not a JSON document") from exc
    if not isinstance(document, dict) or len(document) > MAX_PROPOSALS:
        raise ProposalsRefusedError(
            f"{path} is not one object of at most {MAX_PROPOSALS} entries"
        )
    if not all(type(v) in (int, float) and 0 <= v <= 100 for v in document.values()):
        raise ProposalsRefusedError(f"{path} does not map packages to percentages")
    return {package: float(value) for package, value in document.items()}


def apply_proposals(proposals: dict[str, float], baselines_path: Path) -> list[str]:
    """Mutate the baselines file in place. Returns a list of
    human-readable "package: old% -> new%" change lines (empty if
    nothing changed)."""
    config = json.loads(baselines_path.read_text(encoding="utf-8"))
    changes: list[str] = []

    for package, new_baseline in proposals.items():
        pkg_cfg = config["packages"].get(package)
        if pkg_cfg is None:
            continue
        old_baseline = float(pkg_cfg["baseline"])
        if new_baseline <= old_baseline:
            continue
        pkg_cfg["baseline"] = new_baseline
        changes.append(f"{package}: {old_baseline:.1f}% -> {new_baseline:.1f}%")

    if changes:
        baselines_path.write_text(
            json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    return changes


def _write_github_output(name: str, value: str) -> None:
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if not gh_output:
        print(f"{name}={value}")
        return
    with open(gh_output, "a", encoding="utf-8") as fh:
        if "\n" in value:
            fh.write(f"{name}<<EOF\n{value}\nEOF\n")
        else:
            fh.write(f"{name}={value}\n")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print(
            "usage: apply_ratchet_proposals.py <proposals.json> <coverage-baselines.json>",
            file=sys.stderr,
        )
        return 2

    proposals_path, baselines_path = Path(argv[0]), Path(argv[1])
    if not proposals_path.is_symlink() and not proposals_path.exists():
        # No proposals file (e.g. the gate step failed before ever
        # producing one) -> nothing to do, not an error.
        _write_github_output("changed", "false")
        _write_github_output("summary", "no ratchet proposals file found")
        return 0

    try:
        proposals = load_proposals(proposals_path)
    except ProposalsRefusedError as exc:
        print(f"CI-COV-004: ratchet proposals refused: {exc}", file=sys.stderr)
        return 1
    changes = apply_proposals(proposals, baselines_path)

    _write_github_output("changed", "true" if changes else "false")
    summary = (
        "\n".join(f"- {c}" for c in changes) if changes else "no packages ratcheted"
    )
    _write_github_output("summary", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
