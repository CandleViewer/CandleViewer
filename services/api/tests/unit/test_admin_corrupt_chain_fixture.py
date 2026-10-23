"""E42-Q01 (#962): the corrupted-chain fixture's constants are synthetic and its victim is its own.

The database half, through `POST /admin/audit/verify`, is
`tests/integration/admin/test_admin_corrupt_chain_pg.py`.
"""

from __future__ import annotations

import pytest

from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.observability.redaction import redact_text
from tests.fixtures.admin.corrupt_chain import ACTION, ACTOR, ENTRIES, FORGED, VICTIM_POSITION


@pytest.mark.parametrize("value", [ACTOR, ACTION, FORGED])
def test_no_corrupted_chain_value_is_secret_shaped(value: str) -> None:
    assert redact_text(value) == value


def test_the_victim_is_one_of_the_fixtures_own_entries() -> None:
    assert 0 <= VICTIM_POSITION < ENTRIES


def test_the_fixtures_entries_use_a_registered_action() -> None:
    assert ACTION in AUDIT_ACTIONS
