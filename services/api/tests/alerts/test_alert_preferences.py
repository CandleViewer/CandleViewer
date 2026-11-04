"""CC-9's per-channel decision and the owner's settings read (#1130 slice 3, 24 §19.106).

Pure: no database, no network (C-13.5); the clock is a fixed instant. The Gherkin of E40-S02 Part B:
"Muting a symbol silences without losing the record", "Quiet hours suppress the optional channels
only"; "A critical event overrides everything" holds as the ruling's BQ-5 redefines it: a user
alert never overrides (`USER_ALERTS_OVERRIDE` false), so nothing here locks an alert row.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.alerts import preferences as p
from candleviewer.alerts.dispatcher import CHANNELS, SUPPRESSION_REASONS
from candleviewer.alerts.preferences import (
    DeliveryPrefs,
    QuietHours,
    StoredPrefs,
    decide,
    prefs_of,
    zone,
)

BERLIN = zone("Europe/Berlin")
assert BERLIN is not None
NIGHT = QuietHours(time(22, 0), time(7, 0), BERLIN)
FIRING = {"trigger_type": "crosses_above", "symbol": "ETHUSDT"}
AT_23 = datetime(2026, 11, 4, 22, 0, tzinfo=UTC)  # 23:00 in Berlin (CET)
AT_NOON = datetime(2026, 11, 4, 11, 0, tzinfo=UTC)


def test_decide_mute_silences_in_app_and_suppresses_desktop() -> None:
    """Muting a symbol silences without losing the record."""
    prefs = DeliveryPrefs(muted_symbols=frozenset({"ETHUSDT"}))
    assert decide(channel="in_app", context=FIRING, prefs=prefs, now=AT_NOON) == p.Decision(
        "silence", "muted_symbol"
    )
    assert decide(channel="desktop", context=FIRING, prefs=prefs, now=AT_NOON) == p.Decision(
        "suppress", "muted_symbol"
    )
    other = {**FIRING, "symbol": "BTCUSDT"}
    assert decide(channel="desktop", context=other, prefs=prefs, now=AT_NOON) == p.DELIVER


def test_decide_quiet_hours_hold_the_optional_channels_only() -> None:
    """Quiet hours 22:00-07:00 in the stated zone, a normal alert at 23:00."""
    prefs = DeliveryPrefs(quiet_hours=NIGHT)
    assert decide(channel="in_app", context=FIRING, prefs=prefs, now=AT_23).reason == "quiet_hours"
    assert decide(channel="desktop", context=FIRING, prefs=prefs, now=AT_23) == p.Decision(
        "suppress", "quiet_hours"
    )
    assert decide(channel="email", context=FIRING, prefs=prefs, now=AT_23) == p.DELIVER
    assert decide(channel="desktop", context=FIRING, prefs=prefs, now=AT_NOON) == p.DELIVER


def test_decide_mute_wins_over_quiet_hours_and_desktop_off() -> None:
    prefs = DeliveryPrefs(frozenset({"ETHUSDT"}), NIGHT, desktop_enabled=False)
    assert decide(channel="desktop", context=FIRING, prefs=prefs, now=AT_23).reason == (
        "muted_symbol"
    )


def test_decide_desktop_off_suppresses_every_desktop_row_never_in_app() -> None:
    prefs = DeliveryPrefs(desktop_enabled=False)
    for ctx in (FIRING, {"disarmed": True}, {"storm_summary": True, "symbols": ["ETHUSDT"]}):
        assert decide(channel="desktop", context=ctx, prefs=prefs, now=AT_NOON) == p.Decision(
            "suppress", "desktop_off"
        )
        assert decide(channel="in_app", context=ctx, prefs=prefs, now=AT_NOON) == p.DELIVER


@pytest.mark.parametrize(
    "ctx",
    [
        {"disarmed": True, "symbol": "ETHUSDT"},
        {"channel_failure": True, "symbol": "ETHUSDT"},
        {"storm_summary": True, "symbols": ["ETHUSDT"], "symbol": "ETHUSDT"},
    ],
)
def test_decide_never_holds_a_row_that_is_no_firing(ctx: dict[str, Any]) -> None:
    """CC-9 marks the `in_app` row of a firing; notices and summaries are left to their adapter."""
    prefs = DeliveryPrefs(frozenset({"ETHUSDT"}), NIGHT)
    for channel in ("in_app", "desktop"):
        assert decide(channel=channel, context=ctx, prefs=prefs, now=AT_23) == p.DELIVER


def test_decide_holds_nothing_were_user_alerts_ever_to_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The override list is read, never re-declared: a true flag would deliver everything."""
    monkeypatch.setattr(p, "USER_ALERTS_OVERRIDE", True)
    prefs = DeliveryPrefs(frozenset({"ETHUSDT"}), NIGHT, desktop_enabled=False)
    for channel in ("in_app", "desktop"):
        assert decide(channel=channel, context=FIRING, prefs=prefs, now=AT_23) == p.DELIVER


