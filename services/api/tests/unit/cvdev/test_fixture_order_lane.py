"""#977 (E29-Q03): the order lane served from the account fixture's pack, with a delay model.

Unit rigs build the pair as `wiring._built` does, on the checkout's pack, a request log and key
files under `tmp_path` and a fake fixture clock; the lane's sleep is a fake that records each wait
and moves that clock. The door rigs run the boot guard and serve the lane from another thread
with its own event loop, as the order lane does, while the socket stays on the test's loop. Every
create is signed as M2 signs it with the pack's derived secret; no socket opens, no network.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final

import httpx
import pytest

from candleviewer.account_fixture_wiring import AccountFixtureRefused, account_fixture_guard
from candleviewer.exchange.bybit.private_parse import Push, classify, read_push
from candleviewer.net.read_only_gate import ReadOnlyGate
from candleviewer.settings import Environment
from cvdev.account_fixture import guards, wiring
from cvdev.account_fixture.control import KeyStates
from cvdev.account_fixture.order_lane import (
    CONFIG_FILE,
    MAX_DELAY_MS,
    AckBoard,
    DelayModel,
    LaneConfig,
    OrderLane,
    OrderLaneConfigError,
    ack_frames,
    parse_config,
    read_config,
    read_corpus,
)
from cvdev.account_fixture.private_ws import FixtureSocket, FixtureSockets
from cvdev.account_fixture.requestlog import FILE_NAME, RequestLog
from cvdev.account_fixture.transport import FixtureTransport
from tests._account_fixtures import PACK
from tests.unit.cvdev.test_fixture_wiring import _dev, _door, _one_process, state
from tests.unit.cvdev.test_private_ws import DEMO_WS, _auth
from tests.unit.cvdev.test_transport_guards import NON_FIXTURE_KEY, _key
from tests.unit.cvdev.test_transport_serving import CREATE, KEY_IDS, STOP, _post
from tests.unit.exchange.bybit._trading import NOW_US, account
from tests.unit.exchange.bybit.test_account_fixture_pack import (
    CLOSE_BODY,
    NOW,
    NOW_MS,
    REFERENCE_ORDER,
)

__all__ = ["_one_process", "state"]  # the wiring tests' fixtures, used here too

CORPUS: Final = read_corpus(PACK)
_MS: Final = timedelta(milliseconds=1)
ACKED: Final = {
    "orderId": "00000000-0000-4000-8000-0000000000f1",
    "orderLinkId": "fixture-order-0001",
}


@dataclass
class Rig:
    lane: OrderLane
    transport: FixtureTransport
    sockets: FixtureSockets
    gate: ReadOnlyGate
    directory: Path
    now: list[datetime] = field(default_factory=lambda: [NOW])
    waits: list[float] = field(default_factory=list)

    def lines(self) -> list[dict[str, Any]]:
        text = (self.directory / FILE_NAME).read_text()
        return [json.loads(line) for line in text.splitlines()]

    async def authed(self, scenario: str = "compliant") -> FixtureSocket:
        socket = await self.sockets.connect(DEMO_WS)
        await socket.send(_auth(scenario))
        assert json.loads(await socket.recv(1 << 20))["op"] == "auth"
        return socket


@pytest.fixture
def rig(tmp_path: Path, request: pytest.FixtureRequest) -> Iterator[Rig]:
    config: LaneConfig = getattr(request, "param", LaneConfig())
    now = [NOW]
    waits: list[float] = []

    def clock() -> datetime:
        return now[0]

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        now[0] += timedelta(seconds=seconds)

    with RequestLog(
        tmp_path, process_env=Environment.DEMO, clock=clock, pack_key_ids=KEY_IDS
    ) as log:
        gate = ReadOnlyGate()
        keys = KeyStates(tmp_path, PACK, log=log, clock=clock)
        transport = FixtureTransport(
            PACK, log=log, gate=gate, clock=clock, default="compliant", keys=keys,
            latch=threading.Event(),
        )  # fmt: skip
        lane = OrderLane(transport, config, CORPUS, sleep=sleep)
        sockets = FixtureSockets(transport, sleep=sleep, acks=lane.board)
        yield Rig(lane, transport, sockets, gate, tmp_path, now, waits)


def _create(scenario: str = "compliant", **body: object) -> httpx.Request:
    return _post(scenario, CREATE, {**REFERENCE_ORDER, **body})


def _pushes(frames: list[str]) -> list[tuple[str, dict[str, Any]]]:
    """Each frame as the adapter's private stream reads it: its topic and its one event's row."""
    read: list[tuple[str, dict[str, Any]]] = []
    for frame in frames:
        push = classify(frame)
        assert isinstance(push, Push)
        [event] = read_push(push, account(), now_us=NOW_US)
        [row] = push.rows
        read.append((event.kind, dict(row)))
    return read


def _taken(board: AckBoard, key: str, now: datetime) -> list[str]:
    frames: list[str] = []
    while (frame := board.take(key, now)) is not None:
        frames.append(frame)
    return frames


# --- config -------------------------------------------------------------------------------------


def test_no_config_file_keeps_the_lane_refused(tmp_path: Path) -> None:
    assert read_config(tmp_path) is None


def test_the_config_reads_its_fields_and_defaults() -> None:
    assert parse_config(b'{"mode": "pack"}') == LaneConfig()
    edge = f'{{"mode": "pack", "delay_ms": {MAX_DELAY_MS - 5}, "jitter_ms": 5}}'.encode()
    assert parse_config(edge) == LaneConfig(MAX_DELAY_MS - 5, 5)
    text = b'{"mode":"pack","delay_ms":40,"jitter_ms":10,"seed":7,"fill":true}'
    assert parse_config(text) == LaneConfig(40, 10, 7, True)


@pytest.mark.parametrize(
    "text",
    [
        b"{}",
        b'{"mode": "live"}',
        b"[]",
        b"not json",
        b'{"mode": "pack", "host": "x"}',
        b'{"mode": "pack", "delay_ms": -1}',
        f'{{"mode": "pack", "jitter_ms": {MAX_DELAY_MS + 1}}}'.encode(),
        f'{{"mode": "pack", "delay_ms": {MAX_DELAY_MS}, "jitter_ms": 1}}'.encode(),
        b'{"mode": "pack", "delay_ms": true}',
        b'{"mode": "pack", "delay_ms": 1.5}',
        b'{"mode": "pack", "fill": 1}',
        b'{"mode": "pack", "seed": "7"}',
    ],
)
def test_a_config_off_its_rules_is_refused(text: bytes) -> None:
    with pytest.raises(OrderLaneConfigError):
        parse_config(text)


def test_a_config_file_that_is_a_symlink_or_too_large_is_refused(tmp_path: Path) -> None:
    (tmp_path / "real.json").write_text('{"mode": "pack"}')
    (tmp_path / CONFIG_FILE).symlink_to(tmp_path / "real.json")
    with pytest.raises(OrderLaneConfigError, match="regular file"):
        read_config(tmp_path)
    (tmp_path / CONFIG_FILE).unlink()
    (tmp_path / CONFIG_FILE).write_text('{"mode": "pack", "seed": 1}' + " " * 1024)
    with pytest.raises(OrderLaneConfigError, match="fit"):
        read_config(tmp_path)


# --- delay model --------------------------------------------------------------------------------


def test_the_delay_model_is_fixed_plus_seeded_jitter_and_reproducible() -> None:
    draws = [DelayModel(LaneConfig(20, 30, seed)) for seed in (7, 7, 8)]
    first, again, other = ([model.draw_ms() for _ in range(50)] for model in draws)
    assert first == again != other
    assert all(20 <= ms <= 50 for ms in first) and len(set(first)) > 1
    assert {DelayModel(LaneConfig(15)).draw_ms() for _ in range(5)} == {15}


@pytest.mark.parametrize("rig", [LaneConfig(delay_ms=40, jitter_ms=0)], indirect=True)
async def test_a_request_waits_one_draw_and_its_acks_are_due_one_more(rig: Rig) -> None:
    response = await rig.lane.serve(_create())
    assert (response.status_code, rig.waits) == (200, [0.04])
    accepted = rig.now[0]
    key = _key("compliant")
    assert rig.lane.board.take(key, accepted + 39 * _MS) is None
    assert rig.lane.board.next_due_s(key, accepted) == pytest.approx(0.04)
    assert rig.lane.board.take(key, accepted + 40 * _MS) is not None


# --- pack mode ----------------------------------------------------------------------------------


async def test_an_accepted_create_is_acked_on_the_private_stream_as_new(rig: Rig) -> None:
    socket = await rig.authed()
    response = await rig.lane.serve(_create())
    ack = json.loads(response.content)
    assert (response.status_code, ack["retCode"]) == (200, 0)
    # the script's wallet pushes interleave; the order frame is the lane's
    while json.loads(frame := await socket.recv(1 << 20)).get("topic") != "order":
        pass
    [(kind, row)] = _pushes([frame])
    assert kind == "order"
    sent = REFERENCE_ORDER
    assert (row["orderId"], row["orderLinkId"]) == (ack["result"]["orderId"], sent["orderLinkId"])
    terms = ("symbol", "side", "orderType", "qty", "price", "timeInForce", "stopLoss")
    assert {name: row[name] for name in terms} == {name: sent[name] for name in terms}
    assert (row["category"], row["orderStatus"], row["leavesQty"]) == ("linear", "New", "0.001")
    assert rig.lines()[-1]["order"]["stop_loss"] == "56769.0"  # the native SL, as sent (C-2.6)


@pytest.mark.parametrize("rig", [LaneConfig(fill=True)], indirect=True)
async def test_with_fill_a_priced_create_is_acked_then_filled(rig: Rig) -> None:
    await rig.lane.serve(_create())
    frames = _taken(rig.lane.board, _key("compliant"), rig.now[0])
    pushes = _pushes(frames)
    assert [(kind, row.get("orderStatus")) for kind, row in pushes] == [
        ("order", "New"),
        ("execution", None),
        ("order", "Filled"),
    ]
    fill = pushes[1][1]
    assert (fill["execPrice"], fill["execQty"], fill["seq"]) == ("56799.0", "0.001", 1)
    assert pushes[2][1]["cumExecQty"] == "0.001"


@pytest.mark.parametrize(
    "change",
    [
        {"symbol": "BTC-PERP"},
        {"side": "buy"},
        {"orderType": "Stop"},
        {"price": None},
        {"qty": "1e3"},
    ],
)
def test_a_create_the_pushes_cannot_carry_posts_none(change: dict[str, object]) -> None:
    sent = {k: v for k, v in (REFERENCE_ORDER | change).items() if v is not None}
    assert ack_frames(CORPUS, sent, ACKED, server_ms=NOW_MS, fill=True, seq=1) == []


def test_an_unpriced_market_create_is_acked_new_and_never_filled() -> None:
    sent = {k: v for k, v in REFERENCE_ORDER.items() if k not in ("price", "timeInForce")}
    frames = ack_frames(
        CORPUS, sent | {"orderType": "Market"}, ACKED, server_ms=NOW_MS, fill=True, seq=1
    )
    [(_, row)] = _pushes(frames)
    assert (row["orderType"], row["price"], row["timeInForce"], row["orderStatus"]) == (
        "Market", "0", "IOC", "New"
    )  # fmt: skip


async def test_the_native_sl_trading_stop_is_served_and_logged_without_an_ack(rig: Rig) -> None:
    body = {"category": "linear", "symbol": "BTCUSDT", "stopLoss": "56769.0", "positionIdx": 0}
    response = await rig.lane.serve(_post("compliant", STOP, body))
    assert (response.status_code, json.loads(response.content)["retCode"]) == (200, 0)
    line = rig.lines()[-1]
    sl = line["order"]["stop_loss"]
    assert (line["path"], line["outcome"], sl) == (STOP, "served", "56769.0")
    assert len(rig.lane.board) == 0


async def test_a_rejected_create_is_answered_as_the_pack_says_and_never_acked(rig: Rig) -> None:
    response = await rig.lane.serve(_post("close_rejected", CREATE, CLOSE_BODY))
    assert json.loads(response.content)["retCode"] == 110017
    assert len(rig.lane.board) == 0
    accepted = await rig.lane.serve(_create("close_rejected"))  # not reduce-only: compliant's ack
    assert json.loads(accepted.content)["retCode"] == 0 and len(rig.lane.board) == 1


async def test_the_lane_keeps_every_guard_of_the_pair(rig: Rig) -> None:
    unsigned = httpx.Request("POST", "https://api-demo.bybit.com" + CREATE, content=b"{}")
    with pytest.raises(httpx.ConnectError):
        await rig.lane.serve(unsigned)
    with pytest.raises(httpx.ConnectError):
        await rig.lane.serve(_foreign(_create()))
    assert rig.transport.latched and rig.gate.latched_reason_code == guards.GUARD_REASON_CODE
    assert len(rig.lane.board) == 0


def _foreign(request: httpx.Request) -> httpx.Request:
    """`request` re-keyed with a key the pack does not hold."""
    headers = dict(request.headers) | {guards.KEY_HEADER: NON_FIXTURE_KEY}
    return httpx.Request(request.method, request.url, headers=headers, content=request.content)


def test_the_board_is_bounded() -> None:
    board = AckBoard(max_pending=2)
    assert board.post("k", NOW, ["a", "b"]) and not board.post("k", NOW, ["c"])
    assert _taken(board, "k", NOW) == ["a", "b"]


# --- through the door, from the lane's own thread and loop ---------------------------------------


async def _armed(state: Path, config: str | None) -> tuple[wiring.FixtureDoor, ReadOnlyGate]:
    if config is not None:
        (state / CONFIG_FILE).write_text(config)
    door, gate = _door(_dev(state)), ReadOnlyGate()
    assert await account_fixture_guard(_dev(state), door, gate) is not None
    return door, gate


def _on_the_lane(transport: httpx.AsyncBaseTransport, request: httpx.Request) -> httpx.Response:
    """`request` through `transport` on a new thread running its own event loop."""

    async def send() -> httpx.Response:
        return await transport.handle_async_request(request)

    return asyncio.run(send())


async def test_armed_without_the_pack_mode_the_lane_still_refuses(state: Path) -> None:
    door, _ = await _armed(state, None)
    assert door.armed is not None and door.armed.lane is None
    with pytest.raises(httpx.ConnectError, match=re.escape(wiring.REFUSAL)):
        await asyncio.to_thread(_on_the_lane, door.lane_rest_transport(), _create())


async def test_a_bad_config_refuses_boot(state: Path) -> None:
    with pytest.raises(AccountFixtureRefused, match=wiring.BUILD_REFUSAL):
        await _armed(state, '{"mode": "pack", "delay_ms": -5}')


async def test_the_lane_thread_is_served_and_wakes_the_serving_loops_socket(state: Path) -> None:
    door, _ = await _armed(state, '{"mode": "pack"}')
    socket = await door.private_ws_connect(guards.DEMO_PRIVATE_WS)
    await socket.send(_auth())

    async def order_frame() -> str:
        while json.loads(frame := await socket.recv(1 << 20)).get("topic") != "order":
            pass
        return frame

    reading = asyncio.create_task(order_frame())  # waiting on this loop before the lane posts
    await asyncio.sleep(0)
    lane = door.lane_rest_transport()
    response = await asyncio.to_thread(_on_the_lane, lane, _create())
    assert json.loads(response.content)["retCode"] == 0
    async with asyncio.timeout(5):
        frame = await reading
    assert _pushes([frame])[0][1]["orderLinkId"] == REFERENCE_ORDER["orderLinkId"]
    await lane.aclose()  # the lane's close leaves the pair open
    assert (await door.rest_transport.handle_async_request(_create())).status_code == 200
    log = [json.loads(n) for n in (state / FILE_NAME).read_text().splitlines()]
    assert next(n["outcome"] for n in log if n["path"] == CREATE) == "served"


async def test_a_trip_on_the_lane_latches_the_gate_on_the_serving_loop(state: Path) -> None:
    door, gate = await _armed(state, '{"mode": "pack"}')
    threads: list[int] = []
    gate.subscribe(lambda *_: threads.append(threading.get_ident()))
    with pytest.raises(httpx.ConnectError):
        await asyncio.to_thread(_on_the_lane, door.lane_rest_transport(), _foreign(_create()))
    assert guards.LATCH.is_set()  # every transport refuses at once
    for _ in range(3):
        await asyncio.sleep(0)  # the handed latch runs on this loop
    assert gate.latched_reason_code == guards.GUARD_REASON_CODE
    assert threads == [threading.get_ident()]
