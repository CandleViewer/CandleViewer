"""Whether an object has been frozen (`gc.freeze()`), for the startup heap freeze's tests (#3641).

`gc.get_freeze_count()` cannot say. CPython 3.12 moves a few hundred immortal objects of its own to
the permanent generation in any full collection, so the count is above 0 after a plain
`gc.collect()` (a freeze that never happened would still pass `count > 0`), and it leaves 0 again
once anything collects after an `unfreeze`. `gc.get_objects()` leaves the permanent generation
out, so a tracked object that a test kept alive and that is missing from it is frozen.
"""

from __future__ import annotations

import gc


class Marker:
    """A tracked object for a test to keep alive across a freeze."""


def is_frozen(obj: object) -> bool:
    """Whether `obj`, a tracked object, is in the permanent generation."""
    return not any(o is obj for o in gc.get_objects())
