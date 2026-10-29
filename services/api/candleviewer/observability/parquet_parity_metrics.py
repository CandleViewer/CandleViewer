"""BR-16 (#2294): a roll-off archive that is not its hot rows, defined in `observability` so both
`storage` (the read-back, `storage.cold.rolloff_ops`) and `recorder.metrics` (which re-exports it
onto the scraped registry) may import it, as `cold_kline_cache_metrics` is.

`stream` is a `StreamKind` value (a closed enum, 13 values), never a symbol or a path."""

from __future__ import annotations

from candleviewer.observability.metrics import Counter

parquet_hot_cold_parity_mismatch_total = Counter(
    "parquet_hot_cold_parity_mismatch_total",
    "Roll-off archives whose Parquet file differs from the QuestDB rows it holds (row count or"
    " content digest), by stream; the file is not kept and the hot partition stays.",
    labelnames=("stream",),
)

__all__ = ["parquet_hot_cold_parity_mismatch_total"]
