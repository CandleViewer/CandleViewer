# E17-Q02 — client WS chaos catalogue (#410)

Suite: `services/api/tests/chaos/ws/` (marker `chaos` only, no `integration`: like the ingestion
suite it needs no docker, so the PR `py` lane runs it; no nightly job yet, see #410 DoD).
Run: `cd services/api && uv run pytest tests/chaos/ws -m chaos --no-cov`

**Harness.** `_server.Stack` serves the real `/ws` gateway (`make_ws_router`, `ConnectionRegistry`,
`SequencingHub`, `RevocationHub`, `GatewayHub`, the E17-Q01 wiring) on a real `PlannedShutdownServer`
with the production WS settings (`server.uvicorn_kwargs`), on an ephemeral 127.0.0.1 port. Grant
changes go through `ws_wiring.WsEvents`. Doubles: one `VirtualClock` (gateway monotonic + wall
clock and the session service), the real `SessionService` over `FakeSessionRepository`, the grant
store the principal loader reads, the snapshot source (a corpus-fed fake; #2195 and #2197 not landed) and
`POST /auth/refresh`. The book is the recorded BTCUSDT corpus. `_client.Client` is a protocol
client independent of `apps/web` (§9.2 seeded full-jitter backoff, no reconnect after
1002/4400/4403; §9.3 private topics resubscribed first; refresh over REST before reconnecting when
the token is within 60 s of expiry or after `4401`; `pong`; records frames, closes and §7.1 gaps). `Stack.restart()` boots a second server process on a new
port behind the same proxy (the stores survive); `Stack.lane()` is a second proxy, so a fault can
hit one client. The §9.4 grace is slept on the virtual clock via `GatewayHub.shutdown(sleep=...)`,
a seam `WsRuntime.stop()` does not forward (a harness subclass).

**Faults** are injected at `_proxy.Proxy` (toxiproxy-style, between client and gateway; REST goes
through it too), never by patching application code. Each is one scripted `inject()` step, logged
in `proxy.trace`: `DROP` aborts both legs of every live link (client sees 1006); `REFUSE` accepts
then aborts every new connection until `HEAL`; `PAUSE` stops reading server->client (TCP backs
up); `LATENCY` holds server->client bytes until `HEAL`; `HEAL` restores pass-through. Time moves
only by `clock.advance()` once the client is parked in a backoff sleep; every wait is an event
with a 5 s bound. Same seed, same backoff schedule and fault trace (scenario 6 pins the trace).
A reset crosses the proxy, `PAUSE` also holds the chunk being read, no server behind it = reset (`down`).

## Catalogue

| #   | Scenario (#410 AC)                                                  | This slice                                                    | Blocker for the end-to-end run                                                                                                                                                                                                                           |
| --- | ------------------------------------------------------------------- | ------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Upstream kill (G3)                                                  | not run                                                       | Nothing feeds the hub: `SequencingHub.publish` / `upstream_desync` / `upstream_reconnect` (`ws/sequencing.py:621,672,675`) have no production caller; book publisher E21-T01 #604, ingestion feed                                                        |
| 2   | Slow consumer, 60 s (G4, P6; AC-12)                                 | not run; `Fault.PAUSE` is ready                               | A flag-on server in `_server.py`: the ladder is wired behind `CV_WS_BACKPRESSURE_ENABLED` (#412, off by default); its steps count in `cv_ws_overflow_total{reason}`; the close, in `cv_ws_closes_total{reason}` (not `cv_ws_slow_consumer_closes_total`) |
| 3   | Burst 5 000 msg/s (§8)                                              | not run                                                       | A flag-on server in `_server.py` (coalescing and pacing are wired behind `CV_WS_BACKPRESSURE_ENABLED`, #412) and #571's `cv_ws_conflated_total`                                                                                                          |
| 4   | Restart, `shutdown_notice` (§9.4)                                   | **runs**: `test_s4_restart_shutdown_notice.py`                | —                                                                                                                                                                                                                                                        |
| 5   | Token expiry during an outage (§4.3, §9.2)                          | **runs**: `test_s5_token_expiry_outage.py`                    | —                                                                                                                                                                                                                                                        |
| 6   | Grant revoked mid-reconnect (E17-X02)                               | **runs**: `test_s6_revocation_reconnect_race.py`              | — (SR-189 half: #2318 merged)                                                                                                                                                                                                                            |
| 7   | Kill switch reaches every socket <= 1 s under chaos (WS-E04, AC-26) | **runs** (gateway half): `test_s7_kill_switch_propagation.py` | Producer half: nothing calls `WsEvents.kill_switch_changed` (`app.py:1050` only builds it): #956 E39-S03                                                                                                                                                 |

**Scenario 4.** Three workspaces are connected and `server.should_exit` is set (what SIGTERM sets):
`PlannedShutdownServer` runs `WsRuntime.stop()` before uvicorn's own shutdown. Each client gets the
schema-valid `shutdown_notice` (`deploy`, `closing_in_ms` 5000, `expected_downtime_ms` 20000) and
turns order entry off (C12, modelled in the client). Data still flows 4 s into the (virtual) grace;
only its end brings `bye shutdown` (`retry_after_ms` 20000, the last frame) and `1001`, never `1006`
or a bare `1012` (`cv_ws_closes_total{reason="shutdown"}` +3). The clients back off (§9.2 attempt 1,
distinct jitter), are reset by the dead port, back off again; a second process starts on a new
port. Each re-authenticates (no refresh), resubscribes private topics first and re-snapshots every
topic, no gap, no `err`; order entry returns with the new `auth_ok`.

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

**Scenario 7 (gateway half).** `WsEvents.kill_switch_changed` is fired directly: no producer yet
(#956 E39-S03). The 1 s bound is wall time (`loop.time()`: delivery is socket I/O, which no virtual
clock measures; 0.3 to 10 ms measured); no `cv_ws_*` series covers the broadcast, so none is
asserted. `s7`: four sockets, one behind a `PAUSE`d lane. The three healthy ones get the
schema-valid `system` `kill_switch` frame in under 1 s, ahead of their `permission_change` (§12.5),
and turn order entry off. The paused one gets nothing and is not evicted; after `HEAL` it gets its
stuck delta, then the frame, no gap. `s7b`: a client cut off by `DROP` redials and its `auth` parks
in the principal load while the switch flips. The healthy sockets get the frame in under 1 s; the
broadcast skips the parked socket, whose `auth_ok.kill_switch` (§4.3; `welcome` has none) is live.

## Verification recorded

- **Mutation** (restored; no application change in this PR; re-run after the rebase onto #2318):
  sub-time account check removed (`ws/permissions.py` `_authorise`), producer-side account filter
  removed (`ws/sequencing.py` `in_scope`), registry serving a cached principal: scenario 6 fails
  on each. `s6b` also fails when the SR-189 re-check after `register`
  (`ConnectionRegistry.recheck`) is removed, and when `roles_changed` stops stamping
  `_changed_at`. Scenario 4 fails on: no notice pushed, the grace `sleep` removed, no planned
  shutdown before uvicorn's (pre-#2560: bare `1012`), `shutdown` mapped to `1013`, `bye` without
  `retry_after_ms`. Scenario 7: `broadcast_system` skipping a socket, re-evaluation before the
  `system` frame, `auth_ok.kill_switch` always off (or read before the `auth` load: `s7b` only), a
  1.2 s blocking call ahead of the fan-out.
- **SR-189 flip:** #2318 merged (`549d9032`), and `s6b` reported `XPASS(strict)` on the rebased
  branch, as planned, so its `xfail` marker is removed and it runs as a plain test.
- **Flake budget:** 3 consecutive gate runs plus 20 more after the flip, all green (`7 passed`).
