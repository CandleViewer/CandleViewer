"""#399 R4: the pack rewrites its reports after each scenario; a stopped pack keeps what finished.

The full pack ran 35 h on the bench runner and was cancelled with no report, because the reports
were written only after the last scenario. `main` is driven here with a stand-in `run_scenario`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

import bench.ingestion.runner as runner
from bench.ingestion import budgets
from bench.ingestion.config import Scenario
from bench.ingestion.engine import ProcSampler

NAMES = ("soak_steady", "ratelimit_headroom")


@dataclass
class Pack:
    started: list[str] = field(default_factory=list)
    fail_at: str = ""  # the scenario that dies, as a cancelled or timed-out job's process does


@pytest.fixture
def pack(monkeypatch: pytest.MonkeyPatch) -> Pack:
    state = Pack()
    monkeypatch.setenv("CV_BENCH_MACHINE_PROFILE", "unit-test")  # never gated against a baseline
    monkeypatch.setattr(runner, "SCENARIOS", NAMES)

    async def run(sc: Scenario, sampler: ProcSampler | None = None) -> budgets.Verdict:
        state.started.append(sc.name)
        if sc.name == state.fail_at:
            raise RuntimeError("stopped")
        return budgets.Verdict(sc.name)

    monkeypatch.setattr(runner, "run_scenario", run)
    return state


def _md(out: Path) -> str:
    return next(out.glob("e08-smoke-*.md")).read_text(encoding="utf-8")


def _scenarios(out: Path) -> list[str]:
    rows = json.loads(next(out.glob("e08-smoke-*.json")).read_text(encoding="utf-8"))
    return [row["verdict"]["scenario"] for row in rows]


def test_reports_are_on_disk_after_each_scenario_and_marked_partial_until_the_last(
    tmp_path: Path, pack: Pack, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[list[str], str]] = []
    stand_in = runner.run_scenario

    async def run(sc: Scenario, sampler: ProcSampler | None = None) -> budgets.Verdict:
        if pack.started:  # the first scenario's reports exist before the second one starts
            seen.append((_scenarios(tmp_path), _md(tmp_path).splitlines()[0]))
        return await stand_in(sc, sampler)

    monkeypatch.setattr(runner, "run_scenario", run)
    assert runner.main(["all", "--out-dir", str(tmp_path)]) == 0
    first = "> **Partial:** 1 of 2 scenarios have finished; not run yet: ratelimit_headroom."
    assert seen == [(["soak_steady"], first)]
    md = _md(tmp_path)
    assert md.startswith("# E08-Q04 ingestion performance report") and "Partial" not in md
    assert _scenarios(tmp_path) == list(NAMES)
    diff = (tmp_path / "gate-diff.md").read_text(encoding="utf-8")
    assert diff.startswith("### soak_steady") and "### ratelimit_headroom" in diff
    assert not list(tmp_path.glob("*.tmp"))  # every report was renamed into place


def test_a_pack_stopped_part_way_keeps_the_reports_of_what_finished(
    tmp_path: Path, pack: Pack
) -> None:
    pack.fail_at = "ratelimit_headroom"
    with pytest.raises(RuntimeError, match="stopped"):
        runner.main(["all", "--out-dir", str(tmp_path)])
    assert pack.started == list(NAMES)
    assert _md(tmp_path).startswith("> **Partial:** 1 of 2 scenarios have finished; not run yet:")
    assert _scenarios(tmp_path) == ["soak_steady"]
    # the gate diff is the issue body of a failed pack: it says it is partial too
    diff = (tmp_path / "gate-diff.md").read_text(encoding="utf-8")
    assert diff.startswith("> **Partial:** 1 of 2") and "### soak_steady" in diff
