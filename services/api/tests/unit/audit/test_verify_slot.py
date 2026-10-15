"""Verify single-flight (`VerifySlot`): on-demand runs try, scheduled runs wait and are never
skipped. Events and scheduler turns only, no sleeps."""

from __future__ import annotations

import asyncio

from candleviewer.audit.verify_slot import VerifySlot


async def test_one_run_at_a_time() -> None:
    slot = VerifySlot()
    assert slot.try_acquire() and slot.held
    assert not slot.try_acquire()  # a second on-demand run: 409
    slot.release()
    assert not slot.held and slot.try_acquire()


async def test_a_waiting_scheduled_run_gets_the_slot_and_is_never_skipped() -> None:
    slot = VerifySlot()
    assert slot.try_acquire()  # an on-demand run holds it
    first = asyncio.ensure_future(slot.acquire())
    second = asyncio.ensure_future(slot.acquire())
    await asyncio.sleep(0)  # both are queued
    slot.release()  # handed straight to the first waiter
    assert not slot.try_acquire()  # an on-demand run cannot slip in between
    await first
    assert slot.held and not second.done()
    slot.release()
    await second
    slot.release()
    assert not slot.held


async def test_a_cancelled_waiter_leaves_the_queue() -> None:
    slot = VerifySlot()
    assert slot.try_acquire()
    waiter = asyncio.ensure_future(slot.acquire())
    await asyncio.sleep(0)
    waiter.cancel()
    await asyncio.gather(waiter, return_exceptions=True)
    slot.release()
    assert not slot.held and slot.try_acquire()  # nobody left waiting


async def test_a_slot_handed_over_as_its_waiter_is_cancelled_is_given_back() -> None:
    slot = VerifySlot()
    assert slot.try_acquire()
    waiter = asyncio.ensure_future(slot.acquire())
    await asyncio.sleep(0)
    slot.release()  # handed over ...
    waiter.cancel()  # ... and cancelled before the waiter ran
    await asyncio.gather(waiter, return_exceptions=True)
    assert waiter.cancelled() and not slot.held
