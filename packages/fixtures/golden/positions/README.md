# Positions goldens (E29-S01, #911, BQ-22)

The web positions feature's fixtures: what the shipped code serves for three fixture accounts.
`apps/web/test/features/positions/` and `apps/web/test/contract/positions.contract.test.ts` read
them; nothing else may.

| File                                 | What                                                                                     | Written by                                                   |
| ------------------------------------ | ---------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| `ws_positions_snapshot.json`         | the `positions` snapshot body (`23` §15.2), each account's view stamped with its read    | `oms.ws_topics.position_item`                                |
| `ws_positions_deltas.json`           | three deltas: a mark move, a late frame older than the snapshot, a flat removal          | `position_item`; the removal as `OmsTopics._fan_out` sends it |
| `ws_positions_contract_fields.json`  | the snapshot plus `margin_mode`, `realised_pnl_session`, `r_multiple`, `trade_group_id`  | the snapshot, extended (below)                               |
| `ws_wallet_snapshot.json`            | the `wallet` snapshot (`23` §15.4): balances with `account_mm_rate`, health              | `accounts.wallet_topic.balance_item`, `AccountHealth.ws_entry` |
| `ws_system_account_notice.json`      | an `account_notice` (`23` §15.9), `oms.account_resyncing`                                | `oms_stream_wiring.account_notice`                           |
| `rest_list_positions.json`           | `listPositions` 200                                                                      | `api.oms_reads.position_document`                            |
| `rest_list_positions_aggregate.json` | `listPositions?aggregate=true` 200                                                       | `position_document`, `aggregate_positions`, `aggregate_document` |
| `rest_list_exchange_accounts.json`   | `listExchangeAccounts` 200                                                               | `api.exchange_accounts.account_document`                     |
| `manifest.json`                      | the sources, each mapper with the commit of its file, and each file's sha256             | the generator                                                |

## Provenance (C-13.5)

Every row starts as the recorded private `position` push
`packages/fixtures/bybit/2026-10-05/ws/private-position.jsonl` (line 1, a flat BTCUSDT row), takes
the values of `docs/design/E29/E29-D02.md` §5.2's LIVE rows (Main, Sub-1, Sub-2: the account ids
remapped into three fixture accounts), and goes through the shipped chain: the adapter's
`classify` and `read_push`, the projection's `_state`, then the mappers above. No payload shape is
written by hand. Sub-2 is the cross-margin, hedge-mode account.

`ws_positions_contract_fields.json` is the one extension: `23` §6.2.3 says the position row cannot
tell those four members, so no producer sends them, while `23` §15.2 allows them. They carry E29-D02
§5.2's rPnL today, `24` §7.2's R at 4 places and one trade group across Main's and Sub-1's BTCUSDT
legs, so the client's fallbacks (BQ-8) and its trade-group grouping (BQ-10) are tested against
contract-valid frames. E29-T09 (#1029) owns serving them.

The `wallet` amounts are `22`'s `listExchangeAccounts` example for Main; Sub-1's and Sub-2's are
chosen for E29-D02 §5.3 (Sub-2's 72 % margin rate sits in the cross Near tier).

## Regeneration

A change of a mapper's output fails the generator's check until the goldens follow it:

    cd services/api && CV_REGEN_GOLDEN=1 uv run pytest tests/unit/oms/test_positions_web_golden.py

Review the JSON diff before committing it. The files are `json.dumps(indent=2)` with LF, so
`.prettierignore` keeps prettier off them.
