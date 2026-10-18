"""E17-T02: CVWB codec — hypothesis round trip, malformed cases, SR-128, drift + SR-155 corpus."""

from __future__ import annotations

import importlib.util
import json
import struct
import sys
import tracemalloc
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from candleviewer.ws import cvwb_vectors
from candleviewer.ws._generated import cvwb_layout
from candleviewer.ws.binary import (
    BARS,
    BOOK_DELTA,
    BOOK_SNAPSHOT,
    FOOTPRINT,
    HEATMAP_COLUMN,
    TRADES,
    Frame,
    FrameEncodeError,
    FrameMalformedError,
    decode,
    decode_b64,
    encode,
    encode_b64,
)

REPO = Path(__file__).resolve().parents[5]
U8 = st.integers(0, 2**8 - 1)
U32 = st.integers(0, 2**32 - 1)
U64 = st.integers(0, 2**64 - 1)
I64 = st.integers(-(2**63), 2**63 - 1)
SIDE = st.sampled_from((0, 1))

_RECORD = {
    BOOK_SNAPSHOT: st.tuples(SIDE, I64, U64),
    BOOK_DELTA: st.tuples(SIDE, I64, U64),
    TRADES: st.tuples(U32, I64, U64, SIDE, U8),
    BARS: st.tuples(U64, U64, U32, I64, I64, I64, I64, U64, U64, U32, I64, U8),
    FOOTPRINT: st.tuples(I64, U64, U64, U32, U8),
    HEATMAP_COLUMN: st.tuples(U64, U64),
}


@st.composite
def frames(draw: st.DrawFn) -> Frame:
    kind = draw(st.sampled_from(sorted(_RECORD)))
    rec = _RECORD[kind]
    flags = draw(st.integers(0, 0b1111))
    ps = draw(st.integers(0, 8))
    qs = draw(st.integers(0, 8))
    ts = draw(U64)
    if kind == FOOTPRINT:
        # v2 group prefix (#2529): (generation, index, ts_offset_ms, flags), cell_count derived;
        # flags bit0 is confirm and the reserved bits 1-7 are 0 on send.
        prefix = st.tuples(U64, U64, U32, st.sampled_from((0, 1)))
        groups = draw(st.lists(st.tuples(prefix, st.lists(rec, max_size=6).map(tuple)), max_size=6))
        return Frame(kind, (), flags, ps, qs, ts, groups=tuple(groups))
    records = tuple(draw(st.lists(rec, max_size=6)))
    if kind == BOOK_SNAPSHOT:
        return Frame(kind, records, flags, ps, qs, ts, trailer=draw(st.tuples(U64, U64)))
    if kind == HEATMAP_COLUMN:
        return Frame(kind, records, flags, ps, qs, ts, prefix=draw(st.tuples(U32, I64, I64)))
    return Frame(kind, records, flags, ps, qs, ts)


@settings(max_examples=300, deadline=None)
@given(frames())
def test_codec_round_trip_any_valid_frame_is_exact(frame: Frame) -> None:
    raw = encode(frame)
    assert decode(raw) == frame
    assert encode(decode(raw)) == raw  # byte-identical re-encode (ADR-0005)
    assert decode_b64(encode_b64(frame)) == frame


@settings(max_examples=300, deadline=None)
@given(st.binary(max_size=200))
def test_decode_arbitrary_bytes_never_raises_anything_else(data: bytes) -> None:
    try:
        decode(data)
    except FrameMalformedError:
        pass


@given(frames(), st.binary(min_size=1, max_size=16))
def test_decode_trailing_bytes_follow_the_per_kind_rule(frame: Frame, extra: bytes) -> None:
    raw = encode(frame) + extra
    if frame.body_kind == BARS:
        with pytest.raises(FrameMalformedError):
            decode(raw)
    else:
        assert decode(raw) == frame


def _hdr(kind: int, count: int, ver: int = 1, magic: int = 0x43565742) -> bytes:
    return struct.pack("<IBBBBB3xIQ", magic, ver, kind, 0, 2, 3, count, 0)


