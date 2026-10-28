"""#3963 scenario "A revoked key closes its stream" (SR-E27-17, KV-E13, AC-28; 24 §14.2 rule 13), on
the real B13 interpreter, a fake venue and a virtual clock.

`close_key` closes every stream on the key before it returns and names their accounts: the
socket is closed, `closed(key_revoked)` (or `key_rotated`) is the stream's last item, and the key
is tombstoned, so nothing dials with it again and a new stream on it is refused before anything
is signed or dialled. A revoke landing while M2 signs the `auth` sends no `auth` frame. Only an
operator's `reopen` (for a key three refusals marked) or a new key opens streams again; a
revoked key stays closed.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest

from candleviewer.exchange.base.errors import AuthError
from candleviewer.exchange.base.models import PrivateStreamStatus
from candleviewer.exchange.bybit.private_stream import CLOSE_TIMEOUT_S
from candleviewer.observability.context import spawn
from candleviewer.secrets import CredentialBorrower, RequestSignature
from tests._signing import Call, fake_capability
from tests.chaos.ingestion._clock import VirtualClock
from tests.unit.exchange.bybit._private_venue import (
    REFUSED_AUTH,
    Consumer,
    PrivateVenue,
    make_streams,
    until,
)
from tests.unit.exchange.bybit._trading import ACCOUNT_A, ACCOUNT_B, SIGNER_ID, account

NEW_KEY = "00000000-0000-4000-8000-0000000000c2"


@pytest.mark.parametrize("reason", ["key_revoked", "key_rotated"])
async def test_closing_a_key_closes_its_streams_before_the_call_returns(reason: Any) -> None:
    clock, calls = VirtualClock(), list[Call]()
    venue = PrivateVenue(clock)
    streams = make_streams(venue, calls=calls)
    mine = Consumer(await streams.open(account(ACCOUNT_A)))
    other_key = account(ACCOUNT_B, key_ref=NEW_KEY)
    theirs = Consumer(await streams.open(other_key))
    await until(
        clock, lambda: len(mine.statuses()) == len(theirs.statuses()) == 2, within_s=5, what="l"
    )
    closed = await streams.close_key(account().key_ref, reason=reason)
    assert closed == (ACCOUNT_A,)
    assert venue.sockets[0].closed and not venue.sockets[1].closed  # only the key's stream
    await clock.settle()
    assert mine.statuses()[-1] == f"closed:{reason}:1" and mine.task.done()
    signed, dialled = len(calls), len(venue.dialled)
    await clock.advance(600)  # ten minutes: no dial with the key
    assert (len(calls), len(venue.dialled)) == (signed, dialled)
    with pytest.raises(AuthError):
        await streams.open(account(ACCOUNT_A))
    assert (len(calls), len(venue.dialled)) == (signed, dialled)  # nothing signed or dialled
    await theirs.stop()
    await streams.aclose()


async def test_a_revoke_while_m2_signs_the_auth_sends_no_auth_frame() -> None:
    """The stream checks it is not closing after M2's borrow, and B13's `KILL` cancels the
    `auth` in flight: either way nothing is sent on the revoked key's socket."""
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    entered, release = asyncio.Event(), asyncio.Event()
    calls: list[Call] = []

    async def gated(key_id: UUID, message: Any, purpose: Any) -> RequestSignature:
        entered.set()
        await release.wait()
        return await fake_capability(SIGNER_ID, calls).sign(key_id, message, purpose=purpose)

    streams = make_streams(venue, credentials=CredentialBorrower(gated))
    consumer = Consumer(await streams.open(account()))
    await clock.settle()
    assert entered.is_set() and venue.sent("auth") == []
    assert await streams.close_key(account().key_ref, reason="key_revoked") == (ACCOUNT_A,)
    release.set()
    await clock.advance(60)
    assert venue.sent("auth") == [] and venue.sockets[0].closed
    assert consumer.statuses() == ["closed:key_revoked:1"]
    await streams.aclose()


async def test_a_new_key_opens_a_stream_and_a_revoked_one_never_reopens() -> None:
    """Rotation: the account resubscribes with its new key; an operator's `reopen` clears only a
    key three refusals marked, never a revoked one."""
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams = make_streams(venue)
    old = Consumer(await streams.open(account()))
    await until(clock, lambda: len(old.statuses()) == 2, within_s=5, what="live")
    await streams.close_key(account().key_ref, reason="key_rotated")
    await clock.settle()
    assert streams.reopen(account().key_ref) is False  # a closed key is not reopened
    new = Consumer(await streams.open(account(key_ref=NEW_KEY)))
    await until(clock, lambda: len(new.statuses()) == 2, within_s=5, what="new key live")
    await new.stop()
    await streams.aclose()


