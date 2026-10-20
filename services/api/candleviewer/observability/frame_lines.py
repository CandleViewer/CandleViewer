"""The WebSocket frame lines of `uvicorn.error` name a frame, never its payload (#415, SR-122).

At DEBUG the websockets server logs each frame it reads or writes as `< %s` or `> %s`, with the
frame as the one argument. `FrameLineFilter` replaces that argument with the frame's opcode and
length (`TEXT [85 bytes]`), so the line carries no payload, at any level. Any other line, and a
`< %s` or `> %s` line whose argument is not a frame, is left as it is. `configure_logging()`
installs the one instance on the logger, ahead of every handler, so stdout and the support
bundle's buffer get the same line; `reset_logging()` removes it.

Written for the sans-I/O implementation the server runs (`server.CvWebSocketsProtocol` subclasses
uvicorn's `WebSocketsSansIOProtocol`, which logs `websockets.frames.Frame`). A frame is matched by
its shape, so the legacy implementation's `Frame`, a named tuple, is summarised as well.
"""

from __future__ import annotations

import logging
from typing import Final

from websockets.frames import Opcode

#: The websockets frame lines (`websockets/protocol.py`): one argument, the frame.
_FRAME_LINES: Final = frozenset({"< %s", "> %s"})


class FrameLineFilter(logging.Filter):
    """A websockets frame line shows the frame's opcode and length, not its payload."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg, args = record.msg, record.args
        # A message that is not text (a dict, a list) is never looked up: it may have no hash.
        if isinstance(msg, str) and msg in _FRAME_LINES and isinstance(args, tuple):
            if len(args) == 1 and (summary := frame_summary(args[0])) is not None:
                record.args = (summary,)
        return True


def frame_summary(value: object) -> str | None:
    """`OPCODE [n bytes]`, and `, continued` for a fragment that is not the last; None when `value`
    is not a frame. A frame is matched by its shape, an `Opcode`, bytes-like `data` and a bool
    `fin`, which the `Frame` of either websockets implementation has."""
    opcode, data, fin = (getattr(value, name, None) for name in ("opcode", "data", "fin"))
    if not isinstance(opcode, Opcode) or not isinstance(fin, bool):
        return None
    if not isinstance(data, bytes | bytearray | memoryview):
        return None
    size, more = len(data), "" if fin else ", continued"
    return f"{opcode.name} [{size} byte{'' if size == 1 else 's'}{more}]"


FRAME_LINE_FILTER: Final = FrameLineFilter()
