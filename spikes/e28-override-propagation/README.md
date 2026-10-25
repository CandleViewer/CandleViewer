# E28-K01 propagation prototype — THROWAWAY

**Throwaway spike code (E28-K01, #968). Not promoted, not production, not a test.** It exists so the numbers in
`docs/plan/spikes/E28-K01.md` and ADR-0040 can be reproduced. Nothing in `services/api` imports it, no CI lane runs
it, and no test collector picks it up (no `test_*` file; outside every `testpaths`). Delete it, do not extend it: the
production design is ADR-0040, built by E28-S01 (#971) and E28-S05 (#1144).

## What it measures

End to end, per change: a profile write commits → `ProfilesChanged` is published on the bus → the client learns of it
(a WebSocket frame, or a poll) → the client re-fetches `GET /exchange-accounts/{accountId}/profiles` → the client asks
for a new preview. The sample is the time from the commit to the preview's answer, split into its parts.

| Transport                 | How the client learns                                                                     |
| ------------------------- | ----------------------------------------------------------------------------------------- |
| `system_notice`           | `system` `account_notice`, `reason: profiles.changed`, sent at once (as `push_system` is) |
| `system_notice_1s_window` | the same frame, held to the 1 000 ms default window 23 §6.2 lists for `system`            |
| `trade_groups_100ms`      | an illustrative `profiles_changed` member on `trade_groups`, in its 100 ms window         |
| `rest_poll_1s`            | no frame: the client re-fetches every 1 000 ms                                            |
| `preview_only`            | the stand-in preview alone, 5 and 20 legs, against SCR-061's 300 ms                       |

## Real and stand-in parts

- **Real** (`main` at the base commit): the bus (`candleviewer.bus.Bus`, a `NEVER_DROP` subscription on
  `demo.profiles.*.changed`), `system_view` (the per-socket account cut of an `account_notice`), the profile list route
  (`make_profiles_router`) over the real `ProfilesRepository` and `profile_document`, uvicorn, and a loopback WebSocket.
- **Stand-in**: the profile write (#906's `PUT`), the `ProfilesChanged` event (#906 slice D3a), the gateway (a minimal
  WebSocket endpoint with a fixed Manager principal in place of `hello`/`auth`), the store (in memory, scoped as SQL
  scopes it: no Postgres), and the preview (a stand-in route running a `Decimal` copy of 24 §9.3's sizing; the real
  `POST /trade-groups/preview` is not on `main`).

## Topology

One process on the developer laptop (WSL2): a server thread (its own event loop: uvicorn HTTP and WebSocket on
`127.0.0.1`, an ephemeral port, plus the bus and the bridge) and a client thread (its own loop: `httpx` and
`websockets`). Loopback TCP only; nothing listens beyond `127.0.0.1`; no exchange, no network, no secrets. This is the
Deviation the spike records: the ticket asked for the R3 staging topology over Tailscale, which is not available.

## Run

From the repository root, with the backend's own environment (`cd services/api && uv sync --frozen` once):

```sh
for t in system_notice trade_groups_100ms preview_only system_notice_1s_window rest_poll_1s; do
  timeout 300 services/api/.venv/bin/python spikes/e28-override-propagation/measure.py --transport "$t"
done
```

Options: `--iterations` (default 200), `--legs` (default 5), `--seed` (default 968: the phase of each change against
the windows), `--out` (default `results.json` here; each run replaces its own transport's entry). Every run also
prints `decision_table_check`, which compares ADR-0040's classification with the live `AccountProfile` fields.

`results.json` holds every sample (milliseconds), the summary (nearest-rank p50, p95, p99, max), the environment
and a scope check: a change on an account outside the Manager's grants must produce no frame, and its `GET` must
answer `404`.

One `rest_poll_1s` sample has a negative `trigger_ms` (−1.096 ms). `Client.poll` stamps the trigger when it starts the
`GET`, not when the answer is sent (the field's comment says otherwise): that `GET` left just before the commit and
the server read the new version after it. It is the poll model's clock read order and changes no quoted number.

**Task ownership (after the samples).** The five background tasks (the WebSocket writer, the bridge, the server, the
receiver and the poller) now start through `candleviewer.observability.spawn`, the repo's owned-task helper (the Semgrep
rule `cv-bare-create-task`), instead of a bare `asyncio.create_task`. `results.json` was recorded before that change.
`spawn` creates the same task under a copied context, so the timing path is unchanged. A re-run after the change (200
iterations, seed 968, 5 legs, 25 Oct 01:4xZ, not committed) gave `system_notice` p50 3.8 / p95 5.6 / max 15.6 ms and
`trade_groups_100ms` p50 53.9 / p95 98.7 / max 104.9 ms. That is the same shape on a busier host, and both are far
inside 2 s.
