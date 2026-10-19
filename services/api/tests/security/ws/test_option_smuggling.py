"""E17-X02 AC-09 (#415, threat model `E17-ws-gateway.md` §7): the options of a topic are data too.
Unknown keys, wrong types (of every option kind), NaN-like strings, huge and negative numbers
(floats past a `number` option's bounds, and non-finite ones), 41 `symbols`, 26
`exchange_account_ids` (a cap counts entries, so duplicates count), objects nested to the decoder's
depth cap and extra fields on the topic entry (the model's WS-T06 keys among them) each refuse that
topic alone: `invalid_options` with its `field` (never the client's text), counted in
`cv_ws_subscribe_total`, audited when the topic is a private family's, and the topics around it in
the same `sub` are served (their results, snapshots and upstream refs). Under both subprotocols,
fake clock, no sleeps.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from typing import Any

import pytest

from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode
from candleviewer.ws.topics import FAMILIES
from tests.contract.ws._harness import current_wire
from tests.security.ws import test_topic_injection as inj
from tests.security.ws._raw import RawClient, RawWorld, authenticated, delta, raw_connect
from tests.unit.ws._seq_support import ACC_A, ACC_B, USER

Row = tuple[dict[str, Any], str, str]  # the topic entry sent, then its error's `field` and message
T, L, FOOTPRINT = "trades.BTCUSDT", "liquidations", "footprint.BTCUSDT.time.5"
METRICS, PROFILE = "metrics.BTCUSDT", "profile.BTCUSDT.volume"
NUMBER_OPTIONS = {"imbalance_ratio": FOOTPRINT, "value_area_pct": PROFILE}  # the `number` kind
#: The deepest nest SR-184's 32 levels let through: the frame, `p`, `topics`, the entry and `opts`
#: take five. A literal, so a raised or lowered cap turns a row or the boundary test red.
CAP = 27
ACCOUNTS = [f"00000000-0000-0000-0000-{i:012x}" for i in range(26)]  # ACC_A is the 11th
SYMBOLS = ["BTCUSDT", "ETHUSDT", *(f"S{i:02d}USDT" for i in range(38))]
#: §6.2: a refusal of one of these families writes a `ws.subscribe.denied` row. `system` and
#: `machines` are refused by name, in `test_topic_injection.py`.
PRIVATE = {name for name, family in FAMILIES.items() if family.private} - {"system", "machines"}


def bad(ch: str, **opts: Any) -> Row:
    """`ch` with `opts`, which break the range or type of the one option they name."""
    (field,) = opts
    return {"ch": ch, "opts": opts}, field, f"Option '{field}' is out of range."


def unknown(ch: str, opts: Any, field: str = "opts") -> Row:
    """An option the server does not know: `field` is its name only if that is a known option's."""
    return {"ch": ch, "opts": opts}, field, "Unknown option."


def extra(entry: dict[str, Any]) -> Row:
    """A topic entry that carries a field of its own: refused with `field` `topics`."""
    return entry, "topics", "Unknown topic entry field."


def nest(depth: int, wrap: Callable[[Any], Any]) -> Any:
    value: Any = 1
    for _ in range(depth):
        value = wrap(value)
    return value


def obj(value: Any) -> dict[str, Any]:
    return {"a": value}


