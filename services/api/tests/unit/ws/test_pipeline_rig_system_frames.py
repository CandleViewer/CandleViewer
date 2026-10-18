"""#3198 (#3125 item 7), #3537: the `system` frames the pipeline tests queue are production's.

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

The other rig, `_attached` in `test_pipeline_ladder.py` (a bare pipeline on a `_seq_support.Conn`,
used by four more modules), had a `notify` that framed its `connection_quality` notices by hand. It
now gives the pipeline `push_system` of a bare `_Connection`, as `run_auth` does, so production
frames each notice (`t`, `ch`, `s`, `ts`, `e`, `p`) and cuts it for the principal's role. The same
detector then runs over every module in `tests/unit/ws` (one added later too), by scope: each
function that is not itself a test (`test_*`) is scanned, whatever holds it. That is a helper, a
fixture, a method of a helper class or of a `Test*` class, a function nested in a helper or in a
test (the removed `notify` was one), and module-level code. Only what `ALLOWED` names builds a
`system` frame there, and that stays one `return` of a dict literal with no call in it.

The scan has the guard's limits: it sees a dict literal with that `ch` and a `ch=` argument, not a
channel passed positionally or through a helper's argument. `_d("system", ...)` of
`test_pipeline_outbound.py` and `_frame("d", "system")` of `test_outbound.py` are generic builders
of that kind: they make inputs (a frame pushed into a pipeline or an encoder, which the gateway
does not frame), not notices. That is why the first test of each rig runs the rig instead of
reading it. The scan of the rig's classes also finds `push_system` named; the scan of helpers does
not, as `_attached` names it. A frame a test builds in its own body (an expected value, an input, a
frame to validate) is left alone, and so is one in a lambda or comprehension there.

Where it cannot tell, it reports (it is conservative and fails closed). The guard reads names as
one namespace per module, so a name given the topic anywhere (`ch = "system"`, in a test's body
too) holds it for the whole module, and a generic builder there that frames `{"ch": ch}` is
reported: rename the local. A `Test*` class's attribute or decorator is in no function, so it is
reported as `<module>`. The exemption of a test is by name only: a function called `test_*` is read
as a test wherever it sits, and a method of a `Test*` class that is not called that is scanned.
Like the guard, it is a tripwire for an accident, not a proof.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import math
from pathlib import Path
from typing import Any

import pytest

from candleviewer.ws import gateway, pacing, system_filter
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.gateway import _Connection
from candleviewer.ws.metrics import cv_ws_system_frames_withheld_total
from tests.unit.architecture.test_system_frame_callers import _sites
from tests.unit.ws.test_lifecycle_socket import BASE_MS
from tests.unit.ws.test_pipeline_ladder import _attached
from tests.unit.ws.test_pipeline_outbound import _DEADLINE_S, _counter, _queued, _Rig, _Wire

RIG = Path(__file__).resolve().with_name("test_pipeline_outbound.py")
#: Every module of `tests/unit/ws` (the scan of helpers reads them all, a new one too).
WS_TESTS = RIG.parent
#: The helpers there that build a `system` frame beside production. The scan is exact: one that is
#: not here fails it, and so does one here that builds none. `_frame` wraps a `system_view` result
#: in an envelope for the contract's schema (`validate`) and reaches no connection or pipeline: the
#: scan checks that, as one `return` of a dict literal with no call in it. Tracked in #3637.
ALLOWED = {("test_system_filter.py", "_frame")}
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
#: The `notify` the ladder's rig had before #3537, as it was: it framed the notice itself.
REMOVED_NOTIFY = """
def _attached(levels: int = 2, now: float = 0.0, **config: Any) -> ConnectionPipeline:
    system = itertools.count(1)

    def notify(body: dict[str, Any]) -> None:
        pipe.push({"t": "d", "ch": "system", "s": next(system), "ts": BASE_MS, "e": "j", "p": body})

    pipe = ConnectionPipeline(encoding="cv.v1.json", config=BackpressureConfig(**config))
    pipe.attach(conn.authz, conn.emitter, notify)
    return pipe
"""


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


def _helper_builders(source: str) -> set[str]:
    """The scopes of `source` that build a frame on the system channel, by the guard's detector over
    the whole module, less those whose innermost function is itself a test (`test_*`): a helper, a
    fixture, a method of any class (a `Test*` one too), a function nested in a test or in a helper,
    and `<module>` for module-level code."""
    built, _ = _sites(source)
    return {scope for scope in built if not scope.split(".")[-1].startswith("test_")}


def _returns_only_a_literal(source: str, scope: str) -> bool:
    """Each function `scope` names in `source` is one `return` of a dict literal with no call in
    it, so it hands a frame back and cannot queue it; and there is one."""
    name = scope.split(".")[-1]
    found = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name
    ]
    return bool(found) and all(
        len(node.body) == 1
        and isinstance(node.body[0], ast.Return)
        and isinstance(node.body[0].value, ast.Dict)
        and not any(isinstance(child, ast.Call) for child in ast.walk(node))
        for node in found
    )


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


def test_every_notice_of_the_ladder_rig_is_queued_by_push_system(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_attached` gives its pipeline `push_system` of a bare `_Connection`: each
    `connection_quality` notice it raises is offered to it once, and the frame queued is
    production's, whole: `t`, `ch`, `s` from 1 on this socket, `ts` its wall clock, `e` and `p`,
    the notice as raised, and no other key. A `notify` that framed the notices itself would be
    offered none."""
    offered: list[tuple[_Connection, dict[str, Any]]] = []
    push_system = _Connection.push_system

    def spy(conn: _Connection, body: dict[str, Any]) -> None:
        offered.append((conn, body))
        push_system(conn, body)

    monkeypatch.setattr(_Connection, "push_system", spy)
    budget = 8
    pipe, _, _ = _attached(max_frames=budget, classify_interval_ms=1000)
    for _ in range(math.ceil(budget * pacing.LAGGING_QUEUE_PCT / 100)):  # `lagging`'s share queued
        pipe.push({"t": "pong", "ts": 1, "p": {}})
    frames: list[dict[str, Any]] = []
    for now in (1.0, 2.0):  # the second reads the first's probe, unanswered: `saturated`
        pipe.service(now)
        frames += [f for f in _queued(pipe) if f.get("ch") == "system"]
    bodies = [body for _, body in offered]
    assert [body["class"] for body in bodies] == ["lagging", "saturated"]
    assert frames == [
        {"t": "d", "ch": "system", "s": n, "ts": BASE_MS, "e": "j", "p": body}
        for n, body in enumerate(bodies, 1)
    ]


