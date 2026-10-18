# Key-verification fixtures (E27-T03)

Inputs for the API-key verification pipeline (`candleviewer/accounts/verification.py`) and its
adapter parsers (`candleviewer/exchange/bybit/key_info.py`). All eight files are **synthetic,
documented-shape** stand-ins, following the owner exception #1778 group A pattern. Private
endpoints cannot be recorded without a real key, and agents never handle one (C-13.5). #2240
owns the recorded, redacted capture that replaces them.

Shapes follow the exchange's v5 reference pages "Get API Key Information" and "Get Wallet
Balance" and its error-code table. Every file has date 2026-10-15, env demo and no symbol. The
six REST files have `time` 1792054800000 and host `api-demo.bybit.com`; the two `ws_auth_*`
files below have no `time`, and their host is `stream-demo.bybit.com`. Redaction: no key id,
secret, signature or real identifier. The UID is the synthetic `1000001` of
`packages/fixtures/accounts/accounts.json`, `apiKey` is `***`, and the whitelist uses the
documentation address 203.0.113.7 (RFC 5737).

The two `ws_auth_*` files are the private stream's `auth` reply on host `stream-demo.bybit.com`,
with fabricated connection ids and no `time`. Their fields (`success`, `ret_msg`, `op`, `conn_id`)
are the ack that `docs/research/11-backend-tech.md` §2.2 (line 43) gives for the v5 "Connect"
page, not re-read from this network. But `docs/research/06-bybit-api.md` §11 and §12 (lines 353
and 376) give the order-entry stream's `auth` reply as `retCode` and `connId`, and say the same
scheme applies to `/v5/private`. Before these files are replaced, #2240's capture must show which
shape `/v5/private` returns: in the `retCode` shape every reply would read as `exchange_unknown`.

| File                  | Call                             | Notable                                                              |
| --------------------- | -------------------------------- | -------------------------------------------------------------------- |
| `key_info_trade.json` | `GET /v5/user/query-api`         | Compliant trade key: `ContractTrade` and `Derivatives` only, `uta` 1 |
| `wallet_balance.json` | `GET /v5/account/wallet-balance` | The signed no-op probe's success; `time` is the exchange clock       |
| `error_10003.json`    | either call                      | Key unknown on this environment's host (`key_wrong_environment`)     |
| `error_10004.json`    | either call                      | Signature refused: inconclusive, never a verdict (SR-E27-18)         |
| `error_10010.json`    | either call                      | Egress IP not on the key's whitelist (`key_ip_whitelist_mismatch`)   |
| `error_33004.json`    | either call                      | Key past its expiry (`key_expired`)                                  |
| `ws_auth_ok.json`     | private WS `auth`                | Granted (`success` true)                                             |
| `ws_auth_denied.json` | private WS `auth`                | Refused (`success` false); its `ret_msg` is never read               |

Tests derive the other scenarios (fund rights, read-only, `uta` 0, wildcard or extra IPs, near
or past expiry, clock skew, a slow probe) from these files in-test. The 10002, 10018 and 5xx replies are in the shared
corpus `packages/fixtures/bybit/2026-10-05/rest/`.

`key_info_trade.json` gives an IP-bound key an expiry, but the venue's reference fills `expiredAt`
only for keys with no IP binding, and the reply for an IP-bound key is undocumented. Until #2240's
capture shows it, the parser reads an empty `expiredAt`, one at or before the Unix epoch, or a
`deadlineDay` of -1 as no expiry; `test_key_info.py` pins these forms.
