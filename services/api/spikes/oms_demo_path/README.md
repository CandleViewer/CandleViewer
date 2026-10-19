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
| `soak` (24 h by default)                  | Private-stream uptime, drops and reconnects with their windows, ping RTT, latency, and the REST-only executions over the whole window, split by whether the stream was delivering when each happened                                                      | Source-of-truth assumption                                                                                                                                      |

A cycle reads the touch and the REST exposure, places a small Buy limit with a native `stopLoss`
at the bid, waits up to `--fill-wait-s` for a fill on the private stream, amends the rest one tick
lower and cancels it. Every `--taker-every`-th cycle crosses the ask by one tick, so fills happen.
A partial fill depends on market flow: `summary.md` counts the cycles that saw one, by the stream's
`order` pushes and by the REST status at lookup; zero means the run did not observe the S5
ordering of a partial fill. The first order is sent twice with the same `orderLinkId` (the
duplicate capture), once its create is accepted: a refused or unresolved create is not sent again.
A cycle whose reads still fail after the adapter's retries is recorded, its order gets one cancel,
and the run goes on. The demo 7-day retention (24 §8.3 rule 6) is a note from `--retention-probe`:
run a short `orders` run at least 8 days after a full one, passing the full run's `orders.csv`.

## Before a run

- A demo key with trading permissions only: no withdrawal, transfer, wallet, fiat or card right,
  and bound to this host's IP. The preflight refuses any other key (C-2.8). The harness reads the
  pair from environment variables, not from the E27 vault, which never releases a key (C-2.7): see
  Deviations.
- The symbol (`ETHUSDT` by default; `BTCUSDT` and `SOLUSDT` are allowed) is flat with no open
  orders, in one-way position mode, and the demo wallet holds USDT.
- From `services/api/`, with the project venv (`uv sync --frozen`, AGENTS.md §4).

Environment variables:

- `CV_SPIKE_BYBIT_ENV`: read, and must be `demo`; anything else is refused.
- `CV_SPIKE_BYBIT_API_KEY` and `CV_SPIKE_BYBIT_API_SECRET`: the demo key pair, read once at start
  and popped from the process environment, so no child process inherits them. The process's own
  initial environment block still holds them while it runs, so give them to the one command only:
  never `export` them in an interactive shell (see Commands).

## Commands

```bash
cd services/api
# Reads the key id, then the secret, without echo or shell history. The pair lives in a subshell
# and reaches the one python process only.
spike() { ( read -rs k && read -rs s && CV_SPIKE_BYBIT_ENV=demo CV_SPIKE_BYBIT_API_KEY="$k" \
  CV_SPIKE_BYBIT_API_SECRET="$s" python -m spikes.oms_demo_path "$@" ) }
# 1. The 24 h soak first: its window then covers the orders run's executions too.
spike soak
# 2. In a second terminal (define spike there too): the 4 h orders run with the 10002 capture.
spike orders --capture-10002 --metrics-port 9464
# 3. Last, and only after the soak ends: the 10018 capture (an orders run only: with a soak
#    it is refused). The burst sends at most --burst-max unsigned server-time reads and may get
#    the host IP held for 10 min or more.
spike orders --orders 2 --hours 0.05 --capture-10018
# 4. At least 8 days later: the retention note.
spike orders --orders 2 --hours 0.05 --retention-probe runs/<run>/orders.csv
```

`--help` lists every option. `BTCUSDT` needs `--lots 2` to stay under the per-order cap.

Stop requests (Ctrl-C or SIGTERM). The first stops between cycles: the run still cancels, flattens
and writes its outputs, and reports `interrupted` (the 10018 burst does not run). The second cancels
the step in progress (a wait for a fill, a request, the backfill) and the run still winds down: if
the cancel cut the cleanup short it cancels its orders and flattens once more, then it writes what
it has and reports `interrupted`. A soak never flattens: it places no order. A stop request that
cuts that second cleanup short aborts the run, with nothing more cancelled, flattened or written;
the log then says what to do by hand (below). No stop request prints exchange text: an aborted run
logs the error class only.

