# Executions goldens (E29-S04, #979, BQ-18)

The web fills feature's fixtures: what the shipped code serves for three fixture accounts (Main,
Sub-1, Sub-2; the positions goldens' ids). `apps/web/test/features/positions/fills/` and
`apps/web/test/contract/executions.contract.test.ts` read them; nothing else may.

| File                          | What                                                                                  | Written by                                                     |
| ----------------------------- | ------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| `ws_executions_snapshot.json` | the `executions` snapshot body (`23` §6.2.3, §15.3): every fill of an order, oldest first, but the delta's | `oms.ws_topics.execution_item`, `_snapshot`                    |
| `ws_executions_deltas.json`   | one delta: board 02's last fill, after the snapshot                                   | `execution_item`                                               |
| `rest_list_executions.json`   | `listExecutions` 200, newest first by the SQL keyset (`exec_ts`, `id`)                 | `api.oms_reads.execution_document`                             |
| `rest_get_order.json`         | five `getOrder?include_events=true` 200 bodies: `limit`, `stop_exit`, `amended`, `at_limit`, `market` | `order_document`, `execution_document`, `event_document`       |
| `manifest.json`               | the sources, each mapper with the commit of its file, and each file's sha256          | the generator                                                  |

## Provenance (C-13.5)

Every fill of an order starts as the recorded private `execution` push
`packages/fixtures/bybit/2026-10-05/ws/private-execution.jsonl` (line 1, a Market fill), takes the
values of `docs/design/E29/E29-D03.md` §3.4 (board 02's order, board 04's fan-out over the three
accounts on trade group …7c1e, board 05's entry, stop exit and amended order) and goes through the
shipped chain: the adapter's `classify` and `read_push`, B1's `exec_payload`, the order's totals by
`apply_execution` and the fill step's `order_steps._fill`, then the mappers above. Board 02's maker
fill is split in two, so its order fills in four executions, as the ticket's Gherkin says; every
D03 figure (Σ value 15,853.505, average 63,414.02, fees 7.38760775) is unchanged. The `market`
order's fill keeps the capture's own values. No payload shape is written by hand.

The one fill of no order is an ADL fill on Sub-2: the recorded `execution/list` row
(`.../rest/trading-execution-list.json`) through reconciliation's store path (`parse`,
`to_execution`, `reconciler.new_execution`). It is in the REST body only: `23` §15.3 requires
`order_id`, so no frame carries it (D03 G20). Its recorded empty `feeCurrency` is stored as `USDT`
(`new_execution`'s default, D03 G6). No producer stores a funding fill yet (the adapter sets one
aside, D03 G5), so the type sampler's Funding row is a unit fixture, not a golden.

The two wire forms differ as the server writes them: WS decimals carry no trailing zero
(`money_text`), REST keeps the stored scale (`"0.100"`, `"63414.020000000000000000"`), and REST
`ts` is RFC 3339 to the microsecond where WS `ts_ms` is epoch milliseconds.

## Regeneration

A change of a mapper's output fails the generator's check until the goldens follow it:

    cd services/api && CV_REGEN_GOLDEN=1 uv run pytest tests/unit/oms/test_executions_web_golden.py

Review the JSON diff before committing it. The files are `json.dumps(indent=2)` with LF, so
`.prettierignore` keeps prettier off them.