async def test_an_operator_reopens_a_key_three_refusals_marked() -> None:
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    venue.auth.extend([REFUSED_AUTH] * 3)
    streams = make_streams(venue)
    refused = Consumer(await streams.open(account(), clock_offset_ms=lambda: 0))
    await until(clock, lambda: refused.task.done(), within_s=60, what="closed")
    with pytest.raises(AuthError):
        await streams.open(account())
    assert streams.reopen(account().key_ref) is True
    assert streams.reopen(account().key_ref) is False  # once
    again = Consumer(await streams.open(account(), clock_offset_ms=lambda: 0))
    await until(clock, lambda: len(again.statuses()) == 2, within_s=5, what="reopened")
    await again.stop()
    await streams.aclose()


async def test_the_adapter_closes_a_keys_streams_and_reopens_through_its_hooks() -> None:
    """E27-S04 (#898) wires these: the service's hooks reach its one registry. Before any stream
    is opened there is no stream to close, and the key is tombstoned all the same (#913
    L1d-2a, RC-G8B-03), so these first calls name another key."""
    from candleviewer.exchange.bybit.service import ExchangeBybitService

    venue = PrivateVenue(VirtualClock())
    adapter = ExchangeBybitService(
        fake_capability(SIGNER_ID), private_ws_connect=venue.connect, environment="demo"
    )
    assert await adapter.close_private_streams(NEW_KEY) == ()
    assert adapter.reopen_private_streams(NEW_KEY) is False  # closed, never marked
    stream = await adapter.open_private_stream(account())
    async with asyncio.timeout(5):  # a guard only: no clock is needed to reach `live`
        for _ in range(2):  # heartbeat, resyncing
            await stream.__anext__()
    closed = await adapter.close_private_streams(account().key_ref, reason="key_rotated")
    assert closed == (ACCOUNT_A,) and venue.sockets[0].closed
    last = await stream.__anext__()
    assert isinstance(last, PrivateStreamStatus) and last.reason == "key_rotated"
    await stream.aclose()
    await adapter.stop(5.0)


async def test_a_close_the_peer_never_finishes_holds_close_key_1_s_at_most() -> None:
    """CR-G8B-C-01, SR-E27-17: a socket's close is bounded (`CLOSE_TIMEOUT_S`): a peer that never
    finishes it holds the revoke 1 s at most, and `closed(key_revoked)` is still the last item."""
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams = make_streams(venue)
    consumer = Consumer(await streams.open(account()))
    await until(clock, lambda: len(consumer.statuses()) == 2, within_s=5, what="live")
    venue.socket.stall_close = True
    revoke = spawn(streams.close_key(account().key_ref, reason="key_revoked"), name="revoke")
    await clock.advance(CLOSE_TIMEOUT_S * 0.9)
    assert not revoke.done()
    await clock.advance(CLOSE_TIMEOUT_S * 0.2)
    assert revoke.done() and revoke.result() == (ACCOUNT_A,)
    assert consumer.statuses()[-1] == "closed:key_revoked:1"
    await streams.aclose()


async def test_a_revoke_cancelled_mid_close_still_closes_the_stream() -> None:
    """CR-G8B-C-05, SR-E27-17: the close runs in a task the registry owns, so a caller cancelled
    while the socket's close is pending leaves no stopped stream with its socket open:
    `closed(key_revoked)` is still queued, and a second `close_key` waits for that same close
    without naming the account again."""
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams = make_streams(venue)
    consumer = Consumer(await streams.open(account()))
    await until(clock, lambda: len(consumer.statuses()) == 2, within_s=5, what="live")
    venue.socket.stall_close = True
    revoke = spawn(streams.close_key(account().key_ref, reason="key_revoked"), name="revoke")
    await clock.advance(CLOSE_TIMEOUT_S / 2)
    revoke.cancel()
    again = spawn(streams.close_key(account().key_ref, reason="key_revoked"), name="again")
    await clock.settle()
    assert revoke.cancelled() and not again.done()  # the close in flight is waited for
    await clock.advance(CLOSE_TIMEOUT_S)
    assert again.done() and again.result() == ()
    assert venue.sockets[0].closed and consumer.statuses()[-1] == "closed:key_revoked:1"
    await streams.aclose()


@pytest.mark.parametrize(
    "key_ref",
    [account().key_ref.upper(), "{" + account().key_ref + "}", "not-a-key", ""],
    ids=["upper-case", "braced", "not-a-uuid", "empty"],
)
async def test_close_key_refuses_a_key_ref_that_is_no_api_keys_id(key_ref: str) -> None:
    """CR-G8B-C-04: a key named in any other shape would tombstone no stream's key and close
    nothing, a silent fail-open on SR-E27-17; it is refused before anything is done."""
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    streams = make_streams(venue)
    consumer = Consumer(await streams.open(account()))
    await until(clock, lambda: len(consumer.statuses()) == 2, within_s=5, what="live")
    with pytest.raises(ValueError, match="not an api_keys id"):
        await streams.close_key(key_ref, reason="key_revoked")
    assert not streams.tombstones.refuses(key_ref) and not venue.sockets[0].closed
    assert not streams.tombstones.refuses(account().key_ref)
    await consumer.stop()
    await streams.aclose()
