"""E17-X02 AC-08 (#415, threat model `E17-ws-gateway.md` §7): a topic name is data, never a command.
Extends E09-X02's `test_ac_ws_04_*` (JSON only) with path and backslash forms, wildcards of other
dialects, dot-only names, look-alike (Cyrillic, Greek), fullwidth and NFKC-equivalent letters,
zero-width and control characters, 10 KiB names, extra segments and dots in a `param`, under both
subprotocols. A string that is no §13 topic name refuses its whole `sub` (one `err invalid_options`,
no strike, no audit row, and the string is in no log sink); a well-formed one the registry cannot
place is refused alone (the rest of the batch is served). Either way the snapshot source and the
upstream refs get no call for it, and the next valid topic is `s_01`: nothing was admitted. Fake
clock, no sleeps. `test_option_smuggling.py` (AC-09) shares the helpers.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from prometheus_client import REGISTRY

from candleviewer.app import _ws_symbol_known
from candleviewer.audit.models import AuditOutcome, Severity
from tests.security.ws._raw import RawClient, RawWorld, authenticated, delta, raw_connect

Calls = Callable[[], dict[str, int]]
Sender = Callable[[RawClient, Any], dict[str, Any]]  # sends a batch holding an entry; the reply
T, TICKER = "trades.BTCUSDT", "ticker.ETHUSDT"  # the two valid topics every batch holds
#: The stub catalogue: the instruments it lists and their status (`create_app`'s check takes the
#: trading ones).
CATALOGUE = {"BTCUSDT": "trading", "ETHUSDT": "trading", "LUNAUSDT": "closed"}
_EFFECTIVE = {
    T: {"throttle_ms": 100, "encoding": "binary", "coalesce": True},
    TICKER: {"throttle_ms": 250, "encoding": "structured", "coalesce": True},
}


def arm(world: RawWorld) -> Calls:
    """Wire the sink of the per-`sub` audit rows, which `World` leaves out (its gateway sink is
    wired), and spy on every call the snapshot source and the upstream refs get."""
    world.registry.services.audit = world.audit
    refs = world.registry.services.upstream
    spies: dict[str, MagicMock] = {}
    for obj, name in [(world.source, n) for n in ("build", "generation", "continuity")] + [
        (refs, "acquire")
    ]:
        spies[name] = MagicMock(wraps=getattr(obj, name))
        setattr(obj, name, spies[name])
    return lambda: {name: spy.call_count for name, spy in spies.items() if spy.call_count}


def list_instruments(world: RawWorld) -> None:
    """Wire `create_app`'s own symbol check (`_ws_symbol_known`) over a stub catalogue snapshot
    that lists `CATALOGUE` and no other symbol."""
    snapshot = {sym: SimpleNamespace(status=status) for sym, status in CATALOGUE.items()}
    instruments = SimpleNamespace(snapshot=lambda: snapshot)
    ctx: Any = SimpleNamespace(ingestion=SimpleNamespace(instruments=instruments))
    world.registry.services.instrument_known = lambda sym: _ws_symbol_known(ctx, sym)


def counted(name: str) -> float:
    """`name` summed over every label set (the process registry)."""
    return sum(s.value for fam in REGISTRY.collect() for s in fam.samples if s.name == name)


def served(ch: str, n: int, effective: dict[str, Any] | None = None) -> dict[str, Any]:
    """The `sub_ok` result of `ch` as its socket's `n`th subscription: `T`'s or `TICKER`'s
    `effective` unless one is given."""
    effective = effective or _EFFECTIVE[ch]
    return dict(ch=ch, ok=True, sub_id=f"s_{n:02d}", snapshot_pending=True, effective=effective)


def refusal(ch: str, code: str, message: str, field: str | None = None) -> dict[str, Any]:
    error = {"code": code, "message": message, "retryable": False}
    return {"ch": ch, "ok": False, "error": error | ({"field": field} if field else {})}


def sub_ok(world: RawWorld, *results: dict[str, Any]) -> dict[str, Any]:
    return {"t": "sub_ok", "id": "s", "ts": world.clock.wall_ms(), "p": {"results": list(results)}}


def send_batch(c: RawClient, entry: Any) -> dict[str, Any]:
    """`entry` between `T` and `TICKER` in one `sub`; the reply."""
    c.send({"t": "sub", "id": "s", "p": {"topics": [T, entry, {"ch": TICKER}]}})
    return c.recv()


def snapped(c: RawClient) -> list[str]:
    """The channel of every `snap` sent so far, once a `pong` shows the queue is drained."""
    c.send({"t": "ping", "id": "p"})
    c.next_of("pong")
    return [f["ch"] for f in c.seen if f["t"] == "snap"]


def still_serves(world: RawWorld, c: RawClient, calls: Calls) -> None:
    """The socket serves `T` as the first topic it ever admitted (no refused entry took a
    subscription), and the spies see that one: they are live."""
    c.send({"t": "sub", "id": "s", "p": {"topics": [T]}})
    assert c.recv() == sub_ok(world, served(T, 1))
    assert snapped(c) == [T]
    assert calls() == {"build": 1, "generation": 1, "acquire": 1}


def refused_alone(
    world: RawWorld,
    entry: Any,
    code: str,
    message: str,
    field: str | None = None,
    audited: str | None = None,
    send: Sender = send_batch,
) -> None:
    """`entry` in a `sub` between `T` and `TICKER` (sent by `send`) is refused alone: its `sub_ok`
    result carries the documented error, the other two are served (results, snapshots, spies),
    `cv_ws_subscribe_total` counts each result once, no `err` frame is built, and a private
    family's refusal writes the one `ws.subscribe.denied` row, which names `audited`."""
    ch = entry if isinstance(entry, str) else entry["ch"]
    calls = arm(world)
    login = world.login("alice")
    label = "unknown" if code == "unknown_topic" else ch.split(".")[0]
    refused = delta("cv_ws_subscribe_total", topic=label, result=code)
    results, errors = counted("cv_ws_subscribe_total"), counted("cv_ws_errors_total")
    with raw_connect(world) as c:
        authenticated(c, login)
        expected = sub_ok(world, served(T, 1), refusal(ch, code, message, field), served(TICKER, 2))
        assert send(c, entry) == expected
        assert snapped(c) == [T, TICKER]  # the two valid topics' snapshots, none for the refused
        assert (counted("cv_ws_subscribe_total") - results, refused()) == (3, 1)  # each result once
        assert counted("cv_ws_errors_total") == errors  # a result, not an `err` frame
        assert calls() == {"build": 2, "generation": 2, "acquire": 2}  # the two valid topics only
    row = dict(  # §5.2: the family, never the name the client sent
        action="ws.subscribe.denied", actor_label="ws", actor_user_id=login.user_id,
        object_kind="ws_topic", object_id=audited, outcome=AuditOutcome.DENIED,
        severity=Severity.WARNING, reason=code,
    )  # fmt: skip
    assert world.audit.of("ws.subscribe.denied") == ([row] if audited else [])


