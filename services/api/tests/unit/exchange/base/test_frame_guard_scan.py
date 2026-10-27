"""#913 L1d-2 Q9 (SEC-G8B-B-02): the depth guard's escape scan, exact and linear (24 §14.2 item 10).

A frame with a backslash was walked one Python step per character, about 100 ms per MiB on the
serving loop. R8 (`perf`) times the scan on 1 MiB frames of each measured shape, best of 5,
against the escape-free path on the same frame and against that loop, kept here as the oracle.
R9 holds the scan to the reference scanner on longer frames with escapes and newlines.
"""

from __future__ import annotations

import gc
import json
import time
from collections.abc import Callable

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from candleviewer.exchange.base.frame_guard import MAX_FRAME_DEPTH, _walk, json_depth_exceeds
from tests._corpus import frames

_MIB = 1 << 20
#: 42 openers outside any literal, two deep: past the opener-count fast path, never too deep.
_PAD = ',"pad":[' + "[]," * 40 + "[]]}"
_HALF = (_MIB - 64) // 2


def _venue_rows() -> str:
    """The recorded private order push, its row repeated to 1 MiB, one row's id escaped."""
    raw = frames("ws/private-order.jsonl")[0]
    head = raw[: raw.index('"data":[') + len('"data":[')]
    row = json.dumps(json.loads(raw)["data"][0], separators=(",", ":"))
    rows = [row] * ((_MIB - len(head)) // (len(row) + 1))
    rows[1] = row.replace('"orderLinkId":""', '"orderLinkId":"caf\\u00e9"')
    return head + ",".join(rows) + "]}"


def _empty_literals(first: str) -> str:
    return '{"a":["' + first + '",' + '"",' * (2 * _HALF // 3) + '""]' + _PAD


#: shape -> (1 MiB frame, bound on the scan's time over the escape-free path's). Measured on the
#: build host (best of 5, load about 6): 2.4x, 1.3x, 12x, 1.1x and 1.8x, the old loop 54x, 4.7x,
#: 27x, 3.2x and 3.4x. The two adversarial shapes: dense backslash pairs, the `str.replace` step's
#: worst at 12x, and dense empty literals with one escaped quote, the regex's at 1.8x.
_SHAPES: dict[str, tuple[Callable[[], str], float]] = {
    "one backslash in a long string": (
        lambda: '{"a":"' + "x" * _HALF + "\\n" + "x" * _HALF + '"' + _PAD,
        4.0,
    ),
    "venue rows with one backslash": (_venue_rows, 2.0),
    "dense backslash pairs": (lambda: '{"a":"' + "\\\\" * _HALF + '"' + _PAD, 20.0),
    "dense empty literals, one backslash": (lambda: _empty_literals("\\n"), 2.0),
    "dense empty literals, one escaped quote": (lambda: _empty_literals('\\"'), 3.0),
}

#: shape -> the path its frame takes past the opener-count fast path.
_PATHS = {
    "one backslash in a long string": "split",
    "venue rows with one backslash": "split",
    "dense backslash pairs": "replace, then split",
    "dense empty literals, one backslash": "split",
    "dense empty literals, one escaped quote": "regex",
}


def _path(frame: str) -> str:
    """The path `json_depth_exceeds` takes past its fast path, read as it reads the frame."""
    if '\\"' not in frame:
        return "split" if "\\" in frame else "escape-free"
    return "regex" if '\\"' in frame.replace("\\\\", "") else "replace, then split"


def _escape_free(frame: str) -> bool:
    return _walk("".join(frame.split('"')[::2]), MAX_FRAME_DEPTH)


def _old_loop(frame: str) -> bool:
    """`main`'s scan of a frame with a backslash before Q9: one Python step per character."""
    if frame.count("[") + frame.count("{") <= MAX_FRAME_DEPTH:
        return False
    out: list[str] = []
    in_string = escaped = False
    for ch in frame:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        else:
            out.append(ch)
    return _walk("".join(out), MAX_FRAME_DEPTH)


def _best_of_5(frame: str) -> list[float]:
    """The scan's, the escape-free path's and the old loop's best of 5, interleaved so a load
    spike costs all three alike; one untimed call each first, so none pays for fresh arenas."""
    scans = (json_depth_exceeds, _escape_free, _old_loop)
    for scan in scans:
        scan(frame)
    best = [float("inf")] * len(scans)
    for _ in range(5):
        for i, scan in enumerate(scans):
            gc.collect()
            gc.disable()
            try:
                start = time.perf_counter()
                scan(frame)
                best[i] = min(best[i], time.perf_counter() - start)
            finally:
                gc.enable()
    return best


@pytest.mark.perf
@pytest.mark.parametrize("shape", list(_SHAPES))
def test_escape_scan_holds_each_shapes_bound_and_never_trails_the_old_loop(shape: str) -> None:
    build, bound = _SHAPES[shape]
    frame = build()
    assert json_depth_exceeds(frame) is False
    assert _old_loop(frame) is False
    scan, free, old = _best_of_5(frame)
    assert scan <= bound * free, f"{scan / free:.1f}x the escape-free path, over {bound}x"
    assert scan <= old, f"{scan * 1e3:.1f} ms, the old loop {old * 1e3:.1f} ms"


@pytest.mark.parametrize("shape", list(_SHAPES))
def test_each_measured_shape_takes_the_path_its_name_claims(shape: str) -> None:
    """A shape times its path only while its frame keeps its escape: a re-recorded fixture
    without one would time the split alone."""
    assert _path(_SHAPES[shape][0]()) == _PATHS[shape]


def _deepest(frame: str) -> int:
    """The reference scanner, one character at a time: the deepest nesting outside literals."""
    depth = deepest = 0
    in_string = escaped = False
    for ch in frame:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch in "[{":
            depth += 1
            deepest = max(deepest, depth)
        elif ch in "]}":
            depth -= 1
    return deepest


#: Lone and paired backslashes, a backslash before a closing quote, escaped quotes inside and
#: outside a literal, newlines inside and outside one, and literals left open.
_TOKENS = ("[", "]", "{", "}", '"', "\\", "\\\\", '\\"', '\\\\"', '"\\"', "\n", "\\\n", "a")
_FRAMES = st.lists(st.sampled_from(_TOKENS), max_size=400)


@settings(max_examples=500, deadline=None)
@given(_FRAMES | st.lists(st.sampled_from(_TOKENS), min_size=100, max_size=400))
@example(['"', "\\\\", '"', "["])  # an escaped backslash ends no literal: the `str.replace` step
@example(['"', '\\"', '"', "["])  # an escaped quote ends none either: the regex, not the split
@example(['\\"', "\n", "["])  # a stray backslash outside, then a literal holding a newline
def test_escape_scan_flips_at_the_references_depth_on_long_frames(tokens: list[str]) -> None:
    frame = "".join(tokens)
    deepest = _deepest(frame)
    assert not json_depth_exceeds(frame, deepest)
    if deepest:
        assert json_depth_exceeds(frame, deepest - 1)
