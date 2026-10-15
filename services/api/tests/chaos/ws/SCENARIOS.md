# E17-Q02 — client WS chaos catalogue (#410)

Suite: `services/api/tests/chaos/ws/` (marker `chaos` only, no `integration`: like the ingestion
suite it needs no docker, so the PR `py` lane runs it; no nightly job yet, see #410 DoD).
Run: `cd services/api && uv run pytest tests/chaos/ws -m chaos --no-cov`

**Harness.** `_server.Stack` serves the real `/ws` gateway (`make_ws_router`, `ConnectionRegistry`,
`SequencingHub`, `RevocationHub`, `GatewayHub`, the E17-Q01 wiring) on a real `uvicorn.Server`
with the production WS settings (`server.uvicorn_kwargs`), on an ephemeral 127.0.0.1 port. Grant
changes go through `ws_wiring.WsEvents`. Doubles: one `VirtualClock` (gateway monotonic + wall
clock and the session service), the real `SessionService` over `FakeSessionRepository`, the grant
store the principal loader reads, the snapshot source (#2195-#2197 not landed) and
`POST /auth/refresh`. The book is the recorded BTCUSDT corpus. `_client.Client` is a protocol
client independent of `apps/web` (§9.2 seeded full-jitter backoff, no reconnect after
1002/4400/4403; §9.3 private topics resubscribed first; refresh over REST before reconnecting when
the token is within 60 s of expiry or after `4401`; `pong`; records frames, closes and §7.1 gaps).

**Faults** are injected at `_proxy.Proxy` (toxiproxy-style, between client and gateway; REST goes
through it too), never by patching application code. Each is one scripted `inject()` step, logged
in `proxy.trace`: `DROP` aborts both legs of every live link (client sees 1006); `REFUSE` accepts
then aborts every new connection until `HEAL`; `PAUSE` stops reading server->client (TCP backs
up); `LATENCY` holds server->client bytes until `HEAL`; `HEAL` restores pass-through. Time moves
only by `clock.advance()` once the client is parked in a backoff sleep; every wait is an event
with a 5 s bound. Same seed, same backoff schedule and fault trace (scenario 6 pins the trace).

## Catalogue

| #   | Scenario (#410 AC)                                                  | This slice                                       | Blocker for the end-to-end run                                                                                                                                                                                                                           |
| --- | ------------------------------------------------------------------- | ------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Upstream kill (G3)                                                  | not run                                          | Nothing feeds the hub: `SequencingHub.publish` / `upstream_desync` / `upstream_reconnect` (`ws/sequencing.py:621,672,675`) have no production caller; book `SnapshotSource` #2196 (`ws_wiring.py:61`), book publisher E21-T01 #604, ingestion feed       |
| 2   | Slow consumer, 60 s (G4, P6; AC-12)                                 | not run; `Fault.PAUSE` is ready                  | #412 gateway wiring slice: the gateway still has the 1 024-frame queue that closes on full (`ws/gateway.py:106,352-359`); `ws/outbound.py` (8 MiB / 2 000 ladder) is not wired. `cv_ws_overflow_total` / `cv_ws_slow_consumer_closes_total` do not exist |
| 3   | Burst 5 000 msg/s (§8)                                              | not run                                          | #412 wiring (`ws/coalescing.py`, `ws/pacing.py` are not on the gateway path) and #571 (budget-#6 fan-out p95, `cv_ws_conflated_total`)                                                                                                                   |
| 4   | Restart, `shutdown_notice` (§9.4)                                   | not run                                          | #2560: uvicorn closes the sockets before `WsRuntime.stop()` sends the notice                                                                                                                                                                             |
| 5   | Token expiry during an outage (§4.3, §9.2)                          | **runs**: `test_s5_token_expiry_outage.py`       | —                                                                                                                                                                                                                                                        |
| 6   | Grant revoked mid-reconnect (E17-X02)                               | **runs**: `test_s6_revocation_reconnect_race.py` | — (SR-189 half: #2318 merged)                                                                                                                                                                                                                            |
| 7   | Kill switch reaches every socket <= 1 s under chaos (WS-E04, AC-26) | not run                                          | Gateway half is runnable now (`WsEvents.kill_switch_changed`, `ws_wiring.py:289` -> `GatewayHub.broadcast_system`, `ws/gateway.py:218`), but no producer calls it (`app.py:1050` only builds it): #956 E39-S03                                           |

**Scenario 5.** The token (real ADR-0020 TTL, 720 s) expires during a `REFUSE` window that also
blocks the REST refresh. The client backs off to the 30 s cap within the §9.2 jitter bands; its
refreshes inside the 60 s margin fail; the one that succeeds comes after the expiry and right
before the socket opens. The new socket authenticates the rotated session; no `err`, `bye` or
`4401`; every topic re-snapshots with no gap. `s5b`: a token expiring on a live socket costs
exactly one `bye token_expired` + `4401`, then refresh, then reconnect.

**Scenario 6.** Client holds `book`, `trades`, `orders` [A] and `positions` [A, B]; an A delta is
delivered (positive control). `REFUSE` + `DROP` (the server unregisters the socket), one refused
attempt, then A is withdrawn from the grant store and `grants_changed` runs, between two
attempts. After `HEAL` the resubscription answers `orders` with `account_scope_denied`, narrows
`positions` to [B], and the market topics re-snapshot. Publishing for A then reaches nobody
(`publish` returns 0), B and the book still flow, no received frame mentions A after the
withdrawal, no gap, one close (1006), exact proxy trace. `s6b` (SR-189) is AC-14's other half: the
loader double parks the new socket's `auth` between its principal read and its registration while
A is withdrawn. #2318 versions the permission snapshots, so the stale read loses: `orders` [A] is
refused with `account_scope_denied` and no A delta is delivered. Before #2318 the stale principal
won (the test was a strict xfail until then).

## Verification recorded

- **Mutation** (restored; no application change in this PR; re-run after the rebase onto #2318):
  sub-time account check removed (`ws/permissions.py` `_authorise`), producer-side account filter
  removed (`ws/sequencing.py` `in_scope`), registry serving a cached principal: scenario 6 fails
  on each. `s6b` also fails when the SR-189 re-check after `register`
  (`ConnectionRegistry.recheck`) is removed, and when `roles_changed` stops stamping
  `_changed_at`.
- **SR-189 flip:** #2318 merged (`549d9032`), and `s6b` reported `XPASS(strict)` on the rebased
  branch, as planned, so its `xfail` marker is removed and it runs as a plain test.
- **Flake budget:** 3 consecutive gate runs plus 20 more after the flip, all green (`4 passed`).
