"""ADR-0037 S1a, first half: the lane frame codec, its parse order and the marker
(`docs/plan/24-internal-schemas.md` §15.6 Frame, Parse order, Confirmation marker).

Frames are built here independently of the codec, from §15.6's text, so the codec is checked
against the format and not only against itself. Keys are test vectors.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.audit.lane_journal import (
    MAX_FRAME_BYTES,
    ZERO_MAC,
    LaneFrame,
    LaneFrameTooLarge,
    LaneKeyInvalid,
    LaneKeys,
    LaneMarker,
    decode_frame,
    decode_marker,
    encode_frame,
    encode_marker,
    key_id,
    scan,
    segment_name,
)

KEY, PREVIOUS = bytes(range(32)), bytes(range(32, 64))
KEYS = LaneKeys(KEY)
LANE = uuid.UUID(int=0xABCDEF)  # hex letters, so upper-casing it changes it
FRAME_LABEL, MARKER_LABEL = b"cv-audit-lane/v1/frame\n", b"cv-audit-lane/v1/marker\n"
DROP = object()


def sealed(obj: dict[str, Any], label: bytes, key: bytes = KEY) -> tuple[bytes, bytes]:
    body = json.dumps(obj, separators=(",", ":"), sort_keys=True).encode()
    return body, hmac.new(key, label + body, hashlib.sha256).hexdigest().encode()


def frame_of(obj: dict[str, Any], key: bytes = KEY) -> bytes:
    body, mac = sealed(obj, FRAME_LABEL, key)
    return b"%d\n%s\n%s\n" % (len(body), body, mac)


def envelope(**change: object) -> dict[str, Any]:
    base = {"v": 1, "lane": str(LANE), "seq": 1, "prev": ZERO_MAC, "kid": key_id(KEY)}
    obj = base | {"cls": "reserved", "rec": {"action": "auth.logout"}} | change
    return {name: value for name, value in obj.items() if value is not DROP}


GOOD = frame_of(envelope())


def test_lane_frame_round_trips_and_matches_the_format() -> None:
    frame = encode_frame(
        KEYS, lane=LANE, seq=1, prev=ZERO_MAC, cls="reserved", rec=envelope()["rec"]
    )

    assert frame == GOOD
    mac = GOOD[-65:-1].decode()
    want = LaneFrame(LANE, 1, ZERO_MAC, key_id(KEY), "reserved", {"action": "auth.logout"}, mac)
    assert decode_frame(KEYS, frame, lane=LANE) == want


def test_lane_kid_is_one_way_and_the_previous_key_only_verifies() -> None:
    rotated = LaneKeys(PREVIOUS, previous=KEY)
    newer = encode_frame(rotated, lane=LANE, seq=2, prev="a" * 64, cls="shared", rec={})

    assert key_id(KEY) == hmac.new(KEY, b"cv-audit-lane/v1/kid", hashlib.sha256).digest()[:8].hex()
    assert isinstance(decode_frame(rotated, GOOD, lane=LANE), LaneFrame)
    assert rotated.current_kid == key_id(PREVIOUS) != key_id(KEY)
    assert decode_frame(KEYS, newer, lane=LANE) == "hold"


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"v": 2}, "hold"),
        ({"v": 0}, "hold"),
        ({"kid": "0" * 16}, "hold"),
        ({"v": "1"}, "frame_rejected"),
        ({"v": True}, "frame_rejected"),
        ({"v": 1.0}, "frame_rejected"),
        ({"v": DROP}, "frame_rejected"),
        ({"kid": key_id(KEY).upper()}, "frame_rejected"),
        ({"kid": key_id(KEY)[:15]}, "frame_rejected"),
        ({"kid": DROP}, "frame_rejected"),
        ({"seq": True}, "frame_rejected"),
        ({"seq": "1"}, "frame_rejected"),
        ({"seq": 0}, "frame_rejected"),
        ({"prev": "1" * 64}, "frame_rejected"),
        ({"seq": 2, "prev": "A" * 64}, "frame_rejected"),
        ({"cls": "other"}, "frame_rejected"),
        ({"rec": []}, "frame_rejected"),
        ({"lane": str(LANE).upper()}, "frame_rejected"),
        ({"lane": str(uuid.UUID(int=2))}, "frame_rejected"),
        ({"extra": 0}, "frame_rejected"),
    ],
)
def test_lane_parse_steps_3_to_6_are_strict(change: dict[str, object], expected: str) -> None:
    assert decode_frame(KEYS, frame_of(envelope(**change)), lane=LANE) == expected


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (b"auth.logout", b"auth.logouT"),
        (b'"seq":1', b'"seq":7'),
        (b'"prev":"0', b'"prev":"1'),
        (b'"reserved"', b'"reservex"'),
        (str(LANE).encode(), str(LANE)[:-1].encode() + b"0"),
    ],
    ids=["rec", "seq", "prev", "cls", "lane"],
)
def test_lane_rejects_a_changed_byte(old: bytes, new: bytes) -> None:
    tampered = GOOD.replace(old, new)

    assert len(tampered) == len(GOOD) and tampered != GOOD
    assert decode_frame(KEYS, tampered, lane=None) == "frame_rejected"


def framed_body(body: bytes) -> bytes:
    mac = hmac.new(KEY, FRAME_LABEL + body, hashlib.sha256).hexdigest().encode()
    return b"%d\n%s\n%s\n" % (len(body), body, mac)


@pytest.mark.parametrize(
    "data",
    [
        b"+" + GOOD,
        b"0" + GOOD,
        GOOD[:-1],
        GOOD + b"\n",
        GOOD[:-65] + GOOD[-65:-1].upper() + b"\n",
        GOOD[:-65] + b"\xff" + GOOD[-64:],
        b"10000000000\n" + GOOD,
        framed_body(b"[1]"),
        framed_body(b'{"a":"\xc3\xa9"}'),
        framed_body(b'{"a":'),
        framed_body(b"[" * 30000 + b"]" * 30000),
    ],
    ids="sign zero torn trailing upper non_ascii_mac len_11 array non_ascii not_json deep".split(),
)
def test_lane_bytes_that_fail_steps_1_or_2_do_not_parse(data: bytes) -> None:
    assert decode_frame(KEYS, data, lane=LANE) is None


def test_lane_frame_limit_is_the_whole_encoded_frame() -> None:
    pad = MAX_FRAME_BYTES - len(frame_of(envelope(rec={"pad": ""}))) - 2  # `len` gains 2 digits
    largest = frame_of(envelope(rec={"pad": "x" * pad}))
    rec: dict[str, object] = {"pad": "x" * (pad + 1)}

    assert len(largest) == MAX_FRAME_BYTES
    assert isinstance(decode_frame(KEYS, largest, lane=LANE), LaneFrame)
    assert decode_frame(KEYS, frame_of(envelope(rec=rec)), lane=LANE) is None
    with pytest.raises(LaneFrameTooLarge):
        encode_frame(KEYS, lane=LANE, seq=1, prev=ZERO_MAC, cls="reserved", rec=rec)


MARKER = LaneMarker(LANE, (1, 0), 1, ZERO_MAC, True)


def marker_of(**change: object) -> bytes:
    obj = {"v": 1, "lane": str(LANE), "pos": [1, 0], "next_seq": 1, "prev": ZERO_MAC}
    body, mac = sealed(obj | {"anchored": True, "kid": key_id(KEY)} | change, MARKER_LABEL)
    return body + b"\n" + mac + b"\n"


def test_lane_marker_round_trips_and_its_mac_covers_the_state() -> None:
    data = encode_marker(KEYS, MARKER)

    assert data == marker_of()
    assert decode_marker(KEYS, data) == MARKER
    assert decode_marker(LaneKeys(PREVIOUS, previous=KEY), data) == MARKER
    assert decode_marker(KEYS, data.replace(b'"next_seq":1', b'"next_seq":9')) is None


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (marker_of(v=2), "hold"),
        (marker_of(kid="0" * 16), "hold"),
        (marker_of(v=True), None),
        (marker_of(kid=key_id(KEY)[:15]), None),
        (marker_of(pos=[1, -1]), None),
        (marker_of(pos=[True, 0]), None),
        (marker_of(pos=[1]), None),
        (marker_of(next_seq="1"), None),
        (marker_of(anchored=1), None),
        (marker_of(prev="A" * 64), None),
        (marker_of(lane="x"), None),
        (marker_of(extra=0), None),
        (marker_of()[:-1], None),
        (marker_of() + b"\n", None),
        (marker_of()[:-65] + b"\xff" * 64 + b"\n", None),
        (b"[]\n" + marker_of()[-65:], None),
        (b"", None),
    ],
)
def test_lane_marker_holds_on_an_unknown_kid_or_v_and_is_strict(
    data: bytes, expected: str | None
) -> None:
    assert decode_marker(KEYS, data) == expected


def test_lane_logs_and_errors_carry_no_record_or_key() -> None:
    record = "do-not-print-this-record"
    frame = encode_frame(KEYS, lane=LANE, seq=1, prev=ZERO_MAC, cls="shared", rec={"s": record})
    segment = frame + record.encode()  # a hand-over, then a run of bytes that do not parse
    with capture_logs() as logs:
        decode_frame(KEYS, GOOD.replace(b"auth.logout", b"auth.logouT"), lane=LANE)
        decode_marker(KEYS, marker_of(v=2))
        result = scan(KEYS, marker=None, names=[segment_name(1)], read=lambda _: segment)
        with pytest.raises(LaneKeyInvalid) as short:
            LaneKeys(KEY[:31])
        with pytest.raises(LaneFrameTooLarge) as large:
            encode_frame(
                KEYS, lane=LANE, seq=1, prev=ZERO_MAC, cls="shared", rec={"s": record * 3000}
            )
    shown = " ".join(f"{e} {e!r}" for e in (short.value, large.value)) + repr(
        LaneKeys(KEY, PREVIOUS)
    )
    shown += repr((decode_frame(KEYS, frame, lane=LANE), result, *result.units))

    assert logs == [] and len(result.units) == 3  # a marker_lost run, the frame, the record
    assert large.value.reason == "too_large"
    assert key_id(KEY) in shown
    for leak in (record, KEY.hex(), PREVIOUS.hex(), repr(KEY), repr(PREVIOUS)):
        assert leak not in shown


def test_lane_a_malformed_tag_or_kid_is_refused_not_raised() -> None:
    body, mac = sealed(envelope(), FRAME_LABEL)

    assert KEYS.verify(key_id(KEY), FRAME_LABEL, body, mac)
    assert not KEYS.verify(key_id(KEY), FRAME_LABEL, body, "é".encode() * 32)
    assert not KEYS.verify(["unhashable"], FRAME_LABEL, body, mac)
    assert ["unhashable"] not in KEYS
