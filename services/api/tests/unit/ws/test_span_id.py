"""E17-T06 (#571) slice D2: the envelope span id `sp` as the emitter stamps it (23-ws-protocol.md
§3.1, S14), and the room every frame sized against the cap sets aside for it.

The hub stamps one data frame of a subscription in `SAMPLE_EVERY` (`push_data`). That frame, and no
other, carries a fresh `sp` while the emitter has an id source (`CV_TELEMETRY_ENABLED` on): a delta
whose `s` is a multiple of it, or the final chunk of such a snapshot. Frames pass the §13 schemas
(`Conn.push`) unless a sweep turns the check off for speed. The socket side (codecs, both writers,
the span record, a client's `sp`) is `test_span_id_socket.py`; S14 is in `tests/contract/ws/`.
"""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import Callable
from typing import Any

import pytest

from candleviewer.ws.binary import BOOK_DELTA, Frame, FrameEncodeError
from candleviewer.ws.metrics import SAMPLE_EVERY
from candleviewer.ws.sequencing import (
    MAX_OUTBOUND_FRAME_BYTES,
    SequencingHub,
    SnapshotCache,
    new_span_id,
)
from tests.unit.ws._seq_support import ACC_A, Book, Conn, Source
from tests.unit.ws.test_bars_publish import _em, _up, _world

N = SAMPLE_EVERY
CH = "book.BTCUSDT.50"
SPAN = re.compile(r"[0-9a-f]{16}")
BODY = {"symbol": "BTCUSDT", "bids": [["100.0", "1.500"]], "asks": []}
PART = Frame(BOOK_DELTA, records=((0, 1000, 1500), (1, 1010, 250)), price_scale=1, qty_scale=3)
#: As wide as the sizing assumes a field can be (20 digits), and a multiple of `N`: stamped.
WIDE_S = 2**64 - N


class _Stamping(Conn):
    """`Conn` whose emitter stamps as the gateway's does (`push_data`) and draws span ids from
    `span_id` (None: telemetry off). `stamps` holds each stamp; `check=False` skips the schemas."""

    def __init__(
        self,
        source: Source,
        *,
        span_id: Callable[[], str] | None = new_span_id,
        check: bool = True,
        **kw: Any,
    ) -> None:
        self.check = check
        super().__init__(source, ACC_A, **kw)
        self.stamps: list[float] = []
        self.emitter.push_data = self._stamped
        self.emitter.span_id = span_id

    def push(self, frame: dict[str, Any]) -> None:
        if self.check:
            super().push(frame)
        else:
            self.out.append(frame)

    def _stamped(self, frame: dict[str, Any], received: float | None) -> None:
        assert received is not None
        self.stamps.append(received)
        self.push(frame)


def _book_source(levels: int = 40) -> Source:
    src = Source()
    book = Book("BTCUSDT")
    book.apply(
        [[f"{100 - i}.0", "1.000"] for i in range(levels)],
        [[f"{101 + i}.0", "2.000"] for i in range(levels)],
    )
    src.books["BTCUSDT"] = book
    return src


def _spans(frames: list[dict[str, Any]]) -> list[tuple[Any, str]]:
    """(s, sp) of each frame that carries a span id."""
    return [(f["s"], f["sp"]) for f in frames if "sp" in f]


def _size(frame: dict[str, Any]) -> int:
    return len(json.dumps(frame, separators=(",", ":")))


# -- the id -------------------------------------------------------------------------------------


def test_new_span_id_is_16_lowercase_hex_characters_fresh_for_every_draw() -> None:
    ids = [new_span_id() for _ in range(10_000)]
    assert all(SPAN.fullmatch(sp) for sp in ids)
    assert len(set(ids)) == len(ids)


