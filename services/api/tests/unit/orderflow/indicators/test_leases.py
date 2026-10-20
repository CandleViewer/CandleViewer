"""Server indicator instance leases: the SR-E13-03 caps, joins, the release grace and the
per-user bucket gauge (E13-T02, #426; E13 threat model SR-E13-03, IR-21, IR-31, IR-36)."""

from __future__ import annotations

import pytest

from candleviewer.orderflow.errors import IndicatorError, InstanceCapError, InstanceChurnError
from candleviewer.orderflow.indicators.leases import InstanceCaps, InstanceLeases
from candleviewer.orderflow.indicators.metrics import CAP_REJECTED, SUBSCRIPTIONS, bucket_of
from tests.unit.orderflow.indicators._engine import counter

SYM, OTHER = "BTCUSDT", "ETHUSDT"


def _key(i: int) -> str:
    return f"{i:064x}"


def _hold(leases: InstanceLeases, symbol: str, n: int, user: str | None, start: int = 0) -> None:
    for i in range(start, start + n):
        leases.check(symbol, [_key(i)], user)
        leases.acquire((symbol, _key(i)), f"{user}-c{i}", user)


def _refused(leases: InstanceLeases, symbol: str, key: str, user: str | None) -> str:
    with pytest.raises(InstanceCapError) as caught:
        leases.check(symbol, [key], user)
    return caught.value.cap


def test_the_ninth_distinct_instance_of_a_user_is_refused() -> None:
    leases = InstanceLeases()
    _hold(leases, SYM, 8, "u1")
    before = counter(CAP_REJECTED["user"])
    assert _refused(leases, SYM, _key(99), "u1") == "user"
    assert counter(CAP_REJECTED["user"]) - before == 1
    leases.check(SYM, [_key(3)], "u1")  # one the user holds already: no new distinct instance
    leases.check(SYM, [_key(99)], None)  # a system consumer is exempt from the user cap only
    leases.check(SYM, [_key(99)], "u2")


def test_the_33rd_on_a_symbol_and_the_129th_in_the_process_are_refused() -> None:
    leases = InstanceLeases()
    for u in range(4):
        _hold(leases, SYM, 8, f"u{u}", start=u * 8)
    assert len(leases._held) == 32
    assert _refused(leases, SYM, _key(999), "u9") == "symbol"
    assert _refused(leases, SYM, _key(999), None) == "symbol"  # system consumers are not exempt
    leases.check(SYM, [_key(5)], "u9")  # joining a running instance counts toward no symbol cap
    small = InstanceLeases(InstanceCaps(per_user=8, per_symbol=32, process=3))
    _hold(small, SYM, 3, None)
    assert _refused(small, OTHER, _key(7), None) == "process"
    small.check(SYM, [_key(1)], "u1")  # a join counts toward the user cap alone


def test_a_check_with_a_consumer_counts_its_own_leases_out_as_a_replace_does() -> None:
    leases = InstanceLeases()
    for i in range(8):
        leases.acquire((SYM, _key(i)), "ctl-sub", "u1")
    assert _refused(leases, SYM, _key(9), "u1") == "user"
    leases.check(SYM, [_key(9), *(_key(i) for i in range(7))], "u1", "ctl-sub")


def test_a_batch_is_checked_whole() -> None:
    leases = InstanceLeases()
    _hold(leases, SYM, 6, "u1")
    with pytest.raises(InstanceCapError):
        leases.check(SYM, [_key(50), _key(51), _key(52)], "u1")  # 6 + 3 > 8
    leases.check(SYM, [_key(50), _key(51)], "u1")


def test_a_released_instance_keeps_its_grace_and_still_counts() -> None:
    leases = InstanceLeases(InstanceCaps(per_symbol=1), grace_us=30_000_000)
    assert leases.acquire((SYM, _key(1)), "c1", "u1") is True
    leases.release((SYM, _key(1)), "c1", now_us=1_000)
    assert leases.expired(30_000_999) == () and (SYM, _key(1)) in leases._held
    assert _refused(leases, SYM, _key(2), "u2") == "symbol"  # in its grace it still counts
    assert leases.acquire((SYM, _key(1)), "c2", "u2") is False  # re-acquired: the same instance
    leases.release((SYM, _key(1)), "c2", now_us=2_000)
    assert leases.expired(30_002_000) == ((SYM, _key(1)),) and len(leases._held) == 0
    with pytest.raises(IndicatorError):
        leases.release((SYM, _key(1)), "c2", now_us=3_000)


