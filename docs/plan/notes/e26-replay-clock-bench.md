# E26-T03 — `ReplayClock` sustained at 100x through the E26-K01 busiest minute

Status: **recorded, not gated.** E26-Q03 wires the regression gate. Ticket #626.

Reproduce: `cd services/api && uv run python bench/replay_clock.py --runs 5`. The harness has no
network. Its smoke test, `tests/unit/replay/test_replay_clock_bench.py`, runs it on fake time.

## Workload

This is E26-T02's dense busiest minute (`bench/replay_source.py`): 242 000 two-level book-delta
rows and 1 200 trades over 60 s, 243 200 events. Each run replays the whole minute through
`ReplaySource` over the in-memory tier and `ReplayClock` into a counting sink, on the event loop's
monotonic clock (`LoopTime`). At 100x the minute is due in 0.6 s. The sink counts the events and
every out-of-order timestamp.

## Results (p50 of 5, i7-13850HX, WSL2 on a shared laptop, Python 3.12)

| Run                                   |    wall | events/s | achieved speed ratio | dropped | out of order |
| ------------------------------------- | ------: | -------: | -------------------: | ------: | -----------: |
| 100x, paced                           | 0.601 s |  404 818 |                0.999 |       0 |            0 |
| unbounded (-1)                        | 0.475 s |  512 200 |                    — |       0 |            0 |
| `ReplaySource` alone (T02, in-memory) |       — |  818 267 |                    — |       — |            — |

The clock costs about 0.7 µs per event on top of the source (512 k/s against 818 k/s). So 100x
holds through the densest recorded minute on this machine, with about 25 % to spare.

Before this slice's hot-loop pass, the clock cost about 1.2 µs per event (415 k/s unbounded), and
100x reached 0.90 of the requested speed. Even then it dropped nothing: it reported the shortfall
through the achieved ratio and the lag histogram, as US-RPL-002 requires.

Budget #15 is met on the in-memory tier: 100x, crash-free, with zero dropped or reordered events.
The cold Parquet tier reads 80 k events/s here (E26-T02 harness), below what 100x needs at this
density. On that tier the clock slows and reports the achieved rate instead of dropping. #2367
tracks the cold-tier shortfall.
