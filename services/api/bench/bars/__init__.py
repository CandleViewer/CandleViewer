"""E12-Q05 bar-building performance pack (#528): reporting math and guards.

Slice 1 holds the pure, offline pieces every harness reports through (`stats`, `compare`,
`guard`, `scrub`): percentiles and the median-of-3 pick, the 5 % regression compare
(06-performance §7.4), the loopback-only target guard and the report scrubber. Slice 2 adds
`throughput` (six builder families). Rebuild, backfill, fan-out and engine series follow.
It reuses `bench.ingestion.budgets.percentile`; nothing here is forked.
"""

HARNESS_VERSION = "e12-q05/1"