@pytest.mark.parametrize(
    ("data", "diagnostic"),
    [
        (b"", "frame_malformed"),
        (_hdr(BOOK_DELTA, 0, magic=0)[:20], "frame_malformed"),
        (_hdr(BOOK_DELTA, 0, magic=0x42575643), "frame_malformed"),
        (_hdr(BOOK_DELTA, 0, ver=2), "unsupported_format_version"),
        (_hdr(BARS, 0, ver=1), "unsupported_format_version"),
        (_hdr(9, 0), "unsupported_body_kind"),
        (_hdr(TRADES, 2) + bytes(43), "frame_malformed"),
        (_hdr(BOOK_SNAPSHOT, 0) + bytes(15), "frame_malformed"),
        (_hdr(HEATMAP_COLUMN, 1) + bytes(10), "frame_malformed"),
        (_hdr(FOOTPRINT, 1, ver=2) + bytes(27), "frame_malformed"),
        (_hdr(FOOTPRINT, 1, ver=2) + bytes(8), "frame_malformed"),
        (_hdr(FOOTPRINT, 1) + struct.pack("<II", 0, 0), "unsupported_format_version"),
    ],
    ids=[
        "empty",
        "short-header",
        "magic",
        "version",
        "bars-v1",
        "kind",
        "short",
        "trailer",
        "hm-prefix",
        "fp-prefix",
        "fp-v1-group-under-v2-header",
        "fp-v1",
    ],
)
def test_decode_malformed_input_raises_typed_error(data: bytes, diagnostic: str) -> None:
    with pytest.raises(FrameMalformedError) as info:
        decode(data)
    assert info.value.diagnostic == diagnostic
    assert info.value.code == "frame_malformed"


def test_decode_max_u32_count_rejects_without_proportional_allocation() -> None:
    """SR-128 / Gherkin: record_count=2^32-1, 32-byte body -> reject, no big allocation."""
    data = _hdr(BOOK_DELTA, 2**32 - 1) + bytes(32)
    tracemalloc.start()
    try:
        with pytest.raises(FrameMalformedError):
            decode(data)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 64 * 1024


def test_decode_b64_rejects_non_base64() -> None:
    with pytest.raises(FrameMalformedError):
        decode_b64("not*base64")


@pytest.mark.parametrize(
    "frame",
    [
        Frame(9),
        Frame(BOOK_DELTA, flags=0b1_0000),
        Frame(BOOK_DELTA, ((2, 0, 0),)),
        Frame(BOOK_DELTA, ((0, 2**63, 0),)),
        Frame(BOOK_SNAPSHOT),
        Frame(BOOK_DELTA, trailer=(0, 0)),
        Frame(HEATMAP_COLUMN),
        Frame(FOOTPRINT),
        Frame(FOOTPRINT, ((1, 2, 3, 4, 5),), groups=()),
        Frame(FOOTPRINT, groups=(((0, 2**64, 0, 0), ()),)),
        Frame(FOOTPRINT, groups=cast(Any, (((0, 1, 2, 0), (5,)),))),
    ],
    ids=[
        "kind",
        "flags",
        "side",
        "range",
        "no-trailer",
        "extra-trailer",
        "no-prefix",
        "no-groups",
        "records-outside-groups",
        "fp-index-over-u64",
        "fp-cell-not-a-tuple",
    ],
)
def test_encode_unrepresentable_frame_raises(frame: Frame) -> None:
    with pytest.raises(FrameEncodeError):
        encode(frame)


