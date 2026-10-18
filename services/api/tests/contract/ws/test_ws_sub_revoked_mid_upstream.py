"""#2896 on the wire: while a `sub` waits for its `book` topic's upstream to open, the user loses
`marketdata:read`. The next frames are `permission_change`, `revoked` for `book`, then `sub_ok`
with `book` refused (`forbidden`, no `sub_id`) and the unrevoked `orders` topic accepted, then
`orders`' `snap`: nothing more of `book`, whose upstream ref is released. Both wires (conftest),
the backpressure flag off and on; every frame is validated (§13-§15)."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

import pytest

from candleviewer.auth.generated_permissions import Permission
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.upstream import UpstreamRefs
from tests.contract.ws import _harness as h
from tests.unit.ws._seq_support import ACC_A, USER

BOOK = "book.BTCUSDT.50"


class _GatedSink:
    """The exchange side of the upstream refs: `book`'s open waits until the test sets `go`."""

    def __init__(self) -> None:
        self.entered, self.go = threading.Event(), asyncio.Event()

    async def open(self, key: Any) -> None:
        if key[1] == "book":
            self.entered.set()
            await self.go.wait()

    async def drop(self, key: Any) -> None: ...


@pytest.mark.parametrize("flag", [None, BackpressureConfig()], ids=["flag-off", "flag-on"])
def test_contract_a_topic_revoked_while_its_sub_awaits_the_upstream_is_refused_after_revoked(
    flag: BackpressureConfig | None,
) -> None:
    w, sink = h.World(backpressure=flag), _GatedSink()
    refs = w.registry.services.upstream = UpstreamRefs(sink)
    orders = {"ch": "orders", "opts": {"exchange_account_ids": [str(ACC_A)]}}
    with h.connect(w) as c:
        c.send({"t": "sub", "id": "s", "p": {"topics": [orders, {"ch": BOOK}]}})
        assert sink.entered.wait(5.0)  # `orders` is admitted; `book` waits in its upstream
        w.perms = h.ALL_PERMS - {Permission.MARKETDATA_READ}
        w.call(w.registry.roles_changed, USER)
        w.call(sink.go.set)
        frames = c.drain(4)
        assert [(f["t"], f.get("ch")) for f in frames] == [
            ("permission_change", None),
            ("revoked", BOOK),
            ("sub_ok", None),
            ("snap", "orders"),
        ]
        ok, refused = frames[2]["p"]["results"]
        assert (ok["ch"], ok["ok"], ok["sub_id"]) == ("orders", True, "s_01")
        error = {"code": "forbidden", "message": "Missing permission for this topic."}
        assert refused == {"ch": BOOK, "ok": False, "error": {**error, "retryable": False}}
        assert frames[1]["p"]["sub_id"] == "s_02"
        c.send({"t": "ping", "id": "p"})
        assert c.recv()["t"] == "pong"  # nothing else was queued
        assert w.call(refs.consumers, ("BTCUSDT", "book", ("50",))) == 0