OPTIONS: dict[str, Row] = {
    "unknown-key": unknown(T, {"nope": 1}),
    "option-of-another-family": unknown(T, {"depth": 50}, "depth"),
    "key-of-5000-characters": unknown(T, {"k" * 5000: 1}),
    "key-of-look-alikes": unknown(T, {inj.cp(0x430, 0x431): 1}),
    "proto-key": unknown(T, {"__proto__": {"admin": True}}),
    "token-key": unknown(T, {"access_token": "t"}),
    "params-key": unknown(T, {"params": {"a": 1}}),
    "opts-a-string": ({"ch": T, "opts": "x"}, "opts", "opts must be an object."),
    "opts-a-list": ({"ch": T, "opts": [1]}, "opts", "opts must be an object."),
    "throttle_ms-a-string": bad(T, throttle_ms="100"),
    "throttle_ms-a-float": bad(T, throttle_ms=100.5),
    "throttle_ms-a-bool": bad(T, throttle_ms=True),
    "throttle_ms-null": bad(T, throttle_ms=None),
    "throttle_ms-a-list": bad(T, throttle_ms=[100]),
    "coalesce-a-string": bad(T, coalesce="true"),
    "coalesce-an-int": bad(T, coalesce=1),
    "encoding-a-list": bad(T, encoding=["binary"]),
    "encoding-an-object": bad(T, encoding={"a": 1}),
    "bar_type-a-list": bad(METRICS, bar_type=["time"]),
    "metrics-an-int": bad(METRICS, metrics=[1]),
    "metrics-an-empty-string": bad(METRICS, metrics=[""]),
    "metrics-a-string-of-65-characters": bad(METRICS, metrics=["x" * 65]),
    "min-size-a-number": bad(T, min_size=1),
    "throttle_ms-nan": bad(T, throttle_ms="NaN"),
    "throttle_ms-infinity": bad(T, throttle_ms="Infinity"),
    "throttle_ms-minus-infinity": bad(T, throttle_ms="-Infinity"),
    "throttle_ms-1e999": bad(T, throttle_ms="1e999"),
    "min-size-nan": bad(T, min_size="NaN"),
    "min-size-infinity": bad(T, min_size="Infinity"),
    "min-size-exponent": bad(T, min_size="1e5"),
    "imbalance-ratio-nan": bad(FOOTPRINT, imbalance_ratio="NaN"),
    "throttle_ms-negative": bad(T, throttle_ms=-1),
    "throttle_ms-minus-2-63": bad(T, throttle_ms=-(2**63)),
    "throttle_ms-60001": bad(T, throttle_ms=60_001),
    "throttle_ms-2-63": bad(T, throttle_ms=2**63),
    "throttle_ms-2-64-minus-1": bad(T, throttle_ms=2**64 - 1),
    "throttle_ms-1e308": bad(T, throttle_ms=1e308),
    "history-2-63": bad("bars.BTCUSDT.time.1", history=2**63),
    "from-seq-negative": bad(T, from_seq=-1),
    "imbalance-ratio-negative": bad(FOOTPRINT, imbalance_ratio=-3),
    "imbalance-ratio-20-5": bad(FOOTPRINT, imbalance_ratio=20.5),
    "imbalance-ratio-1e308": bad(FOOTPRINT, imbalance_ratio=1e308),
    "value-area-pct-49-5": bad(PROFILE, value_area_pct=49.5),
    "value-area-pct-95-5": bad(PROFILE, value_area_pct=95.5),
    "41-symbols": bad(L, symbols=[f"S{i:02d}USDT" for i in range(41)]),
    "41-duplicate-symbols": bad(L, symbols=["BTCUSDT"] * 41),
    "symbol-of-look-alikes": bad(L, symbols=[inj.cp(0x412, 0x422, 0x421) + "USDT"]),
    "symbol-fullwidth": bad(L, symbols=[inj.wide("BTCUSDT")]),
    "symbol-trailing-newline": bad(L, symbols=["BTCUSDT\n"]),
    "symbols-a-string": bad(L, symbols="BTCUSDT"),
    "symbols-empty": bad(L, symbols=[]),
    "41-symbols-on-the-recorder": bad("recorder", symbols=["BTCUSDT"] * 41),
    "26-accounts": bad("orders", exchange_account_ids=ACCOUNTS),
    "26-duplicate-accounts": bad("orders", exchange_account_ids=[str(ACC_A)] * 26),
    "accounts-empty": bad("orders", exchange_account_ids=[]),
    "account-not-a-uuid": bad("orders", exchange_account_ids=["x"]),
    "account-a-number": bad("orders", exchange_account_ids=[1]),
    "accounts-nested-list": bad("orders", exchange_account_ids=[[str(ACC_A)]]),
    "param-with-a-dot": bad(METRICS, param="0.5"),
    "param-of-25-characters": bad(METRICS, param="a" * 25),
    "object-at-the-depth-cap": bad(T, throttle_ms=nest(CAP, obj)),
    "list-at-the-depth-cap": bad(T, throttle_ms=nest(CAP, lambda v: [v])),
    "object-under-an-unknown-key": unknown(T, {"z": nest(CAP, obj)}),
    "extra-field-on-the-entry": extra({"ch": T, "x": 1}),
    "token-on-the-entry": extra({"ch": T, "access_token": "t"}),
    "accounts-on-the-entry": extra({"ch": "orders", "exchange_account_ids": [str(ACC_B)]}),
    "user-on-the-entry": extra({"ch": T, "user": str(USER)}),
}


def overflow(c: RawClient, entry: Any) -> dict[str, Any]:
    """`inj.send_batch` with the entry's infinity written `1e999`, JSON text only."""
    frame = {"t": "sub", "id": "s", "p": {"topics": [inj.T, entry, {"ch": inj.TICKER}]}}
    c.send_text(json.dumps(frame).replace("Infinity", "1e999"))
    return c.recv()


