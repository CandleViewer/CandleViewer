"""E21-X02 (#652; the model's G-13, HM-I02; AC-HM-07): two users overflow at once with different
topic sets, and each one's slow-consumer `bye` names only its own topics (23 §8.4 step 3: the
hint is ranked from the closing connection's own queue and pacer). Two pipelines in one process,
each attached to its own user's `Conn` over one shared book source (as `test_pipeline_ladder`
attaches one), their `orders` backlogs pushed in turn until both close."""

from __future__ import annotations

import uuid
from typing import Any, cast

from fastapi import WebSocket

from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.gateway import _Connection
from candleviewer.ws.lifecycle import bye_frame
from candleviewer.ws.pipeline import ConnectionPipeline
from tests.unit.ws._seq_support import ACC_A, ACC_B, Book, Conn, Source
from tests.unit.ws.test_lifecycle_socket import BASE_MS
from tests.unit.ws.test_pipeline_ladder import _structured

ALICE, BOB = uuid.UUID(int=0xA11CE), uuid.UUID(int=0xB0B)


class _Socket:
    """One user's attached pipeline, its `Conn`, its book and its `orders` subscription."""

    def __init__(self, source: Source, user: uuid.UUID, account: uuid.UUID, book: str) -> None:
        self.conn = Conn(source, account, user=user)
        self.closes: list[str] = []
        self.pipe = ConnectionPipeline(
            encoding="cv.v1.json",
            config=BackpressureConfig(max_frames=4),
            close=self._close,
            wall_ms=lambda: BASE_MS,
            connection_id=f"ws_{user.hex[-6:]}",
        )
        shell = _Connection(
            cast(WebSocket, None),  # `push_system` queues the frame: no socket, no writer
            encoding="cv.v1.json",
            clock=self.conn.clock,
            wall_ms=lambda: BASE_MS,
            auth_timeout_s=10.0,
        )
        shell.authz, shell.pipeline, shell.system_snapped = self.conn.authz, self.pipe, True
        self.pipe.attach(self.conn.authz, self.conn.emitter, shell.push_system)
        self.conn.emitter.push = self.pipe.push
        self.book = _structured(self.conn, book)  # its snapshot is queued: one frame
        opts = {"exchange_account_ids": [str(account)]}
        _, orders = self.conn.authz.admit({"ch": "orders", "opts": opts})
        assert orders is not None
        orders.snapshot_pending = False
        self.orders = orders

    def _close(self, reason: str, *, bye: dict[str, Any] | None = None) -> None:
        self.closes.append(reason)
        frame = bye or bye_frame(reason, now_ms=BASE_MS)
        self.pipe.close(frame, int(frame["p"]["code"]), flush=reason != "slow_consumer")

    def book_deltas(self, symbol: str, n: int) -> None:
        """`n` book deltas, queued unsent beside the book's snapshot (the writer has not run)."""
        for i in range(n):
            body = {"symbol": symbol, "depth": 50, "bids": [[f"{90 - i}", "1"]], "asks": []}
            self.conn.emitter.delta(self.book, body)

    def order(self) -> None:
        """One `orders` frame, which step 1 never drops."""
        self.conn.emitter.delta(self.orders, {"orders": []})

    def hint(self) -> list[str]:
        assert self.closes == ["slow_consumer"] and self.pipe.terminal is not None
        topics: list[str] = self.pipe.terminal.bye["p"]["hint"]["most_expensive_topics"]
        return topics


async def test_ac_hm_07_two_users_bye_hints_name_only_their_own_topics() -> None:
    source = Source()
    for symbol in ("BTCUSDT", "ETHUSDT"):
        source.books[symbol] = Book(symbol)
        source.books[symbol].apply([[str(100 + i), "1"] for i in range(2)], [])
    alice = _Socket(source, ALICE, ACC_A, "book.BTCUSDT.50")
    bob = _Socket(source, BOB, ACC_B, "book.ETHUSDT.50")
    alice.book_deltas("BTCUSDT", 2)  # with its snapshot, three of the four frames
    bob.book_deltas("ETHUSDT", 2)
    for _ in range(7):  # in turn: both go over budget at once, shed their book, then close
        alice.order()
        bob.order()
    hints = {"alice": alice.hint(), "bob": bob.hint()}
    own = {"alice": {"orders", "book.BTCUSDT.50"}, "bob": {"orders", "book.ETHUSDT.50"}}
    assert all(hints[who] and set(hints[who]) <= own[who] for who in own), hints
    assert "book.BTCUSDT.50" in hints["alice"] and "book.ETHUSDT.50" in hints["bob"], hints
    assert "book.ETHUSDT.50" not in hints["alice"] and "book.BTCUSDT.50" not in hints["bob"]
