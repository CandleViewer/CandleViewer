"""`_fuzz.drive` and `_fuzz.Watch`, which every nightly fuzz target runs on (#415, E17-X02): the
time box, the seed of each run, and what a failure on a later run records. On a fake clock that
reads one second more each time it is read, so no test sleeps. The targets run nightly; the
reports of their failures are pinned by `test_cvwb_fuzz_report.py`."""

from __future__ import annotations

import base64
import hashlib
import json
from itertools import count
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import hypothesis
import pytest
from hypothesis import settings
from hypothesis import strategies as st

from tests.unit.ws import _fuzz
from tests.unit.ws._fuzz import Input

BASE = 4_000_000_007  # the base seed here, whatever CV_FUZZ_SEED is set to


def _case(n: int) -> Input:
    return Input("probe", lambda: str(n).encode())


CASES = st.integers(0, 10**9).map(_case)


@pytest.fixture(autouse=True)
def _drive_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fixed base seed, no time box, 30 examples a run, and a clock that `drive` reads once for
    its deadline and once after each run, a second apart."""
    ticks = count()
    monkeypatch.setattr(_fuzz, "SEED", BASE)
    monkeypatch.setattr(_fuzz, "SECONDS", 0.0)
    monkeypatch.setattr(_fuzz, "FUZZ_SETTINGS", settings(_fuzz.FUZZ_SETTINGS, max_examples=30))
    monkeypatch.setattr(_fuzz, "time", SimpleNamespace(monotonic=lambda: float(next(ticks))))


@pytest.fixture
def runs(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """The seed of each run `drive` starts, in order: each run seeds Hypothesis first."""
    started: list[int] = []
    real = hypothesis.seed

    def spy(value: int) -> Any:
        started.append(value)
        return real(value)

    monkeypatch.setattr(_fuzz, "seed", spy)
    return started


def test_drive_makes_one_run_from_the_base_seed_without_a_time_box(runs: list[int]) -> None:
    _fuzz.drive(CASES, lambda case: None)
    assert runs == [BASE]


def test_drive_starts_runs_from_the_next_seeds_until_the_time_box_has_passed(
    monkeypatch: pytest.MonkeyPatch, runs: list[int]
) -> None:
    monkeypatch.setattr(_fuzz, "SECONDS", 3.0)  # the clock reads 0, then 1, 2 and 3 after the runs
    drawn: dict[int, list[bytes]] = {}
    _fuzz.drive(CASES, lambda case: drawn.setdefault(case.run, []).append(case.data))
    assert runs == [BASE, BASE + 1, BASE + 2]
    assert sorted(drawn) == [0, 1, 2]  # each case is told its run
    assert len({tuple(cases) for cases in drawn.values()}) == 3  # each run draws its own cases


def test_a_failure_on_a_later_run_records_that_runs_seed_and_replays_with_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runs: list[int]
) -> None:
    monkeypatch.setenv("CV_FUZZ_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setattr(_fuzz, "SECONDS", 10.0)  # room for ten runs
    third = BASE + 2

    def check(case: Input) -> None:
        n = int(case.data)
        if runs[-1] == third and n > 10**8 and n % 3 == 0:  # a fault that only run 2 can reach
            raise AssertionError(_fuzz.save_failure(case)) from None

    with pytest.raises(AssertionError) as first:
        _fuzz.drive(CASES, check)
    assert runs == [BASE, BASE + 1, third]  # the failure ended the loop: no fourth run
    label, _, name = str(first.value).partition(" sha256=")
    record = json.loads((tmp_path / f"probe-{name}.json").read_text("utf-8"))
    assert (label, record["target"], record["seed"]) == ("probe", "probe", str(third))
    pair = f"{record['seed']}:".encode() + base64.b64decode(record["input"])
    assert hashlib.sha256(pair).hexdigest() == name  # the digest names that seed and that input
    monkeypatch.setattr(_fuzz, "SEED", int(record["seed"]))  # the recorded seed, same example count
    monkeypatch.setattr(_fuzz, "SECONDS", 0.0)
    runs.clear()
    with pytest.raises(AssertionError) as again:
        _fuzz.drive(CASES, check)
    assert runs == [third]
    assert str(again.value) == str(first.value)  # the same failure, digest included


@pytest.mark.parametrize(
    ("took", "slow"),
    [(0.0, False), (_fuzz.CALL_SECONDS, False), (_fuzz.CALL_SECONDS + 0.001, True)],
)
def test_a_block_is_slow_only_when_it_takes_longer_than_the_bound(
    monkeypatch: pytest.MonkeyPatch, took: float, slow: bool
) -> None:
    readings = iter([10.0, 10.0 + took])
    monkeypatch.setattr(_fuzz, "time", SimpleNamespace(perf_counter=lambda: next(readings)))
    with _fuzz.Watch() as watch:
        pass
    assert watch.slow is slow


def test_a_block_that_raises_is_timed_and_its_error_goes_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    readings = iter([0.0, _fuzz.CALL_SECONDS + 1])
    monkeypatch.setattr(_fuzz, "time", SimpleNamespace(perf_counter=lambda: next(readings)))
    watch = _fuzz.Watch()
    with pytest.raises(ValueError, match="boom"), watch:
        raise ValueError("boom")
    assert watch.slow
