"""The private stream's `auth` (24 §14.2 rule 13; SR-E27-17; G-8b ruling 10, OQ-4), on the real B13
interpreter, a fake venue, the M2 signing double and a virtual clock.

Every dial borrows M2 under `sign_ws_auth` for `GET/realtime` and an `expires` 10 s ahead of the
exchange clock. Three consecutive exchange refusals, each while the clock offset is measured,
close the stream (`closed(auth_refused)`) and mark the key, so a later stream on it is refused
with nothing signed or dialled; a grant resets the count; a timeout or an unreadable reply never
counts, nor a refusal while the offset is unmeasured. M2's refusal to sign closes the stream at
once (`closed(key_unusable)`); the key vault being down only backs off.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID

import pytest

from candleviewer.exchange.base.errors import AuthError
from candleviewer.secrets import (
    CredentialBorrower,
    CredentialUnavailable,
    KekUnavailable,
    RequestSignature,
    SecretsError,
    WithdrawPermissionRejected,
)
from candleviewer.secrets.errors import SnapshotInvalid
from tests._signing import CREDENTIAL_ID, Call, fake_capability, stand_in_signature
from tests.chaos.ingestion._clock import VirtualClock
from tests.unit.exchange.bybit._private_venue import (
    REFUSED_AUTH,
    UNKNOWN_AUTH,
    Consumer,
    PrivateVenue,
    make_streams,
    until,
)
from tests.unit.exchange.bybit._trading import SIGNER_ID, account


def _measured(skew: int = 0) -> Callable[[], int | None]:
    return lambda: skew


@pytest.mark.parametrize("skew", [None, -12_000, 3_000])
async def test_every_dial_signs_a_fresh_auth_through_m2_ten_seconds_ahead(skew: int | None) -> None:
    """SR-E27-17: `expires` is 10 s ahead of the exchange clock as measured (exchange minus host),
    of the host's while unmeasured; the frame is the key id, `expires` and M2's signature."""
    clock, calls = VirtualClock(), list[Call]()
    venue = PrivateVenue(clock)
    streams = make_streams(venue, calls=calls)
    offset = None if skew is None else _measured(skew)
    consumer = Consumer(await streams.open(account(), clock_offset_ms=offset))
    await until(clock, lambda: len(consumer.statuses()) == 2, within_s=5, what="live")
    venue.socket.drop()
    await until(clock, lambda: len(consumer.statuses()) == 5, within_s=30, what="relive")
    assert len(calls) == 2
    for (credential, message, purpose), frame in zip(calls, venue.sent("auth"), strict=True):
        expires = frame["args"][1]
        assert (credential, purpose) == (CREDENTIAL_ID, "sign_ws_auth")
        assert message == b"GET/realtime" + str(expires).encode()
        assert frame == {"op": "auth", "args": [SIGNER_ID, expires, stand_in_signature(message)]}
    first = venue.sent("auth")[0]["args"][1]
    assert first == 1_700_000_000_000 + (skew or 0) + 10_000  # dialled at virtual time 0
    await consumer.stop()
    await streams.aclose()


async def test_three_measured_refusals_close_the_stream_and_mark_the_key() -> None:
    """Ruling 10: the stream ends `closed(auth_refused)` and a later stream on the key is refused
    (`AuthError`) before anything is signed or dialled."""
    clock, calls = VirtualClock(), list[Call]()
    venue = PrivateVenue(clock)
    venue.auth.extend([REFUSED_AUTH] * 3)
    streams = make_streams(venue, calls=calls)
    consumer = Consumer(await streams.open(account(), clock_offset_ms=_measured()))
    await until(clock, lambda: consumer.task.done(), within_s=60, what="closed")
    assert consumer.statuses() == ["closed:auth_refused:3"]
    assert (len(calls), len(venue.dialled), streams.count()) == (3, 3, 0)
    with pytest.raises(AuthError) as refused:
        await streams.open(account(), clock_offset_ms=_measured())
    assert refused.value.__cause__ is None and refused.value.__context__ is None
    assert (len(calls), len(venue.dialled)) == (3, 3)
    await streams.aclose()


async def test_refusals_while_the_offset_is_unmeasured_never_end_the_stream() -> None:
    """OQ-4: with no measured offset `expires` may be stale, so a refusal is no verdict."""
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    venue.auth.extend([REFUSED_AUTH] * 5)
    streams = make_streams(venue)
    consumer = Consumer(await streams.open(account(), clock_offset_ms=lambda: None))
    await until(clock, lambda: len(consumer.statuses()) == 2, within_s=300, what="live at last")
    assert len(venue.dialled) == 6 and consumer.statuses()[0] == "heartbeat:evidence:6"
    await consumer.stop()
    await streams.aclose()


async def test_a_timeout_or_an_unreadable_reply_counts_nothing_and_only_a_grant_resets() -> None:
    clock = VirtualClock()
    venue = PrivateVenue(clock)
    # refused, unreadable, no reply (the 5 s bound), refused: two refusals; then granted.
    venue.auth.extend([REFUSED_AUTH, UNKNOWN_AUTH, None, REFUSED_AUTH])
    streams = make_streams(venue)
    consumer = Consumer(await streams.open(account(), clock_offset_ms=_measured()))
    await until(clock, lambda: len(consumer.statuses()) == 2, within_s=300, what="live")
    [conn] = streams._conns.values()
    assert (len(venue.dialled), conn._refusals) == (5, 0)  # the grant reset the two
    venue.auth.extend([REFUSED_AUTH, REFUSED_AUTH])
    venue.socket.drop()
    await until(clock, lambda: len(venue.dialled) == 8, within_s=300, what="two more refusals")
    await until(
        clock, lambda: "resyncing:reconnected:8" in consumer.statuses(), within_s=60, what="l"
    )
    assert conn._refusals == 0  # two refusals, then a grant: never three in a row
    await consumer.stop()
    await streams.aclose()


def _refusing(error: Exception, calls: list[Call]) -> CredentialBorrower:
    async def refuse(key_id: UUID, message: Sequence[object], purpose: str) -> RequestSignature:
        calls.append((key_id, b"", purpose))
        raise error

    return CredentialBorrower(refuse)


@pytest.mark.parametrize(
    "error",
    [
        CredentialUnavailable("credential_unavailable"),
        WithdrawPermissionRejected("key_withdraw_permission"),
        SnapshotInvalid("snapshot_invalid"),
        SecretsError("other"),
    ],
    ids=["unavailable", "withdraw-permission", "snapshot-invalid", "other"],
)
async def test_m2_refusing_to_sign_closes_the_stream_at_once(error: Exception) -> None:
    clock, calls = VirtualClock(), list[Call]()
    venue = PrivateVenue(clock)
    streams = make_streams(venue, credentials=_refusing(error, calls))
    consumer = Consumer(await streams.open(account()))
    await until(clock, lambda: consumer.task.done(), within_s=10, what="closed")
    assert consumer.statuses() == ["closed:key_unusable:1"]
    assert (len(calls), venue.sent("auth")) == (1, [])  # nothing was sent
    assert venue.sockets[0].closed
    await streams.aclose()


async def test_the_key_vault_being_down_only_backs_off() -> None:
    clock, calls = VirtualClock(), list[Call]()
    venue = PrivateVenue(clock)
    down = [True, True]

    async def sign(key_id: UUID, message: Any, purpose: Any) -> RequestSignature:
        if down:
            down.pop()
            raise KekUnavailable("kek_unavailable")
        return await fake_capability(SIGNER_ID, calls).sign(key_id, message, purpose=purpose)

    streams = make_streams(venue, credentials=CredentialBorrower(sign))
    consumer = Consumer(await streams.open(account(), clock_offset_ms=_measured()))
    await until(clock, lambda: len(consumer.statuses()) == 2, within_s=60, what="live")
    assert (len(venue.dialled), len(calls), consumer.statuses()[0]) == (
        3,
        1,
        "heartbeat:evidence:3",
    )
    await consumer.stop()
    await streams.aclose()