def test_no_helper_in_the_ws_unit_tests_builds_a_frame_on_the_system_channel() -> None:
    """The guard's detector over every module of `tests/unit/ws`, by scope: no function that is not
    itself a test builds a frame on `system` (a dict literal with that `ch`, or a `ch=` argument),
    be it a helper, a fixture, a method of a `Test*` class, a function nested in a test, or
    module-level code, but what `ALLOWED` names, and that stays one `return` of a dict literal with
    no call in it. A frame reaches a pipeline by `_Connection.push_system` or
    `GatewayHub.broadcast_system` (C-12.4). What else it reports is in the module docstring."""
    found = {
        (path.relative_to(WS_TESTS).as_posix(), scope)
        for path in WS_TESTS.rglob("*.py")
        for scope in _helper_builders(path.read_text(encoding="utf-8"))
    }
    assert found - ALLOWED == set(), "a helper frames a system frame beside push_system"
    assert ALLOWED - found == set(), "an allowed helper builds no frame now: drop it from ALLOWED"
    for module, scope in sorted(ALLOWED):  # the reason `ALLOWED` gives is read, not taken on trust
        source = (WS_TESTS / module).read_text(encoding="utf-8")
        assert _returns_only_a_literal(source, scope), f"{module}::{scope} is more than a literal"


@pytest.mark.parametrize(
    ("source", "found"),
    [
        (REMOVED_NOTIFY, {"notify"}),  # nested in a helper: the ladder's, as it was
        ('def _hand(body):\n    return {"t": "d", "ch": "system", "p": body}', {"_hand"}),
        ('class H:\n    def tell(self):\n        return dict(t="d", ch="system")', {"H.tell"}),
        ('@pytest.fixture\ndef frame():\n    return {"t": "d", "ch": "system"}', {"frame"}),
        ('FRAME = {"t": "d", "ch": "system", "p": {}}', {"<module>"}),
        # inside a test, but not its own body: a function nested in it, a `Test*` class's helpers
        (
            "def test_x(pipe):\n    def notify(body):\n"
            '        pipe.push({"t": "d", "ch": "system", "p": body})',
            {"notify"},
        ),
        (
            "class TestFrames:\n    @pytest.fixture\n    def frame(self):\n"
            '        return {"t": "d", "ch": "system"}\n\n    def _tell(self):\n'
            '        return dict(t="d", ch="system")',
            {"TestFrames.frame", "TestFrames._tell"},
        ),
        # what it leaves alone: a test's own frame, a call of `push_system`, another channel
        ('def test_frame():\n    assert queued == {"t": "d", "ch": "system"}', set()),
        ('class TestFrames:\n    def test_a(self):\n        q = {"t": "d", "ch": "system"}', set()),
        ("def _tell(conn, body):\n    conn.push_system(body)", set()),
        ('def _book(body):\n    return {"t": "d", "ch": "book.BTCUSDT.50", "p": body}', set()),
    ],
    ids=[
        *("removed-notify", "function", "method", "fixture", "module-level"),
        *("nested-in-test", "test-class-helper"),
        *("test", "test-method", "push_system", "other-channel"),
    ],
)
def test_the_scan_finds_a_frame_built_outside_the_tests_and_no_other(
    source: str, found: set[str]
) -> None:
    """So the scan above is not vacuous: it finds the ladder's removed `notify` wherever it sits (in
    a helper, nested in a test, in a method or fixture of a `Test*` class) and a frame built
    anywhere else outside a test's own body, and leaves a test, a helper that calls production
    alone."""
    assert _helper_builders(source) == found


@pytest.mark.parametrize(
    ("source", "literal"),
    [
        ('def _f(body):\n    return {"t": "d", "ch": "system", "p": body}', True),
        ('def _f(body):\n    PIPE.push(body)\n    return {"ch": "system"}', False),
        ('def _f(body):\n    return {"ch": "system", "p": PIPE.push(body)}', False),
        ('def _f(body):\n    frame = {"ch": "system"}\n    return frame', False),
        ('def _g(body):\n    return {"ch": "system"}', False),
    ],
    ids=["literal", "grows-a-call", "call-in-the-literal", "not-a-literal", "no-such-function"],
)
def test_an_allowed_helper_is_read_as_one_return_of_a_dict_literal(
    source: str, literal: bool
) -> None:
    """So the check of `ALLOWED` in the scan is not vacuous: a helper that grows a call or a
    statement, or is gone, is not what its entry says."""
    assert _returns_only_a_literal(source, "_f") is literal
