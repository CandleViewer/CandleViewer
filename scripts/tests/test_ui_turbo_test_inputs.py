"""#3272: a tokens- or scripts-only change to packages/ui re-runs its tests on a warm turbo cache.

The root `test` and `test:cov` inputs are `src/**`, `test/**` and `tests/**`, but packages/ui's tests
also read its token sources (`tokens/**`) and token build scripts (`scripts/**`), so a cached run
could be replayed after such a change. `packages/ui/turbo.json` adds the two globs for that package
only. Its `inputs` replace the root's unless they start with `$TURBO_EXTENDS$` (turbo 2.11), and
with no package file the root's apply: the effective list is resolved the way turbo does it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXTENDS = "$TURBO_EXTENDS$"


def _root_inputs(task: str) -> list[str]:
    tasks: dict[str, Any] = json.loads((ROOT / "turbo.json").read_text(encoding="utf-8"))["tasks"]
    inputs: list[str] = tasks[task]["inputs"]
    return inputs


def _ui_inputs(task: str) -> list[str]:
    path = ROOT / "packages" / "ui" / "turbo.json"
    if not path.is_file():
        return _root_inputs(task)
    config: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    assert config.get("extends") == ["//"], "a package turbo.json extends the root"
    own: list[str] | None = config.get("tasks", {}).get(task, {}).get("inputs")
    if own is None:
        return _root_inputs(task)
    return _root_inputs(task) + own[1:] if own[:1] == [EXTENDS] else own


@pytest.mark.parametrize("task", ["test", "test:cov"])
def test_ui_tests_rerun_when_only_tokens_or_scripts_change(task: str) -> None:
    inputs = _ui_inputs(task)
    assert {"tokens/**", "scripts/**"} <= set(inputs)
    assert set(_root_inputs(task)) <= set(inputs), "keeps src, test, tests and the .md exclusion"
