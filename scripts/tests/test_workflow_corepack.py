"""#2952: the corepack bundled with the Node that `.nvmrc` pins (20.19.5) cannot unpack pnpm 12
("Cannot find module .../pnpm/12.5.1/bin/pnpm.cjs"). A job that sets Node up from `.nvmrc` must
therefore upgrade corepack before it prepares pnpm. fuzz-nightly's typescript job skipped the
upgrade and failed every night from 2026-10-09. Jobs on `node-version: "20"` resolve a newer 20.x
whose corepack handles pnpm 12, so they are out of this rule."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
UPGRADE = "npm install -g corepack@latest"
PREPARE = "corepack prepare pnpm"


def _nvmrc_jobs() -> Iterator[tuple[str, str, list[dict[str, Any]]]]:
    for path in sorted((ROOT / ".github/workflows").glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for name, job in (doc.get("jobs") or {}).items():
            steps = job.get("steps") or []
            if any(
                str(step.get("uses", "")).startswith("actions/setup-node@")
                and (step.get("with") or {}).get("node-version-file") == ".nvmrc"
                for step in steps
            ):
                yield path.name, name, steps


def test_nvmrc_jobs_upgrade_corepack_before_preparing_pnpm() -> None:
    prepared = []
    for workflow, job, steps in _nvmrc_jobs():
        for step in steps:
            run = str(step.get("run", ""))
            if PREPARE in run:
                prepared.append((workflow, job))
                assert UPGRADE in run and run.index(UPGRADE) < run.index(PREPARE), (workflow, job)
    # An empty scan proves nothing: _job-js.yml and fuzz-nightly.yml both prepare pnpm on .nvmrc.
    assert ("fuzz-nightly.yml", "typescript") in prepared
    assert any(workflow == "_job-js.yml" for workflow, _ in prepared)
