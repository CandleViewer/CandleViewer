"""Tests for e19_d07_handoff_check.py: the tree passes and each gate fails on its own mutation.

Run from the repository root: `python3 -m pytest -q docs/design/_tools/test_e19_d07_handoff_check.py`.
Offline; it reads the working tree and the pinned sources, and mutates only in-memory copies.
With no pack on disk (slice 1a) the pack-side tests check that those gates are not run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import e19_d07_handoff_check as check

PACK, DECK = check.read()


def failing(result: dict[str, list[str]]) -> list[str]:
    return [gate for gate, found in result.items() if found]


def test_tree_passes() -> None:
    assert failing(check.check(PACK, DECK)) == []


def test_self_test_passes() -> None:
    assert check.self_test() == []


def test_each_mutation_trips_only_its_gate() -> None:
    for gate, target, find, repl in check.MUTATIONS:
        if target == "pack" and PACK is None:
            assert gate in check.PACK_GATES or gate in check.check(None, DECK)
            continue
        text = PACK if target == "pack" else DECK
        assert text is not None and text.count(find) == 1, gate
        mutated = text.replace(find, repl)
        got = check.check(mutated, DECK) if target == "pack" else check.check(PACK, mutated)
        assert failing(got) == [gate]


def test_every_gate_has_a_mutation() -> None:
    assert {m[0] for m in check.MUTATIONS} == set(check.GATES)
    assert {m[0] for m in check.MUTATIONS if m[1] == "deck"} == {"G-RAW", "G-DECK"}


def test_deck_string_must_be_a_whole_cell() -> None:
    deck = json.loads(DECK)
    wid = next(iter(deck["entries"]))
    deck["entries"][wid]["text"] = deck["entries"][wid]["text"][:-3] + '"'
    found = check.gate_deck(PACK, json.dumps(deck))
    assert any(f.startswith(wid) for f in found)


def test_deck_placeholder_fails() -> None:
    deck = json.loads(DECK)
    wid = next(iter(deck["entries"]))
    deck["entries"][wid]["text"] = '"Lorem ipsum"'
    assert any("placeholder" in f for f in check.gate_deck(PACK, json.dumps(deck)))


def test_raw_hex_in_the_deck_fails() -> None:
    assert check.gate_raw(PACK, DECK.replace('"pack": "E19-D07"', '"pack": "#a1b2c3"'))


def test_cites_expand_ranges_and_continuations() -> None:
    assert check.cites("(`22`:10–12, :20; D03:5)") == [
        ("22", 10, 12),
        ("22", 20, 20),
        ("D03", 5, 5),
    ]


def test_section_ends_at_the_next_peer_heading() -> None:
    text = "# t\n## 1. a\nx\n### 1.1 b\ny\n## 2. c\nz"
    assert check.section(text, "## 1. ") == ["## 1. a", "x", "### 1.1 b", "y"]
    assert check.section(text, "### 1.1 ") == ["### 1.1 b", "y"]
    assert check.section(text, "## 9. ") == []


def test_every_source_reads_at_its_pin() -> None:
    assert [k for k in check.SOURCES if not check.source(k)] == []
