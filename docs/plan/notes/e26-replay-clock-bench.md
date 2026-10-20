# E26-T03 — `ReplayClock` at 100x through the E26-K01 busiest minute

Status: **recorded, not gated.** E26-Q03 wires the regression gate. Ticket #626.

Reproduce: `cd services/api && uv run python bench/replay_clock.py --runs 5`. The harness has no
network. Its smoke test, `tests/unit/replay/test_replay_clock_bench.py`, runs it on fake time.

## Workload

This is E26-T02's dense busiest minute (`bench/replay_source.py`): 242 000 two-level book-delta
rows and 1 200 trades over 60 s, 243 200 events. Each run replays the whole minute through
`ReplaySource` over the in-memory tier and `ReplayClock` into a counting sink, on the event loop's
monotonic clock (`LoopTime`). At 100x the minute is due in 0.6 s from its first event.

The sink counts the events and every out-of-order timestamp. The harness reports:

- the cold first read (`prime_s`), the source's read-ahead fill before the first event, which the
  clock does not count as lateness: its schedule starts once the first event is read;
- the achieved speed ratio (scheduled seconds over wall seconds from the first event), as min,
  p50 and max over the runs;
- how many runs booked backpressure;
- the 1-minute load average at the start.

## Results (5 runs each, i7-13850HX, 28 threads, WSL2, Python 3.12)

**This is not an unloaded machine.** The laptop is shared with other agents' jobs. The 1-minute
load average was 14.2 at the start of the clock run and 14.8 at the start of the source run. Every
figure below is slower than an idle machine would give.

| Run                                                   | wall p50 | cold first read p50 | events/s p50 (whole wall) | achieved ratio min / p50 / max | runs with backpressure | dropped | out of order |
| ----------------------------------------------------- | -------: | ------------------: | ------------------------: | -----------------------------: | ---------------------: | ------: | -----------: |
| `ReplayClock` 100x, paced                             |  0.872 s |             0.272 s |                   278 871 |          0.9994 / 0.9999 / 1.0 |                  0 / 5 |       0 |            0 |
| `ReplayClock` unbounded (-1)                          |  0.719 s |             0.288 s |                   338 401 |                              — |                  0 / 5 |       0 |            0 |
| `ReplaySource` alone, in-memory tier (T02 harness)    |        — |                   — |                   606 124 |                              — |                      — |       — |            — |
| `ReplaySource` alone, cold Parquet tier (T02 harness) |        — |                   — |                    67 790 |                              — |                      — |       — |            — |

Once the first event is read, the clock keeps 100x through the densest recorded minute even at
this load. The worst of five runs reached 0.9994 of the requested speed, and no run fell past
`max_lag_s` or dropped or reordered an event. The wall time is longer than the 0.6 s schedule by
the cold first read: the source fills its read-ahead before it hands over the first batch. That is
E26-T02's producer (#2368). On this in-memory tier it blocks the loop for about 0.2 s to 0.3 s at
start, which breaks C-2.17's 50 ms cap; that is bug #2731. The real hot and cold tiers await I/O
between batches, so their stall may be shorter; #2731 asks for both to be measured.

Caveat: the concurrency review reported ~100 ms mid-run stalls (7 of 10 runs) as cyclic GC over
the bench heap (#2731); the code review saw at most 8.2 ms, at a different load.

An earlier run on the same laptop, before this round's fixes, recorded 0.999 at 100x and 512 k/s
unbounded. Its load was not recorded, so it is not comparable, and it is not claimed as an
unloaded figure. Its ratios were measured over the whole wall time and were bimodal (about 1.0 or
about 0.67) because the cold first read was booked as lateness. The clock now reads the first
event before it anchors its schedule.

## The K01 busiest-minute check of budget #15

Budget #15 asks for 100x crash-free, with no desync. On the in-memory tier, every run was
crash-free, held 100x after the cold first read, and dropped and reordered nothing. Where a
machine cannot keep up, the clock reports the shortfall through the achieved ratio and
`replay_clock_lag_ms` instead of dropping (US-RPL-002). The cold Parquet tier reads 68 k events/s
here (80 k earlier), far below the 405 k/s that 100x needs at this density. There the clock slows
and reports the achieved rate. #2367 tracks the cold-tier shortfall. Whether this holds on an idle
reference machine is for E26-Q03's CI leg to establish.
