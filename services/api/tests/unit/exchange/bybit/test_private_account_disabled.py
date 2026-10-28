"""#898 B3b1 (E27-S04; 24 §14.2 rule 13): an account's disable closes its keys' private streams with
the temporary tombstone `account_disabled`, which only its re-enable lifts.

`close_private_streams(key_ref, reason="account_disabled")` closes each stream on the key with
`closed(account_disabled)` and refuses a new one (`AuthError`) before anything is signed or
dialled; `reopen_private_streams(key_ref, reason="account_disabled")` lifts that tombstone and
nothing else, so the key opens streams again. A `key_revoked` or `key_rotated` tombstone is
permanent: the lift refuses it, an operator's reopen refuses it, and a later `account_disabled`
never weakens it. The operator's reopen of a key three refusals marked is unchanged and never
lifts a disable. On the real B13 interpreter, a fake venue (`PrivateVenue`'s fake connect) and a
virtual clock: no network (C-13.5).
"""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.exchange.base.errors import AuthError
from candleviewer.exchange.base.models import PRIVATE_STREAM_REASONS, PrivateStreamStatus
from candleviewer.exchange.bybit import private_stream as ps
from candleviewer.exchange.bybit.service import ExchangeBybitService
from tests._signing import Call, fake_capability
from tests.chaos.ingestion._clock import VirtualClock
from tests.unit.exchange.bybit._private_venue import (
    REFUSED_AUTH,
    Consumer,
    PrivateVenue,
    make_streams,
    until,
)
from tests.unit.exchange.bybit._trading import ACCOUNT_A, SIGNER_ID, account

OTHER_KEY = "00000000-0000-4000-8000-0000000000c3"


def _adapter(venue: PrivateVenue, calls: list[Call] | None = None) -> ExchangeBybitService:
    return ExchangeBybitService(
        fake_capability(SIGNER_ID, calls), private_ws_connect=venue.connect, environment="demo"
    )


async def _live(adapter: ExchangeBybitService, clock: VirtualClock) -> Consumer:
    consumer = Consumer(await adapter.open_private_stream(account()))
    await until(clock, lambda: len(consumer.statuses()) == 2, within_s=5, what="live")
    return consumer


async def test_a_disable_closes_the_keys_stream_and_refuses_a_new_one_until_the_lift() -> None:
    clock = VirtualClock()
    venue, calls = PrivateVenue(clock), list[Call]()
    adapter = _adapter(venue, calls)
    consumer = await _live(adapter, clock)
    closed = await adapter.close_private_streams(account().key_ref, reason="account_disabled")
    assert closed == (ACCOUNT_A,) and venue.sockets[0].closed
    await clock.settle()
    assert consumer.statuses()[-1] == "closed:account_disabled:1"
    signed, dialled = len(calls), len(venue.dialled)
    with pytest.raises(AuthError):
        await adapter.open_private_stream(account())
    assert (len(calls), len(venue.dialled)) == (signed, dialled)  # nothing signed or dialled
    assert adapter.reopen_private_streams(account().key_ref, reason="account_disabled") is True
    again = await _live(adapter, clock)  # the consumer's next refresh subscribes: no resubscribe
    assert adapter.reopen_private_streams(account().key_ref, reason="account_disabled") is False
    await again.stop()
    await adapter.stop(5.0)


def test_the_closed_status_names_the_disable() -> None:
    """24 §14.4: `account_disabled` is one of `closed`'s reasons, and of no other state's."""
    owners = [s for s, group in PRIVATE_STREAM_REASONS.items() if "account_disabled" in group]
    assert owners == ["closed"]
    status = PrivateStreamStatus(
        account_id=ACCOUNT_A, state="closed", reason="account_disabled", epoch=1, ts=1
    )
    assert status.reason == "account_disabled"


@pytest.mark.parametrize("permanent", ["key_revoked", "key_rotated"])
@pytest.mark.parametrize("order", ["before", "after"])
async def test_a_revoked_or_rotated_key_stays_closed_whatever_lifts_it(
    permanent: Any, order: str
) -> None:
    """The lift lifts `account_disabled` only: a revoke or a rotation told before the disable or
    after it stays, and neither the re-enable's lift nor the operator's reopen clears it."""
    adapter = _adapter(PrivateVenue(VirtualClock()))
    key_ref = account().key_ref
    reasons = (
        ["account_disabled", permanent] if order == "after" else [permanent, "account_disabled"]
    )
    for reason in reasons:
        await adapter.close_private_streams(key_ref, reason=reason)
    assert adapter.reopen_private_streams(key_ref, reason="account_disabled") is False
    assert adapter.reopen_private_streams(key_ref) is False
    with pytest.raises(AuthError):
        await adapter.open_private_stream(account())
    await adapter.stop(5.0)


async def test_the_operators_reopen_never_lifts_a_disable_and_the_lift_no_refusal_mark() -> None:
    """Two lifts, kept apart: three `auth` refusals' mark is the operator's (ruling 10), a disable
    is the re-enable's."""
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    venue.auth.extend([REFUSED_AUTH] * ps.MAX_AUTH_REFUSALS)
    adapter = _adapter(venue)
    streams = make_streams(venue, tombstones=adapter._tombstones)
    refused = Consumer(await streams.open(account(), clock_offset_ms=lambda: 0))
    await until(clock, lambda: refused.task.done(), within_s=60, what="three refusals")
    await adapter.close_private_streams(OTHER_KEY, reason="account_disabled")
    assert adapter.reopen_private_streams(account().key_ref, reason="account_disabled") is False
    assert adapter.reopen_private_streams(OTHER_KEY) is False
    with pytest.raises(AuthError):
        await streams.open(account(key_ref=OTHER_KEY))
    with pytest.raises(AuthError):
        await streams.open(account())
    await streams.aclose()
    await adapter.stop(5.0)


def test_a_disable_tombstone_of_no_api_keys_id_is_refused_before_anything_is_recorded() -> None:
    tombstones = ps.KeyTombstones()
    with pytest.raises(ValueError):
        tombstones.close("not-a-key", "account_disabled")
    assert tombstones.lift("not-a-key") is False
