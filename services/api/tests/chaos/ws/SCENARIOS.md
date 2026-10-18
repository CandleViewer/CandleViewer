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

**Flag on.** `_server.flag_on()` (fixture `stack_on`, in `conftest.py`) serves the same router with
E17-T03's `CV_WS_BACKPRESSURE_ENABLED` on: the default `BackpressureConfig` (8 MiB / 2 000 frames,
the §8.4 ladder, pacing, classification and the RTT probe). Its listening socket has a fixed 32 KiB
`SO_SNDBUF` (64 KiB once the kernel doubles it), which every accepted socket inherits, and each of
its lanes fixes its upstream `SO_RCVBUF` at 128 KiB (`LANE_RCVBUF`, `Proxy.rcvbuf`). So a stopped
reader's backlog reaches the gateway's budget once well under 1 MB is in flight, however bursty the
writes, not after the megabytes loopback autotuning holds. The lane buffer has a floor: set after
connect, as `Proxy` sets it, a receiver of 28 KiB or less that stopped reading resumes only on the
sender's next zero-window probe, 0.5 s to seconds after `HEAL` (about 32 KiB on Linux 6.6; set
before connect there is none), and kernels that advertise about half the buffer as window need
twice that. 128 KiB clears it with room, and the `recovered` wait names both
sizes if it ever stalls. uvicorn's transport keepalive (a 15 s ping, a 45 s pong timeout, then
`1011`) is off there: it is timed on the loop's wall clock and the scenarios on the virtual one, so
a slow run (coverage) would close a paused client mid-scenario. The §9.1 application heartbeat
stays, on the virtual clock. Production keeps both: a reader stalled for 60 real seconds meets that
`1011`, which this harness leaves out. `trades_step` publishes the recorded BTCUSDT tape (production
parser) as §14.2 batches, replayed in rounds with unique ids. Client opt-ins, set before `start()`:
the §9.1 client `ping` (`heartbeat_s`), no permessage-deflate (`deflate`), and `on_data`, which
takes the data frames of a stream too large to keep. The flag-off scenarios use none of these.

## Catalogue

