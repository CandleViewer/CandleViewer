# `exchange_smoke` - demo connectivity smoke suite (E08-T05)

Proves real connectivity to Bybit **demo**. It covers the instrument catalogue, the server-time
offset, one kline page, a public WS subscribe/receive for trades, tickers and the order book,
and a clean shutdown. An opted-in run currently fails closed: see _Fails closed for now_ below.

```bash
cd services/api
CV_EXCHANGE_SMOKE=1 uv run pytest tests/exchange_smoke -m exchange_smoke --no-cov
```

## The demo-only guard (`_guard.py`)

- **Opt-in.** Without `CV_EXCHANGE_SMOKE=1`, every test is skipped and nothing is resolved.
  The default CI py lane also runs `-m "not exchange_smoke"`, so it never selects them.
- **Demo-only, fail closed.** Before any lookup or socket, the session aborts with
  `SmokeGuardError`, raised when `conftest.py` is imported, in any of these cases:
  - `CV_ENVIRONMENT`, `CV_SMOKE_ENV` or `CV_BYBIT_ENV` is set to anything other than `demo`.
  - `CV_BYBIT_REST_BASE_URL` is not `https://api-demo.bybit.com`.
  - Any `CV_BYBIT*` value names a live host.
- **No credentials.** The run is refused if any `CV_*API_KEY` / `CV_*API_SECRET` is set. The
  suite only calls unauthenticated endpoints.
- **Network guard.** The test network guard refuses a name lookup outside its allow-list
  (#3826). So `conftest.py` resolves `api-demo.bybit.com` and `stream.bybit.com` when it is
  imported, after the demo-only guard passes and before the network guard installs at the first
  test. With `CV_EXCHANGE_SMOKE=1` exported, any run that collects this directory does these two
  lookups, even when `-m "not exchange_smoke"` deselects every test. Only the resolved IPs are
  added to the allow-list; no exchange hostname is ever added. Demo has no public stream of its
  own (C-2.11).
- **Fails closed for now.** The REST and WS clients look the hostnames up again when they
  connect, and the network guard refuses those lookups. So an opted-in run errors at session
  setup with an explicit message, before any test dials. It stays that way until the clients
  can connect to the pre-resolved IPs.

`tests/unit/fixtures_corpus/test_smoke_guard.py` holds the negative tests, including the check
that nothing is resolved without `CV_EXCHANGE_SMOKE=1`. It runs in the default lane.