_prefs = st.builds(
    DeliveryPrefs,
    muted_symbols=st.frozensets(st.sampled_from(["ETHUSDT", "BTCUSDT", "SOLUSDT"])),
    quiet_hours=st.none() | st.builds(
        QuietHours, st.times(), st.times(), st.just(BERLIN)
    ),
    desktop_enabled=st.booleans(),
)  # fmt: skip
_ctx = st.fixed_dictionaries(
    {"symbol": st.none() | st.sampled_from(["ETHUSDT", "BTCUSDT", "XRPUSDT"])},
    optional={"disarmed": st.booleans(), "storm_summary": st.booleans(),
              "channel_failure": st.booleans()},
)  # fmt: skip
_now = st.datetimes(
    min_value=datetime(2026, 1, 1), max_value=datetime(2027, 12, 31), timezones=st.just(UTC)
)


@given(channel=st.sampled_from(CHANNELS), ctx=_ctx, prefs=_prefs, now=_now)
def test_decide_property_the_record_is_never_dropped(
    channel: str, ctx: dict[str, Any], prefs: DeliveryPrefs, now: datetime
) -> None:
    """The `in_app` row is delivered or silenced, never suppressed; a suppression reason is one the
    dispatcher may store; channels other than in-app and desktop are never touched; and the in-app
    and desktop rows of one firing are held for the same reason."""
    got = decide(channel=channel, context=ctx, prefs=prefs, now=now)
    if channel == "in_app":
        assert got.action in ("deliver", "silence")
    elif channel != "desktop":
        assert got == p.DELIVER
    if got.action == "suppress":
        assert got.reason in SUPPRESSION_REASONS
    if got.action == "silence":
        assert got.reason in ("muted_symbol", "quiet_hours")
    app = decide(channel="in_app", context=ctx, prefs=prefs, now=now)
    desk = decide(channel="desktop", context=ctx, prefs=prefs, now=now)
    if app.action == "silence":
        assert desk == p.Decision("suppress", app.reason)


@given(ctx=_ctx, now=_now, channel=st.sampled_from(CHANNELS))
def test_decide_property_no_prefs_hold_nothing(
    ctx: dict[str, Any], now: datetime, channel: str
) -> None:
    assert decide(channel=channel, context=ctx, prefs=p.NO_PREFS, now=now) == p.DELIVER


@pytest.mark.parametrize(
    ("start", "end", "local", "inside"),
    [
        (time(22), time(7), time(23), True),
        (time(22), time(7), time(6, 59), True),
        (time(22), time(7), time(7), False),
        (time(22), time(7), time(21, 59), False),
        (time(9), time(17), time(9), True),
        (time(9), time(17), time(17), False),
        (time(9), time(9), time(9), False),  # an empty window holds nothing
    ],
)
def test_quiet_hours_window_bounds(start: time, end: time, local: time, inside: bool) -> None:
    utc = zone("UTC")
    assert utc is not None
    now = datetime.combine(datetime(2026, 11, 4).date(), local, tzinfo=UTC)
    assert QuietHours(start, end, utc).holds(now) is inside


