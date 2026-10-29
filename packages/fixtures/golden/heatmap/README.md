# Heatmap golden (E21-T02, #605)

`columns_BTCUSDT.json`: the first 30 native 100 ms columns of the heatmap engine at
`price_grouping` 5, depth 200, each in its `23-ws-protocol.md` §14.5 form plus `estimated` and
`samples_held` (the column's own sample count). Consumed by
`services/api/tests/unit/orderflow/test_heatmap_golden.py`, which compares floats to a relative
1e-9.

## Provenance (C-13.5)

Input: the recorded corpus `bybit/2026-10-05/ws/orderbook_BTCUSDT.jsonl` (public depth-200 stream,
no account data, already redacted): its opening snapshot and first 30 deltas, one delta per
100 ms of the test's fake clock, through the production `BookEngine` and `HeatmapTopic`. Nothing is
synthesised.

## Regeneration

A deliberate change of the engine's output (windowing, time weighting, rounding of the wire form)
regenerates it, and the PR says why:

    cd services/api && CV_REGEN_GOLDEN=1 uv run pytest tests/unit/orderflow/test_heatmap_golden.py

Review the diff of the JSON before committing it.
