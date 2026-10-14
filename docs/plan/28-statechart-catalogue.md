# 28 — Statechart Catalogue (lifecycle contracts executed by `xstate-statemachine`)

Date: 2026-09-15 (revised 2026-09-24) · Status: **normative**. Governing decision: [`27-adrs/ADR-0016-statechart-runtime.md`](27-adrs/ADR-0016-statechart-runtime.md) — **Accepted (2026-09-24)**: every contract here is executed by **`xstate-statemachine==0.9.1`** via `cv.statechart.factory`. There is no in-house shim.

---

> **2026-09-24 — full adoption (ADR-0016 Decision (final)). Current position.** The JSON below is loaded unmodified by `cv.statechart.factory.build(chart_id)` and run on the library under the FINAL mandatory configuration (§1.3c). The factory injects `"strictConfig": true` and `"maxIterations": 500` at build time. Four our-side chart defects found during verification are **merged** here, each marked *Corrected 2026-09-24* in its entry: **B16** C-04 (revocation hoisted to root → `elevation.dead`; region `REVOKE` deleted), **B18** C-07b (`onUnhandled: "defer"` + ordered unguarded `RELEASE` audit arm), **B11** (event-aware `all_streams_healthy` / `reasons_remain`; `degraded` handles `GAP_DETECTED`), **B8** B610-OC-CD03 (bounded `fallback_attempts` on the `naked ⇄ verifying` loop). This closes gate P3-G1 once `tests/xstate_contract/` is green on them. Inline `// CV-C31…` comments inside JSON blocks are historical; the policy keys themselves are authoritative, and comments are stripped by the factory loader.
>
> **Round-6 catalogue corrections (2026-09-20, ADR-0016 Amendment 6).** `actionErrorPolicy: "fail"` is **re-permitted and in places required** (#145 verified; CV-C31 retired and inverted by CV-C31′ — `"rollback"` is now the unsafe policy on an `invoke`-carrying state with a raisable entry action, upstream R6-03). `onUnhandled: "error"` is **removed from B18** (C-07b: a guard-denied `RELEASE` bricks the kill switch). New structural rules CV-C35 (no `always` into an invoked child), CV-C36, CV-C37; **CV-C30 retired** — parallel regions are safe again now that #142/#143 enforce one legality predicate on both snapshot sides. Outstanding on our side: the explicit `halted` states CV-C31 promised were never written (C-07), plus C-04 (B16 elevation survives `LOGOUT`/`REVOKE`), CV-B4-01, C-06, OUR-B11-01, OUR-B14-01 — all ticketed in `E50-T14`/`E50-T16`. See `docs/research/xstate/39-r6-final-readiness-verdict.md` §4/§7.
>
> **Round-5 catalogue corrections (2026-09-19, CV-C34/CV-C31):** all `"*": {"actions": ["defer"]}` scaffolding removed (OC-01 — it pre-empted `onUnhandled: "defer"` and silently disabled `strict`); `actionErrorPolicy: "fail"` withdrawn everywhere in favour of `"rollback"` + explicit `halted` states (R5-12). Invariant gaps OC-02…OC-10 (B2, B4, B8, B11, B14, B16, B19) are ticketed in E50-T14 and their corrected JSON lives in `docs/research/xstate/battle-3ed3099/contracts/*.machine.json` pending merge here.


## 0. What this document is, and what it is not

This document is the **behavioural contract** for every long-lived lifecycle in CandleViewer. For each of the twenty components analysed in `docs/research/xstate/10-fit-analysis.md` Part B it gives the XState-v5-compatible statechart JSON, the event / guard / action / service tables derived from that JSON, and the invariants the implementation must satisfy.

**It is executed by `xstate-statemachine`.** A contract names *states, events, guards, actions and services*; the library interprets the JSON directly, and our Python supplies only the `logic` (guards, actions, services) bound by name. The executor is fixed by ADR-0016 (Accepted):

| Aspect | Value |
|---|---|
| Executor | `xstate-statemachine==0.9.1` (hash-locked, PEP 740 attested), async `Interpreter` in production |
| Construction | `services/api/candleviewer/statechart/factory.py` (`cv.statechart.factory`) — the only call site of `create_machine` / `Interpreter` / `Interpreter.from_snapshot` |
| Configuration | FINAL mandatory block, §1.3c |
| Hot paths | never a chart (§1.2); per-tick rule evaluation stays plain Python (BENCH-2 380.9 ev/s vs 2,000) |

### The three ways to read this

1. **You are implementing a lifecycle.** The owning tickets (E08, E16, E26, E29, E32, E33, E34, E35, E39, E40, E44, E45) load the JSON here through `cv.statechart.factory` and implement only the named guards, actions and services as the machine's `logic`. You do **not** hand-roll transitions. The JSON is the program; the contract suite (`E50-T03`, `tests/xstate_contract/`) asserts its golden traces on the library.
2. **You are reviewing a lifecycle.** The contract is the specification. If the code and the JSON disagree, the JSON is right and the code is a defect.
3. **You are wondering whether something should be a statechart.** Read §1. The answer is *no* far more often than the state-shaped feel of a problem suggests.

### What is *not* here

- Hot paths. See §1.2. The exclusion is architectural and measured, not a preference.
- Enum definitions, field types and persistence schemas. Those are owned by [`24-internal-schemas.md`](24-internal-schemas.md); this document links to the owning section and does not restate it (`CONSTITUTION.md` §16.5 single-source rule).
- The factory, the linter, the gateway, the reaper and the persistence envelope. Those are ADR-0016 (Decision (final)), `20-architecture.md` §statechart runtime, `24-internal-schemas.md`, and epic `E50` / `E29-T10`–`E29-T12`.

---

## 1. Scope — what is a contract here, and what must never be one

### 1.1 In scope (the adopt-for list, `11-adversarial-review.md` §5)

| § | Machine | `id` | Owning epic | Schema owner | Fit | Event rate |
|---|---|---|---|---|---|---|
| [§B1](#b1--order) | Order | `order` | E29 | 24-internal-schemas.md §8.2 (order state machine), §8.8 (native-SL invariant), ADR-0006 | Good | per-order exchange events; bursty on fills, otherwise low |
| [§B2](#b2--tradegroup) | TradeGroup | `trade_group` | E34 | 24-internal-schemas.md §9.6 (group lifecycle), §9.4 (fan-out), §9.5 (leg failure policy), ADR-0008 | Good | low - one event per leg outcome |
| [§B3](#b3--tradegroupleg) | TradeGroupLeg | `leg` | E34 | 24-internal-schemas.md §9.1 (model), §9.5.1 (per-account unwind), §9.3 (sizing) | Good | low per leg; bursty on fills |
| [§B4](#b4--emulatedalgo---oco) | EmulatedAlgo - OCO | `oco` | E33 | 24-internal-schemas.md §10.2 (OCO), §10.1 (common algo model) | Good - the best algo fit; event-driven and timing-light | low |
| [§B5](#b5--emulatedalgo---iceberg) | EmulatedAlgo - Iceberg | `iceberg` | E33 | 24-internal-schemas.md §10.3 (iceberg), §10.1 | Workaround - structure and bounds only; all timing external | low |
| [§B6](#b6--emulatedalgo---twap) | EmulatedAlgo - TWAP | `twap` | E33 | 24-internal-schemas.md §10.4 (TWAP), §10.1 | Workaround - structure and bounds only; all timing external | low |
| [§B7](#b7--emulatedalgo---chase) | EmulatedAlgo - Chase | `chase` | E33 | 24-internal-schemas.md §10.5 (chase / pegged limit), §10.1 | Workaround - the weakest of the four algos | input bounded to <= 10 Hz by contract |
| [§B8](#b8--position-protection--native-sl-invariant) | Position protection / native-SL invariant | `position_protection` | E32 | 24-internal-schemas.md §8.8 (safety invariant), §10.7 (bracket), ADR-0008 rule 2 | Workaround | low; the watchdog scan is externally scheduled |
| [§B9](#b9--rule-instance-lifecycle-only) | Rule instance (lifecycle only) | `rule_instance` | E35 | 24-internal-schemas.md §11.5 (evaluation semantics), §11.7 (safety limits), §11.9 (simulation), ADR-0007 | Workaround (lifecycle) / **Not suitable** (per-tick evaluation) | lifecycle transitions only; **never per tick** |
| [§B10](#b10--alert-lifecycle) | Alert lifecycle | `alert` | E40 | **not yet in 24** - see §Gaps below | Excellent | human frequencies |
| [§B11](#b11--recordingsession) | RecordingSession | `recording` | E16 | 24-internal-schemas.md §13.1 (recording policy model), ADR-0015 | Excellent | per-symbol lifecycle events only |
| [§B12](#b12--replaysession) | ReplaySession | `replay` | E26 | 24-internal-schemas.md §13.7 (replay engine) | Good | control events only; the data path is outside the machine |
| [§B13](#b13--exchangeconnection-ws-reconnect--resync) | ExchangeConnection (WS reconnect / resync) | `ws_conn` | E08 | 20-architecture.md §3.1, §10.4 (reconnect and resync) | Good | rare transitions; steady state is a heartbeat |
| [§B14](#b14--book-health-fsm-data-path-excluded) | Book health FSM (data path excluded) | `book` | E08 | 20-architecture.md §3.2 (book engine), §4.2 (backpressure) | **Not suitable** (data path) / Good (health FSM with the data path excluded) | health transitions only - resync/desync, not deltas |
| [§B15](#b15--paper-account-liquidation-fsm) | Paper-account liquidation FSM | `paper_account` | E38 | 24-internal-schemas.md §12.4 (margin, liquidation and ADL) | **Not suitable** (paper matcher) / contract-only (account liquidation FSM) | **edge-triggered only** - on band change, never per tick |
| [§B16](#b16--authsession--step-up) | AuthSession / step-up | `session` | E09 | 24-internal-schemas.md §15.1 (session model), §15.3 (step-up), ADR-0010 | Good | low; documented ~100-session threshold per process |
| [§B17](#b17--liveenablement-gate) | LiveEnablement gate | `live_gate` | E44 | 24-internal-schemas.md §15.3 | Excellent | extremely low; audit-shaped |
| [§B18](#b18--killswitch) | KillSwitch | `kill_switch` | E39 | 24-internal-schemas.md §11.7 (safety limits and kill switches) | Good - as record-and-orchestrate only | extremely low |
| [§B19](#b19--reconciliation-job) | Reconciliation job | `reconciliation` | E45 | 24-internal-schemas.md §8.5 (reconciliation algorithm), §14.3 | Good | periodic sweeps plus event-triggered runs |
| [§B20](#b20--risklockout) | RiskLockout | `risk_lockout` | E39 | 24-internal-schemas.md §11.7 (safety limits) | Good | **edge-triggered** on band change only |

### 1.2 Out of scope — never a statechart, in any form

From `11-adversarial-review.md` §5 "Do not use for" and MUSTNOT-01/02/05. These are not "discouraged"; they are forbidden, including as internal (actions-only) transitions.

| # | Path | Measured reason |
|---|---|---|
| 1 | Book-engine delta application, bar builders, footprint aggregation | 48k ev/s against a ~9–20k process budget, and a 33 µs transition tax on 15–60 µs of real work |
| 2 | Per-tick rule **condition** evaluation | plain Python does the entire unfiltered 200,000 eval/s workload in 30 ms — **~744×** the statechart fleet; no pre-filter closes the gap |
| 3 | Paper-matcher fill model, queue-position estimator, fee/funding arithmetic | no states, and it needs virtual time no runtime here provides |
| 4 | Per-account rate-limit governor / fan-out admission control | **~238,000×** slower (35.2 ms p50 vs 0.148 µs) and structurally unable to answer synchronously |
| 5 | Any synchronous safety **enforcement** point — kill switch, live gate, risk caps, rate budgets | a statechart **records and orchestrates**; a synchronous flag or function **enforces** |

> The rate-limit governor is the canonical trap: it has states (`open` / `starved` / `downshifted`), it has transitions, it looks textbook, and it is on this list. Anything on the order path that must **return an answer** rather than **record a fact** cannot be a statechart.

### 1.3 House rules every contract in this document obeys

These are `10-fit-analysis.md` Part A, enforced by the machine-definition linter (`E29-T10`) and the conformance suite (`E50-T03`) rather than by review discipline.

| Rule | Statement | Visible in the contracts as |
|---|---|---|
| **A1** | No action may raise. Ever. | every action is `@cv_action`-wrapped; a fault routes to a quarantine/error state |
| **A2** | Timing lives outside the statechart. | no `after` anywhere in this catalogue; every deadline is an absolute `*_us` timestamp in context, armed by the `MonotonicScheduler` |
| **A3** | Every transient state has an explicit deferral handler. | ~~`` plus `drain_deferred` on entry~~ — **superseded 2026-09-17** by `onUnhandled: "defer"` in the policy block (§1.3b) |
| **A4** | Self-transitions must say `reenter: true`. | every self-target in this document carries it; `always` self-targets are a build error |
| **A5** | Absolute targets only, validated at build time. | every `target` is `#machine.path.to.state`; CI resolves each one against the state tree |
| **A6** | Guards are pure, total, and deny-by-default on safety paths. | safety guards prove permission; failure or exception means **blocked** |
| **A7** | The statechart is never the book of record. | Postgres is authoritative; every transition write-ahead-logs before the in-memory state changes |
| **A8** | Operational hygiene. | shared machine definitions, thread-safe sends through the gateway, compact snapshots |

The nine MUST-NOTs and twelve MUSTs from `11-adversarial-review.md` §3 are reproduced in full in ADR-0016 and are binding on every machine below.

### 1.3b The mandatory policy block (added 2026-09-17, ADR-0016 Amendment 1)

Every contract in this document opens with the same six keys, immediately after `"id"`. They are **normative and non-negotiable**: two of the four Blockers closed in `xstate-statemachine` 0.8.0 (`LC-01` action-raises, `LC-03` unhandled-events) are closed by a per-machine policy whose **default still reproduces the old, silent behaviour**. A machine that omits them is a machine with two open Blockers.

```jsonc
"actionErrorPolicy": "rollback",   // DEFAULT. CV-C31' RETIRED on the async lane (2026-09-21) and
                                   // CV-C31" RETIRED OUTRIGHT (2026-09-22): #193 unwinds a `def`
                                   // invoke on rollback on the async engine, which was CV-C31"'s
                                   // entire ground. The surviving ROLL-FORWARD leak (R9-04) is a
                                   // different shape, carried by CV-C32 + CV-C46, not by a policy ban.
                                   // Wrapper attempt counter STILL REQUIRED on any rollback +
                                   // invoke.onDone state: the storm is bounded (maxIterations+2) but
                                   // every lap is a real order, and R9-07 can wedge it silently.
                                   // Order-path states with invoke + raisable entry still use "fail".
                                   // CV-C31 (the blanket ban on "fail") remains RETIRED: #145 verified.
"onUnhandled":       "defer",      // "error" on the control machines -- but NOT on B18 (C-07b)
"guardErrorPolicy":  "raise",      // a crashed guard is NOT a denial. #170 made the receipt matrix
                                   // injective, so `denied` alone is a correct discriminator (W-04a
                                   // retired); W-04b stands -- `defer` still outranks guard_denied
"strictTargets":     true,         // kills the silent sibling-target fallback; #147 now raises
                                   // a non-downgradable RootTargetError at build time
"strict":            true,         // undeclared event names raise at the call site. #190/#195/#203
                                   // FIXED: config-level strict is inherited, "*" no longer defeats
                                   // it, and a hand-built Done/Error/AfterEvent IS refused at send().
                                   // R9-02 IS CLOSED (2026-09-22, round 10): #203 gates `after`
                                   // selection on is_system_event at base_interpreter.py:4624 -- the
                                   // same test the Done/Error branch already used. The discriminating
                                   // control (a public AfterEvent firing a 60s timer instantly at the
                                   // DEFAULT strict=false) is refused on both engines.
                                   // => CV-C45's SEND-SIDE CLAUSE RETIRES. The RESTORE-side clause
                                   //    does NOT, and is WIDENED, on two surviving residuals:
                                   //  - strict does NOT gate events restored from pending_events
                                   //    (R10-05a) -- _check_strict runs at the send() call site only,
                                   //    and _enqueue_restored -> _put_inbox bypasses it.
                                   //  - a 0.8.0-era persisted `after` record (kind:"after", NO
                                   //    "engine" flag) is now SILENTLY REFUSED rather than demoted
                                   //    (R10-05b): the deadline is DROPPED with no raise, no WARNING
                                   //    and nothing on last_error. Migrate blobs before restore and
                                   //    RE-ARM deadlines from context (CV-C48).
                                   // R10-07 stands (was R9-16): a TYPO in a top-level key is silently
                                   // accepted and downgrades to the default -- measured 6/6 keys,
                                   // including strict->False and onUnhandled "error"->"ignore", with
                                   // a GREEN build. The wrapper whitelists top-level keys itself.
                                   // R10-01 (Blocker->Low): in-process forgery via engine_after /
                                   // _replace / pickle / deepcopy is real but presumes attacker-
                                   // controlled Python, which already grants strictly more; and the
                                   // snapshot vector needs blob-write, which suffices with NO event
                                   // forgery at all. Hardening, not a boundary break.
"spawnBlockingTimeout": 5000,      // ms; never rely on the 30 s default. NOTE R9-16: parsed but sets
                                   // no MachineNode attribute, so a lint cannot assert it post-build
"maxIterations":     500,          // LIVE and lane-independent. Re-confirmed 2026-09-22 by POLLING TO
                                   // CONVERGENCE rather than trusting a changelog: the rollback +
                                   // onDone storm plateaus at EXACTLY maxIterations+2 (1003/1003) on
                                   // BOTH lanes and stays there -- `def` converges ~1.0s, async <0.5s.
                                   // (Upstream's own test reads the counter at 0.6s and so reports
                                   // correct behaviour as a spin ~80% of runs. Poll, never sleep.)
                                   // R8-01's residual inertness is CLOSED by #192: the priority lane
                                   // now sheds by provenance, verified on the real B18 -- 12/12 kill
                                   // presses accepted, 0 shed, press pre-empts the chain.
                                   // ONE residual remains: a DELAYED self-send cycle is charged to
                                   // nothing and tagged *external* by #192, so it can never be shed
                                   // (R9-06). That is why CV-C42 still bans priority=True OUTRIGHT.
                                   // ---- ROUND 10 (2026-09-22), main @ 19cb1f1 ----
                                   // R9-06 is CLOSED by #206: a delayed self-send is now a debt of
                                   // the arming step and its firing is charged as engine work.
                                   // CV-C42's ban STANDS on narrower ground -- see R10-03 below, and
                                   // R10-C4's refutation confirming priority=True is an INBOX LANE,
                                   // not configuration-level selection, so it never buys what people
                                   // expect (sibling-only kill 1.458s; ancestor handler 0.001s).
                                   // TWO NEW RESIDUALS:
                                   //  - CROSS-ENGINE BUDGET EQUIVALENCE IS NOT A SAFETY PROPERTY
                                   //    (R10-06). #209's "all three lanes agree at limits 1-25" is
                                   //    false on ENGINE-WORK-ONLY charts: async grows ~3*mi+3, sync
                                   //    ~2*mi+3, and 24/25 swept limits differ -- at mi=25 the same
                                   //    chart is permitted ~47% more work on one engine. Size
                                   //    maxIterations PER ENGINE; never carry a limit validated on
                                   //    one engine across to the other.
                                   //  - THE CHAIN-CLEAR TEST IS TIME-BLIND (R10-03). A self-paced
                                   //    raise(delay=) heartbeat dies at maxIterations beats
                                   //    REGARDLESS OF PERIOD (measured 9 beats at 30/100/250ms
                                   //    alike). Use `after` -- measured 93/92 beats in 3s with ZERO
                                   //    drops on the same config -- or the external
                                   //    MonotonicScheduler. => CV-C47. NOTE BENCH-6 is UNMEASURED for
                                   //    two rounds, so `after` stays coarse-timeouts-only.
```

> **Round-10 amendments (2026-09-22, ADR-0016 Amendment 10). Current position.** The keys are
> unchanged; five things about how to read them are.
> **(1) `strict` now carries its own weight on the send side.** #203 closed R9-02 at
> `base_interpreter.py:4624`, so **CV-C45's send-side clause retires** — the gateway no longer needs
> to reject externally submitted `AfterEvent`s, because the engine refuses them itself with a named
> `UnknownEventError` on both spellings, at the *default* `strict=false`. **The restore-side clause
> does not retire and is widened**: match the serialised record `kind` as well as the class, and
> **re-arm deadlines explicitly from context** (CV-C48), because a pre-0.8.1 `after` record is now
> silently *dropped* rather than demoted.
> **(2) The order path may run on `SyncInterpreter` again — CV-C46 RETIRES.** Its entire ground was
> R9-04's sync-engine roll-forward leaks; #204 closed them (`LD-01` 3 leaks → 0/6) and the
> `167 rollback_reinvoke_spin` cell now passes 5/5. **CV-C32 also retires as a *safety* rule** while
> the rule stands verbatim, re-grounded on R10-D2: an invoke-bearing state with an escape transition
> cannot be pre-empted on the `def` lane, so the escape is not an escape (binds B12 `buffering`,
> B12 `stepping`, B13 `subscribing`). The async engine remains our order-path engine by preference,
> not by containment.
> **(3) A SELF-TARGETING TRANSITION IS INTERNAL BY CONTRACT — `"reenter": true` is mandatory** on any
> self-targeting `onDone`/`on` meant to **restart** a state's invoke or entry actions. XState v5 makes
> internal the default with `reenter` as the opt-in, and this library follows it. Without `reenter`,
> the invoke arms exactly once and never again (`submits = 1` forever); with it, every lane re-arms
> to `maxIterations + 2` and the `#207` stranded hook fires. The library's validator warns for the
> `always` case only, so **our lint must cover the `onDone`/`on` case** (R10-02, refuted — the defect
> was our chart, and it cost a round to establish).
> **(4) Kill/cancel is declared on an ANCESTOR of every invoking state (CV-C4x), never only on
> siblings.** Measured: sibling-only holds the kill **1.458 s** against a 1.5 s service; a
> parent-level handler **0.001 s**; a handler on the invoking state itself **0.000 s**. `priority=True`
> does not help — it is an inbox lane, not configuration-level selection. Statically lintable, and it
> is the whole of R10-C4 once that finding is refuted down to a modelling error.
> **(5) Observability never polls `last_error` (CV-C50).** `RunawayChainError` is **cleared once
> settled on the `async def` lane and retained on the `def` lane**, so a supervisor sampling
> asynchronously sees the runaway on `def` services and **misses it on the recommended `async def`
> ones**. `CvErrorHooks` implements `on_invocation_stranded` and samples
> `on_event_dropped(..., "chain_budget")`; the health sweep asserts `has_dormant_invocations() is
> False`. Also: **snapshot only with no armed delayed self-`raise` debt** (CV-C49) — an armed-but-
> unfired self-delay has no snapshot representation at all and is discharged silently on restore,
> wedging any state whose only exit was that event.
>
> **What blocks B16 and B18 is OURS, and round 10 removed the last doubt about it.** **C-04** (B16
> elevation outlives `LOGOUT`/`IDLE_DEADLINE`/`ABSOLUTE_DEADLINE`, and a dead session can be
> re-elevated) and **C-07b** (B18's `onUnhandled: "error"` plus a sole guarded `RELEASE` bricks the
> kill switch) were both filed as library Blockers this round and **both were refuted by building the
> corrected chart and running it** — B16 with all revocation events handled in the elevation region
> plus a `session_alive` guard on `STEP_UP_OK`, and B18 with an ordered unguarded `RELEASE` fallback
> while **keeping** `onUnhandled: "error"`. Both corrected charts pass on **both engines and both
> service spellings**. The engine follows the chart in every cell. The Amendment-6 removal for B18
> **still has not landed in `ka_killswitch` JSON** (sha1 `3d0de943effd` at `19cb1f1`), and
> `B16.machine.json` is byte-identical to the catalogue (sha1 `9d8ad9937417`). These are the only
> Blockers of any kind left in a ten-round study, they are open five rounds, and they are the next
> thing to work.
>
> Also ours, and new this round: **R10-C3** — `B19.machine.json` declares only `RECONNECTED` on
> `reconciliation.stale_lockout` while catalogue invariant **INV-B19-b states it is "cleared only by
> `OPERATOR_RESOLVED`"**. The contract contradicts its own normative invariant. The lockout *is*
> escapable (so this is Medium, not High), but only by a **connectivity** signal — meaning an
> automatic reconnect can clear a paged critical state with no operator in the loop and no distinct
> audit record, and the escape is venue-conditional. Fix: add `OPERATOR_RESOLVED` to
> `stale_lockout.on` targeting `idle` with `reset_failures` plus an audit action. And **R10-C5** —
> B16's `elevated→elevated` `STEP_UP_OK` re-enter arm carries `[stamp_elevated_until]` only, omitting
> the `audit_step_up` present on the `normal→elevated` arm, so **a privilege extension leaves no audit
> record** (`audit_step_up = 1` for 2 presses, both lanes).

> **Round-8 amendments (2026-09-21, ADR-0016 Amendment 8). Superseded by the round-10 block above; retained as history.** The six keys are
> unchanged; five things about how to read them are.
> **(1) `maxIterations` is a real bound again** — see the annotation above. **CV-C38 retires**: the
> engine bounds invoke cycles itself now, verified at identical lap counts on both service spellings
> on the real contract machines. Linter rule **CV-LINT-XS16 is downgraded from error to warning**, not
> deleted — an unguarded invoke cycle is still a design smell and is still the trigger R8-04 needs.
> The practical consequence: **B18 leaves the library-blocked set.** Its kill-switch path, which
> produced 3,547 `flatten_all_positions` calls in 3.0 s at `221ce7c`, now plateaus at 1,002 with
> `last_error = RunawayChainError`. What still blocks B18 is **ours** — C-07b.
> **(2) `priority=True` is forbidden OUTRIGHT (CV-C42, widened)** — everywhere, on any event, from any
> origin, not merely outside wrapper code and not merely on externally originated events. Upstream
> R8-01 makes both halves of the lane unsafe: a priority event issued from an action is never charged
> and livelocks unbounded with `status="running"`, `last_error is None`, no drop hook and `start()`
> never returning; an external one arriving at an already-tripped chain is destroyed as
> `reason="chain_budget"` with `send()` reporting success. Containment only — the library routes its
> own completions onto the same queue regardless of what we do.
> **(3) Health signals are OUT-OF-PROCESS (CV-C43).** The round-7 rule ("progress counters, never
> `status` or `last_error`") is strengthened: no **in-process** watchdog may be the sole liveness
> detector for an order-path machine, because R8-01's livelock starves the very loop thread an
> `asyncio.wait_for` or a loop-resident supervisor task would run on. The supervisor is a separate
> process with a wall-clock deadline.
> **(4) Child bring-up is bounded by us, per child (CV-C44).** `start(children_timeout=)` is a
> **no-op** against a non-yielding plain-`def` child entry action and **suppresses its own WARNING**
> while failing (R8-03: 50 children x 1 s took 50.04 s under a 0.2 s bound, silently). Entry actions
> on `invoke`-bearing states are coroutines that yield at least once, and the factory bounds each
> child itself rather than relying on the library's aggregate `asyncio.wait`.
> **(5) Completion events are never accepted from a wire (CV-C45).** `DoneEvent` and `AfterEvent` are
> publicly constructible, carry no provenance marker and are exempt from `strict`/`onUnhandled`, and
> `restore_event` reconstitutes a *trusted* `DoneEvent` from an attacker-authored snapshot record
> (R8-05). The restore path strips every completion event from `pending_events` before
> `from_snapshot()`, in-flight completions are re-derived from the restored configuration, and the
> gateway rejects any externally submitted instance of either class.
> **Two restore clauses join CV-C23 and CV-C27'.** #186's `configuration`/`state_ids` agreement rule
> is **one-sided** — emptying either field short-circuits it — so our check asserts agreement in
> **both** directions (R8-08). And our envelope always writes `version >= 1` plus a `machine_hash`,
> and our restore path refuses `version: 0` or absent on **our** blobs, closing R8-06's residue on our
> side without depending on the library.
> **CV-C32 stands, and for the first time comfortably.** Round 8 inverted which lane is dangerous: the
> coroutine lane is now the healthy one on every battle track, and CV-C32 is exactly what keeps us off
> the plain-`def` path, where a service is uncancellable and an invoke is not unwound by `rollback`
> or by an `always` (R8-02).

> **Round-9 amendments (2026-09-22, ADR-0016 Amendment 9). CURRENT POSITION — this supersedes the
> round-8 block above wherever they differ.** The six keys are still unchanged. **The gate verdict is
> now ADOPT WITH CONSTRAINTS on all four lifecycle families, order path included** — the Blocker row
> is empty for the first time. Five things to read differently:
> **(1) CV-C43 RETIRES as a mandate.** Its entire ground was R8-01's livelock, which starved the very
> loop thread any in-process detector runs on. **#192 closes it at the root** — the priority lane now
> sheds by provenance, verified on both engines, both service kinds, and the real B18 (12/12 kill
> presses accepted, 0 shed, press pre-empts the chain). **`status` and `last_error` are liveness
> signals again.** The out-of-process progress counter drops from *the only permitted detector* to a
> **recommendation** we keep anyway, because it is good practice for an OMS regardless.
> **(2) CV-C31" RETIRES.** #193 fixed exactly its ground — a `def` invoke IS now unwound by `rollback`
> on the async engine. Keeping it would misstate the reason, which is how a constraint set rots.
> **(3) NEW: CV-C46 — the order path NEVER runs on `SyncInterpreter`.** Every order-path machine
> (B1-B9, B18) is built on the async `Interpreter` with an explicit `service_pool_size`. Ground:
> **R9-04**, where a `def` service armed by a transition an `always` rolls **forward** is still
> submitted — 3 of 6 lanes leak, and 2 of those 3 are sync-engine lanes. `production-characteristics.md:97`
> promises the opposite verbatim, and SCXML 6.4 agrees with the doc. Also covers R9-09's sync/async
> lap divergence and the `167` sync-only gate FAIL. **Together with CV-C32 this makes every leaking
> lane unreachable for us** — which is precisely why R9-04 is a constrained-adopt item, not a blocker.
> **(4) CV-C45 WIDENED, and this one is load-bearing.** The restore filter now matches the
> **serialised record** (`kind` in {done, error, after}) as well as the deserialised class, and the
> gateway rejection explicitly names `AfterEvent`. Ground: **R9-02** — `after` transitions are selected
> on the **public exported** `AfterEvent`, never on #195's `_EngineAfter`. The decisive vector is a
> forged `pending_events` record carrying **no `"engine"` flag**, which `_enqueue_restored` hands
> straight to the inbox, so **a 60-second timer fires instantly from untrusted snapshot data even at
> `strict: true`, with no API call at all.** A class-only filter would miss it. Credit where due: the
> **send-side** gate #195 built *does* correctly refuse a hand-built `AfterEvent` under `strict` — we
> re-ran that rather than inheriting the claim, and our own register had overstated it.
> **(5) Snapshots are TRUSTED INPUT and we now sign them (CV-C23 clause).** Control-plane snapshots
> carry an **HMAC tag** verified before `from_snapshot()`, and any payload declaring `version < 1` or
> omitting `version` is refused outright. R9-05 is a documented wrapper obligation, not a library
> defect — XState v5 `createActor({snapshot})` trusts persisted snapshots too and SCXML specifies no
> persistence model — so this closes on our side without waiting on upstream.
> **Clauses that ease.** #186 is now two-sided, so **CV-C27' becomes defence in depth** rather than
> the only check; #199 closed the start-hook window, so **CV-C40** likewise; #194 bounds each child
> and always logs the overrun on both lanes, so **CV-C44** likewise. None are deleted — they are
> re-grounded, and a re-grounded constraint must say so or the next reader retires it for the wrong
> reason.
> **CV-C42 stands on NARROWER ground.** R8-01's livelock is fixed, but a **delayed** self-`send` cycle
> is charged to nothing and tagged *external* by #192, so it can never be shed (R9-06). The outright
> ban survives on that basis alone.
> **CV-C35 stands and is re-grounded.** R9-03 was **refuted outright** (its "starvation" was an
> artefact of reading a counter after a fixed `sleep(1.0)`; polling to drain gives 500/500 applied with
> both queues at zero) — but the chart shape it used is exactly what CV-C35 forbids and what the
> library documents as invalid. The constraint was right for a reason the refuted finding got wrong.
> **The binding constraint on our order path is now OURS.** **C-04** (B16 elevation survives
> `LOGOUT`/`REVOKE`) and **C-07b** (B18 kill switch bricked by a guard-denied `RELEASE`) are the only
> Blockers of any kind still open in this study. Both are catalogue defects on **any** runtime, on
> machines the library has already cleared. Nine rounds of upstream verification have arrived here.
> **Still outstanding on our side, unchanged and now the critical path for two machines:** C-04 and
> C-07b (both Blockers **on any runtime**, ours, on control machines the library has already cleared),
> C-07 (the explicit `halted` states CV-C31 promised on B16-B20 and nobody wrote), CD-01, C-06, C-05,
> CV-B4-01, OUR-B11-01, OUR-B14-01/02, OUR-B15-01. Tracked in `E50-T14` / `E50-T16`.

> **Round-7 amendments (2026-09-20, ADR-0016 Amendment 7). Superseded by round 8 above; retained for the record.** The keys above are unchanged; three
> things about *how to read them* are not.
> **(1) `maxIterations` is inert for a new and more specific reason** — see the annotation above.
> The containment is **CV-C38**: no machine may contain an invoke cycle (two invoking states that can
> target each other on success, or an `invoke.onDone` that can re-enter its own source) **unless a
> bounded attempt counter in context gates the re-entry**. Enforced by linter rule **CV-LINT-XS16**,
> plus a contract test per machine carrying an `invoke`. This is what lets B19 stay in the GO set and
> what keeps B18 out of it.
> **(2) `priority=True` is forbidden outside wrapper code (CV-C42)** and the gateway never sets it on
> an externally originated event: upstream R7-02 charges an *external* `send(priority=True)` to the
> chain budget and sheds it as `reason="chain_budget"` — 751 of 1 500 in our measurement, with the
> control run (same load, no `priority=True`) dropping zero, `last_error` reading `None` throughout.
> Containment only; the loss is upstream.
> **(3) Three snapshot and lifecycle rules join the block.** **CV-C39** `await start()` is always
> bounded (`asyncio.wait_for`); nothing may `await start()` bare, because an invoked child's slow
> entry action hangs it unboundedly with `status="running"` (R7-03). **CV-C40** no snapshot may be
> taken before the factory has observed the machine settled after `start()` — the async initial-entry
> window is explicitly excluded, because the library's mid-step refusal is inert there and 720/720
> torn blobs land in exactly that window (R7-05). **CV-C41** snapshots capture the **root only**;
> child-actor state is reported upward by explicit `sendTo` into parent context and persisted from
> there (R7-07, R7-08).
> **CV-C37 is retired** — #171 fixed the children-ready race, and `_actors` is populated the instant
> `start()` returns. It is replaced by its inverse, CV-C39, because the same fix introduced the
> unbounded wait.
> **`Receipt.denied` is trustworthy again (W-04a retired)** — #170 makes
> `(denied, error, deferred, changed)` injective on both engines. But **W-04b stands**:
> `onUnhandled: "defer"` still outranks the `guard_denied` disposition, so a guard-refused amend is
> replayed later against a changed world unless the wrapper drains denied events from the defer
> buffer. And because `denied` is asymmetric across machines for the same class of rollback outcome
> (B15 `True`, B14 `False`), **`error is not None` remains the only usable "did my transition land?"
> test.**
> **Health signals:** `status` and `last_error` are **not** liveness signals on the async engine —
> R7-01, R7-03 and the R7-04 residual all present as `status == "running"` with `last_error is None`,
> and R7-15 shows `last_error` is set *after* the drop hooks and cleared by the next success. Every
> supervisor we ship keys on a **progress counter**.
> **Still outstanding on our side, unchanged:** C-07 (the explicit `halted` states CV-C31 promised on
> B16-B20 and nobody wrote), C-04 and C-07b (both Blockers **on any runtime**, ours), CD-03, C-06,
> CV-B4-01, OUR-B11-01, OUR-B14-01/02, OUR-B15-01. Tracked in `E50-T14` / `E50-T16`.

> **Round-6 amendments (2026-09-20, ADR-0016 Amendment 6).** `"fail"` is **re-permitted** — #145 makes it
> safe (`status="stopped"`, configuration cleared, `TransitionFailedError` retained, and `from_snapshot`
> refuses the halted blob) — and `"rollback"` is now the policy that needs guarding on the order path.
> This is the exact inversion of the round-5 position, and it is driven by measurement, not preference.
> Three structural rules join the block: **CV-C35** no `always` may descend into a child carrying an
> `invoke`, nor target an ancestor of its own source (upstream R6-01/R6-02 livelock the async engine on
> that shape); **CV-C36** every `send_threadsafe` future is read (R6-05 sheds silently under load);
> **CV-C37** the factory awaits `children_ready()` before handing out a machine, because `await start()`
> returns ~13 ms before the initial `invoke` children are addressable (R6-11).
> **CV-C30 is retired** — #142/#143 landed one legality predicate on both snapshot sides, so parallel
> regions are safe on the order path again.
> **Still outstanding on our side (C-07):** CV-C31 promised explicit `halted` states on B16-B20 and they
> were never written, so a failed `locked` entry currently rolls B20 back to `clear` (tag
> `trading_allowed`) with no record. Tracked in `E50-T16`.

Only the first two vary, and only by machine role:

| Value | Machines | Why |
|---|---|---|
| `actionErrorPolicy: "fail"` **re-permitted (CV-C31 retired, 2026-09-20)** | B8, B17, B18, B20, **and any order-path state carrying an `invoke` with a raisable entry action (CV-C31′)** | #145 verified on both engines: halts with `status="stopped"` and a cleared configuration, retains `TransitionFailedError`, round-trips through a snapshot, and the halted blob is refused by `from_snapshot` with `InvalidConfigError`. R5-12 (reverts to source, bricks the interpreter) is dead. Pair with an explicit `halted` state entered from `on_transition_failed` — **these states are still missing (C-07, `E50-T16`)**. |
| `actionErrorPolicy: "rollback"` | all others | Restore context and configuration; the transition never half-commits. **Not safe on a state that carries an `invoke` and can raise in an entry action** — upstream R6-03 makes that an unbounded, silent re-invocation loop on the async engine. |
| `onUnhandled: "error"` | **none** — removed from B13 `ws_conn` and B14 `book` (E50-S02, 2026-10-01: the §1.3c mandatory block is unconditional, `CV-LINT-POLICY`); **no longer B18** | Control machines have a closed event vocabulary; an unexpected event is a bug, not backlog. **Removed from B18 (C-07b):** a guard-denied `RELEASE` is terminal under this policy, i.e. the kill switch is bricked by a wrong button press. Note also R6-08: the kill is visible via `status`/`.error`/`on_error` but the caller's `Receipt` is byte-identical to a no-op. |
| `onUnhandled: "defer"` | all others | An event arriving before its handler is armed is held at the **head** of the queue and replayed in order. |

Three consequences that shape how the machines below are written:

- **`rollback` is a context + configuration transaction, not an effect transaction.** A `sendTo` or `raise` emitted by an *earlier* action in the same list survives the rollback. So **the action that talks to the outside world is always last in its list**, or lives on the `entry` of a state that is only reached once the transition has committed (constraint CV-C02). Check this whenever editing an `actions` array below.

  > **Narrowed on `main` @ `5327ba6` (pre-0.8.1), but unchanged as a rule.** Rollback now also **withdraws self-`raise`d events** queued by the failed action list — verified in eight hostile shapes including parallel regions and child actors. It still **cannot un-send a `sendTo`** (that effect has left the machine), and the library says so explicitly. CV-C02 is therefore unchanged: keep outward effects last, or on the committed state's `entry`.
- **No event may be named `error.*` or `done.*`.** Those namespaces are reserved by the engine: such names are invisible to a `"*"` handler and exempt from `onUnhandled: "error"` (constraint CV-C15). Enforced by the event-name gate `E50-T05`.

  > **Re-scoped on `main` @ `3c527b0` (unreleased 0.8.1), and narrowed.** #79 replaced the name-based exemption with provenance, so a *user-sent* `done.review` or `error.validation` is now fully visible to `"*"`, trips `onUnhandled: "error"`, and is rejected by `strict` — **case variants included**. The blanket `done.`/`error.` ban is therefore over-broad and its case-insensitivity requirement **retires**.
  >
  > **The rule becomes:** no CandleViewer event may be named with any prefix in `ENGINE_EVENT_SHAPES` — **`done.invoke.`, `done.state.`, `error.platform.`, `after.`, `xstate.`, `___xstate`**. These are the only names `models.is_known_event` still exempts **by name**, so a typo inside them is still silent under `strict` (`after.party` — not even a well-formed `after.` shape — is accepted undeclared). **`E50-T05` must be re-specified to this list, case-sensitively**; the library matches case-sensitively and so does the hole.
- **House rule A3 is retired.** The `` handler and the `drain_deferred` entry action that used to appear on every transient state are gone — `onUnhandled: "defer"` is the library's own, snapshot-durable buffer. A3 remains in the table above as a historical record; the live rule is this block.

  > **Known inconsistency, tracked as `E50-T09`.** The A3 scaffolding (`_deferred` in `context`, the `"*"` defer handler on entry) is **still present inline in all twenty contracts below**. It was left in place deliberately rather than stripped mechanically, because removing it touches every transient state in the document and must be done alongside the conformance harness (`E50-T03`) so the before/after traces can be proved identical. Until `E50-T09` lands, read the scaffolding as **dead but harmless** — with `onUnhandled: "defer"` set, the runtime holds the event before any `"*"` handler is consulted, so the inline handler never fires. Do **not** copy it into a new machine.

`spawnBlockingTimeout` is carried by every machine for uniformity, and is load-bearing only on the machines that use `spawn_blocking_*`.

Enforcement is CV-LINT-XS1…XS14 in the machine-definition linter (`E29-T10`), plus a runtime assertion in `cv.statechart.factory` — the only place an interpreter may be constructed. Full rationale per key: `docs/research/xstate/17-reeval-0.8.0-verdict.md` §4, as amended by `22-verify-main-verdict.md` §4.5 and `26-verify-3c527b0-verdict.md` §5.6.

> **Verified unchanged on `main` @ `3c527b0` (unreleased 0.8.1, PR #83), 2026-09-18.** **No library default changed on that commit either**, so the six-key block above remains normative **verbatim** — still no edit required, across two verification passes. Everything that changed is *around* it, never in the machine JSON:
>
> - **Four constraints are added**, all enforced in `cv.statechart`, not in a machine definition. **CV-C19** — never construct `Event(system=True)`, and never trust `is_system_event()` / `Event.system` as a routing or trust boundary: it is a public, user-settable dataclass field that bypasses `strict`, `onUnhandled` and `"*"` (**CV-LINT-XS13**). **CV-C20** — `cv.statechart.persistence` owns the mailbox across a snapshot boundary: quiesce before snapshotting (`queue_depth == 0 and deferred_count == 0`) and reconcile every `pending_invocations()` entry on restore, because the library's snapshot **silently drops** pending `ErrorEvent`/`DoneEvent` and **silently loses** event provenance. **CV-C21** — every `onError` action branches on `isinstance(event, ErrorEvent)` and reads `event.error`; never `.data`, never `event.type.startswith("error.")`, never `event.payload.get(...)` on an error-shaped event (**CV-LINT-XS14**); `escalate` is the exception and still carries its error under `payload["error"]`. **CV-C22** — no global `-W error::DeprecationWarning` in CI while the library trips its own `ErrorEvent.data` deprecation.
> - **CV-C06's `deferred_count` clause is WITHDRAWN AS UNSOUND** — see below.
> - **CV-C15 is re-scoped and narrowed** — see §1.3's event-name bullet.
> - **Capacity planning changes**: an idle invoked child now costs **one** asyncio task, not two (`children + 1`, pinned by the library's own tests). Any budget computed from `2 × children` can be revised.

> **⚠️ The CV-C06 deferred-receipt clause above is withdrawn — it does not work.** Re-tested on `3c527b0`: at the caller's `await` point, `interpreter.deferred_count` reads **`0`** for the deferred case **and** for the genuine no-op. The observation point at which it reads `1` is inside the macrostep, where a caller cannot stand. `test_receipt_is_inconclusive_when_deferred` cannot be written as specified.
>
> **The replacement rule is a prohibition, not a mitigation:** *a `send(wait=True)` receipt reading `changed=False, error=None` is **inadmissible** as a gate on any machine configured `onUnhandled: "defer"` — which is every machine below.* **No order-path statechart ships** until either the library's receipt learns the defer disposition, or `cv.statechart` obtains an out-of-band discriminator (a correlated `on_event_deferred` hook), which the library does not currently expose. Enforced by **CV-LINT-XS9** (re-purposed) and by the absence of an order-path machine in the registry.

> **Verified unchanged on `main` @ `5327ba6` (pre-0.8.1), 2026-09-18.** **No library default changed**, so the six-key block above is normative **verbatim** — no edit was required. Three things did change *around* it, none of them in the machine JSON:
>
> - **Two linter clauses retire.** **CV-LINT-XS9**'s fresh-`Event` rule is gone (the library now detaches the queued envelope, so reusing an `Event` across concurrent `wait=True` sends is safe), and the gateway's duplicate `strict`/`event_schemas` validation is gone (the library now runs it on the calling thread before queuing). Delete both; keep their regression tests.
> - **Three constraints are added**, all enforced outside the machine JSON: **CV-C16** — no action may call `send()` on its own interpreter (use the `raise` built-in; it is the only shape the runaway budget bounds on the async engine), **CV-LINT-XS11**. **CV-C17** — no machine relies on a `raise` chain deeper than 1,000; the cut is silent. **CV-C18** — one `MachineLogic` per `create_machine()` call, one spelling per implementation, `MachineLogic(strict=True)` in the factory, **CV-LINT-XS12**.
> - **CV-C06 gains a clause that changes how callers read a receipt**, not how machines are written: a `send(wait=True)` receipt with `changed=False, error=None` must be treated as **inconclusive** while `interpreter.deferred_count > 0`. With `onUnhandled: "defer"` mandated on every machine below, a legitimate event arriving one microstep early returns a receipt that denies its own transition. Handled once in `cv.statechart`; no per-machine change.

> **Round 14 — verified on tag `v0.9.1` = `45bb7f3`, 2026-09-24. ROW 8. NO NEW MANDATORY KEY; the seven-key block stands.** Round 14 makes four changes.
> 1. **Chart fixes specified and pending merge (Blockers, ours).** The R13-13 (B16 root-hoist to terminal `elevation.dead` plus deletion of `elevated.on.REVOKE`), R13-14 (B18 `onUnhandled:'defer'` plus an ordered unguarded auditing RELEASE fall-through) and R13-15/16 (B11 event-aware guard plus a `degraded.on.GAP_DETECTED` handler) fixes are **re-proven green on 0.9.1 in both spellings**. They are tracked here as *pending merge into the chart JSON*. The charts are not live-order-eligible until they land.
> 2. **B8 (B610-OC-CD03, High, ours).** The naked↔verifying loop trips the chain budget. Add a bounded `verify_attempts` counter in context, guarded, routing to `error` when exhausted.
> 3. **`CV-C68` (new).** Every `events.re_mint()` call goes through `cv_re_mint()` with payload-only overrides. `type=`/`src=` are banned (R14-01).
> 4. **`CV-C65′`/`CV-C66′`.** Shutdown is drain, then journal, then `get_persisted_snapshot()`, then stop. `on_interpreter_start` is permitted for telemetry, branching on `restored_from_snapshot`.
>
> Source: `docs/research/xstate/79-r14-final-readiness-verdict.md`.

> **Round 13 — verified on tag `v0.9.0` = `91bd979` (tree `main` @ `e3a1f22`), 2026-09-23. NO NEW MANDATORY KEY — the seven-key block stands verbatim. THREE constraints RETIRE (the most in any round), three are new, and the single biggest timing rule in this catalogue is one of the retirements.**
>
> **TIMERS — `CV-C12`, the `after` ban standing since round 4, RETIRES to `CV-C12′`, and the reason is that OUR INSTRUMENT WAS WRONG, not that the library changed.** `bench_c_timers.py` does not reproduce upstream's "N busy machines" loaded-timer scenario at all, so **five consecutive rounds of "174.4 ms against a ≤100 ms bar, still missed" were five rounds of measuring a question nobody asked**, while the largest architectural constraint in this catalogue stood entirely on the number. Re-run on **THEIR** `benchmarks/production_characteristics.py --quick` §2 (`after: 10` lateness at 500 busy machines), ten runs on an idle host: **min 52.1 · p50 53.4 · p99 55.8 · max 55.8 ms — every run under the 100 ms bar, ~44 ms headroom, spread 3.7 ms**, the tightest this programme has recorded. Round 12 read ~110 ms median on the same unchanged tool and three round-13 submissions disagreed with each other (71.0 / 87.5 / 97.9); that resolved to **host load, not library variance**. **`CV-C12′`: `after` and `raise(delay=)` are PERMITTED for coarse timeouts and for deadlines carrying ≥250 ms of tolerance.** Three things do **not** move with it, and the retirement must not be read as a general relaxation: **(1) hard sub-100 ms deadlines and ALL algo timing — TWAP intervals, chase repricing, iceberg release — stay on the external `MonotonicScheduler` with absolute `*_us` deadlines in context, unconditionally.** **(2) The relaxation is CONDITIONAL on re-measuring BENCH-6 on TARGET hardware** (Phase-3 gate P3-G6) — ours is one Windows dev host, and the library's own note says your macrostep cost sets your budget; until that gate is green the linter narrows from "ban `after`" to "ban `after` on any state tagged `x-hard-deadline`" but production keeps the old rule. **(3) `CV-C55` (no `delay` below 10 ms in either spelling) and `R11-W-1` (every chart deadline carries a stable `send_id`) continue to apply to both spellings.**
>
> **ACTIONS — `CV-C64` RETIRES to a lint (`CV-C64′`), and this catalogue again paid nothing for a library change because of a rule it already had.** #225 replaced the inheritable `ContextVar` self-send predicate with **task identity** (`_action_tasks`). The old predicate meant any task spawned inside an action inherited `_ACTIVE_ACTION_OWNER` **for its entire life** and was refused as a self-send even 300 ms after the machine went idle — that inheritance was `CV-C64`'s whole ground, and it is now closed. A worker outliving its action and the documented `asyncio.ensure_future(i.send(..., wait=True))` hand-out are now **ordinary external traffic** (`worker_send='ok'`, machine advances, `chain_trips == 0`), while the **genuine in-step await is still refused by the library** with `ReentrantWaitError`. **No catalogue chart changes behaviour because of #225** — verified positively, not assumed. The prohibition drops to a lint, and the lint **stays**: because the hand-out is legal again, the old blanket ban no longer incidentally catches a *hand-written* reentrant await. **`CV-C25`** (no external `send()` from inside an action — gateway queue only) is **untouched**, and is the rule that made #219 and #225 both cost us nothing.
>
> **NEW: `CV-C67` — register coroutine functions DIRECTLY, never behind a sync `def` wrapper.** This comes from **`R13-21`, a bug in our own harness**, and it is the most instructive thing in the round. Our contract `Stub.mk_a` wrapped every action implementation in a plain `def` for uniformity — correct for sync impls, but for an `async def` action it **drops the returned coroutine**, which is then never awaited and **silently never runs**. No error, no warning, no failed assertion. It had been **masking the #225 probes**, which read `exc=None` where they should have read `ReentrantWaitError`. It surfaced only under `-W error::RuntimeWarning` (`coroutine ... was never awaited`). **Any house action registry must register coroutine functions directly, and the contract runner runs under `-W error::RuntimeWarning` from now on.**
>
> **NEW: `CV-C65` — the shutdown wrapper persists via `get_persisted_snapshot()`, NEVER `drain_pending()`.** From **`R13-01`** (library, High, the single row between us and unconstrained adoption): async `drain_pending()` reads only `_event_queue` and never `_priority_queue`, while the sibling `_snapshot_pending_events()` deliberately includes the lane — two documented durability views of the same interpreter that disagree, with the lossy one being the one whose docstring promises *"every accepted-but-unprocessed event"*. `_teardown()` then clears the lane, so the documented drain → persist → `stop()` recipe **permanently destroys** fired `after` timers, invoke completions and `send_priority()` traffic. Any `drain_pending()` result is a **lower bound**, usable for telemetry only. Enforced by a lint plus a startup assertion, with `tests/xstate_contract/test_shutdown_drain.py` as the passing test row 6 requires.
>
> **NEW: `CV-C66` — no per-process bring-up work may hang off `on_interpreter_start`.** From **`R13-02`**: the hook **never fires on a snapshot-restored interpreter**, on either engine, via either registration route, because both `start()` implementations `return self` from the resume branch above their plugin notification loop. `on_interpreter_stop` still fires, so a lifecycle plugin observes an **unbalanced stop-without-start** — which is a stronger failure mode than an absent hook, because anything holding a span, a correlation id or an audit "actor came up" record either leaks or under-reports. Bring-up happens at construction/restore time in our own wrapper.
>
> **RESTORE — one API change this catalogue must actively adopt (`R13-W1`).** Every restore site passes **`from_snapshot(..., minimum_version=3, plugins=[CvErrorHooks()])`**. Plugins passed via `plugins=` are registered **before** persisted events are admitted; a `.use()` after `from_snapshot` is structurally blind to exactly the strict/schema refusal it exists to catch (a dropped deadline). Verified exactly-once over 320 property cases. **Caveat per `CV-C66`:** this route carries `on_invalid_event` only, never the lifecycle hook. **`CV-C63` NARROWS** — #226 makes `chain_trips` / `last_chain_error` real v3 snapshot fields, so the wrapper no longer carries them in its own envelope; what survives is the **type** rule (`R13-07`): `RestoredError` subclasses `XStateMachineError`, **not** `RunawayChainError`, so a supervisor's `isinstance` check is correct live and **silently false** after a restart — **read `chain_trips > 0`, never `isinstance` the latch.**
>
> **SEVEN CATALOGUE DEFECTS ARE OURS, AND THE ENGINE IS SPEC-CORRECT IN EVERY ONE.** This is the round the board inverted: the library carries 0 Blockers and 1 High; **we** carry 3 Blockers and 1 High, all config-only, all with fixes proven green 11/11 in both spellings on this exact build. **`R13-15` (B11, BLOCKER)** — `degraded.on.STREAM_HEALTHY`'s first arm carries guard `all_streams_healthy` **and** actions `[mark_stream_healthy]` on the same arm; XState v5 and SCXML both evaluate a transition's guard against the context **before that transition's own actions run**, so the guard reads a map in which the very stream the event announces healthy is still `False`, the recovery arm is never selectable, and `unsubscribe_and_flush` never runs. Same class recurs at `recording/degraded REASON_REMOVED`. **Remedy: event-aware guards in our code.** **`R13-16` (B11, HIGH)** — `degraded` defines no `GAP_DETECTED` handler and root `onUnhandled:'defer'` swallows it, so **gap telemetry goes dark precisely during the degraded window** and the operator sees a *healthier* 24 h number the worse the feed gets. **`R13-13` (B16, BLOCKER)** — all four revocation events fail to drop the parallel `elevation` region, and a later `STEP_UP_OK` **re-elevates a revoked session**; the fix needs **both** the root hoist to a terminal `elevation.dead` **and** deletion of the region-level `elevated.on.REVOKE` handler, because the deeper handler outranks the root arm (round-12's correction, re-proven). **`R13-14` (B18, BLOCKER)** — our own opt-in root `onUnhandled:'error'` makes a guard-denied RELEASE **fatal**, and the later authorised RELEASE is then accepted by `send()` but **dropped**: the kill switch is permanently bricked. XState v5 and SCXML treat a guard-denied event as simply untaken and have **no fatal-unhandled mode**, so upstream semantics argue against our configuration. **Fix: `onUnhandled:'defer'` plus an ordered unguarded auditing RELEASE fall-through — the shape B13/B17/B20 already use.** **`R13-17` (B3, MEDIUM)** — `pending.always`'s third arm is **unguarded**, so the leg chart transitions to terminal `leg.error` **during initial entry**, `status=done` before any event is sent. **`R13-18` (B16, MEDIUM)** — the `elevated → elevated` re-enter arm on `STEP_UP_OK` does not audit, so two successful step-ups record one `audit_step_up`. **`R13-19` (B19, MEDIUM)** — `OPERATOR_RESOLVED` is deferred rather than handled in `reconciliation.stale_lockout`, so **an operator cannot clear a stale lockout**.

> **Round 12 — verified on `main` @ `de2da4e` (unreleased 0.8.1, merge of PR #223), 2026-09-23. NO NEW MANDATORY KEY — the seven-key block stands verbatim. Two constraints RETIRE; two are new; the timing rules are the only thing that moves.**
>
> **Gate: ADOPT WITH CONSTRAINTS, decision-table ROW 8** (up two from round 11's row 6; ADR-0016 Amendment 12). All five round-11 fixes (#218–#222) verified FIXED on both engines and both service spellings; library board **0 Blocker · 0 High · 3 Medium · 6 Low**.
>
> **The `strictConfig` key gains its full value this round, and the result is retroactive.** #220 turns the round-11 root-dict scan into a **full recursion** — nested `states`, parallel regions, `on` / `always` / `after` / `onDone` transition bodies, `invoke` entries and their `onDone` / `onError` — with per-level known sets and **path-named findings** (`session.auth: 'entyr' (did you mean 'entry'?)`). Round 11 noted the key's value was "~95 % unrealised until the recursion lands". **It has landed, and all twenty catalogue charts build clean under it — 0 warnings, both lanes.** Both controls are positive: planted nested typos are refused **40/40** with path-named findings, and a full valid-key grammar (including `x-` / `meta` / `description` / `tags` at every level) is accepted with **0** findings. **Therefore: nothing in B1–B20 was ever silently dropping an entry action or a transition.** That could not be established before #220 existed, and it validates every contract result from rounds 4–11. **One hole remains (Q-5): the recursion does not descend into an inline-machine `invoke.src`** — so **CV-C57**, the wrapper's own recursive check, **stands, re-grounded on exactly that hole**. No catalogue chart uses the inline form today.
>
> **TIMERS — the round's only rule change, and it is a RETIREMENT rather than a relaxation.** **CV-C47 and CV-C61 RETIRE.** #218 closes the unbounded `_timer_handles` leak **at the mechanism**: a 200-beat `raise(delay=)` heartbeat holds **peak 1 handle** on every engine/kind cell, a 500× arm/cancel storm peaks at **0** with no double-release, `stop()` releases, and the soak that read **+753 MB** last round reads **RSS Δ 0.00 MB over 93,168 beats** at `handles_max_per_machine = 1`. Both of CV-C47's grounds are now closed — R10-03 by #212, R11-04 by #218 — and a constraint with no surviving ground is rot, not a safety margin. **But three things do NOT move, and the retirement must not be read as a general relaxation:**
>
> 1. **CV-C12 STANDS UNCHANGED — `after` (and now `raise(delay=)`, which #212 made its equal) is permitted ONLY for coarse, non-critical timeouts where seconds of lateness is tolerable.** Its ground is **BENCH-6**, last measured at **174.4 ms against a ≤100 ms bar** and now **UNMEASURED FOR FIVE CONSECUTIVE ROUNDS**. #218 fixed a handle-**retention** defect and says nothing about **drift under load**; retiring CV-C12 on its strength would answer a timing question with a memory measurement. **All algo timing — TWAP intervals, chase repricing, iceberg release — stays on the external `MonotonicScheduler` with absolute `*_us` deadlines in context.**
> 2. **`raise(delay=)` is not thereby recommended**, merely no longer separately banned. **Nothing becomes newly legal for algo timing.**
> 3. **CV-C55** (no `delay` below 10 ms in either spelling) and **R11-W-1** (every chart deadline carries a **stable `send_id`**) continue to apply to both spellings. The `_timer_handles` gauge **survives CV-C61's retirement as telemetry** — it is the instrument that would detect a recurrence.
>
> **ACTIONS — a BREAKING CHANGE upstream that cost this catalogue nothing, and the reason it cost nothing is a rule we already had.** #219 makes an action that awaits `send(..., wait=True)` on its **own** interpreter raise `ReentrantWaitError` instead of deadlocking (the sync engine refuses the same shape for parity). **Zero catalogue actions required a change — verified positively, not assumed:** 0 of 573 corpus scripts and 0 of 20 charts contain the shape. That is **CV-C25** (no external `send()` from inside an action — gateway queue only) doing its job since round 5. **NEW CV-C64** makes the audit standing and widens it: the **documented escape hatch** `asyncio.ensure_future(i.send(..., wait=True))` is **also unsafe** (DE-L1) — the guard rides an **inheritable `ContextVar`**, so a task spawned inside an action keeps `_ACTIVE_ACTION_OWNER` for its whole life and is refused even 300 ms after the machine goes idle. A helper that must talk to the machine goes through the **gateway queue**, or is spawned with a **fresh `contextvars.Context()`**. A **`def`** action calling `send(wait=True)` gets an unawaited `_Awaitable` — no error, no warning, no receipt — so **the lint covers both kinds, and it must run BEFORE the dependency bump.**
>
> **SUPERVISION — #222 gives us the API CV-C59 asked for, plus one durability gap that is ours.** `last_error` remains the **per-step** read it always was (by design); chain stickiness now lives in `interpreter.chain_trips`, the `interpreter.last_chain_error` latch, `clear_chain_error()` and `PluginBase.on_chain_budget_exceeded` (fires exactly once per trip, settle-budget trips included; `on_event_dropped(reason='chain_budget')` **precedes** it, so either is safe to key a supervisor on). **`chain_trips == 0` on every happy path across all twenty charts, both lanes.** **NEW CV-C63:** the latch is **process-local — not a snapshot field** — so read `chain_trips` and `last_chain_error` **before** `get_persisted_snapshot()` and carry them in the wrapper's own envelope, or a restart silently resets "this machine discarded work" to zero.
>
> **PERSISTENCE — one re-label that matters.** `minimum_version=3` (CV-C52) is **HYGIENE, NOT A SECURITY CONTROL**: R12-02 demonstrates it by refusing a forged `"version": 2` blob while leaving an equivalent **v3 verbatim write** untouched — both reach the same state. **The boundary is CV-C53, the MAC'd journal at rest.** `from_snapshot` documents the snapshot as **trusted input** and `machine_hash` as *"a fingerprint, not a MAC"*. **CV-C49′** (never re-persist an un-`start()`ed interpreter) is **retained as defence in depth** even though #221 closed its ground at 640/640 byte-identical records across four compaction hops.
>
> **OUR OUTSTANDING CATALOGUE DEFECTS — all config-only, and now the ONLY things blocking the order path.** Ticketed in **E50-T43**.
>
> - **R12-13 (B16, Blocker, open SEVEN rounds)** — elevation outlives the session. `LOGOUT` / `IDLE_DEADLINE` / `ABSOLUTE_DEADLINE` leave `["session.auth.revoked", "session.elevation.elevated"]`, and `REVOKE` lands in `normal` where a later `STEP_UP_OK` **re-elevates a dead session**. 12/12 lanes fail across both engines, both spellings and four kill events. **CORRECTION TO THE PRESCRIBED FIX, recorded because it would otherwise ship wrong: the root hoist to a final `elevation.dead` state fixes only 9 of 12 lanes, because the deeper `elevated.on.REVOKE` handler OUTRANKS the root arm. The region-level `REVOKE` handler must ALSO be deleted.**
> - **R12-14 (B18, Blocker, open SEVEN rounds)** — one **guard-denied** `RELEASE` under root `onUnhandled: "error"` makes the machine fatal (`status='error'`), and the subsequent **authorised** `RELEASE` is accepted by `send()` but **silently dropped**: `bricked: true`. The Amendment-6 removal of `onUnhandled: "error"` from B18 **still has not landed in `ka_killswitch`**. Fix: `onUnhandled: "defer"` plus an ordered **unguarded auditing `RELEASE` fall-through** — proven 6/6 and 13/13 on both engines and both spellings.
> - **R12-15 (B19, High)** — `stale_lockout.on` has only `RECONNECTED` while `divergent` carries an `OPERATOR_RESOLVED` arm, so under `onUnhandled: "defer"` the operator event **parks forever** and a venue that never reconnects leaves the account `account_locked` / `critical` **until process restart**. Fix verified in both lanes: add `stale_lockout.on.OPERATOR_RESOLVED → idle` with `unlock_account`.
> - **A general rule falls out of R12-14 and R12-15 together, and it belongs in every control chart's review:** `onUnhandled: "error"` **bricks** on a guard denial, and `onUnhandled: "defer"` **parks forever** on a missing arm. Neither policy is free. **Every operator-recovery event must have an arm in EVERY state it must be honoured in**, and every state whose only arm is guarded needs an **ordered unguarded fallback**.
>
> Full reasoning, the decision-table walk, the constraint recomputation and the mandatory config block: `docs/research/xstate/69-r12-final-readiness-verdict.md` §4/§7.

> **Round 11 — verified on `main` @ `c78ce99` (unreleased 0.8.1, merge of PR #217), 2026-09-22. ONE NEW MANDATORY KEY — the six-key block becomes SEVEN.**
>
> ```jsonc
> "strictConfig": true,              // #216, NEWLY MANDATORY. Set this key in the JSON *and* pass
>                                    // strict_config=True to create_machine. Either alone raises
>                                    // InvalidConfigError on an unknown key (both spellings verified,
>                                    // and either one alone is sufficient) -- we set BOTH, because the
>                                    // two switches are read at different layers and a future release
>                                    // could diverge them.
>                                    //
>                                    // WHAT IT BUYS: an unknown top-level key now raises instead of
>                                    // being silently accepted, with a did-you-mean hint that named
>                                    // the right key 47/47, 120/120 and 200/200 in three independent
>                                    // mutation harnesses. Applied across all 20 machines below it
>                                    // found ZERO unknown root keys, with a positive control
>                                    // confirming the check was live rather than vacuous. This
>                                    // retires the LAST use of R10-07's "a TYPO in any top-level key
>                                    // is accepted silently" -- at the ROOT.
>                                    //
>                                    // SCOPE WARNING, AND IT IS THE LARGER HALF (R11-07):
>                                    // validate_top_level_keys iterates the ROOT DICT ONLY, while
>                                    // KNOWN_MACHINE_KEYS is overwhelmingly a list of STATE-level
>                                    // names (entry, exit, on, after, always, invoke, onDone,
>                                    // initial, type, states). A misspelled structural key INSIDE a
>                                    // state is accepted with NO RAISE AND NO WARNING under every
>                                    // strict setting -- 0/120 nested mutations caught, 7/7 and 30/30
>                                    // silently accepted in two other harnesses.
>                                    //   {"states": {"a": {"entryy": [...], "onn": {...}}}}
>                                    // builds a CLEAN machine with zero entry actions and zero
>                                    // transitions. Verified behaviourally: the entry action runs 0
>                                    // times (expected 1) and the machine does not move on the event
>                                    // that should move it.
>                                    // Our typo surface is ~200 state nodes, not ~10 root keys, so
>                                    // this key closes roughly 5% of our actual exposure.
>                                    // -> CV-C57: the wrapper runs its OWN RECURSIVE key check over
>                                    //    every state node at build time. NOT OPTIONAL. It does not
>                                    //    exist yet and is the least-defended item on the board.
>                                    // Nested POLICY misspellings (actionErrorPolicyy under a state)
>                                    // are inert either way -- policies are read from the root only.
>                                    // The STRUCTURAL keys above are the real exposure.
> ```
>
> **The other six keys are normative VERBATIM — no edit required for an eleventh round.** No library default changed at this commit. What changed is the *justification* behind three annotations, and per ADR-0016 Amendment 11 / standing amendment 20 a constraint carried on a dead justification is folklore, so each is restated:
>
> - **`strict: true` — the annotation changes, the value does not. `strict` IS NOT AND NEVER WAS A SNAPSHOT BOUNDARY.** Two Blocker/High findings were filed this round against restore-path provenance (the `"version": 2` downgrade minting `engine: true`; `scheduled_sends` bypassing the strict check) and **both were refuted on controls**: an attacker who can write the blob reaches the same target state via `state_ids`/`context` **with no event forgery at all**. `from_snapshot` is a **documented trusted-input boundary** (#205 applies `state_ids`/`configuration`/`context` verbatim; `machine_hash` is explicitly *not a MAC*). **The boundary is the HMAC tag our envelope writes over the whole blob (CV-C53)** — not `strict`, not `minimum_version`. Residual R11-02 (Low): `scheduled_sends` restores without the *reported* refusal #214 promises, so a chart upgrade that undeclares an event yields silent delivery → **CV-C54** (reconcile persisted vs admitted record counts).
> - **`maxIterations: 500` — three notes, all new. (a) It NEVER bounded delayed work, on any commit.** #212 gives `raise(delay=)` the same exemption `after` always had; our own claim that this was an escape hatch was **refuted** on an `after:` control behaving identically at the same delays. Do **not** treat `maxIterations` as a liveness bound for anything timer-driven. **(b) TWO PLATEAUS, both correct:** descent-seeded chains get `maxIterations+3`, externally kicked ones exactly `+2` (swept over limits {3,5,7,9}). Sizing against the external number **under-provisions the descent case by ~2.7×** → **CV-C62**. **(c) A trip is ERASED by the next event:** `last_error` is a per-event read, not a latch, so one benign handled event clears `RunawayChainError`, and `interpreter.error` is never set at all. On a permanently inert machine, 6/40 (`def`) and 8/40 (`async`) post-mortems read perfectly healthy → **CV-C59**, never poll `last_error` for chain health.
> - **`actionErrorPolicy: "rollback"` — unchanged, and the attempt counter is re-confirmed as mandatory.** Re-measured at this commit: the mandated rollback+onDone storm places `place_order` **128× (async) / 91× (def)** on B1 and `submit_child` **208× / 126×** on B5 before the chain cut. Library-correct behaviour; **an idempotency key on every order-placing service, keyed on CHART STATE and never on lap, remains non-negotiable.**
>
> **TIMERS — the round's central rule, and it TIGHTENS rather than relaxes.** #212 made a self-paced `raise(delay=)` heartbeat *legal*, and the same reversal made it *leak*: **`_timer_handles` retains exactly 1.00 handle per beat, for ever**, on both engines and both action kinds (**+455 MB / 24 s at 200 machines, strictly linear, no plateau**), because the handle is keyed under the machine id while the only pruner pops by state id on state exit. **No usage bounds it** — id reuse, explicit `cancel(sendId)` before re-arm, a 250 ms period and a never-exiting self-loop all measure 1.00/beat. The `after:` spelling is **flat**. Therefore **CV-C61**, a three-way split:
>
> 1. **restart-critical deadlines → `raise(delay=)`**, with a **stable `send_id`**, on a machine with a **bounded interpreter lifetime**, with `len(i._timer_handles.get(i.id, []))` exported as a gauge and alerted;
> 2. **everything periodic and non-persistent → `after:`**;
> 3. **NO high-frequency `raise(delay=)` heartbeat under any circumstances** (**CV-C47**, which stands, is widened, and is now **load-bearing** — its original R10-03 ground was closed by #212 and R11-04 replaced it).
>
> **No `delay` below 10 ms anywhere, either spelling (CV-C55)** — `delay` is milliseconds and the Windows clock floor is ~15.6 ms.
>
> **CV-C12 STANDS UNCHANGED: `after` remains BANNED in catalogue machines.** #212 did not touch `after`'s drift; **BENCH-6 is not merely still missed (174.4 ms vs ≤100 ms) but UNMEASURED FOR FOUR ROUNDS**, and a constraint whose ground has not been re-measured cannot be retired. All algo timing stays on the external `MonotonicScheduler` with absolute `*_us` deadlines in context.
>
> **K11 — the tension this catalogue must resolve, and it is currently blocked upstream.** All 20 machines below declare **zero `after` transitions and zero `raise(delay=)` actions**; every deadline is a host-side timer an action stamps. #213 exists precisely to make deadlines restart-safe, and **we cannot use it until deadlines move into the charts** — which would adopt the leaking primitive as a production dependency, since `after` deadlines are deliberately not persisted (#128, R11-DC-2). **Do not move catalogue deadlines into the charts until R11-04 is fixed upstream** (E50-R11-11). The containment above is free only while K11 holds.
>
> **Three further catalogue lints, all cheap and all currently unwritten:** every chart deadline declares a **stable `send_id`** (#213 keys `scheduled_sends` by it; an auto-generated id leaves a restored deadline unaddressable) · **never register a user action whose name collides with a built-in** (`raise`, `send`, …) — a collision **silently disarms the built-in**: `beats=0`, `last_error=None`, no warning, no error; filter registrations through `xstate_statemachine.actions.is_builtin` · **`SimulatedClock` fires neither `after` nor restored `scheduled_sends`** on this build, so every deadline property must be verified against the **real** clock (the real-clock property verified 300/300).
>
> **Two runtime rules that are not machine-JSON but bind every machine below.** **CV-C51:** no entry or exit action may `await` a receipt (`send(..., wait=True)`) on its own interpreter, directly or through a helper — #215's `_descent_done` gate makes that cycle unsatisfiable and **`start()` hangs forever** with `last_error=None`, status `running` and a legal configuration. **CV-C56:** every `start()` is wrapped in `asyncio.wait_for(..., CV_START_TIMEOUT)` and a timeout is a **hard startup failure, never a retry** — it is the only detector we have for that hang.
>
> **CV-C48 RETIRES** (its ground, the 0.8.0-era `after`-record migration cliff, is closed by #214's v2 upcast, and the security objection to that upcast was refuted). **CV-C45's stripping clause RETIRES** with it, replaced by **CV-C45″ / CV-C60**: read `last_error` / `last_transition_ok` **immediately after `from_snapshot` and before `start()`** — `on_invalid_event` is **structurally unreachable** on the restore path (`from_snapshot` takes no `plugins=` and is still constructing the interpreter), and `last_error` holds only the **last** refusal and reverts to `None` after `start()`. **CV-C49 is REWRITTEN** as **CV-C49′**: #213 now persists the armed-delay debt exactly (600/600), so the rule becomes **never re-persist an interpreter that has not been `start()`ed** — the restored records sit in `_restored_self_sends` until `start()` consumes them while `_persist_scheduled_sends` reads only `_armed_self_sends`, so a journal-compaction or migration job that loads and re-writes **without starting destroys every deadline, silently** (R11-08, **CV-C58**).
>
> Full reasoning and the complete config block with annotations: `docs/research/xstate/64-r11-final-readiness-verdict.md` §7; ADR-0016 **Amendment 11**.

### 1.3c The FINAL mandatory machine configuration (2026-09-24, ADR-0016 Decision (final))

Supersedes the interpreter-side guidance in §1.3b's amendment notes. The chart-side keys of §1.3b stand, with root `"onUnhandled": "defer"` (+ an ordered unguarded audit arm wherever a guarded transition may be denied) and `"maxIterations": 500` (CV-C62). The interpreter side is exactly this, and lives only in `cv.statechart.factory` (source: `docs/research/xstate/79-r14-final-readiness-verdict.md` §7):

```python
machine = create_machine(chart, logic=logic, strict_config=True)
interpreter = Interpreter(
    machine, strict=True, event_schemas=CV_EVENT_SCHEMAS,
    max_queue_size=CV_INBOX_BOUND,     # async only; SyncInterpreter(max_queue_size=...) -> ValueError (#245)
    overflow_policy="refuse",
).use(CvErrorHooks())
# chart root: "onUnhandled": "defer" (+ ordered unguarded audit arm), "maxIterations": 500 (CV-C62)

# restore
interpreter = Interpreter.from_snapshot(machine, blob, minimum_version=3,
                                        plugins=[CvErrorHooks()])   # kwarg, not .use() (R13-W1)
assert interpreter.last_transition_ok is not None                    # before start() (CV-C60)
_cv_bring_up(interpreter)                                            # CV-C66'
await interpreter.start()   # on_interpreter_start fires; branch on restored_from_snapshot

# supervision
if interpreter.chain_trips > 0: page_operator(interpreter.last_chain_error)
if interpreter.dropped_receipts > 0: alert("receipt dropped")        # CV-C69

# shutdown (CV-C65')
drained = await interpreter.drain_pending()     # [priority..., inbox...]
journal(drained)                                # replay exactly once after restore
blob = interpreter.get_persisted_snapshot()
await interpreter.stop()

# provenance (CV-C68)
ev2 = cv_re_mint(ev, data=patched)              # never type=/src=
# timing: after:/raise(delay=) coarse only, >=250 ms tolerance, >=10 ms (CV-C12', CV-C55)
# actions: coroutine functions directly (CV-C67); no external send() in actions (CV-C25)
```

Standing constraints and their enforcement are tabled in ADR-0016 § *Decision (final)*.

**SL-protection exception to C-04 / `CV-LINT-KILL-ANCESTOR` (amended 2026-10-09, #1650, owner decision #1778 item X; tightened per PR #2133 review).** Every `KILL` arm that carries a target must land in a `type: final` state. The single exception: a chart whose id is in the lint's explicit allowlist (`SL_PROTECTION_CHART_IDS = {"position_protection"}`) **and** whose root carries `"meta": {"cv:slProtection": true}` may target a **non-terminal** state, under all of these conditions, each enforced by `tools/lint_statecharts.py`: (1) the target state is named exactly `frozen`; (2) it declares no `invoke`, `after`, `always` or child `states`; (3) every arm on it is internal (no `target`) except recovery events `RECONCILED` / `RESUME` if a catalogue entry adds them. A non-final KILL target on any other chart, on an untagged chart, or pointing at any state other than `frozen` is a lint error. Pre-existing non-final KILL targets in B9/B10/B11/B12/B18/B19 are listed by exact (chart, state) pair in the lint's `KILL_NONFINAL_PENDING_DECISION`. They await an owner decision (separate ticket or documented baseline) and are **not** part of this exception. Rationale: KILL must never switch off a native stop-loss (C-2.6, C-4.14), so the SL-protection machine freezes rather than terminates. This is not a baseline change; no other chart may use it.

### 1.4 How to read each entry

Every entry has the same seven parts: **Purpose** · **Why this shape** · **Contract (JSON)** · **States** · **Events** · **Guards / Actions / Services** · **Invariants**. The JSON is the normative part; the tables are derived from it and exist for review, not as a second source of truth.

### 1.5 Conventions

- Targets are written absolutely in the JSON (`#order.lifecycle.filled`) and abbreviated in the tables (`lifecycle.filled`) for width.
- `_fault` and `*_us` are reserved context keys with fixed meanings: the fault record (A1 / MUST-01) and an absolute microsecond deadline (A2). `_deferred` is **retired** — the deferral buffer is now owned by the runtime under `onUnhandled: "defer"` and is observable as `interpreter.deferred_count`, not as a context key (§1.3b).
- `(always)` in an event column is an eventless transition, evaluated on entry to the state.
- `*` is the wildcard handler; in this catalogue it is always `defer`.

---

## B1 — Order

| | |
|---|---|
| **Machine `id`** | `order` |
| **Root type** | `parallel` (orthogonal regions) |
| **Owning epic** | E29 - OMS core & order state machine |
| **Schema owner** | 24-internal-schemas.md §8.2 (order state machine), §8.8 (native-SL invariant), ADR-0006 |
| **Fit (research)** | Good |
| **Event rate** | per-order exchange events; bursty on fills, otherwise low |
| **States / leaves / finals** | 21 / 19 / 5 |

**Purpose.** The canonical lifecycle of a single exchange order, from local draft to a terminal state, plus the independent native-stop-loss protection invariant for the position that order opens.

**Why this shape.** Two orthogonal regions. `lifecycle` carries the S1-S9 machine from 24 §8.2; `protection` independently tracks the §8.8 native-SL invariant, so an order can be `partially_filled` **and** `sl_missing` at the same time - a combination the current single-enum `status` column cannot express, and which is exactly what the §8.8 watchdog must observe. `quarantined` is the fourteenth lifecycle state and exists solely as the landing state for a faulted action (A1 / MUST-01).

### B1.1 Contract (normative)

```json
{
  "id": "order",
  "actionErrorPolicy": "rollback",
  "onUnhandled": "defer",
  "guardErrorPolicy": "raise",
  "strictTargets": true,
  "strict": true,
  "spawnBlockingTimeout": 5000,
  "type": "parallel",
  "context": {
    "order_id": null,
    "order_link_id": null,
    "account_id": null,
    "symbol": null,
    "side": null,
    "qty": "0",
    "filled_qty": "0",
    "leaves_qty": "0",
    "avg_price": null,
    "seen_exec_ids": [],
    "last_exchange_update": 0,
    "recon_misses": 0,
    "_fault": null,
    "sl_deadline_us": null,
    "halted_by_kill": false,
    "kill_skip_cancel": false
  },
  "states": {
    "lifecycle": {
      "initial": "draft",
      "states": {
        "draft": {
          "entry": [
            "persist_event"
          ],
          "on": {
            "VALIDATE": [
              {
                "target": "#order.lifecycle.validated",
                "guard": "passes_all_gates",
                "actions": [
                  "stamp_validated"
                ]
              },
              {
                "target": "#order.lifecycle.rejected",
                "actions": [
                  "set_local_reject"
                ]
              }
            ],
            "KILL": {
              "target": "#order.lifecycle.killed",
              "actions": [
                "skip_kill_cancel"
              ]
            }
          }
        },
        "validated": {
          "entry": [
            "persist_event",
            "reserve_rate_token"
          ],
          "on": {
            "SEND": {
              "target": "#order.lifecycle.submitting"
            },
            "KILL": {
              "target": "#order.lifecycle.killed",
              "actions": [
                "skip_kill_cancel"
              ]
            }
          }
        },
        "submitting": {
          "entry": [
            "persist_event"
          ],
          "invoke": {
            "id": "place",
            "src": "place_order",
            "onDone": [
              {
                "target": "#order.lifecycle.submitted",
                "guard": "ret_code_ok",
                "actions": [
                  "adopt_ack"
                ]
              },
              {
                "target": "#order.lifecycle.submitted",
                "guard": "is_duplicate_link_id",
                "actions": [
                  "mark_needs_lookup"
                ]
              },
              {
                "target": "#order.lifecycle.rejected",
                "actions": [
                  "map_reject_code"
                ]
              }
            ],
            "onError": {
              "target": "#order.lifecycle.unknown",
              "actions": [
                "record_transport_fault"
              ]
            }
          },
          "on": {}
        },
        "submitted": {
          "entry": [
            "persist_event"
          ],
          "on": {
            "EXEC": [
              {
                "target": "#order.lifecycle.filled",
                "guard": "exec_new_and_closes",
                "actions": [
                  "apply_fill"
                ]
              },
              {
                "target": "#order.lifecycle.partially_filled",
                "guard": "exec_new_and_partial",
                "actions": [
                  "apply_fill"
                ]
              },
              {
                "actions": [
                  "audit_guard_denied"
                ]
              }
            ],
            "TRIGGERED": {
              "target": "#order.lifecycle.triggered"
            },
            "CANCEL": {
              "target": "#order.lifecycle.cancel_pending"
            },
            "AMEND": {
              "target": "#order.lifecycle.amend_pending"
            },
            "EXPIRE": {
              "target": "#order.lifecycle.expired"
            },
            "TRANSPORT_FAULT": {
              "target": "#order.lifecycle.unknown"
            },
            "FAULT": {
              "target": "#order.lifecycle.quarantined"
            }
          }
        },
        "triggered": {
          "entry": [
            "persist_event"
          ],
          "on": {
            "EXEC": [
              {
                "target": "#order.lifecycle.filled",
                "guard": "exec_new_and_closes",
                "actions": [
                  "apply_fill"
                ]
              },
              {
                "target": "#order.lifecycle.partially_filled",
                "guard": "exec_new_and_partial",
                "actions": [
                  "apply_fill"
                ]
              },
              {
                "actions": [
                  "audit_guard_denied"
                ]
              }
            ],
            "CANCEL": {
              "target": "#order.lifecycle.cancel_pending"
            }
          }
        },
        "partially_filled": {
          "entry": [
            "persist_event",
            "notify_protection_region"
          ],
          "on": {
            "EXEC": [
              {
                "target": "#order.lifecycle.filled",
                "guard": "exec_new_and_closes",
                "actions": [
                  "apply_fill"
                ]
              },
              {
                "target": "#order.lifecycle.partially_filled",
                "guard": "exec_new_and_partial",
                "reenter": true,
                "actions": [
                  "apply_fill"
                ]
              },
              {
                "actions": [
                  "audit_guard_denied"
                ]
              }
            ],
            "CANCEL": {
              "target": "#order.lifecycle.cancel_pending"
            },
            "AMEND": {
              "target": "#order.lifecycle.amend_pending"
            },
            "FAULT": {
              "target": "#order.lifecycle.quarantined"
            }
          }
        },
        "cancel_pending": {
          "entry": [
            "persist_event"
          ],
          "invoke": {
            "id": "cancel",
            "src": "cancel_order",
            "onDone": {
              "target": "#order.lifecycle.cancelled",
              "actions": [
                "adopt_cancel_ack"
              ]
            },
            "onError": {
              "target": "#order.lifecycle.unknown",
              "actions": [
                "record_transport_fault"
              ]
            }
          },
          "on": {
            "EXEC": [
              {
                "target": "#order.lifecycle.filled",
                "guard": "exec_new_and_closes",
                "actions": [
                  "apply_fill"
                ]
              },
              {
                "target": "#order.lifecycle.partially_filled",
                "guard": "exec_new_and_partial",
                "actions": [
                  "apply_fill"
                ]
              },
              {
                "actions": [
                  "audit_guard_denied"
                ]
              }
            ],
            "KILL": {
              "actions": [
                "mark_halted_by_kill",
                "audit_kill_cancel_in_flight"
              ]
            }
          }
        },
        "amend_pending": {
          "entry": [
            "persist_event"
          ],
          "invoke": {
            "id": "amend",
            "src": "amend_order",
            "onDone": [
              {
                "target": "#order.lifecycle.partially_filled",
                "guard": "has_fills",
                "actions": [
                  "adopt_amend"
                ]
              },
              {
                "target": "#order.lifecycle.submitted",
                "actions": [
                  "adopt_amend"
                ]
              }
            ],
            "onError": {
              "target": "#order.lifecycle.unknown",
              "actions": [
                "record_transport_fault"
              ]
            }
          },
          "on": {
            "AMEND_REJECTED": [
              {
                "target": "#order.lifecycle.partially_filled",
                "guard": "has_fills",
                "actions": [
                  "keep_prior_order_live",
                  "notify_amend_rejected"
                ]
              },
              {
                "target": "#order.lifecycle.submitted",
                "actions": [
                  "keep_prior_order_live",
                  "notify_amend_rejected"
                ]
              }
            ]
          }
        },
        "unknown": {
          "entry": [
            "persist_event",
            "raise_unknown_alert",
            "arm_recon_deadline"
          ],
          "on": {
            "RECON_FOUND_LIVE": {
              "target": "#order.lifecycle.submitted",
              "actions": [
                "adopt_recon"
              ]
            },
            "RECON_FOUND_PARTIAL": {
              "target": "#order.lifecycle.partially_filled",
              "actions": [
                "adopt_recon"
              ]
            },
            "RECON_FOUND_FILLED": {
              "target": "#order.lifecycle.filled",
              "actions": [
                "adopt_recon"
              ]
            },
            "RECON_FOUND_CANCELLED": {
              "target": "#order.lifecycle.cancelled",
              "actions": [
                "adopt_recon"
              ]
            },
            "RECON_MISS": [
              {
                "target": "#order.lifecycle.rejected",
                "guard": "second_consecutive_miss",
                "actions": [
                  "set_reject_unresolvable"
                ]
              },
              {
                "target": "#order.lifecycle.unknown",
                "reenter": true,
                "actions": [
                  "bump_recon_misses"
                ]
              }
            ]
          }
        },
        "quarantined": {
          "entry": [
            "persist_event",
            "raise_critical_alert",
            "request_reconciliation"
          ],
          "tags": [
            "untrusted"
          ],
          "on": {
            "RECON_FOUND_LIVE": {
              "target": "#order.lifecycle.submitted",
              "actions": [
                "adopt_recon"
              ]
            },
            "RECON_FOUND_PARTIAL": {
              "target": "#order.lifecycle.partially_filled",
              "actions": [
                "adopt_recon"
              ]
            },
            "RECON_FOUND_FILLED": {
              "target": "#order.lifecycle.filled",
              "actions": [
                "adopt_recon"
              ]
            }
          }
        },
        "filled": {
          "type": "final",
          "entry": [
            "persist_event",
            "emit_terminal"
          ],
          "tags": [
            "terminal"
          ],
          "on": {
            "KILL": {
              "actions": [
                "audit_kill_ignored_terminal"
              ]
            }
          }
        },
        "cancelled": {
          "type": "final",
          "entry": [
            "persist_event",
            "emit_terminal"
          ],
          "tags": [
            "terminal"
          ],
          "on": {
            "KILL": {
              "actions": [
                "audit_kill_ignored_terminal"
              ]
            }
          }
        },
        "rejected": {
          "type": "final",
          "entry": [
            "persist_event",
            "emit_terminal"
          ],
          "tags": [
            "terminal"
          ],
          "on": {
            "KILL": {
              "actions": [
                "audit_kill_ignored_terminal"
              ]
            }
          }
        },
        "expired": {
          "type": "final",
          "entry": [
            "persist_event",
            "emit_terminal"
          ],
          "tags": [
            "terminal"
          ],
          "on": {
            "KILL": {
              "actions": [
                "audit_kill_ignored_terminal"
              ]
            }
          }
        },
        "killed": {
          "type": "final",
          "entry": [
            "persist_event",
            "mark_halted_by_kill",
            "audit_kill",
            "issue_kill_cancel",
            "emit_terminal"
          ],
          "tags": [
            "terminal",
            "halted_by_kill"
          ],
          "on": {
            "KILL": {
              "actions": [
                "audit_kill_ignored_terminal"
              ]
            }
          }
        }
      },
      "on": {
        "KILL": {
          "target": "#order.lifecycle.killed"
        }
      }
    },
    "protection": {
      "initial": "not_required",
      "states": {
        "not_required": {
          "on": {
            "FIRST_FILL": {
              "target": "#order.protection.sl_pending"
            }
          }
        },
        "sl_pending": {
          "entry": [
            "arm_sl_deadline"
          ],
          "invoke": {
            "id": "attach_sl",
            "src": "attach_native_sl",
            "onDone": {
              "target": "#order.protection.sl_present"
            },
            "onError": {
              "target": "#order.protection.sl_missing"
            }
          },
          "on": {
            "SL_DEADLINE": {
              "target": "#order.protection.sl_missing"
            }
          }
        },
        "sl_present": {
          "tags": [
            "protected"
          ],
          "on": {
            "SL_LOST": {
              "target": "#order.protection.sl_missing"
            }
          }
        },
        "sl_missing": {
          "tags": [
            "naked"
          ],
          "entry": [
            "raise_naked_position_alert",
            "request_fallback_sl"
          ],
          "on": {
            "SL_OBSERVED": {
              "target": "#order.protection.sl_present"
            }
          }
        }
      },
      "on": {
        "KILL": {
          "actions": [
            "audit_kill_protection_retained"
          ]
        }
      }
    }
  }
}
```

### B1.2 States

| State | Kind | Tags | Entry actions | Exit actions | Defers `*` |
|---|---|---|---|---|---|
| `lifecycle` | compound | — | — | — | — |
| `lifecycle.draft` | atomic | — | `persist_event` | — | yes |
| `lifecycle.validated` | atomic | — | `persist_event`, `reserve_rate_token` | — | yes |
| `lifecycle.submitting` | atomic | — | `persist_event` | — | yes |
| `lifecycle.submitted` | atomic | — | `persist_event` | — | — |
| `lifecycle.triggered` | atomic | — | `persist_event` | — | — |
| `lifecycle.partially_filled` | atomic | — | `persist_event`, `notify_protection_region` | — | — |
| `lifecycle.cancel_pending` | atomic | — | `persist_event` | — | yes |
| `lifecycle.amend_pending` | atomic | — | `persist_event` | — | yes |
| `lifecycle.unknown` | atomic | — | `persist_event`, `raise_unknown_alert`, `arm_recon_deadline` | — | — |
| `lifecycle.quarantined` | atomic | `untrusted` | `persist_event`, `raise_critical_alert`, `request_reconciliation` | — | — |
| `lifecycle.filled` | final | `terminal` | `persist_event`, `emit_terminal` | — | — |
| `lifecycle.cancelled` | final | `terminal` | `persist_event`, `emit_terminal` | — | — |
| `lifecycle.rejected` | final | `terminal` | `persist_event`, `emit_terminal` | — | — |
| `lifecycle.expired` | final | `terminal` | `persist_event`, `emit_terminal` | — | — |
| `lifecycle.killed` *(Corrected 2026-10-09)* | final | `terminal`, `halted_by_kill` | `persist_event`, `mark_halted_by_kill`, `audit_kill`, `issue_kill_cancel`, `emit_terminal` | — | — |
| `protection` | compound | — | — | — | — |
| `protection.not_required` | atomic | — | — | — | — |
| `protection.sl_pending` | atomic | — | `arm_sl_deadline` | — | — |
| `protection.sl_present` | atomic | `protected` | — | — | — |
| `protection.sl_missing` | atomic | `naked` | `raise_naked_position_alert`, `request_fallback_sl` | — | — |

### B1.3 Events and transitions

| From | Event | Guard | Target | Actions | `reenter` |
|---|---|---|---|---|---|
| `lifecycle.draft` | `VALIDATE` | `passes_all_gates` | `lifecycle.validated` | `stamp_validated` | — |
| `lifecycle.draft` | `VALIDATE` | — | `lifecycle.rejected` | `set_local_reject` | — |
| `lifecycle.draft` | `*` | — | _(internal)_ | `defer` | — |
| `lifecycle.validated` | `SEND` | — | `lifecycle.submitting` | — | — |
| `lifecycle.validated` | `*` | — | _(internal)_ | `defer` | — |
| `lifecycle.submitting` | `*` | — | _(internal)_ | `defer` | — |
| `lifecycle.submitted` | `EXEC` | `exec_new_and_closes` | `lifecycle.filled` | `apply_fill` | — |
| `lifecycle.submitted` | `EXEC` | `exec_new_and_partial` | `lifecycle.partially_filled` | `apply_fill` | — |
| `lifecycle.submitted` | `EXEC` | — | _(internal)_ | `audit_guard_denied` | — |
| `lifecycle.submitted` | `TRIGGERED` | — | `lifecycle.triggered` | — | — |
| `lifecycle.submitted` | `CANCEL` | — | `lifecycle.cancel_pending` | — | — |
| `lifecycle.submitted` | `AMEND` | — | `lifecycle.amend_pending` | — | — |
| `lifecycle.submitted` | `EXPIRE` | — | `lifecycle.expired` | — | — |
| `lifecycle.submitted` | `TRANSPORT_FAULT` | — | `lifecycle.unknown` | — | — |
| `lifecycle.submitted` | `FAULT` | — | `lifecycle.quarantined` | — | — |
| `lifecycle.triggered` | `EXEC` | `exec_new_and_closes` | `lifecycle.filled` | `apply_fill` | — |
| `lifecycle.triggered` | `EXEC` | `exec_new_and_partial` | `lifecycle.partially_filled` | `apply_fill` | — |
| `lifecycle.triggered` | `EXEC` | — | _(internal)_ | `audit_guard_denied` | — |
| `lifecycle.triggered` | `CANCEL` | — | `lifecycle.cancel_pending` | — | — |
| `lifecycle.partially_filled` | `EXEC` | `exec_new_and_closes` | `lifecycle.filled` | `apply_fill` | — |
| `lifecycle.partially_filled` | `EXEC` | `exec_new_and_partial` | `lifecycle.partially_filled` | `apply_fill` | yes |
| `lifecycle.partially_filled` | `EXEC` | — | _(internal)_ | `audit_guard_denied` | — |
| `lifecycle.partially_filled` | `CANCEL` | — | `lifecycle.cancel_pending` | — | — |
| `lifecycle.partially_filled` | `AMEND` | — | `lifecycle.amend_pending` | — | — |
| `lifecycle.partially_filled` | `FAULT` | — | `lifecycle.quarantined` | — | — |
| `lifecycle.cancel_pending` | `EXEC` | `exec_new_and_closes` | `lifecycle.filled` | `apply_fill` | — |
| `lifecycle.cancel_pending` | `EXEC` | `exec_new_and_partial` | `lifecycle.partially_filled` | `apply_fill` | — |
| `lifecycle.cancel_pending` | `EXEC` | — | _(internal)_ | `audit_guard_denied` | — |
| `lifecycle.cancel_pending` | `*` | — | _(internal)_ | `defer` | — |
| `lifecycle.amend_pending` | `AMEND_REJECTED` | `has_fills` | `lifecycle.partially_filled` | `keep_prior_order_live`, `notify_amend_rejected` | — |
| `lifecycle.amend_pending` | `AMEND_REJECTED` | — | `lifecycle.submitted` | `keep_prior_order_live`, `notify_amend_rejected` | — |
| `lifecycle.amend_pending` | `*` | — | _(internal)_ | `defer` | — |
| `lifecycle.unknown` | `RECON_FOUND_LIVE` | — | `lifecycle.submitted` | `adopt_recon` | — |
| `lifecycle.unknown` | `RECON_FOUND_PARTIAL` | — | `lifecycle.partially_filled` | `adopt_recon` | — |
| `lifecycle.unknown` | `RECON_FOUND_FILLED` | — | `lifecycle.filled` | `adopt_recon` | — |
| `lifecycle.unknown` | `RECON_FOUND_CANCELLED` | — | `lifecycle.cancelled` | `adopt_recon` | — |
| `lifecycle.unknown` | `RECON_MISS` | `second_consecutive_miss` | `lifecycle.rejected` | `set_reject_unresolvable` | — |
| `lifecycle.unknown` | `RECON_MISS` | — | `lifecycle.unknown` | `bump_recon_misses` | yes |
| `lifecycle.quarantined` | `RECON_FOUND_LIVE` | — | `lifecycle.submitted` | `adopt_recon` | — |
| `lifecycle.quarantined` | `RECON_FOUND_PARTIAL` | — | `lifecycle.partially_filled` | `adopt_recon` | — |
| `lifecycle.quarantined` | `RECON_FOUND_FILLED` | — | `lifecycle.filled` | `adopt_recon` | — |
| `lifecycle` | `KILL` | — | `lifecycle.killed` | — (entry of `killed`) | — |
| `lifecycle.draft` | `KILL` | — | `lifecycle.killed` | `skip_kill_cancel` *(Corrected 2026-10-09, #2133 review)* | — |
| `lifecycle.validated` | `KILL` | — | `lifecycle.killed` | `skip_kill_cancel` *(Corrected 2026-10-09, #2133 review)* | — |
| `lifecycle.cancel_pending` | `KILL` | — | _(internal)_ | `mark_halted_by_kill`, `audit_kill_cancel_in_flight` *(Corrected 2026-10-09, #2133 review)* | — |
| `lifecycle.filled` | `KILL` | — | _(internal)_ | `audit_kill_ignored_terminal` | — |
| `lifecycle.cancelled` | `KILL` | — | _(internal)_ | `audit_kill_ignored_terminal` | — |
| `lifecycle.rejected` | `KILL` | — | _(internal)_ | `audit_kill_ignored_terminal` | — |
| `lifecycle.expired` | `KILL` | — | _(internal)_ | `audit_kill_ignored_terminal` | — |
| `lifecycle.killed` | `KILL` | — | _(internal)_ | `audit_kill_ignored_terminal` | — |
| `protection` | `KILL` | — | _(internal)_ | `audit_kill_protection_retained` | — |
| `protection.not_required` | `FIRST_FILL` | — | `protection.sl_pending` | — | — |
| `protection.sl_pending` | `SL_DEADLINE` | — | `protection.sl_missing` | — | — |
| `protection.sl_present` | `SL_LOST` | — | `protection.sl_missing` | — | — |
| `protection.sl_missing` | `SL_OBSERVED` | — | `protection.sl_present` | — | — |

### B1.4 Invoked services

| In state | `id` | `src` | `onDone` | `onError` |
|---|---|---|---|---|
| `lifecycle.submitting` | `place` | `place_order` | `lifecycle.submitted` if `ret_code_ok`; `lifecycle.submitted` if `is_duplicate_link_id`; `lifecycle.rejected` | `lifecycle.unknown` |
| `lifecycle.cancel_pending` | `cancel` | `cancel_order` | `lifecycle.cancelled` | `lifecycle.unknown` |
| `lifecycle.amend_pending` | `amend` | `amend_order` | `lifecycle.partially_filled` if `has_fills`; `lifecycle.submitted` | `lifecycle.unknown` |
| `protection.sl_pending` | `attach_sl` | `attach_native_sl` | `protection.sl_present` | `protection.sl_missing` |

### B1.5 Guards

| Guard | Polarity | Contract |
|---|---|---|
| `exec_new_and_closes` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `exec_new_and_partial` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `has_fills` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `is_duplicate_link_id` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `passes_all_gates` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `ret_code_ok` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `second_consecutive_miss` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |

### B1.6 Actions

All actions are `@cv_action`-wrapped (A1). A raising action writes `context["_fault"]`, aborts the transition and routes to this machine's fault state; the snapshot writer refuses to persist a faulted context (MUST-01).

| Action |
|---|
| `adopt_ack` |
| `adopt_amend` |
| `adopt_cancel_ack` |
| `adopt_recon` |
| `apply_fill` |
| `arm_recon_deadline` |
| `arm_sl_deadline` |
| `bump_recon_misses` |
| `defer` |
| `emit_terminal` |
| `keep_prior_order_live` |
| `map_reject_code` |
| `mark_needs_lookup` |
| `notify_amend_rejected` |
| `notify_protection_region` |
| `persist_event` |
| `raise_critical_alert` |
| `raise_naked_position_alert` |
| `raise_unknown_alert` |
| `record_transport_fault` |
| `request_fallback_sl` |
| `request_reconciliation` |
| `reserve_rate_token` |
| `set_local_reject` |
| `set_reject_unresolvable` |
| `stamp_validated` |
| `audit_guard_denied` *(Corrected 2026-10-09)* |
| `audit_kill` *(Corrected 2026-10-09)* |
| `audit_kill_cancel_in_flight` *(Corrected 2026-10-09, #2133 review)* |
| `audit_kill_ignored_terminal` *(Corrected 2026-10-09)* |
| `audit_kill_protection_retained` *(Corrected 2026-10-09)* |
| `issue_kill_cancel` *(Corrected 2026-10-09)* |
| `mark_halted_by_kill` *(Corrected 2026-10-09)* |
| `skip_kill_cancel` *(Corrected 2026-10-09, #2133 review)* |

### B1.7 Invariants

| ID | Invariant |
|---|---|
| **INV-1** | `filled_qty <= qty` at every observable point, including mid-drain. |
| **INV-2** | A terminal state (`filled`, `cancelled`, `rejected`, `expired`, `killed`) is never left (24 §8.2 S6). |
| **INV-5** | **No delivered `EXEC` is ever unaccounted for**: every `exec_id` the gateway delivers appears in `seen_exec_ids` or in `_deferred`. This is the direct regression test for LC-03 and it is mandatory for this family. |
| **INV-B1-a** | `apply_fill` is order-independent: applying the same set of `EXEC` events in any order yields identical `filled_qty` and `avg_price` (MUSTNOT-04). |
| **INV-B1-b** | `exec_id` dedupe is total - a repeated `exec_id` changes nothing (24 §8.2 S4). |
| **INV-B1-c** | An `AMEND_REJECTED` leaves the prior order live (S2): the machine returns to the state it amended from, never to a terminal state. |
| **INV-B1-d** | A fill beats a pending cancel (S3): `cancel_pending` handles `EXEC` explicitly rather than deferring it. |
| **INV-B1-e** | `unknown` never resubmits (S1); it may only be resolved by a `RECON_FOUND_*` event. |
| **INV-B1-f** | The `protection` region reaches `sl_present` only from an exchange read (`SL_OBSERVED`), never from a local assumption. |
| **INV-B1-h** | *(Corrected 2026-10-09, #1650; reworded #2133)* **At most one exchange cancel per order, and only if it was submitted.** Root `KILL` from `draft`/`validated` reaches `killed` with audit only (`skip_kill_cancel`, no exchange call); from any other non-terminal lifecycle state except `cancel_pending` it reaches `killed`, sets `halted_by_kill`, writes `audit_kill` **before** the cancel (write-ahead, C-2.9) and issues one `cancel_order` (same `orderLinkId`, C-2.10) bounded by `CV_KILL_CANCEL_TIMEOUT`; failure or timeout is audited and never rolls the kill back. In `cancel_pending` KILL reuses the in-flight cancel (no second call): it sets `halted_by_kill` and audits, and the existing invoke resolves the order. Reconciliation re-syncs the true exchange state (C-2.5). `KILL` on a terminal state only audits. |
| **INV-B1-i** | *(Corrected 2026-10-09, #1650)* `KILL` never changes the `protection` region (C-2.6, C-4.14): no SL is cancelled or amended; the region only audits. |
| **INV-B1-g** | A write-ahead `order_events` row exists for every transition before the in-memory state changes (S8, A7, MUST-02). |

### B1.8 Implementation notes

- **Corrected 2026-10-09 (C-04 / C-07b, #1650, owner decision #1778 item X option a):** `lifecycle.on.KILL` → new final `killed` (entry: `persist_event`, `mark_halted_by_kill`, `audit_kill`, `issue_kill_cancel`, `emit_terminal` — audit is write-ahead of the cancel, C-2.9; *PR #2133 review:* `draft`/`validated` KILL skips the cancel via `skip_kill_cancel`, `cancel_pending` KILL reuses the in-flight cancel, and the cancel is bounded by `CV_KILL_CANCEL_TIMEOUT`) instead of misreporting the kill as an exchange-side `cancelled`/`rejected`/`expired`; every invoking lifecycle state has a kill ancestor. The `protection` region declares `KILL` as an internal audit-only arm (`audit_kill_protection_retained`) — it has no terminal by design and KILL must never remove the native SL. Terminals carry an internal `KILL` audit arm so a late kill is recorded, not deferred. Ordered unguarded `audit_guard_denied` arm appended to every guarded-only `EXEC` (C-07b). New context key `halted_by_kill`.
- **Deferral is load-bearing.** `submitting` and `amend_pending` are occupied while an exchange round trip is in flight. Omit the wildcard handler on one of them and a fill is lost with no exception and no log line (LC-03; Study 05 C17 lost three `PARTIAL` fills deterministically across 10 runs). `cancel_pending` deliberately handles `EXEC` explicitly instead of deferring, because S3 says the fill wins the race.
- **Timing is external.** `sl_deadline_us` and the reconciliation deadline are absolute microsecond timestamps in context, armed by the `MonotonicScheduler` and re-armed on restore (A2).
- **Restore re-drives invokes.** A crash in `submitting` restores a machine parked in `submitting` with no service running (LC-19); the boot procedure re-sends the triggering event *after* draining `_deferred` (MUST-03).

---

## B2 — TradeGroup

| | |
|---|---|
| **Machine `id`** | `trade_group` |
| **Root type** | `compound`, initial `draft` |
| **Owning epic** | E34 - Trade-group fan-out & rate-limit governor |
| **Schema owner** | 24-internal-schemas.md §9.6 (group lifecycle), §9.4 (fan-out), §9.5 (leg failure policy), ADR-0008 |
| **Fit (research)** | Good |
| **Event rate** | low - one event per leg outcome |
| **States / leaves / finals** | 10 / 10 / 3 |

**Purpose.** The supervisor for one fan-out: it spawns one leg per account, aggregates leg outcomes into a group status, and runs the compensating unwind when policy demands it.

**Why this shape.** The group is a pure aggregator. Group status is a **function of the leg counters in context**, never of event arrival order - `EVALUATE` is raised after each leg outcome to re-run the decision, because an `always` self-target on `submitting` would deadlock (LC-02) and because `raise` is queued behind pending external events rather than settling inside the macrostep (LC-05), so `EVALUATE` may be observed *after* a later `LEG_OPEN`.

### B2.1 Contract (normative)

```json
{
  "id": "trade_group",
  "actionErrorPolicy": "rollback",
  "onUnhandled": "defer",
  "guardErrorPolicy": "raise",
  "strictTargets": true,
  "strict": true,
  "spawnBlockingTimeout": 5000,
  "on": {
    "KILL": {
      "target": "#trade_group.failed",
      "actions": [
        "audit_kill"
      ]
    }
  },
  "initial": "draft",
  "context": {
    "group_id": null,
    "policy": "best_effort",
    "leg_ids": [],
    "legs_open": 0,
    "legs_failed": 0,
    "legs_skipped": 0,
    "legs_total": 0,
    "quiesce_deadline_us": null,
    "unwind_id": null,
    "quiesced": false
  },
  "states": {
    "draft": {
      "on": {
        "CONFIRM": {
          "target": "#trade_group.submitting",
          "actions": [
            "reserve_rate_budget",
            "launch_all_legs"
          ]
        },
        "CANCEL": {
          "target": "#trade_group.cancelled"
        }
      }
    },
    "submitting": {
      "entry": [
        "arm_quiesce_deadline"
      ],
      "on": {
        "LEG_OPEN": {
          "actions": [
            "count_open",
            {
              "type": "raise",
              "params": {
                "event": {
                  "type": "EVALUATE"
                }
              }
            }
          ]
        },
        "LEG_FAILED": [
          {
            "target": "#trade_group.aborting",
            "guard": "policy_is_abort_on_first",
            "actions": [
              "count_failed"
            ]
          },
          {
            "actions": [
              "count_failed",
              {
                "type": "raise",
                "params": {
                  "event": {
                    "type": "EVALUATE"
                  }
                }
              }
            ]
          }
        ],
        "LEG_SKIPPED": {
          "actions": [
            "count_skipped",
            {
              "type": "raise",
              "params": {
                "event": {
                  "type": "EVALUATE"
                }
              }
            }
          ]
        },
        "QUIESCE_DEADLINE": {
          "actions": [
            "mark_quiesced",
            "force_resolve_unknown_legs",
            {
              "type": "raise",
              "params": {
                "event": {
                  "type": "EVALUATE"
                }
              }
            }
          ]
        },
        "EVALUATE": [
          {
            "target": "#trade_group.unwinding",
            "guard": "policy_all_or_none_and_any_failed"
          },
          {
            "target": "#trade_group.open",
            "guard": "all_non_skipped_open"
          },
          {
            "target": "#trade_group.failed",
            "guard": "quiesced_and_zero_open"
          },
          {
            "target": "#trade_group.partially_open",
            "guard": "quiesced_and_some_open"
          },
          {
            "actions": [
              "audit_guard_denied"
            ]
          }
        ]
      }
    },
    "partially_open": {
      "on": {
        "LEG_OPEN": [
          {
            "target": "#trade_group.open",
            "guard": "all_non_skipped_open",
            "actions": [
              "count_open"
            ]
          },
          {
            "target": "#trade_group.partially_open",
            "reenter": true,
            "actions": [
              "count_open"
            ]
          }
        ],
        "CLOSE_GROUP": {
          "target": "#trade_group.closing"
        }
      }
    },
    "open": {
      "on": {
        "CLOSE_GROUP": {
          "target": "#trade_group.closing"
        },
        "ALL_LEGS_FLAT": {
          "target": "#trade_group.closed"
        }
      }
    },
    "aborting": {
      "entry": [
        "stop_submitting_remaining_legs"
      ],
      "always": [
        {
          "target": "#trade_group.partially_open",
          "guard": "some_open"
        },
        {
          "target": "#trade_group.failed"
        }
      ]
    },
    "unwinding": {
      "entry": [
        "persist_unwind_plan"
      ],
      "invoke": {
        "id": "unwind",
        "src": "unwind_machine",
        "onDone": [
          {
            "target": "#trade_group.failed",
            "guard": "unwind_complete",
            "actions": [
              "mark_unwound"
            ]
          },
          {
            "target": "#trade_group.failed",
            "actions": [
              "mark_unwind_incomplete",
              "raise_critical_alert"
            ]
          }
        ],
        "onError": {
          "target": "#trade_group.failed",
          "actions": [
            "mark_unwind_incomplete",
            "raise_critical_alert"
          ]
        }
      }
    },
    "closing": {
      "on": {
        "ALL_LEGS_FLAT": {
          "target": "#trade_group.closed"
        },
        "CLOSE_INCOMPLETE": {
          "target": "#trade_group.failed",
          "actions": [
            "raise_critical_alert"
          ]
        }
      }
    },
    "closed": {
      "type": "final",
      "tags": [
        "terminal"
      ]
    },
    "failed": {
      "type": "final",
      "tags": [
        "terminal"
      ]
    },
    "cancelled": {
      "type": "final",
      "tags": [
        "terminal"
      ]
    }
  }
}
```

### B2.2 States

| State | Kind | Tags | Entry actions | Exit actions | Defers `*` |
|---|---|---|---|---|---|
| `draft` | atomic | — | — | — | — |
| `submitting` | atomic | — | `arm_quiesce_deadline` | — | — |
| `partially_open` | atomic | — | — | — | — |
| `open` | atomic | — | — | — | — |
| `aborting` | atomic | — | `stop_submitting_remaining_legs` | — | — |
| `unwinding` | atomic | — | `persist_unwind_plan` | — | — |
| `closing` | atomic | — | — | — | — |
| `closed` | final | `terminal` | — | — | — |
| `failed` | final | `terminal` | — | — | — |
| `cancelled` | final | `terminal` | — | — | — |

### B2.3 Events and transitions

| From | Event | Guard | Target | Actions | `reenter` |
|---|---|---|---|---|---|
| `draft` | `CONFIRM` | — | `submitting` | `reserve_rate_budget`, `launch_all_legs` | — |
| `draft` | `CANCEL` | — | `cancelled` | — | — |
| `submitting` | `LEG_OPEN` | — | _(internal)_ | `count_open`, `raise` → `EVALUATE` (built-in) | — |
| `submitting` | `LEG_FAILED` | `policy_is_abort_on_first` | `aborting` | `count_failed` | — |
| `submitting` | `LEG_FAILED` | — | _(internal)_ | `count_failed`, `raise` → `EVALUATE` (built-in) | — |
| `submitting` | `LEG_SKIPPED` | — | _(internal)_ | `count_skipped`, `raise` → `EVALUATE` (built-in) | — |
| `submitting` | `QUIESCE_DEADLINE` | — | _(internal)_ | `mark_quiesced`, `force_resolve_unknown_legs`, `raise` → `EVALUATE` (built-in) | — |
| `submitting` | `EVALUATE` | `policy_all_or_none_and_any_failed` | `unwinding` | — | — |
| `submitting` | `EVALUATE` | `all_non_skipped_open` | `open` | — | — |
| `submitting` | `EVALUATE` | `quiesced_and_zero_open` | `failed` | — | — |
| `submitting` | `EVALUATE` | `quiesced_and_some_open` | `partially_open` | — | — |
| `partially_open` | `LEG_OPEN` | `all_non_skipped_open` | `open` | `count_open` | — |
| `partially_open` | `LEG_OPEN` | — | `partially_open` | `count_open` | yes |
| `partially_open` | `CLOSE_GROUP` | — | `closing` | — | — |
| `open` | `CLOSE_GROUP` | — | `closing` | — | — |
| `open` | `ALL_LEGS_FLAT` | — | `closed` | — | — |
| `aborting` | _always_ | `some_open` | `partially_open` | — | — |
| `aborting` | _always_ | — | `failed` | — | — |
| `closing` | `ALL_LEGS_FLAT` | — | `closed` | — | — |
| `closing` | `CLOSE_INCOMPLETE` | — | `failed` | `raise_critical_alert` | — |

### B2.4 Invoked services

| In state | `id` | `src` | `onDone` | `onError` |
|---|---|---|---|---|
| `unwinding` | `unwind` | `unwind_machine` | `failed` if `unwind_complete`; `failed` | `failed` |

### B2.5 Guards

| Guard | Polarity | Contract |
|---|---|---|
| `all_non_skipped_open` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `policy_all_or_none_and_any_failed` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `policy_is_abort_on_first` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `quiesced_and_some_open` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `quiesced_and_zero_open` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `some_open` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `unwind_complete` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |

### B2.6 Actions

All actions are `@cv_action`-wrapped (A1). A raising action writes `context["_fault"]`, aborts the transition and routes to this machine's fault state; the snapshot writer refuses to persist a faulted context (MUST-01).

| Action |
|---|
| `arm_quiesce_deadline` |
| `count_failed` |
| `count_open` |
| `count_skipped` |
| `force_resolve_unknown_legs` |
| `mark_quiesced` |
| `mark_unwind_incomplete` |
| `mark_unwound` |
| `persist_unwind_plan` |
| `raise_critical_alert` |
| `raise` → `EVALUATE` (built-in) |
| `reserve_rate_budget` |
| `launch_all_legs` |
| `stop_submitting_remaining_legs` |

### B2.7 Invariants

| ID | Invariant |
|---|---|
| **INV-4** | The sum of leg `filled_qty` equals the group aggregate at every quiescent point. |
| **INV-B2-a** | Group status is a **pure function of `legs_open`/`legs_failed`/`legs_skipped`/`legs_total`**; no guard reads the event. |
| **INV-B2-b** | `legs_open + legs_failed + legs_skipped <= legs_total` always; a resolution state is entered only once that sum equals `legs_total` or the quiesce deadline fires. |
| **INV-B2-c** | `all_or_none` never rests in `partially_open`: it either reaches `open` or runs the unwind. |
| **INV-B2-d** | The unwind is restartable and idempotent - re-entering `unwinding` after a crash re-drives the same persisted plan without double-closing. |
| **INV-B2-e** | Legs are addressed through the application-owned registry, never by `sendTo` service key (LC-16). |

### B2.8 Implementation notes

- **MUSTNOT-02 applies here specifically.** `reserve_rate_budget` on `submitting` is an *action that calls* the synchronous token-bucket governor. The governor itself is never a statechart: measured p50 35.2 ms per account as a chart against 0.148 us as a token bucket (~238,000x), and a 5-account atomic fan-out would burn ~175 ms of the 750 ms `CV_FANOUT_ADMIT_WAIT_MS` budget purely asking permission.
- **Bound the actors.** MUSTNOT-08 caps concurrently invoked children at 200 per process; each costs two asyncio tasks, one polling at 200 Hz.
- **Corrected 2026-10-01 (C-04 / C-07b class, E50-S01, `tools/lint_statecharts.py` CV-LINT-KILL-ANCESTOR / CV-LINT-FALLTHROUGH):** root `on.KILL` → existing `failed` with `audit_kill`, so every invoking state has a kill ancestor (C-04; no new guard, no new business transition); ordered unguarded `audit_guard_denied` arm (internal, B18 shape) appended after the guarded arms of `submitting.EVALUATE` so a guard-denied event is audited, never silently deferred (C-07b).

---

## B3 — TradeGroupLeg

| | |
|---|---|
| **Machine `id`** | `leg` |
| **Root type** | `compound`, initial `pending` |
| **Owning epic** | E34 - Trade-group fan-out & rate-limit governor |
| **Schema owner** | 24-internal-schemas.md §9.1 (model), §9.5.1 (per-account unwind), §9.3 (sizing) |
| **Fit (research)** | Good |
| **Event rate** | low per leg; bursty on fills |
| **States / leaves / finals** | 16 / 15 / 4 |

**Purpose.** One account's share of a fan-out: preflight, sizing from the per-account profile, entry submission, TP ladder, and the nested compensating unwind.

**Why this shape.** The unwind is a **nested compound state**, not a flag: `cancel_children -> close_position -> verify_flat -> verify_sl`. 24 §9.5.1 already describes it as "an explicit, restartable, idempotent state machine rather than 'cancel and close'", and there is currently no ticket anywhere in the backlog that builds it.

### B3.1 Contract (normative)

```json
{
  "id": "leg",
  "actionErrorPolicy": "rollback",
  "onUnhandled": "defer",
  "guardErrorPolicy": "raise",
  "strictTargets": true,
  "strict": true,
  "spawnBlockingTimeout": 5000,
  "on": {
    "KILL": {
      "target": "#leg.error",
      "actions": [
        "audit_kill"
      ]
    }
  },
  "initial": "pending",
  "context": {
    "leg_id": null,
    "account_id": null,
    "profile_snapshot": null,
    "sized_qty": "0",
    "filled_qty": "0",
    "entry_order_id": null,
    "tp_order_ids": [],
    "skip_reason": null,
    "error_code": null,
    "close_attempts": 0,
    "qty_drift": "0"
  },
  "states": {
    "pending": {
      "entry": [
        "size_from_profile"
      ],
      "always": [
        {
          "target": "#leg.skipped",
          "guard": "should_skip"
        },
        {
          "target": "#leg.submitting",
          "guard": "passes_preflight"
        },
        {
          "target": "#leg.error"
        }
      ]
    },
    "submitting": {
      "entry": [
        "submit_entry_order",
        "arm_submit_timeout"
      ],
      "on": {
        "ORDER_OPEN": {
          "target": "#leg.open"
        },
        "ORDER_REJECTED": {
          "target": "#leg.rejected",
          "actions": [
            "map_error"
          ]
        },
        "ORDER_UNKNOWN": {
          "target": "#leg.resolving"
        },
        "SUBMIT_TIMEOUT": {
          "target": "#leg.resolving"
        }
      }
    },
    "resolving": {
      "invoke": {
        "id": "lookup",
        "src": "lookup_by_link_id",
        "onDone": [
          {
            "target": "#leg.open",
            "guard": "lookup_says_live"
          },
          {
            "target": "#leg.filled",
            "guard": "lookup_says_filled"
          },
          {
            "target": "#leg.rejected",
            "actions": [
              "map_error"
            ]
          }
        ],
        "onError": {
          "target": "#leg.error",
          "actions": [
            "map_error"
          ]
        }
      },
      "on": {}
    },
    "open": {
      "on": {
        "EXEC": {
          "target": "#leg.partially_filled",
          "actions": [
            "accumulate_fill",
            "place_tp_ladder_once"
          ]
        },
        "UNWIND": {
          "target": "#leg.unwinding"
        },
        "CLOSE": {
          "target": "#leg.closing"
        }
      }
    },
    "partially_filled": {
      "on": {
        "EXEC": [
          {
            "target": "#leg.filled",
            "guard": "fully_filled",
            "actions": [
              "accumulate_fill"
            ]
          },
          {
            "target": "#leg.partially_filled",
            "reenter": true,
            "actions": [
              "accumulate_fill"
            ]
          }
        ],
        "UNWIND": {
          "target": "#leg.unwinding"
        },
        "CLOSE": {
          "target": "#leg.closing"
        }
      }
    },
    "filled": {
      "on": {
        "UNWIND": {
          "target": "#leg.unwinding"
        },
        "CLOSE": {
          "target": "#leg.closing"
        }
      }
    },
    "unwinding": {
      "initial": "cancel_children",
      "states": {
        "cancel_children": {
          "invoke": {
            "id": "cx",
            "src": "cancel_children_svc",
            "onDone": {
              "target": "#leg.unwinding.close_position"
            },
            "onError": {
              "target": "#leg.unwinding.close_position",
              "actions": [
                "note_cancel_failure"
              ]
            }
          }
        },
        "close_position": {
          "entry": [
            "read_authoritative_position_qty",
            "bump_close_attempts"
          ],
          "invoke": {
            "id": "cl",
            "src": "reduce_only_close",
            "onDone": {
              "target": "#leg.unwinding.verify_flat"
            },
            "onError": [
              {
                "target": "#leg.unwinding.close_position",
                "reenter": true,
                "guard": "close_attempts_left"
              },
              {
                "target": "#leg.unwinding.verify_sl",
                "actions": [
                  "mark_incomplete"
                ]
              }
            ]
          }
        },
        "verify_flat": {
          "invoke": {
            "id": "vf",
            "src": "poll_until_flat",
            "onDone": [
              {
                "target": "#leg.closed",
                "guard": "is_flat"
              },
              {
                "target": "#leg.unwinding.close_position",
                "reenter": true,
                "guard": "close_attempts_left"
              },
              {
                "target": "#leg.unwinding.verify_sl",
                "actions": [
                  "mark_incomplete"
                ]
              }
            ],
            "onError": {
              "target": "#leg.unwinding.verify_sl",
              "actions": [
                "mark_incomplete"
              ]
            }
          }
        },
        "verify_sl": {
          "invoke": {
            "id": "vs",
            "src": "assert_native_sl",
            "onDone": {
              "target": "#leg.error"
            },
            "onError": {
              "target": "#leg.error",
              "actions": [
                "raise_naked_position_alert"
              ]
            }
          }
        }
      }
    },
    "closing": {
      "on": {
        "FLAT": {
          "target": "#leg.closed"
        },
        "CLOSE_FAILED": {
          "target": "#leg.error"
        }
      }
    },
    "skipped": {
      "type": "final",
      "tags": [
        "terminal",
        "skip"
      ]
    },
    "rejected": {
      "type": "final",
      "tags": [
        "terminal",
        "failure"
      ]
    },
    "closed": {
      "type": "final",
      "tags": [
        "terminal"
      ]
    },
    "error": {
      "type": "final",
      "tags": [
        "terminal",
        "failure"
      ]
    }
  }
}
```

### B3.2 States

| State | Kind | Tags | Entry actions | Exit actions | Defers `*` |
|---|---|---|---|---|---|
| `pending` | atomic | — | `size_from_profile` | — | — |
| `submitting` | atomic | — | `submit_entry_order`, `arm_submit_timeout` | — | — |
| `resolving` | atomic | — | — | — | yes |
| `open` | atomic | — | — | — | — |
| `partially_filled` | atomic | — | — | — | — |
| `filled` | atomic | — | — | — | — |
| `unwinding` | compound | — | — | — | — |
| `unwinding.cancel_children` | atomic | — | — | — | — |
| `unwinding.close_position` | atomic | — | `read_authoritative_position_qty`, `bump_close_attempts` | — | — |
| `unwinding.verify_flat` | atomic | — | — | — | — |
| `unwinding.verify_sl` | atomic | — | — | — | — |
| `closing` | atomic | — | — | — | — |
| `skipped` | final | `terminal`, `skip` | — | — | — |
| `rejected` | final | `terminal`, `failure` | — | — | — |
| `closed` | final | `terminal` | — | — | — |
| `error` | final | `terminal`, `failure` | — | — | — |

### B3.3 Events and transitions

| From | Event | Guard | Target | Actions | `reenter` |
|---|---|---|---|---|---|
| `pending` | _always_ | `should_skip` | `skipped` | — | — |
| `pending` | _always_ | `passes_preflight` | `submitting` | — | — |
| `pending` | _always_ | — | `error` | — | — |
| `submitting` | `ORDER_OPEN` | — | `open` | — | — |
| `submitting` | `ORDER_REJECTED` | — | `rejected` | `map_error` | — |
| `submitting` | `ORDER_UNKNOWN` | — | `resolving` | — | — |
| `submitting` | `SUBMIT_TIMEOUT` | — | `resolving` | — | — |
| `resolving` | `*` | — | _(internal)_ | `defer` | — |
| `open` | `EXEC` | — | `partially_filled` | `accumulate_fill`, `place_tp_ladder_once` | — |
| `open` | `UNWIND` | — | `unwinding` | — | — |
| `open` | `CLOSE` | — | `closing` | — | — |
| `partially_filled` | `EXEC` | `fully_filled` | `filled` | `accumulate_fill` | — |
| `partially_filled` | `EXEC` | — | `partially_filled` | `accumulate_fill` | yes |
| `partially_filled` | `UNWIND` | — | `unwinding` | — | — |
| `partially_filled` | `CLOSE` | — | `closing` | — | — |
| `filled` | `UNWIND` | — | `unwinding` | — | — |
| `filled` | `CLOSE` | — | `closing` | — | — |
| `closing` | `FLAT` | — | `closed` | — | — |
| `closing` | `CLOSE_FAILED` | — | `error` | — | — |

### B3.4 Invoked services

| In state | `id` | `src` | `onDone` | `onError` |
|---|---|---|---|---|
| `resolving` | `lookup` | `lookup_by_link_id` | `open` if `lookup_says_live`; `filled` if `lookup_says_filled`; `rejected` | `error` |
| `unwinding.cancel_children` | `cx` | `cancel_children_svc` | `unwinding.close_position` | `unwinding.close_position` |
| `unwinding.close_position` | `cl` | `reduce_only_close` | `unwinding.verify_flat` | `unwinding.close_position` if `close_attempts_left`; `unwinding.verify_sl` |
| `unwinding.verify_flat` | `vf` | `poll_until_flat` | `closed` if `is_flat`; `unwinding.close_position` if `close_attempts_left`; `unwinding.verify_sl` | `unwinding.verify_sl` |
| `unwinding.verify_sl` | `vs` | `assert_native_sl` | `error` | `error` |

### B3.5 Guards

| Guard | Polarity | Contract |
|---|---|---|
| `close_attempts_left` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `fully_filled` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `is_flat` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `lookup_says_filled` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `lookup_says_live` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `passes_preflight` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `should_skip` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |

### B3.6 Actions

All actions are `@cv_action`-wrapped (A1). A raising action writes `context["_fault"]`, aborts the transition and routes to this machine's fault state; the snapshot writer refuses to persist a faulted context (MUST-01).

| Action |
|---|
| `accumulate_fill` |
| `arm_submit_timeout` |
| `bump_close_attempts` |
| `defer` |
| `map_error` |
| `mark_incomplete` |
| `note_cancel_failure` |
| `place_tp_ladder_once` |
| `raise_naked_position_alert` |
| `read_authoritative_position_qty` |
| `size_from_profile` |
| `submit_entry_order` |

### B3.7 Invariants

| ID | Invariant |
|---|---|
| **INV-B3-a** | `sized_qty` is computed exactly once, from the profile snapshot taken at `pending`; a profile edit mid-fan-out never changes an in-flight leg. |
| **INV-B3-b** | `place_tp_ladder_once` is idempotent - re-entering `open` after a restore does not create a second ladder. |
| **INV-B3-c** | `verify_flat` reads the **authoritative exchange position**, never local state; `qty_drift` is recorded, not assumed zero. |
| **INV-B3-d** | `verify_sl` runs after every close attempt: a leg may not leave the unwind while a position with no native SL exists (C-2.6). |
| **INV-B3-e** | `close_attempts` is bounded; exhaustion reaches `error`, which is a **visible** state, not a retry loop. |
| **INV-5** | No delivered `EXEC` is unaccounted for across `submitting`, `resolving` and the unwind. |

### B3.8 Implementation notes

- `resolving` exists for the `ORDER_UNKNOWN` case and resolves by `orderLinkId` lookup (C-2.10), never by blind resubmission.
- Retry loops route through a distinct intermediate state rather than an `always` self-target (A4 / LC-02).
- **Corrected 2026-10-01 (C-04 / C-07b class, E50-S01, `tools/lint_statecharts.py` CV-LINT-KILL-ANCESTOR / CV-LINT-FALLTHROUGH):** root `on.KILL` → existing `error` with `audit_kill`, so every invoking state has a kill ancestor (C-04; no new guard, no new business transition); no guarded-only transitions, so no fall-through arm is needed.

---

## B4 — EmulatedAlgo - OCO

| | |
|---|---|
| **Machine `id`** | `oco` |
| **Root type** | `compound`, initial `arming` |
| **Owning epic** | E33 - Emulated algos (OCO, iceberg, TWAP, chase) |
| **Schema owner** | 24-internal-schemas.md §10.2 (OCO), §10.1 (common algo model) |
| **Fit (research)** | Good - the best algo fit; event-driven and timing-light |
| **Event rate** | low |
| **States / leaves / finals** | 11 / 11 / 3 |

**Purpose.** One-cancels-other: two child orders race, the winner settles and the loser is cancelled, with an explicit overshoot path for the double-fill case.

**Why this shape.** `overshoot` is a **named state**, not an error branch. A genuine double fill (both legs filling before either cancel lands) is a real market outcome; it must be visible, journalled and corrected by a reduce-only market order - not swallowed.

### B4.1 Contract (normative)

```json
{
  "id": "oco",
  "actionErrorPolicy": "rollback",
  "onUnhandled": "defer",
  "guardErrorPolicy": "raise",
  "strictTargets": true,
  "strict": true,
  "spawnBlockingTimeout": 5000,
  "on": {
    "KILL": {
      "target": "#oco.failed",
      "actions": [
        "audit_kill"
      ]
    }
  },
  "initial": "arming",
  "context": {
    "algo_id": null,
    "mode": "reduce_other",
    "leg_a_id": null,
    "leg_b_id": null,
    "filled_a": "0",
    "filled_b": "0",
    "settle_failures": 0,
    "excess_qty": "0"
  },
  "states": {
    "arming": {
      "invoke": {
        "id": "arm",
        "src": "submit_both_legs",
        "onDone": {
          "target": "#oco.racing",
          "actions": [
            "record_child_ids"
          ]
        },
        "onError": {
          "target": "#oco.failed",
          "actions": [
            "map_error"
          ]
        }
      }
    },
    "racing": {
      "on": {
        "LEG_A_FILL": [
          {
            "target": "#oco.overshoot",
            "guard": "position_overshoots",
            "actions": [
              "record_fill_a"
            ]
          },
          {
            "target": "#oco.settling_b",
            "actions": [
              "record_fill_a"
            ]
          }
        ],
        "LEG_B_FILL": [
          {
            "target": "#oco.overshoot",
            "guard": "position_overshoots",
            "actions": [
              "record_fill_b"
            ]
          },
          {
            "target": "#oco.settling_a",
            "actions": [
              "record_fill_b"
            ]
          }
        ],
        "POSITION_FLAT": [
          {
            "target": "#oco.cancelling_all",
            "guard": "cancel_on_position_flat"
          },
          {
            "actions": [
              "audit_guard_denied"
            ]
          }
        ],
        "USER_CANCEL": {
          "target": "#oco.cancelling_all"
        }
      }
    },
    "settling_b": {
      "invoke": {
        "id": "settle_b",
        "src": "settle_other_leg",
        "onDone": [
          {
            "target": "#oco.completing",
            "guard": "other_leg_terminal"
          },
          {
            "target": "#oco.racing",
            "guard": "partial_settle_remaining",
            "reenter": true
          }
        ],
        "onError": [
          {
            "target": "#oco.reconciling",
            "guard": "error_is_order_gone"
          },
          {
            "target": "#oco.settling_b",
            "reenter": true,
            "guard": "settle_retries_left",
            "actions": [
              "bump_settle_failures"
            ]
          },
          {
            "target": "#oco.failed",
            "actions": [
              "raise_critical_alert"
            ]
          }
        ]
      },
      "on": {}
    },
    "settling_a": {
      "invoke": {
        "id": "settle_a",
        "src": "settle_other_leg",
        "onDone": [
          {
            "target": "#oco.completing",
            "guard": "other_leg_terminal"
          },
          {
            "target": "#oco.racing",
            "guard": "partial_settle_remaining",
            "reenter": true
          }
        ],
        "onError": [
          {
            "target": "#oco.reconciling",
            "guard": "error_is_order_gone"
          },
          {
            "target": "#oco.settling_a",
            "reenter": true,
            "guard": "settle_retries_left",
            "actions": [
              "bump_settle_failures"
            ]
          },
          {
            "target": "#oco.failed",
            "actions": [
              "raise_critical_alert"
            ]
          }
        ]
      },
      "on": {}
    },
    "overshoot": {
      "entry": [
        "raise_warning_alert",
        "journal_double_fill"
      ],
      "invoke": {
        "id": "flatten_excess",
        "src": "reduce_only_market_excess",
        "onDone": {
          "target": "#oco.completing"
        },
        "onError": {
          "target": "#oco.failed",
          "actions": [
            "raise_critical_alert"
          ]
        }
      }
    },
    "reconciling": {
      "invoke": {
        "id": "rec",
        "src": "reconcile_children",
        "onDone": {
          "target": "#oco.completing"
        },
        "onError": {
          "target": "#oco.failed",
          "actions": [
            "raise_critical_alert"
          ]
        }
      }
    },
    "cancelling_all": {
      "invoke": {
        "id": "ca",
        "src": "cancel_all_children",
        "onDone": {
          "target": "#oco.cancelled"
        },
        "onError": {
          "target": "#oco.failed",
          "actions": [
            "raise_critical_alert"
          ]
        }
      }
    },
    "completing": {
      "on": {
        "CHILDREN_TERMINAL": {
          "target": "#oco.completed"
        },
        "LEG_A_FILL": [
          {
            "target": "#oco.overshoot",
            "guard": "position_overshoots",
            "actions": [
              "record_fill_a"
            ]
          },
          {
            "actions": [
              "record_fill_a"
            ]
          }
        ],
        "LEG_B_FILL": [
          {
            "target": "#oco.overshoot",
            "guard": "position_overshoots",
            "actions": [
              "record_fill_b"
            ]
          },
          {
            "actions": [
              "record_fill_b"
            ]
          }
        ]
      }
    },
    "completed": {
      "type": "final",
      "tags": [
        "terminal"
      ]
    },
    "cancelled": {
      "type": "final",
      "tags": [
        "terminal"
      ]
    },
    "failed": {
      "type": "final",
      "tags": [
        "terminal",
        "failure"
      ]
    }
  }
}
```

### B4.2 States

| State | Kind | Tags | Entry actions | Exit actions | Defers `*` |
|---|---|---|---|---|---|
| `arming` | atomic | — | — | — | — |
| `racing` | atomic | — | — | — | yes |
| `settling_b` | atomic | — | — | — | yes |
| `settling_a` | atomic | — | — | — | yes |
| `overshoot` | atomic | — | `raise_warning_alert`, `journal_double_fill` | — | — |
| `reconciling` | atomic | — | — | — | — |
| `cancelling_all` | atomic | — | — | — | — |
| `completing` | atomic | — | — | — | — |
| `completed` | final | `terminal` | — | — | — |
| `cancelled` | final | `terminal` | — | — | — |
| `failed` | final | `terminal`, `failure` | — | — | — |

### B4.3 Events and transitions

| From | Event | Guard | Target | Actions | `reenter` |
|---|---|---|---|---|---|
| `racing` | `LEG_A_FILL` | `position_overshoots` | `overshoot` | `record_fill_a` | — |
| `racing` | `LEG_A_FILL` | — | `settling_b` | `record_fill_a` | — |
| `racing` | `LEG_B_FILL` | `position_overshoots` | `overshoot` | `record_fill_b` | — |
| `racing` | `LEG_B_FILL` | — | `settling_a` | `record_fill_b` | — |
| `racing` | `POSITION_FLAT` | `cancel_on_position_flat` | `cancelling_all` | — | — |
| `racing` | `USER_CANCEL` | — | `cancelling_all` | — | — |
| `racing` | `*` | — | _(internal)_ | `defer` | — |
| `settling_b` | `*` | — | _(internal)_ | `defer` | — |
| `settling_a` | `*` | — | _(internal)_ | `defer` | — |
| `completing` | `CHILDREN_TERMINAL` | — | `completed` | — | — |
| `completing` | `LEG_A_FILL` *(Corrected 2026-10-10, #2204, OC-03)* | `position_overshoots` | `overshoot` | `record_fill_a` | — |
| `completing` | `LEG_A_FILL` *(Corrected 2026-10-10, #2204, OC-03)* | — | _(internal)_ | `record_fill_a` | — |
| `completing` | `LEG_B_FILL` *(Corrected 2026-10-10, #2204, OC-03)* | `position_overshoots` | `overshoot` | `record_fill_b` | — |
| `completing` | `LEG_B_FILL` *(Corrected 2026-10-10, #2204, OC-03)* | — | _(internal)_ | `record_fill_b` | — |

### B4.4 Invoked services

| In state | `id` | `src` | `onDone` | `onError` |
|---|---|---|---|---|
| `arming` | `arm` | `submit_both_legs` | `racing` | `failed` |
| `settling_b` | `settle_b` | `settle_other_leg` | `completing` if `other_leg_terminal`; `racing` if `partial_settle_remaining` | `reconciling` if `error_is_order_gone`; `settling_b` if `settle_retries_left`; `failed` |
| `settling_a` | `settle_a` | `settle_other_leg` | `completing` if `other_leg_terminal`; `racing` if `partial_settle_remaining` | `reconciling` if `error_is_order_gone`; `settling_a` if `settle_retries_left`; `failed` |
| `overshoot` | `flatten_excess` | `reduce_only_market_excess` | `completing` | `failed` |
| `reconciling` | `rec` | `reconcile_children` | `completing` | `failed` |
| `cancelling_all` | `ca` | `cancel_all_children` | `cancelled` | `failed` |

### B4.5 Guards

| Guard | Polarity | Contract |
|---|---|---|
| `cancel_on_position_flat` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `error_is_order_gone` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `other_leg_terminal` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `partial_settle_remaining` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `position_overshoots` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `settle_retries_left` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |

### B4.6 Actions

All actions are `@cv_action`-wrapped (A1). A raising action writes `context["_fault"]`, aborts the transition and routes to this machine's fault state; the snapshot writer refuses to persist a faulted context (MUST-01).

| Action |
|---|
| `bump_settle_failures` |
| `defer` |
| `journal_double_fill` |
| `map_error` |
| `raise_critical_alert` |
| `raise_warning_alert` |
| `record_child_ids` |
| `record_fill_a` |
| `record_fill_b` |

### B4.7 Invariants

| ID | Invariant |
|---|---|
| **INV-B4-a** | `filled_a` and `filled_b` are both recorded before any settlement decision; the machine never assumes a single winner. |
| **INV-B4-b** | Reaching `completed` implies both children are terminal (`CHILDREN_TERMINAL` observed), never merely 'cancel requested'. |
| **INV-B4-c** | `reduce_only_market_excess` is reduce-only by construction; the overshoot correction can never open a position. |
| **INV-B4-d** | A fill on the other leg **during settlement** is applied, not dropped - this is what the wildcard deferral on the settling states buys (E33-S01 acceptance). |
| **INV-B4-e** | *(Corrected 2026-10-10, #2204, OC-03)* A leg fill reaching `completing` (live or replayed from the defer buffer) is **consumed, never re-deferred**: it is recorded (`record_fill_a`/`record_fill_b`) and, if it overshoots the position, routed to `overshoot` for the reduce-only correction (B4.3). |

### B4.8 Implementation notes

- Timing-light: no in-machine timers at all, which is why this rates the cleanest of the four algos.
- **Corrected 2026-10-01 (C-04 / C-07b class, E50-S01, `tools/lint_statecharts.py` CV-LINT-KILL-ANCESTOR / CV-LINT-FALLTHROUGH):** root `on.KILL` → existing `failed` with `audit_kill`, so every invoking state has a kill ancestor (C-04; no new guard, no new business transition); ordered unguarded `audit_guard_denied` arm (internal, B18 shape) appended after the guarded arms of `racing.POSITION_FLAT` so a guard-denied event is audited, never silently deferred (C-07b).
- **Corrected 2026-10-10 (#2204, OC-03, `docs/research/xstate/33-r5-findings-register.md` §6):** `completing` handled only `CHILDREN_TERMINAL`, so a late `LEG_A_FILL`/`LEG_B_FILL` correctly deferred by a settling state was replayed into `completing` and re-deferred forever (INV-B4-d broken). `completing` now records the fill on an unguarded internal arm and sends an overshooting fill to `overshoot` on a guarded first arm. Each `overshoot → completing → overshoot` lap needs another external fill, so this is not an invoke cycle. Chart `version: 1`; context shape unchanged, so no upcaster.

---

## B5 — EmulatedAlgo - Iceberg

| | |
|---|---|
| **Machine `id`** | `iceberg` |
| **Root type** | `compound`, initial `pending` |
| **Owning epic** | E33 - Emulated algos (OCO, iceberg, TWAP, chase) |
| **Schema owner** | 24-internal-schemas.md §10.3 (iceberg), §10.1 |
| **Fit (research)** | Workaround - structure and bounds only; all timing external |
| **Event rate** | low |
| **States / leaves / finals** | 13 / 13 / 3 |

**Purpose.** Slice a large order into visible child slices, refilling as each slice completes, with post-only reject handling and a cooldown.

**Why this shape.** Slice counting routes through distinct states (`submitting_slice -> working -> waiting_refill -> submitting_slice`) rather than an accumulate-until-threshold `always` self-target, which deadlocks (LC-02; probe A10 parked at `loop` with `n==1`, `is_running == True` and no error, while A19 proved the distinct-intermediate-state form converges).

### B5.1 Contract (normative)

```json
{
  "id": "iceberg",
  "actionErrorPolicy": "rollback",
  "onUnhandled": "defer",
  "guardErrorPolicy": "raise",
  "strictTargets": true,
  "strict": true,
  "spawnBlockingTimeout": 5000,
  "on": {
    "KILL": {
      "target": "#iceberg.failed",
      "actions": [
        "audit_kill"
      ]
    }
  },
  "initial": "pending",
  "context": {
    "algo_id": null,
    "total_qty": "0",
    "remaining_qty": "0",
    "slices_done": 0,
    "max_slices": 450,
    "active_child_id": null,
    "post_only_rejects": 0,
    "next_refill_at_us": null,
    "failure_count": 0
  },
  "states": {
    "pending": {
      "always": [
        {
          "target": "#iceberg.failed",
          "guard": "preflight_invalid"
        },
        {
          "target": "#iceberg.submitting_slice"
        }
      ]
    },
    "submitting_slice": {
      "entry": [
        "compute_slice_qty",
        "bump_slices_done"
      ],
      "invoke": {
        "id": "slice",
        "src": "submit_child",
        "onDone": {
          "target": "#iceberg.working",
          "actions": [
            "record_child"
          ]
        },
        "onError": [
          {
            "target": "#iceberg.repricing",
            "guard": "is_post_only_reject"
          },
          {
            "target": "#iceberg.failed",
            "guard": "failures_exhausted"
          },
          {
            "target": "#iceberg.submitting_slice",
            "reenter": true,
            "actions": [
              "bump_failure"
            ]
          }
        ]
      },
      "on": {}
    },
    "working": {
      "on": {
        "CHILD_FILLED": [
          {
            "target": "#iceberg.completing",
            "guard": "remaining_is_zero",
            "actions": [
              "apply_fill"
            ]
          },
          {
            "target": "#iceberg.waiting_refill",
            "actions": [
              "apply_fill"
            ]
          }
        ],
        "CHILD_PARTIAL": {
          "actions": [
            "apply_fill"
          ]
        },
        "CHILD_CANCELLED": {
          "target": "#iceberg.waiting_refill"
        },
        "USER_PAUSE": {
          "target": "#iceberg.paused"
        },
        "WS_DISCONNECT": [
          {
            "target": "#iceberg.paused",
            "guard": "on_disconnect_is_freeze"
          },
          {
            "actions": [
              "audit_guard_denied"
            ]
          }
        ],
        "USER_CANCEL": {
          "target": "#iceberg.cancelling"
        },
        "POSITION_FLAT": [
          {
            "target": "#iceberg.cancelling",
            "guard": "cancel_on_position_flat"
          },
          {
            "actions": [
              "audit_guard_denied"
            ]
          }
        ],
        "MAX_DURATION": {
          "target": "#iceberg.cancelling"
        }
      }
    },
    "waiting_refill": {
      "entry": [
        "schedule_refill_deadline"
      ],
      "on": {
        "REFILL_DUE": [
          {
            "target": "#iceberg.completing",
            "guard": "remaining_is_zero"
          },
          {
            "target": "#iceberg.completing",
            "guard": "slices_exhausted"
          },
          {
            "target": "#iceberg.submitting_slice"
          }
        ],
        "USER_PAUSE": {
          "target": "#iceberg.paused"
        },
        "USER_CANCEL": {
          "target": "#iceberg.cancelling"
        }
      }
    },
    "repricing": {
      "entry": [
        "bump_post_only_rejects"
      ],
      "always": [
        {
          "target": "#iceberg.cooling_down",
          "guard": "two_consecutive_post_only_rejects"
        },
        {
          "target": "#iceberg.submitting_slice"
        }
      ]
    },
    "cooling_down": {
      "entry": [
        "schedule_cooldown_deadline",
        "reset_post_only_rejects"
      ],
      "on": {
        "COOLDOWN_DUE": {
          "target": "#iceberg.submitting_slice"
        }
      }
    },
    "paused": {
      "on": {
        "RESUME": {
          "target": "#iceberg.reconciling"
        },
        "USER_CANCEL": {
          "target": "#iceberg.cancelling"
        }
      }
    },
    "reconciling": {
      "invoke": {
        "id": "rec",
        "src": "reconcile_children",
        "onDone": {
          "target": "#iceberg.working"
        },
        "onError": {
          "target": "#iceberg.failed"
        }
      }
    },
    "cancelling": {
      "invoke": {
        "id": "cx",
        "src": "cancel_all_children",
        "onDone": {
          "target": "#iceberg.cancelled"
        },
        "onError": {
          "target": "#iceberg.failed"
        }
      }
    },
    "completing": {
      "on": {
        "CHILDREN_TERMINAL": {
          "target": "#iceberg.completed"
        }
      }
    },
    "completed": {
      "type": "final",
      "tags": [
        "terminal"
      ]
    },
    "cancelled": {
      "type": "final",
      "tags": [
        "terminal"
      ]
    },
    "failed": {
      "type": "final",
      "tags": [
        "terminal",
        "failure"
      ]
    }
  }
}
```

### B5.2 States

| State | Kind | Tags | Entry actions | Exit actions | Defers `*` |
|---|---|---|---|---|---|
| `pending` | atomic | — | — | — | — |
| `submitting_slice` | atomic | — | `compute_slice_qty`, `bump_slices_done` | — | yes |
| `working` | atomic | — | — | — | — |
| `waiting_refill` | atomic | — | `schedule_refill_deadline` | — | — |
| `repricing` | atomic | — | `bump_post_only_rejects` | — | — |
| `cooling_down` | atomic | — | `schedule_cooldown_deadline`, `reset_post_only_rejects` | — | — |
| `paused` | atomic | — | — | — | — |
| `reconciling` | atomic | — | — | — | — |
| `cancelling` | atomic | — | — | — | — |
| `completing` | atomic | — | — | — | — |
| `completed` | final | `terminal` | — | — | — |
| `cancelled` | final | `terminal` | — | — | — |
| `failed` | final | `terminal`, `failure` | — | — | — |

### B5.3 Events and transitions

| From | Event | Guard | Target | Actions | `reenter` |
|---|---|---|---|---|---|
| `pending` | _always_ | `preflight_invalid` | `failed` | — | — |
| `pending` | _always_ | — | `submitting_slice` | — | — |
| `submitting_slice` | `*` | — | _(internal)_ | `defer` | — |
| `working` | `CHILD_FILLED` | `remaining_is_zero` | `completing` | `apply_fill` | — |
| `working` | `CHILD_FILLED` | — | `waiting_refill` | `apply_fill` | — |
| `working` | `CHILD_PARTIAL` | — | _(internal)_ | `apply_fill` | — |
| `working` | `CHILD_CANCELLED` | — | `waiting_refill` | — | — |
| `working` | `USER_PAUSE` | — | `paused` | — | — |
| `working` | `WS_DISCONNECT` | `on_disconnect_is_freeze` | `paused` | — | — |
| `working` | `USER_CANCEL` | — | `cancelling` | — | — |
| `working` | `POSITION_FLAT` | `cancel_on_position_flat` | `cancelling` | — | — |
| `working` | `MAX_DURATION` | — | `cancelling` | — | — |
| `waiting_refill` | `REFILL_DUE` | `remaining_is_zero` | `completing` | — | — |
| `waiting_refill` | `REFILL_DUE` | `slices_exhausted` | `completing` | — | — |
| `waiting_refill` | `REFILL_DUE` | — | `submitting_slice` | — | — |
| `waiting_refill` | `USER_PAUSE` | — | `paused` | — | — |
| `waiting_refill` | `USER_CANCEL` | — | `cancelling` | — | — |
| `repricing` | _always_ | `two_consecutive_post_only_rejects` | `cooling_down` | — | — |
| `repricing` | _always_ | — | `submitting_slice` | — | — |
| `cooling_down` | `COOLDOWN_DUE` | — | `submitting_slice` | — | — |
| `paused` | `RESUME` | — | `reconciling` | — | — |
| `paused` | `USER_CANCEL` | — | `cancelling` | — | — |
| `completing` | `CHILDREN_TERMINAL` | — | `completed` | — | — |

### B5.4 Invoked services

| In state | `id` | `src` | `onDone` | `onError` |
|---|---|---|---|---|
| `submitting_slice` | `slice` | `submit_child` | `working` | `repricing` if `is_post_only_reject`; `failed` if `failures_exhausted`; `submitting_slice` |
| `reconciling` | `rec` | `reconcile_children` | `working` | `failed` |
| `cancelling` | `cx` | `cancel_all_children` | `cancelled` | `failed` |

### B5.5 Guards

| Guard | Polarity | Contract |
|---|---|---|
| `cancel_on_position_flat` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `failures_exhausted` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `is_post_only_reject` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `on_disconnect_is_freeze` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `preflight_invalid` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `remaining_is_zero` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `slices_exhausted` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `two_consecutive_post_only_rejects` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |

### B5.6 Actions

All actions are `@cv_action`-wrapped (A1). A raising action writes `context["_fault"]`, aborts the transition and routes to this machine's fault state; the snapshot writer refuses to persist a faulted context (MUST-01).

| Action |
|---|
| `apply_fill` |
| `bump_failure` |
| `bump_post_only_rejects` |
| `bump_slices_done` |
| `compute_slice_qty` |
| `defer` |
| `record_child` |
| `reset_post_only_rejects` |
| `schedule_cooldown_deadline` |
| `schedule_refill_deadline` |

### B5.7 Invariants

| ID | Invariant |
|---|---|
| **INV-B5-a** | The sum of submitted slice quantities is `<= total_qty`; `remaining_qty` is never negative. |
| **INV-B5-b** | At most one child slice is live at a time (`active_child_id` is single-valued). |
| **INV-B5-c** | `slices_done <= max_slices`; exhaustion reaches a completion path, never an unbounded loop. |
| **INV-B5-d** | `next_refill_at_us` and the cooldown deadline are absolute timestamps in context, re-armed from context on restore - including the 'deadline expired while the process was down' case. |
| **INV-B5-e** | Two consecutive post-only rejects force `cooling_down`; the machine never busy-loops against a crossed book. |

### B5.8 Implementation notes

- `WS_DISCONNECT` is policy-driven via `on_disconnect_is_freeze`: freeze-and-pause or cancel, per the algo's configured disconnect policy (24 §10.1).
- **Corrected 2026-10-01 (C-04 / C-07b class, E50-S01, `tools/lint_statecharts.py` CV-LINT-KILL-ANCESTOR / CV-LINT-FALLTHROUGH):** root `on.KILL` → existing `failed` with `audit_kill`, so every invoking state has a kill ancestor (C-04; no new guard, no new business transition); ordered unguarded `audit_guard_denied` arm (internal, B18 shape) appended after the guarded arms of `working.WS_DISCONNECT`, `working.POSITION_FLAT` so a guard-denied event is audited, never silently deferred (C-07b).

---

## B6 — EmulatedAlgo - TWAP

| | |
|---|---|
| **Machine `id`** | `twap` |
| **Root type** | `compound`, initial `pending` |
| **Owning epic** | E33 - Emulated algos (OCO, iceberg, TWAP, chase) |
| **Schema owner** | 24-internal-schemas.md §10.4 (TWAP), §10.1 |
| **Fit (research)** | Workaround - structure and bounds only; all timing external |
| **Event rate** | low |
| **States / leaves / finals** | 12 / 12 / 3 |

**Purpose.** Spread an order across a duration in slices, with a participation cap, a price limit, catch-up for missed slices and a final sweep.

**Why this shape.** Every slice boundary is precomputed as an **absolute deadline list in context** (`slice_deadlines_us`) and registered with the external `MonotonicScheduler` on arming. Nothing here uses `after`: measured, a 10 ms `after` fires 2.25 s late under 500 busy interpreters, and pending timers do not survive `from_snapshot` (LC-20, LC-26).

### B6.1 Contract (normative)

```json
{
  "id": "twap",
  "actionErrorPolicy": "rollback",
  "onUnhandled": "defer",
  "guardErrorPolicy": "raise",
  "strictTargets": true,
  "strict": true,
  "spawnBlockingTimeout": 5000,
  "on": {
    "KILL": {
      "target": "#twap.failed",
      "actions": [
        "audit_kill"
      ]
    }
  },
  "initial": "pending",
  "context": {
    "algo_id": null,
    "slices_total": 0,
    "slices_done": 0,
    "total_qty": "0",
    "remaining_qty": "0",
    "shortfall_qty": "0",
    "slice_deadlines_us": [],
    "end_at_us": null,
    "catch_up": "next_slice",
    "price_limit": null,
    "failure_count": 0
  },
  "states": {
    "pending": {
      "entry": [
        "precompute_all_slice_deadlines",
        "register_deadlines_with_scheduler"
      ],
      "always": [
        {
          "target": "#twap.failed",
          "guard": "preflight_invalid"
        },
        {
          "target": "#twap.armed"
        }
      ]
    },
    "armed": {
      "on": {
        "SLICE_DUE": [
          {
            "target": "#twap.price_blocked",
            "guard": "price_limit_breached"
          },
          {
            "target": "#twap.submitting_slice"
          }
        ],
        "DURATION_END": [
          {
            "target": "#twap.final_sweep",
            "guard": "final_market_sweep_and_remaining"
          },
          {
            "target": "#twap.completing"
          }
        ],
        "USER_PAUSE": {
          "target": "#twap.paused"
        },
        "WS_DISCONNECT": [
          {
            "target": "#twap.paused",
            "guard": "on_disconnect_is_freeze"
          },
          {
            "actions": [
              "audit_guard_denied"
            ]
          }
        ],
        "USER_CANCEL": {
          "target": "#twap.cancelling"
        },
        "MAX_DURATION": {
          "target": "#twap.cancelling"
        }
      }
    },
    "submitting_slice": {
      "entry": [
        "compute_slice_qty_with_participation_cap",
        "apply_catch_up",
        "bump_slices_done"
      ],
      "always": [
        {
          "target": "#twap.armed",
          "guard": "slice_qty_below_min_roll_forward"
        }
      ],
      "invoke": {
        "id": "slice",
        "src": "submit_child",
        "onDone": {
          "target": "#twap.armed",
          "actions": [
            "record_child"
          ]
        },
        "onError": [
          {
            "target": "#twap.failed",
            "guard": "failures_exhausted"
          },
          {
            "target": "#twap.armed",
            "actions": [
              "bump_failure",
              "record_shortfall"
            ]
          }
        ]
      },
      "on": {}
    },
    "price_blocked": {
      "entry": [
        "raise_price_limit_notice"
      ],
      "always": [
        {
          "target": "#twap.cancelling",
          "guard": "abort_on_price_limit"
        }
      ],
      "on": {
        "PRICE_OK": {
          "target": "#twap.armed"
        },
        "SLICE_DUE": {
          "actions": [
            "record_shortfall"
          ]
        },
        "DURATION_END": {
          "target": "#twap.completing"
        },
        "USER_CANCEL": {
          "target": "#twap.cancelling"
        }
      }
    },
    "final_sweep": {
      "invoke": {
        "id": "sweep",
        "src": "market_sweep_remainder",
        "onDone": {
          "target": "#twap.completing"
        },
        "onError": {
          "target": "#twap.failed",
          "actions": [
            "raise_warning_alert"
          ]
        }
      }
    },
    "paused": {
      "on": {
        "RESUME": {
          "target": "#twap.reconciling"
        },
        "USER_CANCEL": {
          "target": "#twap.cancelling"
        }
      }
    },
    "reconciling": {
      "entry": [
        "rearm_deadlines_from_context"
      ],
      "invoke": {
        "id": "rec",
        "src": "reconcile_children",
        "onDone": {
          "target": "#twap.armed"
        },
        "onError": {
          "target": "#twap.failed"
        }
      }
    },
    "cancelling": {
      "invoke": {
        "id": "cx",
        "src": "cancel_all_children",
        "onDone": {
          "target": "#twap.cancelled"
        },
        "onError": {
          "target": "#twap.failed"
        }
      }
    },
    "completing": {
      "on": {
        "CHILDREN_TERMINAL": {
          "target": "#twap.completed"
        }
      }
    },
    "completed": {
      "type": "final",
      "tags": [
        "terminal"
      ]
    },
    "cancelled": {
      "type": "final",
      "tags": [
        "terminal"
      ]
    },
    "failed": {
      "type": "final",
      "tags": [
        "terminal",
        "failure"
      ]
    }
  }
}
```

### B6.2 States

| State | Kind | Tags | Entry actions | Exit actions | Defers `*` |
|---|---|---|---|---|---|
| `pending` | atomic | — | `precompute_all_slice_deadlines`, `register_deadlines_with_scheduler` | — | — |
| `armed` | atomic | — | — | — | — |
| `submitting_slice` | atomic | — | `compute_slice_qty_with_participation_cap`, `apply_catch_up`, `bump_slices_done` | — | yes |
| `price_blocked` | atomic | — | `raise_price_limit_notice` | — | — |
| `final_sweep` | atomic | — | — | — | — |
| `paused` | atomic | — | — | — | — |
| `reconciling` | atomic | — | `rearm_deadlines_from_context` | — | — |
| `cancelling` | atomic | — | — | — | — |
| `completing` | atomic | — | — | — | — |
| `completed` | final | `terminal` | — | — | — |
| `cancelled` | final | `terminal` | — | — | — |
| `failed` | final | `terminal`, `failure` | — | — | — |

### B6.3 Events and transitions

| From | Event | Guard | Target | Actions | `reenter` |
|---|---|---|---|---|---|
| `pending` | _always_ | `preflight_invalid` | `failed` | — | — |
| `pending` | _always_ | — | `armed` | — | — |
| `armed` | `SLICE_DUE` | `price_limit_breached` | `price_blocked` | — | — |
| `armed` | `SLICE_DUE` | — | `submitting_slice` | — | — |
| `armed` | `DURATION_END` | `final_market_sweep_and_remaining` | `final_sweep` | — | — |
| `armed` | `DURATION_END` | — | `completing` | — | — |
| `armed` | `USER_PAUSE` | — | `paused` | — | — |
| `armed` | `WS_DISCONNECT` | `on_disconnect_is_freeze` | `paused` | — | — |
| `armed` | `USER_CANCEL` | — | `cancelling` | — | — |
| `armed` | `MAX_DURATION` | — | `cancelling` | — | — |
| `submitting_slice` | `*` | — | _(internal)_ | `defer` | — |
| `submitting_slice` | _always_ | `slice_qty_below_min_roll_forward` | `armed` | — | — |
| `price_blocked` | `PRICE_OK` | — | `armed` | — | — |
| `price_blocked` | `SLICE_DUE` | — | _(internal)_ | `record_shortfall` | — |
| `price_blocked` | `DURATION_END` | — | `completing` | — | — |
| `price_blocked` | `USER_CANCEL` | — | `cancelling` | — | — |
| `price_blocked` | _always_ | `abort_on_price_limit` | `cancelling` | — | — |
| `paused` | `RESUME` | — | `reconciling` | — | — |
| `paused` | `USER_CANCEL` | — | `cancelling` | — | — |
| `completing` | `CHILDREN_TERMINAL` | — | `completed` | — | — |

### B6.4 Invoked services

| In state | `id` | `src` | `onDone` | `onError` |
|---|---|---|---|---|
| `submitting_slice` | `slice` | `submit_child` | `armed` | `failed` if `failures_exhausted`; `armed` |
| `final_sweep` | `sweep` | `market_sweep_remainder` | `completing` | `failed` |
| `reconciling` | `rec` | `reconcile_children` | `armed` | `failed` |
| `cancelling` | `cx` | `cancel_all_children` | `cancelled` | `failed` |

### B6.5 Guards

| Guard | Polarity | Contract |
|---|---|---|
| `abort_on_price_limit` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `failures_exhausted` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `final_market_sweep_and_remaining` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `on_disconnect_is_freeze` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `preflight_invalid` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `price_limit_breached` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `slice_qty_below_min_roll_forward` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |

### B6.6 Actions

All actions are `@cv_action`-wrapped (A1). A raising action writes `context["_fault"]`, aborts the transition and routes to this machine's fault state; the snapshot writer refuses to persist a faulted context (MUST-01).

| Action |
|---|
| `apply_catch_up` |
| `bump_failure` |
| `bump_slices_done` |
| `compute_slice_qty_with_participation_cap` |
| `defer` |
| `precompute_all_slice_deadlines` |
| `raise_price_limit_notice` |
| `raise_warning_alert` |
| `rearm_deadlines_from_context` |
| `record_child` |
| `record_shortfall` |
| `register_deadlines_with_scheduler` |

### B6.7 Invariants

| ID | Invariant |
|---|---|
| **INV-B6-a** | `slices_done <= slices_total`, and submitted quantity plus `shortfall_qty` equals `total_qty` at completion. |
| **INV-B6-b** | `rearm_deadlines_from_context` is the only way deadlines come back after a restore; deadlines that expired during downtime are resolved by catch-up, not silently skipped. |
| **INV-B6-c** | A slice below the instrument minimum rolls forward into the next slice rather than being submitted or dropped. |
| **INV-B6-d** | `price_blocked` is a **state**, not a skipped slice: time spent blocked is visible and recorded as shortfall. |
| **INV-B6-e** | Slice-interval error p95 `<= 100 ms` with 500 resident order machines (E33-S03 acceptance). |

- **Corrected 2026-10-01 (C-04 / C-07b class, E50-S01, `tools/lint_statecharts.py` CV-LINT-KILL-ANCESTOR / CV-LINT-FALLTHROUGH):** root `on.KILL` → existing `failed` with `audit_kill`, so every invoking state has a kill ancestor (C-04; no new guard, no new business transition); ordered unguarded `audit_guard_denied` arm (internal, B18 shape) appended after the guarded arms of `armed.WS_DISCONNECT` so a guard-denied event is audited, never silently deferred (C-07b).

---

## B7 — EmulatedAlgo - Chase

| | |
|---|---|
| **Machine `id`** | `chase` |
| **Root type** | `compound`, initial `arming` |
| **Owning epic** | E33 - Emulated algos (OCO, iceberg, TWAP, chase) |
| **Schema owner** | 24-internal-schemas.md §10.5 (chase / pegged limit), §10.1 |
| **Fit (research)** | Workaround - the weakest of the four algos |
| **Event rate** | input bounded to <= 10 Hz by contract |
| **States / leaves / finals** | 13 / 13 / 3 |

**Purpose.** A pegged limit order that reprices toward a moving book target, bounded in ticks, repricings and wall-clock time.

**Why this shape.** The reprice interval is a **monotonic guard over `last_reprice_us`**, not a timer: `drift_over_threshold_and_interval_elapsed_and_budget_ok` is a pure predicate over context and the incoming target. The 200 ms nominal interval has no timing headroom on Windows (measured ~10.9 ms drift on a 5 ms sleep with an idle loop - the ~15.6 ms platform timer floor showing through), so an `after`-based design is not viable.

### B7.1 Contract (normative)

```json
{
  "id": "chase",
  "actionErrorPolicy": "rollback",
  "onUnhandled": "defer",
  "guardErrorPolicy": "raise",
  "strictTargets": true,
  "strict": true,
  "spawnBlockingTimeout": 5000,
  "on": {
    "KILL": {
      "target": "#chase.failed",
      "actions": [
        "audit_kill"
      ]
    }
  },
  "initial": "arming",
  "context": {
    "algo_id": null,
    "arm_price": null,
    "target_price": null,
    "child_id": null,
    "repricings": 0,
    "max_repricings": 200,
    "max_chase_ticks": 0,
    "last_reprice_us": 0,
    "reprice_interval_us": 200000,
    "timeout_at_us": null,
    "failure_count": 0
  },
  "states": {
    "arming": {
      "invoke": {
        "id": "arm",
        "src": "submit_initial_limit",
        "onDone": {
          "target": "#chase.working",
          "actions": [
            "record_child",
            "stamp_arm_price"
          ]
        },
        "onError": {
          "target": "#chase.failed",
          "actions": [
            "map_error"
          ]
        }
      }
    },
    "working": {
      "on": {
        "BOOK_TARGET_MOVED": [
          {
            "target": "#chase.bound_exceeded",
            "guard": "beyond_max_chase_ticks"
          },
          {
            "target": "#chase.bound_exceeded",
            "guard": "repricings_exhausted"
          },
          {
            "target": "#chase.repricing",
            "guard": "drift_over_threshold_and_interval_elapsed_and_budget_ok"
          },
          {
            "actions": [
              "audit_guard_denied"
            ]
          }
        ],
        "CHILD_FILLED": {
          "target": "#chase.completing",
          "actions": [
            "apply_fill"
          ]
        },
        "CHILD_PARTIAL": {
          "actions": [
            "apply_fill"
          ]
        },
        "TIMEOUT": {
          "target": "#chase.timing_out"
        },
        "RATE_BUDGET_EXHAUSTED": {
          "target": "#chase.paused"
        },
        "USER_PAUSE": {
          "target": "#chase.paused"
        },
        "WS_DISCONNECT": [
          {
            "target": "#chase.paused",
            "guard": "on_disconnect_is_freeze"
          },
          {
            "actions": [
              "audit_guard_denied"
            ]
          }
        ],
        "USER_CANCEL": {
          "target": "#chase.cancelling"
        }
      }
    },
    "repricing": {
      "entry": [
        "compute_target_excluding_own_size",
        "bump_repricings",
        "stamp_last_reprice"
      ],
      "invoke": {
        "id": "amend",
        "src": "amend_child_price",
        "onDone": {
          "target": "#chase.working"
        },
        "onError": [
          {
            "target": "#chase.completing",
            "guard": "error_is_order_not_found_after_fill"
          },
          {
            "target": "#chase.failed",
            "guard": "failures_exhausted"
          },
          {
            "target": "#chase.working",
            "actions": [
              "bump_failure"
            ]
          }
        ]
      },
      "on": {}
    },
    "bound_exceeded": {
      "entry": [
        "raise_warning_alert"
      ],
      "always": [
        {
          "target": "#chase.timing_out",
          "guard": "on_timeout_is_market"
        },
        {
          "target": "#chase.cancelling",
          "guard": "on_timeout_is_cancel"
        },
        {
          "target": "#chase.parked"
        }
      ]
    },
    "timing_out": {
      "always": [
        {
          "target": "#chase.market_converting",
          "guard": "on_timeout_is_market"
        },
        {
          "target": "#chase.cancelling",
          "guard": "on_timeout_is_cancel"
        },
        {
          "target": "#chase.parked"
        }
      ]
    },
    "market_converting": {
      "invoke": {
        "id": "mkt",
        "src": "convert_to_market",
        "onDone": {
          "target": "#chase.completing"
        },
        "onError": {
          "target": "#chase.failed"
        }
      }
    },
    "parked": {
      "tags": [
        "left_working"
      ],
      "on": {
        "CHILD_FILLED": {
          "target": "#chase.completing"
        },
        "USER_CANCEL": {
          "target": "#chase.cancelling"
        }
      }
    },
    "paused": {
      "on": {
        "RESUME": {
          "target": "#chase.working"
        },
        "USER_CANCEL": {
          "target": "#chase.cancelling"
        }
      }
    },
    "cancelling": {
      "invoke": {
        "id": "cx",
        "src": "cancel_child",
        "onDone": {
          "target": "#chase.cancelled"
        },
        "onError": {
          "target": "#chase.failed"
        }
      }
    },
    "completing": {
      "on": {
        "CHILDREN_TERMINAL": {
          "target": "#chase.completed"
        }
      }
    },
    "completed": {
      "type": "final",
      "tags": [
        "terminal"
      ]
    },
    "cancelled": {
      "type": "final",
      "tags": [
        "terminal"
      ]
    },
    "failed": {
      "type": "final",
      "tags": [
        "terminal",
        "failure"
      ]
    }
  }
}
```

### B7.2 States

| State | Kind | Tags | Entry actions | Exit actions | Defers `*` |
|---|---|---|---|---|---|
| `arming` | atomic | — | — | — | — |
| `working` | atomic | — | — | — | — |
| `repricing` | atomic | — | `compute_target_excluding_own_size`, `bump_repricings`, `stamp_last_reprice` | — | yes |
| `bound_exceeded` | atomic | — | `raise_warning_alert` | — | — |
| `timing_out` | atomic | — | — | — | — |
| `market_converting` | atomic | — | — | — | — |
| `parked` | atomic | `left_working` | — | — | — |
| `paused` | atomic | — | — | — | — |
| `cancelling` | atomic | — | — | — | — |
| `completing` | atomic | — | — | — | — |
| `completed` | final | `terminal` | — | — | — |
| `cancelled` | final | `terminal` | — | — | — |
| `failed` | final | `terminal`, `failure` | — | — | — |

### B7.3 Events and transitions

| From | Event | Guard | Target | Actions | `reenter` |
|---|---|---|---|---|---|
| `working` | `BOOK_TARGET_MOVED` | `beyond_max_chase_ticks` | `bound_exceeded` | — | — |
| `working` | `BOOK_TARGET_MOVED` | `repricings_exhausted` | `bound_exceeded` | — | — |
| `working` | `BOOK_TARGET_MOVED` | `drift_over_threshold_and_interval_elapsed_and_budget_ok` | `repricing` | — | — |
| `working` | `CHILD_FILLED` | — | `completing` | `apply_fill` | — |
| `working` | `CHILD_PARTIAL` | — | _(internal)_ | `apply_fill` | — |
| `working` | `TIMEOUT` | — | `timing_out` | — | — |
| `working` | `RATE_BUDGET_EXHAUSTED` | — | `paused` | — | — |
| `working` | `USER_PAUSE` | — | `paused` | — | — |
| `working` | `WS_DISCONNECT` | `on_disconnect_is_freeze` | `paused` | — | — |
| `working` | `USER_CANCEL` | — | `cancelling` | — | — |
| `repricing` | `*` | — | _(internal)_ | `defer` | — |
| `bound_exceeded` | _always_ | `on_timeout_is_market` | `timing_out` | — | — |
| `bound_exceeded` | _always_ | `on_timeout_is_cancel` | `cancelling` | — | — |
| `bound_exceeded` | _always_ | — | `parked` | — | — |
| `timing_out` | _always_ | `on_timeout_is_market` | `market_converting` | — | — |
| `timing_out` | _always_ | `on_timeout_is_cancel` | `cancelling` | — | — |
| `timing_out` | _always_ | — | `parked` | — | — |
| `parked` | `CHILD_FILLED` | — | `completing` | — | — |
| `parked` | `USER_CANCEL` | — | `cancelling` | — | — |
| `paused` | `RESUME` | — | `working` | — | — |
| `paused` | `USER_CANCEL` | — | `cancelling` | — | — |
| `completing` | `CHILDREN_TERMINAL` | — | `completed` | — | — |

### B7.4 Invoked services

| In state | `id` | `src` | `onDone` | `onError` |
|---|---|---|---|---|
| `arming` | `arm` | `submit_initial_limit` | `working` | `failed` |
| `repricing` | `amend` | `amend_child_price` | `working` | `completing` if `error_is_order_not_found_after_fill`; `failed` if `failures_exhausted`; `working` |
| `market_converting` | `mkt` | `convert_to_market` | `completing` | `failed` |
| `cancelling` | `cx` | `cancel_child` | `cancelled` | `failed` |

### B7.5 Guards

| Guard | Polarity | Contract |
|---|---|---|
| `beyond_max_chase_ticks` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `drift_over_threshold_and_interval_elapsed_and_budget_ok` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `error_is_order_not_found_after_fill` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `failures_exhausted` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `on_disconnect_is_freeze` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `on_timeout_is_cancel` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `on_timeout_is_market` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `repricings_exhausted` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |

### B7.6 Actions

All actions are `@cv_action`-wrapped (A1). A raising action writes `context["_fault"]`, aborts the transition and routes to this machine's fault state; the snapshot writer refuses to persist a faulted context (MUST-01).

| Action |
|---|
| `apply_fill` |
| `bump_failure` |
| `bump_repricings` |
| `compute_target_excluding_own_size` |
| `defer` |
| `map_error` |
| `raise_warning_alert` |
| `record_child` |
| `stamp_arm_price` |
| `stamp_last_reprice` |

### B7.7 Invariants

| ID | Invariant |
|---|---|
| **INV-B7-a** | `repricings <= max_repricings` and cumulative movement `<= max_chase_ticks`; exceeding either reaches `bound_exceeded`, a visible state. |
| **INV-B7-b** | `compute_target_excluding_own_size` never chases the algo's own resting order. |
| **INV-B7-c** | A reprice is attempted only when the rate budget permits it; `RATE_BUDGET_EXHAUSTED` parks the algo rather than queueing amendments. |
| **INV-B7-d** | `BOOK_TARGET_MOVED` is an **edge-triggered, pre-decimated** input at `<= 10 Hz` produced by a plain-Python `ChaseTargetTracker`. Raw book deltas never reach this machine (MUSTNOT-01/03; E33-S04/Q03 assert the bound). |
| **INV-B7-e** | `timing_out` resolves by policy to cancel or market conversion; it never silently leaves a resting order. |

### B7.8 Implementation notes

- This is the machine most at risk of being level-triggered by accident. The tracker is the boundary: it does the fast work in plain Python and emits a bounded event stream.
- **Corrected 2026-10-01 (C-04 / C-07b class, E50-S01, `tools/lint_statecharts.py` CV-LINT-KILL-ANCESTOR / CV-LINT-FALLTHROUGH):** root `on.KILL` → existing `failed` with `audit_kill`, so every invoking state has a kill ancestor (C-04; no new guard, no new business transition); ordered unguarded `audit_guard_denied` arm (internal, B18 shape) appended after the guarded arms of `working.BOOK_TARGET_MOVED`, `working.WS_DISCONNECT` so a guard-denied event is audited, never silently deferred (C-07b).

---

## B8 — Position protection / native-SL invariant

| | |
|---|---|
| **Machine `id`** | `position_protection` |
| **Root type** | `parallel` (orthogonal regions) |
| **Owning epic** | E32 - Brackets, scaled orders & native SL invariant |
| **Schema owner** | 24-internal-schemas.md §8.8 (safety invariant), §10.7 (bracket), ADR-0008 rule 2 |
| **Fit (research)** | Workaround |
| **Event rate** | low; the watchdog scan is externally scheduled |
| **States / leaves / finals** | 14 / 11 / 0 |

**Purpose.** Enforce C-2.6: every open position carries a native exchange-side stop-loss, with an independent watchdog region that keeps checking.

**Why this shape.** Two parallel regions. `sl` is the attach/verify/protect path; `watchdog` scans independently, so a position cannot be considered protected merely because the attach path believed it was. **`protected` is reachable only from an exchange read** (`read_position_sl` reporting an SL), never from a successful attach call alone.

### B8.1 Contract (normative)

```json
{
  "id": "position_protection",
  "actionErrorPolicy": "rollback",
  "onUnhandled": "defer",
  "guardErrorPolicy": "raise",
  "strictTargets": true,
  "strict": true,
  "spawnBlockingTimeout": 5000,
  "type": "parallel",
  "context": {
    "account_id": null,
    "symbol": null,
    "position_qty": "0",
    "native_sl_px": null,
    "desired_sl_px": null,
    "sl_deadline_us": null,
    "naked_since_us": null,
    "attach_attempts": 0,
    "fallback_attempts": 0,
    "frozen": false
  },
  "states": {
    "sl": {
      "initial": "flat",
      "states": {
        "flat": {
          "on": {
            "POSITION_OPENED": {
              "target": "#position_protection.sl.attaching"
            }
          }
        },
        "attaching": {
          "entry": [
            "arm_sl_deadline",
            "bump_attach_attempts"
          ],
          "invoke": {
            "id": "att",
            "src": "attach_native_sl",
            "onDone": {
              "target": "#position_protection.sl.verifying"
            },
            "onError": [
              {
                "target": "#position_protection.sl.attaching",
                "reenter": true,
                "guard": "attach_attempts_left"
              },
              {
                "target": "#position_protection.sl.naked"
              }
            ]
          },
          "on": {
            "SL_DEADLINE": {
              "target": "#position_protection.sl.naked"
            }
          }
        },
        "verifying": {
          "invoke": {
            "id": "ver",
            "src": "read_position_sl",
            "onDone": [
              {
                "target": "#position_protection.sl.protected",
                "guard": "exchange_reports_sl"
              },
              {
                "target": "#position_protection.sl.naked",
                "guard": "fallback_attempts_left"
              },
              {
                "target": "#position_protection.sl.naked_unrecoverable"
              }
            ],
            "onError": [
              {
                "target": "#position_protection.sl.naked",
                "guard": "fallback_attempts_left"
              },
              {
                "target": "#position_protection.sl.naked_unrecoverable"
              }
            ]
          }
        },
        "protected": {
          "tags": [
            "protected"
          ],
          "entry": [
            "reset_fallback_attempts"
          ],
          "on": {
            "TIGHTEN_SL": [
              {
                "guard": "amend_locked",
                "actions": [
                  "audit_amend_refused_frozen"
                ]
              },
              {
                "target": "#position_protection.sl.amending",
                "guard": "tightens_only"
              },
              {
                "actions": [
                  "audit_guard_denied"
                ]
              }
            ],
            "LOOSEN_SL": [
              {
                "guard": "amend_locked",
                "actions": [
                  "audit_amend_refused_frozen"
                ]
              },
              {
                "target": "#position_protection.sl.amending",
                "guard": "explicit_audited_override"
              },
              {
                "actions": [
                  "audit_guard_denied"
                ]
              }
            ],
            "WATCHDOG_MISS": {
              "target": "#position_protection.sl.naked"
            },
            "POSITION_FLAT": {
              "target": "#position_protection.sl.flat"
            }
          }
        },
        "amending": {
          "invoke": {
            "id": "am",
            "src": "set_trading_stop",
            "onDone": {
              "target": "#position_protection.sl.verifying"
            },
            "onError": {
              "target": "#position_protection.sl.verifying"
            }
          },
          "on": {}
        },
        "naked": {
          "tags": [
            "naked",
            "critical"
          ],
          "entry": [
            "stamp_naked_since",
            "bump_fallback_attempts",
            "raise_critical_alert",
            "emit_naked_metric"
          ],
          "invoke": {
            "id": "fb",
            "src": "attach_fallback_sl",
            "onDone": {
              "target": "#position_protection.sl.verifying"
            },
            "onError": {
              "target": "#position_protection.sl.naked_unrecoverable"
            }
          },
          "on": {
            "POSITION_FLAT": {
              "target": "#position_protection.sl.flat"
            }
          }
        },
        "naked_unrecoverable": {
          "tags": [
            "naked",
            "critical"
          ],
          "entry": [
            "page_owner",
            "consider_reduce_only_close"
          ],
          "on": {
            "SL_OBSERVED": {
              "target": "#position_protection.sl.protected"
            },
            "POSITION_FLAT": {
              "target": "#position_protection.sl.flat"
            }
          }
        }
      },
      "on": {
        "KILL": {
          "actions": [
            "audit_kill_sl_continues"
          ]
        }
      }
    },
    "watchdog": {
      "initial": "idle",
      "states": {
        "idle": {
          "on": {
            "POSITION_OPENED": {
              "target": "#position_protection.watchdog.scanning"
            }
          }
        },
        "scanning": {
          "on": {
            "SCAN_DUE": [
              {
                "target": "#position_protection.watchdog.scanning",
                "reenter": true,
                "guard": "sl_observed",
                "actions": [
                  "reset_miss_counter"
                ]
              },
              {
                "target": "#position_protection.watchdog.scanning",
                "reenter": true,
                "actions": [
                  "bump_miss_counter",
                  "maybe_raise_watchdog_miss"
                ]
              }
            ],
            "POSITION_FLAT": {
              "target": "#position_protection.watchdog.idle"
            }
          }
        }
      }
    },
    "amend_lock": {
      "initial": "open",
      "states": {
        "open": {
          "on": {
            "KILL": {
              "target": "#position_protection.amend_lock.frozen"
            }
          }
        },
        "frozen": {
          "tags": [
            "frozen",
            "kill_halted"
          ],
          "entry": [
            "audit_kill",
            "publish_frozen_flag"
          ],
          "on": {
            "KILL": {
              "actions": [
                "audit_frozen_event"
              ]
            }
          }
        }
      }
    }
  },
  "meta": {
    "cv:slProtection": true
  }
}
```

### B8.2 States

| State | Kind | Tags | Entry actions | Exit actions | Defers `*` |
|---|---|---|---|---|---|
| `sl` | compound | — | — | — | — |
| `sl.flat` | atomic | — | — | — | — |
| `sl.attaching` | atomic | — | `arm_sl_deadline`, `bump_attach_attempts` | — | — |
| `sl.verifying` | atomic | — | — | — | — |
| `sl.protected` | atomic | `protected` | `reset_fallback_attempts` | — | — |
| `sl.amending` | atomic | — | — | — | yes |
| `sl.naked` | atomic | `naked`, `critical` | `stamp_naked_since`, `bump_fallback_attempts`, `raise_critical_alert`, `emit_naked_metric` | — | — |
| `sl.naked_unrecoverable` | atomic | `naked`, `critical` | `page_owner`, `consider_reduce_only_close` | — | — |
| `amend_lock` *(Corrected 2026-10-09, #2133 review)* | compound | — | — | — | — |
| `amend_lock.open` | atomic | — | — | — | — |
| `amend_lock.frozen` | atomic | `frozen`, `kill_halted` | `audit_kill`, `publish_frozen_flag` | — | — |
| `watchdog` | compound | — | — | — | — |
| `watchdog.idle` | atomic | — | — | — | — |
| `watchdog.scanning` | atomic | — | — | — | — |

### B8.3 Events and transitions

| From | Event | Guard | Target | Actions | `reenter` |
|---|---|---|---|---|---|
| `sl.flat` | `POSITION_OPENED` | — | `sl.attaching` | — | — |
| `sl.attaching` | `SL_DEADLINE` | — | `sl.naked` | — | — |
| `sl.protected` | `TIGHTEN_SL` | `tightens_only` | `sl.amending` | — | — |
| `sl.protected` | `LOOSEN_SL` | `explicit_audited_override` | `sl.amending` | — | — |
| `sl.protected` | `TIGHTEN_SL` | — | _(internal)_ | `audit_guard_denied` | — |
| `sl.protected` | `LOOSEN_SL` | — | _(internal)_ | `audit_guard_denied` | — |
| `sl.protected` | `WATCHDOG_MISS` | — | `sl.naked` | — | — |
| `sl.protected` | `POSITION_FLAT` | — | `sl.flat` | — | — |
| `sl.amending` | `*` | — | _(internal)_ | `defer` | — |
| `sl.naked` | `POSITION_FLAT` | — | `sl.flat` | — | — |
| `sl.naked_unrecoverable` | `SL_OBSERVED` | — | `sl.protected` | — | — |
| `sl.naked_unrecoverable` | `POSITION_FLAT` | — | `sl.flat` | — | — |
| `sl` | `KILL` | — | _(internal)_ | `audit_kill_sl_continues` *(Corrected 2026-10-09, #2133 review)* | — |
| `sl.protected` | `TIGHTEN_SL` | `amend_locked` (first arm) | _(internal)_ | `audit_amend_refused_frozen` *(Corrected 2026-10-09, #2133 review)* | — |
| `sl.protected` | `LOOSEN_SL` | `amend_locked` (first arm) | _(internal)_ | `audit_amend_refused_frozen` *(Corrected 2026-10-09, #2133 review)* | — |
| `amend_lock.open` | `KILL` | — | `amend_lock.frozen` | — (entry of `frozen`) | — |
| `amend_lock.frozen` | `KILL` | — | _(internal)_ | `audit_frozen_event` | — |
| `watchdog.idle` | `POSITION_OPENED` | — | `watchdog.scanning` | — | — |
| `watchdog.scanning` | `SCAN_DUE` | `sl_observed` | `watchdog.scanning` | `reset_miss_counter` | yes |
| `watchdog.scanning` | `SCAN_DUE` | — | `watchdog.scanning` | `bump_miss_counter`, `maybe_raise_watchdog_miss` | yes |
| `watchdog.scanning` | `POSITION_FLAT` | — | `watchdog.idle` | — | — |

### B8.4 Invoked services

| In state | `id` | `src` | `onDone` | `onError` |
|---|---|---|---|---|
| `sl.attaching` | `att` | `attach_native_sl` | `sl.verifying` | `sl.attaching` if `attach_attempts_left`; `sl.naked` |
| `sl.verifying` | `ver` | `read_position_sl` | `sl.protected` if `exchange_reports_sl`; `sl.naked` if `fallback_attempts_left`; `sl.naked_unrecoverable` | `sl.naked` if `fallback_attempts_left`; `sl.naked_unrecoverable` |
| `sl.amending` | `am` | `set_trading_stop` | `sl.verifying` | `sl.verifying` |
| `sl.naked` | `fb` | `attach_fallback_sl` | `sl.verifying` | `sl.naked_unrecoverable` |

### B8.5 Guards

| Guard | Polarity | Contract |
|---|---|---|
| `amend_locked` *(Corrected 2026-10-09, #2133 review)* | deny polarity | `context.frozen is True`; no I/O; total; returns `True` (locked) on any internal error |
| `attach_attempts_left` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `exchange_reports_sl` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `explicit_audited_override` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `fallback_attempts_left` | pure predicate over `(context, event)` | `context.fallback_attempts < CV_B8_MAX_FALLBACK` (default 3); no I/O; total; returns `False` on any internal error (fails toward `naked_unrecoverable`, which pages) |
| `sl_observed` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `tightens_only` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |

### B8.6 Actions

All actions are `@cv_action`-wrapped (A1). A raising action writes `context["_fault"]`, aborts the transition and routes to this machine's fault state; the snapshot writer refuses to persist a faulted context (MUST-01).

| Action |
|---|
| `arm_sl_deadline` |
| `bump_attach_attempts` |
| `bump_fallback_attempts` |
| `bump_miss_counter` |
| `consider_reduce_only_close` |
| `defer` |
| `emit_naked_metric` |
| `maybe_raise_watchdog_miss` |
| `page_owner` |
| `raise_critical_alert` |
| `reset_fallback_attempts` |
| `reset_miss_counter` |
| `stamp_naked_since` |
| `audit_amend_refused_frozen` *(Corrected 2026-10-09)* |
| `audit_frozen_event` *(Corrected 2026-10-09)* |
| `audit_guard_denied` *(Corrected 2026-10-09)* |
| `audit_kill` *(Corrected 2026-10-09)* |
| `publish_frozen_flag` *(Corrected 2026-10-09)* |
| `audit_kill_sl_continues` *(Corrected 2026-10-09, #2133 review)* |

### B8.7 Invariants

| ID | Invariant |
|---|---|
| **INV-3** | No position is in `naked` for longer than `sl_deadline_us` without a P1 alert (principle P4). |
| **INV-B8-a** | `protected` implies a completed exchange read reported an SL. An attach `onDone` alone moves to `verifying`, never to `protected`. |
| **INV-B8-b** | `tightens_only` is a **deny-polarity** guard (A6): if it raises or cannot decide, the amendment is blocked. |
| **INV-B8-c** | Loosening an SL requires `explicit_audited_override` and writes an audit record (C-2.9). |
| **INV-B8-d** | `naked_unrecoverable` pages the owner and considers a reduce-only close. No configuration, flag or environment suppresses this (C-2.6). |
| **INV-B8-e** | The watchdog region's miss counter is reset only by a positive `sl_observed`, never by the passage of time. |
| **INV-B8-f** | *(2026-09-24, B610-OC-CD03 fix)* The `naked ⇄ verifying` loop is bounded: `fallback_attempts` is bumped on every `naked` entry and reset only on `protected` entry; once `fallback_attempts_left` is false, verification failure goes to `naked_unrecoverable` (pages). Contract test: a fallback attach that succeeds while the exchange never reports an SL reaches `naked_unrecoverable` in ≤ `CV_B8_MAX_FALLBACK` laps with `chain_trips == 0` and exactly that many `raise_critical_alert` firings. |
| **INV-B8-g** | *(Corrected 2026-10-09, #1650; redesigned #2133 review)* **KILL never abandons SL attachment.** In the `sl` region `KILL` is an internal audit-only arm (`audit_kill_sl_continues`), so an in-flight `attach_native_sl` / `read_position_sl` / `attach_fallback_sl` and the `naked_unrecoverable` page always run to completion. KILL moves the parallel `amend_lock` region `open` → `frozen` (**not terminal**): entry writes exactly one `audit_kill` and publishes the plain-bool frozen flag (C-2.20); from then on `amend_locked` refuses (audited) every `TIGHTEN_SL`/`LOOSEN_SL`, so no event sequence after KILL starts `set_trading_stop` or cancels/detaches the native SL (C-2.6, C-4.14). Every position therefore ends with a confirmed SL (`protected`) or an audited page (`naked_unrecoverable`). Un-freeze (`RECONCILED`/`RESUME`) is tracked in #2157. |

### B8.8 Implementation notes

- **Corrected 2026-10-09 (C-04 / C-07b, #1650, owner decision #1778 item X; redesigned per PR #2133 review):** KILL is split across two regions. `sl.on.KILL` is internal and audit-only, so the attach / verify / fallback / page path is never cut short (an earlier draft sent `sl` KILL to a `frozen` leaf, which cancelled an in-flight attach and stranded an unprotected position). A new parallel `amend_lock` region (`open` → `frozen` on KILL) carries the freeze as an amend-lock flag rather than a leaf of `sl`. This was chosen over deferring KILL inside `sl` because the chart is already `parallel`, the lock then holds from every `sl` state including after `POSITION_FLAT` → re-open, and `frozen` stays a pure record (no invoke/after/always) under the §1.3c SL-protection exception. The chart root carries `"meta": {"cv:slProtection": true}`. The guarded `amend_locked` first arm on `protected.TIGHTEN_SL`/`LOOSEN_SL` refuses amendments while frozen, and the ordered unguarded `audit_guard_denied` arm keeps C-07b. New context key `frozen` (snapshotted). Re-publishing the process-level flag after restore and the un-freeze exit are tracked in **#2157**.
- **Corrected 2026-09-24 (B610-OC-CD03, High, ours):** added `fallback_attempts` context, `fallback_attempts_left` guard, `bump_fallback_attempts` on `naked` entry and `reset_fallback_attempts` on `protected` entry; `verifying` failure falls through to `naked_unrecoverable` once exhausted. Before the fix, a successful-but-useless fallback attach looped `naked ⇄ verifying` unbounded (≈500 laps/s, one P1 alert per lap) until the chain budget tripped. Satisfies CV-C38 / CV-LINT-XS16 (bounded invoke cycle).
- The SL deadline is held as `sl_deadline_us` in context; its numeric value is owned by 24 §8.8, which must be reconciled with ADR-0008 (the two currently disagree: 2 s vs 3000 ms).

---

## B9 — Rule instance (lifecycle only)

| | |
|---|---|
| **Machine `id`** | `rule_instance` |
| **Root type** | `compound`, initial `draft` |
| **Owning epic** | E35 - Rule engine IR, compiler & runtime |
| **Schema owner** | 24-internal-schemas.md §11.5 (evaluation semantics), §11.7 (safety limits), §11.9 (simulation), ADR-0007 |
| **Fit (research)** | Workaround (lifecycle) / **Not suitable** (per-tick evaluation) |
| **Event rate** | lifecycle transitions only; **never per tick** |
| **States / leaves / finals** | 11 / 11 / 0 |

**Purpose.** The armed / triggered / cooldown / paused / kill-switched lifecycle of one rule instance at one scope.

**Why this shape.** **This is a split.** The rule *lifecycle* is a statechart; the rule *condition evaluation* is a compiled Python predicate and is on the do-not-use-for list. Measured: plain Python runs the entire unfiltered 200,000 eval/s workload in 30 ms (6.5 M eval/s) against 8,813 ev/s for a realistic 1,000-machine rule fleet - **~744x**. `evaluate_condition_dag` appears here as an invoked service precisely so that evaluation stays outside the machine.

### B9.1 Contract (normative)

```json
{
  "id": "rule_instance",
  "actionErrorPolicy": "rollback",
  "onUnhandled": "defer",
  "guardErrorPolicy": "raise",
  "strictTargets": true,
  "strict": true,
  "spawnBlockingTimeout": 5000,
  "on": {
    "KILL": {
      "target": "#rule_instance.kill_switched",
      "actions": [
        "audit_kill"
      ]
    }
  },
  "initial": "draft",
  "context": {
    "rule_id": null,
    "version": 0,
    "scope_key": null,
    "consecutive_errors": 0,
    "kill_switch_at": 5,
    "fires_this_hour": 0,
    "fires_today": 0,
    "simulation_fires": 0,
    "simulation_started_us": null,
    "cooldown_until_us": null,
    "once_satisfied": false,
    "last_skip_reason": null
  },
  "states": {
    "draft": {
      "on": {
        "SAVE": {
          "target": "#rule_instance.simulating"
        }
      }
    },
    "simulating": {
      "entry": [
        "stamp_simulation_start"
      ],
      "on": {
        "TRIGGER": {
          "actions": [
            "evaluate_and_record_simulated"
          ]
        },
        "SIM_FIRE": {
          "actions": [
            "bump_simulation_fires"
          ]
        },
        "ARM_REQUESTED": [
          {
            "target": "#rule_instance.armed",
            "guard": "promotion_gate_satisfied_and_permitted"
          },
          {
            "actions": [
              "reject_promotion_with_reason"
            ]
          }
        ],
        "EDIT": {
          "target": "#rule_instance.simulating",
          "reenter": true,
          "actions": [
            "reset_simulation_counters"
          ]
        }
      }
    },
    "armed": {
      "entry": [
        "subscribe_triggers",
        "emit_armed_audit"
      ],
      "exit": [
        "unsubscribe_triggers"
      ],
      "on": {
        "TRIGGER": [
          {
            "actions": [
              "record_skip_debounced"
            ],
            "guard": "debounce_blocked"
          },
          {
            "actions": [
              "record_skip_stale_data"
            ],
            "guard": "data_stale"
          },
          {
            "actions": [
              "record_skip_limit"
            ],
            "guard": "limits_blocked"
          },
          {
            "target": "#rule_instance.evaluating"
          }
        ],
        "FEED_DEGRADED": {
          "target": "#rule_instance.paused_degraded"
        },
        "KILL_SWITCH": {
          "target": "#rule_instance.kill_switched"
        },
        "DISARM": {
          "target": "#rule_instance.disarmed"
        },
        "EDIT": {
          "target": "#rule_instance.simulating",
          "actions": [
            "reset_simulation_counters"
          ]
        }
      }
    },
    "evaluating": {
      "invoke": {
        "id": "eval",
        "src": "evaluate_condition_dag",
        "onDone": [
          {
            "target": "#rule_instance.pending_confirmation",
            "guard": "condition_true_and_requires_confirmation"
          },
          {
            "target": "#rule_instance.acting",
            "guard": "condition_true"
          },
          {
            "target": "#rule_instance.armed",
            "actions": [
              "log_no_op_with_values"
            ]
          }
        ],
        "onError": [
          {
            "target": "#rule_instance.kill_switched",
            "guard": "error_budget_exhausted"
          },
          {
            "target": "#rule_instance.armed",
            "actions": [
              "bump_consecutive_errors"
            ]
          }
        ]
      },
      "on": {}
    },
    "pending_confirmation": {
      "entry": [
        "queue_for_human_confirmation",
        "arm_confirmation_ttl"
      ],
      "on": {
        "CONFIRMED": {
          "target": "#rule_instance.acting"
        },
        "CONFIRM_TIMEOUT": {
          "target": "#rule_instance.armed",
          "actions": [
            "record_skip_unconfirmed"
          ]
        },
        "REJECTED": {
          "target": "#rule_instance.armed",
          "actions": [
            "record_skip_rejected"
          ]
        }
      }
    },
    "acting": {
      "entry": [
        "assert_safety_limits"
      ],
      "invoke": {
        "id": "act",
        "src": "dispatch_actions_in_order",
        "onDone": {
          "target": "#rule_instance.cooling_down",
          "actions": [
            "record_fire",
            "reset_consecutive_errors"
          ]
        },
        "onError": [
          {
            "target": "#rule_instance.kill_switched",
            "guard": "error_budget_exhausted",
            "actions": [
              "raise_critical_alert"
            ]
          },
          {
            "target": "#rule_instance.cooling_down",
            "actions": [
              "record_partial_fire",
              "bump_consecutive_errors",
              "raise_partial_alert"
            ]
          }
        ]
      },
      "on": {}
    },
    "cooling_down": {
      "entry": [
        "stamp_cooldown_deadline"
      ],
      "always": [
        {
          "target": "#rule_instance.spent",
          "guard": "once_satisfied"
        }
      ],
      "on": {
        "COOLDOWN_DUE": {
          "target": "#rule_instance.armed"
        },
        "KILL_SWITCH": {
          "target": "#rule_instance.kill_switched"
        },
        "DISARM": {
          "target": "#rule_instance.disarmed"
        }
      }
    },
    "paused_degraded": {
      "entry": [
        "emit_rules_paused_notice"
      ],
      "on": {
        "FEED_HEALTHY": {
          "target": "#rule_instance.armed"
        },
        "KILL_SWITCH": {
          "target": "#rule_instance.kill_switched"
        },
        "DISARM": {
          "target": "#rule_instance.disarmed"
        }
      }
    },
    "kill_switched": {
      "tags": [
        "needs_human_rearm"
      ],
      "entry": [
        "raise_critical_alert",
        "emit_kill_switch_audit"
      ],
      "on": {
        "HUMAN_REARM": [
          {
            "target": "#rule_instance.armed",
            "guard": "rearm_permitted_and_elevated",
            "actions": [
              "reset_consecutive_errors"
            ]
          },
          {
            "actions": [
              "audit_guard_denied"
            ]
          }
        ]
      }
    },
    "spent": {
      "tags": [
        "once_satisfied"
      ],
      "on": {
        "RESET_ONCE": {
          "target": "#rule_instance.armed"
        }
      }
    },
    "disarmed": {
      "on": {
        "ARM_REQUESTED": [
          {
            "target": "#rule_instance.armed",
            "guard": "promotion_gate_satisfied_and_permitted"
          },
          {
            "actions": [
              "audit_guard_denied"
            ]
          }
        ]
      }
    }
  }
}
```

### B9.2 States

| State | Kind | Tags | Entry actions | Exit actions | Defers `*` |
|---|---|---|---|---|---|
| `draft` | atomic | — | — | — | — |
| `simulating` | atomic | — | `stamp_simulation_start` | — | — |
| `armed` | atomic | — | `subscribe_triggers`, `emit_armed_audit` | `unsubscribe_triggers` | — |
| `evaluating` | atomic | — | — | — | yes |
| `pending_confirmation` | atomic | — | `queue_for_human_confirmation`, `arm_confirmation_ttl` | — | — |
| `acting` | atomic | — | `assert_safety_limits` | — | yes |
| `cooling_down` | atomic | — | `stamp_cooldown_deadline` | — | — |
| `paused_degraded` | atomic | — | `emit_rules_paused_notice` | — | — |
| `kill_switched` | atomic | `needs_human_rearm` | `raise_critical_alert`, `emit_kill_switch_audit` | — | — |
| `spent` | atomic | `once_satisfied` | — | — | — |
| `disarmed` | atomic | — | — | — | — |

### B9.3 Events and transitions

| From | Event | Guard | Target | Actions | `reenter` |
|---|---|---|---|---|---|
| `draft` | `SAVE` | — | `simulating` | — | — |
| `simulating` | `TRIGGER` | — | _(internal)_ | `evaluate_and_record_simulated` | — |
| `simulating` | `SIM_FIRE` | — | _(internal)_ | `bump_simulation_fires` | — |
| `simulating` | `ARM_REQUESTED` | `promotion_gate_satisfied_and_permitted` | `armed` | — | — |
| `simulating` | `ARM_REQUESTED` | — | _(internal)_ | `reject_promotion_with_reason` | — |
| `simulating` | `EDIT` | — | `simulating` | `reset_simulation_counters` | yes |
| `armed` | `TRIGGER` | `debounce_blocked` | _(internal)_ | `record_skip_debounced` | — |
| `armed` | `TRIGGER` | `data_stale` | _(internal)_ | `record_skip_stale_data` | — |
| `armed` | `TRIGGER` | `limits_blocked` | _(internal)_ | `record_skip_limit` | — |
| `armed` | `TRIGGER` | — | `evaluating` | — | — |
| `armed` | `FEED_DEGRADED` | — | `paused_degraded` | — | — |
| `armed` | `KILL_SWITCH` | — | `kill_switched` | — | — |
| `armed` | `DISARM` | — | `disarmed` | — | — |
| `armed` | `EDIT` | — | `simulating` | `reset_simulation_counters` | — |
| `evaluating` | `*` | — | _(internal)_ | `defer` | — |
| `pending_confirmation` | `CONFIRMED` | — | `acting` | — | — |
| `pending_confirmation` | `CONFIRM_TIMEOUT` | — | `armed` | `record_skip_unconfirmed` | — |
| `pending_confirmation` | `REJECTED` | — | `armed` | `record_skip_rejected` | — |
| `acting` | `*` | — | _(internal)_ | `defer` | — |
| `cooling_down` | `COOLDOWN_DUE` | — | `armed` | — | — |
| `cooling_down` | `KILL_SWITCH` | — | `kill_switched` | — | — |
| `cooling_down` | `DISARM` | — | `disarmed` | — | — |
| `cooling_down` | _always_ | `once_satisfied` | `spent` | — | — |
| `paused_degraded` | `FEED_HEALTHY` | — | `armed` | — | — |
| `paused_degraded` | `KILL_SWITCH` | — | `kill_switched` | — | — |
| `paused_degraded` | `DISARM` | — | `disarmed` | — | — |
| `kill_switched` | `HUMAN_REARM` | `rearm_permitted_and_elevated` | `armed` | `reset_consecutive_errors` | — |
| `spent` | `RESET_ONCE` | — | `armed` | — | — |
| `disarmed` | `ARM_REQUESTED` | `promotion_gate_satisfied_and_permitted` | `armed` | — | — |

### B9.4 Invoked services

| In state | `id` | `src` | `onDone` | `onError` |
|---|---|---|---|---|
| `evaluating` | `eval` | `evaluate_condition_dag` | `pending_confirmation` if `condition_true_and_requires_confirmation`; `acting` if `condition_true`; `armed` | `kill_switched` if `error_budget_exhausted`; `armed` |
| `acting` | `act` | `dispatch_actions_in_order` | `cooling_down` | `kill_switched` if `error_budget_exhausted`; `cooling_down` |

### B9.5 Guards

| Guard | Polarity | Contract |
|---|---|---|
| `condition_true` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `condition_true_and_requires_confirmation` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `data_stale` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `debounce_blocked` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `error_budget_exhausted` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `limits_blocked` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `once_satisfied` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `promotion_gate_satisfied_and_permitted` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `rearm_permitted_and_elevated` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |

### B9.6 Actions

All actions are `@cv_action`-wrapped (A1). A raising action writes `context["_fault"]`, aborts the transition and routes to this machine's fault state; the snapshot writer refuses to persist a faulted context (MUST-01).

| Action |
|---|
| `arm_confirmation_ttl` |
| `assert_safety_limits` |
| `bump_consecutive_errors` |
| `bump_simulation_fires` |
| `defer` |
| `emit_armed_audit` |
| `emit_kill_switch_audit` |
| `emit_rules_paused_notice` |
| `evaluate_and_record_simulated` |
| `log_no_op_with_values` |
| `queue_for_human_confirmation` |
| `raise_critical_alert` |
| `raise_partial_alert` |
| `record_fire` |
| `record_partial_fire` |
| `record_skip_debounced` |
| `record_skip_limit` |
| `record_skip_rejected` |
| `record_skip_stale_data` |
| `record_skip_unconfirmed` |
| `reject_promotion_with_reason` |
| `reset_consecutive_errors` |
| `reset_simulation_counters` |
| `stamp_cooldown_deadline` |
| `stamp_simulation_start` |
| `subscribe_triggers` |
| `unsubscribe_triggers` |

### B9.7 Invariants

| ID | Invariant |
|---|---|
| **INV-B9-a** | `TRIGGER` is delivered only by the **pre-filtered** dispatcher. MUST-05: the pre-filter achieves `>= 99 %` rejection, asserted by `cv_rule_prefilter_rejection_ratio`; below 99 % rule dispatch is disabled and alerts, because the budget is shared with the OMS. |
| **INV-B9-b** | Every non-firing outcome is recorded with a reason (debounced / limit / rejected / stale data / unconfirmed). A rule that does not fire is never silent. |
| **INV-B9-c** | `assert_safety_limits` runs on **entry to the acting state**, after confirmation - not only at arm time. |
| **INV-B9-d** | `kill_switched` is exited only by `HUMAN_REARM` with `rearm_permitted_and_elevated`; no automatic recovery exists. |
| **INV-B9-e** | `promotion_gate_satisfied_and_permitted` is deny-polarity: a simulation that cannot be evaluated does not promote. |
| **INV-B9-f** | Conflict arbitration between rules is a deterministic sort in the dispatcher, **not** racing machines (E35-S02/S07). |

### B9.8 Implementation notes

- `dispatch_actions_in_order` is an invoked service so that a partial dispatch surfaces as `onError` and lands the instance in `paused_degraded`, rather than as a raised action that would commit the transition anyway (LC-01).
- **Corrected 2026-10-01 (C-04 / C-07b class, E50-S01, `tools/lint_statecharts.py` CV-LINT-KILL-ANCESTOR / CV-LINT-FALLTHROUGH):** root `on.KILL` → existing `kill_switched` with `audit_kill`, so every invoking state has a kill ancestor (C-04; no new guard, no new business transition); ordered unguarded `audit_guard_denied` arm (internal, B18 shape) appended after the guarded arms of `kill_switched.HUMAN_REARM`, `disarmed.ARM_REQUESTED` so a guard-denied event is audited, never silently deferred (C-07b).

---

## B10 — Alert lifecycle

| | |
|---|---|
| **Machine `id`** | `alert` |
| **Root type** | `compound`, initial `armed` |
| **Owning epic** | E40 - Alerts & notifications |
| **Schema owner** | **not yet in 24** - see §Gaps below; today alerts exist only in E40 |
| **Fit (research)** | Excellent |
| **Event rate** | human frequencies |
| **States / leaves / finals** | 10 / 10 / 1 |

**Purpose.** One alert instance from armed, through storm suppression, firing and multi-channel delivery, to acknowledgement or resolution.

**Why this shape.** `partially_delivered` and `delivery_failed` are **distinct states**, which the current E40 ticket descriptions do not separate - and the deliveries API needs the difference. Delivery retry is an invoked service with `onError`, the library's strongest measured area (invoke lifecycle 14/14 in Study 05, including cancellation not producing stale `done` events).

### B10.1 Contract (normative)

```json
{
  "id": "alert",
  "actionErrorPolicy": "rollback",
  "onUnhandled": "defer",
  "guardErrorPolicy": "raise",
  "strictTargets": true,
  "strict": true,
  "spawnBlockingTimeout": 5000,
  "on": {
    "KILL": {
      "target": "#alert.disabled",
      "actions": [
        "audit_kill"
      ]
    }
  },
  "initial": "armed",
  "context": {
    "alert_id": null,
    "severity": "info",
    "storm_count": 0,
    "suppressed_until_us": null,
    "delivery_attempts": 0,
    "max_delivery_attempts": 5,
    "channels": [],
    "delivered_channels": []
  },
  "states": {
    "armed": {
      "on": {
        "CONDITION_MET": [
          {
            "target": "#alert.suppressed",
            "guard": "in_storm_window"
          },
          {
            "target": "#alert.firing"
          }
        ],
        "DISABLE": {
          "target": "#alert.disabled"
        }
      }
    },
    "suppressed": {
      "entry": [
        "bump_storm_count",
        "emit_suppression_metric"
      ],
      "on": {
        "SUPPRESSION_EXPIRED": {
          "target": "#alert.armed"
        },
        "DISABLE": {
          "target": "#alert.disabled"
        }
      }
    },
    "firing": {
      "entry": [
        "persist_fired_row",
        "stamp_storm_window"
      ],
      "invoke": {
        "id": "deliver",
        "src": "dispatch_to_channels",
        "onDone": [
          {
            "target": "#alert.delivered",
            "guard": "all_channels_ok"
          },
          {
            "target": "#alert.partially_delivered"
          }
        ],
        "onError": [
          {
            "target": "#alert.retrying",
            "guard": "delivery_attempts_left"
          },
          {
            "target": "#alert.delivery_failed"
          }
        ]
      }
    },
    "retrying": {
      "entry": [
        "bump_delivery_attempts",
        "schedule_backoff_deadline"
      ],
      "on": {
        "RETRY_DUE": {
          "target": "#alert.firing"
        },
        "ACK": {
          "target": "#alert.acknowledged"
        }
      }
    },
    "delivered": {
      "on": {
        "ACK": {
          "target": "#alert.acknowledged"
        },
        "RESOLVE": {
          "target": "#alert.resolved"
        }
      }
    },
    "partially_delivered": {
      "tags": [
        "degraded"
      ],
      "on": {
        "ACK": {
          "target": "#alert.acknowledged"
        },
        "RESOLVE": {
          "target": "#alert.resolved"
        }
      }
    },
    "delivery_failed": {
      "tags": [
        "degraded"
      ],
      "entry": [
        "emit_delivery_failure_metric"
      ],
      "on": {
        "ACK": {
          "target": "#alert.acknowledged"
        }
      }
    },
    "acknowledged": {
      "on": {
        "RESOLVE": {
          "target": "#alert.resolved"
        }
      }
    },
    "resolved": {
      "type": "final",
      "tags": [
        "terminal"
      ]
    },
    "disabled": {
      "on": {
        "ENABLE": {
          "target": "#alert.armed"
        }
      }
    }
  }
}
```

### B10.2 States

| State | Kind | Tags | Entry actions | Exit actions | Defers `*` |
|---|---|---|---|---|---|
| `armed` | atomic | — | — | — | — |
| `suppressed` | atomic | — | `bump_storm_count`, `emit_suppression_metric` | — | — |
| `firing` | atomic | — | `persist_fired_row`, `stamp_storm_window` | — | — |
| `retrying` | atomic | — | `bump_delivery_attempts`, `schedule_backoff_deadline` | — | — |
| `delivered` | atomic | — | — | — | — |
| `partially_delivered` | atomic | `degraded` | — | — | — |
| `delivery_failed` | atomic | `degraded` | `emit_delivery_failure_metric` | — | — |
| `acknowledged` | atomic | — | — | — | — |
| `resolved` | final | `terminal` | — | — | — |
| `disabled` | atomic | — | — | — | — |

### B10.3 Events and transitions

| From | Event | Guard | Target | Actions | `reenter` |
|---|---|---|---|---|---|
| `armed` | `CONDITION_MET` | `in_storm_window` | `suppressed` | — | — |
| `armed` | `CONDITION_MET` | — | `firing` | — | — |
| `armed` | `DISABLE` | — | `disabled` | — | — |
| `suppressed` | `SUPPRESSION_EXPIRED` | — | `armed` | — | — |
| `suppressed` | `DISABLE` | — | `disabled` | — | — |
| `retrying` | `RETRY_DUE` | — | `firing` | — | — |
| `retrying` | `ACK` | — | `acknowledged` | — | — |
| `delivered` | `ACK` | — | `acknowledged` | — | — |
| `delivered` | `RESOLVE` | — | `resolved` | — | — |
| `partially_delivered` | `ACK` | — | `acknowledged` | — | — |
| `partially_delivered` | `RESOLVE` | — | `resolved` | — | — |
| `delivery_failed` | `ACK` | — | `acknowledged` | — | — |
| `acknowledged` | `RESOLVE` | — | `resolved` | — | — |
| `disabled` | `ENABLE` | — | `armed` | — | — |

### B10.4 Invoked services

| In state | `id` | `src` | `onDone` | `onError` |
|---|---|---|---|---|
| `firing` | `deliver` | `dispatch_to_channels` | `delivered` if `all_channels_ok`; `partially_delivered` | `retrying` if `delivery_attempts_left`; `delivery_failed` |

### B10.5 Guards

| Guard | Polarity | Contract |
|---|---|---|
| `all_channels_ok` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `delivery_attempts_left` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `in_storm_window` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |

### B10.6 Actions

All actions are `@cv_action`-wrapped (A1). A raising action writes `context["_fault"]`, aborts the transition and routes to this machine's fault state; the snapshot writer refuses to persist a faulted context (MUST-01).

| Action |
|---|
| `bump_delivery_attempts` |
| `bump_storm_count` |
| `emit_delivery_failure_metric` |
| `emit_suppression_metric` |
| `persist_fired_row` |
| `schedule_backoff_deadline` |
| `stamp_storm_window` |

### B10.7 Invariants

| ID | Invariant |
|---|---|
| **INV-B10-a** | `delivery_attempts <= max_delivery_attempts`; exhaustion reaches `delivery_failed`, a visible state, never an infinite retry. |
| **INV-B10-b** | `delivered_channels` is a subset of `channels`; full delivery implies equality, partial delivery implies a proper non-empty subset. |
| **INV-B10-c** | Storm suppression is counted and metricised: a suppressed alert is observable, not dropped. |
| **INV-B10-d** | `persist_fired_row` happens on entry to `firing`, before any channel dispatch - the fired record survives a delivery failure. |

### B10.8 Implementation notes

- Backoff deadlines go to the external scheduler for restore-survivability, even though seconds of lateness would be tolerable here.

- **Corrected 2026-10-01 (E50-S02, `tools/lint_statecharts.py` CV-LINT-KILL-ANCESTOR):** root `on.KILL` → existing `disabled` with `audit_kill`, so the invoking `firing` state has a kill ancestor (C-04; no new state, no new guard).

---

## B11 — RecordingSession

| | |
|---|---|
| **Machine `id`** | `recording` |
| **Root type** | `compound`, initial `idle` |
| **Owning epic** | E16 - Recorder, retention & disk budget |
| **Schema owner** | 24-internal-schemas.md §13.1 (recording policy model), ADR-0015 |
| **Fit (research)** | Excellent |
| **Event rate** | per-symbol lifecycle events only |
| **States / leaves / finals** | 8 / 8 / 0 |

**Purpose.** Per-symbol recording lifecycle driven by a set of reasons (explicit list, open chart, open position), with stream health, gap counting and a linger period.

**Why this shape.** Adds `lingering` - today a prose rule in 24 §13.1 with no state - and turns "an open position cannot stop recording" from a scattered check into the guard `position_open_for_symbol`.

### B11.1 Contract (normative)

```json
{
  "id": "recording",
  "actionErrorPolicy": "rollback",
  "onUnhandled": "defer",
  "guardErrorPolicy": "raise",
  "strictTargets": true,
  "strict": true,
  "spawnBlockingTimeout": 5000,
  "on": {
    "KILL": {
      "target": "#recording.error",
      "actions": [
        "audit_kill"
      ]
    }
  },
  "initial": "idle",
  "context": {
    "symbol": null,
    "reasons": [],
    "streams": [],
    "streams_healthy": {},
    "gap_count_24h": 0,
    "linger_until_us": null,
    "error": null
  },
  "states": {
    "idle": {
      "on": {
        "REASON_ADDED": {
          "target": "#recording.starting",
          "actions": [
            "add_reason"
          ]
        }
      }
    },
    "starting": {
      "invoke": {
        "id": "sub",
        "src": "subscribe_streams",
        "onDone": {
          "target": "#recording.recording"
        },
        "onError": {
          "target": "#recording.error",
          "actions": [
            "record_error"
          ]
        }
      },
      "on": {
        "REASON_ADDED": {
          "actions": [
            "add_reason"
          ]
        },
        "REASON_REMOVED": {
          "actions": [
            "remove_reason"
          ]
        }
      }
    },
    "recording": {
      "entry": [
        "cancel_linger",
        "emit_recording_metric"
      ],
      "on": {
        "STREAM_UNHEALTHY": {
          "target": "#recording.degraded",
          "actions": [
            "mark_stream_unhealthy"
          ]
        },
        "REASON_ADDED": {
          "actions": [
            "add_reason"
          ]
        },
        "REASON_REMOVED": [
          {
            "actions": [
              "remove_reason"
            ],
            "guard": "reasons_remain"
          },
          {
            "target": "#recording.lingering",
            "actions": [
              "remove_reason"
            ]
          }
        ],
        "GAP_DETECTED": {
          "actions": [
            "bump_gap_count",
            "emit_gap_metric"
          ]
        }
      }
    },
    "degraded": {
      "tags": [
        "degraded"
      ],
      "entry": [
        "raise_degraded_alert"
      ],
      "on": {
        "STREAM_HEALTHY": [
          {
            "target": "#recording.recording",
            "guard": "all_streams_healthy",
            "actions": [
              "mark_stream_healthy"
            ]
          },
          {
            "actions": [
              "mark_stream_healthy"
            ]
          }
        ],
        "REASON_REMOVED": [
          {
            "actions": [
              "remove_reason"
            ],
            "guard": "reasons_remain"
          },
          {
            "target": "#recording.lingering",
            "actions": [
              "remove_reason"
            ]
          }
        ],
        "GAP_DETECTED": {
          "actions": [
            "bump_gap_count",
            "emit_gap_metric"
          ]
        },
        "STREAM_UNHEALTHY": {
          "actions": [
            "mark_stream_unhealthy"
          ]
        }
      }
    },
    "lingering": {
      "entry": [
        "schedule_linger_deadline"
      ],
      "on": {
        "REASON_ADDED": {
          "target": "#recording.recording",
          "actions": [
            "add_reason"
          ]
        },
        "LINGER_DUE": [
          {
            "target": "#recording.recording",
            "guard": "position_open_for_symbol"
          },
          {
            "target": "#recording.stopping"
          }
        ]
      }
    },
    "stopping": {
      "invoke": {
        "id": "unsub",
        "src": "unsubscribe_and_flush",
        "onDone": {
          "target": "#recording.stopped"
        },
        "onError": {
          "target": "#recording.error",
          "actions": [
            "record_error"
          ]
        }
      }
    },
    "stopped": {
      "on": {
        "REASON_ADDED": {
          "target": "#recording.starting",
          "actions": [
            "add_reason"
          ]
        }
      }
    },
    "error": {
      "tags": [
        "error"
      ],
      "on": {
        "RETRY": {
          "target": "#recording.starting"
        }
      }
    }
  }
}
```

### B11.2 States

| State | Kind | Tags | Entry actions | Exit actions | Defers `*` |
|---|---|---|---|---|---|
| `idle` | atomic | — | — | — | — |
| `starting` | atomic | — | — | — | — |
| `recording` | atomic | — | `cancel_linger`, `emit_recording_metric` | — | — |
| `degraded` | atomic | `degraded` | `raise_degraded_alert` | — | — |
| `lingering` | atomic | — | `schedule_linger_deadline` | — | — |
| `stopping` | atomic | — | — | — | — |
| `stopped` | atomic | — | — | — | — |
| `error` | atomic | `error` | — | — | — |

### B11.3 Events and transitions

| From | Event | Guard | Target | Actions | `reenter` |
|---|---|---|---|---|---|
| `idle` | `REASON_ADDED` | — | `starting` | `add_reason` | — |
| `starting` | `REASON_ADDED` | — | _(internal)_ | `add_reason` | — |
| `starting` | `REASON_REMOVED` | — | _(internal)_ | `remove_reason` | — |
| `recording` | `STREAM_UNHEALTHY` | — | `degraded` | `mark_stream_unhealthy` | — |
| `recording` | `REASON_ADDED` | — | _(internal)_ | `add_reason` | — |
| `recording` | `REASON_REMOVED` | `reasons_remain` | _(internal)_ | `remove_reason` | — |
| `recording` | `REASON_REMOVED` | — | `lingering` | `remove_reason` | — |
| `recording` | `GAP_DETECTED` | — | _(internal)_ | `bump_gap_count`, `emit_gap_metric` | — |
| `degraded` | `STREAM_HEALTHY` | `all_streams_healthy` | `recording` | `mark_stream_healthy` | — |
| `degraded` | `STREAM_HEALTHY` | — | _(internal)_ | `mark_stream_healthy` | — |
| `degraded` | `REASON_REMOVED` | `reasons_remain` | _(internal)_ | `remove_reason` | — |
| `degraded` | `REASON_REMOVED` | — | `lingering` | `remove_reason` | — |
| `degraded` | `GAP_DETECTED` | — | _(internal)_ | `bump_gap_count`, `emit_gap_metric` | — |
| `degraded` | `STREAM_UNHEALTHY` *(Corrected 2026-10-10, #2204, OC-06)* | — | _(internal)_ | `mark_stream_unhealthy` | — |
| `lingering` | `REASON_ADDED` | — | `recording` | `add_reason` | — |
| `lingering` | `LINGER_DUE` | `position_open_for_symbol` | `recording` | — | — |
| `lingering` | `LINGER_DUE` | — | `stopping` | — | — |
| `stopped` | `REASON_ADDED` | — | `starting` | `add_reason` | — |
| `error` | `RETRY` | — | `starting` | — | — |

### B11.4 Invoked services

| In state | `id` | `src` | `onDone` | `onError` |
|---|---|---|---|---|
| `starting` | `sub` | `subscribe_streams` | `recording` | `error` |
| `stopping` | `unsub` | `unsubscribe_and_flush` | `stopped` | `error` |

### B11.5 Guards

| Guard | Polarity | Contract |
|---|---|---|
| `all_streams_healthy` | pure predicate over `(context, event)` — **event-aware** | *(2026-09-24, R14-03 fix)* evaluates "every stream healthy **once this event is applied**": overlay `event.stream = True` on `context.streams_healthy` before the check, because guards run against the pre-action context (XState v5 / SCXML). No I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `position_open_for_symbol` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `reasons_remain` | pure predicate over `(context, event)` — **event-aware** | *(2026-09-24, R14-03 fix)* evaluates "reasons remaining **after** this removal" (`len(reasons) - 1 > 0`), because `remove_reason` has not yet run when the guard is evaluated. No I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |

### B11.6 Actions

All actions are `@cv_action`-wrapped (A1). A raising action writes `context["_fault"]`, aborts the transition and routes to this machine's fault state; the snapshot writer refuses to persist a faulted context (MUST-01).

| Action |
|---|
| `add_reason` |
| `bump_gap_count` |
| `cancel_linger` |
| `emit_gap_metric` |
| `emit_recording_metric` |
| `mark_stream_healthy` |
| `mark_stream_unhealthy` |
| `raise_degraded_alert` |
| `record_error` |
| `remove_reason` |
| `schedule_linger_deadline` |

### B11.7 Invariants

| ID | Invariant |
|---|---|
| **INV-B11-a** | Recording stops only when `reasons` is empty **and** `position_open_for_symbol` is false. A position open for the symbol can never stop recording (ADR-0015). |
| **INV-B11-b** | A reason re-added during `lingering` cancels the linger and returns to recording without a stream restart. |
| **INV-B11-c** | Every gap is counted and metricised; coverage rows are written for captured intervals only. No interpolation, ever (C-2.14). |
| **INV-B11-d** | `degraded` is entered on any unhealthy stream and exited only when **all** streams report healthy. *(Corrected 2026-10-10, #2204, OC-06)* A further `STREAM_UNHEALTHY` while `degraded` is consumed (internal `mark_stream_unhealthy`), never deferred, so `streams_healthy` always reflects every failed stream and a later `STREAM_HEALTHY` for one stream cannot exit `degraded` while another is still down. |

### B11.8 Implementation notes

- `lingering` must also appear in the recorder status API and the admin panel (E16).
- **Corrected 2026-09-24 (R14-03 / R13-15 / R13-16, proven in `docs/research/xstate/battle-v0.9.1/contracts/g2_b11_fix.py` on both engines):** (1) `all_streams_healthy` and `reasons_remain` are event-aware (see B11.5) — without this B11 was a one-way trip into `degraded`; (2) `degraded` now handles `GAP_DETECTED` — previously root `onUnhandled: "defer"` swallowed gap telemetry exactly while degraded. Contract test: the G2 script lands in `stopped` with `gap_count_24h == 1`, both services run, `chain_trips == 0`.

- **Corrected 2026-10-01 (E50-S02, `tools/lint_statecharts.py` CV-LINT-KILL-ANCESTOR):** root `on.KILL` → existing `error` with `audit_kill` (C-04); `starting`/`stopping` now have a kill ancestor.
- **Corrected 2026-10-10 (#2204, OC-06):** `degraded` had no `STREAM_UNHEALTHY` handler. A concurrent second stream failure was parked by `onUnhandled: "defer"`, so the health map went stale. A `STREAM_HEALTHY` for the first stream could then return the chart to `recording` while the second stream was still down, and the deferred failure replayed afterwards. `degraded` now handles `STREAM_UNHEALTHY` as an internal `mark_stream_unhealthy` arm: no re-entry and no second alert. Chart `version: 1`; context shape unchanged, so no upcaster.

---

## B12 — ReplaySession

| | |
|---|---|
| **Machine `id`** | `replay` |
| **Root type** | `compound`, initial `created` |
| **Owning epic** | E26 - Replay engine & scrubbing |
| **Schema owner** | 24-internal-schemas.md §13.7 (replay engine) |
| **Fit (research)** | Good |
| **Event rate** | control events only; the data path is outside the machine |
| **States / leaves / finals** | 8 / 8 / 1 |

**Purpose.** The transport controls of a replay session: prepare, buffer, play, pause, step, seek, loop, finish.

**Why this shape.** The machine owns **control**, never data. `emit_one_step` is an invoked service for the stepping case; the streaming path is ordinary code driven by the replay clock. Putting replayed market events through an interpreter would reintroduce exactly the hot-path cost MUSTNOT-01 forbids.

### B12.1 Contract (normative)

```json
{
  "id": "replay",
  "actionErrorPolicy": "rollback",
  "onUnhandled": "defer",
  "guardErrorPolicy": "raise",
  "strictTargets": true,
  "strict": true,
  "spawnBlockingTimeout": 5000,
  "on": {
    "KILL": {
      "target": "#replay.error",
      "actions": [
        "audit_kill"
      ]
    }
  },
  "initial": "created",
  "context": {
    "session_id": null,
    "symbols": [],
    "range_start": 0,
    "range_end": 0,
    "cursor": 0,
    "speed": 1.0,
    "loop": false,
    "paper_account_id": null,
    "error": null,
    "coverage_gaps": []
  },
  "states": {
    "created": {
      "on": {
        "PREPARE": {
          "target": "#replay.buffering"
        },
        "DESTROY": {
          "target": "#replay.destroyed"
        }
      }
    },
    "buffering": {
      "invoke": {
        "id": "seek",
        "src": "seek_and_prime",
        "onDone": {
          "target": "#replay.paused",
          "actions": [
            "set_cursor",
            "record_coverage"
          ]
        },
        "onError": {
          "target": "#replay.error",
          "actions": [
            "record_error"
          ]
        }
      },
      "on": {
        "CANCEL": {
          "target": "#replay.paused"
        }
      }
    },
    "paused": {
      "on": {
        "PLAY": {
          "target": "#replay.playing"
        },
        "STEP": {
          "target": "#replay.stepping"
        },
        "SEEK": {
          "target": "#replay.buffering"
        },
        "DESTROY": {
          "target": "#replay.destroyed"
        }
      }
    },
    "playing": {
      "entry": [
        "start_clock"
      ],
      "exit": [
        "stop_clock"
      ],
      "on": {
        "PAUSE": {
          "target": "#replay.paused"
        },
        "SEEK": {
          "target": "#replay.buffering"
        },
        "SET_SPEED": {
          "actions": [
            "set_speed"
          ]
        },
        "CONSUMER_SLOW": {
          "actions": [
            "slow_clock"
          ]
        },
        "RANGE_END": [
          {
            "target": "#replay.buffering",
            "guard": "loop_enabled",
            "actions": [
              "reset_cursor_to_start"
            ]
          },
          {
            "target": "#replay.finished"
          }
        ],
        "SOURCE_ERROR": {
          "target": "#replay.error",
          "actions": [
            "record_error"
          ]
        }
      }
    },
    "stepping": {
      "invoke": {
        "id": "step",
        "src": "emit_one_step",
        "onDone": {
          "target": "#replay.paused",
          "actions": [
            "set_cursor"
          ]
        },
        "onError": {
          "target": "#replay.error",
          "actions": [
            "record_error"
          ]
        }
      }
    },
    "finished": {
      "on": {
        "SEEK": {
          "target": "#replay.buffering"
        },
        "DESTROY": {
          "target": "#replay.destroyed"
        }
      }
    },
    "error": {
      "tags": [
        "error"
      ],
      "on": {
        "SEEK": {
          "target": "#replay.buffering"
        },
        "DESTROY": {
          "target": "#replay.destroyed"
        }
      }
    },
    "destroyed": {
      "type": "final",
      "tags": [
        "terminal"
      ]
    }
  }
}
```

### B12.2 States

| State | Kind | Tags | Entry actions | Exit actions | Defers `*` |
|---|---|---|---|---|---|
| `created` | atomic | — | — | — | — |
| `buffering` | atomic | — | — | — | yes |
| `paused` | atomic | — | — | — | — |
| `playing` | atomic | — | `start_clock` | `stop_clock` | — |
| `stepping` | atomic | — | — | — | — |
| `finished` | atomic | — | — | — | — |
| `error` | atomic | `error` | — | — | — |
| `destroyed` | final | `terminal` | — | — | — |

### B12.3 Events and transitions

| From | Event | Guard | Target | Actions | `reenter` |
|---|---|---|---|---|---|
| `created` | `PREPARE` | — | `buffering` | — | — |
| `created` | `DESTROY` | — | `destroyed` | — | — |
| `buffering` | `CANCEL` | — | `paused` | — | — |
| `buffering` | `*` | — | _(internal)_ | `defer` | — |
| `paused` | `PLAY` | — | `playing` | — | — |
| `paused` | `STEP` | — | `stepping` | — | — |
| `paused` | `SEEK` | — | `buffering` | — | — |
| `paused` | `DESTROY` | — | `destroyed` | — | — |
| `playing` | `PAUSE` | — | `paused` | — | — |
| `playing` | `SEEK` | — | `buffering` | — | — |
| `playing` | `SET_SPEED` | — | _(internal)_ | `set_speed` | — |
| `playing` | `CONSUMER_SLOW` | — | _(internal)_ | `slow_clock` | — |
| `playing` | `RANGE_END` | `loop_enabled` | `buffering` | `reset_cursor_to_start` | — |
| `playing` | `RANGE_END` | — | `finished` | — | — |
| `playing` | `SOURCE_ERROR` | — | `error` | `record_error` | — |
| `finished` | `SEEK` | — | `buffering` | — | — |
| `finished` | `DESTROY` | — | `destroyed` | — | — |
| `error` | `SEEK` | — | `buffering` | — | — |
| `error` | `DESTROY` | — | `destroyed` | — | — |

### B12.4 Invoked services

| In state | `id` | `src` | `onDone` | `onError` |
|---|---|---|---|---|
| `buffering` | `seek` | `seek_and_prime` | `paused` | `error` |
| `stepping` | `step` | `emit_one_step` | `paused` | `error` |

### B12.5 Guards

| Guard | Polarity | Contract |
|---|---|---|
| `loop_enabled` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |

### B12.6 Actions

All actions are `@cv_action`-wrapped (A1). A raising action writes `context["_fault"]`, aborts the transition and routes to this machine's fault state; the snapshot writer refuses to persist a faulted context (MUST-01).

| Action |
|---|
| `defer` |
| `record_coverage` |
| `record_error` |
| `reset_cursor_to_start` |
| `set_cursor` |
| `set_speed` |
| `slow_clock` |
| `start_clock` |
| `stop_clock` |

### B12.7 Invariants

| ID | Invariant |
|---|---|
| **INV-B12-a** | Determinism (C-2.15): the same session parameters over the same recorded range produce byte-identical output across runs - and parity is measured over **delivered event sets** per machine, not only over derived outputs (E26-T06). |
| **INV-B12-b** | `cursor` moves monotonically during playback; only `SEEK` may move it backwards. |
| **INV-B12-c** | `CONSUMER_SLOW` slows the clock; it never drops events. Backpressure is coalescing on the transport, not lossy in the replay source (P6). |
| **INV-B12-d** | `coverage_gaps` are surfaced to the consumer as explicit gaps, never interpolated (C-2.14). |
| **INV-B12-e** | `destroyed` releases the paper account and the source handles exactly once. |

- **Corrected 2026-10-01 (E50-S02, `tools/lint_statecharts.py` CV-LINT-KILL-ANCESTOR):** root `on.KILL` → existing `error` with `audit_kill` (C-04); `buffering`/`stepping` now have a kill ancestor.

---

## B13 — ExchangeConnection (WS reconnect / resync)

| | |
|---|---|
| **Machine `id`** | `ws_conn` |
| **Root type** | `compound`, initial `disconnected` |
| **Owning epic** | E08 - Bybit adapter & ingestion skeleton |
| **Schema owner** | 20-architecture.md §3.1, §10.4 (reconnect and resync); 24 §14.2-14.3 |
| **Fit (research)** | Good |
| **Event rate** | rare transitions; steady state is a heartbeat |
| **States / leaves / finals** | 9 / 9 / 1 |

**Purpose.** One WebSocket connection's lifecycle: connect, authenticate, subscribe in batches, live with heartbeats, backoff, close - plus the connection-rate budget.

**Why this shape.** `budget_blocked` is an explicit state. Bybit's connection-rate limit is a known-limit-ledger entry (20 §1.2), and a reconnect storm that silently burns it is a self-inflicted outage; making it a state makes it observable and alertable.

### B13.1 Contract (normative)

```json
{
  "id": "ws_conn",
  "actionErrorPolicy": "rollback",
  "onUnhandled": "defer",
  "guardErrorPolicy": "raise",
  "strictTargets": true,
  "strict": true,
  "spawnBlockingTimeout": 5000,
  "on": {
    "KILL": {
      "target": "#ws_conn.closed",
      "actions": [
        "audit_kill"
      ]
    }
  },
  "initial": "disconnected",
  "context": {
    "env": null,
    "kind": "public",
    "account_id": null,
    "attempt": 0,
    "backoff_ms": 500,
    "max_backoff_ms": 30000,
    "conn_budget_remaining": 500,
    "last_pong_us": 0,
    "pending_topics": [],
    "subscribed_topics": []
  },
  "states": {
    "disconnected": {
      "on": {
        "CONNECT": [
          {
            "target": "#ws_conn.budget_blocked",
            "guard": "connection_budget_exhausted"
          },
          {
            "target": "#ws_conn.connecting"
          }
        ]
      }
    },
    "budget_blocked": {
      "tags": [
        "degraded"
      ],
      "entry": [
        "raise_conn_budget_alert",
        "schedule_budget_recheck"
      ],
      "on": {
        "BUDGET_RECHECK": {
          "target": "#ws_conn.disconnected"
        }
      }
    },
    "connecting": {
      "entry": [
        "bump_attempt"
      ],
      "invoke": {
        "id": "dial",
        "src": "open_socket",
        "onDone": [
          {
            "target": "#ws_conn.authenticating",
            "guard": "is_private"
          },
          {
            "target": "#ws_conn.subscribing"
          }
        ],
        "onError": {
          "target": "#ws_conn.backing_off",
          "actions": [
            "record_conn_error"
          ]
        }
      }
    },
    "authenticating": {
      "invoke": {
        "id": "auth",
        "src": "ws_auth",
        "onDone": {
          "target": "#ws_conn.subscribing"
        },
        "onError": {
          "target": "#ws_conn.backing_off",
          "actions": [
            "record_auth_error"
          ]
        }
      }
    },
    "subscribing": {
      "invoke": {
        "id": "sub",
        "src": "subscribe_in_batches",
        "onDone": {
          "target": "#ws_conn.live",
          "actions": [
            "record_subscribed"
          ]
        },
        "onError": {
          "target": "#ws_conn.backing_off",
          "actions": [
            "record_sub_error"
          ]
        }
      },
      "on": {}
    },
    "live": {
      "entry": [
        "reset_backoff",
        "emit_feed_healthy",
        "arm_pong_deadline"
      ],
      "on": {
        "PONG": {
          "actions": [
            "stamp_pong",
            "rearm_pong_deadline"
          ]
        },
        "PONG_DEADLINE": {
          "target": "#ws_conn.backing_off",
          "actions": [
            "record_pong_timeout"
          ]
        },
        "SOCKET_CLOSED": {
          "target": "#ws_conn.backing_off"
        },
        "TOPIC_STALE": {
          "target": "#ws_conn.backing_off",
          "actions": [
            "record_staleness"
          ]
        },
        "TOPICS_CHANGED": {
          "target": "#ws_conn.subscribing",
          "actions": [
            "set_pending_topics"
          ]
        },
        "SHUTDOWN": {
          "target": "#ws_conn.closing"
        }
      }
    },
    "backing_off": {
      "entry": [
        "compute_jittered_backoff",
        "emit_feed_degraded",
        "schedule_backoff_deadline",
        "notify_dependents_degraded"
      ],
      "on": {
        "BACKOFF_DUE": {
          "target": "#ws_conn.connecting"
        },
        "SHUTDOWN": {
          "target": "#ws_conn.closing"
        }
      }
    },
    "closing": {
      "invoke": {
        "id": "cl",
        "src": "close_socket",
        "onDone": {
          "target": "#ws_conn.closed"
        },
        "onError": {
          "target": "#ws_conn.closed"
        }
      }
    },
    "closed": {
      "type": "final",
      "tags": [
        "terminal"
      ]
    }
  }
}
```

### B13.2 States

| State | Kind | Tags | Entry actions | Exit actions | Defers `*` |
|---|---|---|---|---|---|
| `disconnected` | atomic | — | — | — | — |
| `budget_blocked` | atomic | `degraded` | `raise_conn_budget_alert`, `schedule_budget_recheck` | — | — |
| `connecting` | atomic | — | `bump_attempt` | — | — |
| `authenticating` | atomic | — | — | — | — |
| `subscribing` | atomic | — | — | — | yes |
| `live` | atomic | — | `reset_backoff`, `emit_feed_healthy`, `arm_pong_deadline` | — | — |
| `backing_off` | atomic | — | `compute_jittered_backoff`, `emit_feed_degraded`, `schedule_backoff_deadline`, `notify_dependents_degraded` | — | — |
| `closing` | atomic | — | — | — | — |
| `closed` | final | `terminal` | — | — | — |

### B13.3 Events and transitions

| From | Event | Guard | Target | Actions | `reenter` |
|---|---|---|---|---|---|
| `disconnected` | `CONNECT` | `connection_budget_exhausted` | `budget_blocked` | — | — |
| `disconnected` | `CONNECT` | — | `connecting` | — | — |
| `budget_blocked` | `BUDGET_RECHECK` | — | `disconnected` | — | — |
| `subscribing` | `*` | — | _(internal)_ | `defer` | — |
| `live` | `PONG` | — | _(internal)_ | `stamp_pong`, `rearm_pong_deadline` | — |
| `live` | `PONG_DEADLINE` | — | `backing_off` | `record_pong_timeout` | — |
| `live` | `SOCKET_CLOSED` | — | `backing_off` | — | — |
| `live` | `TOPIC_STALE` | — | `backing_off` | `record_staleness` | — |
| `live` | `TOPICS_CHANGED` | — | `subscribing` | `set_pending_topics` | — |
| `live` | `SHUTDOWN` | — | `closing` | — | — |
| `backing_off` | `BACKOFF_DUE` | — | `connecting` | — | — |
| `backing_off` | `SHUTDOWN` | — | `closing` | — | — |

> Per-topic staleness is handled below the machine (#1913): the runtime resubscribes the stale topic on the live socket, and `TOPIC_STALE` fires only when every watched topic is stale. A `TOPICS_CHANGED` pass sends only the subscribe/unsubscribe diff and does not emit `resubscribing`.

### B13.4 Invoked services

| In state | `id` | `src` | `onDone` | `onError` |
|---|---|---|---|---|
| `connecting` | `dial` | `open_socket` | `authenticating` if `is_private`; `subscribing` | `backing_off` |
| `authenticating` | `auth` | `ws_auth` | `subscribing` | `backing_off` |
| `subscribing` | `sub` | `subscribe_in_batches` | `live` | `backing_off` |
| `closing` | `cl` | `close_socket` | `closed` | `closed` |

### B13.5 Guards

| Guard | Polarity | Contract |
|---|---|---|
| `connection_budget_exhausted` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `is_private` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |

### B13.6 Actions

All actions are `@cv_action`-wrapped (A1). A raising action writes `context["_fault"]`, aborts the transition and routes to this machine's fault state; the snapshot writer refuses to persist a faulted context (MUST-01).

| Action |
|---|
| `arm_pong_deadline` |
| `bump_attempt` |
| `compute_jittered_backoff` |
| `defer` |
| `emit_feed_degraded` |
| `emit_feed_healthy` |
| `notify_dependents_degraded` |
| `raise_conn_budget_alert` |
| `rearm_pong_deadline` |
| `record_auth_error` |
| `record_conn_error` |
| `record_pong_timeout` |
| `record_staleness` |
| `record_sub_error` |
| `record_subscribed` |
| `reset_backoff` |
| `schedule_backoff_deadline` |
| `schedule_budget_recheck` |
| `set_pending_topics` |
| `stamp_pong` |

### B13.7 Invariants

| ID | Invariant |
|---|---|
| **INV-B13-a** | `connection_budget_exhausted` is checked **before** opening a socket; the machine never attempts a connection it knows it cannot afford. |
| **INV-B13-b** | Backoff is jittered and monotonically increasing up to `max_backoff_ms`; it resets only on reaching `live`. |
| **INV-B13-c** | `subscribed_topics` after subscribing equals `pending_topics`; a partial batch subscribe re-enters subscribing rather than declaring `live`. |
| **INV-B13-d** | Health is published as a plain flag consumed by dependents. **No hot path queries this interpreter** (MUSTNOT-03). |
| **INV-B13-e** | Pong deadlines are absolute timestamps armed externally and re-armed on restore. |

### B13.8 Implementation notes

- This machine consumes the shared `SafeInterpreter`/`MachineGateway` utility (E29-T11) rather than its own interpreter handling.

- **Corrected 2026-10-01 (E50-S02, `tools/lint_statecharts.py` CV-LINT-POLICY / CV-LINT-KILL-ANCESTOR):** `onUnhandled` `"error"` → `"defer"` (R13-14 class: the mandatory block §1.3c is unconditional; an unexpected event is surfaced by `CvErrorHooks` on the control lane, not by bricking the interpreter); root `on.KILL` → existing final `closed` with `audit_kill` (C-04).

---

## B14 — Book health FSM (data path excluded)

| | |
|---|---|
| **Machine `id`** | `book` |
| **Root type** | `compound`, initial `init` |
| **Owning epic** | E08 - Bybit adapter & ingestion skeleton |
| **Schema owner** | 20-architecture.md §3.2 (book engine), §4.2 (backpressure) |
| **Fit (research)** | **Not suitable** (data path) / Good (health FSM with the data path excluded) |
| **Event rate** | health transitions only - resync/desync, not deltas |
| **States / leaves / finals** | 4 / 4 / 0 |

**Purpose.** The per-symbol order-book **health** state - awaiting snapshot, live, desynced - and the snapshot/delta sequencing discipline around it.

**Why this shape.** **This is the most dangerous machine in the catalogue to misread.** The contract specifies the health transitions and the sequencing rule. `apply_delta` and `buffer_delta` are named as actions **in the contract** so that the sequencing rule is stated in exactly one place; in the implementation they are plain function calls on the book engine's hot path, and **the per-delta path never enters an interpreter**. Measured: 48k ev/s of deltas against a ~9-20k process budget, with a 33 us statechart tax on 15-60 us of real work.

### B14.1 Contract (normative)

```json
{
  "id": "book",
  "actionErrorPolicy": "rollback",
  "onUnhandled": "defer",
  "guardErrorPolicy": "raise",
  "strictTargets": true,
  "strict": true,
  "spawnBlockingTimeout": 5000,
  "initial": "init",
  "context": {
    "symbol": null,
    "last_seq": 0,
    "snapshot_seq": 0,
    "buffered_deltas": [],
    "max_buffered_deltas": 1000,
    "resync_count": 0,
    "desynced_since_us": null
  },
  "states": {
    "init": {
      "on": {
        "SUBSCRIBE": {
          "target": "#book.snapshot_pending"
        }
      }
    },
    "snapshot_pending": {
      "entry": [
        "clear_buffer",
        "request_snapshot"
      ],
      "on": {
        "SNAPSHOT": {
          "target": "#book.live",
          "actions": [
            "install_snapshot",
            "replay_buffered_deltas_after_seq"
          ]
        },
        "DELTA": [
          {
            "target": "#book.desynced",
            "guard": "delta_buffer_full",
            "actions": [
              "audit_buffer_overflow"
            ]
          },
          {
            "actions": [
              "buffer_delta"
            ]
          }
        ],
        "BUFFER_OVERFLOW": {
          "target": "#book.desynced",
          "actions": [
            "audit_buffer_overflow"
          ]
        },
        "SNAPSHOT_TIMEOUT": {
          "target": "#book.snapshot_pending",
          "reenter": true,
          "actions": [
            "bump_resync_count"
          ]
        }
      }
    },
    "live": {
      "tags": [
        "consumable"
      ],
      "entry": [
        "emit_book_live"
      ],
      "on": {
        "DELTA": {
          "actions": [
            "apply_delta"
          ]
        },
        "SEQUENCE_GAP": {
          "target": "#book.desynced",
          "actions": [
            "stamp_desync"
          ]
        },
        "UNSUBSCRIBE": {
          "target": "#book.init"
        }
      }
    },
    "desynced": {
      "tags": [
        "not_consumable"
      ],
      "entry": [
        "emit_book_desynced",
        "bump_resync_count",
        "emit_resync_metric"
      ],
      "always": {
        "target": "#book.snapshot_pending"
      }
    }
  }
}
```

### B14.2 States

| State | Kind | Tags | Entry actions | Exit actions | Defers `*` |
|---|---|---|---|---|---|
| `init` | atomic | — | — | — | — |
| `snapshot_pending` | atomic | — | `clear_buffer`, `request_snapshot` | — | — |
| `live` | atomic | `consumable` | `emit_book_live` | — | — |
| `desynced` | atomic | `not_consumable` | `emit_book_desynced`, `bump_resync_count`, `emit_resync_metric` | — | — |

### B14.3 Events and transitions

| From | Event | Guard | Target | Actions | `reenter` |
|---|---|---|---|---|---|
| `init` | `SUBSCRIBE` | — | `snapshot_pending` | — | — |
| `snapshot_pending` | `SNAPSHOT` | — | `live` | `install_snapshot`, `replay_buffered_deltas_after_seq` | — |
| `snapshot_pending` | `DELTA` *(Corrected 2026-10-10, #2204, OC-08)* | `delta_buffer_full` | `desynced` | `audit_buffer_overflow` | — |
| `snapshot_pending` | `DELTA` | — | _(internal)_ | `buffer_delta` | — |
| `snapshot_pending` | `BUFFER_OVERFLOW` *(Corrected 2026-10-10, #2204, OC-08)* | — | `desynced` | `audit_buffer_overflow` | — |
| `snapshot_pending` | `SNAPSHOT_TIMEOUT` | — | `snapshot_pending` | `bump_resync_count` | yes |
| `live` | `DELTA` | — | _(internal)_ | `apply_delta` | — |
| `live` | `SEQUENCE_GAP` | — | `desynced` | `stamp_desync` | — |
| `live` | `UNSUBSCRIBE` | — | `init` | — | — |
| `desynced` | _always_ | — | `snapshot_pending` | — | — |

### B14.4 Guards

| Guard | Polarity | Contract |
|---|---|---|
| `delta_buffer_full` *(Corrected 2026-10-10, #2204, OC-08)* | pure predicate over `(context, event)` | `len(buffered_deltas) >= max_buffered_deltas`; no I/O; total; returns `True` (overflow ⇒ resync, fail-safe) on any internal error and logs at `ERROR` |

### B14.5 Actions

All actions are `@cv_action`-wrapped (A1). A raising action writes `context["_fault"]`, aborts the transition and routes to this machine's fault state; the snapshot writer refuses to persist a faulted context (MUST-01).

| Action |
|---|
| `apply_delta` |
| `audit_buffer_overflow` *(Corrected 2026-10-10, #2204)* |
| `buffer_delta` |
| `bump_resync_count` |
| `clear_buffer` |
| `emit_book_desynced` |
| `emit_book_live` |
| `emit_resync_metric` |
| `install_snapshot` |
| `replay_buffered_deltas_after_seq` |
| `request_snapshot` |
| `stamp_desync` |

### B14.6 Invariants

| ID | Invariant |
|---|---|
| **INV-B14-a** | **MUSTNOT-01 is absolute here.** Delta application, bar building and footprint aggregation are never executed by a statechart, in any form, including internal actions-only transitions. |
| **INV-B14-b** | Health is published as a plain bool/enum on state entry; consumers read the flag, they do not call `matches()` (MUSTNOT-03 - even *gating* by querying an interpreter measured 12x a bool read). |
| **INV-B14-c** | A sequence gap always drops state and re-snapshots; deltas are never applied across a gap (C-2.5, P5). |
| **INV-B14-d** | Deltas buffered while awaiting a snapshot are replayed strictly after `snapshot_seq`, and the buffer is bounded (C-2.18). *(Corrected 2026-10-10, #2204, OC-08)* The bound is the context value `max_buffered_deltas` (1 000, the same value as `book/resync.py` `BUFFER_BOUND`). A delta arriving with the buffer full, or an engine-side `BUFFER_OVERFLOW`, never grows the buffer: it writes `audit_buffer_overflow` and takes the resync path `desynced → snapshot_pending`, whose entry clears the buffer and requests a fresh snapshot (C-2.5). |
| **INV-B14-e** | `resync_count` and `desynced_since_us` are exported; a symbol resyncing repeatedly is visible. |

### B14.7 Implementation notes

- If a future reader is tempted to "just add an internal transition" for delta application because the contract names the action - that is precisely the failure MUSTNOT-01 exists to prevent.

- **Corrected 2026-10-01 (E50-S02, `tools/lint_statecharts.py` CV-LINT-POLICY):** `onUnhandled` `"error"` → `"defer"` (same rationale as B13); no invoking state, so no KILL arm is needed.
- **Corrected 2026-10-10 (#2204, OC-08):** the bounded buffer was prose only, and 1 000 `DELTA`s grew `buffered_deltas` 1:1. New context key `max_buffered_deltas`, guarded first arm `delta_buffer_full` on `snapshot_pending.DELTA` and a `BUFFER_OVERFLOW` edge, both → `desynced` with `audit_buffer_overflow`. The hot path still never sends `DELTA` to the interpreter (INV-B14-a). `BookEngine` enforces the same bound and now reports its overflow as `BUFFER_OVERFLOW` instead of the generic `SNAPSHOT_TIMEOUT`. Chart `version: 1`. The context shape changed, so an upcaster is registered (`book_upcasters.py`) that seeds `max_buffered_deltas` and has a golden-snapshot test.

---

## B15 — Paper-account liquidation FSM

| | |
|---|---|
| **Machine `id`** | `paper_account` |
| **Root type** | `compound`, initial `active` |
| **Owning epic** | E38 - Paper trading & demo/live parity |
| **Schema owner** | 24-internal-schemas.md §12.4 (margin, liquidation and ADL) |
| **Fit (research)** | **Not suitable** (paper matcher) / contract-only (account liquidation FSM) |
| **Event rate** | **edge-triggered only** - on band change, never per tick |
| **States / leaves / finals** | 4 / 4 / 1 |

**Purpose.** The margin-call / liquidation state of a simulated account.

**Why this shape.** Catalogued because it is a genuine three-state FSM that 24 §12.4 currently expresses as prose. The surrounding **paper matcher is on the do-not-use-for list**: the fill model, queue-position estimator and fee/funding arithmetic have no states and need virtual time, which no runtime here provides.

### B15.1 Contract (normative)

```json
{
  "id": "paper_account",
  "actionErrorPolicy": "rollback",
  "onUnhandled": "defer",
  "guardErrorPolicy": "raise",
  "strictTargets": true,
  "strict": true,
  "spawnBlockingTimeout": 5000,
  "initial": "active",
  "context": {
    "account_id": null,
    "equity": "0",
    "maintenance_margin": "0",
    "liq_price": null
  },
  "states": {
    "active": {
      "on": {
        "MARK_UPDATE": [
          {
            "target": "#paper_account.liquidating",
            "guard": "mark_crossed_liq_price"
          },
          {
            "target": "#paper_account.margin_call",
            "guard": "below_maintenance_margin"
          },
          {
            "actions": [
              "note_mark_no_change"
            ]
          }
        ]
      }
    },
    "margin_call": {
      "tags": [
        "warning"
      ],
      "entry": [
        "emit_margin_warning"
      ],
      "on": {
        "MARK_UPDATE": [
          {
            "target": "#paper_account.liquidating",
            "guard": "mark_crossed_liq_price"
          },
          {
            "target": "#paper_account.active",
            "guard": "above_maintenance_margin"
          },
          {
            "actions": [
              "note_mark_no_change"
            ]
          }
        ]
      }
    },
    "liquidating": {
      "entry": [
        "apply_liquidation_haircut",
        "write_liquidation_journal"
      ],
      "always": {
        "target": "#paper_account.liquidated"
      }
    },
    "liquidated": {
      "type": "final",
      "tags": [
        "terminal"
      ]
    }
  }
}
```

### B15.2 States

| State | Kind | Tags | Entry actions | Exit actions | Defers `*` |
|---|---|---|---|---|---|
| `active` | atomic | — | — | — | — |
| `margin_call` | atomic | `warning` | `emit_margin_warning` | — | — |
| `liquidating` | atomic | — | `apply_liquidation_haircut`, `write_liquidation_journal` | — | — |
| `liquidated` | final | `terminal` | — | — | — |

### B15.3 Events and transitions

| From | Event | Guard | Target | Actions | `reenter` |
|---|---|---|---|---|---|
| `active` | `MARK_UPDATE` | `mark_crossed_liq_price` | `liquidating` | — | — |
| `active` | `MARK_UPDATE` | `below_maintenance_margin` | `margin_call` | — | — |
| `margin_call` | `MARK_UPDATE` | `mark_crossed_liq_price` | `liquidating` | — | — |
| `margin_call` | `MARK_UPDATE` | `above_maintenance_margin` | `active` | — | — |
| `liquidating` | _always_ | — | `liquidated` | — | — |

### B15.4 Guards

| Guard | Polarity | Contract |
|---|---|---|
| `above_maintenance_margin` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `below_maintenance_margin` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `mark_crossed_liq_price` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |

### B15.5 Actions

All actions are `@cv_action`-wrapped (A1). A raising action writes `context["_fault"]`, aborts the transition and routes to this machine's fault state; the snapshot writer refuses to persist a faulted context (MUST-01).

| Action |
|---|
| `apply_liquidation_haircut` |
| `emit_margin_warning` |
| `write_liquidation_journal` |

### B15.6 Invariants

| ID | Invariant |
|---|---|
| **INV-B15-a** | `MARK_UPDATE` is **edge-triggered**: the margin evaluator computes the band in plain Python and sends an event only on a band change. Level-triggering this machine on mark updates would put market-rate traffic into the shared budget. |
| **INV-B15-b** | The liquidated state is terminal; the account is not silently revived by a favourable mark. |
| **INV-B15-c** | `write_liquidation_journal` runs before the terminal transition settles, so a liquidation is always journalled. |
| **INV-B15-d** | Paper and live use the same OMS code path; only the matcher differs (E38 demo/live parity). |

- **Corrected 2026-10-01 (E50-S02, `tools/lint_statecharts.py` CV-LINT-FALLTHROUGH):** ordered unguarded `note_mark_no_change` arm appended after the guarded `MARK_UPDATE` arms in `active` and `margin_call` (C-07b): a mark that crosses no threshold is an expected no-op, recorded rather than deferred.

---

## B16 — AuthSession / step-up

| | |
|---|---|
| **Machine `id`** | `session` |
| **Root type** | `parallel` (orthogonal regions) |
| **Owning epic** | E09 - Auth, sessions, 2FA & RBAC |
| **Schema owner** | 24-internal-schemas.md §15.1 (session model), §15.3 (step-up), ADR-0010 |
| **Fit (research)** | Good |
| **Event rate** | low; documented ~100-session threshold per process |
| **States / leaves / finals** | 10 / 8 / 2 |

**Purpose.** One session's authentication state and, orthogonally, its elevation (step-up) state.

**Why this shape.** Two regions: `auth` (pending MFA / active / idle-locked / revoked) and `elevation` (normal / elevated / read-only downgrade / dead). `elevated_until_us` becomes a **derived value of the elevation region** rather than a column someone can forget to check. The idle lock is a non-terminal `auth` state (ADR-0020 §4): it drops elevation, keeps a read-only downgrade, and only a password unlock (`UNLOCK_OK`) returns it to `active`.

### B16.1 Contract (normative)

```json
{
  "id": "session",
  "actionErrorPolicy": "rollback",
  "onUnhandled": "defer",
  "guardErrorPolicy": "raise",
  "strictTargets": true,
  "strict": true,
  "spawnBlockingTimeout": 5000,
  "type": "parallel",
  "on": {
    "LOGOUT": {
      "target": "#session.elevation.dead"
    },
    "ABSOLUTE_DEADLINE": {
      "target": "#session.elevation.dead"
    },
    "REVOKE": {
      "target": "#session.elevation.dead"
    },
    "UNLOCK_FAILED": [
      {
        "target": "#session.elevation.dead",
        "guard": "unlock_attempts_exhausted"
      },
      {
        "actions": []
      }
    ]
  },
  "context": {
    "session_id": null,
    "user_id": null,
    "expires_at_us": 0,
    "idle_expires_at_us": 0,
    "refresh_expires_at_us": 0,
    "elevated_until_us": null,
    "mfa_satisfied": false,
    "revoke_reason": null,
    "elevated_classes": {},
    "step_up_failures": 0,
    "readonly_until_us": null,
    "idle_locked": false,
    "unlock_attempts": 0,
    "one_click_armed": null
  },
  "states": {
    "auth": {
      "initial": "pending_mfa",
      "on": {
        "UNLOCK_OK": {
          "actions": [
            "audit_ignored_request"
          ]
        },
        "UNLOCK_FAILED": {
          "actions": [
            "audit_ignored_request"
          ]
        }
      },
      "states": {
        "pending_mfa": {
          "on": {
            "MFA_OK": {
              "target": "#session.auth.active",
              "actions": [
                "mark_mfa_satisfied",
                "audit_login"
              ]
            },
            "MFA_FAILED": [
              {
                "target": "#session.auth.revoked",
                "guard": "mfa_attempts_exhausted",
                "actions": [
                  "set_revoke_locked"
                ]
              },
              {
                "actions": [
                  "bump_mfa_attempts",
                  "audit_mfa_failed"
                ]
              }
            ],
            "MFA_TIMEOUT": {
              "target": "#session.auth.revoked",
              "actions": [
                "set_revoke_timeout"
              ]
            }
          }
        },
        "active": {
          "entry": [
            "stamp_idle_deadline"
          ],
          "on": {
            "REQUEST": {
              "target": "#session.auth.active",
              "reenter": true,
              "actions": [
                "stamp_idle_deadline"
              ]
            },
            "IDLE_DEADLINE": {
              "target": "#session.auth.idle_locked"
            },
            "ABSOLUTE_DEADLINE": {
              "target": "#session.auth.revoked",
              "actions": [
                "set_revoke_expired"
              ]
            },
            "REVOKE": {
              "target": "#session.auth.revoked",
              "actions": [
                "set_revoke_admin"
              ]
            },
            "LOGOUT": {
              "target": "#session.auth.revoked",
              "actions": [
                "set_revoke_logout"
              ]
            }
          }
        },
        "idle_locked": {
          "tags": [
            "locked"
          ],
          "entry": [
            "mark_idle_locked",
            "clear_elevated",
            "disarm_one_click",
            "audit_idle_locked"
          ],
          "exit": [
            "clear_idle_locked"
          ],
          "on": {
            "UNLOCK_OK": {
              "target": "#session.auth.active",
              "actions": [
                "stamp_idle_deadline",
                "audit_session_unlocked"
              ]
            },
            "UNLOCK_FAILED": [
              {
                "target": "#session.auth.revoked",
                "guard": "unlock_attempts_exhausted",
                "actions": [
                  "set_revoke_locked"
                ]
              },
              {
                "actions": [
                  "bump_unlock_attempts",
                  "audit_unlock_failed"
                ]
              }
            ],
            "REQUEST": {
              "actions": [
                "audit_ignored_request"
              ]
            },
            "ABSOLUTE_DEADLINE": {
              "target": "#session.auth.revoked",
              "actions": [
                "set_revoke_expired"
              ]
            },
            "REVOKE": {
              "target": "#session.auth.revoked",
              "actions": [
                "set_revoke_admin"
              ]
            },
            "LOGOUT": {
              "target": "#session.auth.revoked",
              "actions": [
                "set_revoke_logout"
              ]
            }
          }
        },
        "revoked": {
          "type": "final",
          "tags": [
            "terminal"
          ],
          "entry": [
            "audit_session_revoked",
            "broadcast_revocation"
          ]
        }
      }
    },
    "elevation": {
      "initial": "normal",
      "on": {
        "IDLE_DEADLINE": {
          "actions": []
        }
      },
      "states": {
        "normal": {
          "tags": [
            "not_elevated"
          ],
          "on": {
            "STEP_UP_OK": [
              {
                "target": "#session.elevation.elevated",
                "guard": "session_unlocked",
                "actions": [
                  "stamp_elevated_until",
                  "audit_step_up"
                ]
              },
              {
                "actions": [
                  "audit_ignored_request"
                ]
              }
            ],
            "STEP_UP_FAILED": [
              {
                "target": "#session.elevation.readonly_downgrade",
                "guard": "step_up_strikes_exhausted",
                "actions": [
                  "record_step_up_failure",
                  "audit_step_up_failed",
                  "audit_readonly_downgrade"
                ]
              },
              {
                "actions": [
                  "record_step_up_failure",
                  "audit_step_up_failed"
                ]
              }
            ],
            "ACTION_REQUEST": [
              {
                "actions": [
                  "audit_step_up_required"
                ]
              }
            ]
          }
        },
        "elevated": {
          "tags": [
            "elevated"
          ],
          "entry": [
            "schedule_elevation_deadline"
          ],
          "on": {
            "ELEVATION_DEADLINE": {
              "target": "#session.elevation.normal",
              "actions": [
                "clear_elevated"
              ]
            },
            "STEP_UP_OK": {
              "target": "#session.elevation.elevated",
              "reenter": true,
              "actions": [
                "stamp_elevated_until",
                "audit_step_up"
              ]
            },
            "STEP_UP_FAILED": [
              {
                "target": "#session.elevation.readonly_downgrade",
                "guard": "step_up_strikes_exhausted",
                "actions": [
                  "record_step_up_failure",
                  "audit_step_up_failed",
                  "audit_readonly_downgrade"
                ]
              },
              {
                "actions": [
                  "record_step_up_failure",
                  "audit_step_up_failed"
                ]
              }
            ],
            "ACTION_REQUEST": [
              {
                "guard": "grace_window_valid",
                "actions": [
                  "audit_grace_used"
                ]
              },
              {
                "actions": [
                  "audit_step_up_required"
                ]
              }
            ],
            "IDLE_DEADLINE": {
              "target": "#session.elevation.normal",
              "actions": [
                "clear_elevated"
              ]
            }
          }
        },
        "dead": {
          "type": "final"
        },
        "readonly_downgrade": {
          "tags": [
            "readonly"
          ],
          "entry": [
            "clear_elevated"
          ],
          "on": {
            "READONLY_EXPIRED": {
              "target": "#session.elevation.normal",
              "actions": [
                "clear_step_up_failures"
              ]
            }
          }
        }
      }
    }
  }
}
```

### B16.2 States

| State | Kind | Tags | Entry actions | Exit actions | Defers `*` |
|---|---|---|---|---|---|
| `auth` | compound | — | — | — | — |
| `auth.pending_mfa` | atomic | — | — | — | — |
| `auth.active` | atomic | — | `stamp_idle_deadline` | — | — |
| `auth.idle_locked` | atomic | `locked` | `mark_idle_locked`, `clear_elevated`, `disarm_one_click`, `audit_idle_locked` | `clear_idle_locked` | — |
| `auth.revoked` | final | `terminal` | `audit_session_revoked`, `broadcast_revocation` | — | — |
| `elevation` | compound | — | — | — | — |
| `elevation.normal` | atomic | `not_elevated` | — | — | — |
| `elevation.elevated` | atomic | `elevated` | `schedule_elevation_deadline` | — | — |
| `elevation.dead` | final | — | — | — | — |
| `elevation.readonly_downgrade` | atomic | `readonly` | `clear_elevated` | — | — |

### B16.3 Events and transitions

| From | Event | Guard | Target | Actions | `reenter` |
|---|---|---|---|---|---|
| `auth.pending_mfa` | `MFA_OK` | — | `auth.active` | `mark_mfa_satisfied`, `audit_login` | — |
| `auth.pending_mfa` | `MFA_FAILED` | `mfa_attempts_exhausted` | `auth.revoked` | `set_revoke_locked` | — |
| `auth.pending_mfa` | `MFA_FAILED` | — | _(internal)_ | `bump_mfa_attempts`, `audit_mfa_failed` | — |
| `auth.pending_mfa` | `MFA_TIMEOUT` | — | `auth.revoked` | `set_revoke_timeout` | — |
| `auth.active` | `REQUEST` | — | `auth.active` | `stamp_idle_deadline` | yes |
| `auth.active` | `IDLE_DEADLINE` | — | `auth.idle_locked` | — | — |
| `auth.active` | `ABSOLUTE_DEADLINE` | — | `auth.revoked` | `set_revoke_expired` | — |
| `auth.active` | `REVOKE` | — | `auth.revoked` | `set_revoke_admin` | — |
| `auth.active` | `LOGOUT` | — | `auth.revoked` | `set_revoke_logout` | — |
| `auth.idle_locked` | `UNLOCK_OK` | — | `auth.active` | `stamp_idle_deadline`, `audit_session_unlocked` | — |
| `auth.idle_locked` | `UNLOCK_FAILED` | `unlock_attempts_exhausted` | `auth.revoked` | `set_revoke_locked` | — |
| `auth.idle_locked` | `UNLOCK_FAILED` | — | _(internal)_ | `bump_unlock_attempts`, `audit_unlock_failed` | — |
| `auth.idle_locked` | `REQUEST` | — | _(internal)_ | `audit_ignored_request` | — |
| `auth.idle_locked` | `ABSOLUTE_DEADLINE` | — | `auth.revoked` | `set_revoke_expired` | — |
| `auth.idle_locked` | `REVOKE` | — | `auth.revoked` | `set_revoke_admin` | — |
| `auth.idle_locked` | `LOGOUT` | — | `auth.revoked` | `set_revoke_logout` | — |
| `auth` | `UNLOCK_OK` / `UNLOCK_FAILED` | — | _(internal)_ | `audit_ignored_request` | — |
| `elevation.normal` | `STEP_UP_OK` | `session_unlocked` | `elevation.elevated` | `stamp_elevated_until`, `audit_step_up` | — |
| `elevation.normal` | `STEP_UP_OK` | — | _(internal)_ | `audit_ignored_request` | — |
| `elevation.normal` / `elevation.elevated` | `STEP_UP_FAILED` | `step_up_strikes_exhausted` | `elevation.readonly_downgrade` | `record_step_up_failure`, `audit_step_up_failed`, `audit_readonly_downgrade` | — |
| `elevation.normal` / `elevation.elevated` | `STEP_UP_FAILED` | — | _(internal)_ | `record_step_up_failure`, `audit_step_up_failed` | — |
| `elevation.normal` | `ACTION_REQUEST` | — | _(internal)_ | `audit_step_up_required` | — |
| `elevation.elevated` | `ELEVATION_DEADLINE` | — | `elevation.normal` | `clear_elevated` | — |
| `elevation.elevated` | `STEP_UP_OK` | — | `elevation.elevated` | `stamp_elevated_until`, `audit_step_up` | yes |
| `elevation.elevated` | `ACTION_REQUEST` | `grace_window_valid` | _(internal)_ | `audit_grace_used` | — |
| `elevation.elevated` | `ACTION_REQUEST` | — | _(internal)_ | `audit_step_up_required` | — |
| `elevation.elevated` | `IDLE_DEADLINE` | — | `elevation.normal` | `clear_elevated` | — |
| `elevation.readonly_downgrade` | `READONLY_EXPIRED` | — | `elevation.normal` | `clear_step_up_failures` | — |
| `elevation` | `IDLE_DEADLINE` | — | _(internal)_ | — | — |
| _(root)_ | `LOGOUT` / `ABSOLUTE_DEADLINE` / `REVOKE` | — | `elevation.dead` | — | — |
| _(root)_ | `UNLOCK_FAILED` | `unlock_attempts_exhausted` | `elevation.dead` | — | — |
| _(root)_ | `UNLOCK_FAILED` | — | _(internal)_ | — | — |

### B16.4 Guards

| Guard | Polarity | Contract |
|---|---|---|
| `mfa_attempts_exhausted` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `step_up_strikes_exhausted` | pure predicate over `(context, event)` | this failure is the third consecutive step-up failure; total (A6) |
| `grace_window_valid` | pure predicate over `(context, event)` | an unexpired grace window for `event.action_class`, never for a no-grace class; total, fails closed (A6) |
| `unlock_attempts_exhausted` | pure predicate over `(context, event)` | this failure is the fifth consecutive failed unlock (`SessionService.MAX_UNLOCK_ATTEMPTS`); total (A6) |
| `session_unlocked` | pure predicate over `(context, event)` | `True` only while `context.idle_locked` is explicitly `false`; deny-by-default (A6), so elevation is never granted while locked |

### B16.5 Actions

All actions are `@cv_action`-wrapped (A1). A raising action writes `context["_fault"]`, aborts the transition and routes to this machine's fault state; the snapshot writer refuses to persist a faulted context (MUST-01). `disarm_one_click` records `one_click_armed: false` and publishes that plain flag to the session's arm record, which the OMS validator reads synchronously (C-2.20, C-2.21; #2305); it never re-arms. `clear_elevated` only records the elevation drop in context. No gate reads chart state: the step-up gate reads `sessions.step_up_elevations`, which `SessionService.unlock()` clears (B16.7).

| Action |
|---|
| `audit_grace_used` |
| `audit_idle_locked` |
| `audit_ignored_request` |
| `audit_login` |
| `audit_mfa_failed` |
| `audit_readonly_downgrade` |
| `audit_session_revoked` |
| `audit_session_unlocked` |
| `audit_step_up` |
| `audit_step_up_failed` |
| `audit_step_up_required` |
| `audit_unlock_failed` |
| `broadcast_revocation` |
| `bump_mfa_attempts` |
| `bump_unlock_attempts` |
| `clear_elevated` |
| `clear_idle_locked` |
| `clear_step_up_failures` |
| `disarm_one_click` |
| `mark_idle_locked` |
| `mark_mfa_satisfied` |
| `record_step_up_failure` |
| `schedule_elevation_deadline` |
| `set_revoke_admin` |
| `set_revoke_expired` |
| `set_revoke_locked` |
| `set_revoke_logout` |
| `set_revoke_timeout` |
| `stamp_elevated_until` |
| `stamp_idle_deadline` |

### B16.6 Invariants

| ID | Invariant |
|---|---|
| **INV-B16-a** | Elevation cannot outlive the session: leaving the active auth state clears elevation unconditionally. |
| **INV-B16-b** | Every revocation records a specific reason (logout / expired / admin / locked / timeout) and is broadcast to connected clients. |
| **INV-B16-c** | Every step-up attempt, success or failure, writes an audit record (C-2.9). |
| **INV-B16-d** | `revoked` is terminal for that session id; a session is never un-revoked. |
| **INV-B16-e** | Deadlines (absolute, idle, elevation) are absolute timestamps evaluated on access, so a deadline that expired while the process was down is honoured on restore. |
| **INV-B16-f** | A locked session is never un-revoked by unlock and never re-elevated by unlock. |
| **INV-B16-g** | Unlock requires the password factor and is audited: only `UNLOCK_OK`, sent after synchronous code verified the password, takes `auth.idle_locked` back to `auth.active`, and it writes `auth.session_unlocked`. |

> **Corrected 2026-09-24 (C-04 / R13-13 / R14-03, proven in `docs/research/xstate/battle-v0.9.1/contracts/g4_c04_c07b.py`, 11/11 both engines):** the four revocation events are hoisted to the root and target the new final `elevation.dead`, and the region-level `elevated.on.REVOKE` handler is **deleted** — a deeper handler outranks the root arm, so leaving it in landed `REVOKE` in `normal`, re-elevatable (the root hoist alone fixed 9/12 lanes). Re-elevation `STEP_UP_OK` now also audits (INV-B16-c). This closes INV-B16-a on every kill event.

> **Corrected 2026-10-14 (#2301, PR #2290 Architect ruling rules 2-4):** the idle lock is the non-terminal `auth.idle_locked` (ADR-0020 §4), no longer a revocation, so `IDLE_DEADLINE` leaves the root hoist and `set_revoke_idle` is gone; `LOGOUT` / `ABSOLUTE_DEADLINE` / `REVOKE` keep the C-04 shape. The lock drops elevation and keeps a read-only downgrade (a one-factor unlock never inherits a two-factor grace). The chart records the drop (`clear_elevated`); `SessionService.unlock()` enforces it on the `sessions` row (B16.7, C-2.21). Four shapes are deliberate, each measured on 0.9.1 through the factory: (1) **`IDLE_DEADLINE` lives in the `elevation` region, not on the root.** The library selects one transition per active leaf, so a root `IDLE_DEADLINE -> elevation.normal` arm also fires from every auth leaf without its own arm: it re-entered `normal` from `dead` (a revoked session could then be re-elevated, the C-04 class) and dropped `readonly_downgrade` on a repeated lock signal. `elevated` leaves for `normal`; every other elevation state absorbs the event. (2) `session_unlocked` on `normal.STEP_UP_OK` (the `idle_locked` flag is set on lock entry and cleared on exit) keeps `elevation.elevated` and `auth.idle_locked` exclusive for any event sequence. (3) `UNLOCK_OK` / `UNLOCK_FAILED` outside the lock are absorbed and audited on the `auth` region: under `onUnhandled: "defer"` a stray unlock was replayed into the next lock and lifted it. (4) `audit_login` moves from `active.entry` to the `MFA_OK` arm, because `UNLOCK_OK` re-enters `active` and an unlock is not a login. Lock-entry actions change context first and talk to the outside world last (CV-C02). The E09-S04 step-up drift (`readonly_downgrade`, `ACTION_REQUEST`, `READONLY_EXPIRED` and their guards and actions) is folded in, so this entry and the machine JSON agree.

### B16.7 Implementation notes

- Session machines are single-process-owned; beyond roughly 100 concurrent sessions the hosting assumption is re-examined (E09).
- The chart records the lock and the `sessions` row enforces it (`SessionService.require_active` refuses a locked session; C-2.21). `SessionChart` evaluates `is_idle_locked` on access (INV-B16-e) and records `IDLE_DEADLINE` before the next event, so an unlock is recorded against the still-locked row.
- The elevation drop is enforced on the `sessions` row; the chart only records it (C-2.12, C-2.21; PR #2290 ruling rule 4d). `StepUpService` decides from `sessions.step_up_elevations` alone (`require_elevation`, `consume_single_use`, `remaining_grace`, `pending_action_class`), so with `clear_elevated` alone a grace window or one-shot grant taken before the lock would survive a password-only unlock. `SessionService.unlock()` is the only path that re-stamps `last_seen_at` on a locked row (`touch()` and `refresh()` refuse one). On a successful unlock of a row that is idle-locked at that instant, it clears `step_up_elevations` (grace windows, `once:` grants and `pending:` challenges) in the same write that re-stamps `last_seen_at`. It keeps `readonly_until` and `step_up_failures`, so a read-only downgrade survives the lock. Any future path that lifts a lock must clear the same way. Owner: #2301, slice 2/2 (#2391), with a regression test: step up, idle-lock, unlock; then `require_elevation` and `consume_single_use` raise `StepUpRequired`, `SessionInfo.step_up_expires_at` is `null`, and `readonly_until` and `step_up_failures` are unchanged. `POST /auth/unlock` (#2300) is the first caller of `unlock()` and must not ship before this.

---

## B17 — LiveEnablement gate

| | |
|---|---|
| **Machine `id`** | `live_gate` |
| **Root type** | `compound`, initial `locked` |
| **Owning epic** | E44 - Live-enablement gating & environment separation |
| **Schema owner** | 24-internal-schemas.md §15.3; `07-release-and-prr.md` §6 (live-enablement gate) |
| **Fit (research)** | Excellent |
| **Event rate** | extremely low; audit-shaped |
| **States / leaves / finals** | 3 / 3 / 0 |

**Purpose.** The three-state gate controlling whether live trading may be enabled at all: locked, eligible, enabled.

**Why this shape.** `eligible` is **distinct from `locked`**: "all PRR evidence is present but nobody has enabled it" is a different fact from "evidence is missing", and only the first can be acted on. The feature flag becomes a *projection* of this state rather than the source of truth.

### B17.1 Contract (normative)

```json
{
  "id": "live_gate",
  "actionErrorPolicy": "rollback",   // CV-C31: "fail" forbidden until upstream R5-12 is fixed; halt via explicit `halted` state
  "onUnhandled": "defer",
  "guardErrorPolicy": "raise",
  "strictTargets": true,
  "strict": true,
  "spawnBlockingTimeout": 5000,
  "initial": "locked",
  "context": {
    "evidence": {
      "pentest_passed": false,
      "key_audit_passed": false,
      "env_separation_verified": false,
      "runbooks_signed": false
    },
    "enabled_by": null,
    "enabled_at_us": null,
    "disable_reason": null,
    "eligible_user_ids": []
  },
  "states": {
    "locked": {
      "tags": [
        "live_blocked"
      ],
      "on": {
        "EVIDENCE_RECORDED": [
          {
            "target": "#live_gate.eligible",
            "guard": "all_evidence_present",
            "actions": [
              "record_evidence"
            ]
          },
          {
            "actions": [
              "record_evidence"
            ]
          }
        ]
      }
    },
    "eligible": {
      "tags": [
        "live_blocked"
      ],
      "on": {
        "EVIDENCE_INVALIDATED": {
          "target": "#live_gate.locked",
          "actions": [
            "clear_evidence_item"
          ]
        },
        "ENABLE_REQUESTED": [
          {
            "target": "#live_gate.enabled",
            "guard": "owner_and_elevated_and_evidence_still_valid",
            "actions": [
              "record_enable",
              "audit_live_enabled"
            ]
          },
          {
            "actions": [
              "audit_enable_denied"
            ]
          }
        ]
      }
    },
    "enabled": {
      "tags": [
        "live_allowed"
      ],
      "entry": [
        "broadcast_live_enabled",
        "enable_live_visual_language"
      ],
      "on": {
        "DISABLE_REQUESTED": [
          {
            "target": "#live_gate.eligible",
            "guard": "owner_and_elevated",
            "actions": [
              "record_disable",
              "audit_live_disabled"
            ]
          },
          {
            "actions": [
              "audit_disable_denied"
            ]
          }
        ],
        "EVIDENCE_INVALIDATED": {
          "target": "#live_gate.locked",
          "actions": [
            "clear_evidence_item",
            "raise_critical_alert"
          ]
        },
        "EMERGENCY_DISABLE": {
          "target": "#live_gate.locked",
          "actions": [
            "record_disable",
            "raise_critical_alert"
          ]
        }
      }
    }
  }
}
```

### B17.2 States

| State | Kind | Tags | Entry actions | Exit actions | Defers `*` |
|---|---|---|---|---|---|
| `locked` | atomic | `live_blocked` | — | — | — |
| `eligible` | atomic | `live_blocked` | — | — | — |
| `enabled` | atomic | `live_allowed` | `broadcast_live_enabled`, `enable_live_visual_language` | — | — |

### B17.3 Events and transitions

| From | Event | Guard | Target | Actions | `reenter` |
|---|---|---|---|---|---|
| `locked` | `EVIDENCE_RECORDED` | `all_evidence_present` | `eligible` | `record_evidence` | — |
| `locked` | `EVIDENCE_RECORDED` | — | _(internal)_ | `record_evidence` | — |
| `eligible` | `EVIDENCE_INVALIDATED` | — | `locked` | `clear_evidence_item` | — |
| `eligible` | `ENABLE_REQUESTED` | `owner_and_elevated_and_evidence_still_valid` | `enabled` | `record_enable`, `audit_live_enabled` | — |
| `eligible` | `ENABLE_REQUESTED` | — | _(internal)_ | `audit_enable_denied` | — |
| `enabled` | `DISABLE_REQUESTED` | `owner_and_elevated` | `eligible` | `record_disable`, `audit_live_disabled` | — |
| `enabled` | `EVIDENCE_INVALIDATED` | — | `locked` | `clear_evidence_item`, `raise_critical_alert` | — |
| `enabled` | `EMERGENCY_DISABLE` | — | `locked` | `record_disable`, `raise_critical_alert` | — |

### B17.4 Guards

| Guard | Polarity | Contract |
|---|---|---|
| `all_evidence_present` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `owner_and_elevated` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `owner_and_elevated_and_evidence_still_valid` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |

### B17.5 Actions

All actions are `@cv_action`-wrapped (A1). A raising action writes `context["_fault"]`, aborts the transition and routes to this machine's fault state; the snapshot writer refuses to persist a faulted context (MUST-01).

| Action |
|---|
| `audit_enable_denied` |
| `audit_live_disabled` |
| `audit_live_enabled` |
| `broadcast_live_enabled` |
| `clear_evidence_item` |
| `enable_live_visual_language` |
| `raise_critical_alert` |
| `record_disable` |
| `record_enable` |
| `record_evidence` |

### B17.6 Invariants

| ID | Invariant |
|---|---|
| **INV-B17-a** | **MUSTNOT-05: this machine records and orchestrates; it does not enforce.** Live enforcement is a synchronous flag consulted by the order path before any interpreter is involved. |
| **INV-B17-b** | Enabling requires owner + step-up elevation + evidence that has not been invalidated since it was recorded. |
| **INV-B17-c** | `EVIDENCE_INVALIDATED` demotes `eligible` to `locked` immediately, and blocks the next enable check. |
| **INV-B17-d** | `EMERGENCY_DISABLE` requires no elevation and always succeeds. Disabling live is never gated. |
| **INV-B17-e** | Every enable, denial and disable is audited with the actor and the evidence set (C-2.9). |

### B17.7 Implementation notes

- Default is OFF, structurally: R0-R3 have no live code path at all (30 §11.3 rule 3).

- **Corrected 2026-10-01 (E50-S02, `tools/lint_statecharts.py` CV-LINT-FALLTHROUGH):** ordered unguarded `audit_disable_denied` arm appended after the guarded `enabled.DISABLE_REQUESTED` arm (C-07b, B18 shape).

---

## B18 — KillSwitch

| | |
|---|---|
| **Machine `id`** | `kill_switch` |
| **Root type** | `compound`, initial `clear` |
| **Owning epic** | E39 - Risk caps, lockouts & kill-switch |
| **Schema owner** | 24-internal-schemas.md §11.7 (safety limits and kill switches); 20 §4.3; ADR-0008 rule 8 |
| **Fit (research)** | Good - as record-and-orchestrate only |
| **Event rate** | extremely low |
| **States / leaves / finals** | 6 / 6 / 0 |

**Purpose.** Engage the kill switch: block new orders, cancel working orders, flatten positions, and record what actually completed.

**Why this shape.** `engaged_incomplete` exists because "we tried to flatten and some accounts are still open" is the state that actually matters operationally, and it must page rather than be rounded up to `engaged`.

### B18.1 Contract (normative)

```json
{
  "id": "kill_switch",
  "actionErrorPolicy": "rollback",   // CV-C31: "fail" forbidden until upstream R5-12 is fixed; halt via explicit `halted` state
  "onUnhandled": "defer",   // C-07b fix (R14-03): "error" bricked the switch on a guard-denied RELEASE
  "guardErrorPolicy": "raise",
  "strictTargets": true,
  "strict": true,
  "spawnBlockingTimeout": 5000,
  "on": {
    "KILL": {
      "target": "#kill_switch.engaged_incomplete",
      "actions": [
        "block_new_orders_immediately",
        "audit_kill"
      ]
    }
  },
  "initial": "clear",
  "context": {
    "scope": "global",
    "engaged_by": null,
    "engaged_at_us": null,
    "reason": null,
    "cancel_working": false,
    "flatten": false,
    "accounts_flat": 0,
    "accounts_total": 0
  },
  "states": {
    "clear": {
      "tags": [
        "trading_allowed"
      ],
      "on": {
        "ENGAGE": {
          "target": "#kill_switch.engaging",
          "actions": [
            "record_engagement",
            "audit_kill_switch"
          ]
        }
      }
    },
    "engaging": {
      "tags": [
        "trading_blocked"
      ],
      "entry": [
        "block_new_orders_immediately",
        "cancel_entry_and_poll_drains",
        "broadcast_kill_switch"
      ],
      "always": [
        {
          "target": "#kill_switch.cancelling",
          "guard": "cancel_working_requested"
        },
        {
          "target": "#kill_switch.engaged"
        }
      ]
    },
    "cancelling": {
      "tags": [
        "trading_blocked"
      ],
      "invoke": {
        "id": "cx",
        "src": "cancel_all_working_orders",
        "onDone": [
          {
            "target": "#kill_switch.flattening",
            "guard": "flatten_requested"
          },
          {
            "target": "#kill_switch.engaged"
          }
        ],
        "onError": {
          "target": "#kill_switch.engaged",
          "actions": [
            "raise_critical_alert"
          ]
        }
      }
    },
    "flattening": {
      "tags": [
        "trading_blocked"
      ],
      "invoke": {
        "id": "fl",
        "src": "flatten_all_positions",
        "onDone": [
          {
            "target": "#kill_switch.engaged",
            "guard": "all_accounts_flat"
          },
          {
            "target": "#kill_switch.engaged_incomplete"
          }
        ],
        "onError": {
          "target": "#kill_switch.engaged_incomplete",
          "actions": [
            "raise_critical_alert"
          ]
        }
      }
    },
    "engaged": {
      "tags": [
        "trading_blocked"
      ],
      "on": {
        "RELEASE": [
          {
            "target": "#kill_switch.clear",
            "guard": "owner_and_elevated",
            "actions": [
              "audit_kill_switch_released"
            ]
          },
          {
            "actions": [
              "audit_release_denied"
            ]
          }
        ]
      }
    },
    "engaged_incomplete": {
      "tags": [
        "trading_blocked",
        "critical"
      ],
      "entry": [
        "page_owner",
        "emit_incomplete_metric"
      ],
      "on": {
        "RETRY_FLATTEN": {
          "target": "#kill_switch.flattening"
        },
        "RELEASE": [
          {
            "target": "#kill_switch.clear",
            "guard": "owner_and_elevated_and_acknowledged_residual"
          },
          {
            "actions": [
              "audit_release_denied"
            ]
          }
        ]
      }
    }
  }
}
```

### B18.2 States

| State | Kind | Tags | Entry actions | Exit actions | Defers `*` |
|---|---|---|---|---|---|
| `clear` | atomic | `trading_allowed` | — | — | — |
| `engaging` | atomic | `trading_blocked` | `block_new_orders_immediately`, `cancel_entry_and_poll_drains`, `broadcast_kill_switch` | — | — |
| `cancelling` | atomic | `trading_blocked` | — | — | — |
| `flattening` | atomic | `trading_blocked` | — | — | — |
| `engaged` | atomic | `trading_blocked` | — | — | — |
| `engaged_incomplete` | atomic | `trading_blocked`, `critical` | `page_owner`, `emit_incomplete_metric` | — | — |

### B18.3 Events and transitions

| From | Event | Guard | Target | Actions | `reenter` |
|---|---|---|---|---|---|
| `clear` | `ENGAGE` | — | `engaging` | `record_engagement`, `audit_kill_switch` | — |
| `engaging` | _always_ | `cancel_working_requested` | `cancelling` | — | — |
| `engaging` | _always_ | — | `engaged` | — | — |
| `engaged` | `RELEASE` | `owner_and_elevated` | `clear` | `audit_kill_switch_released` | — |
| `engaged` | `RELEASE` | — *(ordered unguarded audit arm)* | _(internal)_ | `audit_release_denied` | — |
| `engaged_incomplete` | `RETRY_FLATTEN` | — | `flattening` | — | — |
| `engaged_incomplete` | `RELEASE` | `owner_and_elevated_and_acknowledged_residual` | `clear` | — | — |

### B18.4 Invoked services

| In state | `id` | `src` | `onDone` | `onError` |
|---|---|---|---|---|
| `cancelling` | `cx` | `cancel_all_working_orders` | `flattening` if `flatten_requested`; `engaged` | `engaged` |
| `flattening` | `fl` | `flatten_all_positions` | `engaged` if `all_accounts_flat`; `engaged_incomplete` | `engaged_incomplete` |

### B18.5 Guards

| Guard | Polarity | Contract |
|---|---|---|
| `all_accounts_flat` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `cancel_working_requested` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `flatten_requested` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `owner_and_elevated` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `owner_and_elevated_and_acknowledged_residual` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |

### B18.6 Actions

All actions are `@cv_action`-wrapped (A1). A raising action writes `context["_fault"]`, aborts the transition and routes to this machine's fault state; the snapshot writer refuses to persist a faulted context (MUST-01).

| Action |
|---|
| `audit_kill_switch` |
| `audit_kill_switch_released` |
| `audit_release_denied` |
| `block_new_orders_immediately` |
| `broadcast_kill_switch` |
| `cancel_entry_and_poll_drains` |
| `emit_incomplete_metric` |
| `page_owner` |
| `raise_critical_alert` |
| `record_engagement` |

### B18.7 Invariants

| ID | Invariant |
|---|---|
| **INV-B18-a** | **MUSTNOT-05 / MUSTNOT-03: the block is a synchronous flag.** `block_new_orders_immediately` runs on entry to the engaging state and sets a plain boolean the `Validator` reads. Measured, asking an interpreter costs 33.5 ms p50 / 50.8 ms max at a realistic 2,854-interpreter fleet - and `send()` is fire-and-forget, so it cannot answer "am I blocked?" at all. |
| **INV-B18-b** | Blocking takes effect **before** the event that records it is processed (E39-S03/Q03: asserted with the loop saturated). |
| **INV-B18-c** | `engaged` requires `accounts_flat == accounts_total`; anything less is `engaged_incomplete` and pages the owner. |
| **INV-B18-d** | Release requires owner + elevation + explicit acknowledgement of the residual. |
| **INV-B18-e** | Engagement and release are audited with actor, scope, reason and timestamps (C-2.9). |
| **INV-B18-f** | *(2026-09-24, C-07b fix)* A guard-denied `RELEASE` never faults the machine: it is audited (`audit_release_denied`) and the switch stays `engaged` and releasable. Root `onUnhandled` is `"defer"`, not `"error"`. |

> **Corrected 2026-09-24 (C-07b / R13-14 / R14-03, proven in `g4_c04_c07b.py` on both engines):** under the former root `onUnhandled: "error"`, a guard-denied `RELEASE` made the kill switch fatal and permanently bricked. Fix = `"defer"` + an ordered unguarded audit arm after the guarded `RELEASE`.

- **Corrected 2026-10-01 (E50-S02, `tools/lint_statecharts.py` CV-LINT-FALLTHROUGH / CV-LINT-KILL-ANCESTOR):** ordered unguarded `audit_release_denied` arm added to `engaged_incomplete.RELEASE` (mirrors `engaged`, C-07b); root `on.KILL` → existing `engaged_incomplete` (trading blocked, owner paged) with `block_new_orders_immediately` + `audit_kill` — fail-safe: a kill can never release the switch (C-04).

---

## B19 — Reconciliation job

| | |
|---|---|
| **Machine `id`** | `reconciliation` |
| **Root type** | `compound`, initial `idle` |
| **Owning epic** | E45 - Reconciliation, chaos & failover resilience |
| **Schema owner** | 24-internal-schemas.md §8.5 (reconciliation algorithm), §14.3; 20 §10.4 |
| **Fit (research)** | Good |
| **Event rate** | periodic sweeps plus event-triggered runs |
| **States / leaves / finals** | 8 / 8 / 0 |

**Purpose.** Fetch authoritative exchange state, diff it against local state, remediate, report - and lock the account out if reconciliation itself cannot succeed.

**Why this shape.** A linear pipeline of long-running invokes, which is the strongest measured shape: cancelling a mid-flight sweep delivers `CancelledError`, honours `finally`, returns promptly, and does **not** later deliver a stale `done.invoke`. A stale reconciliation result applied after a newer sweep would be a genuine corruption path. `stale_lockout` is added explicitly - E45-T02 mentions stale-account lockout but 24 §8.5 does not model it.

### B19.1 Contract (normative)

```json
{
  "id": "reconciliation",
  "actionErrorPolicy": "rollback",
  "onUnhandled": "defer",
  "guardErrorPolicy": "raise",
  "strictTargets": true,
  "strict": true,
  "spawnBlockingTimeout": 5000,
  "on": {
    "KILL": {
      "target": "#reconciliation.stale_lockout",
      "actions": [
        "audit_kill"
      ]
    }
  },
  "initial": "idle",
  "context": {
    "account_id": null,
    "trigger": null,
    "started_us": null,
    "orders_checked": 0,
    "divergences": [],
    "remediations": [],
    "consecutive_failures": 0,
    "auto_remediate": true
  },
  "states": {
    "idle": {
      "on": {
        "SWEEP_DUE": {
          "target": "#reconciliation.fetching",
          "actions": [
            "set_trigger_periodic"
          ]
        },
        "RECONNECTED": {
          "target": "#reconciliation.fetching",
          "actions": [
            "set_trigger_reconnect"
          ]
        },
        "UNKNOWN_ORDER": {
          "target": "#reconciliation.fetching",
          "actions": [
            "set_trigger_unknown"
          ]
        },
        "STARTUP": {
          "target": "#reconciliation.fetching",
          "actions": [
            "set_trigger_startup"
          ]
        }
      }
    },
    "fetching": {
      "entry": [
        "stamp_start",
        "emit_recon_started"
      ],
      "invoke": {
        "id": "fetch",
        "src": "fetch_exchange_state",
        "onDone": {
          "target": "#reconciliation.diffing",
          "actions": [
            "store_exchange_state"
          ]
        },
        "onError": [
          {
            "target": "#reconciliation.stale_lockout",
            "guard": "failures_exhausted"
          },
          {
            "target": "#reconciliation.backing_off",
            "actions": [
              "bump_failures"
            ]
          }
        ]
      },
      "on": {
        "CANCEL": {
          "target": "#reconciliation.idle"
        }
      }
    },
    "backing_off": {
      "entry": [
        "schedule_retry_deadline"
      ],
      "on": {
        "RETRY_DUE": {
          "target": "#reconciliation.fetching"
        },
        "CANCEL": {
          "target": "#reconciliation.idle"
        }
      }
    },
    "diffing": {
      "invoke": {
        "id": "diff",
        "src": "diff_against_local",
        "onDone": [
          {
            "target": "#reconciliation.remediating",
            "guard": "divergences_found_and_auto_remediate",
            "actions": [
              "store_divergences"
            ]
          },
          {
            "target": "#reconciliation.reporting",
            "actions": [
              "store_divergences"
            ]
          }
        ],
        "onError": {
          "target": "#reconciliation.reporting",
          "actions": [
            "record_diff_error"
          ]
        }
      }
    },
    "remediating": {
      "invoke": {
        "id": "rem",
        "src": "apply_remediations",
        "onDone": {
          "target": "#reconciliation.reporting",
          "actions": [
            "store_remediations"
          ]
        },
        "onError": {
          "target": "#reconciliation.reporting",
          "actions": [
            "store_remediations",
            "raise_critical_alert"
          ]
        }
      },
      "on": {}
    },
    "reporting": {
      "entry": [
        "persist_report",
        "emit_recon_metrics",
        "reset_failures",
        "broadcast_recon_complete"
      ],
      "always": [
        {
          "target": "#reconciliation.divergent",
          "guard": "unresolved_divergences"
        },
        {
          "target": "#reconciliation.idle"
        }
      ]
    },
    "divergent": {
      "tags": [
        "needs_attention"
      ],
      "entry": [
        "raise_divergence_alert"
      ],
      "on": {
        "OPERATOR_RESOLVED": {
          "target": "#reconciliation.idle"
        },
        "SWEEP_DUE": {
          "target": "#reconciliation.fetching"
        }
      }
    },
    "stale_lockout": {
      "tags": [
        "account_locked",
        "critical"
      ],
      "entry": [
        "lock_account_for_new_orders",
        "page_owner"
      ],
      "on": {
        "OPERATOR_RESOLVED": {
          "target": "#reconciliation.idle",
          "actions": [
            "audit_operator_resolved",
            "reset_failures",
            "unlock_account_for_new_orders"
          ]
        },
        "RECONNECTED": {
          "actions": [
            "audit_reconnect_while_locked"
          ]
        }
      }
    }
  }
}
```

### B19.2 States

| State | Kind | Tags | Entry actions | Exit actions | Defers `*` |
|---|---|---|---|---|---|
| `idle` | atomic | — | — | — | — |
| `fetching` | atomic | — | `stamp_start`, `emit_recon_started` | — | yes |
| `backing_off` | atomic | — | `schedule_retry_deadline` | — | — |
| `diffing` | atomic | — | — | — | — |
| `remediating` | atomic | — | — | — | yes |
| `reporting` | atomic | — | `persist_report`, `emit_recon_metrics`, `reset_failures`, `broadcast_recon_complete` | — | — |
| `divergent` | atomic | `needs_attention` | `raise_divergence_alert` | — | — |
| `stale_lockout` | atomic | `account_locked`, `critical` | `lock_account_for_new_orders`, `page_owner` | — | — |

### B19.3 Events and transitions

| From | Event | Guard | Target | Actions | `reenter` |
|---|---|---|---|---|---|
| `idle` | `SWEEP_DUE` | — | `fetching` | `set_trigger_periodic` | — |
| `idle` | `RECONNECTED` | — | `fetching` | `set_trigger_reconnect` | — |
| `idle` | `UNKNOWN_ORDER` | — | `fetching` | `set_trigger_unknown` | — |
| `idle` | `STARTUP` | — | `fetching` | `set_trigger_startup` | — |
| `fetching` | `CANCEL` | — | `idle` | — | — |
| `fetching` | `*` | — | _(internal)_ | `defer` | — |
| `backing_off` | `RETRY_DUE` | — | `fetching` | — | — |
| `backing_off` | `CANCEL` | — | `idle` | — | — |
| `remediating` | `*` | — | _(internal)_ | `defer` | — |
| `reporting` | _always_ | `unresolved_divergences` | `divergent` | — | — |
| `reporting` | _always_ | — | `idle` | — | — |
| `divergent` | `OPERATOR_RESOLVED` | — | `idle` | — | — |
| `divergent` | `SWEEP_DUE` | — | `fetching` | — | — |
| `stale_lockout` | `OPERATOR_RESOLVED` *(Corrected 2026-10-10, #2204, OC-05)* | — | `idle` | `audit_operator_resolved`, `reset_failures`, `unlock_account_for_new_orders` | — |
| `stale_lockout` | `RECONNECTED` *(Corrected 2026-10-10, #2204, OC-05; was → `fetching`)* | — | _(internal)_ | `audit_reconnect_while_locked` | — |

### B19.4 Invoked services

| In state | `id` | `src` | `onDone` | `onError` |
|---|---|---|---|---|
| `fetching` | `fetch` | `fetch_exchange_state` | `diffing` | `stale_lockout` if `failures_exhausted`; `backing_off` |
| `diffing` | `diff` | `diff_against_local` | `remediating` if `divergences_found_and_auto_remediate`; `reporting` | `reporting` |
| `remediating` | `rem` | `apply_remediations` | `reporting` | `reporting` |

### B19.5 Guards

| Guard | Polarity | Contract |
|---|---|---|
| `divergences_found_and_auto_remediate` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `failures_exhausted` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `unresolved_divergences` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |

### B19.6 Actions

All actions are `@cv_action`-wrapped (A1). A raising action writes `context["_fault"]`, aborts the transition and routes to this machine's fault state; the snapshot writer refuses to persist a faulted context (MUST-01).

| Action |
|---|
| `audit_operator_resolved` *(Corrected 2026-10-10, #2204)* |
| `audit_reconnect_while_locked` *(Corrected 2026-10-10, #2204)* |
| `broadcast_recon_complete` |
| `bump_failures` |
| `defer` |
| `emit_recon_metrics` |
| `emit_recon_started` |
| `lock_account_for_new_orders` |
| `page_owner` |
| `persist_report` |
| `raise_critical_alert` |
| `raise_divergence_alert` |
| `record_diff_error` |
| `reset_failures` |
| `schedule_retry_deadline` |
| `set_trigger_periodic` |
| `set_trigger_reconnect` |
| `set_trigger_startup` |
| `set_trigger_unknown` |
| `stamp_start` |
| `store_divergences` |
| `store_exchange_state` |
| `store_remediations` |
| `unlock_account_for_new_orders` *(Corrected 2026-10-10, #2204)* |

### B19.7 Invariants

| ID | Invariant |
|---|---|
| **INV-B19-a** | Reconciliation must not share a failure mode with what it repairs: the supervisor starts this machine **before** the OMS accepts orders, and its own faults escalate to `stale_lockout` rather than retrying forever. |
| **INV-B19-b** | `stale_lockout` locks the account for new orders and is cleared only by `OPERATOR_RESOLVED`. *(Corrected 2026-10-10, #2204, OC-05)* The chart now enforces this: `OPERATOR_RESOLVED` is the only arm leaving `stale_lockout` (→ `idle`, audited, account unlocked); `RECONNECTED` while locked is recorded (`audit_reconnect_while_locked`) and never clears the lock or re-pages. |
| **INV-B19-c** | Diffs are by `orderLinkId` (C-2.10); `Unknown` orders are resolved by lookup, never by blind resubmission. |
| **INV-B19-d** | `auto_remediate` is a **context value**, not a separate machine - capabilities drive behaviour, not conditionals (24 §14.3). |
| **INV-B19-e** | A crash during fetching is re-driven on restore by re-sending the triggering event; a machine parked mid-fetch with no live service is a silent hang, and is the single most consequential consequence of static restore (LC-19). E45-T06/T07 chaos-test exactly this. |
| **INV-B19-f** | Every sweep persists a report, whether or not divergences were found. |

- **Corrected 2026-10-01 (E50-S02, `tools/lint_statecharts.py` CV-LINT-KILL-ANCESTOR):** root `on.KILL` → existing `stale_lockout` (account locked for new orders, owner paged) with `audit_kill` — fail-safe, never back to `idle` (C-04).
- **Corrected 2026-10-10 (#2204, OC-05 / R10-C3):** `stale_lockout` handled only `RECONNECTED` (→ `fetching`), while `OPERATOR_RESOLVED` sat on `divergent`. That inverted INV-B19-b: a connectivity signal cleared a paged critical lockout with no operator in the loop and no distinct audit record, and a flapping link looped `fetching → stale_lockout`, re-paging the owner each lap. `stale_lockout` now leaves only on `OPERATOR_RESOLVED` (→ `idle`; `audit_operator_resolved`, `reset_failures`, `unlock_account_for_new_orders`). `RECONNECTED` there is an internal audit-only arm. The next `SWEEP_DUE`/`RECONNECTED` from `idle` re-reconciles. A KILL-induced lockout is cleared the same way, by the operator. Chart `version: 1`; context shape unchanged, so no upcaster.

---

## B20 — RiskLockout

| | |
|---|---|
| **Machine `id`** | `risk_lockout` |
| **Root type** | `compound`, initial `clear` |
| **Owning epic** | E39 - Risk caps, lockouts & kill-switch |
| **Schema owner** | 24-internal-schemas.md §11.7 (safety limits) |
| **Fit (research)** | Good |
| **Event rate** | **edge-triggered** on band change only |
| **States / leaves / finals** | 3 / 3 / 0 |

**Purpose.** Per-account risk lockout: clear, warning band, locked - with day-boundary or duration-based expiry and a step-up override.

**Why this shape.** `warning` is a distinct server-side state; today it is implicit in the dashboard design with no server representation. The lockout follows B18's architecture: the machine records, a synchronous flag enforces.

### B20.1 Contract (normative)

```json
{
  "id": "risk_lockout",
  "actionErrorPolicy": "rollback",   // CV-C31: "fail" forbidden until upstream R5-12 is fixed; halt via explicit `halted` state
  "onUnhandled": "defer",
  "guardErrorPolicy": "raise",
  "strictTargets": true,
  "strict": true,
  "spawnBlockingTimeout": 5000,
  "initial": "clear",
  "context": {
    "account_id": null,
    "scope": "account",
    "realised_pnl_today": "0",
    "max_daily_loss": "0",
    "breach_reason": null,
    "until_mode": "next_utc_day",
    "until_us": null,
    "cleared_by": null
  },
  "states": {
    "clear": {
      "tags": [
        "trading_allowed"
      ],
      "on": {
        "PNL_UPDATE": [
          {
            "target": "#risk_lockout.locked",
            "guard": "breaches_daily_loss_cap",
            "actions": [
              "set_breach_daily_loss"
            ]
          },
          {
            "target": "#risk_lockout.warning",
            "guard": "within_warning_band"
          },
          {
            "actions": [
              "update_pnl"
            ]
          }
        ],
        "CAP_BREACH": {
          "target": "#risk_lockout.locked",
          "actions": [
            "set_breach_from_event"
          ]
        },
        "MANUAL_LOCK": {
          "target": "#risk_lockout.locked",
          "actions": [
            "set_breach_manual"
          ]
        }
      }
    },
    "warning": {
      "tags": [
        "trading_allowed",
        "warning"
      ],
      "entry": [
        "emit_risk_warning"
      ],
      "on": {
        "PNL_UPDATE": [
          {
            "target": "#risk_lockout.locked",
            "guard": "breaches_daily_loss_cap",
            "actions": [
              "set_breach_daily_loss"
            ]
          },
          {
            "target": "#risk_lockout.clear",
            "guard": "outside_warning_band"
          },
          {
            "actions": [
              "update_pnl"
            ]
          }
        ]
      }
    },
    "locked": {
      "tags": [
        "trading_blocked"
      ],
      "entry": [
        "halt_new_orders",
        "compute_until",
        "schedule_expiry_deadline",
        "raise_lockout_alert",
        "audit_lockout",
        "broadcast_lockout"
      ],
      "on": {
        "EXPIRY_DUE": [
          {
            "target": "#risk_lockout.clear",
            "guard": "until_mode_is_time_based",
            "actions": [
              "resume_new_orders",
              "reset_daily_counters_if_new_day"
            ]
          },
          {
            "actions": [
              "log_expiry_ignored_manual_mode"
            ]
          }
        ],
        "OVERRIDE_REQUESTED": [
          {
            "target": "#risk_lockout.clear",
            "guard": "owner_and_elevated_and_override_permitted",
            "actions": [
              "resume_new_orders",
              "audit_override"
            ]
          },
          {
            "actions": [
              "audit_override_denied"
            ]
          }
        ]
      }
    }
  }
}
```

### B20.2 States

| State | Kind | Tags | Entry actions | Exit actions | Defers `*` |
|---|---|---|---|---|---|
| `clear` | atomic | `trading_allowed` | — | — | — |
| `warning` | atomic | `trading_allowed`, `warning` | `emit_risk_warning` | — | — |
| `locked` | atomic | `trading_blocked` | `halt_new_orders`, `compute_until`, `schedule_expiry_deadline`, `raise_lockout_alert`, `audit_lockout`, `broadcast_lockout` | — | — |

### B20.3 Events and transitions

| From | Event | Guard | Target | Actions | `reenter` |
|---|---|---|---|---|---|
| `clear` | `PNL_UPDATE` | `breaches_daily_loss_cap` | `locked` | `set_breach_daily_loss` | — |
| `clear` | `PNL_UPDATE` | `within_warning_band` | `warning` | — | — |
| `clear` | `PNL_UPDATE` | — | _(internal)_ | `update_pnl` | — |
| `clear` | `CAP_BREACH` | — | `locked` | `set_breach_from_event` | — |
| `clear` | `MANUAL_LOCK` | — | `locked` | `set_breach_manual` | — |
| `warning` | `PNL_UPDATE` | `breaches_daily_loss_cap` | `locked` | `set_breach_daily_loss` | — |
| `warning` | `PNL_UPDATE` | `outside_warning_band` | `clear` | — | — |
| `warning` | `PNL_UPDATE` | — | _(internal)_ | `update_pnl` | — |
| `locked` | `EXPIRY_DUE` | `until_mode_is_time_based` | `clear` | `resume_new_orders`, `reset_daily_counters_if_new_day` | — |
| `locked` | `EXPIRY_DUE` | — | _(internal)_ | `log_expiry_ignored_manual_mode` | — |
| `locked` | `OVERRIDE_REQUESTED` | `owner_and_elevated_and_override_permitted` | `clear` | `resume_new_orders`, `audit_override` | — |
| `locked` | `OVERRIDE_REQUESTED` | — | _(internal)_ | `audit_override_denied` | — |

### B20.4 Guards

| Guard | Polarity | Contract |
|---|---|---|
| `breaches_daily_loss_cap` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `outside_warning_band` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `owner_and_elevated_and_override_permitted` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `until_mode_is_time_based` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |
| `within_warning_band` | pure predicate over `(context, event)` | no I/O; total; returns `False` on any internal error and logs at `ERROR` (A6) |

### B20.5 Actions

All actions are `@cv_action`-wrapped (A1). A raising action writes `context["_fault"]`, aborts the transition and routes to this machine's fault state; the snapshot writer refuses to persist a faulted context (MUST-01).

| Action |
|---|
| `audit_lockout` |
| `audit_override` |
| `audit_override_denied` |
| `broadcast_lockout` |
| `compute_until` |
| `emit_risk_warning` |
| `halt_new_orders` |
| `log_expiry_ignored_manual_mode` |
| `raise_lockout_alert` |
| `reset_daily_counters_if_new_day` |
| `resume_new_orders` |
| `schedule_expiry_deadline` |
| `set_breach_daily_loss` |
| `set_breach_from_event` |
| `set_breach_manual` |
| `update_pnl` |

### B20.6 Invariants

| ID | Invariant |
|---|---|
| **INV-B20-a** | **MUSTNOT-05: `halt_new_orders` sets a synchronous flag consulted by the `Validator`**, not a query against this interpreter. |
| **INV-B20-b** | `PNL_UPDATE` is **edge-triggered on band change**. The risk evaluator computes the band in plain Python; level-triggering on mark updates would put market-rate traffic into the shared budget. |
| **INV-B20-c** | `breaches_daily_loss_cap` is deny-polarity (A6): a failure or exception blocks trading, never permits it. |
| **INV-B20-d** | A next-UTC-day expiry is an absolute timestamp in context, scheduled externally and re-armed on restore - **and on restore the machine re-evaluates whether the boundary already passed while the process was down**, because nothing re-fires a deadline that expired during downtime (E39-K01, E39-S02). |
| **INV-B20-e** | Manual mode ignores expiry deadlines and logs that it did so; a manual lock is never cleared by a clock. |
| **INV-B20-f** | Overrides require owner + elevation + permission, and are audited, including denials. |

### B20.7 Implementation notes

- The "deadline expired while the process was down" case is a class of bug that static restore creates across B5, B6, B16, B19 and B20 alike; it is handled once in the boot procedure, not per machine.

---

## 21. Cross-cutting contracts

These hold for every machine above. They are stated once here rather than repeated twenty times.

### 21.1 Reserved context keys

| Key | Type | Meaning | Rule |
|---|---|---|---|
| `_deferred` | list | events received in a state with no matching handler | drained at boot **unconditionally, before invokes are re-driven** (MUST-03); alerts if non-empty for > 5 s (MUST-04) |
| `_fault` | object / null | the record written by `@cv_action` when an action raised | a context carrying `_fault` is **never persisted**; a `quarantined` marker row is written and P1 alerts (MUST-01) |
| `*_us` | int / null | an **absolute** microsecond deadline | armed by the external `MonotonicScheduler`; re-armed from context on restore; a deadline that expired during downtime is resolved at boot, not silently skipped (A2) |

### 21.2 Deferral and ordering

Every state occupied while an exchange round trip is in flight is covered by the runtime's own `onUnhandled: "defer"` buffer (§1.3b); the retired A3 scaffolding (`` plus `drain_deferred` on entry) has been **stripped from every contract in this document** as of the round-5 pass — see §1.3b. Three consequences are binding:

1. **INV-5 is a per-family test**, not a nice-to-have: every delivered event id appears in the machine's applied set or in `_deferred`. This is the only regression test for silent event loss.
2. **Ordering is not a guarantee across a defer/drain boundary** (MUSTNOT-04). `apply_fill` and every aggregation action must be order-independent and sort by `(ts_exec, seq)` itself. Interpreter FIFO is not an OMS ordering guarantee.
3. **No bus message is acked before the resulting transition is observed** (MUSTNOT-07). The interpreter queue is volatile and absent from the snapshot.

### 21.3 Aggregate decisions

Every aggregate decision is a **pure function of context**, never of event arrival order. A raised event is queued behind pending external events rather than settling inside the macrostep, so a raised `EVALUATE` may be observed *after* a later external event. B2 is the worked example; the rule is universal.

### 21.4 Boot and restore

Restore is static: it does not re-run entry actions, does not restart invokes and does not re-arm deadlines. The boot procedure is therefore fixed, and identical for every family:

1. Restore the snapshot through the wrapper that merges `{**machine_defaults, **snapshot_context}` (MUST-06).
2. Verify `machine_hash`; on mismatch apply a registered upcaster with a golden-snapshot test, or fail closed. **No no-op upcasters** (MUSTNOT-09, MUST-12).
3. **Drain `_deferred`** through the gateway with dedupe, then clear it (MUST-03).
4. Re-drive every state carrying an `invoke`, by re-sending its triggering event.
5. Re-arm every `*_us` deadline from context, resolving any that expired during downtime.
6. Reconcile against the exchange before accepting new orders.

Step 3 must precede step 4. The two mitigations are coupled: a drain that lives only in an invoke target's `entry` strands the buffer forever after a crash, and the machine sits looking healthy with unapplied fills in its own context.

### 21.5 Observability (every machine)

| Metric | Meaning |
|---|---|
| `cv_machine_live_count{kind}` | live interpreters per family; alerts on monotonic growth (MUST-11) |
| `cv_machine_deferred_depth{kind}` | deferral-buffer depth; alerts above 0 for > 5 s (MUST-04) |
| `cv_machine_unhandled_events_total{kind,event}` | events with no handler; **CI fails** if a gateway sends an event absent from the machine's descriptor set (MUST-10) |
| `cv_machine_transition_seconds{kind}` | transition latency |
| `cv_machine_quarantined_total{kind}` | faulted transitions (A1 / MUST-01) |
| `cv_rule_prefilter_rejection_ratio` | B9 pre-filter quality; must hold at or above 0.99 (MUST-05) |

Every machine reaching a terminal state is explicitly stopped and evicted by the supervisor reaper (MUST-11). A terminal machine that is merely "done" still retains its context, its queue and its subscriptions.

### 21.6 Hot-path boundary objects

Four components exist purely to keep market-rate traffic out of the machines above. They are plain Python and they are **not** statecharts:

| Component | Feeds | Why it exists |
|---|---|---|
| `ChaseTargetTracker` | B7 `BOOK_TARGET_MOVED` | decimates book updates to at most 10 Hz |
| Rule trigger pre-filter (index) | B9 `TRIGGER` | must reject at least 99 %; below that, dispatch is disabled and alerts (MUST-05) |
| Risk band evaluator | B15 `MARK_UPDATE`, B20 `PNL_UPDATE` | edge-triggers on band change only |
| Rate-limit governor (token bucket) | B2 `reserve_rate_budget` | synchronous pre-flight admission; ~238,000x faster than the chart form, and able to answer synchronously at all (MUSTNOT-02) |

---

## 22. Gaps this catalogue exposes in the owning documents

Contracts were derived from `24-internal-schemas.md` and `20-architecture.md`. Six places where the contract is richer than its owning section. Each needs an edit in the **owning** document, not here (`CONSTITUTION.md` §16.5 single-source rule):

| Contract | Gap | Owner to update |
|---|---|---|
| B1 | `quarantined` is a fourteenth lifecycle state with no counterpart in the status enum; binding rules **S10** (deferral / no dropped fills) and **S11** (no action may raise) are new | `24` §8.2 |
| B3 | The per-account unwind is specified in prose in §9.5.1 and has **no ticket anywhere in the backlog** | `24` §9.5.1 + E34 |
| B8 | The SL deadline is 2 s in `24` §8.8 and 3000 ms in ADR-0008 — the two disagree and must be reconciled | `24` §8.8 / ADR-0008 |
| B10 | There is **no Alert schema section at all**; alerts exist only in E40, while every other stateful entity is specified in `24` | `24` — new §13.8 |
| B11 | `lingering` is a prose rule with no state in the enum | `24` §13.1 |
| B19 / B20 | `stale_lockout` and `warning` have no server-side representation | `24` §8.5, §11.7 |

---

## 23. Conformance

### 23.1 What conformance means

An implementation conforms to a contract when, for every event sequence, it produces **the same state trace and the same action trace** as the contract. Concretely:

- State names, event names, guard names and action names match the JSON exactly.
- The transition table matches: same source, same event, same guard ordering, same target.
- Every invariant in that entry's invariants table has a test.
- Deferral coverage matches: every state the contract marks as deferring actually defers.

Conformance is asserted on the library itself: the contract suite drives the chart through `cv.statechart.factory` with the production `logic` (or pure stubs for guard-matrix tests) and compares traces.

### 23.2 The gates

| Gate | Ticket | What it blocks |
|---|---|---|
| Machine JSON schema + Stately-compatibility validation | `E50-T01` | any malformed or non-portable contract |
| Target resolution, deferral coverage, `reenter`, action-decorator and guard-purity lint | `E29-T10` | the first statechart — MUST-09 requires it to land **before**, not alongside |
| `machine_hash` in CI | `E50-T02` | a semantic change to a shipped machine without a version bump or a registered upcaster (MUST-12) |
| Library contract suite (`tests/xstate_contract/`) | `E50-T03` | any divergence between a chart's golden state/action traces and what `xstate-statemachine` executes via `cv.statechart.factory`; includes the drain→restore round-trip (CV-C65′) and the four 2026-09-24 corrections (B8, B11, B16, B18) |
| Event-name coverage | `E50-T05` | a gateway sending an event no machine declares (MUST-10) |
| `tests/xstate_contract/` under 60 s | `E50-T06` | a gate slow enough to be skipped, which is not a gate |
| Upstream gate on pin bumps | `E50-T04` | bumping `xstate-statemachine==0.9.1` without a green `run_gate.py` + contract suite + BENCH-6 (`bench_c_timers_v2.py`) |

### 23.3 Pin and upgrade

There is no runtime switch. Every family runs on the pinned library from its first ticket. A new upstream release is adopted only by a PR that bumps the exact pin (never `~=`/`>=`) after `docs/research/xstate/gate/run_gate.py`, the contract suite on both engines, and BENCH-6 are green, recorded as a dated ADR-0016 amendment.

---

## 24. Traceability

| This document | Source |
|---|---|
| Machine JSON B1–B20 | `docs/research/xstate/10-fit-analysis.md` Part B |
| House rules A1–A8 (§1.3) | `10-fit-analysis.md` Part A |
| Do-not-use-for list (§1.2) | `11-adversarial-review.md` §5 + MUSTNOT-01/02/05 |
| MUST / MUST-NOT constraints | `11-adversarial-review.md` §3 (reproduced in ADR-0016) |
| Blocker / High closure criteria | `12-challenge-register.md` adoption-gate summary |
| Gate mechanics | `docs/research/xstate/20-adoption-gate.md`, `gate/run_gate.py` |
| Runtime decision | `27-adrs/ADR-0016-statechart-runtime.md` |
| Implementing epic | `docs/plan/backlog/E50.json` |
| Schema ownership | `24-internal-schemas.md`, `20-architecture.md` (named in each entry's header) |

---

<!-- BEGIN GENERATED: tools/statechart/render_catalogue.py -->
## 25. Generated machine index

> Regenerated by `tools/statechart/render_catalogue.py` from `services/api/candleviewer/statechart/machines/*.machine.json` via `candleviewer.statechart.registry`. Never hand-edit the table between the markers below — run `make gen` (or `python tools/statechart/render_catalogue.py`) instead; CI's `gen-check` job fails on drift.

| Machine id | States (top-level) | `machine_hash` |
|---|---|---|
| `alert` | 10 | `33a921e4d2fd…` |
| `book` | 4 | `73121e4a182f…` |
| `chase` | 13 | `bc6436827867…` |
| `iceberg` | 13 | `aecfc7ca58b8…` |
| `kill_switch` | 6 | `17b59ac92505…` |
| `leg` | 12 | `a7d8fb5d8c3e…` |
| `live_gate` | 3 | `780accfd0086…` |
| `oco` | 11 | `e09f72c6a367…` |
| `order` | 2 | `743dfaada4e3…` |
| `paper_account` | 4 | `401363766fb6…` |
| `position_protection` | 3 | `d95cda091fac…` |
| `reconciliation` | 8 | `95c8954fe5e7…` |
| `recording` | 8 | `94b98b086b28…` |
| `replay` | 8 | `61dfccf1be37…` |
| `risk_lockout` | 3 | `08f11db6dab6…` |
| `rule_instance` | 11 | `a60ff42011cf…` |
| `session` | 2 | `a6ac6e5bd897…` |
| `trade_group` | 10 | `c54de416e173…` |
| `twap` | 12 | `c121934637d0…` |
| `ws_conn` | 9 | `4103c8cba47a…` |
<!-- END GENERATED: tools/statechart/render_catalogue.py -->
