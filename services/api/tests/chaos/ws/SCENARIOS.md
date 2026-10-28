# E17-Q02 — client WS chaos catalogue (#410)

Suite: `services/api/tests/chaos/ws/` (marker `chaos` only, no `integration`: like the ingestion
suite it needs no docker, so the PR `py` lane runs it, and `chaos-ws-nightly.yml` runs it again
every night, with any `harness`-marked heavy run that lane deselects; see #410 DoD).
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
with a 5 s bound, except scenario 2's wait for the sleeper's snapshots, which its pause bounds
(below). Same seed, same backoff schedule and fault trace (scenario 6 pins the trace).
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
twice that. 128 KiB clears it with room, and scenario 2's waits name both sizes if one ever
stalls; one hosted night (#4264) still saw the lane resnapshot about 1.4 to 2.9 s after `HEAL`, the
cause not confirmed, so S2's D8 line prints that time (`the lane resnapshotted ... s (wall) after
HEAL`): 0.5 s or more reads as the probe regime above (compare the lane's own baseline under
`--cov`). uvicorn's transport keepalive (a 15 s ping, a 45 s pong timeout, then `1011`) is off there: it is timed on the loop's wall clock and the scenarios on the virtual one, so
a slow run (coverage) would close a paused client mid-scenario. The §9.1 application heartbeat
stays, on the virtual clock. Production keeps both: a reader stalled for 60 real seconds meets that
`1011`, which this harness leaves out. The server's per-connection frame budget (#2176) is kept
there but refilled on the virtual clock (`_server._frames_on`), like the gateway's own inbound
limiter; the flag-off stack keeps the loop clock, as production does.
`flag_on(nodelay=True)` (scenario 3's wall-clock tests) also sets `TCP_NODELAY` on the
listening socket, which every accepted socket inherits: asyncio sets it only on the sockets it
makes by host and port, so otherwise an update can wait about 40 ms on Nagle and the client's
delayed ACK (the stall scenario 1 prints); the default is unchanged, so the other users of
`Stack` are untouched. `trades_step` publishes the recorded BTCUSDT tape (production
parser) as §14.2 batches, replayed in rounds with unique ids. Client opt-ins, set before `start()`:
the §9.1 client `ping` (`heartbeat_s`), no permessage-deflate (`deflate`), and `on_data`, which
takes the data frames of a stream too large to keep. The flag-off scenarios use none of these.
`_book.Replica` (and `replay`) rebuilds a structured book channel from the frames a `Client` kept: a
`snap` replaces it, a `d` patches it, a gap discards until the next `snap` (§7.1). `_book.BookTap` is
a `Client.on_data` for a channel too long to keep (a `Replica` and the disclosure of each `d`), and
`_book.Loop` a book publisher for a stream of any length (Scenario 3).

## Catalogue

| #   | Scenario (#410 AC)                                                  | This slice                                                    | Blocker for the end-to-end run                                                                                                                                                                                                                           |
| --- | ------------------------------------------------------------------- | ------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Upstream kill (G3)                                                  | **runs** (gateway half): `test_s1_upstream_kill.py`           | Producer half: nothing calls `SequencingHub.upstream_desync` or `upstream_reconnect` nor publishes a book `d`: the book publisher E21-T01 #604. End to end then runs over the E08 Rig's recorded upstream (recorded here, not filed)                     |
| 2   | Slow consumer, 60 s (G4, P6; AC-12)                                 | **runs**: `test_s2_slow_consumer.py`                          | — (flag on: `_server.flag_on`. The sleeper holds `book.BTCUSDT.50` and the tape; no bar builder is wired into this harness for `bars` or `footprint`. Step 3's redrop needs a snapshot near the budget, and none is: `test_pipeline_ladder.py` pins it.) |
| 3   | Burst 5 000 msg/s (§8)                                              | **runs**: `test_s3_burst.py`                                  | — (flag on: `_server.flag_on`. The gateway has no book publisher, #604: `_book.Loop` plays it. Budget #6 in wall time runs nightly only (`harness`); its negative control in the PR lane too)                                                            |
| 4   | Restart, `shutdown_notice` (§9.4)                                   | **runs**: `test_s4_restart_shutdown_notice.py`                | —                                                                                                                                                                                                                                                        |
| 5   | Token expiry during an outage (§4.3, §9.2)                          | **runs**: `test_s5_token_expiry_outage.py`                    | —                                                                                                                                                                                                                                                        |
| 6   | Grant revoked mid-reconnect (E17-X02)                               | **runs**: `test_s6_revocation_reconnect_race.py`              | — (SR-189 half: #2318 merged)                                                                                                                                                                                                                            |
| 7   | Kill switch reaches every socket <= 1 s under chaos (WS-E04, AC-26) | **runs** (gateway half): `test_s7_kill_switch_propagation.py` | Producer half: nothing calls `WsEvents.kill_switch_changed` (`app.py:1050` only builds it): #956 E39-S03                                                                                                                                                 |

**Scenario 1 (gateway half)** (C-13.6 #1, a public WS disconnect, "mid-snapshot" here a subscription
attached during the outage, not a kill during an in-flight snapshot; and the gateway's reaction to
#3's desync. The ingestion halves, which leave client-WS fan-out to E17:
`tests/chaos/ingestion/test_s01_ws_hard_disconnect.py` and `test_s03_book_sequence_gap.py`). Nothing
feeds the hub yet, so the test plays the publisher, with production APIs only and nothing patched,
as the §7.4 table reads: the upstream dying is `Source.unavailable` (what the production book source
answers while rebuilding or desynced) and `SequencingHub.upstream_desync`; the upstream coming back
is `upstream_reconnect`. Flag off and on. Three sockets: a full workspace (`book` structured,
`trades`, account A's `orders` for the symbol), a chart and a chart of ETHUSDT (a mirror book). Time
moves 0.5 s once every update is delivered, a tick longer than any window a class can give (asserted
at import). Three ticks warm, a 10 s outage (20 ticks), five after. Through the outage each recorded
delta is a stray: `book_step` hands it to the hub and must find no subscription to take it (a
pending one takes no `d`), asserted at the publish, which a late frame cannot slip past. The tape is
silent; ETHUSDT's book and an update of account A's orders flow. The kill leaves both BTCUSDT book
subscriptions pending and sends nothing: no snapshot and no `cv_ws_resync_total` for the 10 s. The
recovery re-snapshots three: the two books, `upstream_desync` (an incident reason, §7.4; a pending
reason is kept, so a book's two triggers make one snap), and the tape, `upstream_reconnect` (not an
incident); `cv_ws_resync_total` moves by exactly `{upstream_desync: 2, upstream_reconnect: 1}`. A
channel reads `snap`, 3 `d`, `snap`, 5 `d`, `s` 1 to 10: the re-snapshot is the frame right after
the last `d` before the kill, its `previous_seq` that `d`'s `s`, its own `s` the next; each snapshot
is schema-valid and `Client.gaps` is empty. A `Replica` equals the server's book after the recovery
and after the five deltas, and one that lost a delta flags the gap and diverges. ETHUSDT and the
orders keep their `initial` snapshot alone. The outage is 10.000 s of virtual time (asserted) and
the recovery takes none; the snapshots land some ms after it (loop time: a few ms, flag on at times
the ~40 ms Nagle and delayed-ACK stall of the harness's accepted sockets), printed, not asserted.
`s1b`: the upstream is down and a client attaches: `sub_ok` says `snapshot_pending`, as every attach
does (conformance, not the outage's doing); the outage shows in each refused stray and no `snap`
before the restore, which sends its one, `initial` (an attach is no resync: no `previous_seq`, not
counted), equal to the book as it stands. Not covered: repeated kill and restore cycles (the "storm"
of C-13.6 #1); a flag-on kill that lands on an open throttle window (the tick outlasts any window).
Unit tests cover a pended subscription with a window open:
`test_outbound.py::test_backpressure_sheds_the_window_of_a_topic_another_sender_pended` and
`test_pacing.py::test_pacer_forced_coalescing_past_the_key_bound[re-pended]`. What none covers is a
window that `tick` flushes while its subscription is pending, which the emitter refuses until the
pending snapshot carries the state. Also not covered: the binary book path (both
scenarios subscribe structured); and the end to end run, the E08 Rig's recorded upstream through
#604 into the hub, which waits for #604 (recorded here, not filed). The
stand-in encodes the §7.4 table as the publisher's contract; if #604 does otherwise (say
`flush_pending` before `upstream_reconnect`, which gives a book two snaps) this stays "gateway
half", no proof of G3 end to end.

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
pending bytes are in it. Step 1 fires once while asleep, the class `saturated`: the tape, by far
the largest, goes, marked `backpressure`; that takes the queue below the drain line, so the book
keeps its frames and window, unmarked (#4833). No snapshot is queued while asleep (the writer,
parked in its send, runs no drain); after `HEAL` the book's kept frames, then the tape's snapshot,
and the streams resume with no gap. The test awaits that snapshot before it feeds the 4 s awake,
since a feed paced by the healthy clients alone can end before the lane recovers in wall time, and
nothing publishes after it (#4264); that wait is bounded by the wall time the lane was paused plus
1 s (5 s at least), and the wall time from `HEAL` to the snapshot is printed. So the healthy clients' awake ticks never overlap the
sleeper's backlog, by design: no assert needs the overlap, and a tick during the wait would move
the stream past it. A publish landing during the writer's resumption is covered by the unit layer
instead: `test_outbound.py::test_backpressure_slow_consumer_stays_within_the_budget` and
`::test_backpressure_busy_topic_whose_snapshot_was_sent_never_closes`,
`test_pipeline_ladder.py::test_ladder_order_drop_then_backpressure_snap_below_half_then_no_close`
and `test_pacing.py::test_pacer_next_update_after_a_snapshot_drops_the_stale_window`. No
step 3: what is left can always be dropped (`cv_ws_overflow_total` `drop` +1, `resnapshot` +1; no
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
`retry_after_ms` 3000, the fixed message). Its `most_expensive_topics` are the ranking taken when
the overflow began (#3365), at the check that went over (recounted by the test on its entry): the
tape, the orders and the book, kept to the close, where the orders alone are left.
The lane heals in the close's own synchronous turn (the feed's `until` hook, no await between),
inside the close's 2 s flush; the client backs off (§9.2 attempt 1) and re-snapshots every topic,
`orders` first (§9.3), no gap.

**Scenario 3** (no C-13.6 row: 23 §16.4's chaos row, "5 000 msg/s burst on one symbol; assert
coalescing and no sequence break"; the nearest is #11, backpressure). Flag on: coalescing is flag-on
only. The gateway has no book publisher (#604), and `Stack.book_step` sorts the book's levels four
times an update (about 0.5 ms) and ends with the recording after 5 399, so `_book.Loop` plays the
publisher: the 1 000 recorded updates that move the depth-50 window (the recording's first 1 252
deltas), built once as `window_delta` bodies (about 0.5 s), then a bridge body back to the opening
window. `publish` also applies each update's raw levels to the server's book, and the bridge takes
it back to its opening, so the stream replays for ever and every body is a true transition. One
client holds `book.BTCUSDT.50` structured (a book defaults to binary, which the `Replica` does not
read), and the hub gets 5 000 updates a second of virtual time, in lumps: each tick of 250 ms
publishes its 1 250 at one virtual instant, moves the clock and waits until the client holds them
all, so a window closes before the next tick's first update arrives. So a lapsed window flushed
inline by `Pacer.offer`, and a steady interleaving of updates with window closes, are not exercised
here. The frames are then fixed: `s` 2, the first update of a cold lane, leaves alone (the
leading edge, §8.6, D12; no
`coalesced_count`); `s` 3 is the other 1 249 of its tick as one window (`coalesced` true,
`coalesced_count` 1 249); then one window of 1 250 a tick, `s` contiguous, no snapshot after the
first, the socket never closed. The tick outlasts the slowest window the book can get, 200 ms (the
50 ms throttle x4, `saturated`): a class follows RTT samples read on the virtual clock, a `pong`
that crosses ticks can raise it (scenario 1 met that at 125 ms), and a window longer than its tick
waits for a clock the waiting tick never moves. The run is 50 000 updates in 41 frames (x1 220) in
the PR lane; 300 000 in 241 (x1 245), marked `harness`, runs nightly (`chaos-ws-nightly`): the PR
lane's `-m` leaves it out, and `-m chaos` (above) includes it (`-m "chaos and not harness"` does
not). The frames are `windows(1 250, ticks)` and the series `merged(updates, frames)`, the two
helpers the isolation tests assert the burst by too. After every tick the `Replica` equals the
server's `Book.top(50)` (23 §16.4, unit: the coalescer equals applying every source update), and
the pacer's series agree with the frames: `cv_ws_conflated_total{topic="book"}` moves by the
updates less the frames,
`cv_ws_coalesced_updates` by one count a frame but the first and the updates less one in its sum,
and nothing moves in `cv_ws_overflow_total`, `cv_ws_closes_total` or `cv_ws_resync_total`: absorbed,
not lost. A window holds at most 181 distinct levels here, against a bound of 4 096 merge keys. Wall
time is printed, not asserted: the 10 s run takes 3 to 4.5 s (14.7 s under the `py` lane's `--cov`),
the 60 s run 20 to 26 s (85 s under `--cov`, which is why it is `harness`). `loop_feed`: no server;
two laps of a `Loop`, from the
opening of the recording and from one lap in (where a clone symbol would start), through a flag-off
emitter. At every update the replica equals the server's book, so a snapshot built then would equal
what a client following the deltas holds, and at the end of each lap window and book are back where
they began (the bridge has something to take back).

**Scenario 3, the other nine symbols** (#410's second half: 06 §9's isolation clause, budget #6).
Beside the burst, nine more symbols (`ETHUSDT` to `LTCUSDT`, 06 §3.2's ten), each a clone of the
recorded book from its own place in it (500 x (n + 1) deltas in, a lap of 40 updates and its bridge)
and each held structured by its own user and client, get 8 updates a second (ruling R3). That is one
per 125 ms, below the slowest window a book can get (200 ms, `saturated`: a saturated book lane
leaves five frames a second), so the tick's guard cannot cover it and the tick stays the burst
test's grid. The isolation tests cut each tick in two (`HALF_S`, guarded at import: two make a tick,
and the healthy window, 50 ms, closes inside one) and hold every connection `healthy`: before the
clock moves, every RTT probe a client got has been answered and read (`Ten.answered`, on
`cv_ws_rtt_seconds`' count; the writer queues a probe ahead of the frame its stop waits for), so no
RTT sample spans a move, which is what raised scenario 1's class at 125 ms; no queue nears
`lagging`'s 25 %, and no `connection_quality` notice reaches any client (asserted). At a tick's
start and at mid-tick the nine get one update each and the burst symbol 625, 25 at a time with one
of the nine ahead of each of the first nine slices, so all but the first of the nine publish while
the burst's window is open (it opens in the first slice). The burst's frames are the burst test's at
half the lump (`windows(625, n)`): the tick's own grid cannot carry them, as a stop at mid-tick
closes the 50 ms window off the grid and leaves the next lump a leading edge. `same_frames` (ruling
R4; 10 s in the PR lane, 60 s `harness`): on the virtual clock the nine's clients get, byte for
byte, the frames of a control run on a second `flag_on()` stack in which the burst symbol gets one
update a half tick; each of the nine's updates is its own `d` (no `coalesced_count`) and arrives at
the virtual instant of its publish (zero lateness, by construction: the clock cannot move until all
nine have arrived), schema-valid (`BookTap`), `s` contiguous after the one `initial` snapshot, the
`Replica` equal to the server's book; no client sees a gap, a close or a reconnect; and the pacer's
series move for the burst's windows alone (`merged`), and for nothing in the control. 10 s: 9 x 80
updates beside 50 000 in 81 frames, 93 to 100 probes, 13 to 16.5 s of wall time for both runs (31 to
38 s under the `py` lane's `--cov`); 60 s: 9 x 480 beside 300 000 in 481 frames, 593 to 600 probes,
71 to 82 s (the last grid's probes may queue after the final move, so the runner printed 93 and 593).
Not covered: each of the nine has its own user and connection, so this proves isolation across
connections, not per-lane isolation on one socket, the multi-pane workspace of 06 §3.2, where the
burst symbol and the others share a writer, an outbound budget and a class. That is a follow-up, not
filed (the filing freeze).

**Scenario 3, budget #6 in wall time.** `fanout_p95` (`harness`: nightly only) and its negative
control `p95_measure_fails` (marker `chaos` alone, so the PR lane runs it, in 7 to 9 s under
`--cov`, and the nightly again) run on fresh stacks with `TCP_NODELAY` (`flag_on(nodelay=True)`),
the collector off, the clients checking nothing (a schema check costs about 2 ms a frame, the
client's, not the gateway's), and the burst's updates 5 a slice (`TIMED_SLICE`; the isolation tests
keep 25) with a yield after each. `fanout_p95` drops a 1 s warm-up run, then runs the control and
the burst ABBA, 30 s each, pooling each kind's two, so neither warm caches nor drift favour either.
Every client still ends clean, and the nine's publish-to-arrival p95 must be within budget #6's 20
ms; their median within 8 ms of the control's; at most 9 of their 4 320 updates over 100 ms and none
over 1 s; and the burst's window within 20 ms (p95) of its release; figures printed. The arrival
is the client's, through the proxy: a frame of the nine waits out six slices of burst updates, its
publish's own and one in each of the five loop turns that carry it (the writer's send, the proxy's
read and its pipe's write, the client's socket read and its task's; counted: 5 or 6 for every
update, 6 at the median). So the burst adds about 30 updates' publish time to their median, 1.5 to
1.8 ms at the 50 to 60 us an update that the burst test prints, where 25 a slice would add 7.5 to 9
ms against the 8 ms bound (a 2 s run on this shared host, at a load of 8, added 9.9 ms at 25 a
slice, 4.2 at 10 and 1.8 at 5). The 8 ms is 40 % of the budget and about five times that model: a
burst that moves the typical update this much is a regression even where the p95 holds.
test_flood_isolation has the same 8 ms, there about three times its flood's cost (2 to 2.7 ms): its
calibration, not this test's. 100 ms is 5 x the budget, a stall, not a latency: one stall holds
every update then in flight, and a half tick's nine are in flight together (published in its first
nine slices, all delivered before the clock moves, the next half tick's only after), so 9 over it is
one stall, which a run may have; a few stalls, or anything periodic, fail it, where a p99.9 would
let only 4 of the 4 320 pass. That cap counts the updates a stall holds, not for how long, so none
may take over 1 s (10 x 100 ms): one freeze of 1 to 4.9 s would hold only nine and pass every other
check, and a longer one ends at a wait's 5 s bound only if it lands inside a wait; one in the
slices, where no wait runs, only this ceiling catches. The burst's window is timed from the move
(`released`, stamped just before `advance`), as budget #6's span for a paced frame starts at its
release from the window (23 §8.6, D7); the writer's real poll (at most 5 ms, the rig's `tick_s`) and
the move's settling stay inside it, so it is an upper bound, and a loud run's window that left
before its release fails at once (no span below 0). The negative control holds the loop 25 ms in
each slice that carries one of the nine and again between the stamp and each move, for 1 s: each of
their updates and each of the burst's windows waits at least that long, so both budget #6 checks and
the median fail by construction, as asserted, and load can only widen the margin. The stall count
fails there too, and the ceiling holds (the nine's slowest crosses six holds: 165 to 305 ms in 17
saved runs here); neither is asserted. A test here that fails intermittently on the nightly's
runners is quarantined within 24 hours per C-9.3: `@pytest.mark.flaky` and a P1 ticket, the
quarantine expiring after 10 working days, when the test is fixed or deleted with the owner's
approval (`docs/ci-runbook.md` §2 and §9). Only the 20 ms is the standard's (06 §2), and it is never
loosened, nor any check turned into a print. The derived tolerances (the 8 ms added to the median,
the 9 updates over 100 ms, the 1 s ceiling) were reviewed once against the first dispatched figures
(run 39723275319, below) and change only by a reviewed PR that carries the figures (06 §7.4's
baseline rule). `Stack`'s users other than these tests keep its default, no `TCP_NODELAY`.

**Scenario 3, budget #6: the first calibration.** `chaos-ws-nightly` run 39723275319, dispatched on
this branch at `f9c90eb8` (`ubuntu-latest`: Ubuntu 24.04, Python 3.12.3), passed all 21 tests in
99.53 s and printed, under PASSES: the nine beside the burst p50 1.95, p95 3.24, max 4.36 ms, 0 over
100 ms; without it p50 1.05, p95 1.91, max 3.08 ms; the burst's window from its release p50 2.25,
p95 6.77, max 7.09 ms; and the negative control's nine at p95 154.38 ms and window at p95 33.94 ms,
failing as designed. `fanout_p95`'s call took 15.96 s, `same_frames[60s]` 30.37 s and
`same_frames[10s]` 5.41 s. The median added, 0.90 ms, sits by the cost model at that runner's
per-update cost (the burst test printed 22.0 us there: 6 x 5 x 22 us, 0.66 ms). The window's p95
used a third of its 20 ms. A miss there is read first as calibration of the harness's own span (the
writer's poll, the move's settling and the hops, all inside it), and whatever that changes follows
the rule above: a reviewed PR that carries the figures, the 20 ms itself never loosened. A second
sample, run 39727981409 dispatched at `9551bd6f`, passed all 21 tests in 88.99 s: the nine p50 1.47,
p95 2.29, max 4.00 ms; without the burst p50 0.83, p95 1.52, max 2.70 ms; the window from its
release p50 2.81, p95 6.45, max 6.89 ms; the negative control failing as designed (the nine's p95
153.02 ms, the window's 32.74 ms).

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
- **Scenario 1 mutation** (in memory, no file written): `s1`, flag off and on, fails on each of 13
  mutants of `ws/sequencing.py` and `ws/pacing.py`: a `d` taken by a subscription that waits for its
  `snap` (`TopicEmitter.delta` ignoring `snapshot_pending`, which only flag off reaches, since the
  pacer's `_held` refuses first; `_held` ignoring it, flag on only; both fail every test),
  `resnapshot` not marking the subscription pending, `_live_symbol` matching every symbol, the
  private topics (the blotter filtered to the symbol) or, with `book_only` flipped, the wrong
  families, `upstream_desync` not book-only, `upstream_reconnect` book-only, `previous_seq` dropped,
  `s` skipping one (`s1b` too), the resync counter removed, a pending reason replaced by the mundane
  one (`s1b` too: an attach would be counted), a snapshot that claims success without building. One
  survives: `resnapshot` not invalidating the snapshot cache, which this harness cannot show, since
  the source's generation moves with every update.
- **Scenario 3 mutation** (in memory, no file written): the burst fails on each of 10 mutants of
  `ws/pacing.py`, `ws/coalescing.py` and `ws/sequencing.py`: the conflation counter removed, or
  `cv_ws_coalesced_updates` not observed (the series no longer agree with the frames); the book merge
  keeping the first write of a level, dropping the deletes, or forgetting an update (the replica
  leaves the book at the first tick, or the counts never add up: the 5 s wait); the throttle
  bypassed, or a window flushed early (a frame an update, nothing coalesced); a window's count one
  off either way; `s` taken twice (a gap; the loop's own test fails on it too). Four mutants of the
  loop itself (the server's book not taking the raw levels, a bridge that leaves the book or the
  window where it is, the raw levels of a skipped delta dropped) fail the burst and both runs of the
  loop's test.
- **Scenario 3 isolation mutation** (in memory, no file written): `same_frames[10s]` fails on each
  of 6 mutants of `ws/permissions.py`, `ws/pacing.py` and `ws/sequencing.py`: a connection's book
  subscription found by family (every book update reaches every book client: the publish counts
  10); one throttle for the hub (a lane's window starts at any lane's last emit, so the nine are
  held); one coalescing queue per family shared by every lane (the nine's leading edges carry the
  open burst window); a leading edge held while any lane anywhere has a window open; the hub
  re-snapshotting the other books every 625 burst updates; a book `d`'s `s` from one counter for
  the family. With the nine published ahead of the burst's lump the shared queue survived, so they
  publish inside its slices, while its window is open. One survives: one class for every
  connection (the worst any pacer holds), since no class moves here; scenario 2's mutants kill it.
  `p95_measure_fails` is the wall-clock half's own check, in every lane: a loop held 25 ms in each
  slice that carries one of the nine and before each move fails both budget #6 checks and the
  median.
- **Scenario 3 wall-clock sensitivity** (by the cost model, its method stated; the probes are
  uncommitted scratch): count the loop turns between a nine update's publish and its arrival (each
  crossed 5 or 6 slices, 6 at the median), and measure the per-update publish cost (the burst test
  prints it: 50 to 60 us here, 22 us on the dispatched runner); the burst then adds 6 x 5 x that to
  their median. One in-memory mutant was measured: about 300 us of busy work in each burst
  `hub.publish` (the model's +9 ms), on 2 s timed runs here (a dropped warm-up, then ABBA, at a load
  of 10). The median added went from 2.21 ms unmutated, passing, to 13.89 ms: the 8 ms check
  tripped, and so did the nine's p95 (33.66 ms).
- **SR-189 flip:** #2318 merged (`549d9032`), and `s6b` reported `XPASS(strict)` on the rebased
  branch, as planned, so its `xfail` marker is removed and it runs as a plain test.
- **Flake budget:** 3 consecutive gate runs plus 20 more after the flip, all green (`7 passed`).
  With scenario 2: three runs in three seeded shuffled orders and one with `-W error` (`9 passed`),
  and two runs of `s2` and `s2b` under the `py` lane's flags (`--cov`) with the 128 KiB lane buffer
  (three more at the earlier 32 KiB lane buffer), all green. Scenario 3's isolation, before the
  review fold: five consecutive runs of `test_s3_burst.py`'s PR-lane tests and one with their order
  reversed (`4 passed` each; no `pytest-randomly` here), and the 60 s `same_frames` twice and the
  burst once, all green. After it (the timed slice of 5, the negative control in the PR lane), each
  run its own pytest process under the `py` lane's `-m` and `--cov` flags, on a shared host at a
  load of 8 to 13.5: `same_frames[10s]` 11 times (31 to 38 s each) and `p95_measure_fails` 10 times
  (7 to 9 s each; the nine's p95 172 to 226 ms, its check failing every time, as it must), all
  green. With the hold before each move added, `p95_measure_fails` 3 more times at a load of 7 to 9
  (7 to 8 s each; the nine's p95 174 to 195 ms and the window's 55 to 58 ms, both checks failing
  every time), all green. With the median asserted too, `p95_measure_fails` 3 more times at a load
  of 9 to 11 (7 to 8 s each; the nine's p95 176 to 212 ms, the window's 46 to 63 ms and the median
  added 136 to 137 ms, all three failing every time), all green; and `same_frames[60s]` once more
  after the third fold, green in 71.4 s for both runs (78.5 s for the process). The 60 s burst and
  `fanout_p95` were not run here. Budget #6's first figures, from a clean runner, are the
  calibration above (run 39723275319).