@pytest.mark.parametrize(
    "groups",
    [
        ((60_000, ()),),  # the pre-#2529 shape: a bare ts_offset_ms
        (((0, 1, 2), ()),),  # a prefix without flags
        (((0, 1, 2, 0),),),  # a group without cells
        (((0, 1, 2, 0), (), ()),),  # a group with a third member
        (60_000, ()),  # groups that are not nested
        (((0, 1, 2, 0), 5),),  # cells that is not a tuple
        5,  # groups that is not a tuple
    ],
)
def test_encode_refuses_a_malformed_footprint_group_with_a_typed_error(groups: Any) -> None:
    """Anything but ``((generation, index, ts_offset_ms, flags), cells)`` is a FrameEncodeError
    naming that shape, never the bare TypeError or ValueError that unpacking it would raise."""
    with pytest.raises(FrameEncodeError, match=r"\(generation, index, ts_offset_ms, flags\)"):
        encode(Frame(FOOTPRINT, groups=groups))


@pytest.mark.parametrize("group_flags", [0b10, 0b1000_0001, 0xFF])
def test_encode_refuses_reserved_group_flag_bits(group_flags: int) -> None:
    """Group flags bits 1-7 are reserved and 0 on send (section 3.4, #2529)."""
    with pytest.raises(FrameEncodeError, match="reserved group flag bits are 0 on send"):
        encode(Frame(FOOTPRINT, groups=(((0, 1, 2, group_flags), ()),)))


def test_footprint_ts_offset_is_held_to_the_u32_span_rule_on_encode() -> None:
    """Section 3.6: a bar opening more than 2**32-1 ms after ts_base_ms starts a new frame, so the
    encoder refuses a wider offset (and a negative one), never wrapping or clamping it."""
    edge = Frame(FOOTPRINT, groups=(((0, 1, 2**32 - 1, 0), ()),))
    assert decode(encode(edge)) == edge
    for ts_offset_ms in (2**32, -1):
        with pytest.raises(FrameEncodeError):
            encode(Frame(FOOTPRINT, groups=(((0, 1, ts_offset_ms, 0), ()),)))


def test_encode_header_derives_version_and_counts() -> None:
    raw = encode(Frame(HEATMAP_COLUMN, ((1, 2),), prefix=(0, 0, 1)))
    assert raw[4] == 1 and raw[5] == HEATMAP_COLUMN
    assert struct.unpack_from("<I", raw, 12)[0] == 1
    assert encode(Frame(BARS))[4] == 2


# --- body_kind 5 v2: the bar key on every footprint group (#2529) ------------------------

_CELL = (6_500_000, 10, 20, 3, 0b1001)
_FP_SCHEMA = "cv://ws/v1/footprint.schema.json"
_WS_SCHEMAS: dict[str, Any] = json.loads(
    (REPO / "docs/plan/ws-schema.json").read_text(encoding="utf-8")
)["schemas"]
_WS_REGISTRY: Registry[Any] = Registry().with_resources(
    (sid, Resource.from_contents(body)) for sid, body in _WS_SCHEMAS.items()
)


def _footprint_errors(structured: dict[str, Any]) -> list[str]:
    """§14.4 validation errors of a decoded footprint payload (topic fields added)."""
    doc = {"symbol": "BTCUSDT", "bar_type": "tick", "param": "1000", **structured}
    validator = Draft202012Validator(_WS_SCHEMAS[_FP_SCHEMA], registry=_WS_REGISTRY)
    return sorted(e.message for e in validator.iter_errors(doc))


def test_footprint_v2_round_trip_keeps_the_bar_key_and_flags_per_group() -> None:
    other = (6_500_005, 1, 2, 1, 0)
    frame = Frame(
        FOOTPRINT,
        (),
        0b0010,
        1,
        3,
        1_789_132_200_000,
        groups=(((7, 2**64 - 1, 0, 1), (_CELL, other)), ((2**63, 0, 60_000, 0), (other,) * 3)),
    )
    raw = encode(frame)
    assert raw[4] == 2 and raw[5] == FOOTPRINT
    # The wire layout, pinned independently of the generated layout: a 28-byte group prefix
    # (generation, index, ts_offset_ms, cell_count, flags, 3 zero pad bytes), then 33-byte cells.
    # Counts and flags differ per group, so swapped count and flags slots cannot pass.
    second = 24 + 28 + 2 * 33
    assert struct.unpack_from("<QQIIB3x", raw, 24) == (7, 2**64 - 1, 0, 2, 1)
    assert struct.unpack_from("<QQIIB3x", raw, second) == (2**63, 0, 60_000, 3, 0)
    assert raw[24 + 25 : 24 + 28] == raw[second + 25 : second + 28] == bytes(3)
    assert len(raw) == second + 28 + 3 * 33
    assert decode(raw) == frame
    bars = cvwb_vectors.structured(decode(raw))["bars"]
    assert [(b["generation"], b["index"], b["t_ms"], b["confirm"]) for b in bars] == [
        (7, 2**64 - 1, 1_789_132_200_000, True),
        (2**63, 0, 1_789_132_260_000, False),
    ]


