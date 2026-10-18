"""#3198 (#3125 item 7): the `system` frames the pipeline tests broadcast are production's.

The rig of `test_pipeline_outbound.py` (`_Rig`, `_Wire`, `_Hub`, shared by other modules) used to
have a hub whose `broadcast_system` framed the bodies itself. The transcripts those tests pin held
production's framing only in the shutdown notice, the one `system` frame that production built; the
rest was the rig's copy. `rig.hub` is now a `GatewayHub` that frames nothing:

- every body a test broadcasts reaches the socket through `_Connection.push_system`, the one place
  that frames and queues a `system` frame (SR-188, `23-ws-protocol.md` §15.9);
- the one thing the hub lets past is the per-role filter, only for a kind §15.9 does not list, and
  only while its call runs: after it the production filter is back, and the stand-in takes the
  arguments the filter takes;
- the guard's own detector (`_sites`, from `test_system_frame_callers.py`, which covers
  `candleviewer`) runs over the source of the rig's classes and finds no frame built on the
  channel and no reference to `push_system`.

The scan has the guard's limits: it sees a dict literal with that `ch` and a `ch=` argument, not a
channel passed positionally (the helper `_d("system", ...)`, which pipeline unit tests use to push a
hand-made frame straight into a pipeline, and which the gateway does not frame) or through a
helper's argument, which is why the first test runs the rig instead of reading it. It reads the
rig's classes and not the module: the rig module's own tests and the other modules build `system`
frames for their own reasons (the filter's tests, a stand-in for `push_system` on a fake
connection), so it is not extended over them.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
from pathlib import Path
from typing import Any

import pytest

from candleviewer.ws import gateway, system_filter
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.gateway import _Connection
from candleviewer.ws.metrics import cv_ws_system_frames_withheld_total
from tests.unit.architecture.test_system_frame_callers import _sites
from tests.unit.ws.test_lifecycle_socket import BASE_MS
from tests.unit.ws.test_pipeline_outbound import _DEADLINE_S, _counter, _Rig, _Wire

RIG = Path(__file__).resolve().with_name("test_pipeline_outbound.py")
#: The rig's classes: its hub, the rig itself, and the socket the handler talks to.
RIG_CLASSES = frozenset({"_Hub", "_Rig", "_Wire"})
#: The hub the rig had before #3198, as it was: it framed the bodies itself.
REMOVED_HUB = '''
class _Hub(GatewayHub):
    """These tests feed the writer arbitrary `system` bodies, which SR-188's filter would drop."""

    def broadcast_system(self, body: dict[str, Any]) -> int:
        conns = self._authenticated()
        for conn in conns:
            conn.system_seq += 1
            frame = {"t": "d", "ch": "system", "s": conn.system_seq, "ts": conn.wall_ms(), "e": "j"}
            conn.push(frame | {"p": body})
        return len(conns)
