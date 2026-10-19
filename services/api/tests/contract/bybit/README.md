# Bybit adapter contract pack (E08-Q02)

Raw recorded Bybit frames in, internal domain events out. Everything reads the
`packages/fixtures/bybit/<date>/` corpus (E08-T05) through `tests/_corpus.py`: offline,
deterministic, injected clocks, no network (C-13.5). The pack asserts the **boundary**, so it
survives refactors behind it and is reusable verbatim by a second exchange adapter
(`24-internal-schemas.md` §14.2 rule 5).

| Module                         | Stream / concern                                                          | E08-Q01 cases                      |
| ------------------------------ | ------------------------------------------------------------------------- | ---------------------------------- |
| `test_contract_trades.py`      | `publicTrade` -> `TradePrint` -> `TradeEvent`, dedupe, malformed prints   | D01-D05                            |
| `test_contract_orderbook.py`   | `orderbook.N` -> `BookSnapshot`/`BookDelta`, gap = invalidate, truncation | E01-E04, E06, E07                  |
| `test_contract_ticker.py`      | `tickers` snapshot/delta merge                                            | C01-C03                            |
| `test_contract_kline.py`       | kline pages, boundary, split-point property                               | F01, F02                           |
| `test_contract_instruments.py` | `instruments-info` filters, delisting, tick change                        | A01, A02, A08, A10, B-group inputs |
| `test_contract_errors.py`      | `10018`/`10002`/`10001`/5xx/HTML -> internal taxonomy                     | F03, F06, A10                      |
| `test_contract_clock.py`       | server-time fixture -> `ClockGuard` offset                                | F04                                |
| `test_contract_leakage.py`     | P3: no Bybit vocabulary outside `exchange/bybit/`; parse-time guard       | all                                |
| `test_contract_feed_rot.py`    | field-manifest drift guard, fixture coverage meta-test, secret scan       | R6                                 |

Added in review round 2: `test_contract_precision.py` (B01-B07), `test_contract_catalogue.py`
(A02-A04, A08, A09), `test_contract_streams_extra.py` (C01-C04, C06, D04, E04),
`test_pipeline_read_surface.py` (stream -> bus -> REST read surface; in-process, no docker, so it
lives in this lane rather than `tests/integration/`) and `test_contract_q01_mapping.py`.

**Case -> test mapping.** The authoritative table is the `E08-TC-*` id in each test docstring plus
the deferred table in [`E08_Q02_COVERAGE.md`](E08_Q02_COVERAGE.md); `test_contract_q01_mapping.py`
parses `qa/plans/e08-market-data-test-plan.md` and fails if an E08-Q02-owned case is in neither.

## Running

```
cd services/api
uv run pytest tests/contract/bybit -q --no-cov
uv run pytest tests/contract/bybit -m "not perf" -q --no-cov     # PR subset (skips timing guard)
```

## Feed-rot triage

<a id="feed-rot-triage"></a>

`test_committed_corpus_matches_the_expected_field_manifest` fails when the field-path set of a
recorded payload differs from `packages/fixtures/bybit/<date>/schema_expectations.json`
(added / removed / retyped; a rename shows as one removed + one added). The nightly
`fixture-drift` workflow reports the same diff for a _fresh_ capture.

1. **Read the diff.** It names the stream and the exact field path.
2. **Decide: venue change or fixture defect?** Re-capture with
   `tools/fixtures/capture_fixture.py` (it records the mainnet public stream; demo has no public
   feed of its own); if the fresh capture shows the same change, Bybit changed the feed. Each
   nightly run that is not cancelled also keeps its redacted capture as the
   `fixture-drift-sample` artifact (#3447).
3. **Venue change (usual case).** Update the adapter parser in `exchange/bybit/` and its unit tests,
   then refresh the corpus and manifest (`python tools/fixtures/drift_check.py --write-expectations`).
   The manifest change is CODEOWNERS-reviewed (`/services/api/exchange/`): never update it only to
   silence the test.
4. **Cannot fix now.** File a `type/defect` + `area/ingestion` issue naming stream + field, link it
   from the PR, and keep the test red or quarantine per C-9.3 (24 h, P1 ticket). Never delete it.
5. **Fixture defect.** Fix `tools/fixtures/build_corpus.py` and regenerate (byte-identical rebuild).

## Adding a stream or fixture

A new manifest entry must be referenced (by its `rest/...` / `ws/...` path) in a
`test_contract_*.py` module, or `test_every_manifest_fixture_is_referenced_by_at_least_one_pack_test`
fails naming it.

## Mutation checks

Recorded in the PR for E08-Q02: delta merge, descending-kline handling, zero-size delete, and the
confirm flag each have a distinct failing test when deliberately broken.
