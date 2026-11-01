"""Harness guards for the bars chaos suite (E12-Q06; C-13.5, C-13.7).

* The suite cannot reach live Bybit, and it never starts the real-time bars ticker.
* The golden oracle is E12-Q02's runner over what the venue printed: a clean run through the
  rig equals it, so every scenario's "equals the golden" claim rests on a checked oracle.
* Same seed => same bars (determinism).
* The invariant helpers fail on a naive result (they are not vacuous).
"""

from __future__ import annotations

import socket

import pytest

from candleviewer.bars.builder_set import BarBuilderSet
from tests._ci_network_guard import NetworkGuardViolation, Refusal, expected_refusals
from tests.chaos.bars import _golden as golden
from tests.chaos.bars._rig import SPECS, SYMBOL, BarsRig
from tests.chaos.bars.conftest import SEED
from tests.chaos.ingestion._feed import Feeder
from tests.chaos.ingestion._rig import Rig

pytestmark = pytest.mark.chaos

CLEAN_RUN_S = 30.0


async def _clean_run(seed: int) -> tuple[Rig, BarsRig]:
    rig = Rig(seed=seed)
    await rig.start()
    bars = BarsRig(rig)
    await bars.start()
    await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="open")
    await bars.run(Feeder(rig.ex), CLEAN_RUN_S)
    await bars.finish()
    return rig, bars


def test_live_exchange_host_is_unreachable_from_the_suite() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with expected_refusals() as refused, pytest.raises(NetworkGuardViolation):
            sock.connect(("api.bybit.com", 443))
    finally:
        sock.close()
    assert refused == [Refusal("connect", "api.bybit.com")]


async def test_the_real_time_ticker_is_never_started() -> None:
    with pytest.raises(AssertionError, match="virtual clock"):
        await BarBuilderSet.start(object.__new__(BarBuilderSet))


async def test_a_clean_run_equals_the_e12_q02_golden_of_the_venue_tape() -> None:
    rig, bars = await _clean_run(SEED)
    try:
        tape = golden.venue_tape(rig, SYMBOL)
        assert len(tape) > 20, "the corpus produced too few prints to say anything"
        expected = await golden.golden_bars(tape, SPECS, SYMBOL)
        for label in SPECS:
            assert len(bars.bars(label)) > 3, f"{label}: too few bars"
            golden.assert_matches_golden(expected[label], bars.bars(label), label)
    finally:
        await rig.stop()


async def test_same_seed_gives_identical_bars() -> None:
    runs = []
    for _ in range(2):
        rig, bars = await _clean_run(SEED)
        runs.append({label: [b.model_dump_json() for b in bars.bars(label)] for label in SPECS})
        await rig.stop()
    assert runs[0] == runs[1]


async def test_golden_helpers_fail_on_a_naive_result() -> None:
    """Negative control of the helpers themselves: dropped, doubled and reordered bars."""
    rig, bars = await _clean_run(SEED)
    try:
        expected = await golden.golden_bars(golden.venue_tape(rig, SYMBOL), SPECS, SYMBOL)
        vol = bars.bars("vol:1")
        with pytest.raises(AssertionError, match="differs from the golden"):
            golden.assert_matches_golden(expected["vol:1"], vol[:-2], "dropped tail")
        with pytest.raises(AssertionError, match="volume not conserved"):
            golden.assert_conserved(expected["vol:1"], [*vol, vol[0]], "doubled bar")
        with pytest.raises(AssertionError, match="opens before"):
            golden.assert_monotonic(
                [
                    vol[1].model_copy(update={"index": 1}),
                    vol[2].model_copy(update={"index": 2}),
                    vol[0].model_copy(update={"index": 3}),
                ],
                "reordered",
            )
    finally:
        await rig.stop()
