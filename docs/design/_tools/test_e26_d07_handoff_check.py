"""Tests for e26_d07_handoff_check.py: the gates pass on the tree and each mutation trips its own.

Run from the repository root: `python3 -m pytest -q docs/design/_tools/test_e26_d07_handoff_check.py`.
Offline; it reads the working tree and mutates only in-memory copies of the pack, deck and `14`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import e26_d07_handoff_check as check

BASE = check.texts(check.ROOT)


def test_check_tree_passes() -> None:
    assert check.check(check.ROOT, BASE) == []


@pytest.mark.parametrize(
    ("mid", "gate", "mutate"), check.MUTATIONS, ids=[m[0] for m in check.MUTATIONS]
)
def test_mutation_trips_only_its_gate(mid: str, gate: str, mutate: check.Mutation) -> None:
    found = check.check(check.ROOT, mutate(BASE))
    assert found, f"{mid} trips nothing"
    assert all(f.startswith(gate + " ") for f in found), found


def test_mutation_ids_are_unique_and_ordered() -> None:
    ids = [m[0] for m in check.MUTATIONS]
    assert ids == [f"M-{n:02d}" for n in range(1, len(ids) + 1)]


def test_every_gate_has_a_mutation() -> None:
    assert {m[1] for m in check.MUTATIONS} == set(check.GATES)


def test_self_test_passes() -> None:
    assert check.self_test(check.ROOT) == []


def test_main_exit_codes() -> None:
    assert check.main(["--check"]) == 0
    assert check.main(["--json"]) == 0
