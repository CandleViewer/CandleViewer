"""E49-Q01 (#1335): the GA regression pack's tooling (stdlib only).

``specs`` reads the pack's tags from the Playwright specs, ``health`` is the pack's own health
check, ``shard_plan`` balances the nightly shards, ``coverage_map`` maps Must stories to pack
scenarios, ``scrub_artifacts`` strips credentials from failure artefacts and ``report`` builds the
nightly report and metrics. docs/plan/03-testing-strategy.md §7.1 describes the pack.
"""