def test_the_subscription_gauge_buckets_users_by_instances_held_never_by_id() -> None:
    leases = InstanceLeases()
    _hold(leases, SYM, 1, "a")
    _hold(leases, SYM, 3, "b", start=10)
    _hold(leases, SYM, 8, "c", start=20)
    _hold(leases, SYM, 2, None, start=40)  # system consumers are no user
    seen = {name: child._value.get() for name, child in SUBSCRIPTIONS.items()}
    assert seen == {"1": 1, "2-4": 1, "5-7": 0, "8": 1}
    assert [bucket_of(n) for n in (1, 2, 4, 5, 7, 8, 9)] == [
        "1",
        "2-4",
        "2-4",
        "5-7",
        "5-7",
        "8",
        "8",
    ]


def test_a_user_holds_eight_and_runs_twenty_four_with_those_released_in_their_grace() -> None:
    """IR-31 (reviews of the WS delivery): a user holds at most 8 instances and, with those the
    user released that are still in their grace, runs at most 24. Two full flips (release 8, hold
    8 others) are admitted within a grace; past 24 the refusal has its own message, saying it ends
    with the grace, and counts as `user`. Another user is not charged, holding a released one
    again ends its charge, and the grace's end ends the rest."""
    leases = InstanceLeases(grace_us=30_000_000)
    _hold(leases, SYM, 8, "u1")
    for start in (0, 8):  # two flips
        for i in range(start, start + 8):
            leases.release((SYM, _key(i)), f"u1-c{i}", now_us=1_000)
        _hold(leases, SYM, 8, "u1", start=start + 8)
    assert _refused(leases, SYM, _key(99), "u1") == "user"  # a ninth held: the held cap
    leases.release((SYM, _key(23)), "u1-c23", now_us=2_000)  # 7 held, 17 released
    before = counter(CAP_REJECTED["user"])
    with pytest.raises(InstanceChurnError) as caught:
        leases.check(OTHER, [_key(50)], "u1")
    assert (caught.value.cap, caught.value.limit) == ("user", 24)
    assert str(caught.value) == (
        "Server indicator instances you released in the last 30 s still count; "
        "retry once they expire."
    )
    assert counter(CAP_REJECTED["user"]) - before == 1
    leases.check(OTHER, [_key(50)], "u2")  # another user is not charged
    leases.check(SYM, [_key(23)], "u1")  # holding one it released again adds none
    leases.acquire((SYM, _key(0)), "u2-c0", "u2")  # held again, by anyone: no longer u1's
    leases.check(OTHER, [_key(50)], "u1")  # 7 held, 16 released, 1 new: 24
    assert len(leases.expired(30_001_000)) == 15  # the flips' grace ends (u2 holds the 16th)
    _hold(leases, OTHER, 1, "u1", start=60)  # 8 held, 1 released
    assert _refused(leases, OTHER, _key(70), "u1") == "user"


def test_sole_names_the_instances_a_replacing_consumer_alone_holds() -> None:
    """A WS `ctl` forgets the replaced instances it alone held (`IndicatorEngine._let_go`), so
    a retune leaves nothing in a grace: `sole` is True for one lease only, the consumer's."""
    leases = InstanceLeases()
    leases.acquire((SYM, _key(1)), "ctl-sub", "u1")
    leases.acquire((SYM, _key(2)), "ctl-sub", "u1")
    leases.acquire((SYM, _key(2)), "other", "u2")
    assert leases.sole((SYM, _key(1)), "ctl-sub")
    assert not leases.sole((SYM, _key(2)), "ctl-sub")  # shared
    assert not leases.sole((SYM, _key(1)), "other")  # not its lease
    assert not leases.sole((SYM, _key(3)), "ctl-sub")  # no such instance


def test_drop_forgets_an_instance_with_no_grace_and_no_charge() -> None:
    leases = InstanceLeases()
    assert leases.acquire((SYM, _key(1)), "c1", "u1") is True
    leases.drop((SYM, _key(1)))
    leases.drop((SYM, _key(1)))  # twice is nothing
    assert leases._held == {} and leases.expired(10**12) == ()
    _hold(leases, SYM, 8, "u1", start=10)
