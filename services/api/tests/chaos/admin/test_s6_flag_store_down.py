"""E42-Q03 scenario 6, server half: the flag store unreachable, then back (#1216).

The flag store's engine reaches Postgres through a relay of its own, which blackholes it: the
audit module keeps its own healthy path, so only the store fails. `GET /admin/feature-flags`
stays `200` with `resolution: fail_closed`; every boolean flag reads its fail-closed value (the
order-entry kill switch engaged, `trading.live_enabled` off, maintenance on) and no item carries
what only a stored row knows (`default_value`, `updated_at`; D1a). After the store returns the list
is `stored` again within the 1 s retry plus one read. The write half (`PUT` answers `503
store_unavailable` and changes nothing) is pinned by `tests/unit/admin/test_flag_routes.py`
(`test_a_store_outage_is_503_and_says_when_to_retry`): a write needs a step-up this composition
does not run. The UI half (FF-12, MM-8) is part 3's. Marked `harness`: needs Docker, runs nightly.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from candleviewer.admin.flags.catalogue import LIVE_ENABLED, MAINTENANCE_MODE
from candleviewer.admin.flags.registry import FlagKind
from candleviewer.admin.flags.service import RETRY_S
from candleviewer.api.feature_flags import make_feature_flags_routers
from candleviewer.audit.access import AuditPrincipal
from tests.chaos.admin._relay import Relay, upstream_of
from tests.chaos.admin._server import FixedPrincipal, app_of, audit_module, client, flags_runtime

pytestmark = [pytest.mark.chaos, pytest.mark.harness]

ORDER_ENTRY_KILL = "killswitch.order_entry"
RECOVERED_WITHIN_S = RETRY_S + 2.0  # the retry, one read and the reset link's reconnect
POLL_S = 0.1


@pytest.fixture
async def store_relay(pg_dsn: str) -> AsyncIterator[Relay]:
    """The flag store's own path to Postgres."""
    async with Relay(upstream_of(pg_dsn)) as opened:
        try:
            yield opened
        finally:
            await opened.heal()
            await opened.ensure_up()


async def _list(http: Any) -> dict[str, Any]:
    response = await http.get("/admin/feature-flags")
    assert response.status_code == 200, response.text
    return dict(response.json())


async def test_s6_an_unreachable_store_lists_fail_closed_values_then_recovers(
    relay: Relay, store_relay: Relay, pg_dsn: str, owner: AuditPrincipal, tmp_path: Path
) -> None:
    async with (
        audit_module(relay.through(pg_dsn), tmp_path) as audit,
        flags_runtime(store_relay.through(pg_dsn), audit.writer) as flags,
    ):
        read, _write = make_feature_flags_routers(
            flags, resolver=FixedPrincipal(owner), audit=audit.writer
        )
        async with client(app_of(read)) as http:
            assert (await _list(http))["resolution"] == "stored"
            flags.service.invalidate()  # the next read goes to the store, not the 5 s cache
            store_relay.blackhole()
            listed = await _list(http)
            assert listed["resolution"] == "fail_closed"
            values = {item["key"]: item for item in listed["items"]}
            for key, item in values.items():
                spec = flags.registry[key]
                if spec.kind is FlagKind.BOOLEAN:
                    assert item["value"] == spec.fail_closed_value, key
                assert "default_value" not in item and "updated_at" not in item, key
            assert values[ORDER_ENTRY_KILL]["value"] is True
            assert values[LIVE_ENABLED]["value"] is False
            assert values[MAINTENANCE_MODE]["value"] is True
            await store_relay.heal()
            await store_relay.ensure_up()
            healed = time.monotonic()
            while (await _list(http))["resolution"] != "stored":
                assert time.monotonic() - healed < RECOVERED_WITHIN_S, "the store did not return"
                await asyncio.sleep(POLL_S)  # paces the reads; the service's retry decides
            print(f"S6: stored again {(time.monotonic() - healed) * 1000:.0f} ms after the heal")
    await relay.ensure_up()
