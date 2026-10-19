# E29-K01 demo order-path harness (#843)

Throwaway spike code on branch `spike/oms-demo-path`: never merged, never imported by `candleviewer`,
never run by CI. The owner runs it by hand against the **demo** account; per C-4.5 the finding is
written up and the branch is then deleted. It uses the E08 adapter as it is on `main`: `BybitRestClient`
with its token-bucket governor and retCode taxonomy, `BybitSigner`, `parse_key_info`,
`parse_instrument`, and the OMS `orderLinkId` generator.

## What each mode measures

| Mode                                      | Measures                                                                                                                                                                                                                                                  | #843 acceptance criterion                                                                                                                                       |
| ----------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `orders` (200 cycles over 4 h by default) | `POST /v5/order/create` round trip p50/p95/p99 against the 250 ms share of budget #4; `order_submit_seconds`; private-stream latency (`execTime`/`updatedTime` to receipt); executions seen only through `GET /v5/execution/list`; S5 ordering violations | Budget feasibility; error shapes (10002 with `--capture-10002`, duplicate `orderLinkId` always, 10018 with `--capture-10018`) and the adapter's mapping of each |
| `soak` (24 h by default)                  | Private-stream uptime, drops and reconnects, ping RTT, latency, and the REST-only execution count over the whole window                                                                                                                                   | Source-of-truth assumption                                                                                                                                      |

A cycle reads the touch and the REST exposure, places a small Buy limit with a native `stopLoss`
at the bid, waits up to `--fill-wait-s` for a fill on the private stream, amends the rest one tick
lower and cancels it. Every `--taker-every`-th cycle crosses the ask by one tick, so fills happen.
A partial fill depends on market flow: `summary.md` reports how many cycles saw one. The first
order is sent twice with the same `orderLinkId` (the duplicate capture). The demo 7-day retention
(24 §8.3 rule 6) is a note from `--retention-probe`: run a short `orders` run at least 8 days after
a full one, passing the full run's `orders.csv`.

## Before a run

- A demo key from the E27 vault: trading permissions only, withdrawal and transfer off, IP-bound.
- The symbol (`ETHUSDT` by default; `BTCUSDT` and `SOLUSDT` are allowed) is flat with no open
  orders, in one-way position mode, and the demo wallet holds USDT.
- From `services/api/`, with the project venv (`uv sync --frozen`, AGENTS.md §4).

Environment variables, read once and removed from the process environment at start:

- `CV_SPIKE_BYBIT_ENV`: must be `demo`; anything else is refused.
- `CV_SPIKE_BYBIT_API_KEY` and `CV_SPIKE_BYBIT_API_SECRET`: the demo key pair. Set them without
  echo or shell history, for example `read -rs CV_SPIKE_BYBIT_API_KEY && export CV_SPIKE_BYBIT_API_KEY`
  and the same for the secret.

## Commands

```bash
cd services/api
export CV_SPIKE_BYBIT_ENV=demo   # plus the key pair, as above
# 1. The 24 h soak first: its window then covers the orders run's executions too.
python -m spikes.oms_demo_path soak
# 2. In a second terminal (same variables): the 4 h orders run with the 10002 capture.
python -m spikes.oms_demo_path orders --capture-10002 --metrics-port 9464
# 3. Last, and only after the soak ends: the 10018 capture. The burst sends at most
#    --burst-max unsigned server-time reads and may get the host IP held for 10 min or more.
python -m spikes.oms_demo_path orders --orders 2 --hours 0.05 --capture-10018
# 4. At least 8 days later: the retention note.
python -m spikes.oms_demo_path orders --orders 2 --hours 0.05 --retention-probe runs/<run>/orders.csv
```

`--help` lists every option. `BTCUSDT` needs `--lots 2` to stay under the per-order cap. Ctrl-C once
stops between cycles; the run still cancels, flattens and writes its outputs. A second Ctrl-C aborts
(then flatten by hand in the demo UI; the native SL protects the position meanwhile).
`--metrics-port` serves `order_submit_seconds{env="demo",transport="rest"}`, registered from the
metric catalogue through the repo's `Metrics` facade, on `127.0.0.1` for a Prometheus scrape (any
path, so the default `/metrics` works), so Grafana panels can be built on the data; `metrics.prom`
keeps a final copy.

