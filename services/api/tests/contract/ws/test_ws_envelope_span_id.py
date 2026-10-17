"""E17-T06 (#571) slice D1: the envelope span id `sp` (23-ws-protocol.md §3.1, §13.1, S14).

The emitter that draws the id is slice D2's, with the S14 requirement tests. These tests pin the
contract it is built against: the closed §13.1 envelope (bundled in docs/plan/ws-schema.json)
accepts `sp` only on a `snap` or `d` that carries an integer `s` and is not on the `system`
channel (which frames are sampled, and the telemetry gate, are the emitter's S14 tests), and the
two server codecs carry it as a string at the 24 and 20 bytes the document states. No server is
started.
"""

from __future__ import annotations

import json
from typing import Any

import msgpack
import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from candleviewer.ws.codec import encode_server_frame
from candleviewer.ws.gateway import SYSTEM_TOPIC
from candleviewer.ws.sequencing import _dumps
from tests.contract.ws._harness import SCHEMAS
from tests.contract.ws._support import BASE_MS, SAMPLES

ENVELOPE_ID = "cv://ws/v1/envelope.schema.json"
_REGISTRY: Registry[Any] = Registry().with_resources(
    (sid, Resource.from_contents(body)) for sid, body in SCHEMAS.items()
)
ENVELOPE = Draft202012Validator(SCHEMAS[ENVELOPE_ID], registry=_REGISTRY)
PROPS: dict[str, Any] = SCHEMAS[ENVELOPE_ID]["properties"]
#: The most entries a MessagePack fixmap header (1 byte) can count.
FIXMAP_MAX = 15

#: An id of the §3.1 form: 16 lowercase hex characters, not all zeros.
SP = "7c1e9a04d3b58f62"
RS = "0193f2bc-1d40-7000-8000-000000000001"
META = {"reason": "client_resync", "previous_seq": 95, "source": "live"}


def refusals(frame: dict[str, Any]) -> list[str]:
    """What the §13.1 envelope says is wrong with `frame` (empty: it validates)."""
    return sorted(e.message for e in ENVELOPE.iter_errors(frame))


def with_sp(frame: dict[str, Any], value: Any = SP) -> dict[str, Any]:
    return {**frame, "sp": value}


#: Data frames that carry `s`: the only ones `sp` may ride on (§3.1).
BINARY_DELTA = {
    "t": "d",
    "ch": "book.BTCUSDT.50",
    "s": 1024,
    "ts": BASE_MS,
    "e": "b",
    "p": "<CVWB>",
}
STRUCTURED_DELTA = {
    "t": "d",
    "ch": "trades.BTCUSDT",
    "s": 32,
    "ts": BASE_MS,
    "e": "j",
    "p": SAMPLES["trades"][1],
}
REPLAY_DELTA = {**STRUCTURED_DELTA, "rs": RS, "wt": BASE_MS + 5}
SINGLE_SNAP = {
    "t": "snap",
    "ch": "book.BTCUSDT.50",
    "s": 96,
    "ts": BASE_MS,
    "e": "b",
    "meta": META,
    "p": "<CVWB>",
}
FINAL_CHUNK = {**SINGLE_SNAP, "id": "snap-7", "ch": "footprint.BTCUSDT.time.5"}
SAMPLED = [
    pytest.param(BINARY_DELTA, id="binary-delta"),
    pytest.param(STRUCTURED_DELTA, id="structured-delta"),
    pytest.param(REPLAY_DELTA, id="replay-delta"),
    pytest.param(SINGLE_SNAP, id="single-frame-snapshot"),
    pytest.param(FINAL_CHUNK, id="final-chunk-of-a-chunked-snapshot"),
]

#: `system` frames as the gateway builds them (`_Connection.push_system`: `t: "d"`, the system
#: topic, an integer `s`, `e: "j"`; the snapshot is §12.1's example). Each is valid as it is and
#: carries an integer `s`, so only its channel can refuse `sp` (§3.1: never on `system`).
SYS_SNAP_BODY, SYS_DELTA_BODY = SAMPLES["system"]
SYSTEM_FRAMES = [
    pytest.param(
        {"t": "d", "ch": SYSTEM_TOPIC, "s": 32, "ts": BASE_MS, "e": "j", "p": SYS_DELTA_BODY},
        id="system-delta",
    ),
    pytest.param(
        {"t": "snap", "ch": SYSTEM_TOPIC, "s": 1, "ts": BASE_MS, "e": "j", "p": SYS_SNAP_BODY},
        id="system-snapshot",
    ),
]

