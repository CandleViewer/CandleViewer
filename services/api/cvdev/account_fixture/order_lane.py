"""#977 (E29-Q03): the order lane served from the account fixture's pack, with a delay model.

The order lane signs and sends its own venue calls from its own thread and event loop (#913 L1d),
through a REST transport the fixture's door builds there (`FixtureDoor.lane_rest_transport`). That
transport refuses every request, as it always has, unless the door's pair is built (the boot guard
passed) **and** `CV_ACCOUNT_FIXTURE_DIR` holds `order_lane.json` naming the pack mode. Then each
request goes through the pair's one `FixtureTransport`, with every guard, signature check, key
state and request-log line it applies to the adapter's own calls, after a delay the model draws.

- **Config** (`order_lane.json`, at most 1 KiB, a regular file never followed through a symlink):
  `{"mode": "pack", "delay_ms": N, "jitter_ms": N, "seed": N, "fill": bool}`; `mode` is required,
  the rest default to 0, 0, 0 and false. Delays are whole milliseconds and `delay_ms + jitter_ms`
  is at most `MAX_DELAY_MS`, so one draw is at most that (10 s); an ack lands at most two draws
  after the request leaves.
  A file off these rules refuses the build, so boot (fail closed); no file keeps the lane refused.
- **Delay model.** Each draw is `delay_ms` plus a whole number from 0 to `jitter_ms` from one
  `random.Random(seed)`, under a lock: the same seed and the same calls give the same delays. A
  request waits one draw before it reaches the pack.
- **Ack frames.** An order create the pack accepts (HTTP 200, `retCode` 0, an order id in its
  result) posts the private stream's frames for it to `AckBoard`, due one more draw after the
  answer on the fixture clock: the order as `New` and, with `fill` and a priced order, a full fill
  (an `execution` row and the order as `Filled`). Each frame is the corpus's recorded push
  (`packages/fixtures/bybit/2026-10-05/ws/private-order.jsonl`, `private-execution.jsonl`) with
  its values set from the create the pack answered: its category, symbol, ids, terms, native SL
  and times. No field is added or removed. A socket authed with the key that signed the create
  sends them (`private_ws`), in order, once due; the board is shared across threads and bounded.

Nothing here imports `candleviewer.secrets` or `candleviewer.audit`.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import stat
import threading
import uuid
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any, Final

import httpx

from cvdev.account_fixture import guards
from cvdev.account_fixture.control import KeyStateError
from cvdev.account_fixture.pack import Pack
from cvdev.account_fixture.transport import ClockInvalid, FixtureTransport, logger

CONFIG_FILE: Final = "order_lane.json"
MAX_CONFIG_BYTES: Final = 1024
MAX_DELAY_MS: Final = 10_000
MAX_SEED: Final = 2**63 - 1
#: The most frames waiting for a socket; one more post is dropped, and logged.
MAX_PENDING: Final = 256
CORPUS_ORDER: Final = "../bybit/2026-10-05/ws/private-order.jsonl"
CORPUS_EXECUTION: Final = "../bybit/2026-10-05/ws/private-execution.jsonl"
CREATE: Final = ("POST", "/v5/order/create")
_KEYS: Final = frozenset({"mode", "delay_ms", "jitter_ms", "seed", "fill"})
_OPEN_FLAGS: Final = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC
_DECIMAL: Final = re.compile(r"[0-9]{1,24}(?:\.[0-9]{1,16})?")
_SYMBOL: Final = re.compile(r"[A-Z0-9]{2,16}USDT")
_TIME_IN_FORCE: Final = frozenset({"GTC", "IOC", "FOK", "PostOnly"})
_TRIGGER_BY: Final = frozenset({"LastPrice", "MarkPrice", "IndexPrice"})
_FILLS: Final = uuid.UUID("00000000-0000-4000-8000-0000000000e0")
_FEE_PLACES: Final = Decimal("0.00000001")
#: The lane's wait: `asyncio.sleep` on a stack, a fake in tests.
Sleep = Callable[[float], Coroutine[Any, Any, None]]


class OrderLaneConfigError(ValueError):
    """`order_lane.json` is off its rules: names the rule, never a value or a path."""


@dataclass(frozen=True, slots=True)
class LaneConfig:
    delay_ms: int = 0
    jitter_ms: int = 0
    seed: int = 0
    fill: bool = False


def _bounded(raw: Mapping[str, object], name: str, high: int) -> int:
    value = raw.get(name, 0)
    if type(value) is not int or not 0 <= value <= high:
        raise OrderLaneConfigError(f"{name} must be a whole number from 0 to {high}")
    return value


def parse_config(text: bytes) -> LaneConfig:
    """The config a file's bytes hold, or `OrderLaneConfigError`."""
    try:
        raw = json.loads(text)
    except (ValueError, RecursionError) as exc:
        raise OrderLaneConfigError("order_lane.json must be a JSON object") from exc
    if not isinstance(raw, dict) or raw.keys() - _KEYS:
        raise OrderLaneConfigError(f"order_lane.json holds only: {', '.join(sorted(_KEYS))}")
    if raw.get("mode") != "pack":
        raise OrderLaneConfigError('order_lane.json must set "mode": "pack"')
    if type(fill := raw.get("fill", False)) is not bool:
        raise OrderLaneConfigError("fill must be true or false")
    delay, jitter = (_bounded(raw, name, MAX_DELAY_MS) for name in ("delay_ms", "jitter_ms"))
    if delay + jitter > MAX_DELAY_MS:
        raise OrderLaneConfigError(f"delay_ms plus jitter_ms must be at most {MAX_DELAY_MS}")
    return LaneConfig(delay, jitter, _bounded(raw, "seed", MAX_SEED), fill)


