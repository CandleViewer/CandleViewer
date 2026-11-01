"""E35-Q02 property suite: generated IR documents round-trip across every editor hop.

Run: ``uv run pytest tests/rules/roundtrip -q --no-cov -s`` (see docs/qa/e35-roundtrip-suite.md).

* ``CV_ROUNDTRIP_EXAMPLES`` - documents per run (default 10 000, the US-RULE-001 NFR floor).
* ``CV_ROUNDTRIP_SEED`` - base seed (default: fresh, always printed); export it to replay a run.
* ``CV_ROUNDTRIP_WORKERS`` - worker processes (default: CPU count, max 8).
* ``CV_ROUNDTRIP_DB`` - Hypothesis example database (default
  ``services/api/.hypothesis/roundtrip``); CI caches it so a failure found once is replayed
  on every later run.
"""

from __future__ import annotations

import os
import random
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings

from candleviewer.rules.ir import Rule
from tests.rules.roundtrip.shard import run_shard
from tests.rules.roundtrip.strategies import any_rule, form_rule

EXAMPLES = int(os.environ.get("CV_ROUNDTRIP_EXAMPLES", "10000"))
SEED = int(os.environ.get("CV_ROUNDTRIP_SEED", str(random.SystemRandom().randrange(2**31))))
WORKERS = max(1, int(os.environ.get("CV_ROUNDTRIP_WORKERS", str(min(8, os.cpu_count() or 1)))))
DB = os.environ.get("CV_ROUNDTRIP_DB", str(Path(__file__).parents[3] / ".hypothesis/roundtrip"))


