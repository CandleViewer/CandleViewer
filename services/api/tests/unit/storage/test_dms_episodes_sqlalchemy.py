"""E27-T04 W5 (#837): the dead-man's-switch episode journal refuses, before any I/O, an unknown
environment and anything but the monitor's closed codes, so no free text reaches `details`
(C-12.6). The SQL: `tests/integration/storage/test_dms_episode_journal_pg.py`."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast, get_args
from uuid import UUID

import pytest

import candleviewer.storage.repositories.dms_episodes_sqlalchemy as store
from candleviewer.accounts.health import HealthReason, HealthState
from candleviewer.storage.repositories.accounts import AccountsStoreError
from candleviewer.storage.repositories.dms_episodes_sqlalchemy import SqlAlchemyDmsEpisodeJournal

_ECHO = "echoed exchange text: key abc123"  # what a caller might pass on as a code
_ACCOUNT = UUID("a1000000-0000-4000-8000-000000000001")


def test_a_journal_for_an_unknown_environment_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown env"):
        SqlAlchemyDmsEpisodeJournal(cast(Any, None), env="prod")


@pytest.mark.parametrize(("from_state", "reason"), [("down", _ECHO), (_ECHO, "no_success")])
async def test_a_record_of_any_other_code_is_refused(from_state: str, reason: str) -> None:
    journal = SqlAlchemyDmsEpisodeJournal(cast(Any, None), env="demo")  # refused before any I/O
    at = datetime(2026, 10, 18, 12, tzinfo=UTC)
    with pytest.raises(AccountsStoreError, match="closed codes"):
        await journal.record(_ACCOUNT, from_state=from_state, reason=reason, at=at)


def test_the_journal_takes_exactly_the_codes_of_the_monitor() -> None:
    assert store._STATES == {state.value for state in HealthState}
    assert store._REASONS == set(get_args(HealthReason))