def read_config(directory: str | os.PathLike[str]) -> LaneConfig | None:
    """`<directory>/order_lane.json`, None when there is none (the lane stays refused). Blocking."""
    try:
        fd = os.open(Path(directory) / CONFIG_FILE, _OPEN_FLAGS)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise OrderLaneConfigError("order_lane.json must be a regular file") from exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OrderLaneConfigError("order_lane.json must be a regular file")
        text = os.read(fd, MAX_CONFIG_BYTES + 1)
    finally:
        os.close(fd)
    if len(text) > MAX_CONFIG_BYTES:
        raise OrderLaneConfigError(f"order_lane.json must fit in {MAX_CONFIG_BYTES} bytes")
    return parse_config(text)


class DelayModel:
    """Fixed plus seeded jitter, in milliseconds; safe from any thread."""

    def __init__(self, config: LaneConfig) -> None:
        self._fixed, self._jitter = config.delay_ms, config.jitter_ms
        # a seeded test delay, never a secret or a token: reproducible on purpose
        self._random = random.Random(config.seed)  # noqa: S311  # nosec B311
        self._lock = threading.Lock()

    def draw_ms(self) -> int:
        with self._lock:
            return self._fixed + self._random.randint(0, self._jitter)


@dataclass(frozen=True, slots=True)
class _Ack:
    key_id: str
    due: datetime
    order: int
    frame: str


class AckBoard:
    """The ack frames waiting for a socket, by pack key, shared by the lane and the serving loop.
    A post wakes the socket that last authed with its key on that socket's loop."""

    def __init__(self, *, max_pending: int = MAX_PENDING) -> None:
        self._lock, self._max = threading.Lock(), max_pending
        self._pending: list[_Ack] = []
        self._posted = 0
        self._watchers: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Event]] = {}

    def post(self, key_id: str, due: datetime, frames: list[str]) -> bool:
        """Queue `frames` for `key_id`, due at `due` on the fixture clock; false if it is full."""
        with self._lock:
            if len(self._pending) + len(frames) > self._max:
                return False
            for frame in frames:
                self._posted += 1
                self._pending.append(_Ack(key_id, due, self._posted, frame))
            watcher = self._watchers.get(key_id)
        if watcher is not None:
            loop, event = watcher
            try:
                loop.call_soon_threadsafe(event.set)
            except RuntimeError:  # the socket's loop is closed: its next read polls instead
                pass
        return True

    def take(self, key_id: str, now: datetime) -> str | None:
        """The key's earliest frame due by `now`, in post order, removed; None if none is due."""
        with self._lock:
            due = [ack for ack in self._pending if ack.key_id == key_id and ack.due <= now]
            if not due:
                return None
            first = min(due, key=lambda ack: (ack.due, ack.order))
            self._pending.remove(first)
            return first.frame

    def next_due_s(self, key_id: str, now: datetime) -> float | None:
        """Seconds to the key's next frame, None if none waits."""
        with self._lock:
            dues = [ack.due for ack in self._pending if ack.key_id == key_id]
        return None if not dues else max(0.0, (min(dues) - now).total_seconds())

    def watch(self, key_id: str, loop: asyncio.AbstractEventLoop, event: asyncio.Event) -> None:
        with self._lock:
            self._watchers[key_id] = (loop, event)

    def __len__(self) -> int:
        with self._lock:
            return len(self._pending)


