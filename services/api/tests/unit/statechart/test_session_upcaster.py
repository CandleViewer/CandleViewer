"""Golden-snapshot tests for the B16 upcasters (CLAUDE.md §6)."""

from __future__ import annotations

from candleviewer.statechart.session_upcasters import (
    B16_FROM_HASH,
    B16_TO_HASH,
    B16_V1_HASH,
    B16_V2_HASH,
    upcast_session_v0_to_v1,
    upcast_session_v1_to_v2,
)
from candleviewer.statechart.upcasters import has_upcaster


def test_upcaster_registered_for_hash_transition() -> None:
    assert has_upcaster("session", B16_FROM_HASH, B16_TO_HASH)


def test_upcast_seeds_step_up_context_and_preserves_existing() -> None:
    old = {"session_id": "s1", "elevated_until_us": None}
    new = upcast_session_v0_to_v1(old)
    assert new == {
        "session_id": "s1",
        "elevated_until_us": None,
        "elevated_classes": {},
        "step_up_failures": 0,
        "readonly_until_us": None,
    }
    assert "elevated_classes" not in old


def test_v1_to_v2_chains_from_v1_and_is_registered() -> None:
    assert B16_V1_HASH == B16_TO_HASH
    assert has_upcaster("session", B16_V1_HASH, B16_V2_HASH)


def test_upcast_v1_to_v2_seeds_an_unlocked_session_and_preserves_existing() -> None:
    """#2301: a v1 snapshot has no lock state, so it is an unlocked `auth.active`
    (the row's `is_idle_locked` re-evaluates the lock on first access)."""
    old = {"session_id": "s1", "revoke_reason": None, "step_up_failures": 2}
    new = upcast_session_v1_to_v2(old)
    assert new == {
        "session_id": "s1",
        "revoke_reason": None,
        "step_up_failures": 2,
        "idle_locked": False,
        "unlock_attempts": 0,
        "one_click_armed": None,
    }
    assert "idle_locked" not in old