#: Frames that are valid as they are, and that `sp` must not ride on.
NO_SEQUENCE = [
    pytest.param({**FINAL_CHUNK, "s": None, "p": "<partial chunk>"}, id="intermediate-chunk"),
    pytest.param({k: v for k, v in SINGLE_SNAP.items() if k != "s"}, id="snapshot-without-s"),
]


def test_contract_envelope_stays_closed_and_declares_sp_as_a_16_hex_string() -> None:
    assert SCHEMAS[ENVELOPE_ID]["additionalProperties"] is False
    assert PROPS["sp"]["type"] == "string"
    assert PROPS["sp"]["pattern"] == "^[0-9a-f]{16}$"
    # the exact length too: some validators let `$` match before a final newline
    assert PROPS["sp"]["minLength"] == PROPS["sp"]["maxLength"] == 16
    assert refusals({**BINARY_DELTA, "unknown": 1}) != []  # an undocumented key is still refused


@pytest.mark.parametrize("frame", SAMPLED)
def test_contract_envelope_sp_is_accepted_on_a_data_frame_that_carries_s(
    frame: dict[str, Any],
) -> None:
    assert refusals(frame) == []  # the unsampled frame is as valid as it ever was
    assert refusals(with_sp(frame)) == []


@pytest.mark.parametrize("frame", NO_SEQUENCE)
def test_contract_envelope_sp_is_refused_on_a_frame_without_an_integer_s(
    frame: dict[str, Any],
) -> None:
    assert refusals(frame) == []
    assert refusals(with_sp(frame)) != []


@pytest.mark.parametrize("frame", SYSTEM_FRAMES)
def test_contract_envelope_sp_is_refused_on_a_system_frame(frame: dict[str, Any]) -> None:
    assert refusals(frame) == []
    assert refusals(with_sp(frame)) != []


@pytest.mark.parametrize("t", sorted(set(PROPS["t"]["enum"]) - {"snap", "d"}))
def test_contract_envelope_sp_is_refused_on_every_type_but_snap_and_d(t: str) -> None:
    """`err`, `pong`, `welcome` (which advertises no `sp` feature: the field is optional and
    ignorable, §2.3) and every other control frame, even one that carries an integer `s`: the arm
    names `snap` and `d`, so it is the type that refuses it."""
    control = {"t": t, "ts": BASE_MS, "s": 32}
    assert refusals(control) == []
    assert refusals(with_sp(control)) != []


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param(SP.upper(), id="uppercase"),
        pytest.param(SP[:-1], id="15-characters"),
        pytest.param(SP + "0", id="17-characters"),
        pytest.param(SP + "\n", id="trailing-newline"),
        pytest.param("0" * 16, id="all-zeros"),
        pytest.param("g" + SP[1:], id="not-hex"),
        pytest.param("", id="empty"),
        pytest.param(int(SP, 16), id="integer"),
        pytest.param(None, id="null"),
        pytest.param([SP], id="list"),
    ],
)
def test_contract_envelope_sp_must_be_16_lowercase_hex_characters_never_all_zeros(bad: Any) -> None:
    assert refusals(with_sp(BINARY_DELTA, bad)) != []


def test_contract_envelope_sp_is_a_string_under_both_codecs() -> None:
    """§3.1: a `b64` payload is rewritten to `bin` on MessagePack (§3.2); `sp` never is."""
    frame = with_sp({**BINARY_DELTA, "e": "b64", "p": "AAAA"})
    assert json.loads(_dumps(frame))["sp"] == SP  # the writer's own JSON encoding
    packed = msgpack.unpackb(encode_server_frame(frame), raw=False)
    assert type(packed["sp"]) is str and packed["sp"] == SP
    assert (packed["e"], type(packed["p"])) == ("b", bytes)


def test_contract_envelope_sp_costs_24_bytes_of_json_text_and_20_of_messagepack() -> None:
    """The figures §3.1 states, and the room it sets aside in every frame the server sizes against
    the 4 MiB cap. The frame holds every envelope key, so the 11-entry map is the widest one: it
    stays a fixmap, and `sp` adds a 3-byte key and a 17-byte value and nothing to the map header."""
    every_key = {**FINAL_CHUNK, "rs": RS, "wt": BASE_MS}
    full = with_sp(every_key)
    assert refusals(full) == []
    assert len(full) == len(PROPS) <= FIXMAP_MAX

    def text(frame: dict[str, Any]) -> int:
        return len(_dumps(frame))  # the writer's own JSON encoding

    assert text(full) - text(every_key) == 24
    assert len(encode_server_frame(full)) - len(encode_server_frame(every_key)) == 20
