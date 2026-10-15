"""SR-185 allocation bound of the `cv.v1.msgpack` client decoder, for its bounds tests
(`test_msgpack_decode_bounds.py`) and its nightly fuzz targets.

What one decode can hold live, from the codec's caps (#2509):
- Open levels: at most 1 024 (the C unpacker's stack), each a list pre-sized to its cap:
  1 024 x (56 + 8 x 128) B, about 1.05 MiB.
- What open levels hold before they complete, at most 127 values per array level: the worst is a
  32 B int per input byte, 1 024 x 127 x 32 B, about 4 MiB. A map level holds at most 31 pairs,
  each a 56 B tuple plus its key and value: under the array case.
- Completed containers, which the budget charges: at most 16 384 values, about 90 B each at the
  densest (one-entry maps with keys unique to the frame), about 1.4 MiB.

That sums to about 6.5 MiB per frame, under `MAX_PEAK_BYTES`. The worst shape measured, open array
levels each holding five one-entry maps with frame-unique keys and 122 ints, peaks at 6.1 to
6.5 MiB, depending on the process.

One more term is not per frame. msgpack interns every string map key into CPython's process-wide
interned-string table, and a slot used there is only reclaimed when the table resizes. So any
decode that brings new keys can be the one that resizes it, and the resize allocates a table sized
by the whole process's interned population, not by the frame (`interned_resize_bytes`). That
allocation is transient: the keys are released with the frame. A JSON frame has no such term.
"""

from __future__ import annotations

import sys
from typing import Final

#: Per-frame bound; the JSON path's worst at the cap is about 6 MiB.
MAX_PEAK_BYTES: Final = 8 << 20
#: Keys one at-cap frame can bring: 31 per open map level, plus every budgeted map entry.
MAX_FRAME_KEYS: Final = 40_000


def _table_bytes(entries: int) -> int:
    """The table CPython 3.12 allocates when a dict keyed by strings resizes at `entries`: the
    next power of two above 3 x entries slots, a 4 B index per slot and a 16 B entry for two
    slots in three."""
    slots = 1 << (3 * entries - 1).bit_length()
    return slots * 4 + (2 * slots // 3) * 16


def interned_resize_bytes() -> int:
    """The largest table one resize of the interned-string table can allocate now."""
    return _table_bytes(sys.getunicodeinternedsize() + MAX_FRAME_KEYS)


def smallest_resize_bytes() -> int:
    """The smallest table a resize of the interned-string table can allocate now."""
    return _table_bytes(sys.getunicodeinternedsize())


def peak_bound() -> int:
    """What one decode may peak at in this process: the frame, plus one interned-table resize."""
    return MAX_PEAK_BYTES + interned_resize_bytes()
