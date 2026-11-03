"""Fixtures for the E21-X02 market-data abuse suite (#652): the E17-X02 raw rig (`RawWorld`, the
real `/ws` router with real sessions) with the heatmap producer's leases wired (a real
`HeatmapTopic`), `heatmap_depth_500` on, spies on the upstream port and the series store, and a
view-as binding per session, as `create_app` wires `make_ws_router`'s `view_as`."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from functools import partial
from typing import Any
from unittest.mock import patch

import pytest
from structlog.contextvars import merge_contextvars
from structlog.processors import format_exc_info
from structlog.testing import capture_logs

from candleviewer.auth.view_as import ViewAsBinding, ViewAsPhase
from candleviewer.bus.bus import Bus
from candleviewer.orderflow.heatmap import HeatmapSpec, HeatmapTopic
from candleviewer.ws.gateway import make_ws_router
from candleviewer.ws.permissions import ConnectionAuthz
from candleviewer.ws.sequencing import SnapshotBody
from candleviewer.ws.upstream import UpstreamRefs
from candleviewer.ws_wiring import heatmap_part
from tests.contract.ws._harness import OFFERS, reset_wire, use_wire
from tests.security.ws import _raw
from tests.security.ws._raw import Login, RawWorld

LATER = datetime(2100, 1, 1, tzinfo=UTC)


class _Hub:
    def publish(self, ch: str, body: Any = None, **kw: Any) -> int:
        return 0

    def flush_pending(self, match: Any = None) -> int:
        return 0


class Upstream:
    """The upstream port's sink: every reference the gateway opens, by key."""

    def __init__(self) -> None:
        self.opened: list[tuple[Any, ...]] = []

    async def open(self, key: Any) -> None:
        self.opened.append(key)

    async def drop(self, key: Any) -> None:
        return None


class Series:
    """The `bars` series store: every hold a subscription takes."""

    def __init__(self) -> None:
        self.ensured: list[tuple[str, Any]] = []

    async def ensure(self, symbol: str, spec: Any) -> Any:
        self.ensured.append((symbol, spec))
        raise AssertionError("no series is held in this suite")


class QuotaWorld(RawWorld):
    """`RawWorld` whose services lease heatmap specs from a real `HeatmapTopic` (whose engine reads
    no book, so a spec waits for its snapshot), offer depth 500, and spy on the upstream port and
    the series store; a session `view` binds views as its target (§9.6)."""

    def __init__(self, log: pytest.LogCaptureFixture, std: pytest.CaptureFixture[str]) -> None:
        self.views: dict[str, ViewAsBinding] = {}
        router = partial(make_ws_router, view_as=self._view_as)
        with patch.object(_raw, "make_ws_router", router):
            super().__init__(log, std)
        services = self.registry.services
        self.heatmap = HeatmapTopic(
            _Hub(), engine=lambda _s: None, steps=lambda _s: (Decimal("0.1"), Decimal("0.001")),
            part=heatmap_part, body=SnapshotBody, bus=Bus(), env="live", queue_bytes=8_388_608,
            queue_frames=2_000, clock_ms=lambda: 1_700_000_000_000.0,
        )  # fmt: skip
        self.upstream, self.series = Upstream(), Series()
        services.heatmap, services.depth_500 = self.heatmap, True
        services.upstream, services.series = UpstreamRefs(self.upstream), self.series

    async def _view_as(self, session_id: str) -> ViewAsBinding | None:
        return self.views.get(session_id)

    def view(self, viewer: Login, target: Login) -> None:
        """`viewer`'s session views as `target` from its next `auth` (a live context, §9.6)."""
        binding = ViewAsBinding(
            context_id=uuid.uuid4(),
            target_user_id=target.user_id,
            expires_at=LATER,
            phase=ViewAsPhase.LIVE,
        )
        self.views[str(viewer.minted.session_id)] = binding

    def held(self, login: Login) -> tuple[int, int, int]:
        """The user's points, `heatmap.*` subscriptions and distinct specs (the process ledger)."""
        points, heatmaps, specs = self.user_held(login)
        return points, heatmaps, len(specs)

    def user_held(self, login: Login) -> tuple[int, int, dict[HeatmapSpec, int]]:
        """The ledger's own entry for the user: points, `heatmap.*` subscriptions, and the
        subscriptions on each spec; `(0, 0, {})` once it holds nothing."""
        return self.registry.services.user_quota.held(login.user_id)

    def authz(self, login: Login, n: int = 0) -> ConnectionAuthz:
        """The `n`th live socket of `login`'s user, as the registry holds it."""
        authz: ConnectionAuthz = self.registry._conns[login.user_id][n][0]
        return authz


@pytest.fixture(params=list(OFFERS))
def wire(request: pytest.FixtureRequest) -> Iterator[str]:
    """Each test with a `world` runs under both subprotocols, as the E17-X02 suite does (§2.2)."""
    token = use_wire(str(request.param))
    try:
        yield str(request.param)
    finally:
        reset_wire(token)


@pytest.fixture
def world(
    wire: str, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> Iterator[QuotaWorld]:
    caplog.set_level(logging.DEBUG)
    w = QuotaWorld(caplog, capsys)
    with capture_logs(processors=[merge_contextvars, format_exc_info]) as events, w.client:
        w.events = events
        yield w