def test_quiet_hours_follow_the_zone_across_a_dst_change() -> None:
    """Stored as an IANA zone, never an offset: 22:00 Berlin is 21:00 UTC in winter, 20:00 in
    summer (2026-03-29 is the spring change)."""
    assert NIGHT.holds(datetime(2026, 3, 28, 21, 30, tzinfo=UTC))  # 22:30 CET
    assert not NIGHT.holds(datetime(2026, 3, 29, 19, 30, tzinfo=UTC))  # 21:30 CEST
    assert NIGHT.holds(datetime(2026, 3, 29, 20, 30, tzinfo=UTC))  # 22:30 CEST
    assert NIGHT.holds(datetime(2026, 3, 29, 1, 30, tzinfo=UTC))  # 03:30 CEST, the gap passed
    assert not NIGHT.holds(datetime(2026, 3, 29, 5, 0, tzinfo=UTC))  # 07:00 CEST


_QH = {"enabled": True, "start": "22:00", "end": "07:00", "tz": "Europe/Berlin"}


def test_prefs_of_reads_the_three_leaves() -> None:
    got = prefs_of([
        ("notifications.muted_symbols", [{"symbol": "ETHUSDT", "muted_at": "2026-11-03T14:02Z"}]),
        ("notifications.quiet_hours", _QH),
        ("notifications.desktop_enabled", False),
        ("appearance.theme", "dark"),
    ])  # fmt: skip
    assert got == DeliveryPrefs(frozenset({"ETHUSDT"}), NIGHT, desktop_enabled=False)


@pytest.mark.parametrize(
    "value",
    [
        {**_QH, "enabled": False},
        {**_QH, "tz": "Mars/Olympus"},  # SR-E40-12: an unknown zone delivers
        {**_QH, "tz": "../../etc/passwd"},
        {**_QH, "start": "24:00"},
        {"from": "22:00", "days": [1, 2]},  # the old free-form shape
        "22:00-07:00",
    ],
)
def test_prefs_of_ignores_quiet_hours_without_their_contract_shape(value: object) -> None:
    assert prefs_of([("notifications.quiet_hours", value)]).quiet_hours is None


def test_prefs_of_defaults_hold_nothing() -> None:
    assert prefs_of([]) == p.NO_PREFS
    junk = prefs_of([("notifications.muted_symbols", "ETHUSDT"),
                     ("notifications.desktop_enabled", "no")])  # fmt: skip
    assert junk == p.NO_PREFS


@dataclass(frozen=True)
class _Row:
    key: str
    value: object


class _Settings:
    def __init__(self, rows: dict[uuid.UUID, list[_Row]], *, hang: bool = False) -> None:
        self.rows, self.hang, self.read_for = rows, hang, list[uuid.UUID]()

    async def read(self, user_id: uuid.UUID) -> list[_Row]:
        self.read_for.append(user_id)
        if self.hang:
            await asyncio.Event().wait()
        return self.rows.get(user_id, [])


A, B = uuid.UUID(int=0xA), uuid.UUID(int=0xB)


async def test_stored_prefs_read_only_the_named_owner() -> None:
    """RBAC/IDOR: the read names the delivery's owner; another user's mute never applies."""
    settings = _Settings({
        A: [_Row("notifications.desktop_enabled", True)],
        B: [_Row("notifications.muted_symbols", [{"symbol": "ETHUSDT"}])],
    })  # fmt: skip
    got = await StoredPrefs(settings).prefs(str(A))
    assert got.muted_symbols == frozenset() and settings.read_for == [A]


async def test_stored_prefs_bound_the_read() -> None:
    with pytest.raises(TimeoutError):
        await StoredPrefs(_Settings({}, hang=True), timeout_s=0.01).prefs(str(A))


def test_zone_lists_known_names_only() -> None:
    assert zone("UTC") is not None and zone("Not/AZone") is None and zone("") is None
