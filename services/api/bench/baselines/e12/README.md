# E12-Q05 baselines (#528)

Two kinds, never mixed (06 section 7.4, BQ-09):

- **Reference evidence**: figures from reference hardware or any other host, with host, sha and
  date. Recorded for the evidence pack; never a gate.
- **Same-runner gates**: JSON recorded on the runner that gates (`<scenario>.json`, same shape as
  `bench/baselines/e08`). A gate lands with its baseline; without one the run only records
  (`bench.bars.guard.gate_mode`). Baselines are recorded by a reviewed PR, never under CI.

No gate baseline exists yet: every Q05 run is record-only until one is committed.
