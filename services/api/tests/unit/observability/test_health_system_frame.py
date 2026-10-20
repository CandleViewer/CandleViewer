"""E42-T05 (#966 BK-15): the `health` frame is a valid `system` frame (`23-ws-protocol.md` 15.9,
`cv://ws/v1/system.schema.json`), and each snapshot's frame goes to the publisher's direct sinks.
Every frame built here passes the WS tests' own schema harness (`_health_frames.publish`).

`exchange` has, for each component that is deployed, a word of its enum: `public_ws` and
`private_ws` the word of the connection phase the probe reports (`register_public_ws_probe`),
`rest` the word of its state. A component that is not deployed, or missing, leaves its key out,
never a made-up `disconnected`; with no key left there is no `exchange`. `clock_offset_ms` is an
integer in the schema, so it is the ClockGuard's measured offset, read when the frame is built, or
absent: never a null, and never the 0 that `ingestion.clock_offset_ms` answers before a guard is
attached."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from structlog.testing import capture_logs

from candleviewer.health_wiring import HealthSystemPublisher, register_public_ws_probe
from candleviewer.ingestion import connection
from candleviewer.ingestion.connection import (
    PHASE_CLOSED,
    PHASE_CONNECTING,
    PHASE_DEGRADED,
    PHASE_OPEN,
)
from candleviewer.observability.health_probes import (
    ComponentHealth,
    ComponentState,
    HealthRegistry,
    HealthSnapshot,
)
from tests.unit.observability._health_frames import Guard, Probe, publish

T0 = datetime(2026, 10, 20, 3, 0, tzinfo=UTC)
S = ComponentState
#: Every phase `ConnectionManager.state()` reports, and the word the frame gives it: a socket that
#: is backing off, blocked by its budget or closed is not connected; none is a book rebuild, so
#: `resyncing` is never sent.
PHASE_WORDS = {
    PHASE_OPEN: "connected",
    PHASE_CONNECTING: "connecting",
    PHASE_DEGRADED: "disconnected",
    PHASE_CLOSED: "disconnected",
}
#: (state, detail, word): healthy is connected; any other state is the word of the phase its
#: detail names; a detail that names no phase says nothing of the connection (a probe timeout, a
#: probe error), so no key; not deployed is absence, whatever its detail says.
_WS_CASES: list[tuple[ComponentState, str, str | None]] = [
    (S.HEALTHY, PHASE_OPEN, "connected"),
    (S.HEALTHY, "", "connected"),
    (S.DEGRADED, PHASE_CONNECTING, "connecting"),
    (S.DEGRADED, PHASE_DEGRADED, "disconnected"),
    (S.DEGRADED, PHASE_CLOSED, "disconnected"),
    (S.DEGRADED, PHASE_OPEN, "connected"),
    (S.WARNING, PHASE_CONNECTING, "connecting"),
    (S.DOWN, PHASE_CLOSED, "disconnected"),
    (S.DEGRADED, "probe timeout", None),
    (S.WARNING, "", None),
    (S.DOWN, "probe error: RuntimeError", None),
    (S.NOT_DEPLOYED, "ingestion not wired", None),
    (S.NOT_DEPLOYED, PHASE_OPEN, None),
]
_REST_CASES: list[tuple[ComponentState, str | None]] = [
    (S.HEALTHY, "healthy"),
    (S.DEGRADED, "degraded"),
    (S.WARNING, "degraded"),
    (S.DOWN, "down"),
    (S.NOT_DEPLOYED, None),
]


def _of(name: str, state: ComponentState, detail: str = "") -> HealthSnapshot:
    """A snapshot of one component, last healthy at T0."""
    return HealthSnapshot(S.HEALTHY, (ComponentHealth(name, state, 0, detail, T0),), T0)


class _Manager:
    """A `ConnectionManager` that reports `phase`."""

    def __init__(self, phase: str) -> None:
        self.phase = phase

    def state(self) -> str:
        return self.phase


@pytest.mark.parametrize(("phase", "word"), list(PHASE_WORDS.items()))
async def test_the_public_ws_key_is_the_word_of_the_phase_its_probe_reports(
    phase: str, word: str
) -> None:
    registry = HealthRegistry(clock=lambda: T0)
    register_public_ws_probe(registry, lambda: cast(Any, _Manager(phase)))
    frame = await publish(await registry.refresh())
    assert frame["exchange"] == {"public_ws": word}  # and no key for the other two


def test_every_phase_the_connection_manager_defines_is_pinned_here() -> None:
    """A phase it gains later fails here until the frame maps it."""
    defined = {
        value
        for name, value in vars(connection).items()
        if name.startswith("PHASE_") and isinstance(value, str)
    }
    assert defined == set(PHASE_WORDS)


def test_every_state_is_pinned_for_a_connection_and_for_rest() -> None:
    assert {state for state, _, _ in _WS_CASES} == set(ComponentState)
    assert {state for state, _ in _REST_CASES} == set(ComponentState)


@pytest.mark.parametrize(
    ("name", "key"), [("bybit_public_ws", "public_ws"), ("bybit_private_ws", "private_ws")]
)
@pytest.mark.parametrize(("state", "detail", "word"), _WS_CASES)
async def test_a_connection_key_from_each_state_and_detail(
    name: str, key: str, state: ComponentState, detail: str, word: str | None
) -> None:
    frame = await publish(_of(name, state, detail))
    if word is None:
        assert "exchange" not in frame  # honest absence: never a made-up `disconnected`
    else:
        assert frame["exchange"] == {key: word}


@pytest.mark.parametrize(("state", "word"), _REST_CASES)
async def test_rest_is_the_word_of_its_state(state: ComponentState, word: str | None) -> None:
    frame = await publish(_of("bybit_rest", state, "any detail"))
    if word is None:
        assert "exchange" not in frame
    else:
        assert frame["exchange"] == {"rest": word}


async def test_a_component_that_is_missing_or_not_deployed_leaves_its_key_out() -> None:
    snap = HealthSnapshot(
        S.HEALTHY,
        (
            ComponentHealth("bybit_public_ws", S.HEALTHY, 0, PHASE_OPEN, T0),
            ComponentHealth("bybit_private_ws", S.NOT_DEPLOYED, 0, "module not deployed", T0),
        ),  # no `bybit_rest` at all
        T0,
    )
    frame = await publish(snap)
    assert frame["exchange"] == {"public_ws": "connected"}


async def test_no_key_left_means_no_exchange_at_all() -> None:
    nothing = HealthSnapshot(
        S.HEALTHY,
        tuple(
            ComponentHealth(name, S.NOT_DEPLOYED, 0, "module not deployed", T0)
            for name in ("bybit_public_ws", "bybit_private_ws", "bybit_rest")
        ),
        T0,
    )
    assert "exchange" not in await publish(nothing)
    assert "exchange" not in await publish(_of("postgres", S.HEALTHY))


async def test_an_exchange_with_every_key_is_valid() -> None:
    snap = HealthSnapshot(
        S.DEGRADED,
        (
            ComponentHealth("bybit_public_ws", S.HEALTHY, 0, PHASE_OPEN, T0),
            ComponentHealth("bybit_private_ws", S.DEGRADED, 0, PHASE_CONNECTING, T0),
            ComponentHealth("bybit_rest", S.WARNING, 0, "slow", T0),
        ),
        T0,
    )
    frame = await publish(snap)
    assert frame["exchange"] == {
        "public_ws": "connected",
        "private_ws": "connecting",
        "rest": "degraded",
    }


@pytest.mark.parametrize("offset", [0, 12, -340])
async def test_a_measured_offset_is_sent_as_the_integer(offset: int) -> None:
    frame = await publish(_of("postgres", S.HEALTHY), Guard(offset))
    assert frame["clock_offset_ms"] == offset and type(frame["clock_offset_ms"]) is int


@pytest.mark.parametrize(
    "offset", [None, 1.5, True, "3", math.nan], ids=["none", "float", "bool", "str", "nan"]
)
async def test_an_offset_that_is_no_integer_is_left_out(offset: object) -> None:
    frame = await publish(_of("postgres", S.HEALTHY), Guard(offset))
    assert "clock_offset_ms" not in frame  # the schema says integer: a null is not allowed


async def test_without_a_guard_there_is_no_offset_and_no_made_up_zero() -> None:
    assert "clock_offset_ms" not in await publish(_of("postgres", S.HEALTHY))


async def test_the_guard_is_read_each_time_the_frame_is_built() -> None:
    held: dict[str, object] = {"guard": None}
    publisher = HealthSystemPublisher(clock_guard=lambda: cast(Any, held["guard"]))
    sent: list[dict[str, Any]] = []
    publisher.direct_sinks.append(sent.append)
    snap = _of("postgres", S.HEALTHY)
    await publisher(snap)  # no guard yet: it is attached after the app is built
    held["guard"] = Guard(9)
    await publisher(snap)
    held["guard"] = Guard(None)  # attached, nothing measured yet
    await publisher(snap)
    assert [f.get("clock_offset_ms") for f in sent] == [None, 9, None]
    assert ["clock_offset_ms" in f for f in sent] == [False, True, False]


async def test_each_sink_gets_the_frame() -> None:
    publisher = HealthSystemPublisher()
    one: list[dict[str, Any]] = []
    two: list[dict[str, Any]] = []
    publisher.direct_sinks += [one.append, two.append]
    await publisher(_of("postgres", S.HEALTHY))
    assert len(one) == len(two) == 1 and one[0] == two[0]
    await HealthSystemPublisher()(_of("postgres", S.HEALTHY))  # none: nowhere to go, no error


async def test_a_raising_sink_is_logged_and_never_stops_the_other_sinks_or_the_tick() -> None:
    def broken(frame: dict[str, object]) -> None:
        raise RuntimeError("a sink that cannot take the frame")

    publisher = HealthSystemPublisher()
    got: list[dict[str, Any]] = []
    publisher.direct_sinks += [broken, got.append]  # the broken one first
    with capture_logs() as logs:
        await publisher(_of("postgres", S.HEALTHY))  # raises nothing
    assert len(got) == 1
    assert [(e["event"], e["log_level"]) for e in logs] == [
        ("health_wiring: direct sink failed", "error")
    ]
    registry = HealthRegistry(on_snapshot=publisher, clock=lambda: T0)
    registry.register(Probe("postgres", S.HEALTHY))
    with capture_logs():
        await registry.refresh()
        await registry.refresh()  # the failure did not stop the ticker's next tick
    assert len(got) == 3
