"""Tests for e15_d16_handoff_check.py: the gates pass on the tree and each fails on one mutation.

Run from the repository root: `python3 -m pytest -q docs/design/_tools/test_e15_d16_handoff_check.py`.
Offline; it reads the working tree and mutates only in-memory copies of the pack and the deck.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import e15_d16_handoff_check as check

ROOT = check.ROOT
PACK = (ROOT / check.PACK_REL).read_text(encoding="utf-8")
DECK = (ROOT / check.DECK_REL).read_text(encoding="utf-8")


def findings(pack: str = PACK, deck: str = DECK) -> list[str]:
    return check.check(ROOT, pack=pack, deck=deck)


def only(gate: str, result: list[str]) -> list[str]:
    return [f for f in result if f.startswith(gate)]


def test_check_tree_passes() -> None:
    assert findings() == []


def test_link_cite_past_the_end_fails() -> None:
    mutated = PACK.replace("`D15`:509", "`D15`:99999", 1)
    assert mutated != PACK
    assert only("G-LINK", findings(pack=mutated))


def test_link_cite_on_a_blank_line_fails() -> None:
    blank = check.read(check.KEYS["D15"], ROOT).index("") + 1
    mutated = PACK.replace("`D15`:509", f"`D15`:{blank}", 1)
    assert only("G-LINK", findings(pack=mutated))


def test_link_to_a_missing_file_fails() -> None:
    mutated = PACK.replace("](e15-layout-flows.md)", "](e15-no-such-file.md)", 1)
    assert mutated != PACK
    assert only("G-LINK", findings(pack=mutated))


def test_link_unknown_key_fails() -> None:
    mutated = PACK.replace("`D15`:509", "`ZZ99`:509", 1)
    assert only("G-LINK", findings(pack=mutated))


def test_hash_changed_value_fails() -> None:
    value, lift_id = check.HASH.findall(PACK)[0]
    mutated = PACK.replace(
        f"{value}<!--=HASH:{lift_id}-->", f"000000000000<!--=HASH:{lift_id}-->"
    )
    assert only("G-HASH", findings(pack=mutated)) == [
        f"G-HASH {lift_id}: the pack says 000000000000, the source is {value}"
    ]


def test_hash_missing_lift_fails() -> None:
    mutated = re.sub(r"[0-9a-f]{12}<!--=HASH:d14\.s4-->", "", PACK)
    assert "G-HASH d14.s4 is never stated in the pack" in findings(pack=mutated)


def test_index_missing_component_fails() -> None:
    lines = PACK.split("\n")
    row = next(
        i
        for i, line in enumerate(lines)
        if line.startswith("| US-LAY-004 ") and "CMP-188" in line
    )
    lines[row] = lines[row].replace("CMP-188 PriceAxis (`15`:2423); ", "")
    result = only("G-INDEX", findings(pack="\n".join(lines)))
    assert result == ["G-INDEX US-LAY-004 omits CMP-188 (`18` §2.16)"]


def test_index_missing_story_fails() -> None:
    lines = [line for line in PACK.split("\n") if not line.startswith("| US-LAY-008 ")]
    assert "G-INDEX US-LAY-008 has no row in §2" in findings(pack="\n".join(lines))


def test_deck_altered_string_fails() -> None:
    deck = json.loads(DECK)
    key = next(iter(deck["entries"]))
    deck["entries"][key] = deck["entries"][key] + " (edited)"
    result = only("G-DECK", findings(deck=json.dumps(deck)))
    assert f"G-DECK {key}: the string is not verbatim on its source line" in result


def test_deck_fragment_of_a_string_fails() -> None:
    deck = json.loads(DECK)
    key = next(
        k for k, v in deck["entries"].items() if v.startswith('"') and len(v) > 8
    )
    deck["entries"][key] = deck["entries"][key][:-3] + '"'
    result = only("G-DECK", findings(deck=json.dumps(deck)))
    assert f"G-DECK {key}: the string is not verbatim on its source line" in result


def test_deck_bare_string_must_be_a_whole_cell() -> None:
    assert check.verbatim("Reduced", "| CP-26 | Reduced | x |")
    assert not check.verbatim("Reduce", "| CP-26 | Reduced | x |")
    assert not check.verbatim('"Clos"', 'say "Close" here')


def test_deck_unknown_concept_member_fails() -> None:
    deck = json.loads(DECK)
    deck["concepts"]["CG-01"].append("D03:1 no.such.row")
    assert "G-DECK CG-01: no entry D03:1 no.such.row" in findings(deck=json.dumps(deck))


def test_deck_count_mismatch_fails() -> None:
    deck = json.loads(DECK)
    deck["entries"].popitem()
    assert only("G-DECK", findings(deck=json.dumps(deck)))


def test_block_ends_at_the_next_peer_heading() -> None:
    lines = ["# t", "## 1. a", "x", "### 1.1 b", "y", "## 2. c", "z"]
    assert check.block(lines, "## 1. ") == ["## 1. a", "x", "### 1.1 b", "y"]
    assert check.block(lines, "### 1.1 ") == ["### 1.1 b", "y"]
