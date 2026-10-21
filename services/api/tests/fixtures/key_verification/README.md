# Key-verification fixtures (E27-T03)

Inputs for the API-key verification pipeline (`candleviewer/accounts/verification.py`) and its
adapter parsers (`candleviewer/exchange/bybit/key_info.py`). The eight files in the table are
**synthetic, documented-shape** stand-ins, following the owner exception #1778 group A pattern;
`key_info_docs_example.json` is the documented reply itself, transcribed (see below). Private
endpoints cannot be recorded without a real key, and agents never handle one (C-13.5). The
owner's recorded, redacted capture that replaces them is queued on #2701 ("#2240 recorded fixture
via demo key").

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
scheme applies to `/v5/private`. Before these files are replaced, the owner's capture must show
which shape `/v5/private` returns: in the `retCode` shape every reply would read as `exchange_unknown`.

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
only for keys with no IP binding; its Response Example, an IP-bound key, prints `expiredAt` at the
Unix epoch and `deadlineDay` -2. Until the owner's capture shows a real reply, the parser reads an
empty `expiredAt`, one at or before the Unix epoch, or a `deadlineDay` of -1 as no expiry;
`test_key_info.py` and `test_key_info_drift.py` pin these forms.

## The documented reply and recorded captures (#2240)

`key_info_docs_example.json` is the Response Example of the v5 "Get API Key Information" page
(`GET /v5/user/query-api`): its keys, order and values as printed, but for four redactions. It
prints `"Wallet": ["AccountTransfer", "SubMemberTransfer"]`. The page's parameter table also names
`SubMemberTransferList` (sub account) and `Withdraw` (master account); those enter only as
table-derived cases of `tests/unit/accounts/_permission_cases.py`. It is evidence of the
documented shape only, never of live values.

`recorded/manifest.json` lists it and every recorded capture, with the field names of G-8's corpus
manifests (#2877): `path` (relative to `recorded/`), `stream` (`GET /v5/user/query-api`), `source`
(`docs-transcribed` for the transcription), `host`, `capture_date` and `http_status`, plus
`retrieved`, `source_url` and `source_ref` for the transcription. A capture adds `kind`: `trade`, a
compliant key that every gate passes, or `fund_rights`, a key with a transfer or withdrawal right,
queried once and never imported, that every gate refuses. Its line below gives env `demo` and its
redaction: the key `id`, `apiKey`, `userID` and `userIDInt64` (to 1000001) and `ips` (to RFC 5737
addresses). `tests/unit/exchange/bybit/test_key_info_drift.py` compares each capture's field paths
and JSON types with the transcription's and runs it through the gates, and the shared corpus runs
its `permissions` through every deny-list layer and the `ak_snapshot_shape` CHECK.

Recorded capture: owed (owner, #2701).

Each line: file; source; date; symbol; env; redaction.

- `key_info_docs_example.json`: source: docs-transcribed, `user/apikey-info` (`bybit-exchange/docs` commit `19518b90fb36`, `docs/v5/user/apikey-info.mdx`); 2026-10-21; symbol none; env none (a documentation example; its `note` says testnet); redaction: `id` to `1000`, `apiKey` to `***`, `userID` to 1000001, the three `ips` to 203.0.113.7, 203.0.113.8 and 203.0.113.9 (RFC 5737); `userIDInt64` prints "0", no id, and is kept.

### Drift triage

1. **Read the diff.** It names every field path that is recorded only, transcribed only or retyped.
2. **Venue change (the usual case).** The capture is the truth: update the parser
   (`exchange/bybit/key_info.py`) and its tests. As in G-8, the recording then replaces the
   transcription: delete it, its manifest entry and its line above, and derive the corpus's
   `docs_*` cases from the capture.
3. **Capture defect.** Re-record and redact again. Never edit the transcription or a capture to
   silence the test.
4. **Cannot fix now.** Keep the test red, or quarantine it per C-9.3 (24 h, P1 ticket); never
   delete it.
