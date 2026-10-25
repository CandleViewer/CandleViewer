"""The bootstrap Owner grant count `auth_owner_bootstraps` (#4479 C2; SR-023, threat model U46):
the CRITICAL `users.owner_bootstrapped` rows in `audit_log`, one per grant, written ahead in its
transaction (PR-B). It only rises, and unlike `auth_owner_bootstrap_events` no restart resets it
and no sign-in resolves it. `BreakGlassNotice` reads it by a statement of its own, at boot and every
refresh, as it reads `auth_break_glass_attempts`; `AuthOwnerBootstrapped` pages on it.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import cast

import pytest
import structlog
from prometheus_client import REGISTRY

from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.audit.journal import HOST_JOURNAL_ACTIONS
from candleviewer.auth.break_glass_notice import BreakGlassNotice
from candleviewer.auth.metrics import (
    AUTH_EXPORTED_NAMES,
    auth_break_glass_attempts,
    auth_break_glass_unresolved_events,
    auth_owner_bootstraps,
)
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.storage.repositories.break_glass_sqlalchemy import SqlAlchemyBreakGlassEvents
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.unit.auth.test_break_glass_attempts_metric import _Rel, _scraped

SERIES = "auth_owner_bootstraps"
_GAUGES = (auth_owner_bootstraps, auth_break_glass_attempts, auth_break_glass_unresolved_events)


class _Events:
    """`BreakGlassEvents` fake: the grant count scripted, or the error to raise."""

    def __init__(self, grants: int | BaseException, attempts: int = 3) -> None:
        self.grants, self.attempts = grants, attempts

    async def unresolved_break_glass_count(self) -> int:
        return 1

    async def break_glass_attempt_count(self) -> int:
        return self.attempts

    async def owner_bootstrap_count(self) -> int:
        if isinstance(self.grants, BaseException):
            raise self.grants
        return self.grants


@pytest.fixture(autouse=True)
def _clean_gauges() -> Iterator[None]:
    """Process-wide gauges: each test starts from 0 and leaves 0 behind."""
    for gauge in _GAUGES:
        gauge.set(0.0)
    yield
    for gauge in _GAUGES:
        gauge.set(0.0)


def _reading(series: str = SERIES) -> float | None:
    return REGISTRY.get_sample_value(series)


def test_catalogue_declares_the_gauge_live_exported_and_owned_by_e09() -> None:
    spec = next(s for s in CATALOGUE if s.name == SERIES)
    assert (spec.kind, spec.labels, spec.status, spec.exported) == ("gauge", (), "live", True)
    assert (spec.owner_epic, "AuthOwnerBootstrapped" in spec.alert) == ("E09", True)
    assert SERIES in AUTH_EXPORTED_NAMES
    assert _reading() is not None  # bound at import, so its absent() guard stays quiet


async def test_start_publishes_the_count_before_it_returns_and_a_refresh_raises_it() -> None:
    """cv-api serves only after its start-up read, so the first scrape after a restart holds
    the durable count; a grant while cv-api runs shows at the next refresh."""
    events = _Events(grants=1)
    notice = BreakGlassNotice(events)
    await notice.refresh()  # what `start()` runs before serving
    assert _reading() == 1.0
    events.grants = 2
    await notice.refresh()
    assert (_reading(), _reading("auth_break_glass_attempts")) == (2.0, 3.0)


async def test_a_failed_read_keeps_the_last_value_and_is_counted_under_its_own_series() -> None:
    events = _Events(grants=1)
    notice = BreakGlassNotice(events)
    await notice.refresh()
    events.grants = OSError("permission denied")  # a revoked grant on `audit_log`
    with structlog.testing.capture_logs() as logs:
        await notice.refresh()
    assert (_reading(), notice.read_failures) == (1.0, 1)  # unknown never lowers the count
    failed = [e for e in logs if e["event"] == "auth.break_glass_state_read_failed"]
    assert [(e["series"], e["error"]) for e in failed] == [("owner_bootstraps", "OSError")]
    assert (_reading("auth_break_glass_attempts"), notice.unresolved) == (3.0, True)  # unblinded


def test_export_serves_the_gauge_with_the_env_label_and_its_help() -> None:
    auth_owner_bootstraps.set(1.0)
    text = _scraped("demo")
    assert f'{SERIES}{{env="demo"}} 1.0' in text and f"# HELP {SERIES} " in text


async def test_store_reads_one_count_over_the_grant_records() -> None:
    rel = _Rel(1)
    # cast: `_Rel` is a structural fake of the one method the reader calls.
    store = SqlAlchemyBreakGlassEvents(cast(SqlAlchemyRelationalRepository, rel))
    assert await store.owner_bootstrap_count() == 1
    assert rel.sql == ["SELECT count(*) FROM audit_log WHERE action = 'users.owner_bootstrapped'"]
    # The literal is PR-B's registered grant record, cv-api's own: never the host journal's.
    assert "users.owner_bootstrapped" in AUDIT_ACTIONS - HOST_JOURNAL_ACTIONS