def plan(total: int, workers: int, base_seed: int) -> list[tuple[str, int, int]]:
    """Two-thirds full grammar, one-third form subset, split evenly over workers; exact total."""
    out: list[tuple[str, int, int]] = []
    for kind, n in (("any", total * 2 // 3), ("form", total - total * 2 // 3)):
        for w in range(workers):
            share = n // workers + (1 if w < n % workers else 0)
            if share:
                out.append((kind, share, base_seed + 1000 * (kind == "form") + w))
    return out


def test_roundtrip_plan_splits_the_exact_document_count() -> None:
    p = plan(10_000, 7, 5)
    assert sum(n for _, n, _ in p) == 10_000
    assert len({s for *_, s in p}) == len(p)  # every shard has its own seed


def replay_note(shard: tuple[str, int, int]) -> str:
    """The seed and the exact command that replays a failing shard (the plan is deterministic)."""
    kind, n, shard_seed = shard
    return (
        f"[roundtrip] failing shard kind={kind} documents={n} shard_seed={shard_seed}; replay: "
        f"CV_ROUNDTRIP_SEED={SEED} CV_ROUNDTRIP_EXAMPLES={EXAMPLES} "
        f"CV_ROUNDTRIP_WORKERS={WORKERS} uv run pytest tests/rules/roundtrip -q --no-cov -s"
    )


#: A worker that dies (OOM-kill, host pressure) poisons the whole pool; the shards are seeded and
#: pure, so re-running the unfinished ones in a fresh pool is exact. Real property failures are
#: ordinary exceptions from ``f.result()`` and are never retried.
POOL_RESTARTS = 2
this = sys.modules[__name__]  # the module under its pytest-assigned name


def run_shards(shards: list[tuple[str, int, int]]) -> list[tuple[int, float]]:
    """Run every shard; restart the pool (bounded) when a worker process dies."""
    results: dict[int, tuple[int, float]] = {}
    last_exc: BrokenProcessPool | None = None
    for attempt in range(POOL_RESTARTS + 1):
        todo = [i for i in range(len(shards)) if i not in results]
        if not todo:
            break
        try:
            with ProcessPoolExecutor(max_workers=min(WORKERS, len(todo))) as pool:
                futures = {i: pool.submit(run_shard, *shards[i], DB) for i in todo}
                for i, f in futures.items():
                    try:
                        results[i] = f.result()
                    except BrokenProcessPool:
                        raise
                    except Exception as exc:  # a real property failure: name the seed (#1942)
                        exc.add_note(replay_note(shards[i]))
                        raise
        except BrokenProcessPool as exc:
            last_exc = exc
            print(f"[roundtrip] worker died (attempt {attempt + 1}/{POOL_RESTARTS + 1}): {exc!r}")
    missing = [shards[i] for i in range(len(shards)) if i not in results]
    if missing:
        raise AssertionError(
            f"worker pool kept dying; {len(missing)} shard(s) never finished "
            f"(seed={SEED}, workers={WORKERS}): {missing}"
        ) from last_exc
    return [results[i] for i in range(len(shards))]


@pytest.mark.roundtrip
def test_roundtrip_ten_thousand_generated_documents_round_trip() -> None:
    """Scenario: Ten thousand generated documents round-trip."""
    started = time.monotonic()
    shards = plan(EXAMPLES, WORKERS, SEED)
    print(f"\n[roundtrip] seed={SEED} workers={WORKERS} target={EXAMPLES}")
    total = 0
    try:
        for (kind, _, s), (done, secs) in zip(shards, run_shards(shards), strict=True):
            total += done
            print(f"[roundtrip] shard kind={kind} seed={s} documents={done} elapsed_s={secs:.1f}")
    finally:
        print(
            f"[roundtrip] seed={SEED} documents={total} elapsed_s={time.monotonic() - started:.1f}"
        )
    assert total >= EXAMPLES, f"only {total} documents generated (NFR floor {EXAMPLES})"


def test_roundtrip_run_shards_survives_a_dead_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """A BrokenProcessPool on the first pool is retried; a persistent one fails with a message."""
    built: list[int] = []

    def pool_factory(fail_first: int) -> Any:
        class Pool:
            def __init__(self, max_workers: int) -> None:
                built.append(max_workers)
                self.fail = len(built) <= fail_first

            def __enter__(self) -> Pool:
                return self

            def __exit__(self, *a: object) -> None:
                return None

            def submit(self, fn: Any, *args: Any) -> Any:
                class F:
                    def result(_self) -> tuple[int, float]:
                        if self.fail:
                            raise BrokenProcessPool("dead")
                        return (args[1], 0.0)

                return F()

        return Pool

    monkeypatch.setattr(this, "ProcessPoolExecutor", pool_factory(1))
    assert run_shards([("any", 3, 1), ("form", 2, 2)]) == [(3, 0.0), (2, 0.0)]
    assert len(built) == 2  # the dead first pool, then exactly one fresh pool

    built.clear()
    monkeypatch.setattr(this, "POOL_RESTARTS", 1)
    monkeypatch.setattr(this, "ProcessPoolExecutor", pool_factory(99))
    with pytest.raises(AssertionError, match="worker pool kept dying") as info:
        run_shards([("any", 3, 1)])
    assert isinstance(info.value.__cause__, BrokenProcessPool)
    assert len(built) == 2  # POOL_RESTARTS + 1 attempts, then give up


class InlinePool:
    """A pool stand-in that runs each shard in this process, so a fake failure is deterministic."""

    def __init__(self, max_workers: int) -> None:
        self.max_workers = max_workers

    def __enter__(self) -> InlinePool:
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def submit(self, fn: Any, *args: Any) -> Any:
        class Done:
            def __init__(self) -> None:
                self.error: Exception | None = None
                self.value: tuple[int, float] = (0, 0.0)
                try:
                    self.value = fn(*args)
                except Exception as exc:
                    self.error = exc

            def result(self) -> tuple[int, float]:
                if self.error is not None:
                    raise self.error
                return self.value

        return Done()


def test_roundtrip_failure_reports_its_seed_and_the_replay_reproduces_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#1942: a failing shard names the seed; replaying with it reproduces the same failure."""
    bad_seed = 4_242 + 1000  # the fixed fake counter-example: the first "form" shard of seed 4242

    def fake_shard(kind: str, n: int, shard_seed: int, db: str | None) -> tuple[int, float]:
        if shard_seed == bad_seed:
            raise AssertionError(f"counter-example kind={kind} shard_seed={shard_seed}")
        return (n, 0.0)

    monkeypatch.setattr(this, "ProcessPoolExecutor", InlinePool)
    monkeypatch.setattr(this, "run_shard", fake_shard)
    monkeypatch.setattr(this, "SEED", 4_242)
    monkeypatch.setattr(this, "EXAMPLES", 30)
    monkeypatch.setattr(this, "WORKERS", 2)
    with pytest.raises(AssertionError, match="counter-example") as first:
        run_shards(plan(30, 2, 4_242))
    notes = "\n".join(getattr(first.value, "__notes__", []))
    assert f"shard_seed={bad_seed}" in notes, notes
    assert "CV_ROUNDTRIP_SEED=4242" in notes, notes
    assert "kind=form " in notes, notes
    assert "documents=5 " in notes, notes

    # Replay: rebuild the run from the reported environment only, as a developer would.
    env = dict(re.findall(r"(CV_ROUNDTRIP_\w+)=(\d+)", notes))
    seed = int(env["CV_ROUNDTRIP_SEED"])
    examples = int(env["CV_ROUNDTRIP_EXAMPLES"])
    workers = int(env["CV_ROUNDTRIP_WORKERS"])
    monkeypatch.setattr(this, "SEED", seed)
    monkeypatch.setattr(this, "EXAMPLES", examples)
    monkeypatch.setattr(this, "WORKERS", workers)
    with pytest.raises(AssertionError, match="counter-example") as again:
        run_shards(plan(examples, workers, seed))
    again_notes = "\n".join(getattr(again.value, "__notes__", []))
    assert again_notes == notes, again_notes
    assert str(again.value) == str(first.value)


@pytest.mark.parametrize("strategy", [any_rule, form_rule], ids=["any", "form"])
def test_roundtrip_generated_documents_are_schema_valid(strategy: Any) -> None:
    """Guards the generator: invalid documents would only exercise the validator."""

    @settings(max_examples=50, deadline=None, database=None)
    @given(strategy)
    def prop(doc: dict[str, Any]) -> None:
        Rule.model_validate(doc)

    prop()