def cp(*points: int) -> str:
    return "".join(map(chr, points))


def wide(text: str) -> str:
    """`text` in fullwidth forms, which NFKC folds back to ASCII."""
    return "".join(chr(ord(ch) + 0xFEE0) for ch in text)


def leaked(world: RawWorld, c: RawClient, name: str) -> list[str]:
    """The sinks that hold `name` as sent or as they print it (JSON- and `repr`-escaped). Under four
    characters it marks nothing (`.` is in every frame), so it is not looked for."""
    spellings = {name, json.dumps(name)[1:-1], repr(name)[1:-1]}
    return [sink for text in sorted(spellings) if len(text) >= 4 for sink in world.leaks(text, c)]


#: Not §13 topic names (`^[a-z_]+(\.[A-Za-z0-9:_-]+)*$`, at most 120 characters).
SHAPE: dict[str, str] = {
    "slashes": "book/BTCUSDT/50",
    "leading-slash": "/book.BTCUSDT.50",
    "trailing-slash": "book.BTCUSDT.50/",
    "empty-segment": "book.BTCUSDT..50",
    "percent-encoded": "book.%2e%2e.50",
    "trailing-newline": "book.BTCUSDT.50\n",
    "backslashes": "book\\BTCUSDT\\50",
    "wildcard-symbol": "book.*.50",
    "wildcard-depth": "book.BTCUSDT.*",
    "wildcard-family": "*",
    "question-mark": "book.?.50",
    "character-class": "book.[a-z].50",
    "braces": "book.{BTCUSDT,ETHUSDT}.50",
    "percent": "book.%.50",
    "dot": ".",
    "two-dots": "..",
    "three-dots": "...",
    "leading-dot": ".book.BTCUSDT.50",
    "cyrillic-symbol": f"book.{cp(0x412, 0x422, 0x421)}USDT.50",  # look-alikes of B, T, C
    "greek-symbol": f"book.{cp(0x392, 0x3A4, 0x3F9)}USDT.50",  # look-alikes of B, T, C
    "cyrillic-family": f"b{cp(0x43E, 0x43E)}k.BTCUSDT.50",  # look-alikes of o, o
    "fullwidth-symbol": f"book.{wide('BTCUSDT')}.50",
    "fullwidth-family": f"{wide('book')}.BTCUSDT.50",
    "fullwidth-digits": f"book.BTCUSDT.{wide('50')}",
    "fullwidth-full-stop": f"book{cp(0xFF0E)}BTCUSDT{cp(0xFF0E)}50",
    "one-dot-leader": f"book{cp(0x2024)}BTCUSDT{cp(0x2024)}50",
    "superscript-digit": f"book.BTCUSDT.5{cp(0x2070)}",
    "zero-width-space": f"book.BTC{cp(0x200B)}USDT.50",
    "zero-width-joiner": f"bo{cp(0x200D)}ok.BTCUSDT.50",
    "word-joiner": f"book.BTCUSDT.{cp(0x2060)}50",
    "byte-order-mark": f"{cp(0xFEFF)}book.BTCUSDT.50",
    "nul-in-symbol": "book.BTC\x00USDT.50",
    "escape-sequence": "book.\x1b[31mBTCUSDT.50",
    "delete": "book.BTCUSDT.5\x7f0",
    "crlf-injection": "book.BTCUSDT.50\r\nX-Injected: 1",
    "c1-next-line": "book.BTCUSDT.50\x85",
    "10-kib-letters": "a" * 10240,
    "10-kib-after-a-family": "book." + "A" * 10240,
    "10-kib-of-segments": "book" + ".A" * 5120,
    "10-kib-after-a-valid-name": "book.BTCUSDT.50" + ".x" * 5100,
    "121-characters": "book." + "A" * 116,
    "param-empty-segment": "bars.BTCUSDT.renko..5",
    "param-trailing-dot": "bars.BTCUSDT.time.5.",
}
_FORMAT, _SYMBOL = "invalid_topic_format", "unsupported_symbol"
_BOOK, _BARS = "Expected book.{symbol}.{depth}.", "Expected bars.{symbol}.{bar_type}.{param}."
_FOOTPRINT, _PARAM = "Expected footprint.{symbol}.{bar_type}.{param}.", "Bar param is malformed."
_NOT_SUPPORTED, _MACHINE = "Not a supported USDT linear perpetual.", "machines.kill_switch.state.x"
#: Topic names (§13) the registry cannot place: (name, code, message, the `object_id` of the one
#: `ws.subscribe.denied` row a private family's refusal writes, else None).
PLACE: dict[str, tuple[str, str, str, str | None]] = {
    "book-extra-segment": ("book.BTCUSDT.50.extra", _FORMAT, _BOOK, None),
    "book-missing-segment": ("book.BTCUSDT", _FORMAT, _BOOK, None),
    "bars-extra-segment": ("bars.BTCUSDT.time.1.extra", _FORMAT, _BARS, None),
    "param-with-a-dot": ("bars.BTCUSDT.renko.0.5", _FORMAT, _BARS, None),
    "param-with-two-dots": ("bars.BTCUSDT.time.1.5.2", _FORMAT, _BARS, None),
    "footprint-param-with-a-dot": ("footprint.BTCUSDT.renko.0.5", _FORMAT, _FOOTPRINT, None),
    "param-with-a-hyphen": ("bars.BTCUSDT.time.1-5", _FORMAT, _BARS, None),
    "param-of-25-characters": ("bars.BTCUSDT.time." + "5" * 25, _FORMAT, _PARAM, None),
    "hyphen-in-symbol": ("book.BTC-USDT.50", _FORMAT, _BOOK, None),
    "lower-case-symbol": ("book.btcusdt.50", _SYMBOL, _NOT_SUPPORTED, None),
    "unknown-symbol": ("book.NOPEUSDT.50", _SYMBOL, _NOT_SUPPORTED, None),
    "listed-but-closed-symbol": ("book.LUNAUSDT.50", _SYMBOL, _NOT_SUPPORTED, None),
    "unknown-family": ("nope.BTCUSDT", "unknown_topic", "Topic is not in the catalogue.", None),
    "120-characters": ("book." + "A" * 115, _FORMAT, _BOOK, None),
    "orders-extra-segment": ("orders.extra", _FORMAT, "Expected orders.", "orders"),
    "positions-extra-segment": ("positions.BTCUSDT.x", _FORMAT, "Expected positions.", "positions"),
    "system-extra-segment": ("system.extra", _FORMAT, "Expected system.", "system"),
    "machines-extra-segment": (_MACHINE, _FORMAT, "Expected machines.{entity}.state.", _MACHINE),
}


