# Key-verification fixtures (E27-T03)

Inputs for the API-key verification pipeline (`candleviewer/accounts/verification.py`) and its
adapter parsers (`candleviewer/exchange/bybit/key_info.py`). All six files are **synthetic,
documented-shape** stand-ins, following the owner exception #1778 group A pattern. Private
endpoints cannot be recorded without a real key, and agents never handle one (C-13.5). #2240
owns the recorded, redacted capture that replaces them.

Shapes follow the exchange's v5 reference pages "Get API Key Information" and "Get Wallet
Balance" and its error-code table. Every file has date 2026-10-15 (`time` 1792054800000), env
demo (host `api-demo.bybit.com`) and no symbol. Redaction: no key id, secret, signature or real
identifier. The UID is the synthetic `1000001` of `packages/fixtures/accounts/accounts.json`,
`apiKey` is `***`, and the whitelist uses the documentation address 203.0.113.7 (RFC 5737).

| File                  | Call                             | Notable                                                              |
| --------------------- | -------------------------------- | -------------------------------------------------------------------- |
| `key_info_trade.json` | `GET /v5/user/query-api`         | Compliant trade key: `ContractTrade` and `Derivatives` only, `uta` 1 |
| `wallet_balance.json` | `GET /v5/account/wallet-balance` | The signed no-op probe's success; `time` is the exchange clock       |
| `error_10003.json`    | either call                      | Key unknown on this environment's host (`key_wrong_environment`)     |
| `error_10004.json`    | either call                      | Signature refused: inconclusive, never a verdict (SR-E27-18)         |
| `error_10010.json`    | either call                      | Egress IP not on the key's whitelist (`key_ip_whitelist_mismatch`)   |
| `error_33004.json`    | either call                      | Key past its expiry (`key_expired`)                                  |

Tests derive the other scenarios (fund rights, read-only, `uta` 0, wildcard or extra IPs, near
or past expiry, clock skew, a slow probe) from these files in-test. The 10002, 10018 and 5xx replies are in the shared
corpus `packages/fixtures/bybit/2026-10-05/rest/`.
