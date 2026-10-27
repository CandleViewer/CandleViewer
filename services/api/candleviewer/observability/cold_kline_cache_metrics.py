"""The cold kline page cache's series (#2523 lever 5), defined in `observability` so both
`storage` (the cache, `storage.cold.kline_reader`) and `bars.metrics` (which re-exports them onto
the scraped registry) may import them, as `kline_boundary_metrics` is. No labels."""

from __future__ import annotations

from candleviewer.observability.metrics import Counter, Gauge

cv_cold_kline_page_cache_hits_total = Counter(
    "cv_cold_kline_page_cache_hits_total",
    "Cold kline page reads the page cache served, with no DuckDB scan.",
)
cv_cold_kline_page_cache_misses_total = Counter(
    "cv_cold_kline_page_cache_misses_total",
    "Cold kline page reads the page cache did not hold (each scans DuckDB).",
)
cv_cold_kline_page_cache_evictions_total = Counter(
    "cv_cold_kline_page_cache_evictions_total",
    "Cold kline pages evicted, least recently used first, to keep the cache within its bound.",
)
cv_cold_kline_page_cache_bytes = Gauge(
    "cv_cold_kline_page_cache_bytes",
    "Cost of the cold kline page cache's pages (bound: CV_COLD_KLINE_PAGE_CACHE_BYTES).",
)

__all__ = [
    "cv_cold_kline_page_cache_bytes",
    "cv_cold_kline_page_cache_evictions_total",
    "cv_cold_kline_page_cache_hits_total",
    "cv_cold_kline_page_cache_misses_total",
]
