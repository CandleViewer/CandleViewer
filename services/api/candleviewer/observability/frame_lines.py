"""The WebSocket frame lines of `uvicorn.error` name a frame, never its payload (#415, SR-122).

At DEBUG the websockets server logs each frame it reads or writes as `< %s` or `> %s`, with the
frame as the one argument. `FrameLineFilter` replaces that argument with the frame's opcode and
length (`TEXT [85 bytes]`), so the line carries no payload, at any level. Any other line, and a
`< %s` or `> %s` line whose argument is not a frame, is left as it is. `configure_logging()`
installs the one instance on the logger, ahead of every handler, so stdout and the support
bundle's buffer get the same line; `reset_logging()` removes it.
"""

from __future__ import annotations

import logging
from typing import Final

from websockets.frames import Frame

#: The websockets frame lines (`websockets/protocol.py`): one argument, the frame.
_FRAME_LINES: Final = frozenset({"< %s", "> %s"})


class FrameLineFilter(logging.Filter):
    """A websockets frame line shows the frame's opcode and length, not its payload."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if record.msg in _FRAME_LINES and isinstance(args, tuple) and len(args) == 1:
            if isinstance(frame := args[0], Frame):
                record.args = (frame_summary(frame),)
        return True


def frame_summary(frame: Frame) -> str:
    """`OPCODE [n bytes]`, and `, continued` for a fragment that is not the last."""
    size = len(frame.data)
    more = "" if frame.fin else ", continued"
    return f"{frame.opcode.name} [{size} byte{'' if size == 1 else 's'}{more}]"


FRAME_LINE_FILTER: Final = FrameLineFilter()
