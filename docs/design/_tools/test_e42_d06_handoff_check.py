"""Tests for e42_d06_handoff_check.py: the gates pass on the tree and each mutation trips only its own.

Run from the repository root: `python3 -m pytest -q docs/design/_tools/test_e42_d06_handoff_check.py`.
Offline; it reads the working tree and mutates only in-memory copies of the pack, deck and sheet.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import e42_d06_handoff_check as check

ROOT = check.ROOT
BASE = check.texts(ROOT)


def test_check_tree_passes() -> None:
    assert check.check(ROOT, BASE) == []


def test_every_gate_has_a_mutation() -> None:
    assert {m[1] for m in check.mutations()} == set(check.active())


@pytest.mark.parametrize("mutation", check.mutations(), ids=lambda m: m[0])
def test_mutation_trips_only_its_gate(mutation: tuple[str, str, str, str, str]) -> None:
    _, gate, target, find, repl = mutation
    assert find in BASE[target]
    found = check.check(ROOT, {target: BASE[target].replace(find, repl, 1)})
    assert found
    assert {f.split(" ", 1)[0] for f in found} == {gate}


def test_block_ends_at_the_next_peer_heading() -> None:
    lines = ["# t", "## 1. a", "x", "### 1.1 b", "y", "## 2. c", "z"]
    assert check.block(lines, "## 1. ") == ["## 1. a", "x", "### 1.1 b", "y"]
    assert check.block(lines, "### 1.1 ") == ["### 1.1 b", "y"]


def test_rows_drop_header_and_rule() -> None:
    table = "| A | B |\n| - | - |\n| 1 | 2 |\n| 3 | 4 |"
    assert check.rows(table) == [["1", "2"], ["3", "4"]]


def test_self_test_passes() -> None:
    assert check.self_test(ROOT) == []
