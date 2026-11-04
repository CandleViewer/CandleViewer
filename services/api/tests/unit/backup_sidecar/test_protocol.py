"""#3319 B1b (24 §15.8): the sidecar's frame codec refuses everything outside the v1 shapes, and the
age format helpers (the recipient fingerprint, the header check) read no key."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cvbackup import age_format, protocol
from tests.unit.backup_sidecar._sidecar import age_bytes, recipient

RID = "6f1c2b0e-3d4a-4e5f-8a9b-0c1d2e3f4a5b"
BID = str(uuid.UUID(int=8, version=4))
LOC = "/srv/cv/backups/pg_dump/4b7c1e2a-9f3d-4c5e-8a6b-7d8e9f0a1b2c.age"


def _body(**changes: Any) -> bytes:
    value: dict[str, Any] = {"v": 1, "id": RID, "op": "verify", "deadline_s": 60,
                             "args": {"backup_id": BID, "location": LOC}}  # fmt: skip
    value.update(changes)
    return protocol.dumps(value)


def _code(body: bytes) -> str:
    with pytest.raises(protocol.ProtocolError) as refused:
        protocol.parse_request(body)
    return refused.value.code


def test_protocol_a_well_formed_request_parses() -> None:
    request = protocol.parse_request(_body())
    assert (request.id, request.op, request.deadline_s) == (RID, "verify", 60)
    assert dict(request.args) == {"backup_id": BID, "location": LOC}


@pytest.mark.parametrize(
    "header", [b"", b"0", b"012", b"123456", b"-1", b"+5", b"16385", b"1e3", b"\xd9\xa1"]
)
def test_protocol_a_header_outside_1_to_5_digits_up_to_max_frame_is_bad_frame(
    header: bytes,
) -> None:
    with pytest.raises(protocol.ProtocolError, match="bad_frame"):
        protocol.parse_length(header)


def test_protocol_a_frame_over_max_frame_is_refused() -> None:
    assert protocol.parse_length(b"16384") == protocol.MAX_FRAME
    with pytest.raises(ValueError, match="MAX_FRAME"):
        protocol.frame({"pad": "x" * protocol.MAX_FRAME})
    assert _code(b" " * (protocol.MAX_FRAME + 1)) == "bad_frame"


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(_body().replace(b",", b", "), id="whitespace"),
        pytest.param(json.dumps({"v": 1, "id": RID}).encode(), id="unsorted-and-spaced"),
        pytest.param(_body().replace(b'"v":1', b'"v":1,"v":1'), id="duplicate"),
        pytest.param(_body().replace(b"pg_dump", "pg_düm".encode()), id="non-ascii"),
        pytest.param(_body().replace(b"pg_dump", b"pg\\u005fdump"), id="escaped-ascii"),
        pytest.param(_body().replace(b"/srv", b"\\/srv"), id="escaped-slash"),
        pytest.param(_body().replace(b'"deadline_s":60', b'"deadline_s":60.0'), id="float"),
        pytest.param(_body().replace(b'"deadline_s":60', b'"deadline_s":6e1'), id="exponent"),
        pytest.param(_body().replace(b'"deadline_s":60', b'"deadline_s":NaN'), id="nan"),
        pytest.param(b"", id="empty"),
        pytest.param(b"{", id="truncated"),
    ],
)
def test_protocol_noncanonical_json_is_refused_bad_frame(body: bytes) -> None:
    assert _code(body) == "bad_frame"


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"v": 2}, "unsupported_version"),
        ({"v": "1"}, "unsupported_version"),
        ({"v": True}, "unsupported_version"),
        ({"x": 1}, "bad_request"),
        ({"op": "purge"}, "bad_request"),
        ({"id": RID.upper()}, "bad_request"),
        ({"deadline_s": 0}, "bad_request"),
        ({"deadline_s": 86401}, "bad_request"),
        ({"deadline_s": True}, "bad_request"),
        ({"args": {"backup_id": BID}}, "bad_request"),
        ({"args": {"backup_id": BID, "location": LOC, "dsn": "x"}}, "bad_request"),
        ({"args": {"kind": "pg_dump"}}, "bad_request"),
        ({"args": {"backup_id": "x", "location": LOC}}, "bad_request"),
        ({"args": {"backup_id": BID, "location": 7}}, "bad_request"),
    ],
)
def test_protocol_unknown_members_versions_and_mismatched_args_are_refused(
    changes: dict[str, Any], code: str
) -> None:
    assert _code(_body(**changes)) == code


def test_protocol_deep_nesting_is_refused_whatever_the_parser_reaches() -> None:
    depth = protocol.MAX_FRAME // 2
    assert _code(b"[" * depth + b"]" * depth) in ("bad_frame", "bad_request")


def test_protocol_a_refusal_echoes_the_request_id_when_it_reads() -> None:
    with pytest.raises(protocol.ProtocolError) as refused:
        protocol.parse_request(_body(v=2))
    assert refused.value.request_id == RID
    with pytest.raises(protocol.ProtocolError) as unread:
        protocol.parse_request(protocol.dumps([1]))
    assert (unread.value.code, unread.value.request_id) == ("bad_request", None)
    with pytest.raises(protocol.ProtocolError) as versionless:
        protocol.parse_request(protocol.dumps({"id": RID}))
    assert versionless.value.code == "bad_request"


@pytest.mark.parametrize(
    "location",
    [
        "srv/cv/backups/pg_dump/4b7c1e2a-9f3d-4c5e-8a6b-7d8e9f0a1b2c.age",
        "/srv/cv//pg_dump/4b7c1e2a-9f3d-4c5e-8a6b-7d8e9f0a1b2c.age",
        "/srv/cv/../pg_dump/4b7c1e2a-9f3d-4c5e-8a6b-7d8e9f0a1b2c.age",
        "/srv/cv/./pg_dump/4b7c1e2a-9f3d-4c5e-8a6b-7d8e9f0a1b2c.age",
        "/srv/u@h/pg_dump/4b7c1e2a-9f3d-4c5e-8a6b-7d8e9f0a1b2c.age",
        "file:///srv/pg_dump/4b7c1e2a-9f3d-4c5e-8a6b-7d8e9f0a1b2c.age",
        "/srv/cv/pg_dump/4b7c1e2a-9f3d-1c5e-8a6b-7d8e9f0a1b2c.age",  # not a uuid4
        "/srv/cv/pg_dump/4B7C1E2A-9F3D-4C5E-8A6B-7D8E9F0A1B2C.age",
        "/srv/cv/pg_dump/4b7c1e2a-9f3d-4c5e-8a6b-7d8e9f0a1b2c.tar",
        "/pg_dump/4b7c1e2a-9f3d-4c5e-8a6b-7d8e9f0a1b2c.age",
        "/srv/cv/PG/4b7c1e2a-9f3d-4c5e-8a6b-7d8e9f0a1b2c.age",
        "/" + "a/" * 260 + "pg_dump/4b7c1e2a-9f3d-4c5e-8a6b-7d8e9f0a1b2c.age",
    ],
)
def test_protocol_location_outside_pattern_is_refused_bad_request(location: str) -> None:
    assert not protocol.is_location(location)
    assert _code(_body(args={"backup_id": BID, "location": location})) == "bad_request"


@given(st.text(min_size=1, max_size=600))
def test_protocol_no_location_with_dot_dot_double_slash_at_or_scheme_passes(text: str) -> None:
    if any(bad in text for bad in ("..", "//", "@", "://", "\x00")):
        for shaped in (text, LOC.replace("/cv/", f"/{text}/")):
            assert not protocol.is_location(shaped)


def test_protocol_no_frame_member_names_a_credential() -> None:
    names = {"v", "id", "op", "deadline_s", "args", "t", "pct", "result", "code"}
    names |= set().union(*protocol.ARGS.values())
    names |= {"location", "encrypted", "encryption_ref", "size_bytes", "checksum_sha256",
              "covers_from", "covers_to", "method", "state", "purge_after"}  # fmt: skip
    for word in ("password", "passwd", "dsn", "identity", "secret", "token", "key", "stderr"):
        assert not [n for n in names if word in n]


def test_protocol_answers_are_canonical_and_an_unknown_code_is_internal_error() -> None:
    assert protocol.error(RID, "no_such_code") == protocol.error(RID, "internal_error")
    frame = protocol.progress(RID, 50)
    header, _, body = frame.partition(b"\n")
    assert int(header) == len(body) - 1
    assert protocol.loads(body[:-1], floats=True) == {"v": 1, "id": RID, "t": "progress",
                                                      "pct": 50.0}  # fmt: skip
    assert not protocol.is_uuid(None) and not protocol.is_uuid("x" * 36)


def test_fingerprint_is_sha256_of_the_ascii_recipient_string() -> None:
    fixed = "age1ql3z7hjy54pw3hyww5ayyfg7zqgvc7w3j2elw8zmrj2kg5sfn9aqmcac8p"  # the age spec's
    vector = "cf7e5682313150685bf16e42c4ea48e168e16e8206c5c4ad37c72d013cb6a5f4"
    assert hashlib.sha256(fixed.encode("ascii")).hexdigest() == vector
    assert age_format.fingerprint(fixed) == f"age-x25519-sha256:{vector}"
    assert age_format.is_recipient(fixed)


def test_a_recipient_must_be_bech32_age_with_zero_padding() -> None:
    good = recipient(bytes(range(32)))
    assert age_format.is_recipient(good)
    flipped = good[:-1] + ("q" if good[-1] != "q" else "p")
    assert not age_format.is_recipient(flipped)  # checksum
    assert not age_format.is_recipient(good.upper())
    assert not age_format.is_recipient("age1" + good[4:-1])
    assert not age_format.is_fingerprint("sha256:" + "0" * 64)
    assert age_format.is_fingerprint(age_format.fingerprint(good))


def test_verify_header_with_one_x25519_stanza_passes() -> None:
    data = age_bytes()
    assert age_format.header_ok(data[: age_format.MAX_HEADER], len(data))


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(age_bytes(stanzas=("X25519", "X25519")), id="two-stanzas"),
        pytest.param(age_bytes(stanzas=("scrypt",)), id="other-type"),
        pytest.param(age_bytes(stanzas=()), id="no-stanza"),
        pytest.param(age_bytes(pad=age_format.MAX_HEADER), id="over-4kib"),
        pytest.param(age_bytes(payload=31), id="no-room-for-nonce-and-tag"),
        pytest.param(age_bytes().replace(b"org/v1", b"org/v2"), id="version"),
        pytest.param(age_bytes().replace(b"\n--- ", b"\n---"), id="mac-line"),
        pytest.param(b"not age at all", id="plaintext"),
    ],
)
def test_verify_a_malformed_header_is_refused(data: bytes) -> None:
    assert not age_format.header_ok(data[: age_format.MAX_HEADER], len(data))
