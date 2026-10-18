"""E17-S01 pure lifecycle units: §4.1 transition table, negotiation, bye, rate limit, watchdog."""

from __future__ import annotations

import itertools

import pytest

from candleviewer.settings import Settings
from candleviewer.ws.lifecycle import (
    CLOSE_REASONS,
    FEATURES,
    LIMITS_BLOCK,
    PONG_BUDGET_BURST,
    PONG_BUDGET_PER_S,
    SERVER_PING_AFTER_S,
    TRANSITIONS,
    CloseCode,
    ConnEvent,
    ConnState,
    IllegalTransition,
    InboundRateLimiter,
    Lifecycle,
    PongBudget,
    Watchdog,
    bye_frame,
    negotiate_subprotocol,
    welcome_features,
    welcome_payload,
)

_LIVE = [s for s in ConnState if s not in (ConnState.CLOSING, ConnState.CLOSED)]


@pytest.mark.parametrize(("state", "event"), list(itertools.product(ConnState, ConnEvent)), ids=str)
def test_lifecycle_every_state_event_pair_matches_the_table(
    state: ConnState, event: ConnEvent
) -> None:
    lc = Lifecycle()
    lc.state = state
    expected = TRANSITIONS.get((state, event))
    if expected is None:
        with pytest.raises(IllegalTransition):
            lc.fire(event)
        assert lc.state is state
    else:
        assert lc.fire(event) is expected


@pytest.mark.parametrize("state", _LIVE, ids=str)
def test_lifecycle_closing_is_reachable_from_every_live_state(state: ConnState) -> None:
    assert TRANSITIONS[(state, ConnEvent.CLOSE)] is ConnState.CLOSING


def test_lifecycle_happy_path_and_in_place_reauth_loop() -> None:
    lc = Lifecycle()
    for ev in (
        ConnEvent.OPEN_NEGOTIATED,
        ConnEvent.HELLO,
        ConnEvent.WELCOME_SENT,
        ConnEvent.AUTH_OK,
        ConnEvent.REAUTH,
        ConnEvent.AUTH_OK,
    ):
        lc.fire(ev)
    assert lc.state is ConnState.AUTHENTICATED and lc.authenticated
    assert ConnState.REAUTHENTICATING in lc.history


def test_lifecycle_auth_before_hello_is_illegal() -> None:
    lc = Lifecycle()
    lc.fire(ConnEvent.OPEN_NEGOTIATED)
    assert not lc.can(ConnEvent.AUTH_OK)
    assert not lc.authenticated


@pytest.mark.parametrize(
    ("offered", "chosen"),
    [
        (["cv.v1.msgpack", "cv.v1.json"], "cv.v1.msgpack"),
        (["cv.v1.json", "cv.v1.msgpack"], "cv.v1.msgpack"),  # the server's order wins (§2.2)
        (["cv.v1.msgpack"], "cv.v1.msgpack"),
        (["cv.v1.json"], "cv.v1.json"),
        ([" cv.v1.json "], "cv.v1.json"),
        (["cv.v2.json", "graphql-ws"], None),
        ([], None),
    ],
)
def test_negotiate_subprotocol_picks_supported_or_none(
    offered: list[str], chosen: str | None
) -> None:
    assert negotiate_subprotocol(offered) == chosen


def test_negotiate_subprotocol_prefers_msgpack_once_served() -> None:
    both = ("cv.v1.msgpack", "cv.v1.json")
    assert negotiate_subprotocol(["cv.v1.json", "cv.v1.msgpack"], both) == "cv.v1.msgpack"


@pytest.mark.parametrize("reason", sorted(CLOSE_REASONS))
def test_bye_frame_carries_code_reason_message_reconnect(reason: str) -> None:
    frame = bye_frame(reason, now_ms=7, retry_after_ms=5)
    code, reconnect = CLOSE_REASONS[reason]
    assert frame["t"] == "bye" and frame["ts"] == 7
    assert frame["p"] == {
        "code": int(code),
        "reason": reason,
        "message": frame["p"]["message"],
        "reconnect": reconnect,
        "retry_after_ms": 5,
    }
    assert frame["p"]["message"]


def test_close_codes_cover_section_4_4() -> None:
    assert {int(c) for c in CloseCode} == {
        1000, 1001, 1002, 1009, 1011, 1013, 4401, 4403, 4429, 4400
    }  # fmt: skip
    assert {int(c) for c, _ in CLOSE_REASONS.values()} == {int(c) for c in CloseCode}


def test_rate_limiter_allows_30_per_second_then_refuses_the_31st() -> None:
    rl = InboundRateLimiter()
    assert all(rl.allow(10.0 + i * 0.001) for i in range(30))
    assert rl.allow(10.5) is False


def test_rate_limiter_second_window_boundary_is_exclusive() -> None:
    rl = InboundRateLimiter()
    for i in range(30):
        assert rl.allow(i * 0.01)
    assert rl.allow(0.999) is False  # still inside the first second
    assert rl.allow(1.0) is True  # first stamp (t=0) has left the window


def test_rate_limiter_300_per_minute() -> None:
    rl = InboundRateLimiter()
    for i in range(300):
        assert rl.allow(i * 0.1)  # 10/s: never trips the per-second limit
    assert rl.allow(30.0) is False
    assert rl.allow(60.0) is True  # t=0 aged out


#: The `pong` budget 23 §8.5 states: 4 a second, at most 8 at once.
_STATED_PONGS_PER_S, _STATED_PONG_BURST = 4, 8


