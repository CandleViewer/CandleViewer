"""E08-T04: the public WS skeleton is wired into `create_app()` behind
`ingestion_ws_enabled` (default off, C-4.13). No socket is opened and no
exchange host is resolved here (#3826)."""

from __future__ import annotations

from candleviewer.app import create_app
from candleviewer.ingestion.connection import ConnectionManager
from candleviewer.ingestion.service import WS_FRAME_QUEUE_MAXSIZE
from candleviewer.settings import Settings


def test_flag_default_off() -> None:
    assert Settings().ingestion_ws_enabled is False


def test_flag_off_manager_not_constructed() -> None:
    app = create_app(Settings(ingestion_ws_enabled=False))
    assert app.state.app_context.ingestion.ws is None


def test_flag_on_manager_constructed_and_owned_by_ingestion() -> None:
    app = create_app(Settings(ingestion_ws_enabled=True))
    ing = app.state.app_context.ingestion
    assert isinstance(ing.ws, ConnectionManager)
    assert ing.ws.state() == "closed"  # supervised: started by the module lifecycle only
    assert ing.ws_frames.maxsize == WS_FRAME_QUEUE_MAXSIZE > 0  # bounded (C-2.18)


def test_flag_on_gives_the_book_supervisor_the_apps_machine_feed() -> None:
    """E17-T08: `create_app` hands `wire_public_ws` its one feed: the B14 charts publish (§6.4)."""
    app = create_app(Settings(ingestion_ws_enabled=True))
    assert app.state.app_context.ingestion.books._supervisor._feed is app.state.machine_feed


def test_frame_queue_overflow_drops_and_counts() -> None:
    ing = create_app(Settings(ingestion_ws_enabled=True)).state.app_context.ingestion
    for _ in range(WS_FRAME_QUEUE_MAXSIZE + 3):
        ing.offer_frame("{}")
    assert ing.ws_frames.qsize() == WS_FRAME_QUEUE_MAXSIZE
    assert ing.ws_frames_dropped == 3


async def test_supervisor_lifecycle_starts_and_stops_ws() -> None:
    app = create_app(Settings(ingestion_ws_enabled=True))
    ing = app.state.app_context.ingestion
    calls: list[str] = []

    class _Fake:
        """A supervised component that records its lifecycle and calls no exchange host."""

        def __init__(self, name: str) -> None:
            self.name = name

        def add_listener(self, listener: object) -> None:  # the catalogue's swap hook
            calls.append(f"{self.name}.listen")

        async def start(self) -> None:
            calls.append(f"{self.name}.start")

        async def stop(self, grace_s: float | None = None) -> None:
            calls.append(f"{self.name}.stop")

    # #3826: this tests the supervisor lifecycle, not the startup fetches. At start the real
    # clock guard (and, on the real backend, the catalogue) fetch from the venue's REST host
    # (C-13.5), so both are stubbed together with the socket.
    ing.instruments, ing.clock, ing.ws = _Fake("catalogue"), _Fake("clock"), _Fake("ws")
    await ing.start(app.state.app_context)
    await ing.stop(1.0)
    assert calls == [
        "catalogue.listen",
        "catalogue.start",
        "clock.start",
        "ws.start",
        "ws.stop",
        "clock.stop",
        "catalogue.stop",
    ]
