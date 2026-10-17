# Accounts and key-vault fault-injection pack (E27-Q01)

Exchange-side states for the E27 black-box test plan (`qa/plans/e27-accounts-test-plan.md`, §9.3).
Most of them cannot be produced on demand at the exchange: a withdrawal-enabled key, an allowlist
gap, a UID or UTA mismatch, clock skew, a dead private WS, a 5xx, a `10018`, the 48 h new-key
restriction, an open position. Each of the plan's 49 rows is a directory with a `manifest.json`
that names the calls it stubs, the replies, the private-WS script and the expected outcome in the
plan's words: 46 scenarios and 3 overlays. Every value is fabricated and nothing here comes from a
live call (C-13.5).

`accounts.json` (the synthetic account rows read by `services/api/tests/unit/accounts` and
`credentials_m2`) is older than the pack and unrelated to it.

## Using a scenario

- **Automation (now):** `tests/_account_fixtures.py` in `services/api` resolves a scenario:
  `load("withdraw_enabled", now=<tz-aware datetime>)` returns `reply(method, path, at_ms=...)` for
  REST, `ws` for the private-WS script, `clock` for the anchored times and `egress_ip`.
  `overlays=["open_position_btcusdt_5x_sl"]` combines overlays with it, `switched=True` answers
  after a runtime switch (`stored_key_rejected`), and `load_rotation("rotation_ok", now=...)`
  returns the old and new key. Tests serve the replies to the adapter's own REST client through an
  `httpx.MockTransport` (`tests/unit/exchange/bybit/test_account_fixture_pack.py`).
