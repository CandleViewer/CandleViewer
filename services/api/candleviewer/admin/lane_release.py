"""Offline release of a held audit lane (ADR-0037 decisions 8 and 9; #3009 slice S2c).

`docs/plan/24-internal-schemas.md` §15.6 Release owns the rules. Under `lane.lock`, taken
exclusively without waiting (so only while cv-api is stopped), and with the key from S2b-1's loader
only, the command scans the lane as a boot would, with no note, refuses unless that scan holds at a
frame at exactly the position the operator names, copies the held bytes to `quarantine/` and only
then writes the MAC'd `released` note; every open is `O_NOFOLLOW`. The next boot's `released` row,
with the operator's words, is the release's audit record: the break-glass journal admits only its
own actions (R3) and a held lane takes no append. No log line carries the words or a key.
"""

from __future__ import annotations

import argparse
import functools
import os
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

import structlog

from candleviewer.audit import lane_journal as lj
from candleviewer.audit.lane import lane_dir
from candleviewer.audit.lane_lock import LaneUnanchored, take_lane_lock
from candleviewer.audit_lane_wiring import LaneKeyRefused, load_lane_keys
from candleviewer.observability.logging import configure_logging
from candleviewer.settings import Settings, load_settings

#: The operator's words (§15.6 Release): trimmed, printable (break-glass `_label`'s rule), capped.
WORD_MAX = {"operator": 64, "ticket": 64, "operator_reason": 280}
_POSITION = re.compile(r"([0-9]{1,20}):([0-9]{1,20})")


class ReleaseExit(IntEnum):
    """The exit status: 0 once the note is written; 2 is argparse's (an argument refused)."""

    RELEASED = 0
    LANE_UNAVAILABLE = 4  # no lane key (no real audit backend), an unanchored or unreadable lane
    API_RUNNING = 5  # `lane.lock` is held: cv-api runs
    NOT_HELD = 6  # the scan holds at no frame a note applies to (§15.6 Hold)
    HOLD_MISMATCH = 7  # the scan holds, but not at the position the operator named


class ReleaseRefused(Exception):
    """A refusal before anything was written; the message is for the operator's terminal."""

    def __init__(self, status: ReleaseExit, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class Released:
    """What the note covers: positions, a `seq` and a byte count, all safe to log."""

    hold: lj.Pos
    end: lj.Pos
    from_seq: int
    size: int


def release(
    audit_wal_path: str, keys: lj.LaneKeys, hold: lj.Pos, words: tuple[str, ...]
) -> Released:
    """§15.6 Release under `lane.lock`, taken without waiting through the audit directory's
    descriptor (SEC-REM-03); a missing `lane/` is refused, never made. Closing the descriptor
    drops the lock."""
    try:
        fd = take_lane_lock(audit_wal_path, create=False)
    except LaneUnanchored as exc:  # its rule's words, never the path
        raise ReleaseRefused(ReleaseExit.LANE_UNAVAILABLE, str(exc)) from None
    except BlockingIOError:
        raise ReleaseRefused(ReleaseExit.API_RUNNING, "lane.lock is held by cv-api") from None
    try:
        return _release(lj.LaneFiles(lane_dir(audit_wal_path)), keys, hold, words)
    finally:
        os.close(fd)


def _release(
    files: lj.LaneFiles, keys: lj.LaneKeys, hold: lj.Pos, words: tuple[str, ...]
) -> Released:
    names = os.listdir(files.dir)
    read = functools.cache(files.read)
    marker = read("confirmed") if "confirmed" in names else None
    found = lj.scan(keys, marker=marker, names=names, read=read)
    seq = found.state.next_seq
    if not found.held or found.hold is None or found.lane is None or seq is None:
        raise ReleaseRefused(ReleaseExit.NOT_HELD, "the lane does not hold at a frame")
    end, data = lj.held_span(keys, found.lane, names, read, found.hold)
    if not data:  # held at the end of the data, no segment name left (rows 13 and 16)
        raise ReleaseRefused(ReleaseExit.NOT_HELD, "the lane does not hold at a frame")
    if found.hold != hold:
        at = f"{found.hold[0]}:{found.hold[1]}"
        raise ReleaseRefused(ReleaseExit.HOLD_MISMATCH, f"the lane holds at {at}, not there")
    files.quarantine(f"{lj.segment_name(hold[0])}.{hold[1]}", data)  # copy, then note
    note = lj.encode_note(keys, lane=found.lane, hold=hold, end=end, from_seq=seq, words=words)
    files.write_note(note)
    return Released(hold, end, seq, len(data))


def _position(text: str) -> lj.Pos:
    match = _POSITION.fullmatch(text)
    if match is None:
        raise argparse.ArgumentTypeError("must be SEGMENT:OFFSET, two decimal numbers")
    return int(match[1]), int(match[2])


def _words(cap: int) -> Callable[[str], str]:
    def check(text: str) -> str:
        text = text.strip()
        if not text or len(text) > cap or not text.isprintable():
            raise argparse.ArgumentTypeError(f"must be 1 to {cap} printable characters")
        return text

    return check


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m candleviewer.admin.lane_release",
        description="Release a held audit lane frame (ADR-0037); cv-api must be stopped.",
    )
    parser.add_argument("--hold", required=True, type=_position, help="SEGMENT:OFFSET, as logged")
    for name, cap in WORD_MAX.items():  # --operator, --ticket, --operator-reason
        parser.add_argument(f"--{name.replace('_', '-')}", required=True, type=_words(cap))
    return parser


def main(argv: Sequence[str] | None = None, *, settings: Settings | None = None) -> int:
    """`python -m candleviewer.admin.lane_release`; returns a `ReleaseExit` status."""
    args = _parser().parse_args(argv)
    done: Released | None = None
    try:
        config = load_settings() if settings is None else settings
        if settings is None:  # the process entrypoint: the redacting log chain first (main.py)
            env, level, fmt = config.environment.value, config.log_level, config.log_format
            configure_logging(env=env, level=level, fmt=fmt)
        material = load_lane_keys(config)  # S2b-1's loader: the key file, nothing else
        if material is None:
            raise ReleaseRefused(ReleaseExit.LANE_UNAVAILABLE, "no real audit backend, no lane")
        keys = lj.LaneKeys(material.current, material.previous)
        words = tuple(getattr(args, name) for name in lj.NOTE_WORDS)
        done = release(config.audit_wal_path, keys, args.hold, words)
        status, line = ReleaseExit.RELEASED, "the note is written; start cv-api to apply it"
    except ReleaseRefused as exc:
        status, line = exc.status, str(exc)
    except LaneKeyRefused as exc:  # it names the setting and the rule, never a key
        status, line = ReleaseExit.LANE_UNAVAILABLE, str(exc)
    except (ValueError, lj.LaneError, OSError) as exc:  # a setting or a lane file: its class only
        status, line = ReleaseExit.LANE_UNAVAILABLE, f"unusable lane ({type(exc).__name__})"
    span = {} if done is None else {"end": done.end, "from_seq": done.from_seq, "bytes": done.size}
    _log().warning("audit.lane.release", outcome=status.name.lower(), hold=args.hold, **span)
    sys.stdout.write(f"{status.name.lower()}: {line}\n")
    return int(status)


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


if __name__ == "__main__":
    raise SystemExit(main())
