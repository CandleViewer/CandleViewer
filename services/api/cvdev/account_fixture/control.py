"""#2893 S10: the fixture clock and per-key runtime switching, as files in `CV_ACCOUNT_FIXTURE_DIR`.

Both are dev/test stack state that survives a restart (test plan section 9.5) and that a process
other than the stack's may set, so they live beside the request log:

- `clock`: the fixture clock (ADR-0036 decision 5), #2086's `OffsetFileClock` on its own file:
  signed decimal seconds, at most 9 integer and 6 fraction digits. Real UTC plus that offset is
  the stub's scenario and exchange time and the request log's `ts`. It never moves auth time:
  `Settings` refuses `CV_TEST_CLOCK` while the fixture is on, and the stub never judges a
  request's signing timestamp or receive window, which keep the signer's own clock.
- `keys/<key id>.json`: one pack key's scenario, the overlays seeded for it and when its scenario
  started on the fixture clock, `{"scenario": ..., "overlays": [...], "started": <ISO 8601 with
  offset>}`. The transport writes it at the key's first signed call, as the scenario the key is
  stored under (`anchor`), and a switch replaces it (`switch`; test plan section 9.3), so a key's
  times and a switch survive a restart. It never names a secret: the signature stays checked
  against the scenario the key id names (scope 6), whatever the key is switched to.

`FixtureClock.set` and `advance` and `KeyStates.switch` are the control surface: in process for
tests, and on a stack through the command line S14 adds, which calls them. A harness may instead
write a file the same way, to a temporary file and then renamed into place, as #2086's harness
does; the transport checks each key file it reads and refuses a request whose file breaks the
rules. The reads and writes block, so the transport makes them off the event loop.

`KeyStates` holds `keys/` open from boot and reads, links and renames only relative to that
descriptor, each access first checking that the path still names it: `keys/` replaced after boot,
by a symlink or anything else, or removed, refuses every key (`KeyStateError`), never followed.
Each write stages a new 0600 file (`O_EXCL`) and removes it on any failure. Nothing here imports
`candleviewer.secrets` or `candleviewer.audit`.
"""

from __future__ import annotations

import contextlib
import json
import os
import stat
import weakref
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

from candleviewer.auth.testnet_clock import OffsetFileClock
from cvdev.account_fixture.guards import stored_under
from cvdev.account_fixture.pack import OVERLAY, Pack, fixture_key_ids, manifest, scenario_names
from cvdev.account_fixture.requestlog import RequestLog

CLOCK_FILE: Final = "clock"
KEYS_DIR: Final = "keys"
#: What `OffsetFileClock` reads: at most 9 integer digits of seconds.
_MAX_OFFSET_S: Final = 10**9
_MAX_KEY_FILE_BYTES: Final = 4096
_FILE_RULE: Final = "a key file is a regular file of at most 4 KiB: scenario, overlays, started"
_DIR_RULE: Final = "the key files' directory must be the one held since boot, not a symlink"
#: How often a first call's anchor retries a key file that a rename removed meanwhile.
_ANCHOR_ATTEMPTS: Final = 3
_US: Final = timedelta(microseconds=1)
#: A FIFO never blocks the open; a symlink as the last component fails it (as #2728's clock read).
_OPEN_FLAGS: Final = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW
_DIR_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_STAGE_FLAGS: Final = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC


class KeyStateError(ValueError):
    """A switch off the pack, or a key file off the rules: names the rule, never a key."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _staged(dir_fd: int, text: str) -> str:
    """The name of a new file holding `text` in the directory `dir_fd`, mode 0600, to rename or
    link into place; removed again if it cannot be written whole."""
    name = f".staged-{os.urandom(8).hex()}"
    fd = os.open(name, _STAGE_FLAGS, 0o600, dir_fd=dir_fd)
    try:
        view = memoryview(text.encode("ascii"))
        while view:
            view = view[os.write(fd, view) :]
    except BaseException:
        os.unlink(name, dir_fd=dir_fd)
        raise
    finally:
        os.close(fd)
    return name


def _replace(dir_fd: int, name: str, text: str) -> None:
    """`name` in the directory `dir_fd` now holds `text`, renamed into place; nothing staged is
    left if the rename fails."""
    staged = _staged(dir_fd, text)
    try:
        os.replace(staged, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    except BaseException:
        os.unlink(staged, dir_fd=dir_fd)
        raise


class FixtureClock:
    """Real UTC plus the offset in `<directory>/clock`: the stub's clock on a fixture stack."""

    def __init__(
        self, directory: str | os.PathLike[str], *, now: Callable[[], datetime] = _utc_now
    ) -> None:
        self._path, self._now = Path(directory) / CLOCK_FILE, now
        self._read = OffsetFileClock(self._path, now=now)

    def __call__(self) -> datetime:
        return self._read()

    def set(self, moment: datetime) -> None:
        """The clock reads `moment` now, and runs on with real time from there."""
        if moment.utcoffset() is None:
            raise ValueError("the fixture clock is set to a timezone-aware moment")
        micros = (moment - self._now()) // _US
        seconds, fraction = divmod(abs(micros), 1_000_000)
        if seconds >= _MAX_OFFSET_S:
            raise ValueError("the fixture clock's offset must stay under 10**9 seconds")
        text = f"{'-' if micros < 0 else ''}{seconds}.{fraction:06d}"
        dir_fd = os.open(self._path.parent, _DIR_FLAGS)
        try:
            _replace(dir_fd, CLOCK_FILE, text)
        finally:
            os.close(dir_fd)

    def advance(self, delta: timedelta) -> None:
        self.set(self() + delta)