- **A running stack:** `CV_ACCOUNT_FIXTURE=<scenario>` is #2893's stub transport (last section).
  The synthetic feed (`CV_FEED=synthetic`) serves public market data only (#833).

## Fabricated values

| Value           | Rule                                                                                                |
| --------------- | --------------------------------------------------------------------------------------------------- |
| Account UIDs    | `9000xxxx`: `90000001` (`acct-demo-main`), `90000011` (`acct-demo-sub1`), plan §9.2                 |
| Account kinds   | `90000001` is a main account; `90000011` and `90000012` are its sub accounts (plan §9.2)            |
| Key ids         | `fixture-<scenario>-NNNN`: hyphenated, so never key-shaped; the four-digit tail is unique per pack  |
| Secrets         | `fixture-<scenario>-secret-not-real`, derived by this rule and never stored in a file               |
| Egress IP       | `203.0.113.10` (`egress_ip`); other addresses are RFC 5737 too (`198.51.100.20`, `192.0.2.30`)      |
| Orders          | Ids `00000000-0000-4000-8000-0000000000fN`, links `fixture-order-000N`, fills `...0000000000eN`     |
| Prices          | BTCUSDT around the shared corpus's last trade, `63110.00` (tick `0.10`, qty step `0.001`)           |
| Reference `now` | `2026-10-16T09:00:00Z` (`1792141200000`): the stored `time` values; the loader re-times every reply |

## Manifest format

`manifest.schema.json` (JSON Schema 2020-12) is the contract. A manifest is one of three kinds:
a **key scenario** (one key: `tester_inputs.key_id`), a **rotation pair** (`rotation`) or an
**overlay** (`origin: overlay`). In short:

- `scenario` equals the directory name. `origin` is the plan's Origin column verbatim: `ticket`,
  `ticket (verdict)`, `plan`, `plan (#2417)`, `plan (#2417, E27 threat model AC-15)`,
  `plan (E27 threat model AC-15)` or `overlay`.
- `extends` means "as `<scenario>`": every call, clock field, egress and WS field this manifest
  does not set is answered by that scenario. `compliant` is the root.
- `switch_to` (`stored_key_rejected` only) is a runtime switch: until it the key answers as this
  manifest resolves, after it as the named key scenario, keeping its own key id and secret. On a
  stack the switch is #2893's.
- `egress_ip` is what the deployment's IP echo check answers (SR-033): the address a key's
  allowlist is judged against. The schema allows RFC 5737 addresses only. No reply shape is
  recorded: the echo service is not specified anywhere in the repository.
- `rest` maps `"<METHOD> <path>"` (or `"*"`, every other call) to a reply: `payload` (a file in
  `_base/`, in the scenario directory or in the shared corpus `../bybit/<date>/rest/`), an optional
  RFC 7396 `merge_patch`, `http_status` (default 200), `headers`, and an optional window
  `from_ms`/`until_ms` in scenario time. **Lookup:** the scenario's own manifests along its
  `extends` chain, nearest first, then the overlays in the order named, then the root `compliant`;
  in each, the exact call before `*`. A fault the scenario sets therefore beats the state an
  overlay seeds (`close_rejected` with an open position, `ws_drop_rest_fail`'s 503s), and seeded
  state beats `compliant`'s defaults. A call nothing answers is a test failure, never a silent
  success.
- `clock` sets times relative to the injected `now`: `server_offset_ms` (the stub exchange clock),
  `key_created_offset_ms` and `key_expires_offset_ms` (`null` = no expiry).
- **Scenario time.** `from_ms`, `until_ms` and the timeline's `at_ms` count from the scenario
  start, the injected `now` that the `clock` fields are relative to as well. A scenario starts
  when it is loaded or, when a stored key is switched to it at runtime (plan §9.3 lists those
  cases), at the switch: TC-411's T0. So a transport that switches `ws_blip_20s` in starts its
  10 s to 30 s window at the switch, never at the stack's start.
- `ws.private` is the private-WS script: `on_connect` (`accept`, `refuse`); `on_auth`,
  `on_subscribe` and `on_ping` (`reply` with a payload, `ignore`, `close`); `after_auth` (frames
  sent after every successful auth, `after_ms` relative to it, optional `every_ms`); `timeline`
  (`drop`, `refuse_reconnects`, `accept_reconnects`, `silence` at `at_ms` from the scenario start;
  equal times run in list order).
- `rotation` names the old and new key scenarios of a rotation pair; a pair has no stubs of its
  own.
- An **overlay** seeds exchange-side state (positions, orders, history) for whatever scenario it
  is named with. It carries REST stubs only: no `extends`, key, account, clock, WS, egress or `*`.
- `tester_inputs` is what a tester types (account UID, key id); an overlay has none. No field
  holds a key, secret, signature, token or password value.
- `expected` records the outcome named as in the plan (`outcome` text, `cases`, and for a key
  scenario `verification`, `problem` with the rule after the slash, `health`). Lettered case ids
  (`E27-TC-103a`) are the plan's runs of one case. The plan binds one rule name,
  `key_withdraw_permission` for TC-102, and records the others (pending #2417), except that the six
  inputs of E27 threat model AC-15 must get six different rules. So a recorded rule is the shipped
  pipeline's (`candleviewer/accounts/verification.py`, E27-T03, #2854) where that holds, and a bare
  `validation_failed` where the pipeline gives an AC-15 input another one's rule. The Python suite
  asserts every recorded verdict and rule against the pipeline; the rows where they differ are
  listed below.

**Clock and account.** The loader applies both before the merge patch: the envelope `time` and
`X-Bapi-Limit-Reset-Timestamp` follow the stub exchange clock (`now + server_offset_ms`); server
time (`timeSecond`, `timeNano`) likewise. Key info gets `userID` (the account the key is attached
to), `isMaster` and `parentUid` from that account's kind (`true` and `"0"` for a main account,
`false` and the main account's UID for a sub account), `createdAt`, `expiredAt` (`""` when there is
no expiry, the form the adapter reads as absent) and `deadlineDay`: the days left to `expiredAt`,
rounded up and never below 0, as the source fixture's `180` is against its expiry, and absent when
there is no expiry. This anchors exchange-side times only; it is not an application clock (plan
§9.5): a running stack's test clock is #2893's.

## Scenario index

Unless the row says otherwise, a scenario extends `compliant` and the account is `90000001`.

| Scenario                         | Origin                               | Change from its parent                                                                                                                                | Plan cases (`E27-TC-`)                                      |
| -------------------------------- | ------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| `compliant`                      | ticket (verdict)                     | Root: trade-only key (`unified: 0`, `uta: 1`, plan DC-33) expiring in 365 d, egress echo, healthy probe and WS, trading and mode-switch calls succeed | 012 101 119 121 122 124 211 212 401 405 408 412 413 419 422 |
| `compliant_alt`                  | plan                                 | Second key id (rotation)                                                                                                                              | via `rotation_ok`: 201 202 203 205                          |
| `withdraw_enabled`               | ticket                               | `Wallet: [Withdraw]`                                                                                                                                  | 102 119 126 132a                                            |
| `transfer_enabled`               | plan                                 | `Wallet: [AccountTransfer]`                                                                                                                           | 103a                                                        |
| `subtransfer_enabled`            | plan                                 | `Wallet: [SubMemberTransfer]`                                                                                                                         | 103b                                                        |
| `subtransfer_list_enabled`       | plan                                 | `Wallet: [SubMemberTransferList]`                                                                                                                     | 103c                                                        |
| `fiat_p2p_enabled`               | plan (#2417, E27 threat model AC-15) | `FiatP2P: [FiatP2POrder]`                                                                                                                             | 103d                                                        |
| `fiat_bitpay_enabled`            | plan (#2417)                         | `FiatBitPay: [FaitPayOrder]`                                                                                                                          | 103e                                                        |
| `fiat_convert_broker_enabled`    | plan (#2417)                         | `FiatConvertBroker` non-empty (stand-in right)                                                                                                        | 103f                                                        |
| `bitcard_enabled`                | plan (#2417)                         | `BitCard` non-empty (stand-in right)                                                                                                                  | 103g                                                        |
| `ip_missing`                     | ticket                               | `ips: []`                                                                                                                                             | 104 128 132b                                                |
| `ip_mismatch`                    | ticket                               | `ips: [198.51.100.20]`                                                                                                                                | 105 127                                                     |
| `ip_extra_foreign`               | plan                                 | `ips: [203.0.113.10, 192.0.2.30]`                                                                                                                     | 106a                                                        |
| `ip_wildcard`                    | plan (E27 threat model AC-15)        | `ips: ["*"]`                                                                                                                                          | 106b                                                        |
| `uid_mismatch`                   | ticket                               | Key info pins UID `90000099`                                                                                                                          | 107                                                         |
| `non_uta`                        | ticket                               | `unified: 0` and `uta: 0`, both pinned (plan DC-33)                                                                                                   | 108                                                         |
| `clock_skew`                     | ticket                               | Exchange clock +6 s; probe answers `10002` (inconclusive, SR-E27-18)                                                                                  | 109                                                         |
| `wallet_probe_error`             | ticket                               | Probe answers `10005` on every call (a verdict)                                                                                                       | 110                                                         |
| `missing_trade_scope`            | plan                                 | `ContractTrade: []`                                                                                                                                   | 111                                                         |
| `extra_scope_spot`               | plan                                 | `Spot: [SpotTrade]`                                                                                                                                   | 112                                                         |
| `extra_scope_options`            | plan                                 | `Options: [OptionsTrade]`                                                                                                                             | 112                                                         |
| `extra_scope_exchange`           | plan                                 | `Exchange: [ExchangeHistory]`                                                                                                                         | 112                                                         |
| `extra_scope_nft`                | plan                                 | `NFT` non-empty (stand-in right)                                                                                                                      | 112                                                         |
| `extra_scope_affiliate`          | plan                                 | `Affiliate` non-empty (stand-in right)                                                                                                                | 112                                                         |
| `live_key_on_demo`               | ticket (verdict)                     | Every signed call answers `10003`; WS closes on auth                                                                                                  | 113                                                         |
| `unknown_key`                    | plan                                 | Extends `live_key_on_demo`: identical answers, its own key id                                                                                         | 133                                                         |
| `stored_key_rejected`            | plan                                 | As `compliant`; `switch_to: live_key_on_demo`                                                                                                         | 134                                                         |
| `demo_ws_unreachable`            | plan                                 | Private WS refuses connections                                                                                                                        | 115                                                         |
| `expiring_13d`                   | ticket (verdict)                     | Expiry `now` + 13 d                                                                                                                                   | 116                                                         |
| `expiring_15d`                   | ticket (verdict)                     | Expiry `now` + 15 d                                                                                                                                   | 117                                                         |
| `expired_key`                    | plan                                 | Expiry `now` - 1 d                                                                                                                                    | 212                                                         |
| `new_key_48h`                    | ticket                               | Created `now` - 2 h; nothing else differs (no restriction reply)                                                                                      | 130                                                         |
| `bybit_5xx`                      | ticket                               | HTTP 503 on every REST call                                                                                                                           | 122 129                                                     |
| `rate_limited_10018`             | ticket                               | `10018` with the three rate-limit headers on every REST call                                                                                          | 123                                                         |
| `ws_auth_timeout`                | plan                                 | WS never answers auth                                                                                                                                 | 125                                                         |
| `ws_auth_then_drop`              | ticket                               | One wallet snapshot; at 5 s reconnects refused and the connection dropped                                                                             | 403 409                                                     |
| `ws_quiet`                       | plan                                 | One wallet snapshot, then pongs only                                                                                                                  | 406 407                                                     |
| `ws_quiet_rest_fail`             | plan                                 | Extends `ws_quiet`; every `wallet-balance` call answers HTTP 503                                                                                      | 405                                                         |
| `ws_drop_rest_fail`              | plan                                 | Extends `ws_auth_then_drop`; HTTP 503 on every REST call                                                                                              | 404 410 412                                                 |
| `ws_blip_20s`                    | plan                                 | Switched in at runtime once stored; 10 s to 30 s after the switch: WS dropped, reconnects refused, REST 503                                           | 411                                                         |
| `rotation_ok`                    | plan                                 | Pair: old `compliant`, new `compliant_alt`                                                                                                            | 201 202 203 205                                             |
| `rotation_new_key_withdraw`      | plan                                 | Pair: old `compliant`, new `withdraw_enabled`                                                                                                         | 204                                                         |
| `key_delete_5xx`                 | plan                                 | Account `90000011`; both key-delete calls answer 503 (a negative guard)                                                                               | 306                                                         |
| `close_rejected`                 | plan                                 | Account `90000011`; order create rejected with `110017` (reduce-only)                                                                                 | 305                                                         |
| `leverage_ok`                    | plan                                 | Set-leverage answers `retCode` 0                                                                                                                      | 415 417 418                                                 |
| `leverage_refused_open_position` | plan                                 | Set-leverage refused with `110013` (risk limit level)                                                                                                 | 416                                                         |
| `open_position_btcusdt_5x_sl`    | overlay                              | One 0.001 BTCUSDT long at 5x with a native SL; mode switches refused (`110024`; margin mode `110073`, unconfirmed)                                    | 126 132 205 302-305 310 316 410 412 415-418 420             |
| `working_orders_2`               | overlay                              | Two resting BTCUSDT limit orders; mode switches refused (`110028`; margin mode `110073`, unconfirmed)                                                 | 126 132 205 310 314 421                                     |
| `history_round_trip`             | overlay                              | Order history: a filled market buy and its reduce-only sell; their two fills                                                                          | 311                                                         |

## Provenance (C-13.5)

Private endpoints cannot be recorded without a real key, and agents never handle one. Every REST
reply is therefore a **synthetic, documented-shape stand-in** under the owner's exception (#1778
item A), like `services/api/tests/fixtures/key_verification/` (whose six files the REST bases are
derived from). As plan §9.3 says, #2240's recorded, redacted `query-api` capture replaces the
key-info replies in both places, and #2893 (scope item 10) verifies the other stand-ins against
the v5 documentation or that capture. Env `demo` means the demo hosts: REST `api-demo.bybit.com`,
private WS `stream-demo.bybit.com/v5/private`. The date is the reference `now`: nothing was
captured.

One line per file (C-13.5: source, date, symbol, env, redaction):

| File                                                       | Source                                                                                                         | Date       | Symbol                                  | Env  | Redaction                                                                                                                                                                              |
| ---------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- | ---------- | --------------------------------------- | ---- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `_base/query_api.json`                                     | Synthetic; the shape of `key_verification/key_info_trade.json`                                                 | 2026-10-16 | none                                    | demo | `apiKey` `***`, `secret` empty; key `id` `1000`, `note`, UID `90000001` and `ips` `203.0.113.10` (RFC 5737) fabricated                                                                 |
| `_base/wallet_balance.json`                                | Synthetic; the shape of `key_verification/wallet_balance.json`                                                 | 2026-10-16 | none                                    | demo | No identifier; fabricated round balances                                                                                                                                               |
| `_base/error_10003.json`                                   | Synthetic; `key_verification/error_10003.json`                                                                 | 2026-10-16 | none                                    | demo | No identifier                                                                                                                                                                          |
| `_base/error_10004.json`                                   | Synthetic; `key_verification/error_10004.json`                                                                 | 2026-10-16 | none                                    | demo | No identifier                                                                                                                                                                          |
| `_base/ws_auth_ok.json`                                    | Synthetic; the repo's private-WS control frames                                                                | 2026-10-16 | none                                    | demo | No connection or request id                                                                                                                                                            |
| `_base/ws_subscribe_ok.json`                               | Synthetic; as `ws_auth_ok.json`                                                                                | 2026-10-16 | none                                    | demo | No connection or request id                                                                                                                                                            |
| `_base/ws_pong.json`                                       | Synthetic; as `ws_auth_ok.json`                                                                                | 2026-10-16 | none                                    | demo | No connection or request id                                                                                                                                                            |
| `_base/ws_wallet.json`                                     | Synthetic; the `wallet` topic around `wallet_balance.json`'s account object                                    | 2026-10-16 | none                                    | demo | No identifier; the balances of `wallet_balance.json`                                                                                                                                   |
| `_base/fee_rate.json`                                      | Synthetic; research 06 §7, §17                                                                                 | 2026-10-16 | BTCUSDT                                 | demo | No identifier; fabricated rates                                                                                                                                                        |
| `_base/set_leverage_ok.json`                               | Synthetic; the corpus envelope                                                                                 | 2026-10-16 | none                                    | demo | Empty `result`                                                                                                                                                                         |
| `_base/trading_stop_ok.json`                               | Synthetic; the corpus envelope                                                                                 | 2026-10-16 | none                                    | demo | Empty `result`                                                                                                                                                                         |
| `_base/mode_switch_ok.json`                                | Synthetic; the corpus envelope                                                                                 | 2026-10-16 | none                                    | demo | Empty `result`                                                                                                                                                                         |
| `_base/order_ack.json`                                     | Synthetic; research 06 §5, §10                                                                                 | 2026-10-16 | none                                    | demo | `orderId` `00000000-0000-4000-8000-0000000000f1` and `orderLinkId` `fixture-order-0001`, fabricated                                                                                    |
| `_base/order_list_empty.json`                              | Synthetic; the corpus list layout                                                                              | 2026-10-16 | none                                    | demo | Empty list                                                                                                                                                                             |
| `_base/position_list_empty.json`                           | Synthetic; the corpus list layout                                                                              | 2026-10-16 | none                                    | demo | Empty list                                                                                                                                                                             |
| `close_rejected/order_create_rejected.json`                | Synthetic; the corpus error envelope with `110017` and the v5 table's text                                     | 2026-10-16 | none                                    | demo | No identifier                                                                                                                                                                          |
| `leverage_refused_open_position/set_leverage_refused.json` | Synthetic; the corpus error envelope with `110013` and the v5 table's text                                     | 2026-10-16 | none                                    | demo | No identifier                                                                                                                                                                          |
| `<scenario>/manifest.json` (49)                            | Authored from plan §9.3; their merge patches (seeded positions, orders and fills, refusal codes) are synthetic | 2026-10-16 | BTCUSDT in the overlays, none elsewhere | demo | Key ids `fixture-<scenario>-NNNN`, UIDs `9000xxxx`, RFC 5737 addresses, ids `00000000-0000-4000-8000-0000000000fN` (fills `eN`), links `fixture-order-000N`, all fabricated; no secret |

**Redaction evidence.** Nothing here was captured, so nothing needed redacting: every value is
fabricated, and no file holds an API key, secret, signature, session token, real UID, real order
id or real IP address. In CI, `scripts/verify.mjs` (credential patterns, credential-named fields,
the key-shape rule) and `scripts/check_secrets_hygiene.py fixtures` check every file here, and
the Python suite's `test_no_pack_file_holds_a_typed_secret` proves that no derived secret is
stored ("Checks", below).

**Shapes.** The exchange's documentation site was unreachable from the authoring network under
its web policy, so no page was re-read for this pack; #2893 S15 later checked the error codes alone
(below). The "Verified" column says where field names come from.

| File                                                                          | Call                                                                                    | Page (`bybit-exchange.github.io/docs/v5/…`) | Field names from                                                                                                                                                                                                                   | Verified             |
| ----------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- | ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------- |
| `_base/query_api.json`                                                        | `GET /v5/user/query-api`                                                                | `user/apikey-info`                          | `key_verification/key_info_trade.json`                                                                                                                                                                                             | as source            |
| `_base/wallet_balance.json`                                                   | `GET /v5/account/wallet-balance`                                                        | `account/wallet-balance`                    | `key_verification/wallet_balance.json`                                                                                                                                                                                             | as source            |
| `_base/error_10003.json`, `_base/error_10004.json`                            | any signed call                                                                         | error-code table                            | `key_verification/error_10003.json`, `error_10004.json`                                                                                                                                                                            | as source            |
| `_base/ws_auth_ok.json`, `ws_subscribe_ok.json`, `ws_pong.json`               | private WS `auth`, `subscribe`, `ping`                                                  | `ws/connect`                                | the repo's WS control frames (`success`, `op`); op names from `24-internal-schemas.md` §14.3                                                                                                                                       | no: a subset         |
| `_base/ws_wallet.json`                                                        | private WS `wallet` push                                                                | `websocket/private/wallet`                  | `topic`, `data`; `data` holds the wallet-balance account object (research 06 §10)                                                                                                                                                  | no: a subset         |
| `_base/fee_rate.json`                                                         | `GET /v5/account/fee-rate`                                                              | `account/fee-rate`                          | `symbol`, `makerFeeRate`, `takerFeeRate` (research 06 §7, §17); `list` per the corpus                                                                                                                                              | no                   |
| `_base/set_leverage_ok.json`                                                  | `POST /v5/position/set-leverage`                                                        | `position/leverage`                         | the corpus envelope with an empty `result`                                                                                                                                                                                         | no                   |
| `_base/trading_stop_ok.json`                                                  | `POST /v5/position/trading-stop`                                                        | `position/trading-stop`                     | the corpus envelope with an empty `result`                                                                                                                                                                                         | no                   |
| `_base/mode_switch_ok.json`                                                   | `POST /v5/position/switch-mode`, `/switch-isolated`, `POST /v5/account/set-margin-mode` | not cited in research 06                    | the corpus envelope with an empty `result`; the calls from research 06 §1, §6, §7                                                                                                                                                  | no                   |
| `_base/order_ack.json`                                                        | `POST /v5/order/create`, `/cancel`                                                      | `order/create-order`, `order/cancel-order`  | `orderId`, `orderLinkId` (research 06 §5, §10)                                                                                                                                                                                     | no                   |
| `_base/order_list_empty.json`                                                 | `GET /v5/order/realtime`                                                                | `order/open-order`                          | `category`, `list`, `nextPageCursor` as in the corpus                                                                                                                                                                              | no                   |
| `_base/position_list_empty.json`                                              | `GET /v5/position/list`                                                                 | `position/position-info`                    | as above                                                                                                                                                                                                                           | no                   |
| `open_position_btcusdt_5x_sl` merge patch on `_base/position_list_empty.json` | `GET /v5/position/list`                                                                 | `position/position-info`                    | research 06 §6 (`size`, `avgPrice`, `positionValue`, `markPrice`, `liqPrice`, `bustPrice`, `leverage`, `positionIdx`, `tpslMode`, `takeProfit`, `stopLoss`, `trailingStop`, `unrealisedPnl`); `symbol`, `side` as the order fields | no: a subset         |
| `working_orders_2` merge patch on `_base/order_list_empty.json`               | `GET /v5/order/realtime`                                                                | `order/open-order`                          | the order fields of research 06 §5, §10 and `24-internal-schemas.md` §8.9; `orderStatus` (below)                                                                                                                                   | no: a subset         |
| `history_round_trip` merge patches on `_base/order_list_empty.json`           | `GET /v5/order/history`, `GET /v5/execution/list`                                       | `order/order-list`, `order/execution`       | as above; the fills use the execution stream's fields (research 06 §10)                                                                                                                                                            | no: a subset         |
| `close_rejected/order_create_rejected.json`                                   | `POST /v5/order/create`                                                                 | error-code table                            | the corpus error envelope                                                                                                                                                                                                          | code verified by S15 |
| `leverage_refused_open_position/set_leverage_refused.json`                    | `POST /v5/position/set-leverage`                                                        | error-code table                            | the corpus error envelope                                                                                                                                                                                                          | code verified by S15 |

By reference, not copied: `../bybit/2026-10-05/rest/error_10002.json`, `error_10018.json`,
`error_503.json` and `server_time.json` (provenance in `../bybit/README.md` and its manifest).
`wallet_probe_error`'s `10005` reply and the overlays' mode-switch refusals are
`_base/error_10004.json` with a merge patch; of these, only the overlays' margin-mode refusals are
flagged in their manifests. `fee_rate.json` rates, the order and fill ids and prices, and
`fixture-order-NNNN` are fabricated; a stub transport should echo the request's `orderLinkId`.

### Unconfirmed codes and shapes

The refusal codes were checked against the official v5 error table
(<https://bybit-exchange.github.io/docs/v5/error>, page dated 2026-10-14) by main-orchestrator for
#2893 S15, and #3005 brought `mapping.py` and `docs/plan/24-internal-schemas.md` §8.6 in line with
it. A reply's message is that table's description, not a recorded reply, and no test asserts a
message. These codes are confirmed, so their replies are no longer flagged:

- `wallet_probe_error`: `10005` (permission denied) on the probe. The plan asks for a non-zero
  code that SR-E27-18 does not class as inconclusive; the adapter classes this one as a verdict
  about the key. `10004` and `10002` are inconclusive.
- `close_rejected`: `110017`, the reduce-only family ("orderQty will be truncated to zero").
- `leverage_refused_open_position`: `110013`, "Cannot set leverage due to risk limit level."
  (`risk_limit_tier`). It answered `110044` before S15; the table reads that code "Available
  margin is insufficient.", and §8.6 now maps it with the other insufficient-margin rejects.
- `open_position_btcusdt_5x_sl` and `working_orders_2` refuse the position-mode switch
  (`switch-mode`) with `110024` (an existing position) and `110028` (existing open orders). §8.6
  maps both to explicit, non-retryable rejections that keep the mode (never auto-switch mode).
  The Python suite pins every overlay refusal, with the client at its default retry budget (as
  `service.py` builds it), so a `rest.py` that retried one shows as a second send and fails it.

Each reply below still carries `"code_unconfirmed": true` in its manifest. No test asserts its
code: tests compare what the adapter sees with the scenario's own reply.

- Both overlays answer their two margin-mode calls (`switch-isolated`, `set-margin-mode`) with
  `110073`, "Set margin mode failed", which S15 advises for the margin-mode overlays. Whether the
  exchange answers a margin-mode switch refused for an open position or open orders with that
  code is not verified (`110026`, "Cross/isolated margin mode has not been modified.", is the
  no-op, not a refusal). Where the server maps the exchange's refusal instead of checking first,
  TC-421's position-mode refusal can rest on the confirmed `110028`; TC-420's margin-mode refusal
  cannot yet, so a server mapping `110073` by §8.6 alone answers an exchange error, as in TC-416.

`new_key_48h` carries no refusal: the plan row says no restriction reply may be invented (C-13.5)
and the system derives the restriction from `createdAt` (plan §10 DC-23).

Shapes not re-verified:

- the private-WS frames are subsets (the connect page's replies and the wallet push carry more
  fields, such as a connection id, a message, an id and a creation time);
- right names: `SpotTrade`, `OptionsTrade` and `ExchangeHistory` (not re-read), `FiatP2POrder`
  and `FaitPayOrder` (spelt as the E27 threat model, section 5, gives them). No right name is
  documented in the repository for `FiatConvertBroker`, `BitCard`, `NFT` or `Affiliate`, so the
  group's own name stands in. The allow-list refuses any right in those groups, so no verdict
  depends on the spelling;
- the overlays' list entries are field subsets without time fields (a stub serving them anchors
  times on its own clock). `orderStatus` is the status field's name from recollection: research
  06 §10 lists its values (`New`, `Filled`), not the field;
- `deadlineDay`: the rule above (days left, rounded up, 0 once past, absent without expiry) is
  derived from the source fixture, not from the documentation;
- the empty `expiredAt` for a key without expiry (no row uses it now: `compliant` expires in 365
  days, plan §10 DC-27).

### How the pack follows the plan's rows

The pack follows `qa/plans/e27-accounts-test-plan.md` §9.3 on main (#2941, c37e9aab) row for
row: the same 49 names, the origins verbatim, the stub behaviour and the case lists. The lint
gate reads that table and fails on any name, origin or case list that differs (see Checks); the
stub behaviour is checked by review and the Python suite. Where a row leaves the format open:

- `compliant_alt`'s "Via `rotation_ok`" is recorded as `rotation_ok`'s cases (a manifest lists at
  least one case).
- `compliant` also answers `trading-stop`, the native-SL path (C-2.6), which its row does not list.
- `stored_key_rejected` records its runtime switch as `switch_to: live_key_on_demo`.
- Overlays are stateless REST answers. "Closing orders fill" is an accepted order create; the flat
  position list after it, and the private-WS pushes for positions and orders, are state #2893
  keeps. `history_round_trip` seeds exchange-side history only: the audit history comes from
  running the round trip through the application.
- The IP echo check is recorded as the `egress_ip` value, without a reply shape.

### Where the shipped pipeline differs from the plan

The Python suite runs every key scenario through `accounts/verification.py` (#2854). Its verdicts
and rules agree with the recorded ones except in four rows. Three are pinned, so a test fails the
day the pipeline catches up and the row then records the pipeline's answer:

- `new_key_48h` (`PLAN_AHEAD_OF_PIPELINE`): the plan expects one warning naming the 48 h
  restriction (TC-130, DC-23); the pipeline has no such warning and passes the key with none.
- `fiat_p2p_enabled` and `ip_wildcard` (`AC15_SHARED_RULE`): E27 threat model AC-15 refuses each
  of its six inputs with a rule of its own (plan §2: TC-103a, 103d, 104, 106a, 106b and 108). The
  pipeline gives `fiat_p2p_enabled` (TC-103d) the rule of `transfer_enabled` (TC-103a),
  `key_withdraw_permission`. It gives `ip_wildcard` (TC-106b) the rule of `ip_missing` (TC-104),
  `key_ip_whitelist_missing`, with the copy "the key has no IP whitelist". Both rows record a bare
  `validation_failed`: their rule is pending #2417 and must differ.

The fourth is judged outside the pipeline by design, so no pin could flip
(`JUDGED_OUTSIDE_THE_PIPELINE`):

- `ws_auth_timeout`: the plan's `refused` is the test route's private-WS probe (TC-125); the
  pipeline judges the two signed REST calls only, and passes.

Elsewhere the recorded rule is the pipeline's. The pipeline gives every right outside its
allow-list `key_withdraw_permission`, so every transfer, fiat, card and extra-scope row except
`fiat_p2p_enabled` records that rule, which the plan records rather than requires.
`stored_key_rejected` after its switch fails `key_wrong_environment` (a `10003`); TC-134's key
status `invalid` is the status layer's, not the pipeline's. The UTA check (plan DC-33) agrees
with the plan: the adapter reads UTA from `uta` (`exchange/bybit/key_info.py`), so `compliant`
(`unified: 0`, `uta: 1`) passes and `non_uta` (both 0) fails `key_not_unified`. A build that read
the deprecated `unified` would refuse `compliant`, which the plan files against DC-33.

### Where the plan's rows differ from what the exchange would likely do

A real exchange would probably refuse every signed call from a non-allow-listed egress with `10010`
(as `ip_mismatch` would see it), every signed call of an expired key with `33004`, and every signed
call made with a clock 6 s off with `10002`. These variants are not in §9.3; each can become a
scenario of its own once the plan adds it.

## Checks

**The pack checks** (`../scripts/accounts-pack.mjs`, `checkPack`):

- every manifest is checked against the schema by a small validator. It first walks the whole
  schema: an unknown keyword anywhere, or a `$ref` with a sibling keyword, fails;
- the directory name equals `scenario`, and exactly the §9.3 rows are present;
- each manifest's name, `origin` and `expected.cases` equal its row in the plan's §9.3 table,
  which `scripts/verify.mjs` reads from `qa/plans/e27-accounts-test-plan.md` on every run (rows
  checked both ways, en-dash ranges expanded, "Via `x`" read as `x`'s cases, case order
  included). A section, header, row or Cases cell the reader cannot parse fails closed;
- payload files exist and parse, and merge patches apply;
- `extends` chains resolve without cycles, and never through a rotation pair or an overlay;
- every key scenario has `tester_inputs`, answers key info and the probe at 0 ms, and resolves a
  full clock, WS script and `egress_ip`; a `switch_to` names another key scenario without a switch;
- a rotation pair names two key scenarios and carries no stubs or key id of its own;
- an overlay carries REST stubs only: no key, account, clock, WS, egress, `*` or verdict;
- key ids follow the rule, with unique tails;
- there are no orphan files, and no credential-named field holds a value;
- **no bare key-shaped token** appears anywhere under `accounts/`.

**The key-shape rule.** A token is a maximal run of `[A-Za-z0-9_-]` of 18-20 or 36 characters,
purely alphanumeric. It counts when it holds a digit or, if it is letters only, when it has at
least six capitals and six small letters. Hits report length and offset, never the token. The
rule is a tripwire for accidental pastes, not a complete control: a key split by a JSON escape
(`\u0041`) or glued to a hyphen is not a bare token, so reviewers still read the data.

| Where                                                                                                                | Runs                                                                                                                                                                                                                                                                                              | In CI                                                                                                                                                                                                                             |
| -------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pnpm --filter @candleviewer/fixtures lint` (`eslint . --max-warnings=0 && node ./scripts/verify.mjs && vitest run`) | The redaction gate over `raw/`, `golden/`, `bybit/` and `accounts/`, the key-shape rule over `accounts/`, and the pack checks, then the package's vitest suite (the `test` row below); exit 1 on any finding or failing test                                                                      | **js lane, `lint` job** (`pnpm turbo run lint --filter='...[origin/main]'`). It schedules this package whenever a file in it changes; `../turbo.json` makes the data and the plan lint inputs, so no cached run can hide a change |
| `python scripts/check_secrets_hygiene.py fixtures` (repo root)                                                       | The same key-shape rule over `packages/fixtures/accounts/` (every file), plus the field-name rules over every fixture directory                                                                                                                                                                   | **security lane, `gitleaks` job**, step "Credential hygiene gate" (`... all`), on every PR that touches the js, py or infra paths. Its tests and the real-repo scan also run in `governance` on every PR                          |
| `pnpm --filter @candleviewer/fixtures test` (`test/accounts-pack.test.mjs`, `test/verify*.test.mjs`)                 | Unit cases for every rule, the real pack, and planted failures on a temporary copy (CLI exit codes included)                                                                                                                                                                                      | **js lane, `lint` job**: the package's `lint` script ends with `vitest run`, so every planted-failure case runs there (the js unit-test jobs filter to other packages)                                                            |
| `services/api/tests/unit/exchange/bybit/test_account_fixture_pack.py`                                                | Every manifest against the schema with `jsonschema`; every scenario's and overlay's replies through the adapter's REST client, `key_info.py`, `mapping.py` and the permission gates; every key scenario's verdict through the shipped pipeline, against the recorded one, and the AC-15 rule pins | **py lane**, only when the PR also changes `services/api/**` or another `py` path                                                                                                                                                 |

A PR that changes only the plan schedules neither lane, so a §9.3 change and the pack change it
needs go in one PR: the lint gate then compares them.

The adapter-level tests assert that each request is signed with the scenario's key id. The host
they send to is the one the test chose, so that check is a smoke check only; proof of demo/live
isolation (C-2.11) is #2893's request log (plan §9.6).

## A running stack: #2893

Serving a scenario to a running stack is issue #2893 (dev/test only, `security-review`):
`CV_ACCOUNT_FIXTURE=<scenario>`, the overlays, runtime key switching (plan §9.3 lists the cases),
the plan §9.6 request log, a stub-key-safe test clock, and the verification of every stand-in
above. Two of its guards keep real money out of reach and come before anything is served:

- **Fixture keys only (C-2.8, C-4.14).** The transport refuses to start, and never answers, while
  any stored key id does not match `fixture-<scenario>-NNNN`. Otherwise a mis-set variable on a
  stack holding a real demo key would report an empty `Wallet` group for it without contacting
  the exchange, and the withdrawal check would pass.
- **Demo hosts only (C-2.11).** It serves the demo hosts alone and refuses and logs any live or
  testnet request.