@pytest.mark.parametrize("name", SHAPE.values(), ids=SHAPE.keys())
def test_x02_ac_08_a_string_that_is_no_topic_name_refuses_its_whole_sub(
    world: RawWorld, name: str
) -> None:
    calls = arm(world)
    errors = delta("cv_ws_errors_total", code="invalid_options")
    results = counted("cv_ws_subscribe_total")
    forms = [
        (name, "Not a topic name.", "topics[1]"),
        ({"ch": name}, "Missing or malformed ch.", "topics[1].ch"),
    ]
    with raw_connect(world) as c:
        authenticated(c, world.login("alice"))
        for entry, message, field in forms * 2:  # four refusals: three would be strikes
            error = {"code": "invalid_options", "message": message, "retryable": False}
            frame = {"t": "err", "id": "s", "p": error | {"close": False, "field": field}}
            assert send_batch(c, entry) == frame
        assert (errors(), counted("cv_ws_subscribe_total"), calls()) == (4, results, {})
        still_serves(world, c, calls)
    assert world.audit.of("ws.subscribe.denied") == []
    assert leaked(world, c, name) == []  # in no frame, close reason, audit row, log or metric


@pytest.mark.parametrize("row", PLACE.values(), ids=PLACE.keys())
def test_x02_ac_08_a_name_the_registry_cannot_place_is_refused_alone_and_the_batch_served(
    world: RawWorld, row: tuple[str, str, str, str | None]
) -> None:
    name, code, message, audited = row
    list_instruments(world)  # the symbol check `create_app` wires, over a stub catalogue
    refused_alone(world, name, code, message, audited=audited)
