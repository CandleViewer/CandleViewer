"""#410 scenario 5: the access token expires while the client is cut off and backing off.

The outage is a proxy REFUSE window, so REST is unreachable too (the refresh goes through the
proxy like everything else). The token's expiry is the real ADR-0020 TTL of the real
`SessionService`, on the virtual clock the gateway also reads.
"""

from __future__ import annotations

import pytest

from candleviewer.auth.errors import SessionNotFound
from candleviewer.auth.session_service import ACCESS_TOKEN_TTL
from tests.chaos.ws._client import BACKOFF, REFRESH_MARGIN_MS
from tests.chaos.ws._proxy import Fault
from tests.chaos.ws._server import BOOK, Stack
from tests.unit.ws._seq_support import ACC_A, USER

pytestmark = pytest.mark.chaos

TOPICS = {BOOK, "trades.BTCUSDT", "orders"}
EXPIRY_S = ACCESS_TOKEN_TTL.total_seconds()  # minted at virtual t=0


async def test_s5_token_expiring_in_an_outage_is_refreshed_before_the_reconnect(
    stack: Stack,
) -> None:
    minted = await stack.sessions.mint(str(USER))
    await stack.clock.advance(EXPIRY_S - 120)  # connect two minutes before the token dies
    c = stack.client(minted).start(
        {"ch": BOOK},
        {"ch": "trades.BTCUSDT"},
        {"ch": "orders", "opts": {"exchange_account_ids": [str(ACC_A)]}},
    )
    await c.until(lambda: c.snapped == TOPICS, "first snapshots")
    stack.proxy.inject(Fault.REFUSE)
    stack.proxy.inject(Fault.DROP)
    await stack.until_no_connections()
    delay = await c.next_backoff()
    while stack.clock.now + delay < EXPIRY_S:  # refused attempts until a wake falls past expiry
        await stack.clock.advance(delay)
        delay = await c.next_backoff()
    stack.proxy.inject(Fault.HEAL)
    await stack.clock.advance(delay)
    await c.until(lambda: c.sessions == 2 and c.snapped == TOPICS, "resubscribed")
    assert stack.book_step() == 1 and stack.private("orders", ACC_A) == 1
    await c.until(lambda: c.seq.get(BOOK) == 2 and c.seq.get("orders") == 2, "post-outage deltas")

    with pytest.raises(SessionNotFound):  # the first token really is dead on the server
        await stack.sessions.authenticate_access_token(minted.access_token)
    refreshes = [(t, ok) for t, ev, *rest in c.log if ev == "refresh" for ok in rest]
    failed, (done_at, ok) = refreshes[:-1], refreshes[-1]
    assert ok and done_at >= EXPIRY_S  # refreshed after the token died ...
    assert failed and not any(ok for _, ok in failed)  # ... REST being down until then ...
    assert min(t for t, _ in refreshes) >= EXPIRY_S - REFRESH_MARGIN_MS / 1000  # ... once due
    opened = [i for i, e in enumerate(c.log) if e[1] == "open"][-1]
    assert c.log.index((done_at, "refresh", True)) == opened - 1  # ... and right before the socket
    # The new socket authenticated the rotated session: no err, no bye, no 4401 (no loop).
    first, second = (f["p"]["session_id"] for f in c.frames if f["t"] == "auth_ok")
    assert first == str(minted.session_id) != second
    assert not [f for f in c.frames if f["t"] in {"err", "bye"}]
    assert c.closes == [1006] and c.gaps == []
    # It backed off on the §9.2 ladder with jitter, out to the 30 s cap.
    ladder = [(e[2], e[3]) for e in c.log if e[1] == "backoff"]
    for attempt, wait in ladder:
        base, jitter = BACKOFF[min(attempt, len(BACKOFF)) - 1]
        assert abs(wait - base) <= jitter
    assert max(a for a, _ in ladder) > len(BACKOFF) and len({w for _, w in ladder}) == len(ladder)
    assert ("drop", 1) in stack.proxy.trace
    assert sum(e == "refused" for e, _ in stack.proxy.trace) == len(ladder) - 1


async def test_s5b_token_expiring_on_a_live_socket_costs_exactly_one_4401(stack: Stack) -> None:
    minted = await stack.sessions.mint(str(USER))
    c = stack.client(minted).start({"ch": BOOK})
    await c.until(lambda: c.snapped == {BOOK}, "first snapshot")
    await stack.clock.advance(EXPIRY_S)  # no in-place re-auth: the server ends the identity
    await c.until(lambda: c.closes == [4401], "bye token_expired + 4401")
    assert [f["p"]["reason"] for f in c.frames if f["t"] == "bye"] == ["token_expired"]
    await stack.clock.advance(await c.next_backoff())
    await c.until(lambda: c.sessions == 2 and c.snapped == {BOOK}, "refreshed and resubscribed")
    events = [e[1] for e in c.log]
    assert events[events.index("closed") :] == ["closed", "backoff", "refresh", "open", "auth_ok"]
    assert c.closes == [4401] and c.gaps == []  # one 4401 for one expiry: no loop