def test_pong_budget_takes_its_burst_at_once_then_refuses() -> None:
    budget = PongBudget()
    assert [budget.allow(5.0) for _ in range(9)] == [True] * _STATED_PONG_BURST + [False]
    assert budget.allow(5.0) is False  # a refusal takes nothing and refills nothing


def test_pong_budget_refills_at_its_rate_never_past_its_burst() -> None:
    budget = PongBudget()
    assert all(budget.allow(0.0) for _ in range(_STATED_PONG_BURST))
    assert sum(budget.allow(k / 16) for k in range(1, 17)) == _STATED_PONGS_PER_S  # 1 s, at 16/s
    assert [budget.allow(100.0) for _ in range(9)] == [True] * _STATED_PONG_BURST + [False]


def test_pong_budget_is_about_twice_the_most_pings_the_server_sends() -> None:
    """The RTT probe pings once per classification, every 500 ms at the settings' floor, and the
    idle heartbeat once per `SERVER_PING_AFTER_S` of silence: about 2 a second (§8.5, §9.1)."""
    field = Settings.model_fields["ws_classify_interval_ms"]
    floor_ms = next(m.ge for m in field.metadata if hasattr(m, "ge"))
    most = 1000 / floor_ms + 1 / SERVER_PING_AFTER_S
    assert (PONG_BUDGET_PER_S, PONG_BUDGET_BURST) == (_STATED_PONGS_PER_S, _STATED_PONG_BURST)
    assert 1.9 * most <= PONG_BUDGET_PER_S <= 2.5 * most


def test_welcome_payload_full_limits_and_clock_skew() -> None:
    p = welcome_payload(
        encoding="json",
        server_version="1",
        git_sha="abc",
        connection_id="ws_1",
        server_time_ms=1_000_022,
        client_clock_ms=1_000_000,
        features=welcome_features(coalescing=False),
    )
    assert p["clock_skew_ms"] == 22
    assert p["limits"] == LIMITS_BLOCK
    assert LIMITS_BLOCK == {
        "max_subscriptions": 200,
        "max_topics_per_request": 50,
        "max_inbound_frame_bytes": 262144,
        "max_outbound_frame_bytes": 4194304,
        "min_throttle_ms": 50,
        "max_symbols_per_connection": 40,
    }
    assert p["heartbeat"] == {"interval_ms": 15000, "timeout_ms": 45000}
    assert p["auth_timeout_ms"] == 10000 and p["auth_required"] is True


@pytest.mark.parametrize("clock", [None, "1", True, 1.5])
def test_welcome_payload_omits_skew_without_integer_client_clock(clock: object) -> None:
    p = welcome_payload(
        encoding="json",
        server_version="1",
        git_sha="abc",
        connection_id="ws_1",
        server_time_ms=5,
        client_clock_ms=clock,
        features=welcome_features(coalescing=False),
    )
    assert "clock_skew_ms" not in p


def test_welcome_clock_skew_can_be_negative() -> None:
    p = welcome_payload(
        encoding="json",
        server_version="1",
        git_sha="a",
        connection_id="c",
        server_time_ms=1000,
        client_clock_ms=3500,
        features=welcome_features(coalescing=False),
    )
    assert p["clock_skew_ms"] == -2500


def test_the_fixed_features_do_not_advertise_coalescing() -> None:
    """`coalescing` mirrors `CV_WS_BACKPRESSURE_ENABLED` (`23-ws-protocol.md` §4.2), so it is never
    fixed."""
    assert FEATURES == {"replay": True, "binary_payloads": True}


@pytest.mark.parametrize("coalescing", [False, True])
def test_welcome_features_carry_coalescing_and_leave_the_rest_alone(coalescing: bool) -> None:
    assert welcome_features(coalescing=coalescing) == {
        "replay": True,
        "binary_payloads": True,
        "coalescing": coalescing,
    }


def test_welcome_features_hands_out_a_fresh_dict_and_leaves_features_alone() -> None:
    """A router keeps its block for every welcome: a later change to one copy, or to the shared
    `FEATURES`, must not reach another."""
    first = welcome_features(coalescing=True)
    second = welcome_features(coalescing=True)

    assert first is not second
    first["replay"] = False
    assert second == {"replay": True, "binary_payloads": True, "coalescing": True}
    assert FEATURES == {"replay": True, "binary_payloads": True}


def test_welcome_payload_carries_exactly_the_features_it_is_given() -> None:
    given = welcome_features(coalescing=True)
    p = welcome_payload(
        encoding="json",
        server_version="1",
        git_sha="a",
        connection_id="c",
        server_time_ms=1000,
        client_clock_ms=None,
        features=given,
    )

    assert p["features"] == given
    assert p["features"] is not given  # a later change to `given` cannot reach a sent welcome


def test_watchdog_priority_and_deadlines() -> None:
    wd = Watchdog(auth_deadline=10.0, last_inbound=0.0, last_outbound=0.0)
    assert wd.due(5.0) is None
    assert wd.due(10.0) == "auth_timeout"
    wd.auth_deadline = None
    wd.token_expires_at = 100.0
    assert wd.due(20.0) == "ping"
    wd.last_outbound = 20.0
    assert wd.due(30.0) is None
    assert wd.due(45.0) == "heartbeat_timeout"
    wd.last_inbound = 99.0
    wd.last_outbound = 99.0
    assert wd.due(100.0) == "token_expired"
