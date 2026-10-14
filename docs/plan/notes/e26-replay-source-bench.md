# E26-T02 — `ReplaySource` throughput against the E26-K01 baseline

Status: **recorded, not gated.** E26-Q03 wires the regression gate. Ticket #625; the shortfall is
tracked in #2367.

Reproduce: `cd services/api && uv run python bench/replay_source.py --runs 5`. The harness has no
network and writes Parquet to a temporary directory. Its smoke test is
`tests/unit/replay/test_replay_source_bench.py`.

## Workload

This is E26-K01's dense busiest minute: 242 000 two-level book-delta rows and 1 200 trades over
60 s, 243 200 events. It is deterministic, not recorded data, like K01's synthetic day. Every run
replays the full `ReplaySource` (cursors, `(ts_event, seq)` merge, dedup, bounded read-ahead
queue, consumer) over two tier setups:

- **in-memory**: a bisect-indexed tier, so the number is the source's own cost;
- **cold Parquet**: partitions written by the production `ColdExporter` and read through
  `ParquetRecordedReader` (DuckDB).

## Results (p50 of 5, i7-8550U, Windows 11, Python 3.12 — the K01 laptop class)

| Path                              |  events/s | vs 0.41 M/s (100× busiest minute) |
| --------------------------------- | --------: | --------------------------------: |
| `ReplaySource`, in-memory tiers   |   450 047 |                             1.10× |
| `ReplaySource`, cold Parquet      |    45 552 |                             0.11× |
| K01 `(ts_event, seq)` tuple merge | 2 600 000 |                                 — |
| K01 cold DuckDB `read_parquet`    | 7 300 000 |                                 — |

Re-run after the review fixes: old and new code within noise, back to back on a busier machine.

K01 measured Arrow scans and a merge of tuples, while this harness materialises every event
(Decimal prices, typed payloads), which is what the injector consumes. One ~8 k-row cold window
splits into three costs:

- DuckDB + Arrow: ~3 µs/row. A wide window re-decodes the 1 M-row row group.
- `to_pylist`: ~6 µs/row.
- Canonical mapping: ~10 µs/row.

The cold path therefore does **not** meet the 100× floor at the dense busiest minute. #2367 lists
the options: a streamed cold cursor, columnar mapping, cheaper event structs, process-level
decoding, and an end-to-end re-check of budget #15.