| #   | Scenario (#410 AC)                                                  | This slice                                                    | Blocker for the end-to-end run                                                                                                                                                                                                                           |
| --- | ------------------------------------------------------------------- | ------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Upstream kill (G3)                                                  | not run                                                       | Nothing feeds the hub: `SequencingHub.publish` / `upstream_desync` / `upstream_reconnect` (`ws/sequencing.py:621,672,675`) have no production caller; book publisher E21-T01 #604, ingestion feed                                                        |
| 2   | Slow consumer, 60 s (G4, P6; AC-12)                                 | **runs**: `test_s2_slow_consumer.py`                          | — (flag on: `_server.flag_on`. The sleeper holds `book.BTCUSDT.50` and the tape; no bar builder is wired into this harness for `bars` or `footprint`. Step 3's redrop needs a snapshot near the budget, and none is: `test_pipeline_ladder.py` pins it.) |
| 3   | Burst 5 000 msg/s (§8)                                              | not run                                                       | #571's `cv_ws_conflated_total`; the flag-on stack it needs exists (`_server.flag_on`)                                                                                                                                                                    |
| 4   | Restart, `shutdown_notice` (§9.4)                                   | **runs**: `test_s4_restart_shutdown_notice.py`                | —                                                                                                                                                                                                                                                        |
| 5   | Token expiry during an outage (§4.3, §9.2)                          | **runs**: `test_s5_token_expiry_outage.py`                    | —                                                                                                                                                                                                                                                        |
| 6   | Grant revoked mid-reconnect (E17-X02)                               | **runs**: `test_s6_revocation_reconnect_race.py`              | — (SR-189 half: #2318 merged)                                                                                                                                                                                                                            |
| 7   | Kill switch reaches every socket <= 1 s under chaos (WS-E04, AC-26) | **runs** (gateway half): `test_s7_kill_switch_propagation.py` | Producer half: nothing calls `WsEvents.kill_switch_changed` (`app.py:1050` only builds it): #956 E39-S03                                                                                                                                                 |

**Scenario 2** (C-13.6 #11, backpressure: a slow WS client). Flag on. The sleeper holds the
reference workspace's feedable topics, `book.BTCUSDT.50` and `trades.BTCUSDT` (no bar builder is
wired into the harness for its 1 m `bars` and 5 m `footprint` panes), behind a `PAUSE`d lane for 60
s of virtual time. Its §9.1 pings keep the socket open; with none, the writer's first turn after
`HEAL` finds 60 s without inbound traffic and closes it `heartbeat_timeout`, since while the writer
is parked nothing checks the watchdog (#3100). It offers no deflate. Every 125 ms the hub publishes
the recorded book and, after a quiet first 2 s, 250 prints of the tape (the tape starts at 2.125 s;
2 000 prints/s, ~235 KiB/s: inside §16.3's 350 KiB/s; at K01's measured 154 KiB/s the budget would
bind only at the pause's end). The quiet start keeps the sleeper's writer running through its
classification at 2 s. The RTT probe it never answered makes it `saturated` there (§8.6, C6), so its
windows (x4) hold pending bytes from then on, on every run. Pass-through spies on
`Backpressure.check` and `drain`, and a count of `OutboundQueue.push` calls, record every budget
check of the sleeper (ruling D8). On return, queued plus pending window bytes are within 8 MiB and
the frames within 2 000, unless the check closed. At most one frame is pushed between two checks
(the bounded overshoot), the counters equal the lanes and windows recounted, and the windows'
pending bytes are in it. Step 1 fires once while asleep, the class `saturated`: both topics' frames
and windows go, both marked `backpressure`. No snapshot is queued while asleep (the writer, parked
in its send, runs no drain); after `HEAL`, one per drain, and the streams resume with no gap. No
step 3: what is left can always be dropped (`cv_ws_overflow_total` `drop` +2, `resnapshot` +2; no
close). Two healthy clients on the same topics get every update in the tick that published it: no
class the sleeper degraded and no frame held, 0 ms added on the virtual clock, where the Gherkin
allows 10 % on the p95. They see no gap, every print, and the same frames, byte for byte, as a run
without the sleeper. Loop times are printed, not asserted: the proxy hop stalls ~40 ms once a
classification interval in both runs. The test prints the D8 record (the tracemalloc peak over the
pause, the accounted peak, their ratio); the PR keeps one run's values. `s2b`: the sleeper also
holds account A's `orders`, updated 128 times a second, frames §8.4 never drops. Step 1 sheds the
market topics; then the orders take the queue past 2 000 frames with nothing left to drop, so it
closes `slow_consumer` (`close_budget` +1, `cv_ws_closes_total{reason="slow_consumer"}` +1), both
lanes freed at once and the queued frames unsent. Step 3's `bye` carries §8.4's literals (`4429`,
`retry_after_ms` 3000, the fixed message). As built, its `most_expensive_topics` are counted at the
closing check, after step 1 shed the market topics, so the list is empty; #3365 ranks every topic at
the episode's first over-budget check and freezes that ranking, and the assertion flips with its PR.
The lane heals in the close's own synchronous turn (the feed's `until` hook, no await between),
inside the close's 2 s flush; the client backs off (§9.2 attempt 1) and re-snapshots every topic,
`orders` first (§9.3), no gap.

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
- **Scenario 2 mutation** (in memory, no file written): with tracemalloc on and off, it fails on
  each of 16 mutants of `ws/outbound.py`, `ws/pacing.py`, `ws/pipeline.py` and `ws/gateway.py`: the
  budget never binding; queued bytes miscounted; window bytes never coming down; the windows left
  out of the check; no check after a control frame; step 1 dropping one topic or marking none; step
  2 run inside the push, all at once, or never; a close after a drop that cleared the overflow; a
  `bye` without its hint; uncounted steps or closes; a slow-consumer close that keeps its queued
  orders; one classification shared by every connection. The kill of the windows left out of the
  check holds when the 8 MiB crossing lands with trades batches pending, as it did in every
  configuration measured (lane buffers from 24 to 128 KiB, traced, untraced and under coverage);
  `test_backpressure_counts_pending_state_against_the_budget` (`test_outbound.py`) pins that
  property regardless. Two paths lie outside this scenario and the unit suite pins them: the 50 %
  drain gate (the woken sleeper's queue holds only control frames;
  `test_backpressure_drain_waits_until_the_queue_is_below_half`) and the redrop close
  (`test_three_redrops_close_with_close_redrop`).
- **SR-189 flip:** #2318 merged (`549d9032`), and `s6b` reported `XPASS(strict)` on the rebased
  branch, as planned, so its `xfail` marker is removed and it runs as a plain test.
- **Flake budget:** 3 consecutive gate runs plus 20 more after the flip, all green (`7 passed`).
  With scenario 2: three runs in three seeded shuffled orders and one with `-W error` (`9 passed`),
  and two runs of `s2` and `s2b` under the `py` lane's flags (`--cov`) with the 128 KiB lane buffer
  (three more at the earlier 32 KiB lane buffer), all green.