def test_footprint_bars_sharing_an_open_time_stay_distinct_by_index() -> None:
    """The #2529 case: one trade closes bar N and opens bar N+1 in the same millisecond."""
    other = (6_500_005, 1, 2, 1, 0)
    groups = (((0, 5, 900, 1), (_CELL,)), ((0, 6, 900, 0), (other,)))
    decoded = decode(encode(Frame(FOOTPRINT, (), 0, 1, 3, 1_789_132_200_000, groups=groups)))
    assert decoded.groups == groups
    bars = cvwb_vectors.structured(decoded)["bars"]
    assert {b["t_ms"] for b in bars} == {1_789_132_200_900}  # one open time ...
    by_key = {(b["generation"], b["index"]): b for b in bars}  # ... a client keyed per §8.2
    assert list(by_key) == [(0, 5), (0, 6)]
    assert [len(b["cells"]) for b in by_key.values()] == [1, 1]  # never summed into one bar
    assert [b["confirm"] for b in by_key.values()] == [True, False]  # N closed, N+1 forming


@pytest.mark.parametrize(
    ("group_flags", "confirm"), [(0, False), (1, True), (0b1111_1110, False), (0xFF, True)]
)
def test_footprint_group_flags_map_bit0_to_confirm_and_ignore_reserved_bits(
    group_flags: int, confirm: bool
) -> None:
    """Bits 1-7 are accepted on receive and ignored (section 3.4); decode keeps the byte as sent."""
    prefix = struct.pack("<QQIIB3x", 0, 7, 60_000, 0, group_flags)
    decoded = decode(_hdr(FOOTPRINT, 1, ver=2) + prefix)
    assert decoded.groups == (((0, 7, 60_000, group_flags), ()),)
    (bar,) = cvwb_vectors.structured(decoded)["bars"]
    assert bar["confirm"] is confirm


def test_footprint_group_count_is_refused_up_front_at_the_28_byte_stride() -> None:
    """SR-128: the group count is checked against the 28-byte v2 prefix before any group is read.
    Two groups in 48 bytes would pass a 24-byte (pre-flags) or 8-byte (v1) stride and only fail
    later, per group."""
    data = _hdr(FOOTPRINT, 2, ver=2) + bytes(48)
    with pytest.raises(FrameMalformedError, match=r"^footprint: count=2 x 28 bytes exceeds the 48"):
        decode(data)


@pytest.mark.parametrize(
    "name", [n for n, f in cvwb_vectors.vector_frames() if f.body_kind == FOOTPRINT]
)
def test_footprint_structured_twin_validates_against_section_14_4(name: str) -> None:
    structured = cvwb_vectors.structured(decode(encode(dict(cvwb_vectors.vector_frames())[name])))
    assert structured["bars"], name
    assert _footprint_errors(structured) == []
    for key in ("generation", "index"):  # the key is required, not optional (§14.4)
        bar = {k: v for k, v in structured["bars"][0].items() if k != key}
        stripped = {**structured, "bars": [bar, *structured["bars"][1:]]}
        assert _footprint_errors(stripped) == [f"'{key}' is a required property"]


# --- drift: one declaration drives both implementations ---------------------------------

_SIZES = {"u8": 1, "u32": 4, "u64": 8, "i64": 8, "pad3": 3, "pad4": 4}


