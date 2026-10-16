"""#410 scenario 4: a planned restart is announced before it happens (§9.4, client duty C12).

The stop is the production one: `server.should_exit` (what SIGTERM sets) makes
`PlannedShutdownServer` run `WsRuntime.stop()` (notice, grace, `bye` + `1001`) before uvicorn's own
shutdown, which would send a bare `1012`. The grace is on the virtual clock, so the test sits inside
it. A second server process then starts on a new port behind the same proxy while clients back off.
"""

from __future__ import annotations

import pytest

from candleviewer.ws.metrics import cv_ws_closes_total
from tests.chaos.ws._client import BACKOFF, PRIVATE, each
from tests.chaos.ws._server import BOOK, DOWNTIME_MS, GRACE_MS, GRACE_S, SEED, WORKSPACES, Stack
from tests.unit.ws._seq_support import USER, validate

pytestmark = pytest.mark.chaos

# A client's log from the close on (no refresh: a restart is not a 4401, the session survives).
OUTAGE = ["closed", "backoff", "refused", "backoff", "open", "auth_ok", "order_entry"]


def closes(reason: str) -> float:
    samples = (s for fam in cv_ws_closes_total.collect() for s in fam.samples)
    return sum(
        s.value for s in samples if s.name.endswith("_total") and s.labels["reason"] == reason
    )


async def test_s4_restart_notice_then_1001_close_then_clients_come_back(stack: Stack) -> None:
    clients = [
        stack.client(await stack.sessions.mint(str(USER)), SEED + n).start(*topics)
        for n, topics in enumerate(WORKSPACES)
    ]
    await each(clients, lambda c: c.synced, "first snapshots")
    shutdowns = closes("shutdown")

    stack.server.should_exit = True  # SIGTERM; the planned shutdown starts at uvicorn's next tick
    await each(clients, lambda c: c.system("shutdown_notice") != [], "shutdown_notice")
    for c in clients:
        (i,) = c.system("shutdown_notice")
        validate(c.frames[i])
        notice = c.frames[i]["p"]
        assert (notice["reason"], notice["closing_in_ms"]) == ("deploy", GRACE_MS)
        assert notice["expected_downtime_ms"] == DOWNTIME_MS
        assert not c.order_entry  # C12: the ticket is off from the notice, not from the close
        assert c.closes == [] and "bye" not in {f["t"] for f in c.frames}

    # The grace is real: data still flows 4 s into it, and only its end closes the sockets.
    assert stack.book_step() == len(clients)
    await each(clients, lambda c: c.seq.get(BOOK) == 2, "delta in the grace")
    await stack.clock.advance(GRACE_S - 1)
    assert stack.book_step() == len(clients)
    await each(clients, lambda c: c.seq.get(BOOK) == 3, "delta late in the grace")
    await stack.clock.advance(1)
    await each(clients, lambda c: c.closes == [1001], "bye + 1001")  # not 1006, not uvicorn's 1012
    for c in clients:  # the notice, then the bye as the last frame: nothing is sent after it
        bye = c.frames[-1]
        assert c.system("shutdown_notice")[0] < len(c.frames) - 1
        assert (bye["t"], bye["p"]["code"], bye["p"]["reason"]) == ("bye", 1001, "shutdown")
        assert bye["p"].get("retry_after_ms") == DOWNTIME_MS and bye["p"]["reconnect"] is True
    await stack.until_stopped()  # uvicorn's own shutdown ran after the planned one
    assert len(stack.gateway) == 0 and closes("shutdown") - shutdowns == len(clients)

    # Outage: back off (attempt 1), dial the dead port (refused), back off again (attempt 2).
    first = [await c.next_backoff() for c in clients]
    assert len(set(first)) == len(clients)  # full jitter: the herd is spread
    await stack.clock.advance(max(first))
    second = [await c.next_backoff() for c in clients]
    for attempt, delays in enumerate((first, second)):
        base, jitter = BACKOFF[attempt]
        assert all(abs(d - base) <= jitter for d in delays)
    stack.restart()  # a new process on a new port, behind the same proxy
    await stack.clock.advance(max(second))
    await each(clients, lambda c: c.sessions == 2 and c.synced, "resubscribed after restart")
    assert stack.book_step() == len(clients)
    await each(clients, lambda c: c.seq.get(BOOK) == 2, "delta after restart")

    for c in clients:
        events = [e[1] for e in c.log]
        assert events.index("order_entry") < events.index("closed")  # off before the close ...
        assert events[events.index("closed") :] == OUTAGE  # ... on again at the new `auth_ok`
        assert c.order_entry and c.closes == [1001] and c.gaps == []
        assert not [f for f in c.frames if f["t"] in {"err", "revoked"}]
        frames = c.frames[[f["t"] for f in c.frames].index("welcome", 1) :]  # the second socket
        want = [e["ch"] for e in c.topics]
        kinds = [ch.split(".")[0] in PRIVATE for ch in want]
        assert kinds == sorted(kinds, reverse=True)  # private topics first (§9.3) ...
        assert [f["ch"] for f in frames if f["t"] == "snap"] == want  # ... every one re-snapshot
        (sub_ok,) = (f for f in frames if f["t"] == "sub_ok")
        assert [r["ch"] for r in sub_ok["p"]["results"]] == want
    refused = sum(e[1] == "refused" for c in clients for e in c.log)
    assert refused == sum(e == "down" for e, _ in stack.proxy.trace) == len(clients)
    assert len(stack.gateway) == len(clients)
