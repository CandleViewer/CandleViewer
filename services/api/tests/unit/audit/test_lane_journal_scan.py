"""ADR-0037 S1a, second half: the scan transition table and quarantine
(`docs/plan/24-internal-schemas.md` §15.6 Scan, Hold, Release and Ingest step 1).

`outline()` shows a scan as hand-overs (their `seq`) and runs (`reason, from_seq, to_seq`); "row n"
is the table's row `#` n. Keys are test vectors.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import replace
from itertools import pairwise

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.audit.lane_journal import (
    ZERO_MAC,
    Handover,
    LaneKeys,
    LaneMarker,
    LaneScan,
    LaneState,
    Run,
    anomaly_id,
    encode_frame,
    encode_marker,
    key_id,
    record_invalid,
    scan,
    segment_name,
)

KEY, OTHER = bytes(range(32)), bytes(range(32, 64))
KEYS = LaneKeys(KEY)
LANE, FOREIGN = uuid.UUID(int=1), uuid.UUID(int=2)


def mac(frame: bytes) -> str:
    return frame[-65:-1].decode()


def chain(n: int, *, lane: uuid.UUID = LANE) -> list[bytes]:
    frames, prev = [], ZERO_MAC
    for seq in range(1, n + 1):
        frames.append(
            encode_frame(KEYS, lane=lane, seq=seq, prev=prev, cls="shared", rec={"n": seq})
        )
        prev = mac(frames[-1])
    return frames


def odd(seq: int, prev: str, key: bytes = KEY) -> bytes:
    """An authentic frame whose `prev` the test chooses."""
    return encode_frame(LaneKeys(key), lane=LANE, seq=seq, prev=prev, cls="shared", rec={})


def sealed(obj: dict[str, object], label: bytes, key: bytes = KEY) -> tuple[bytes, bytes]:
    body = json.dumps(obj, separators=(",", ":"), sort_keys=True).encode()
    return body, hmac.new(key, label + body, hashlib.sha256).hexdigest().encode()


def raw_frame(obj: dict[str, object]) -> bytes:
    body, tag = sealed(obj, b"cv-audit-lane/v1/frame\n")
    return b"%d\n%s\n%s\n" % (len(body), body, tag)


def bump(frame: bytes, by: int) -> bytes:
    head, rest = frame.split(b"\n", 1)
    return b"%d\n%s" % (int(head) + by, rest)


def marker(
    pos: tuple[int, int] = (1, 0), next_seq: int = 1, prev: str = ZERO_MAC, key: bytes = KEY
) -> bytes:
    return encode_marker(LaneKeys(key), LaneMarker(LANE, pos, next_seq, prev, True))


def note_of(hold: tuple[int, int], end: tuple[int, int], key: bytes = KEY) -> bytes:
    words = {"operator": "owner", "ticket": "#3009", "operator_reason": "planted"}
    obj = {"v": 1, "lane": str(LANE), "hold": list(hold), "end": list(end), "from_seq": 3}
    body, tag = sealed(obj | words, b"cv-audit-lane/v1/released\n", key)
    return body + b"\n" + tag + b"\n"


F, START = chain(6), marker()
TAMPERED = F[1].replace(b'"n":2', b'"n":9')
X3, Y4, Z3 = odd(3, "b" * 64), odd(4, "c" * 64), odd(3, "d" * 64)  # off the chain
P3 = odd(3, mac(F[1]), key=OTHER)  # under a key nobody configured


def run_scan(
    segments: dict[int, bytes], mark: bytes | None = START, note: bytes | None = None
) -> LaneScan:
    files = {segment_name(first): data for first, data in segments.items()}
    names = [*files, "confirmed", "lane.lock", "seg-1.lane"]  # only `seg-<20 digits>.lane` count
    return scan(KEYS, marker=mark, names=names, read=files.__getitem__, note=note)


def outline(result: LaneScan) -> list[object]:
    return [
        u.frame.seq if isinstance(u, Handover) else (u.reason, u.from_seq, u.to_seq)
        for u in result.units
    ]


def runs(result: LaneScan) -> list[Run]:
    return [u for u in result.units if isinstance(u, Run)]


def test_scan_hands_over_frames_in_sequence_from_the_marker() -> None:
    result = run_scan({1: F[0] + F[1], 3: F[2] + F[3]})
    resumed = run_scan({1: F[0] + F[1], 3: F[2]}, marker((1, len(F[0])), 2, mac(F[0])))

    assert outline(result) == [1, 2, 3, 4] and result.lane == LANE and not result.sealed
    assert result.state == LaneState(5, mac(F[3]), True) == result.units[-1].state
    assert (result.units[1].end, result.units[2].start) == ((1, len(F[0] + F[1])), (3, 0))
    assert outline(resumed) == [2, 3]


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (F[0] + F[2] + F[3], [1, ("seq_gap", 2, 2), 3, 4]),
        (F[0] + F[2] + F[1] + F[3], [1, ("seq_gap", 2, 2), 3, ("frame_rejected", 4, 3), 4]),
        (F[0] + F[1] + F[1] + F[2], [1, 2, ("frame_rejected", 3, 2), 3]),
        (F[0] + chain(2, lane=FOREIGN)[1] + F[1], [1, ("frame_rejected", 2, 1), 2]),
        (F[0] + TAMPERED + F[2], [1, ("frame_rejected", 2, 2), 3]),
    ],
    ids=["removed", "reordered", "duplicated", "spliced_from_another_lane", "changed_rec"],
)
def test_lane_rejects_a_tampered_frame(data: bytes, expected: list[object]) -> None:
    result = run_scan({1: data})

    assert outline(result) == expected
    assert all(u.raw in F for u in result.units if isinstance(u, Handover))


def test_lane_quarantine_names_a_run_by_its_first_byte() -> None:
    gap, bad = runs(run_scan({1: F[0] + F[2]}))[0], runs(run_scan({1: F[0] + TAMPERED + F[2]}))[0]

    assert gap.data == b"" and gap.quarantined is None and gap.prev_unverified
    assert gap.digest == hashlib.sha256(b"").hexdigest()
    assert bad.data == TAMPERED and bad.quarantined == f"{segment_name(1)}.{len(F[0])}"


@pytest.mark.parametrize(
    ("segments", "mark", "expected", "behind"),
    [
        ({1: F[0] + F[1], 5: F[4] + F[5]}, START, [1, 2, ("seq_gap", 3, 4), 5, 6], False),
        ({1: F[0] + F[1], 5: F[4]}, marker((3, 0), 3, mac(F[1])), [("seq_gap", 3, 4), 5], False),
        ({5: F[4] + F[5]}, marker((3, 0), 3, mac(F[1])), [("seq_gap", 3, 4), 5, 6], True),
        ({5: F[4]}, START, [("seq_gap", 1, 4), 5], True),
    ],
    ids=["middle", "marker_segment", "oldest_unconfirmed", "marker_rolled_back"],
)
def test_lane_detects_a_deleted_segment(
    segments: dict[int, bytes], mark: bytes, expected: list[object], behind: bool
) -> None:
    result = run_scan(segments, mark)

    assert outline(result) == expected
    assert runs(result)[0].marker_behind is behind and runs(result)[0].prev_unverified


FORGED = marker((1, len(F[0] + F[1])), 3, mac(F[1]))[:-65] + START[-65:]


@pytest.mark.parametrize(
    ("mark", "ahead"),
    [
        (None, False),
        (FORGED, False),
        (marker((1, 10_000), 3), True),
        (marker((9, 0), 3), True),
        (marker((1, 5), 3), True),
    ],
    ids=["absent", "rolled_forward_without_the_key", "past_its_segment", "newer", "off_boundary"],
)
def test_lane_rescans_everything_when_the_marker_is_lost_or_ahead(
    mark: bytes | None, ahead: bool
) -> None:
    result = run_scan({1: F[0] + F[1] + F[2]}, mark)

    assert outline(result) == [("marker_lost", 1, 0), 1, 2, 3] and result.lane == LANE
    assert runs(result)[0].marker_ahead is ahead


def test_lane_marker_ahead_accounts_from_its_next_seq_when_that_is_smaller() -> None:
    ahead = marker((1, 10_000), 3)  # row 2: past the end of its segment
    released = run_scan({1: P3 + F[3]}, ahead, note_of((1, 0), (1, len(P3))))

    assert outline(run_scan({1: F[4] + F[5]}, ahead)) == [("marker_lost", 3, 4), 5, 6]
    assert outline(released) == [("marker_lost", 3, None), ("released", 3, 2), ("seq_gap", 3, 3), 4]


@pytest.mark.parametrize(
    ("segments", "expected", "lane"),
    [
        ({3: F[2] + F[3]}, [("marker_lost", 3, 2), 3, 4], LANE),
        ({1: b"junk\n" + F[0]}, [("segment_corrupt", 1, 0), 1], LANE),
        (
            {1: chain(1, lane=FOREIGN)[0] + F[1]},
            [("marker_lost", 1, 0), 1, ("frame_rejected", 2, None)],
            FOREIGN,
        ),
        ({1: b"junk\n"}, [("segment_corrupt", None, None)], None),
        ({1: odd(1, ZERO_MAC, key=OTHER)}, [("marker_lost", None, None)], None),
    ],
    ids=["compacted", "junk_first", "foreign_first", "no_frame", "hold_first"],
)
def test_lane_without_a_verifiable_marker_takes_its_first_authentic_frames_lane(
    segments: dict[int, bytes], expected: list[object], lane: uuid.UUID | None
) -> None:
    result = run_scan(segments, None)

    assert outline(result) == expected and result.lane == lane


def test_lane_scan_of_an_empty_lane() -> None:
    gone = run_scan({}, marker((5, 0), 7))

    empty = LaneScan(None, (), LaneState(None, ZERO_MAC, False), False, None, False, False)

    assert run_scan({}, None) == empty
    assert run_scan({}, START).units == ()
    assert outline(gone) == [("marker_lost", 7, None)] and not gone.sealed


def test_lane_marker_under_an_unknown_kid_holds_before_any_frame() -> None:
    result = run_scan({1: F[0]}, marker(key=OTHER))

    assert result.held and result.hold is None and result.units == () and result.lane is None


@pytest.mark.parametrize("held", [P3, raw_frame({"v": 2, "kid": key_id(KEY)})], ids=["kid", "v"])
def test_lane_holds_on_an_unknown_kid_or_v(held: bytes) -> None:
    plain = run_scan({1: F[0] + F[1] + held + F[2]})
    after_junk = run_scan({1: F[0] + F[1] + b"junk\n" + held + F[2]})

    assert outline(plain) == [1, 2] and plain.held and plain.hold == (1, len(F[0] + F[1]))
    assert plain.state == LaneState(3, mac(F[1]), True) and not plain.note_ignored
    assert outline(after_junk) == [1, 2, ("segment_corrupt", 3, None)]
    assert after_junk.hold == (1, len(F[0] + F[1]) + 5)  # resync stops at it, never skims it


@pytest.mark.parametrize(
    ("data", "expected", "sealed_after"),
    [
        (F[0] + F[1] + F[2][:30], [1, 2, ("torn_tail", 3, None)], True),
        (F[0] + F[1] + bump(F[2], 1), [1, 2, ("torn_tail", 3, None)], True),
        (F[0] + F[1] + F[2][:2], [1, 2, ("torn_tail", 3, None)], True),
        (F[0] + bump(F[1], 1) + F[2], [1, ("segment_corrupt", 2, 2), 3], False),
        (F[0] + F[1] + bump(F[2], -1), [1, 2, ("segment_corrupt", 3, None)], True),
        (F[0] + b"x" + F[1] + F[2], [1, ("segment_corrupt", 2, 2), 3], False),
    ],
    ids=["torn", "newest_len_raised", "partial_len", "middle_len_raised", "len_lowered", "glued"],
)
def test_lane_torn_tail_against_a_len_edit(
    data: bytes, expected: list[object], sealed_after: bool
) -> None:
    result = run_scan({1: data})

    assert outline(result) == expected and result.sealed is sealed_after
    assert result.state.anchored is (expected[-1] != ("segment_corrupt", 3, None))


def test_lane_released_note_resumes_after_the_held_bytes() -> None:
    hold, end = (1, len(F[0] + F[1])), (1, len(F[0] + F[1] + P3))
    one, two = {1: F[0] + F[1] + P3 + F[3]}, {1: F[0] + F[1] + P3, 3: F[3]}

    released = run_scan(one, note=note_of(hold, end))
    across = run_scan(two, note=note_of(hold, (3, 0)))

    assert outline(released) == [1, 2, ("released", 3, 2), ("seq_gap", 3, 3), 4]
    assert runs(released)[0].note == ("owner", "#3009", "planted") and not released.held
    assert runs(released)[0].data == P3 == runs(across)[0].data and outline(across)[-1] == 4
    for bad in (note_of(hold, end, OTHER), note_of((1, 0), end), note_of(hold, hold)):
        ignored = run_scan(one, note=bad)
        assert outline(ignored) == [1, 2] and ignored.held and ignored.note_ignored
    for bad in (note_of(hold, (5, 0)), note_of(hold, (3, 999)), note_of(hold, end)[:-1]):
        assert run_scan(two, note=bad).note_ignored


@pytest.mark.parametrize(
    ("segments", "mark", "note", "head"),
    [
        ({1: F[0] + F[1] + b"junk\n" + X3 + Y4}, START, None, [1, 2, ("segment_corrupt", 3, 2)]),
        (
            {1: F[0] + F[1] + X3.replace(b"shared", b"sharex") + X3 + Y4},
            START,
            None,
            [1, 2, ("frame_rejected", 3, 2)],
        ),
        ({1: F[0] + F[1] + Z3 + X3 + Y4}, START, None, [1, 2, ("frame_rejected", 3, 2)]),
        ({1: F[0] + F[1] + F[1] + X3 + Y4}, START, None, [1, 2, ("frame_rejected", 3, 2)]),
        ({1: F[0] + X3 + Y4}, START, None, [1, ("seq_gap", 2, 2)]),
        ({3: X3 + Y4}, None, None, [("marker_lost", 3, 2)]),
        ({1: F[0] + F[1] + F[2][:30], 3: F[2] + Y4}, START, None, [1, 2, ("torn_tail", 3, 2)]),
        ({1: F[0] + F[1] + P3 + X3 + Y4}, START, "released", [1, 2, ("released", 3, 2)]),
    ],
    ids=["corrupt", "mac", "chain_break", "repeated_seq", "gap", "marker_lost", "torn", "released"],
)
def test_lane_re_anchors_after_each_kind_of_run(
    segments: dict[int, bytes], mark: bytes | None, note: str | None, head: list[object]
) -> None:
    hold = (1, len(F[0] + F[1]))
    release = None if note is None else note_of(hold, (1, len(F[0] + F[1] + P3)))
    result = run_scan(segments, mark, release)

    assert outline(result) == [*head, 3, ("frame_rejected", 4, None)]


def test_lane_record_invalid_frame_keeps_the_chain_anchored() -> None:
    result = run_scan({1: F[0] + b"junk\n" + F[1] + odd(3, "b" * 64)})
    handed = result.units[2]
    assert isinstance(handed, Handover)
    invalid = record_invalid(handed)

    assert outline(result) == [1, ("segment_corrupt", 2, 1), 2, ("frame_rejected", 3, None)]
    assert (invalid.reason, invalid.from_seq, invalid.to_seq) == ("record_invalid", 2, 2)
    assert invalid.state == handed.state == LaneState(3, mac(F[1]), True)
    assert invalid.data == F[1] and invalid.quarantined == f"{segment_name(1)}.{len(F[0]) + 5}"


def test_lane_one_row_per_run() -> None:
    result = run_scan({1: F[0] + b"junk\n" + TAMPERED + F[0] + F[3]})

    assert outline(result) == [1, ("segment_corrupt", 2, 3), 4]
    assert runs(result)[0].data == b"junk\n" + TAMPERED + F[0]


def test_lane_anomaly_ids_are_equal_only_for_byte_identical_runs() -> None:
    first, again = (runs(run_scan({1: F[0] + b"junk\n" + F[1]}))[0] for _ in range(2))
    other_bytes = runs(run_scan({1: F[0] + b"junK\n" + F[1]}))[0]
    uid = anomaly_id(KEYS, LANE, first)
    message = json.dumps([str(LANE), "segment_corrupt", 2, 1, first.digest], separators=(",", ":"))
    tag = hmac.new(KEY, b"cv-audit-lane/v1/anomaly\n" + message.encode(), hashlib.sha256)
    raw = bytearray(tag.digest()[:16])
    raw[6], raw[8] = (raw[6] & 0x0F) | 0x80, (raw[8] & 0x3F) | 0x80
    distinct = [
        anomaly_id(KEYS, LANE, run) for run in (first, other_bytes, replace(first, to_seq=9))
    ]
    distinct += [anomaly_id(LaneKeys(OTHER), LANE, first), anomaly_id(KEYS, None, first)]

    assert uid == anomaly_id(KEYS, LANE, again) == uuid.UUID(bytes=bytes(raw))
    assert uid.version == 8 and uid.variant == uuid.RFC_4122
    assert len(set(distinct)) == len(distinct) == 5


_EDITS = st.tuples(
    st.integers(0, 2), st.integers(0, 4096), st.sampled_from("fid"), st.integers(1, 255)
)


@given(st.data())
def test_lane_random_damage_never_hands_over_a_bad_frame_or_loses_a_good_one(
    data: st.DataObject,
) -> None:
    """(a) Accounting, over every input: each byte from the scan start lies in one hand-over or
    one run, and each `seq` from where it starts up to the last hand-over is handed over once or
    inside one run's range. (b) Liveness: every frame intact at a line start before the hold
    whose `seq` is above all before it is handed over, and nothing else is."""
    n = data.draw(st.integers(1, 6))
    order = data.draw(st.just(list(range(n))) | st.lists(st.integers(0, n - 1), max_size=n + 2))
    cuts = sorted(data.draw(st.sets(st.integers(0, len(order)), max_size=2)))
    segments = [
        bytearray(b"".join(F[i] for i in order[a:b])) for a, b in pairwise([0, *cuts, len(order)])
    ]
    for k, at, kind, value in data.draw(st.lists(_EDITS, max_size=3)):
        seg = segments[k % len(segments)]
        if kind == "i":
            seg.insert(at % (len(seg) + 1), value)
        elif seg and kind == "f":
            seg[at % len(seg)] ^= value
        elif seg:
            del seg[at % len(seg)]
    layout = {1 + 1000 * k: bytes(seg) for k, seg in enumerate(segments)}
    marked = data.draw(st.booleans())
    result = run_scan(layout, START if marked else None)
    hold = result.hold or (1 << 60, 0)
    handed = [u for u in result.units if isinstance(u, Handover)]
    seqs = [u.frame.seq for u in handed]
    ranges = [(u.from_seq or 0, u.to_seq) for u in runs(result) if u.to_seq is not None]

    scanned = b"".join(
        s if f < hold[0] else s[: hold[1]] for f, s in layout.items() if f <= hold[0]
    )
    assert b"".join(u.raw if isinstance(u, Handover) else u.data for u in result.units) == scanned
    assert all(u.raw == F[u.frame.seq - 1] for u in handed)
    for seq in range(1 if marked or not seqs else seqs[0], seqs[-1] + 1 if seqs else 0):
        assert seqs.count(seq) + sum(a <= seq <= b for a, b in ranges) == 1
    expected: list[int] = []
    for first, chunk in layout.items():
        for p in range(len(chunk)):
            if (first, p) >= hold or (p and chunk[p - 1] != 0x0A):
                continue
            expected += [
                s
                for s, f in enumerate(F[:n], 1)
                if s > max(expected, default=0) and chunk.startswith(f, p)
            ][:1]
    assert seqs == expected
