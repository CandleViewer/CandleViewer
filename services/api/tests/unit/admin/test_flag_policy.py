"""E42-T03: the pure write policy: the one step-up class a write needs, judged on the key and the
row as stored, and what counts as a real transition of the stored value."""

from __future__ import annotations

import pytest

from candleviewer.admin.flags import LIVE_ENABLED, MAINTENANCE_MODE, StoredFlag, default_registry
from candleviewer.admin.flags.policy import step_up_class, stored_transition
from candleviewer.admin.flags.registry import FlagValue


@pytest.mark.parametrize(
    ("key", "stored", "value", "expected"),
    [
        ("killswitch.ingestion", 0, False, "killswitch"),  # unreadable counts as engaged
        (MAINTENANCE_MODE, True, False, "killswitch"),  # a release
        (MAINTENANCE_MODE, False, False, "flags"),  # nothing to release
        (MAINTENANCE_MODE, False, True, "flags"),  # engaging: the console is not the emergency stop
        (MAINTENANCE_MODE, True, True, "flags"),
        (LIVE_ENABLED, False, True, "live_enablement"),
        (LIVE_ENABLED, "yes", True, "live_enablement"),  # unreadable: not enabled
        (LIVE_ENABLED, True, True, "live_enablement"),  # whatever is stored
        (LIVE_ENABLED, True, False, "flags"),  # turning the live gate off
        ("rules.graph_editor", True, False, "flags"),
    ],
)
def test_one_step_up_class_from_the_key_and_the_row_as_stored(
    key: str, stored: FlagValue, value: object, expected: str
) -> None:
    assert step_up_class(default_registry()[key], StoredFlag(stored), value) == expected


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        (False, True, True),
        (True, False, True),
        (True, True, False),
        (None, True, True),  # unknown to true: as a boot that finds it on
        (None, False, False),  # unknown to false announces nothing
        ("on", True, True),  # an unreadable row is unknown
        ("on", False, False),
    ],
)
def test_a_stored_transition_is_a_change_from_a_known_value_or_from_unknown_to_true(
    before: FlagValue | None, after: bool, expected: bool
) -> None:
    row = None if before is None else StoredFlag(before)
    spec = default_registry()[MAINTENANCE_MODE]
    assert stored_transition(spec, row, StoredFlag(after)) is expected