'''


def _rig_classes(source: str) -> str:
    """The text of the rig's classes in `source`, which is what the detector reads. A class that is
    gone fails, so the scan cannot pass on a module the rig moved out of."""
    found = {
        node.name: ast.get_source_segment(source, node) or ""
        for node in ast.parse(source).body
        if isinstance(node, ast.ClassDef) and node.name in RIG_CLASSES
    }
    assert set(found) == RIG_CLASSES, "the rig's classes are not where this test reads them"
    return "\n\n".join(found.values())


@pytest.mark.parametrize("flag_on", [False, True], ids=["flag_off", "flag_on"])
async def test_every_system_frame_of_the_rig_is_queued_by_push_system(
    flag_on: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each body a test broadcasts is offered to its socket through `push_system`, once per body,
    and the frames that arrive are those. A hub that framed the bodies itself, as the rig's once
    did, would call it never."""
    offered: list[tuple[_Connection, dict[str, Any]]] = []
    push_system = _Connection.push_system

    def spy(conn: _Connection, body: dict[str, Any]) -> None:
        offered.append((conn, body))
        push_system(conn, body)

    monkeypatch.setattr(_Connection, "push_system", spy)
    rig, sock = _Rig(BackpressureConfig() if flag_on else None), _Wire()
    bodies = [{"kind": "tick", "n": i} for i in range(3)]
    async with asyncio.timeout(_DEADLINE_S):
        handler, conn = await rig.open(sock)
        assert [rig.hub.broadcast_system(body) for body in bodies] == [1, 1, 1]  # sockets offered
        frames = await sock.next(len(bodies))
        assert sock.sent.empty()
        handler.cancel()
        await asyncio.wait({handler})
    assert offered == [(conn, body) for body in bodies]
    assert [(f["t"], f["ch"], f["p"]) for f in frames] == [("d", "system", b) for b in bodies]


async def test_the_filter_is_open_to_unlisted_kinds_only() -> None:
    """The rig's hub lets a body of a kind that §15.9 does not list reach the socket whole, and
    nothing more. A kind it lists keeps the cut the filter gives the rig's Manager (a health
    component loses its `detail`). The opening lasts as long as the broadcast: after it the
    production filter is back, so the same unlisted body pushed to the socket directly is withheld
    and counted, and nothing is queued."""
    rig, sock = _Rig(), _Wire()
    component = {"name": "ws", "state": "degraded", "last_good_at": 1}
    listed = {"kind": "health", "components": [component | {"detail": "text for the Owner"}]}
    async with asyncio.timeout(_DEADLINE_S):
        handler, conn = await rig.open(sock)
        rig.hub.broadcast_system({"kind": "tick", "n": 1})
        rig.hub.broadcast_system(listed)
        # vars(): mypy does not see an import as an attribute of the module that imports it
        assert vars(gateway)["system_view"] is system_filter.system_view  # undone with the call
        unlisted, health = await sock.next(2)
        withheld = _counter(cv_ws_system_frames_withheld_total, reason="unknown_kind")
        conn.push_system({"kind": "tick", "n": 2})  # not through the hub: the filter is back
        sock.feed({"t": "ping", "id": "fence", "p": {"client_ms": BASE_MS}})
        (pong,) = await sock.next()  # a frame queued before the pong would have come first
        assert pong["t"] == "pong" and sock.sent.empty()
        assert _counter(cv_ws_system_frames_withheld_total, reason="unknown_kind") == withheld + 1
        handler.cancel()
        await asyncio.wait({handler})
    assert unlisted["p"] == {"kind": "tick", "n": 1}
    assert health["p"] == {"kind": "health", "components": [component]}


def test_the_filter_stand_in_takes_the_arguments_system_view_takes() -> None:
    """`push_system` calls what `ws.gateway.system_view` is with the arguments `system_view` takes,
    so the rig's stand-in must take the same ones: a new argument fails here with one clear message,
    before any broadcast raises a `TypeError`, so the stand-in is updated with `system_view`."""
    # Imported here so that the tests above still run, and fail, against a rig that has none.
    from tests.unit.ws.test_pipeline_outbound import _unlisted_kinds_pass

    assert inspect.signature(_unlisted_kinds_pass) == inspect.signature(system_filter.system_view)


def test_the_rig_classes_build_no_frame_on_the_system_channel_and_name_no_push_system() -> None:
    """The guard's detector over the rig's classes (`_Hub`, `_Rig`, `_Wire`): no function in them,
    a nested one included, builds a frame on `system` (a dict literal with that `ch`, or a `ch=`
    argument) or names `push_system`. A frame reaches the socket through
    `GatewayHub.broadcast_system`, as in production (C-12.4). Only those patterns: a channel
    passed positionally, as `_d("system", ...)` does, is not seen."""
    scanned = _rig_classes(RIG.read_text(encoding="utf-8"))
    assert _sites(scanned) == (set(), set()), "a rig class frames a system frame beside push_system"


def test_the_hub_the_rig_once_had_is_what_the_detector_finds() -> None:
    """The detector finds the envelope the rig used to build, in the hub, so the scan above is not
    vacuous."""
    built, _ = _sites(REMOVED_HUB)
    assert built and {scope.split(".")[0] for scope in built} == {"_Hub"}
