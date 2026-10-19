"""Unit (E42-T05 #966 BK-11): `SourceMisses`, a fetch's misses per source address. Past 10 in a
rolling minute a miss is refused until its minute has room; the first refusal per address and
minute is recorded, its place taken only once the record is written (SR-3456-02); bounded."""

from __future__ import annotations

import candleviewer.admin.backups.misses as misses_module
from candleviewer.admin.backups import limits
from candleviewer.admin.backups.misses import SourceMisses


class Clock:
    now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_the_eleventh_miss_in_a_minute_is_refused_until_its_minute_has_room() -> None:
    assert (limits.MISSES_PER_MINUTE, misses_module.SOURCES_TRACKED) == (10, 1024)
    clock = Clock()
    misses = SourceMisses(clock=clock)
    for _ in range(10):  # one every 5 s, from 1000 s
        assert misses.miss("10.0.0.7") is None
        clock.now += 5.0
    assert misses.miss("10.0.0.7") == 15  # it counts too: the ten from 1005 s fill the minute
    assert misses.miss("10.0.0.8") is None  # another address has its own minute
    clock.now += 15.0
    assert misses.miss("10.0.0.7") is None  # 60 s after 1005 s, the minute has room again


def test_the_wait_rounds_up_to_the_whole_second_the_minute_has_room() -> None:
    """A refused miss counts too, so a client retrying a second early stays refused."""
    clock = Clock()
    misses = SourceMisses(clock=clock)
    for _ in range(10):  # one every 0.5 s, from 1000 s
        assert misses.miss("10.0.0.7") is None
        clock.now += 0.5
    assert misses.miss("10.0.0.7") == 56  # room at 1060.5 s: 55.5 s from 1005 s, rounded up


def test_one_record_per_source_and_minute_taken_only_once_written() -> None:
    clock = Clock()
    misses = SourceMisses(clock=clock)
    assert misses.claim_record("10.0.0.7") is False  # an address with no miss has no refusal
    misses.miss("10.0.0.7")
    assert (misses.claim_record("10.0.0.7"), misses.claim_record("10.0.0.7")) == (True, False)
    misses.settle_record("10.0.0.7", written=False)  # unwritten: the next refusal writes it
    assert misses.claim_record("10.0.0.7") is True
    misses.settle_record("10.0.0.7", written=True)
    clock.now += 59.9
    assert misses.claim_record("10.0.0.7") is False
    clock.now += 0.1
    assert misses.claim_record("10.0.0.7") is True  # a new minute, a new record
    misses.settle_record("10.0.0.9", written=True)  # an untracked address: nothing to settle


def test_tracked_sources_are_bounded_the_least_recent_forgotten_first() -> None:
    misses = SourceMisses(clock=Clock(), per_minute=1, tracked=2)
    for source in ("a", "b", "a", "c"):  # "b" is the least recently missing when "c" comes
        misses.miss(source)
    assert list(misses._sources) == ["a", "c"]
    assert misses.miss("b") is None and misses.miss("c") == 60
    by_default, bound = SourceMisses(clock=Clock()), misses_module.SOURCES_TRACKED
    for n in range(bound + 1):  # one past the bound: the first goes
        by_default.miss(str(n))
    assert len(by_default._sources) == bound and "0" not in by_default._sources
