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


def _flipped_twice() -> InstanceLeases:
    """IR-31 (reviews of the WS delivery): u1 held eight instances, then twice released all it
    held (at `now_us` 1 000) and held eight others: it holds 8 (keys 16..23) and 16 it released
    are in their grace (keys 0..15)."""
    leases = InstanceLeases(grace_us=30_000_000)
    _hold(leases, SYM, 8, "u1")
    for start in (0, 8):
        for i in range(start, start + 8):
            leases.release((SYM, _key(i)), f"u1-c{i}", now_us=1_000)
        _hold(leases, SYM, 8, "u1", start=start + 8)
    return leases


def _at_the_churn_bound() -> InstanceLeases:
    """`_flipped_twice`, then u1 releases key 23 (at 2 000): 7 held and 17 released in their
    grace, so one more instance makes 25, past the churn bound of 24."""
    leases = _flipped_twice()
    leases.release((SYM, _key(23)), "u1-c23", now_us=2_000)
    return leases


def test_two_flips_of_eight_are_admitted_and_a_ninth_held_meets_the_held_cap() -> None:
    """IR-31: a user holds at most 8 instances and, with those it released that are still in
    their grace, runs at most 24, so two full flips within a grace are admitted; holding a
    ninth is the held cap's refusal, not the churn bound's."""
    leases = _flipped_twice()
    with pytest.raises(InstanceCapError) as caught:
        leases.check(SYM, [_key(99)], "u1")
    assert type(caught.value) is InstanceCapError and caught.value.cap == "user"


def test_churn_past_twenty_four_is_refused_saying_it_ends_with_a_grace() -> None:
    leases = _at_the_churn_bound()
    with pytest.raises(InstanceChurnError) as caught:
        leases.check(OTHER, [_key(50)], "u1")
    assert (caught.value.cap, caught.value.limit) == ("user", 24)
    assert str(caught.value) == (
        "Server indicator instances you released in the last 30 s still count; "
        "retry once they expire."
    )


def test_a_churn_refusal_is_counted_as_the_user_cap() -> None:
    leases = _at_the_churn_bound()
    before = counter(CAP_REJECTED["user"])
    with pytest.raises(InstanceChurnError):
        leases.check(OTHER, [_key(50)], "u1")
    assert counter(CAP_REJECTED["user"]) - before == 1


def test_a_users_churn_is_not_charged_to_another_user() -> None:
    _at_the_churn_bound().check(OTHER, [_key(50)], "u2")


def test_holding_again_an_instance_the_user_released_adds_no_churn() -> None:
    _at_the_churn_bound().check(SYM, [_key(23)], "u1")


def test_an_instance_held_again_by_anyone_ends_its_releasers_charge() -> None:
    leases = _at_the_churn_bound()
    leases.acquire((SYM, _key(0)), "u2-c0", "u2")
    leases.check(OTHER, [_key(50)], "u1")  # 7 held, 16 released, 1 new: 24


def test_the_end_of_a_grace_ends_its_churn_charge() -> None:
    leases = _at_the_churn_bound()
    assert len(leases.expired(30_002_000)) == 17
    leases.check(OTHER, [_key(50)], "u1")


def _with_a_ctl_holding_eight(leases: InstanceLeases) -> list[str]:
    """`ctl-sub` (u1's subscription) alone holds keys 0..7 on SYM; the eight it retunes to."""
    for i in range(8):
        leases.acquire((SYM, _key(i)), "ctl-sub", "u1")
    return [_key(50 + i) for i in range(8)]


def test_a_ctl_at_the_symbol_cap_counts_out_the_instances_it_alone_drops() -> None:
    """A WS `ctl` drops the instances it alone held that its new set leaves out
    (`IndicatorEngine._let_go`), so they do not count toward the symbol cap: on a symbol running
    32, eight of them the `ctl`'s alone, a retune to eight others passes, while one more instance
    from anyone else is refused `symbol`."""
    leases = InstanceLeases()
    retune = _with_a_ctl_holding_eight(leases)
    for u in range(2, 5):
        _hold(leases, SYM, 8, f"u{u}", start=u * 8)
    assert _refused(leases, SYM, _key(99), "u9") == "symbol"
    leases.check(SYM, retune, "u1", "ctl-sub")


def test_a_ctl_at_the_process_cap_counts_out_the_instances_it_alone_drops() -> None:
    leases = InstanceLeases(InstanceCaps(process=10))
    retune = _with_a_ctl_holding_eight(leases)
    _hold(leases, OTHER, 2, "u2", start=10)
    assert _refused(leases, OTHER, _key(99), "u9") == "process"
    leases.check(SYM, retune, "u1", "ctl-sub")


def test_a_ctl_still_counts_an_instance_it_shares() -> None:
    """An instance the `ctl` shares outlives the retune (another consumer holds it), so it still
    counts: with one of its eight shared, a retune to eight others on a symbol running 32 would
    make 33, refused `symbol`."""
    leases = InstanceLeases()
    retune = _with_a_ctl_holding_eight(leases)
    leases.acquire((SYM, _key(0)), "other", "u9")
    for u in range(2, 5):
        _hold(leases, SYM, 8, f"u{u}", start=u * 8)
    with pytest.raises(InstanceCapError) as caught:
        leases.check(SYM, retune, "u1", "ctl-sub")
    assert caught.value.cap == "symbol"


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