def test_new_span_id_takes_8_bytes_from_secrets_and_draws_again_while_they_are_all_zeros(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draws = iter(["0" * 16, "0" * 16, "7c1e9a04d3b58f62"])
    asked: list[int] = []

    def token_hex(nbytes: int) -> str:
        asked.append(nbytes)
        return next(draws)

    monkeypatch.setattr(secrets, "token_hex", token_hex)
    assert new_span_id() == "7c1e9a04d3b58f62"
    assert asked == [8, 8, 8]


# -- which frames carry it ----------------------------------------------------------------------


@pytest.mark.parametrize("encoding", ["binary", "structured"])
def test_sp_rides_exactly_the_deltas_the_hub_stamps_each_with_its_own_id(encoding: str) -> None:
    conn = _Stamping(_book_source())
    _, sub = conn.sub({"ch": CH, "opts": {"encoding": encoding}})
    conn.take()
    for _ in range(3 * N):  # `s` 2 to 3N + 1
        assert conn.emitter.delta(sub, BODY, part=PART)
    out = conn.take()
    assert [s for s, _ in _spans(out)] == [N, 2 * N, 3 * N] and len(conn.stamps) == 3
    ids = {sp for _, sp in _spans(out)}
    assert all(SPAN.fullmatch(sp) for sp in ids) and len(ids) == 3
    assert {f["e"] for f in out} == {"b64" if encoding == "binary" else "j"}


@pytest.mark.parametrize("encoding", ["binary", "structured"])
def test_only_the_final_chunk_of_a_stamped_snapshot_carries_sp(encoding: str) -> None:
    conn = _Stamping(_book_source(), max_frame_bytes=900)
    _, sub = conn.sub({"ch": CH, "opts": {"encoding": encoding}})
    attach = conn.take()  # `s` 1: not stamped
    assert len(attach) > 1 and _spans(attach) == []
    sub.seq = N - 1
    assert conn.emitter.snapshot(sub, "client_resync")
    out = conn.take()
    assert len(out) > 1 and [f["s"] for f in out] == [None] * (len(out) - 1) + [N]
    assert [i for i, f in enumerate(out) if "sp" in f] == [len(out) - 1]
    assert len(conn.stamps) == 1


def test_no_sp_while_the_emitter_has_no_id_source() -> None:
    """Latency telemetry off: the frames are still stamped for the fan-out series, without `sp`."""
    conn = _Stamping(_book_source(), span_id=None)
    _, sub = conn.sub({"ch": CH, "opts": {"encoding": "binary"}})
    for _ in range(2 * N):
        conn.emitter.delta(sub, BODY, part=PART)
    sub.seq = 3 * N - 1
    assert conn.emitter.snapshot(sub, "client_resync")
    assert len(conn.stamps) == 3 and _spans(conn.take()) == []


def test_each_connection_draws_its_own_sp_for_one_published_delta() -> None:
    hub, src = SequencingHub(), _book_source()
    conns = [_Stamping(src), _Stamping(src)]
    for c in conns:
        hub.register(c.authz, c.emitter)
        c.sub({"ch": CH, "opts": {"encoding": "binary"}})
        c.take()
    for _ in range(N - 1):  # `s` 2 to N on both
        assert hub.publish(CH, BODY, part=PART) == 2
    ((s_a, a),), ((s_b, b),) = (_spans(c.take()) for c in conns)
    assert s_a == s_b == N and a != b


# -- room for it: no frame, `sp` included, passes the cap (§3.1 Room, §3.6) ----------------------


def _widest_snapshot(src: Source, encoding: str, limit: int) -> list[dict[str, Any]]:
    """A stamped snapshot for the widest envelope the sizing allows (20-digit `s`, `previous_seq`,
    `ts` and chunk counter, the longest reason), after an `initial` attach (`s` 1) on its cache.
    None (`[]`) at a limit too small for one record: nothing is sent."""
    cache = SnapshotCache()
    entry = {"ch": CH, "opts": {"encoding": encoding}}
    narrow = _Stamping(src, cache=cache, max_frame_bytes=limit, check=False)
    wide = _Stamping(src, cache=cache, max_frame_bytes=limit, check=False)
    try:
        narrow.sub(entry)
        _, sub = wide.sub(entry)
        wide.take()
        wide.emitter.wall_ms = lambda: 2**64 - 1
        wide.emitter._snap_ids = 10**19  # a 20-digit chunk `id`
        sub.seq = WIDE_S - 1
        assert wide.emitter.snapshot(sub, "instrument_revision") and cache.builds == 1
    except FrameEncodeError:
        return []
    return wide.take()


@pytest.mark.parametrize("encoding", ["binary", "structured"])
def test_no_frame_passes_the_cap_at_the_widest_envelope_sp_included(encoding: str) -> None:
    """Every limit from below one record per chunk to just above the snapshot as one frame, so
    every cut of its 8 records is tried and some final chunk (the one with `id` and `sp`) is
    packed tight."""
    src = _book_source(levels=4)
    (whole,) = map(_size, _widest_snapshot(src, encoding, MAX_OUTBOUND_FRAME_BYTES))
    cuts: set[int] = set()
    for limit in range(whole - 130, whole + 16):
        out = _widest_snapshot(src, encoding, limit)
        cuts.add(len(out))
        if out:
            assert out[-1]["s"] == WIDE_S and "sp" in out[-1]
            assert max(map(_size, out)) <= limit, (limit, whole)
    assert max(cuts) >= 4 and 0 in cuts  # down to one or two records per chunk, and below


async def _stamped_bars(limit: int) -> list[dict[str, Any]]:
    """The deltas of one 12-bar emission to a binary subscriber whose first one is stamped, with
    the widest `s` and `ts`."""
    _, pub, [(conn, sub)] = _world({}, max_frame_bytes=limit)
    out: list[dict[str, Any]] = []
    conn.emitter.push = out.append
    conn.emitter.push_data = lambda frame, _received: out.append(frame)
    conn.emitter.span_id = new_span_id
    conn.emitter.wall_ms = lambda: 2**64 - 1
    sub.seq = WIDE_S - 1
    await pub.emit(_em(*(_up("close", index=i) for i in range(12))))
    return out


async def test_a_stamped_bars_delta_is_cut_with_room_for_its_sp() -> None:
    """The bars publisher sizes its deltas against the cap too: around the limit at which the
    emission is one delta."""
    (whole,) = map(_size, await _stamped_bars(MAX_OUTBOUND_FRAME_BYTES))
    for limit in range(whole - 30, whole + 4):
        out = await _stamped_bars(limit)
        assert out[0]["s"] == WIDE_S and "sp" in out[0]
        assert max(map(_size, out)) <= limit, (limit, whole)
