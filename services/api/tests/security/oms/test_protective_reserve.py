"""E29-X02 (#982), Gherkin 3 "The protective reserve cannot be starved", and AC-17, AC-18 and
AC-30 (SR-E29-14, SR-044c, SR-071; OM-D02, OM-D06, OM-D08): a stop's token is acquired within the
`critical` lane's wait while other traffic fills the budget it draws on.

The real `TokenBucketGovernor`, compressed as the ticket's performance note asks: two tokens a
UID at one a second, or an IP bucket of five at one a second, on a clock that only the governor's
injected sleep moves (`Clock`), so a run of several budget-seconds takes no real time and never
sleeps (C-13.7). The waits are the adapter's own (`CRITICAL_WAIT_S`, `POLL_WAIT_S`,
`DEFAULT_ENTRY_WAIT_S`). The control is E34-T02's (#859): each case is a strict xfail naming it and
its accepted-risk record (`docs/security/abuse-cases/e29-oms.md`, BQ-5 as ruled), so it turns red
the day #859 lands. `test_the_harness_*` hold what the pins stand on: the traffic fills the
budget past the stop's wait, and a stop with nothing ahead of it is acquired at once.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Final

import pytest

from candleviewer.exchange.base.errors import RateBudgetExceededError
from candleviewer.exchange.base.models import RateLane
from candleviewer.exchange.bybit.config import EndpointClass
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.exchange.bybit.trading import CRITICAL_WAIT_S, DEFAULT_ENTRY_WAIT_S, POLL_WAIT_S

A, B = "100001", "200002"  # two UIDs of one process's governor
ORDER: Final = EndpointClass.ORDER
#: Each case's budget, compressed: a UID's order bucket, or the process's IP bucket.
UID_BUDGET: Final = {"default_capacity": 2.0, "default_refill_per_s": 1.0}
IP_BUDGET: Final = {"default_capacity": 100.0, "default_refill_per_s": 100.0, "ip_budget_per_5s": 5}


@dataclass
class Clock:
    """Budget time that only the governor's sleep moves; each sleep lets the queued takers run, as
    a real wait would, and none waits for real."""

    at: float = 0.0
    slept: list[float] = field(default_factory=list)

    def now(self) -> float:
        return self.at

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.at += seconds
        await asyncio.sleep(0)  # a yield, not a wait


type Traffic = Callable[[TokenBucketGovernor], list[Awaitable[None]]]


def _lane(gov: TokenBucketGovernor, uid: str, lane: RateLane, wait: float, n: int) -> list[Any]:
    return [gov.acquire(uid, ORDER, lane=lane, deadline_s=wait) for _ in range(n)]


#: What fills the budget ahead of the stop, by case: AC-17 a UID's entries and background polls;
#: AC-18 its cancels (risk-reducing, so `critical` too); AC-30 another UID's entries, polls and
#: cancels and a public client's market-data call on the process's IP bucket.
CASES: Final[dict[str, tuple[dict[str, Any], str, Traffic]]] = {
    "ac17": (UID_BUDGET, A, lambda g: [
        *_lane(g, A, "entry", DEFAULT_ENTRY_WAIT_S, 2), *_lane(g, A, "poll", POLL_WAIT_S, 6),
    ]),
    "ac18": (UID_BUDGET, A, lambda g: _lane(g, A, "critical", CRITICAL_WAIT_S, 8)),
    "ac30": (IP_BUDGET, B, lambda g: [
        *_lane(g, A, "entry", DEFAULT_ENTRY_WAIT_S, 5), *_lane(g, A, "poll", POLL_WAIT_S, 3),
        *_lane(g, A, "critical", CRITICAL_WAIT_S, 2), g.acquire_ip_only(),
    ]),
}  # fmt: skip


def _governor(case: str) -> tuple[TokenBucketGovernor, Clock]:
    clock = Clock()
    return TokenBucketGovernor(**CASES[case][0], clock=clock.now, sleep=clock.sleep), clock


async def _run(case: str, *, stop: bool = True) -> tuple[float | None, Clock]:
    """The case's traffic, queued first, then the stop's acquisition: how long the stop waited on
    the budget's clock, or None when it was refused (nothing would be sent)."""
    gov, clock = _governor(case)
    waited: list[float | None] = []

    async def placement() -> None:
        started = clock.now()
        try:
            await gov.acquire(CASES[case][1], ORDER, lane="critical", deadline_s=CRITICAL_WAIT_S)
        except RateBudgetExceededError:
            waited.append(None)
            return
        waited.append(clock.now() - started)

    calls = [*CASES[case][2](gov), *([placement()] if stop else [])]
    await asyncio.gather(*calls, return_exceptions=True)  # a refused entry is the traffic's own
    return (waited[0] if waited else None), clock


def _pin(n: int, what: str) -> pytest.MarkDecorator:
    return pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
        f"X02-R{n} (#859): {what} acquires its critical token within the lane's wait"))  # fmt: skip


@pytest.mark.parametrize(
    "case",
    [
        pytest.param("ac17", marks=_pin(1, "a stop placement behind entries and polls")),
        pytest.param("ac18", marks=_pin(2, "a stop attach behind cancels")),
        pytest.param("ac30", marks=_pin(3, "another UID's stop behind the IP bucket's queue")),
    ],
)
async def test_g3_a_stop_acquires_its_token_within_its_wait_while_the_budget_is_full(
    case: str,
) -> None:
    waited, _clock = await _run(case)
    assert waited is not None and waited <= CRITICAL_WAIT_S, (case, waited)


@pytest.mark.parametrize("case", list(CASES))
async def test_the_harness_fills_the_budget_past_the_stops_wait_in_no_real_time(case: str) -> None:
    _none, clock = await _run(case, stop=False)
    assert clock.now() > CRITICAL_WAIT_S, (case, clock.slept)


@pytest.mark.parametrize("case", list(CASES))
async def test_the_harness_acquires_a_stop_with_nothing_ahead_at_once(case: str) -> None:
    gov, clock = _governor(case)
    await gov.acquire(CASES[case][1], ORDER, lane="critical", deadline_s=CRITICAL_WAIT_S)
    assert (clock.now(), clock.slept) == (0.0, [])
