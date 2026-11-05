"""The clock model (#856 Technical notes; the scout's §2): every interval the two arms report,
and when a sample is discarded for skew. Pure: the arms hand in what the clocks read.

- `offset_ms`: exchange minus host, from #843's `ClockOffset` (the wallet read's envelope `time`
  against the midpoint of its round trip, the best of `OFFSET_SAMPLES`). Its uncertainty is half
  that best round trip.
- Skew, per sample: the measured call's reply envelope `time` against the host's midpoint of
  that exchange moved onto the exchange clock, `|venue - (mid + offset)|`.
- A sample is discarded (`skew`) when that skew, or the offset's own uncertainty, passes
  `SKEW_LIMIT_MS` (500 ms): exactly 500 is kept. A reply without a `time` cannot be checked, so
  it is discarded too.
"""

from __future__ import annotations

from dataclasses import dataclass

from spike.sl_attach.config import SKEW_LIMIT_MS


def _r(value: float) -> float:
    return round(value, 3)


@dataclass(frozen=True, slots=True)
class Exchanged:
    """One HTTP exchange as the harness's tap saw it: the host's wall clock (ms) at send and at
    the whole reply, the reply's envelope `time` (the exchange clock, ms) and its code."""

    path: str
    method: str
    sent_wall_ms: float
    received_wall_ms: float
    venue_ms: int | None
    ret_code: int | None
    status: int
    limit_status: int | None = None
    limit_cap: int | None = None
    limit_reset_ms: int | None = None
    timenow_ms: int | None = None

    @property
    def mid_wall_ms(self) -> float:
        return (self.sent_wall_ms + self.received_wall_ms) / 2


def skew_ms(exchange: Exchanged, offset_ms: float) -> float | None:
    """`|venue - (mid + offset)|`, or `None` when the reply carried no envelope `time`."""
    if exchange.venue_ms is None:
        return None
    return _r(abs(exchange.venue_ms - (exchange.mid_wall_ms + offset_ms)))


def skew_discard(skew: float | None, uncertainty_ms: float | None) -> bool:
    """The 500 ms rule: discard past the limit (500 itself is kept), or when unverifiable."""
    if skew is None or uncertainty_ms is None:
        return True
    return skew > SKEW_LIMIT_MS or uncertainty_ms > SKEW_LIMIT_MS


@dataclass(frozen=True, slots=True)
class AckTiming:
    """Arm (a): the create's call, monotonic seconds at send and at return, and the round trip
    the tap measured for it (ms)."""

    t_send_s: float
    t_ack_s: float
    rtt_ms: float | None

    @property
    def ack_ms(self) -> float:
        return _r((self.t_ack_s - self.t_send_s) * 1000)

    @property
    def overhead_ms(self) -> float | None:
        return None if self.rtt_ms is None else _r(max(0.0, self.ack_ms - self.rtt_ms))


@dataclass(frozen=True, slots=True)
class ExposureTiming:
    """Arm (b): the first execution's `execTime` (exchange clock, ms) and its local ingest
    (host wall, us); the host's wall (ms) and monotonic (s) clocks just before the
    `trading-stop` and at its `200`; the stop reply's envelope `time`; the offset."""

    exec_time_ms: int
    ingest_us: int
    t_stop_send_wall_ms: float
    t_stop_send_s: float
    t_stop_ok_s: float
    t_stop_ok_wall_ms: float
    stop_venue_ms: int | None
    offset_ms: float

    @property
    def exposure_ms(self) -> float:
        """The gated interval (24 §8.8 rule 2): `execTime` to the `200`, on the exchange clock."""
        return _r(self.t_stop_ok_wall_ms + self.offset_ms - self.exec_time_ms)

    @property
    def exposure_venue_ms(self) -> float | None:
        """The cross-check that needs no offset: the stop reply's own `time` minus `execTime`."""
        return None if self.stop_venue_ms is None else float(self.stop_venue_ms - self.exec_time_ms)

    @property
    def push_lag_ms(self) -> float:
        return _r(self.ingest_us / 1000 + self.offset_ms - self.exec_time_ms)

    @property
    def react_ms(self) -> float:
        return _r(self.t_stop_send_wall_ms - self.ingest_us / 1000)

    @property
    def stop_rtt_ms(self) -> float:
        return _r((self.t_stop_ok_s - self.t_stop_send_s) * 1000)