#: Numbers no finite float is, with the sender that writes each in the JSON text: `json.dumps`
#: writes `NaN`, `Infinity` and `-Infinity`; `overflow` writes a literal `json.loads` reads as one
#: (JSON text only: MessagePack has no such spelling, so there that case is `infinity` again).
NON_FINITE: dict[str, tuple[float, inj.Sender]] = {
    "nan": (math.nan, inj.send_batch),
    "infinity": (math.inf, inj.send_batch),
    "minus-infinity": (-math.inf, inj.send_batch),
    "1e999": (math.inf, overflow),
}
#: The value just inside each limit, with the `effective` its result reports: served, whole.
INSIDE: dict[str, tuple[Any, dict[str, Any]]] = {
    "25-accounts": (  # §6.2: narrowed to the one account the caller may view, ACC_A
        {"ch": "orders", "opts": {"exchange_account_ids": ACCOUNTS[:25]}},
        {
            "throttle_ms": 0,
            "encoding": "structured",
            "coalesce": False,
            "exchange_account_ids": [str(ACC_A)],
        },
    ),
    "40-symbols": (
        {"ch": L, "opts": {"symbols": SYMBOLS}},
        {"symbols": SYMBOLS, "throttle_ms": 500, "encoding": "structured", "coalesce": True},
    ),
    # The name grammar takes a colon where it refuses a dot. The rig wires no bar service, so the
    # spec check of `renko` (a whole number, not `0:5`) does not run: this pins the grammar only.
    "param-with-a-colon-passes-the-name-check": (
        "bars.BTCUSDT.renko.0:5",
        {
            "throttle_ms": 250,
            "encoding": "binary",
            "coalesce": True,
            "history": 500,
            "include_delta": False,
        },
    ),
}


def refused_as_malformed(world: RawWorld, entry: Any) -> None:
    """`entry` makes its whole frame malformed, so no option is read: one `err frame_malformed` (the
    catalogue's title, no `id`) and one strike of three, no producer call, and the socket serves."""
    calls = inj.arm(world)
    malformed = delta("cv_ws_errors_total", code="frame_malformed")
    with raw_connect(world) as c:
        authenticated(c, world.login("alice"))
        error = {"code": "frame_malformed", "retryable": False, "close": False}
        title = ERROR_META[ErrorCode.FRAME_MALFORMED].title
        assert inj.send_batch(c, entry) == {"t": "err", "p": error | {"message": title}}
        assert (malformed(), calls()) == (1, {})  # one strike of three, and no option read
        inj.still_serves(world, c, calls)


@pytest.mark.parametrize("row", OPTIONS.values(), ids=OPTIONS.keys())
def test_x02_ac_09_a_smuggled_option_refuses_its_topic_alone_and_the_batch_is_served(
    world: RawWorld, row: Row
) -> None:
    entry, field, message = row
    family = entry["ch"].split(".")[0]
    inj.refused_alone(
        world, entry, "invalid_options", message, field, family if family in PRIVATE else None
    )


@pytest.mark.parametrize("option", NUMBER_OPTIONS)
@pytest.mark.parametrize("number", NON_FINITE.values(), ids=NON_FINITE.keys())
def test_x02_ac_09_a_non_finite_number_is_refused_as_each_wire_reads_it(
    world: RawWorld, number: tuple[float, inj.Sender], option: str
) -> None:
    value, send = number
    entry, field, message = bad(NUMBER_OPTIONS[option], **{option: value})
    if current_wire() == "json":  # `json.loads` reads the literal: the option check refuses it
        inj.refused_alone(world, entry, "invalid_options", message, field, send=send)
    else:  # MessagePack's decoder (SR-185) refuses a float NaN or infinity anywhere in a frame
        refused_as_malformed(world, entry)


def test_x02_ac_09_one_level_past_the_depth_cap_is_a_malformed_frame_not_an_option_error(
    world: RawWorld,
) -> None:
    refused_as_malformed(world, {"ch": T, "opts": {"throttle_ms": nest(CAP + 1, obj)}})


@pytest.mark.parametrize("row", INSIDE.values(), ids=INSIDE.keys())
def test_x02_ac_08_09_the_limits_are_exact_the_value_just_inside_is_served(
    world: RawWorld, row: tuple[Any, dict[str, Any]]
) -> None:
    entry, effective = row
    ch = entry if isinstance(entry, str) else entry["ch"]
    results = [inj.served(inj.T, 1), inj.served(ch, 2, effective), inj.served(inj.TICKER, 3)]
    with raw_connect(world) as c:
        authenticated(c, world.login("alice"))
        assert inj.send_batch(c, entry) == inj.sub_ok(world, *results)
        assert inj.snapped(c) == [inj.T, ch, inj.TICKER]
