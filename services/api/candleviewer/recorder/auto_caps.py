"""Per-session auto-record trigger limits (E16-FR-01, #1738; threat model R-S1, R-D2).

One session (one authenticated client) may hold chart-open triggers for at most
`max_per_session` distinct symbols, and may add at most `rate_per_min` NEW distinct symbols in
any sliding 60 s window (on the injected clock). A trigger over either limit is not recorded:
the chart itself stays live-only (AC-02). The global cap on concurrent auto-recorded symbols is
`RecordingPolicy`'s (`CV_RECORDER_MAX_AUTO_SYMBOLS`); this book only bounds what one session
can ask for.

Pure and synchronous (C-2.20: no statechart, no I/O). Every container is bounded (C-2.18): at
most `max_sessions` sessions, least recently used evicted first; per session, the held symbols
by `max_per_session`, the rate window by `rate_per_min`, the denied set by `MAX_DENIED`. A
session id comes from the server-side caller only, never from a client "record" flag.
"""

from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Final, Literal

#: Distinct sessions tracked; the least recently used is evicted past it.
MAX_SESSIONS: Final = 4096
#: Distinct (session, symbol) denials remembered per session, so each is audited once. Past it a
#: denial is still refused and counted, but not audited again (an audit flood is a DoS too).
MAX_DENIED: Final = 1024
WINDOW_S: Final = 60.0

SessionRefusal = Literal["session_cap", "session_rate"]


@dataclass(slots=True)
class _Session:
    held: dict[str, set[str]] = field(default_factory=dict)  # symbol -> chart ids
    starts: deque[float] = field(default_factory=deque)  # admissions of a NEW symbol
    denied: set[str] = field(default_factory=set)


class SessionAutoBook:
    def __init__(
        self, *, max_per_session: int, rate_per_min: int, max_sessions: int = MAX_SESSIONS
    ) -> None:
        if min(max_per_session, rate_per_min, max_sessions) < 1:
            raise ValueError("session limits must be >= 1")
        self._max_held, self._rate, self._max_sessions = max_per_session, rate_per_min, max_sessions
        self._sessions: OrderedDict[str, _Session] = OrderedDict()

    def __len__(self) -> int:
        return len(self._sessions)

    def __contains__(self, session_id: object) -> bool:
        return session_id in self._sessions

    def check(self, session_id: str, symbol: str, now: float) -> SessionRefusal | None:
        """Why `session_id` may not add a trigger for `symbol` now, or None. Changes nothing but
        the rate window's expiry; a symbol the session already holds is always admitted."""
        s = self._sessions.get(session_id)
        if s is None or symbol in s.held:
            return None
        self._expire(s, now)
        if len(s.held) >= self._max_held:
            return "session_cap"
        if len(s.starts) >= self._rate:
            return "session_rate"
        return None

    def commit(self, session_id: str, symbol: str, chart_id: str, now: float) -> None:
        """Record an admitted trigger (after `check` returned None)."""
        s = self._touch(session_id)
        charts = s.held.get(symbol)
        if charts is None:
            charts = s.held[symbol] = set()
            s.starts.append(now)
        charts.add(chart_id)
        s.denied.discard(symbol)

    def first_denial(self, session_id: str, symbol: str) -> bool:
        """True the first time `(session_id, symbol)` is denied: the caller audits it then."""
        s = self._touch(session_id)
        if symbol in s.denied or len(s.denied) >= MAX_DENIED:
            return False
        s.denied.add(symbol)
        return True

    def release(self, session_id: str, symbol: str, chart_id: str, now: float) -> None:
        """A chart closed: the session's slot for `symbol` frees with its last chart."""
        s = self._sessions.get(session_id)
        if s is None:
            return
        charts = s.held.get(symbol)
        if charts is not None:
            charts.discard(chart_id)
            if not charts:
                del s.held[symbol]
        self._expire(s, now)
        if not (s.held or s.starts):
            del self._sessions[session_id]

    def _touch(self, session_id: str) -> _Session:
        s = self._sessions.get(session_id)
        if s is None:
            s = self._sessions[session_id] = _Session()
            while len(self._sessions) > self._max_sessions:
                self._sessions.popitem(last=False)
        else:
            self._sessions.move_to_end(session_id)
        return s

    @staticmethod
    def _expire(s: _Session, now: float) -> None:
        while s.starts and now - s.starts[0] >= WINDOW_S:
            s.starts.popleft()
