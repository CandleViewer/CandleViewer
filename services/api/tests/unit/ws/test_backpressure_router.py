"""E17-T03 (#412): `make_ws_router(backpressure=...)`, `BackpressureConfig` and the welcome.

The budgeted pipeline bounds every connection's outbound queue (S2a, `test_pipeline_outbound.py`):
a router built without a config runs on the contract budget (`DEFAULT_BACKPRESSURE`), and every
welcome advertises `features.coalescing: true` (`23-ws-protocol.md` §4.2). #2409 removed
`CV_WS_BACKPRESSURE_ENABLED` and the 1 024-frame bound it kept while off; this file was
`test_backpressure_flag.py`.

The real router runs on the test's own loop behind a fake socket: no threads, no sleeps. Frames
are queued in one synchronous turn, so the writer cannot drain them meanwhile.
"""

from __future__ import annotations

import asyncio
import dataclasses
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.routing import APIWebSocketRoute

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.settings import Settings
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.gateway import DEFAULT_BACKPRESSURE, GatewayHub, make_ws_router
from candleviewer.ws.outbound import QUEUE_BYTES, QUEUE_FRAMES
from candleviewer.ws.pacing import CLASSIFY_INTERVAL_S
from candleviewer.ws.permissions import ConnectionRegistry
from candleviewer.ws.revocation import RevocationHub
from tests.unit.ws._system_snap import is_system_snap
from tests.unit.ws.test_gateway_teardown import _Socket
from tests.unit.ws.test_lifecycle_socket import BASE_MS, ORIGIN, SESSION, USER

_DEADLINE_S = 5.0
#: A burst past the bound #2409 removed (1 024 frames), well inside the contract budget.
_BURST = 1024


class _Rig:
    """The real `/ws` router, with the knob under test, behind a fake socket."""

    def __init__(self, **router_kwargs: Any) -> None:
        """`router_kwargs` go to `make_ws_router` as given: none at all is the router's default."""
        self.hub = GatewayHub()

        async def resolve(uid: uuid.UUID) -> PrincipalSnapshot:
            perms = frozenset({Permission.MARKETDATA_READ})
            return PrincipalSnapshot(uid, frozenset({"viewer"}), perms)

        async def authenticate(token: str) -> tuple[str, uuid.UUID, datetime]:
            return SESSION, USER, datetime(2100, 1, 1, tzinfo=UTC)

        router = make_ws_router(
            authenticate=authenticate,
            registry=ConnectionRegistry(resolve, lambda: BASE_MS),
            revocation_hub=RevocationHub(),
            allowed_origins=frozenset({ORIGIN}),
            hub=self.hub,
            clock=lambda: 0.0,
            wall_ms=lambda: BASE_MS,
            tick_s=0.005,
            **router_kwargs,
        )
        (route,) = router.routes
        assert isinstance(route, APIWebSocketRoute)
        self.endpoint = route.endpoint

    async def open(self, sock: _Socket) -> tuple[asyncio.Task[None], dict[str, Any]]:
        """Start the handler and take it through `hello` and `auth`; returns it and the welcome."""
        handler = asyncio.create_task(self.endpoint(sock))
        sock.feed({"t": "hello", "id": "h"})
        welcome: dict[str, Any] = await sock.sent.get()
        sock.feed({"t": "auth", "id": "a", "p": {"access_token": "tok"}})
        assert (await sock.sent.get())["t"] == "auth_ok"
        assert is_system_snap(await sock.sent.get())  # §12.1 (#4992): then the `system` snap
        return handler, welcome


async def test_router_with_a_backpressure_config_bounds_at_its_budget() -> None:
    """S2a: a burst within the config's budget is delivered whole, and one frame over it closes
    the socket `slow_consumer` / 4429."""
    rig, sock = _Rig(backpressure=BackpressureConfig(max_frames=_BURST + 2)), _Socket()
    async with asyncio.timeout(_DEADLINE_S):
        handler, _ = await rig.open(sock)
        (conn,) = rig.hub.of_user(USER)
        for _ in range(_BURST + 1):
            conn.push_system({"kind": "notice", "message": "tick"})
        for _ in range(_BURST + 1):
            assert (await sock.sent.get())["t"] == "d"
        assert not conn.closing
        for _ in range(_BURST + 3):
            conn.push_system({"kind": "notice", "message": "tick"})
        bye = await sock.sent.get()  # both lanes cleared: the `bye` is next
        await handler

    assert (bye["p"]["reason"], bye["p"]["code"]) == ("slow_consumer", 4429)


@pytest.mark.parametrize(
    "router_kwargs", [{}, {"backpressure": BackpressureConfig()}], ids=["router_default", "config"]
)
async def test_router_welcome_advertises_coalescing_with_or_without_a_config(
    router_kwargs: dict[str, Any],
) -> None:
    """Every router coalesces (§8.2): one built without the knob runs on the contract budget."""
    rig, sock = _Rig(**router_kwargs), _Socket()
    async with asyncio.timeout(_DEADLINE_S):
        handler, welcome = await rig.open(sock)
        handler.cancel()
        await asyncio.wait({handler})

    assert welcome["p"]["features"] == {
        "replay": True,
        "binary_payloads": True,
        "coalescing": True,
    }


def test_a_router_without_a_config_runs_on_the_contract_budget() -> None:
    assert DEFAULT_BACKPRESSURE == BackpressureConfig()


def test_backpressure_config_defaults_to_the_contract_budget() -> None:
    config = BackpressureConfig()

    assert (config.max_bytes, config.max_frames) == (QUEUE_BYTES, QUEUE_FRAMES)
    assert (config.max_bytes, config.max_frames) == (8_388_608, 2_000)
    assert config.classify_interval_ms == round(CLASSIFY_INTERVAL_S * 1000) == 1_000


def test_backpressure_config_is_frozen() -> None:
    config = BackpressureConfig()

    with pytest.raises(dataclasses.FrozenInstanceError):
        config.max_bytes = 1  # type: ignore[misc]  # asserting that a frozen field refuses it


def test_backpressure_config_from_settings_copies_the_three_budget_settings() -> None:
    settings = Settings(ws_queue_bytes=5_000_000, ws_queue_frames=300, ws_classify_interval_ms=750)

    assert BackpressureConfig.from_settings(settings) == BackpressureConfig(
        max_bytes=5_000_000, max_frames=300, classify_interval_ms=750
    )
