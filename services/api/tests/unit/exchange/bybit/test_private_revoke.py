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
    """E27-S04 (#898) wires these: the service's hooks reach its one registry, and before any
    trading port exists there is no stream to close."""
    from candleviewer.exchange.bybit.service import ExchangeBybitService

    venue = PrivateVenue(VirtualClock())
    adapter = ExchangeBybitService(
        fake_capability(SIGNER_ID), private_ws_connect=venue.connect, environment="demo"
    )
    assert await adapter.close_private_streams(account().key_ref) == ()
    assert adapter.reopen_private_streams(account().key_ref) is False
    stream = await adapter.trading_port("demo").subscribe_private(account())
    async with asyncio.timeout(5):  # a guard only: no clock is needed to reach `live`
        for _ in range(2):  # heartbeat, resyncing
            await stream.__anext__()
    closed = await adapter.close_private_streams(account().key_ref, reason="key_rotated")
    assert closed == (ACCOUNT_A,) and venue.sockets[0].closed
    last = await stream.__anext__()
    assert isinstance(last, PrivateStreamStatus) and last.reason == "key_rotated"
    await stream.aclose()
    await adapter.stop(5.0)
