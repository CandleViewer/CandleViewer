"""#3319 B1b (24 §15.8): the golden frames pin the sidecar's end of its socket.

Each request frame decodes on the sidecar (`cvbackup.protocol`) to the request it names, or to the
refusal it names; each answer frame is what the sidecar encodes for its answer. The API's client
(`sidecar_wire`, B1b-ii) is held to the same frames, which keeps the two ends equal."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cvbackup import protocol

FRAMES = Path(__file__).resolve().parents[2] / "fixtures" / "backup_sidecar" / "frames_v1.jsonl"
_LINES = [json.loads(line) for line in FRAMES.read_text("ascii").splitlines()]


def _body(frame: bytes) -> bytes:
    header, _, rest = frame.partition(b"\n")
    assert rest.endswith(b"\n") and len(rest) == int(header) + 1
    return rest[:-1]


def _cases(side: str) -> list[Any]:
    return [pytest.param(c, id=c["name"]) for c in _LINES if c["side"] == side]


def test_the_golden_file_covers_every_op_and_every_error_code() -> None:
    requested = {c["request"]["op"] for c in _LINES if c["side"] == "request" and "request" in c}
    codes = {c["answer"]["code"] for c in _LINES if c.get("answer", {}).get("t") == "error"}
    assert requested == set(protocol.OPS)
    assert codes == set(protocol.ERROR_CODES)


@pytest.mark.parametrize("case", _cases("request"))
def test_a_request_frame_decodes_as_the_golden_file_names(case: dict[str, Any]) -> None:
    frame = case["frame"].encode("latin-1")
    if case["expect"] != "ok":
        with pytest.raises(protocol.ProtocolError) as refused:
            protocol.parse_request(_body(protocol_frame_or_raise(frame)))
        assert refused.value.code == case["expect"]
        return
    sent = case["request"]
    parsed = protocol.parse_request(_body(frame))
    assert (parsed.id, parsed.op, parsed.deadline_s, dict(parsed.args)) == (
        sent["id"],
        sent["op"],
        sent["deadline_s"],
        sent["args"],
    )


def protocol_frame_or_raise(frame: bytes) -> bytes:
    """A refused frame may break the frame layer itself: its header is checked first."""
    header, _, rest = frame.partition(b"\n")
    protocol.parse_length(header)
    if not rest.endswith(b"\n") or len(rest) != int(header) + 1:
        raise protocol.ProtocolError("bad_frame")
    return frame


@pytest.mark.parametrize(
    "case", [c for c in _cases("answer") if c.values[0]["expect"] != "violation"]
)
def test_an_answer_frame_is_what_the_sidecar_encodes(case: dict[str, Any]) -> None:
    frame = case["frame"].encode("latin-1")
    sent = case["answer"]
    if sent["t"] == "ok":
        assert protocol.ok(sent["id"], sent["result"]) == frame
    elif sent["t"] == "error":
        assert protocol.error(sent["id"], sent["code"]) == frame
    else:
        assert protocol.progress(sent["id"], sent["pct"]) == frame
