"""E08-Q04 ingestion performance pack (06-performance §2 budgets #5, #6, #8, #11, #12, #13).

Six checked-in scenarios (`scenarios/*.json`) driven by `runner.py`, judged by the pure
assertion logic in `budgets.py`, compared against `bench/baselines/e08/*.json` by `gate.py`
and written up by `report.py`. Consumes (never forks) the E08-T06 harness
`bench/ingestion_soak.py`. Offline: recorded corpus + seeded synthetic feeds only (C-13.5).
"""

#: Bumped when a metric's definition changes: `gate.compare` reads no baseline from another version.
#: /2: `rss_mb_per_symbol` is the RSS the lanes add (it was the whole process's RSS per symbol).
HARNESS_VERSION = "e08-q04/2"