## Guard rails (all in code, before any request leaves)

- Demo only: `CV_SPIKE_BYBIT_ENV` must be `demo` and the hosts must be exactly the demo REST and
  private-stream hosts of `exchange/bybit/config.py`. No host is configurable; every REST request
  passes `GuardedTransport`, which refuses any other host, plain HTTP, and any method and path
  outside an 11-endpoint allow-list. No withdrawal or transfer endpoint is listed or referenced.
- The key pair lives in M2's `Secret` wrappers and is MAC'd by M2's `request_signature` (C-2.7). It
  is never logged, printed, persisted or put in an exception; logging goes through the repo's
  redacting `configure_logging`, and outputs pass the scrubber's known-value check.
- Before anything else: key info is read and a key with any withdrawal or transfer right, or a
  read-only key, is refused (C-2.8, the M13 predicate).
- Every opening order is a Buy limit with a native `stopLoss` below its price (C-2.6); a Sell must
  be reduce-only; an amend may change price or qty only, never the protection. The run cancels what
  it left open and flattens what it opened, and refuses to start unless the symbol is flat.
- USDT linear perpetuals only (allow-list plus `contractType`/`settleCoin` check), at most 250 USDT
  per order and 1000 USDT of position plus resting orders per run (the CLI may lower both only).
- Every REST call goes through the adapter's governor; only the flagged 10018 burst bypasses it.
- `orderLinkId`s follow 24 §8.3 (`cvd-...`); retries reuse them (C-2.10). A create whose outcome is
  unknown is looked up by its id, never re-sent under a new one. The run stops after a key, clock or
  rate refusal, or three failed creates in a row.

## Outputs

`runs/<stamp>-<mode>/`: `summary.md` (the tables for #843), `summary.json`, `rest_calls.csv` (every
request with its round trip), `orders.csv` (cycles; our own `orderLinkId`s, needed by the retention
probe), `ws_items.csv` (stream items with stand-in ids), `metrics.prom`.

`staging/<stamp>-<mode>/bybit/<date>/`: the captures, scrubbed (credential fields masked; UIDs and
account, connection, message, cursor and order ids replaced by stable, shape-keeping stand-ins;
leak-checked, a leaking file is withheld): `rest/<endpoint>_<retCode>.json` (the first reply of each
shape, non-JSON replies as `.txt`), `ws/private_<mode>_<symbol>.jsonl` (frames in receipt order),
`manifest.json` entries in the corpus shape (plus the rate-limit headers where present) and
`README.e29-k01.md` lines (source, date, symbol, env, redaction). `runs/` and `staging/` are
git-ignored.

## Committing the fixtures and recording the results (owner)

1. Read every staged file. Run `node packages/fixtures/scripts/verify.mjs`,
   `python scripts/check_secrets_hygiene.py fixtures` and `gitleaks protect --staged --redact`.
2. Move the files you keep into `packages/fixtures/bybit/<date>/`, merge their entries into its
   `manifest.json` and the README lines into its README. The corpus loader reads plain `.jsonl`
   (the ticket says `.jsonl.gz`); a file above 1.5 MB goes through Git LFS.
3. Paste the `summary.md` tables on #843 and add the addendum to ADR-0006 §Validation, applying the
   ticket's decision rules: create p95 above 250 ms renegotiates budget #4 in
   `06-performance-and-load-standard.md`; any ordering violation gives E29-T05 a reorder buffer on
   `(ts_exec, seq)`; a non-zero REST-only count revises the reconciliation cadence in ADR-0006
   before T06; a retCode the adapter maps differently from 24 §8.6 gets an amendment ticket.

Run the unit tests (pure parts, no network) from `services/api/`:
`pytest spikes/oms_demo_path/tests --no-cov`.