@dataclass(frozen=True, slots=True)
class Corpus:
    """The recorded order and execution pushes the ack frames are set from."""

    order: dict[str, Any]
    execution: dict[str, Any]


def _recorded(pack: Pack, ref: str) -> dict[str, Any]:
    path = (pack.root / ref).resolve()
    if not path.is_relative_to(pack.root.parent):
        raise ValueError("a corpus frame is outside the fixtures package")
    [line] = path.read_text(encoding="utf-8").splitlines()
    frame = json.loads(line)
    if not (isinstance(frame, dict) and isinstance(frame.get("data"), list) and frame["data"]):
        raise ValueError("a corpus push holds no row")
    return frame


def read_corpus(pack: Pack) -> Corpus:
    """Both recorded pushes, read once at build. Blocking."""
    return Corpus(_recorded(pack, CORPUS_ORDER), _recorded(pack, CORPUS_EXECUTION))


def _text(sent: Mapping[str, object], name: str, rule: re.Pattern[str]) -> str | None:
    value = sent.get(name)
    return value if isinstance(value, str) and rule.fullmatch(value) else None


def _push(recorded: dict[str, Any], row: dict[str, Any], server_ms: int) -> str:
    """The recorded push with its creation time and its one row replaced."""
    [base] = recorded["data"][:1]
    if set(row) - set(base):
        raise ValueError("an ack row names a field its recorded row does not hold")
    push = recorded | {"creationTime": server_ms, "data": [base | row]}
    return json.dumps(push, separators=(",", ":"))


