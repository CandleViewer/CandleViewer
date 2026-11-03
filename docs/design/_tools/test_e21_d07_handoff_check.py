"""Tests for e21_d07_handoff_check.py: the gates pass on the tree and each fails on its mutation.

Run from the repository root: `python3 -m pytest -q docs/design/_tools/test_e21_d07_handoff_check.py`.
Offline; it reads the working tree and the pinned commits, and mutates only in-memory copies.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import e21_d07_handoff_check as check

DECK = (check.ROOT / check.DECK_REL).read_text(encoding="utf-8")
PACK = (check.ROOT / check.PACK_REL).read_text(encoding="utf-8") if check.PACK_IN_TREE else ""
ALL = check.MUTATIONS + (check.PACK_MUTATIONS if check.PACK_IN_TREE else [])


def findings(pack: str = PACK, deck: str = DECK) -> list[str]:
    return check.check(pack if check.PACK_IN_TREE else None, deck)


def test_check_tree_passes() -> None:
    assert findings() == []


@pytest.mark.parametrize(("gate", "what", "edit"), ALL, ids=[m[1] for m in ALL])
def test_mutation_trips_only_its_gate(gate: str, what: str, edit: check.Edit) -> None:
    pack, deck = edit(PACK, DECK)
    result = findings(pack, deck)
    assert result, what
    assert all(f.startswith(gate + " ") for f in result), result


def test_self_test_catches_every_mutation() -> None:
    assert check.self_test() == []


def test_verbatim_needs_the_whole_string() -> None:
    assert check.verbatim('"Clamp"', 'say "Clamp" here')
    assert check.verbatim("Book stale 3 s", '("Book stale 3 s")')
    assert not check.verbatim("Book stal", '("Book stale 3 s")')
    assert not check.verbatim("Clam", "| Clamp |")
    assert not check.verbatim(" ", "| a |")


def test_block_ends_at_the_next_peer_heading() -> None:
    lines = ["# t", "## 1. a", "x", "### 1.1 b", "y", "## 2. c", "z"]
    assert check.block(lines, "## 1. ") == ["## 1. a", "x", "### 1.1 b", "y"]
    assert check.block(lines, "### 1.1 ") == ["### 1.1 b", "y"]


def test_cites_read_ranges_and_tails() -> None:
    got = [(name, num) for name, num, _ in check.cites("D02:221–233; `15`:2958, :2960")]
    assert got == [("D02", 221), ("D02", 233), ("15", 2958), ("15", 2960)]


def test_deck_duplicate_id_fails() -> None:
    deck = json.loads(DECK)
    deck["entries"].append(dict(deck["entries"][0]))
    result = findings(deck=json.dumps(deck))
    assert f"G-DECK {deck['entries'][0]['id']} is not unique" in result
