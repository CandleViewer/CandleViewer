"""E17-T03 (#412): `make_ws_router(backpressure=...)`, `BackpressureConfig` and the welcome.

Until the backpressure wiring lands, with or without a config the router still bounds a
connection's outbound queue at `OUTBOUND_QUEUE_MAX` (1 024 frames) and closes `slow_consumer`.
What changes is `welcome.features.coalescing`, which mirrors the flag (`23-ws-protocol.md` §4.2):
a router built without a config now advertises `false` (it was hard-coded `true`). Nothing
coalesces yet, so the flag stays off until the pipeline is complete.

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
from candleviewer.ws.gateway import OUTBOUND_QUEUE_MAX, GatewayHub, make_ws_router
from candleviewer.ws.outbound import QUEUE_BYTES, QUEUE_FRAMES
from candleviewer.ws.pacing import CLASSIFY_INTERVAL_S
from candleviewer.ws.permissions import ConnectionRegistry
from candleviewer.ws.revocation import RevocationHub
from tests.unit.ws.test_gateway_teardown import _Socket
from tests.unit.ws.test_lifecycle_socket import BASE_MS, ORIGIN, SESSION, USER

_DEADLINE_S = 5.0


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
        return handler, welcome


async def _frames_before_the_close(**router_kwargs: Any) -> tuple[int, dict[str, Any]]:
    """Queue one frame more than the push bound in a single turn, then read to the `bye`:
    (the frames that came before it, the `bye`)."""
    rig, sock = _Rig(**router_kwargs), _Socket()
    async with asyncio.timeout(_DEADLINE_S):
        handler, _ = await rig.open(sock)
        (conn,) = rig.hub.of_user(USER)
        for _ in range(OUTBOUND_QUEUE_MAX + 1):
            conn.push_system({"kind": "tick"})
        frames = 0
        while (frame := await sock.sent.get())["t"] != "bye":
            frames += 1
        await handler
    return frames, frame


@pytest.mark.parametrize(
    "router_kwargs", [{}, {"backpressure": None}], ids=["router_default", "explicit_none"]
)
async def test_router_without_backpressure_keeps_the_1024_frame_close(
    router_kwargs: dict[str, Any],
) -> None:
    """Flag off is today's path: the 1 025th queued frame closes `slow_consumer` / 4429, with no
    drop, no re-snapshot and no allowance for the spec's 2 000 frames (that comes with the
    backpressure wiring). Leaving the knob out is the same path as passing `None`."""
    frames, bye = await _frames_before_the_close(**router_kwargs)

    assert OUTBOUND_QUEUE_MAX == 1024
    assert frames == OUTBOUND_QUEUE_MAX
    assert (bye["p"]["reason"], bye["p"]["code"]) == ("slow_consumer", 4429)


async def test_router_with_a_backpressure_config_is_inert_until_the_pipeline_is_wired() -> None:
    """The config is only threaded through for now: it must not move the bound. The wiring that
    reads it replaces this test with the budgeted pipeline's own."""
    frames, bye = await _frames_before_the_close(backpressure=BackpressureConfig())

    assert frames == OUTBOUND_QUEUE_MAX
    assert (bye["p"]["reason"], bye["p"]["code"]) == ("slow_consumer", 4429)


@pytest.mark.parametrize(
    ("router_kwargs", "coalescing"),
    [({}, False), ({"backpressure": None}, False), ({"backpressure": BackpressureConfig()}, True)],
    ids=["router_default", "explicit_none", "config"],
)
async def test_router_welcome_advertises_coalescing_only_with_a_backpressure_config(
    router_kwargs: dict[str, Any], coalescing: bool
) -> None:
    """A router built without the knob is flag off: every other caller of `make_ws_router`
    (the shared rigs, the chaos harness) gets the flag-off welcome (`coalescing: false`)."""
    rig, sock = _Rig(**router_kwargs), _Socket()
    async with asyncio.timeout(_DEADLINE_S):
        handler, welcome = await rig.open(sock)
        handler.cancel()
        await asyncio.wait({handler})

    assert welcome["p"]["features"] == {
        "replay": True,
        "binary_payloads": True,
        "coalescing": coalescing,
    }


def test_backpressure_config_defaults_to_the_contract_budget() -> None:
    config = BackpressureConfig()

    assert (config.max_bytes, config.max_frames) == (QUEUE_BYTES, QUEUE_FRAMES)
    assert (config.max_bytes, config.max_frames) == (8_388_608, 2_000)
    assert config.classify_interval_ms == round(CLASSIFY_INTERVAL_S * 1000) == 2_000


def test_backpressure_config_is_frozen() -> None:
    config = BackpressureConfig()

    with pytest.raises(dataclasses.FrozenInstanceError):
        config.max_bytes = 1  # type: ignore[misc]  # asserting that a frozen field refuses it


def test_backpressure_config_from_settings_copies_the_three_budget_settings() -> None:
    settings = Settings(ws_queue_bytes=5_000_000, ws_queue_frames=300, ws_classify_interval_ms=750)

    assert BackpressureConfig.from_settings(settings) == BackpressureConfig(
        max_bytes=5_000_000, max_frames=300, classify_interval_ms=750
    )