def test_generated_python_layout_matches_the_declaration() -> None:
    doc = json.loads((REPO / "packages/protocol/cvwb-layout.json").read_text(encoding="utf-8"))
    assert cvwb_layout.MAGIC == doc["magic"] == 0x43565742
    assert struct.calcsize(cvwb_layout.HEADER.fmt) == doc["header_bytes"] == 24
    for k in doc["kinds"]:
        gen = cvwb_layout.KINDS[k["id"]]
        assert (gen.name, gen.format_version, gen.length_rule) == (
            k["name"],
            k["format_version"],
            k["length_rule"],
        )
        assert gen.record.size == k["record_bytes"] == struct.calcsize(gen.record.fmt)
        assert gen.record.size == sum(_SIZES[f["type"]] for f in k["record"])
        for part in ("group_prefix", "body_prefix", "trailer"):
            fields = k.get(part)
            got = getattr(gen, part)
            assert (got is None) == (fields is None), (k["name"], part)
            if got is not None:
                assert got.size == sum(_SIZES[f["type"]] for f in fields)
                assert got.size == struct.calcsize(got.fmt)
    footprint = cvwb_layout.KINDS[FOOTPRINT]
    prefix = footprint.group_prefix
    assert footprint.format_version == 2 and prefix is not None and prefix.size == 28
    assert " ".join(prefix.fields) == "generation index ts_offset_ms cell_count flags"


@pytest.mark.parametrize("name", ["vectors.json", "corpus.json"])
def test_committed_vectors_and_corpus_are_fresh(name: str) -> None:
    path, render = {
        "vectors.json": (
            REPO / "packages/fixtures/golden/cvwb/vectors.json",
            cvwb_vectors.render_vectors,
        ),
        "corpus.json": (REPO / "tests/fuzz/ws-frames/corpus.json", cvwb_vectors.render_corpus),
    }[name]
    assert path.read_text(encoding="utf-8") == render(), "run scripts/generate_cvwb_vectors.py"


def _load_by_path(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"_cv_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_gen_gate_names_every_file_the_vectors_script_writes() -> None:
    """#3392: the `gen` gate's FIXED_OUTPUTS entry for this script is the files it writes,
    so a committed file it does not write in their directories fails CI-GEN-006."""
    gate = _load_by_path(REPO / "tools/ci/check_gen_freshness.py")
    script = _load_by_path(REPO / "services/api/scripts/generate_cvwb_vectors.py")
    written = sorted(path.relative_to(REPO).as_posix() for path in script.TARGETS)
    entry = gate.FIXED_OUTPUTS["services/api/scripts/generate_cvwb_vectors.py"]
    assert sorted(entry) == written


def test_fuzz_corpus_every_seed_behaves_as_declared() -> None:
    """SR-155: each committed seed is accepted or rejected exactly as declared, never crashes."""
    seeds = json.loads((REPO / "tests/fuzz/ws-frames/corpus.json").read_text(encoding="utf-8"))
    assert len(seeds) >= 40
    for seed in seeds:
        try:
            decode(bytes.fromhex(seed["hex"]))
            got = "ok"
        except FrameMalformedError:
            got = "malformed"
        assert got == seed["expect"], seed["name"]


def test_encode_counts_frames_and_bytes_per_body_kind() -> None:
    from candleviewer.ws.metrics import ENCODED

    for name, frame in cvwb_vectors.vector_frames():
        frames, nbytes = ENCODED[frame.body_kind]
        f0, b0 = frames._value.get(), nbytes._value.get()
        size = len(encode(frame))
        assert frames._value.get() == f0 + 1, name
        assert nbytes._value.get() == b0 + size, name


def test_failed_encode_is_not_counted() -> None:
    from candleviewer.ws.metrics import ENCODED

    frames, _ = ENCODED[BOOK_DELTA]
    before = frames._value.get()
    with pytest.raises(FrameEncodeError):
        encode(Frame(BOOK_DELTA, records=((0, 0, -1),)))
    assert frames._value.get() == before