@dataclass(frozen=True, slots=True)
class KeyState:
    """What a pack key answers as: `scenario` with `overlays` seeded, from `started`."""

    scenario: str
    overlays: tuple[str, ...]
    started: datetime


class KeyStates:
    """The pack keys' files in `<directory>/keys`. `clock` is the fixture clock; `log` the request
    log, where each switch is one `switch` line (test plan section 9.6)."""

    def __init__(
        self,
        directory: str | os.PathLike[str],
        pack: Pack,
        *,
        log: RequestLog,
        clock: Callable[[], datetime],
    ) -> None:
        self._dir, self._log, self._clock = Path(directory) / KEYS_DIR, log, clock
        with contextlib.suppress(FileExistsError):
            self._dir.mkdir(mode=0o700)
        try:
            self._dir_fd = os.open(self._dir, _DIR_FLAGS)
        except OSError as exc:
            raise KeyStateError(_DIR_RULE) from exc
        weakref.finalize(self, os.close, self._dir_fd)
        held = os.fstat(self._dir_fd)
        self._held = (held.st_dev, held.st_ino)
        self._key_ids = fixture_key_ids(pack)
        self._targets = frozenset(stored_under(key) for key in self._key_ids)
        manifests = {name: manifest(pack, name) for name in scenario_names(pack)}
        self._overlays = frozenset(n for n, m in manifests.items() if m.get("origin") == OVERLAY)
        self._switch_to = {n: str(m["switch_to"]) for n, m in manifests.items() if "switch_to" in m}

    def read(self, key_id: str) -> KeyState | None:
        """The key's state, None before its first call; `KeyStateError` for a file off the rules
        (not a regular file, a symlink, over 4 KiB, or not exactly the three fields)."""
        try:
            fd = os.open(self._name(key_id), _OPEN_FLAGS, dir_fd=self._dir_fd)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise KeyStateError("a key file must be a regular file, not a symlink") from exc
        try:
            regular = stat.S_ISREG(os.fstat(fd).st_mode)
            raw = os.read(fd, _MAX_KEY_FILE_BYTES + 1) if regular else b""
        finally:
            os.close(fd)
        if not regular or len(raw) > _MAX_KEY_FILE_BYTES:
            raise KeyStateError(_FILE_RULE)
        try:
            body = json.loads(raw)
            started, overlays = datetime.fromisoformat(body.pop("started")), body.pop("overlays")
            if not isinstance(overlays, list):  # a dict or a string would read as its names
                raise KeyStateError(_FILE_RULE)
            state = KeyState(body.pop("scenario"), tuple(overlays), started)
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
            raise KeyStateError(_FILE_RULE) from exc
        if body:
            raise KeyStateError(_FILE_RULE)
        return self._checked(state)

    def anchor(self, key_id: str, now: datetime) -> KeyState:
        """The key's state, written at its first signed call as the scenario it is stored under,
        started `now`. Never over a file already there: a switch made meanwhile stands. A file
        that appears and is renamed away again on every attempt refuses the call."""
        for _ in range(_ANCHOR_ATTEMPTS):
            if (state := self.read(key_id)) is not None:
                return state
            state = KeyState(stored_under(key_id), (), now)
            staged = _staged(self._dir_fd, _text(state))
            try:
                name, fd = self._name(key_id), self._dir_fd
                os.link(staged, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
            except FileExistsError:
                continue
            finally:
                os.unlink(staged, dir_fd=self._dir_fd)
            return state
        raise KeyStateError("a key file kept changing during its first call: refused")

    def switch(
        self, key_id: str, scenario: str | None = None, *, overlays: Sequence[str] = ()
    ) -> KeyState:
        """Switch a stored pack key at runtime to key scenario `scenario` (by default its stored
        scenario's `switch_to`) with `overlays` seeded. Its scenario time restarts now, on the
        fixture clock (pack README, "Scenario time"); its key id, secret and account stay. The
        file is replaced first, then the switch logged: a log that cannot write raises."""
        name = self._name(key_id)
        target = scenario or self._switch_to.get(stored_under(key_id))
        if target is None:
            raise KeyStateError("the key's scenario names no switch_to: name the target")
        state = self._checked(KeyState(target, tuple(overlays), self._clock()))
        _replace(self._dir_fd, name, _text(state))
        self._log.write(
            outcome="switch",
            signing_key_id=key_id,
            key_class="fixture",
            scenario=target,
            stored_under=stored_under(key_id),
            overlays=state.overlays,
        )
        return state

    def _name(self, key_id: str) -> str:
        """The key's file name in the held `keys/`, which its path must still name."""
        if key_id not in self._key_ids:
            raise KeyStateError("only a pack key id has a key file")
        try:
            now = os.stat(self._dir, follow_symlinks=False)
        except OSError as exc:
            raise KeyStateError(_DIR_RULE) from exc
        if (now.st_dev, now.st_ino) != self._held:
            raise KeyStateError(_DIR_RULE)
        return f"{key_id}.json"

    def _checked(self, state: KeyState) -> KeyState:
        """A key scenario of the pack (never an overlay or a rotation pair), distinct overlays of
        the pack, and a timezone-aware start."""
        overlays = state.overlays
        if (
            not isinstance(state.scenario, str)
            or state.scenario not in self._targets
            or not all(isinstance(name, str) and name in self._overlays for name in overlays)
            or len(set(overlays)) != len(overlays)
            or state.started.utcoffset() is None
        ):
            raise KeyStateError("a key switches to a key scenario, with distinct pack overlays")
        return state


def _text(state: KeyState) -> str:
    body = {"scenario": state.scenario, "overlays": list(state.overlays)}
    return json.dumps(body | {"started": state.started.isoformat()})
