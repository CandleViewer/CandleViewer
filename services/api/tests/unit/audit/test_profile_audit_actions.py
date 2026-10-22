"""The E28 profile audit vocabulary is registered before any route emits it (E28-T02, #906;
threat model SR-E28-20, finding F-21).

`AuditWriter.emit` refuses an action outside `AUDIT_ACTIONS` (no row, a 500 at the edge), so the
six `profile.*` actions and the closed `reason` set of `profile.save_refused` are pinned here by
name, independently of the registry, and the two docs that list the vocabulary are held to them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from candleviewer.audit.actions import (
    AUDIT_ACTIONS,
    PROFILE_SAVE_REFUSED_REASONS,
    UnknownAuditAction,
    validate_action,
)

ROOT = Path(__file__).resolve().parents[5]
_ACTIONS = frozenset(
    f"profile.{verb}"
    for verb in ("created", "updated", "deleted", "bound", "unbound", "save_refused")
)
#: `native_stop_mandatory` (SR-E28-08), the first pass's `above_leverage_cap` and the exchange
#: limits of the second validation pass; no `step_up`: the path guard refuses a missing one before
#: the handler and B16 audits it (ruling B4). A malformed body is not audited (ruling, 2026-10-22).
_REASONS = frozenset(
    {
        "native_stop_mandatory",
        "above_leverage_cap",
        "cap_unbounded",  # PF-T02: a removed cap is a policy refusal (ruling of 2026-10-22 07:10Z)
        "max_leverage",
        "min_order_qty",
        "qty_step",
        "min_notional",
        "symbol_not_listed",
    }
)


def _words(text: str) -> str:
    """One line of single-spaced words: line wraps and table padding do not matter."""
    return " ".join(text.split())


def test_the_six_profile_actions_are_registered_by_exact_name() -> None:
    assert {a for a in AUDIT_ACTIONS if a.startswith("profile.")} == _ACTIONS
    assert {validate_action(action) for action in _ACTIONS} == _ACTIONS


@pytest.mark.parametrize("name", ["profile.changed", "profile.restored", "profile.save_failed"])
def test_a_profile_action_outside_the_vocabulary_is_refused(name: str) -> None:
    """`profile.changed` is the name 04 section 8.2 kept before E28 (finding F-21)."""
    with pytest.raises(UnknownAuditAction):
        validate_action(name)


def test_save_refused_reasons_are_the_profile_policy_refusals() -> None:
    assert PROFILE_SAVE_REFUSED_REASONS == _REASONS
    assert all(re.fullmatch(r"[a-z][a-z0-9_]*", reason) for reason in _REASONS)


def test_a_missing_step_up_is_no_save_refused_reason() -> None:
    """Ruling B4: the path guard refuses it before the handler runs, so B16 alone audits it
    (`auth.step_up_required`) and a handler cannot write `profile.save_refused{step_up}`."""
    assert not {r for r in PROFILE_SAVE_REFUSED_REASONS if "step_up" in r}
    assert "auth.step_up_required" in AUDIT_ACTIONS


def test_the_docs_list_the_profile_actions_and_the_closed_save_refused_reasons() -> None:
    """24 section 15.5 is the closed set (and holds each family's fields); 21 section 3.10.1 lists
    the actions that must be audited. Both name all six; 24 names the reasons the code holds."""
    plan = ROOT / "docs" / "plan"
    schema = (plan / "21-database-schema.md").read_text(encoding="utf-8")
    must_audit = schema.split("Actions that MUST be audited", 1)[1].split("\n\n", 1)[0]
    internal = (plan / "24-internal-schemas.md").read_text(encoding="utf-8")
    closed = internal[internal.index("### 15.5 Audited action vocabulary") :]
    closed = _words(closed[: closed.index("\n### ")])
    for vocabulary in (must_audit, closed):
        assert all(f"`{action}`" in vocabulary for action in _ACTIONS)
    sentence = re.search(r"its `reason` is one of (.*?) \(`PROFILE_SAVE_REFUSED_REASONS`\)", closed)
    assert sentence is not None
    assert set(re.findall(r"`([a-z_]+)`", sentence.group(1))) == PROFILE_SAVE_REFUSED_REASONS