The exit code is 0 only for a `completed` run; an `interrupted` run, a run `stopped early`, a
cleanup that did not finish and a REST backfill that failed exit 1, a refusal 2.

After a run whose outcome says `cleanup INCOMPLETE`, and after an aborted run, the run's orders may
still rest and a position may still be open (its native SL protects it meanwhile): in the demo UI,
cancel the open orders of the symbol whose `orderLinkId` starts with `cvd-` (the run's), then
flatten the position of the symbol. `orders.csv` lists the run's own ids, if the run got to write it.

A backfill that failed (the outcome then says `REST execution backfill FAILED: the AC2 number ... is
missing`) leaves no REST-only count, the number behind #843's second acceptance criterion:
`summary.json` has `rest_backfill_error`, and `summary.md` heads the parity section with the failure
and reads n/a, not 0, in every cell that needs the listing.

`--metrics-port` serves `order_submit_seconds{env="demo",transport="rest"}`, registered from the
metric catalogue through the repo's `Metrics` facade, on `127.0.0.1` for a Prometheus scrape (any
path, so the default `/metrics` works), so Grafana panels can be built on the data; `metrics.prom`
keeps a final copy.

## Guard rails (all in code, before any request leaves)

- Demo only: `CV_SPIKE_BYBIT_ENV` must be `demo` and the hosts must be exactly the demo REST and
  private-stream hosts of `exchange/bybit/config.py`. No host is configurable; every REST request
  passes `GuardedTransport`, which refuses any other host, plain HTTP, and any method and path
  outside an 11-endpoint allow-list. No withdrawal or transfer endpoint is listed or referenced.
- The key pair lives in M2's `Secret` wrappers and is MAC'd by M2's `request_signature`. It is
  never logged, printed, persisted or put in an exception; logging goes through the repo's
  redacting `configure_logging`. Failures are named by class and code, never by exchange text (a
  10004 `retMsg` echoes the signed string, key id included). Every output has the run's known
  values (key id, UID) masked and must pass the scrubber's leak check, or it is withheld.
