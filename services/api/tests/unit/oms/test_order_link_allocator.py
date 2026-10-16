"""§8.3 rules 4 and 5 (E29-T02, #846), per rulings B1 (lookup port + fake), Q1 (any
row in any state collides), Q3 (`replaces_order_id`) and Q6 (16 increments, <= 3843)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from uuid import UUID

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.domain.primitives import AccountId, GroupId, OrderId, OrderLinkId
from candleviewer.oms.errors import InvalidOrderLinkId, OrderLinkIdExhausted
from candleviewer.oms.fakes import InMemoryOrderLinkLookup
from candleviewer.oms.order_link import SEQ_MAX, OrderLinkIdParts
from candleviewer.oms.order_link_allocator import (
    MAX_SEQ_INCREMENTS,
    OrderLinkIdAllocator,
    OrderLinkLookup,
)

GROUP = GroupId(UUID("0f8e2b6c-3d4a-4b5c-9e7f-1a2b3c4d5e6f"))
ACCOUNT = AccountId(UUID("5b1c9d2e-7f30-4a6b-8c4d-2e3f4a5b6c7d"))
REPLACED = OrderId(UUID("9a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"))
seqs = st.integers(min_value=0, max_value=SEQ_MAX)


def _id(seq: int = 0) -> OrderLinkIdParts:
    return OrderLinkIdParts.generate(
        mode="exchange",
        environment="demo",
        group_id=GROUP,
        account_id=ACCOUNT,
        seq=seq,
        purpose="entry",
    )


def _taken(taken: Iterable[int]) -> InMemoryOrderLinkLookup:
    return InMemoryOrderLinkLookup(_id(seq).value for seq in taken)


def _looked_up(lookup: InMemoryOrderLinkLookup) -> list[int]:
    return [OrderLinkIdParts.parse(value).seq for value in lookup.lookups]


class _BothLookBeforeEitherPersists:
    """An `OrderLinkLookup` that answers only once `parties` allocations have asked: the
    window between the check and the INSERT, closed deterministically."""

    def __init__(self, rows: InMemoryOrderLinkLookup, parties: int) -> None:
        self._rows = rows
        self._barrier = asyncio.Barrier(parties)

    async def exists(self, order_link_id: OrderLinkId) -> bool:
        taken = await self._rows.exists(order_link_id)
        await self._barrier.wait()
        return taken


async def test_in_memory_lookup_reports_persisted_rows_as_taken() -> None:
    fake = InMemoryOrderLinkLookup()
    port: OrderLinkLookup = fake  # mypy checks the structural match

    fake.add(_id(0).value)

    assert await port.exists(_id(0).value) is True
    assert await port.exists(_id(1).value) is False


async def test_free_candidate_is_allocated_after_a_single_lookup() -> None:
    lookup = InMemoryOrderLinkLookup()

    allocated = await OrderLinkIdAllocator(lookup).allocate(_id(0))

    assert allocated.order_link_id == _id(0).value
    assert allocated.replaces_order_id is None
    assert _looked_up(lookup) == [0]


async def test_local_collision_is_caught() -> None:
    """Scenario: Local collision is caught (any state, ruling Q1)."""
    lookup = _taken({0})

    with capture_logs() as logs:
        allocated = await OrderLinkIdAllocator(lookup).allocate(_id(0))

    assert allocated.order_link_id == _id(1).value
    assert logs == [
        {
            "event": "order_link_id_collision",
            "log_level": "warning",
            "order_link_id": _id(0).value,
            "next_order_link_id": _id(1).value,
        }
    ]


@pytest.mark.parametrize(("taken", "allocated_seq"), [({0, 1, 2}, 3), (set(range(16)), 16)])
async def test_collisions_take_the_first_free_seq_up_to_the_16th_increment(
    taken: set[int], allocated_seq: int
) -> None:
    lookup = _taken(taken)

    allocated = await OrderLinkIdAllocator(lookup).allocate(_id(0))

    assert allocated.parts == _id(allocated_seq)
    assert _looked_up(lookup) == list(range(allocated_seq + 1))


async def test_still_colliding_after_16_increments_is_exhausted() -> None:
    lookup = _taken(range(MAX_SEQ_INCREMENTS + 1))

    with pytest.raises(OrderLinkIdExhausted) as exc_info:
        await OrderLinkIdAllocator(lookup).allocate(_id(0))

    assert _looked_up(lookup) == list(range(17))
    assert (exc_info.value.first, exc_info.value.last) == (_id(0).value, _id(16).value)


async def test_never_increments_past_seq2_3843() -> None:
    lookup = _taken(range(SEQ_MAX - 2, SEQ_MAX + 1))

    with pytest.raises(OrderLinkIdExhausted):
        await OrderLinkIdAllocator(lookup).allocate(_id(SEQ_MAX - 2))

    assert _looked_up(lookup) == [3841, 3842, 3843]


@pytest.mark.parametrize(("taken", "allocated_seq"), [({4}, 5), ({4, 5, 6}, 7)])
async def test_replacement_takes_the_next_free_seq_and_returns_replaces_order_id(
    taken: set[int], allocated_seq: int
) -> None:
    lookup = _taken(taken)

    allocated = await OrderLinkIdAllocator(lookup).allocate_replacement(
        _id(4).value, replaces_order_id=REPLACED
    )

    assert allocated.parts == _id(allocated_seq)
    assert allocated.replaces_order_id == REPLACED
    assert _looked_up(lookup) == list(range(5, allocated_seq + 1))


async def test_replacing_seq2_3843_is_exhausted_without_a_lookup() -> None:
    lookup = InMemoryOrderLinkLookup()

    with pytest.raises(OrderLinkIdExhausted):
        await OrderLinkIdAllocator(lookup).allocate_replacement(
            _id(SEQ_MAX).value, replaces_order_id=REPLACED
        )

    assert lookup.lookups == []


async def test_an_adopted_ext_key_cannot_be_replaced_by_seq() -> None:
    with pytest.raises(InvalidOrderLinkId):
        await OrderLinkIdAllocator(InMemoryOrderLinkLookup()).allocate_replacement(
            "ext-" + "0" * 32, replaces_order_id=REPLACED
        )


async def test_two_allocations_of_one_candidate_can_both_get_it_so_the_loser_re_allocates() -> None:
    """`allocate` checks, it does not reserve: the unique index tells two racing allocations
    apart at INSERT time. The loser's `ux_orders_link` violation is a collision like any
    other: it allocates again from the same candidate, which now skips the winner's row."""
    rows = InMemoryOrderLinkLookup()
    allocator = OrderLinkIdAllocator(_BothLookBeforeEitherPersists(rows, parties=2))

    winner, loser = await asyncio.gather(allocator.allocate(_id(0)), allocator.allocate(_id(0)))
    rows.add(winner.order_link_id)  # the first INSERT wins `ux_orders_link`

    assert winner.order_link_id == loser.order_link_id == _id(0).value  # both saw it free
    again = await OrderLinkIdAllocator(rows).allocate(_id(0))
    assert again.parts == _id(1)  # one increment past the candidate, inside rule 5's bound


@given(start=seqs, offsets=st.sets(st.integers(min_value=0, max_value=MAX_SEQ_INCREMENTS + 2)))
async def test_allocation_returns_the_first_free_seq_within_16_increments(
    start: int, offsets: set[int]
) -> None:
    taken = {start + offset for offset in offsets if start + offset <= SEQ_MAX}
    free = [seq for seq in range(start, min(start + 16, SEQ_MAX) + 1) if seq not in taken]
    assume(free)
    lookup = _taken(taken)

    allocated = await OrderLinkIdAllocator(lookup).allocate(_id(start))

    assert allocated.parts == _id(free[0])
    assert _looked_up(lookup) == list(range(start, free[0] + 1))


@given(start=seqs)
async def test_a_fully_taken_window_is_always_exhausted(start: int) -> None:
    window = range(start, min(start + MAX_SEQ_INCREMENTS, SEQ_MAX) + 1)
    lookup = _taken(window)

    with pytest.raises(OrderLinkIdExhausted):
        await OrderLinkIdAllocator(lookup).allocate(_id(start))

    assert _looked_up(lookup) == list(window)
