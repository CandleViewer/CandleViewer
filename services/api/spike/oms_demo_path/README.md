# E29-K01 demo order-path spike harness (#843 A4): throwaway, never merged

Throwaway, on `spike/oms-demo-path`, **never merged** (#843: "Branch left unmerged and marked
throwaway"). It measures the exchange's **demo** order path and the private stream's parity
through the E08 adapter as production composes it. This slice builds and proves it **offline
only**: nothing here has dialled a venue host. The host runs come later, after A1 to A3 (#4479,
#895, #3180) merge, the owner imports the demo key and the coordinator calls the window. The
findings (`docs/plan/spikes/E29-K01.md`, the ADR-0006 §Validation addendum, the fixtures for
`packages/fixtures`) are a later PR, after the host runs.

No production code changes: the harness composes `candleviewer` as it is. Where it cannot do
something without a change, the gap is listed at the end with its workaround.

## Modes

`python -m spike.oms_demo_path <mode> --out <dir> [--offline | --demo ...]` (`--help` lists all).

| Mode        | What it does                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `cycles`    | `--cycles` (>=200 online) cycles over `--min-hours` (>=4 online), BTCUSDT only: a GTC limit order `--away-bps` from the reference price **with its native `stop_loss`** `--sl-bps` away on the protective side (C-2.6); an amend one tick further away; the drive, an amend to the touch, joining it (a maker that may fill in part) or crossing it by `--cross-bps` (a taker), alternating; the outcome (`filled`, `partial`, `unfilled`) read back over REST; a cancel of any remainder; a reduce-only market close of what filled; a REST check that the book is flat; the execution list for the cycle's window. Every step, transition and outcome is counted. |
| `soak`      | The private stream open for `--hours` (24 for the ticket), no orders: dials, `auth` grants and refusals, pongs and heartbeats, `down`s, gaps, the longest silence. The offset is re-measured every 10 minutes. Its idle phase is a block of its own (below).                                                                                                                                                                                                                                                                                                                                                                                                        |
| `shapes`    | The duplicate `orderLinkId` reply and the `10002` reply (below); `10018` is never provoked.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `retention` | On day 8 or later of a `cycles` run: its order history from `--since-ms` (its `started_at_ms`), by state and age (24 §8.3 rule 6).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `report`    | The tables of a run, from its scrubbed `summary.json` (`--run-dir`), and `adr-0006-addendum.md` in `--out`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |

The order size is `--qty-multiple` minimum quantities, 2 by default: BTCUSDT's minimum is one
quantity step, so a minimum-size order fills all or nothing and no partial fill could be seen.
`--max-qty-multiple` (default 2, ceiling 10) caps every opener and amend.

## Offline (the default, and the only mode this slice runs)

From `services/api` of a checkout, in the project venv:

```sh
python -m spike.oms_demo_path cycles --out <run> --cycles 8 --min-hours 0 --fill-wait-s 0.5 \
  --offline-drop-every 5 --offline-reorder-every 4
python -m spike.oms_demo_path report --out <run> --run-dir <run>
```

The tests (`spike/oms_demo_path/tests`) run under a session guard that fails any socket connect or
name lookup, loopback included.

`--offline` swaps only the two I/O edges the adapter exposes (`ExchangeBybitService`'s
`rest_transport` and `private_ws_connect`) and the stores:

- **The venue** (`offline.CorpusVenue`): an `httpx.MockTransport` handler and a scripted private
  socket. Every answer is a shape of the recorded corpus `packages/fixtures/bybit/2026-10-05/`
  (`rest/trading-*.json`, `rest/error_10002.json`, `rest/error_10018.json`,
  `rest/trading-error-110072.json`, `ws/private-*.jsonl`) with its values patched and its keys
  never (`patched` refuses a key the corpus row lacks; C-13.5). It keeps a one-tick book at the
  corpus's last trade: an order away from the touch rests, one joining it fills one step, one
  crossing it fills whole, a reduce-only market order closes the position. It answers `10002` to
  a request signed outside the receive window and `110072` to a reused `orderLinkId`.
  `--offline-drop-every N` withholds every Nth fill from the stream (REST only) and
  `--offline-reorder-every N` pushes every Nth fill's order update before its execution, so the
  parity and ordering counters are seen to count; the summary names what was injected.
- **The stack, in memory** (`offline.offline_stack`): cv-api's first boot (M2 over
  `InMemoryCredentialStore`, which enrols the KEK's check value) and the owner's key import (M2's
  own `candidate_keys`, a synthetic pasted pair). The KEK is a file of 32 random bytes made for
  the run in a temporary directory (0400) and removed with it.
- **The harness then composes exactly as online** (`compose.compose`): the KEK proof, the audit
  service with the real `AuditWriter` on a WAL of its own (its repository in memory: the fake
  audit sink), M2 over the same store, the real `BybitTradingPort` and `PrivateStreams`. The only
  offline seam inside M2 is `harden` (`assume_hardened`): SR-009's `harden_process` would change
  the test process's core dumps and ptrace for the whole session.

Pure logic is also tested against `FakeTradingPort` (`tests/test_safety.py`, `tests/test_cycles.py`).

## Safety (online; each check proven offline in `tests/`)

- `Settings.environment` must be `demo` (C-2.11); the adapter's demo entries must be the pinned
  allow-list (`https://api-demo.bybit.com`, `wss://stream-demo.bybit.com/v5/private`); the
  recording transport refuses any other host and the recording connector any other URL, before
  anything leaves. A proxy variable (`HTTP(S)_PROXY`, `ALL_PROXY`) refuses the run: httpx would
  mount the proxy ahead of the adapter's transport and bypass the seam.
- `--demo` needs `--i-understand-this-places-demo-orders`, `--account-id` (the
  `exchange_accounts.id`), `--key-ref` (the `api_keys.id`), the ticket's floors, and the typed
  confirmation `PLACE DEMO ORDERS`. The harness never holds a secret and needs no UID (the
  governor's bucket label is a constant; `AccountRef.uid` is never sent).
- An online run refuses to start with an open order or a position on the account.
- BTCUSDT only; no order above `--max-qty-multiple` minimums or off the quantity step.
- **Every position-opening order carries a native `stop_loss` on the protective side** (C-2.6);
  a close is a reduce-only market order with no stop (the venue refuses one), so it never opens;
  no amend removes or zeroes a stop. `GuardedPort` is the only trading surface: no batch,
  leverage, stop write, withdrawal or transfer (C-2.8; the adapter has no such endpoint).
- SIGINT, SIGTERM or an unhandled error ends the mode, then `cancel_all` (BTCUSDT, plain orders)
  and a reduce-only flatten run before M2 and audit stop; the summary's `shutdown` records the
  reason and what the flatten did. Three venue failures in a row end a `cycles` run the same way.

## Audit: a WAL of its own (decided, brief item 2)

The harness runs **beside** cv-api, with its own audit WAL; cv-api keeps running.

- The setting is `Settings.audit_wal_path` (`CV_AUDIT_WAL_PATH`). The stack's is
  `/var/lib/candleviewer/audit/audit.wal` on `cv-audit-data`; the harness's is
  `/var/lib/candleviewer/audit/spike/audit.wal` on `cv-spike-audit`, a volume of its own.
- Why a second writer is safe on its own WAL: `AuditWriter` owns one `AuditWal` per process (`audit/writer.py`); `AuditWal` takes no lock and "is not safe for concurrent writers" (`audit/wal.py`), so a shared file would truncate cv-api's in-flight frames, and nothing stops a second process on the same file. The chain is safe across processes: the repository's insert takes `pg_advisory_xact_lock(hashtext('audit_log'))` (`storage/repositories/audit_sqlalchemy.py`), `audit_chain()` takes it again and draws `id` under it (migrations `0003`, `0045`), and `record_id` is unique with `ON CONFLICT DO NOTHING`. `tests/integration/audit/test_two_writers_one_chain.py` (#913 Q12) proves two writers with their own WALs keep one chain.
- The harness refuses to start when its WAL directory is, or could be, the stack's
  (`safety.check_audit_dir`): the stack's path or directory, a directory or parent holding
  `lane/` or a WAL it did not create, or a mount of `cv-audit-data` (`/proc/self/mountinfo`).
  It marks its directory on first use.
- Why it cannot touch the order lane's audit lane (ADR-0037): the lane's files are
  `<dir of CV_AUDIT_WAL_PATH>/lane/` (`lane.lock`, its `seg-*.lane` segments, marker, note,
  `quarantine/`, `link.probe`; `audit/lane.py`, `audit/lane_journal.py`, `audit/lane_lock.py`)
  and its keys come from `CV_AUDIT_LANE_KEY_FILE` through `audit_lane_wiring.load_lane_keys`. The
  harness builds `build_audit_service(repository)` with **no lane key loader**, so `start()`
  loads no key, takes no `lane.lock`, builds and boots no lane (`audit/service.py`); its façade
  falls back to the writer. Its WAL directory is on its own volume, so even its `breakglass/`
  run lock and `lane_dir()` resolve away from the stack's; the container has no lane-key secret
  and no `cv-audit-data` mount.
- Fallback, not needed by the code: "cv-api stopped during the active run" would only be required
  if the harness could not have a directory of its own.
- Never delete `cv-spike-audit` before its WAL drained into Postgres: the summary's `audit`
  shows `buffer_depth` at exit; a WAL left undrained is replayed by the next harness start on
  the same volume (C-2.9).

## M2: it only opens what exists (brief item 1)

`compose.compose` builds `build_secrets_service(credentials, kcv, audit, auth_keys=keyring,
export_keys=None)` over the real stores, then `ExchangeBybitService(credentials=
bundle.exchange_borrower, ...).trading_port("demo")`. A second process starting M2:

- the **KEK** is loaded, never generated; `prove_kek_possession` runs first and requires the
  check value already enrolled (cv-api booted once on this KEK), since `start()` would enrol a
  missing one; `CV_KEK_PREV_HANDLE` set refuses the run (a rotation window);
- the **auth keyring** is never opened at start (only a KEK re-wrap counts it), so passing it is
  inert;
- the **export signing keys** would be opened, and possibly destroyed (retired seeds), generated
  or re-wrapped at start (`secrets/_export_custody.open_at_boot`): the harness **never passes
  them** (export is not its business; `secrets` health stays OK without them);
- no DEK is re-wrapped (only the admin `rewrap_deks` does); start writes one
  `security.kek_loaded` record; each signing writes `security.credential_borrowed` before the MAC;
- the harness refuses to go on unless `secrets` health is OK and its own gate is unlatched.

## Outputs, scrubbed before they are written (brief item 7)

`<out>/events.jsonl`, `summary.json`, `metrics.prom`, and fixture candidates in the corpus's
layout: `fixtures/rest_<call>_<code>_<n>.json` (reply bodies) and
`fixtures/private_<topic>.jsonl.gz`. The directory is 0700, every file 0600.

Every write passes `Scrubber.dumps` first (`outputs._emit`): a value under an identifier key
(`orderId`, `orderLinkId`, `execId`, push `id`, `conn_id`, `req_id`, cursors, account and key
ids) becomes a per-run token (`order#3`) from an in-memory map that is never written; headers,
signatures and `args` are dropped with their key; `auth` frames are dropped whole; every string is
cleaned of every registered value (the account and key ids given, each request's key id and
signature, every identifier any record has carried, the UID a push id leads with); the final text
is re-checked and refused (never written) if anything registered is left. The process's own log
(JSON on stderr) goes through the same scrubber. The fixture candidates are reviewed before
anything reaches `packages/fixtures`, in the findings PR.

## Measurements (brief item 5)

- **RTT per call class** (create, amend, cancel, cancel-all, execution list, reads): at the
  `rest_transport` seam, from send to the whole reply, on the monotonic clock. **Our overhead** is
  each port call's latency minus the RTTs of its exchanges: it holds M2's key read and the
  fsynced audit append before each signature, the governor and the parse (budget #4's <=50 ms).
- **The signing share**, on its own: the borrower `compose` hands `ExchangeBybitService` is
  wrapped (`measure.timed_borrower`, offline over the in-memory M2 the same way), and each M2
  `sign` call is timed: the key read, the fsynced audit append and the MAC. The wrapper passes
  the call through and hands back what M2 returns untouched; no signature or key id is read or
  recorded. `summary.signing_ms` holds n, p50, p95 and max per port call class (a REST signing
  under the call in flight), `sign_ws_auth` for the stream's `auth`, `sign_rest` for a port no
  guard wraps (the `10002` probe), and `overall`; `spike_signing_seconds` exports them.
- **Budget #4 judges itself** (`summary.budget4`, the report's first table): the three p95s
  (the create RTT at the seam, our overhead, end to end at the port) with the signing share
  beside our overhead, the rule as #843 agreed it, "p95 create RTT > 250 ms ⇒ budget #4
  renegotiated in `06` §5.2, never absorbed by our 50 ms", and the run's verdict: `within`,
  `renegotiate` or `no data` (no create timed). An offline run's verdict is never evidence
  (`evidence: false`).
- **`order_submit_seconds{transport="rest"}`** (the catalogue entry, `SUBMIT_BUCKETS`): each
  create's call-to-ack latency at the port, our overhead included, as the OMS will measure it
  (there is no UI click here). `bybit_clock_drift_ms` carries the offset (exchange minus host);
  the adapter's own series are re-exported; the rest are `spike_*`.
- **Clock offset**: the signed wallet read's envelope `time` against the midpoint of its exchange
  at the seam; the smallest of 5 round trips wins; re-measured every `--offset-every` cycles and
  every 10 minutes of a soak. It feeds the port (`clock_offset_ms`), so REST and `auth` are signed
  on the exchange's clock.
- **Private-stream latency**: `ts_ingest + offset - venue time` per kind (`execTime` for
  executions, `updatedTime` for orders and positions, the push's `creationTime` for all).
- **Parity**: execution ids on the stream against `GET /v5/execution/list` per cycle and over the
  whole run: `rest_only` (target zero) and `stream_only`; `execution.fast` separately.
- **Ordering** (23 §S5): an execution that arrives when an order event has already reported its
  fill.
- **Two ordering counts, kept apart** (`summary.private.ordering_counts`): "Execution before its
  order transition", broken, is a venue reorder,
  `venue_reorder_execution_after_its_order_transition` (the S5 count above; non-zero: E29-T05
  gains a reorder buffer). "Execution only via the backfill" is a dropped push,
  `dropped_push_execution_only_via_backfill` (parity's `rest_only`; non-zero: ADR-0006's
  reconciliation cadence is revised). The old keys stay.
- **The soak's idle phase** (`summary.soak.idle_phase`, a report section of its own): the window
  the stream was held, the orders sent (every order call the guard let through: none), dials,
  reconnects and outages, the ping gaps (between two pongs) and message gaps (between two
  frames) as n, p50, p95, max and the count over 7.5 s (`LONG_SILENCE_S`: past the 5 s ping by
  half the slack to the 10 s watchdog), and the executions only the backfill listed over the
  window: at its end the port's own `executions` reads `GET /v5/execution/list` from when the
  stream came up to now, on the exchange's clock, widened at both ends by the offset's own
  uncertainty (half its best round trip plus 1 ms), and counts those the stream never
  delivered. Zero missed executions: `met` (0), `not met` (any: that is the finding) or
  `no data` (the read failed).
- **The ADR-0006 addendum**: `report` writes `adr-0006-addendum.md` in `--out`, a template of
  §Validation's Spike S3 addendum filled with the run's numbers: the budget #4 verdict, its
  three p95s and the signing share; the two ordering counts under their own headings; the
  idle phase; the error shapes; the retention reading. `missing` marks what the run did not
  measure, and every section of an offline run says it is not evidence.

## Error shapes (brief item 4)

- **Duplicate `orderLinkId`**: the adapter keeps no record of ids it sent, so a second
  `place_order` with the same id reaches the venue: a `post_only` opener with its stop away from
  the touch, then the same create; the port raises `DuplicateClientIdError` and the recording
  transport keeps the venue's whole reply; then the order is cancelled.
- **`10002`**: a second port from the adapter's own factory
  (`trading_port("demo", clock_offset_ms=lambda: -60000)`) reads the wallet; the REST client
  re-signs once with the same offset, so two replies are kept and the read raises
  `ClockDriftError`. Nothing is created on that port and no stream is opened on it.
- **`10018`** is never provoked: the governor keeps the port under the venue's limits, a real one
  holds this process for >=600 s and the venue's IP limit covers cv-api's egress too. Any run
  that meets one records its whole reply (`summary.error_shapes`); a follow-up ticket captures one
  in a sanctioned window (cv-api stopped) or accepts the documented shape.

## Host runbook (the demo host of #3180)

The commands target #3180's proposed shape; every line marked **CHECK #3180** is to be confirmed
when it merges. Never read, print or copy a secret file, and never run `docker compose config`
(it prints the resolved environment, the DSN included).

**For the whole of every run:**

- No manual trading on that demo account during a run.
- cv-api stopped or untouched: it opens no private stream and runs no reconciler, so it never acts on the harness's orders.

**Before anything**: A1 to A3 merged; the stack up and healthy from the checkout at the pinned
`main` sha (`<stack>`); the owner imported the demo key through
`POST /exchange-accounts/{id}/keys`; you hold its `exchange_accounts.id` (`<ACCOUNT_ID>`) and
`api_keys.id` (`<KEY_ID>`); the coordinator called the window; the bench runner is idle
(`systemctl status 'actions.runner.*'` shows no job, and the [BENCH-BUSY] thread is quiet: a
running bench leg finishes first, none starts during the window; RTT beside a bench leg is not
evidence).

1. **The spike checkout** at `<spike>` on `spike/oms-demo-path`, rebased onto the pinned sha if
   it differs from this branch's base, with its offline gates re-run (README "Offline"); the
   image's `candleviewer` must be the one the harness was built against.
2. **The image**, built from the stack's checkout (**CHECK #3180**: its overlay's name, and the
   image name it gives `api`; compose's default is `cv-demo-api`):

   ```sh
   cd <stack>/infra/compose
   docker compose -p cv-demo -f docker-compose.yml -f docker-compose.vps.yml \
     -f <3180 overlay> --profile core build api
   ```

3. **The output directory**, owned by the container's uid:
   `sudo install -d -o 10001 -g 10001 -m 0700 /srv/cv-spike/out`.
4. **The command prefix** (from `<stack>/infra/compose`, so compose reads the host's `.env`:
   `CV_PG_DSN`, `CV_KEK_FILE`, `CV_KEK_VERSION`, **CHECK #3180**):

   ```sh
   export CV_SPIKE_SRC=<spike>/services/api/spike CV_SPIKE_OUT=/srv/cv-spike/out
   SPIKE="docker compose -p cv-demo -f docker-compose.yml -f docker-compose.vps.yml \
     -f <3180 overlay> -f <spike>/services/api/spike/oms_demo_path/docker-compose.spike.yml \
     --profile spike run --rm --no-deps spike"
   IDS="--demo --i-understand-this-places-demo-orders --account-id <ACCOUNT_ID> --key-ref <KEY_ID>"
   ```

   The container: the `api` image, `python -m spike.oms_demo_path` with `/app/spike` bind-mounted
   read-only and `PYTHONPATH=/app`, uid 10001, read-only root, the `cv_kek` secret at
   `/run/secrets/cv_kek` (the host file `CV_KEK_FILE`, 10001:10001 0400), the runtime DSN, the
   audit WAL on `cv-spike-audit`, no lane-key secret, no `cv-audit-data`, no static IP.

5. **Run each mode in a terminal you keep** (tmux), since each asks for the typed confirmation:

   ```sh
   $SPIKE shapes $IDS --out /var/lib/candleviewer/spike-out/shapes-<yyyymmdd>
   $SPIKE cycles $IDS --cycles 200 --min-hours 4 --out /var/lib/candleviewer/spike-out/cycles-<yyyymmdd>
   $SPIKE soak $IDS --hours 24 --out /var/lib/candleviewer/spike-out/soak-<yyyymmdd>
   # on day 8 or later of the cycles run (its summary's started_at_ms):
   $SPIKE retention $IDS --since-ms <started_at_ms> --out /var/lib/candleviewer/spike-out/retention-<yyyymmdd>
   ```

   Follow a run with `tail -f /srv/cv-spike/out/<run>/events.jsonl` (scrubbed).

6. **Stop**: Ctrl-C in its terminal (SIGINT), or `docker kill --signal SIGTERM <container>`: the
   harness cancels every BTCUSDT order, closes any position reduce-only and writes its summary
   (`stop_grace_period` 60 s). If `summary.json` shows `shutdown.flat: false`, or there is no
   summary, close the position in the venue's web UI; its native stop protects it meanwhile; the
   next run's preflight refuses until the account is flat.
7. **Report**: the tables on stdout and `adr-0006-addendum.md` (the §Validation template, filled)
   in `--out`, then copy `/srv/cv-spike/out/<run>` off the host for the findings PR (the fixture
   candidates are reviewed there first):

   ```sh
   $SPIKE report --out /var/lib/candleviewer/spike-out/<run> \
     --run-dir /var/lib/candleviewer/spike-out/<run>
   ```

8. **Keep `cv-spike-audit`** until each summary's `audit.buffer_depth` is 0.

## Production gaps found (none changed here)

| Gap                                                                                               | Workaround here / follow-up                                                                                                                                                                                                                                                                     |
| ------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| The port has no ticker, instrument or server-time read (`trading.ENDPOINTS`)                      | Reference price and filters through the adapter's own unsigned public client on the live public host (`public_rest_client`, as production reads demo's market data), two `GET` paths only; the offset from the signed wallet read's envelope. Follow-up only if the OMS needs a demo-host price |
| `compose run api` inherits the stack's audit volume, WAL path, lane-key secret and static IP      | A dedicated `spike` service with volumes of its own (`docker-compose.spike.yml`); the harness refuses the stack's WAL directory                                                                                                                                                                 |
| M2's start opens the export signing keys and may destroy, generate or re-wrap them                | `export_keys=None`; `prove_kek_possession` first; no previous KEK handle                                                                                                                                                                                                                        |
| `SecretsService.start(ctx)` is typed `AppContext`                                                 | `cast` of a namespace holding `settings` and the gate (the M2 tests' pattern)                                                                                                                                                                                                                   |
| The service's factory gives the streams and the port no `sleep`/`now_us` seam                     | Virtual-time tests build `BybitTradingPort` and `PrivateStreams` directly; the CLI runs in real time                                                                                                                                                                                            |
| `order_submit_seconds` is planned (E29) and there is no private-stream latency name               | Registered from its catalogue entry here; `spike_*` names; a catalogue follow-up if Grafana panels want them                                                                                                                                                                                    |
| The port surfaces a duplicate's code and text only                                                | The recording transport keeps the whole reply                                                                                                                                                                                                                                                   |
| A `10018` cannot be provoked under the governor                                                   | Follow-up: capture in a sanctioned window, or accept the documented shape                                                                                                                                                                                                                       |
| No reserve for stop and cancel calls yet (E34-T02)                                                | Low pacing (one cycle every 72 s at 200 over 4 h)                                                                                                                                                                                                                                               |
| A flatten needs M2 and audit (every borrow is audited first, fail closed)                         | The native stop is the backstop; the runbook's step 6                                                                                                                                                                                                                                           |
| httpx mounts an environment proxy ahead of the adapter's transport                                | The harness refuses a proxy variable (the production adapter has the same exposure; worth a note to E08)                                                                                                                                                                                        |
| `audit.lane` is a façade over the writer, not `LaneNotWired`, once a writer runs with no lane key | Tests assert `lane_parts()` has no lane instead                                                                                                                                                                                                                                                 |
| `FakeTradingPort.seed_order` keeps a stale open row when it seeds a terminal state                | The fake-backed cycle test drives partial fills only; full fills run through the corpus venue                                                                                                                                                                                                   |