- Before anything else: key info is read, and a key that may move funds (a withdrawal, transfer,
  wallet, fiat or card right, also re-cased, spaced or full-width: M13's judgement), a key with no
  IP allowlist of host addresses (none, a wildcard or a range) and a read-only key are refused
  (C-2.8).
- Every opening order is a Buy limit with a native `stopLoss` below its price (C-2.6); a Sell must
  be reduce-only. An amend may change the price only, of an opening order the run created, and
  never to or below that order's `stopLoss`; never the qty or the protection.
- The run cancels what it left open, by its own `orderLinkId`, and flattens what it opened. Each
  cleanup step runs whatever the one before it did, so a failed cancel never skips the flatten.
  It refuses to start unless the symbol is flat.
- USDT linear perpetuals only (allow-list plus `contractType`/`settleCoin` check), at most 250 USDT
  per order and 1000 USDT of position plus resting orders per run (the CLI may lower both only).
- Every REST call goes through the adapter's governor; only the flagged 10018 burst bypasses it.
  The burst runs only after a `completed` run, with no stop request, when a fresh REST read shows
  no position and no open order of the run, so the IP hold never locks out a cancel or a flatten.
  It is for an `orders` run only: a soak has no orders of its own to show the account flat, so
  `--capture-10018` with `soak` is refused when the config is built, before anything is sent.
- `orderLinkId`s follow 24 §8.3 (`cvd-...`); retries reuse them (C-2.10). A create whose outcome is
  unknown is looked up by its id, never re-sent under a new one. The run stops after a key, clock or
  rate refusal, three failed creates in a row, or three cycles in a row that a failed read ended.

## Outputs

`runs/<stamp>-<mode>/`: `summary.md` (the tables for #843), `summary.json` (with the stream's live
spans and down windows), `rest_calls.csv` (every request with its round trip), `orders.csv`
(cycles; our own `orderLinkId`s, needed by the retention probe), `ws_items.csv` (stream items with
stand-in ids), `rest_executions.csv` (each REST execution with a stand-in id, its type and time,
whether the stream was delivering then, and on which execution topic the stream delivered it; empty
when the backfill failed) and `metrics.prom`. A REST-only execution while the stream was delivering
is evidence against the stream as the source of truth; one inside a down window (before the first
connect, from a drop's last frame to the next connect, after the stop) is expected, since the
harness does not resync.

`staging/<stamp>-<mode>/bybit/<date>/`: the captures, scrubbed (credential fields masked; UIDs and
account, connection, message, cursor and order ids replaced by stable, shape-keeping stand-ins;
leak-checked, a leaking file is withheld): `rest/<endpoint>_<retCode>.json` (the first reply of each
shape; a read endpoint keeps one per kind of list, suffixed `_empty`, an order status such as `_New`,
or a position's `_flat` or `_open`; non-JSON replies as `.txt`), `ws/private_<mode>_<symbol>.jsonl`
(frames in receipt order), `manifest.json` entries in the corpus shape (plus the rate-limit headers
where present) and `README.e29-k01.md` lines (source, date, symbol, env, redaction). `runs/` and
`staging/` are git-ignored.

## Committing the fixtures and recording the results (owner)

1. Read every staged file. Run `node packages/fixtures/scripts/verify.mjs`,
   `python scripts/check_secrets_hygiene.py fixtures` and `gitleaks protect --staged --redact`.
2. Move the files you keep into `packages/fixtures/bybit/<date>/`, merge their entries into its
   `manifest.json` and the README lines into its README. The corpus loader reads plain `.jsonl`
   (the ticket says `.jsonl.gz`); a file above 1.5 MB goes through Git LFS.
3. Paste the `summary.md` tables on #843 and add the addendum to ADR-0006 §Validation, applying the
   ticket's decision rules: create p95 above 250 ms renegotiates budget #4 in
   `06-performance-and-load-standard.md`; any ordering violation gives E29-T05 a reorder buffer on
   `(ts_exec, seq)`; a non-zero REST-only count while the stream was delivering revises the
   reconciliation cadence in ADR-0006 before T06; a retCode the adapter maps differently from
   24 §8.6 gets an amendment ticket.
4. Land the findings note `docs/plan/spikes/E29-K01.md`, the ADR-0006 addendum, the reviewed
   fixtures and the `32-risk-register.md` update in one small docs and fixtures PR (conventional
   title, `Closes #843`), with the follow-ups in its record; then delete this branch (C-4.5).

## Deviations (this branch is never opened as a PR)

- Credentials (C-2.7, C-3.2): the demo pair comes from the environment and is held, in M2's
  `Secret` wrappers, inside this process rather than `services/api/secrets/`; the spike imports
  M2's signing helpers and M13's private key judgements. `lint-imports` does not check `spikes/`
  (its root packages are `candleviewer` and `cvdev`). This is acceptable only because the spike is
  never merged; the owner's acceptance belongs on #843.
- Audit (C-2.9): no audit record of each order action is written. `orders.csv` (every cycle's
  create, amend and cancel with their retCodes and round trips) and `rest_calls.csv` (every
  request) stand in for it; they are run outputs, not an append-only, hash-chained log.
- Test data: `tests/venue.py` builds the fake venue the tests run against (REST through
  `httpx.MockTransport` under the harness's own `GuardedTransport`, and a fake private stream). A
  recorded reply of the corpus is reused where it has one; the corpus holds none of an order, a
  position, an execution or the tickers, so those rows are built from the documented v5 fields, and
  no test proves a real payload shape. This run records them (AGENTS.md §6, rule 5).
- Size and gates: about 2,350 lines of source and 1,800 of tests against the C-4.8 preference of
  400 changed lines, in a new top-level `services/api/spikes/` directory, and the repo's Semgrep
  rules flag this tree. The PR gates would refuse it, which is why the branch stays PR-less and is
  deleted after the run.

Run the tests (no network: an in-memory venue stands in for the demo hosts) from `services/api/`:
`pytest spikes/oms_demo_path/tests --no-cov`.