def ack_frames(
    corpus: Corpus,
    sent: Mapping[str, object],
    result: Mapping[str, object],
    *,
    server_ms: int,
    fill: bool,
    seq: int,
) -> list[str]:
    """The pushes for one accepted create: `New`, then with `fill` and a price its fill and
    `Filled`; none for a create whose terms the pushes cannot carry."""
    symbol, qty = _text(sent, "symbol", _SYMBOL), _text(sent, "qty", _DECIMAL)
    price, stop = _text(sent, "price", _DECIMAL), _text(sent, "stopLoss", _DECIMAL)
    side, kind, link = sent.get("side"), sent.get("orderType"), result.get("orderLinkId")
    order_id, tif = result.get("orderId"), sent.get("timeInForce")
    if symbol is None or qty is None or side not in ("Buy", "Sell") or not isinstance(link, str):
        return []
    if kind not in ("Limit", "Market") or not isinstance(order_id, str) or not order_id:
        return []
    if kind == "Limit" and price is None:
        return []
    trigger = sent.get("slTriggerBy")
    ms = str(server_ms)
    new: dict[str, Any] = {
        "category": "linear", "symbol": symbol, "orderId": order_id, "orderLinkId": link,
        "side": side, "orderType": kind, "price": price or "0", "qty": qty,
        "timeInForce": tif if tif in _TIME_IN_FORCE else "GTC" if kind == "Limit" else "IOC",
        "orderStatus": "New", "leavesQty": qty, "leavesValue": "0", "cumExecQty": "0",
        "cumExecValue": "0", "avgPrice": "0", "cumExecFee": "0", "cumFeeDetail": {},
        "reduceOnly": sent.get("reduceOnly") is True, "stopLoss": stop or "",
        "slTriggerBy": trigger if trigger in _TRIGGER_BY else "",
        "tpslMode": "Full" if stop else "", "stopOrderType": "", "positionIdx": 0,
        "createdTime": ms, "updatedTime": ms, "feeCurrency": "",
    }  # fmt: skip
    frames = [_push(corpus.order, new, server_ms)]
    if not fill or price is None:
        return frames
    value = Decimal(price) * Decimal(qty)
    rate = Decimal(str(corpus.execution["data"][0]["feeRate"]))
    fee = str((value * rate).quantize(_FEE_PLACES, rounding=ROUND_DOWN))
    execution: dict[str, Any] = {
        "category": "linear", "symbol": symbol, "orderId": order_id, "orderLinkId": link,
        "side": side, "orderType": kind, "orderPrice": price, "orderQty": qty, "leavesQty": "0",
        "execId": str(uuid.uuid5(_FILLS, f"{order_id}:{link}")), "execPrice": price,
        "execQty": qty, "execValue": str(value), "execFee": fee, "execType": "Trade",
        "execTime": ms, "seq": seq, "closedSize": "0", "execPnl": "0", "markPrice": price,
        "extraFees": [], "isMaker": kind == "Limit", "stopOrderType": "UNKNOWN",
    }  # fmt: skip
    filled = new | {"orderStatus": "Filled", "leavesQty": "0", "cumExecQty": qty}
    filled |= {"cumExecValue": str(value), "avgPrice": price, "cumExecFee": fee}
    fills = [_push(corpus.execution, execution, server_ms), _push(corpus.order, filled, server_ms)]
    return [*frames, *fills]


class OrderLane:
    """The lane's pack mode: the delay, then the pair's transport, then the create's ack frames.
    One per process, built with the pair; each lane transport the door builds serves through it."""

    def __init__(
        self,
        transport: FixtureTransport,
        config: LaneConfig,
        corpus: Corpus,
        *,
        board: AckBoard | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._rest, self._config, self._corpus, self._sleep = transport, config, corpus, sleep
        self._delay, self.board = DelayModel(config), board or AckBoard()
        self._seq_lock, self._seq = threading.Lock(), 0

    async def serve(self, request: httpx.Request) -> httpx.Response:
        await self._sleep(self._delay.draw_ms() / 1000)
        response = await self._rest.handle_async_request(request)
        if (request.method, request.url.path) == CREATE and response.status_code == 200:
            await self._post_acks(request, response)
        return response

    async def _post_acks(self, request: httpx.Request, response: httpx.Response) -> None:
        """The create's frames on the board, if the pack accepted it; a state the stub cannot
        read posts nothing (the answer stands), logged by a fixed code."""
        key = guards.admit(request, self._rest.key_ids).key_id
        try:  # both in memory already: the pack's reply, then a body the pair verified (<= 64 KiB)
            body = json.loads(response.content)
            if not isinstance(body, dict) or body.get("retCode") != 0:
                return
            # nosemgrep: cv-unbounded-read reason=own-body owner=@basiltt review=2027-03-25
            sent = json.loads(request.content)
        except (ValueError, httpx.RequestNotRead):
            return
        result = body.get("result")
        if key is None or not isinstance(sent, dict) or not isinstance(result, dict):
            return
        try:
            now, scenario, started = await asyncio.to_thread(self._rest.select, key)
        except (ClockInvalid, KeyStateError, OSError) as exc:
            logger().error("exchange.account_fixture_lane_ack_skipped", error=type(exc).__name__)
            return
        with self._seq_lock:
            self._seq += 1
            seq = self._seq
        server_ms = scenario.at(now, started=started).clock.server_ms
        frames = ack_frames(
            self._corpus, sent, result, server_ms=server_ms, fill=self._config.fill, seq=seq
        )
        due = now + timedelta(milliseconds=self._delay.draw_ms())
        if frames and not self.board.post(key, due, frames):
            logger().error("exchange.account_fixture_lane_ack_dropped", pending=len(self.board))
