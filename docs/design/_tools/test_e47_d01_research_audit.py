"""Tests for e47_d01_research_audit.py: every gate passes; each mutation trips only its own gate.

Run from the repository root:
`python3 -m pytest -q docs/design/_tools/test_e47_d01_research_audit.py`.
Offline; it reads the working tree and the pinned base, and mutates only in-memory copies.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import e47_d01_research_audit as audit
import spec_audit_lib as L

TREE = audit.read_tree()


def expect(ok: bool, what: str) -> None:
    """An assertion that survives `python3 -O` (Ruff S101)."""
    if not ok:
        raise AssertionError(what)


def test_every_gate_passes_on_the_memo() -> None:
    failed = [(r.gate, r.detail) for r in L.run_gates(audit.GATES, TREE) if not r.ok]
    expect(failed == [], f"failed: {failed}")


def test_every_gate_has_a_mutation() -> None:
    gates = {g.name for g in audit.GATES}
    expect({m.gate for m in audit.MUTATIONS} == gates, "a gate has no mutation")


@pytest.mark.parametrize("mutation", audit.MUTATIONS, ids=lambda m: m.mid)
def test_mutation_trips_only_its_gate(mutation: L.Mutation) -> None:
    mutated = L.apply_mutation(TREE, mutation)
    failed = [r.gate for r in L.run_gates(audit.GATES, mutated) if not r.ok]
    expect(failed == [mutation.gate], f"{mutation.mid} tripped {failed}")


def test_cite_grammar_reads_keys_and_ranges() -> None:
    found = audit.cites("see `05`:185 and `KMAP`:615\u2013618, not KMAP:1 or `x`:2")
    got = [(c.doc, c.lo, c.hi) for c in found]
    expect(got == [("05", 185, 185), ("KMAP", 615, 618)], f"parsed {got}")


def test_per_minute_halves_the_two_minute_window() -> None:
    got = (audit.per_minute(23), audit.per_minute(0), audit.per_minute(22))
    expect(got == ("11.5", "0", "11"), f"per minute {got}")


def test_flood_default_is_silent_and_always_is_not() -> None:
    table = audit.flood()
    expect(table["On significant change (default)"][0] == "0 / 0 / 0", "the default speaks")
    expect(table["Always · Normal"][1] != "0", "Always is silent")


def test_sc_screen_holds_the_criteria_a_reviewer_asked_for() -> None:
    for sc in ("2.1.1", "2.4.11", "2.5.7", "2.5.8", "3.3.8"):
        expect(sc in audit.SC_SCREEN, f"{sc} is not screened")


def test_t2_note_rejects_an_unknown_status_and_a_missing_ad() -> None:
    memo = TREE.text("memo")
    bad = memo.replace("AD-5 a key binding", "a key binding", 1).replace("AD-5 and AD-4", "", 1)
    mutated = L.Tree(files={**TREE.files, "memo": bad}, changed=TREE.changed)
    expect(audit.g_t2(mutated) == ["section 3.3 does not name AD-5"], f"{audit.g_t2(mutated)}")


def test_pending_heading_names_the_posted_list() -> None:
    tail = f"ruling pending (comment {audit.BQ_LIST})"
    expect(audit.BQ_HEADING.endswith(tail), "the heading lost the comment id")
