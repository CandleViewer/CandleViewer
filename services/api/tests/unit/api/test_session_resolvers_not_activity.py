"""#2300 slice 2f-B: a session-backed principal resolver is never activity.

The resolvers authorise most of the signed-in REST surface (market and chart reads, rules, audit,
admin, owner and order routes). Before #2300's last slice each re-stamped `last_seen_at` on
every request, so a background poll kept an unattended terminal unlocked. Now only extend and
unlock move the idle deadline: a resolver authenticates and never calls `touch()`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from starlette.requests import Request

from candleviewer.api.audit_principal import SessionAuditPrincipalResolver
from candleviewer.api.order_principal import SessionTradingPrincipalResolver
from candleviewer.api.rules_actor import SessionRulesActorResolver
from candleviewer.api.session_snapshot import SessionSnapshotResolver

_UID = uuid.uuid4()
_RECORD = SimpleNamespace(
    view_as=None, id=uuid.uuid4(), user_id=_UID, step_up_elevations={}, readonly_until=None
)


class _Sessions:
    """Records how a resolver uses the session service: the keywords it authenticates with, and
    any `touch()` (the re-stamp a resolver must never make)."""

    def __init__(self) -> None:
        self.keywords: list[dict[str, Any]] = []
        self.touched: list[str] = []

    async def authenticate_access_token(self, raw_access_token: str, **keywords: Any) -> Any:
        self.keywords.append(keywords)
        return _RECORD

    async def touch(self, session_id: str) -> Any:
        self.touched.append(session_id)
        return _RECORD


class _Identity:
    async def user(self, user_id: str) -> dict[str, Any]:
        return {"username": "u", "roles": ["owner"], "status": "active"}

    async def session_info(self, user_id: str) -> dict[str, Any]:
        return {"permissions": [], "account_scope": []}


class _Grants:
    async def load_trade_grants(
        self, user_id: uuid.UUID
    ) -> list[tuple[uuid.UUID, bool, bool, bool]]:
        return []


def _resolvers() -> dict[str, Callable[[_Sessions], Any]]:
    return {
        "snapshot": lambda s: SessionSnapshotResolver(lambda: s, _Identity()),
        "audit": lambda s: SessionAuditPrincipalResolver(lambda: s, _Identity()),
        "rules": lambda s: SessionRulesActorResolver(lambda: s, lambda: None, _Identity()),
        "orders": lambda s: SessionTradingPrincipalResolver(lambda: s, _Identity(), _Grants()),
    }


@pytest.mark.parametrize("name", sorted(_resolvers()))
async def test_a_resolver_authenticates_without_ever_re_stamping_the_session(name: str) -> None:
    sessions = _Sessions()
    resolver = _resolvers()[name](sessions)
    request = Request({"type": "http", "headers": [(b"authorization", b"Bearer tok")]})
    await resolver.resolve(request)
    assert sessions.keywords == [{}] and sessions.touched == []
