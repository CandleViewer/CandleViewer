"""Composition-root wiring (not a module) for `testApiKey` (E27-T03 slice 2b6, #836).

It binds `accounts.key_test.KeyTest` to the stored-key self-check (decision 11: a test's verdict is
handled as the hourly pass handles one), to key import's owner-scoped reads (one Postgres pool for
the key routes, released by that import's drain), and to the adapter's private-WS `auth` probe on
the process environment only (C-2.11), stamped on the exchange's clock once the clock guard has
measured it. Only the real backend has a self-check and an import, so the fake one has no test.
The probe is named here and in the adapter only (`test_ws_probe_callers.py`). Nothing here does I/O.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from candleviewer.accounts.key_test import KeyTest, PrivateAuth
from candleviewer.accounts.selfcheck import KeySelfCheck
from candleviewer.key_import_wiring import KeyImports

if TYPE_CHECKING:
    from candleviewer.app import AppContext

__all__ = ["wire_key_test"]


def wire_key_test(
    ctx: AppContext, selfcheck: KeySelfCheck | None, imports: KeyImports | None
) -> KeyTest | None:
    """`testApiKey`'s flow on the real backend; `None` without a self-check or an import."""
    if selfcheck is None or imports is None:
        return None
    env, exchange = ctx.settings.environment.value, ctx.exchange_bybit

    def offset_ms() -> int:
        """Exchange minus host clock, read per probe: 0 until the guard has measured it."""
        return ctx.ingestion.clock_offset_ms() or 0

    async def websocket(key_id: UUID) -> PrivateAuth:
        return await exchange.key_ws_probe(env, key_id, clock_offset_ms=offset_ms)

    return KeyTest(
        imports.flow.accounts, selfcheck, websocket, env=env, clock=lambda: datetime.now(UTC)
    )
