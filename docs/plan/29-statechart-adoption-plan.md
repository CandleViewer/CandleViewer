# 29 - Statechart Adoption Plan (full `xstate-statemachine` adoption)

Date: 2026-09-24 | Owner: basiltt | Status: **Binding plan. It executes ADR-0016 as Accepted.**
Inputs: `docs/research/xstate/79-r14-final-readiness-verdict.md` §6–§10 (decision-table **row 8**, the FINAL mandatory config block, constraints), `28-statechart-catalogue.md` (B1–B20), `27-adrs/ADR-0016-statechart-runtime.md`, `docs/research/xstate/battle-v0.9.1/contracts/` (the corrected catalogue JSON), `docs/research/xstate/gate/run_gate.py`, `docs/research/xstate/bench/bench_c_timers_v2.py`.

> **Owner decision (2026-09-24).** We adopt `xstate-statemachine` completely. There is no in-house shim, no dual-runtime harness and no phased shim retirement. Every catalogue lifecycle B1–B20 is built on the library from its first line of code. The remaining constraints are about **our architecture**, not the library:
> - Per-tick rule evaluation stays plain code, because BENCH-2 is 381 ev/s against a 2,000 ev/s need. That is permanent.
> - `after:` timers are allowed only where a p99 of ≤100 ms does not matter. BENCH-6 measured 55–92 ms; the target hardware is gated by P3-G6.
> - The one open library item is Medium: **R14-01**, `re_mint` accepting `type`/`src` overrides. The CV-C68 payload-only wrapper contains it.

**Pin (single source of truth):**

```toml
[project.dependencies]
xstate-statemachine = "==0.9.1"
# uv.lock / requirements hash: sha256:d832d4d9a17b7b8003f61fa0714a8e57eaff316bcd5dd699d81d410362687162
# anchor: tag v0.9.1 = 45bb7f3; wheel == tag (42/42 modules); PEP 740 attested
# CI:  python -m pypi_attestations verify pypi --repository https://github.com/basiltt/xstate-statemachine \
#          pypi:xstate_statemachine-0.9.1-py3-none-any.whl
```

ADR-0016 changes status from *Proposed (gated)* to **Accepted**. Its Part 2 (in-house shim) is **withdrawn**, and Part 3 (the gate) is **satisfied**. MUST-08 (vendored copy plus a one-line import switch) is superseded: the pin, hash and attestation above replace vendoring, and there is no second runtime to switch to.

---

## 1. Adoption architecture

### 1.1 Package layout

```
services/api/candleviewer/statechart/
  __init__.py            # re-exports build(), restore(), Gateway; nothing else is public
  factory.py             # the ONLY module that imports create_machine / Interpreter / SyncInterpreter
  config.py              # CV_INBOX_BOUND, CV_START_TIMEOUT, CV_EVENT_SCHEMAS, lane table (order|control|platform)
  persistence.py         # quiescent snapshot, HMAC envelope, restore, drain journal
  gateway.py             # send / send_threadsafe wrapper, cv_re_mint, refusal accounting
  registry.py            # loads machines/*.machine.json, validates, computes machine_hash
  plugins/
    errors.py            # CvErrorHooks  (on_transition_failed, on_invalid_event, on_event_dropped,
                         #                on_chain_budget_exceeded, on_invocation_stranded, on_receipt_dropped)
    metrics.py           # CvMetricsPlugin (cv_machine_* Prometheus families)
    audit.py             # CvAuditPlugin  (write-ahead machine_events rows; hash-chained audit M19)
  bindings/              # one MachineLogic module per machine: guards, actions, services (coroutines)
    b01_order.py ... b20_risk_lockout.py
  machines/
    B01.order.machine.json ... B20.risk_lockout.machine.json
    machine_hashes.lock  # committed; CI recomputes and diffs
tools/lint_statecharts.py  # AST + JSON lint (§1.6)
tests/xstate_contract/     # blocking CI gate (§1.7)
```

**Import rule, enforced by lint `CV-LINT-IMPORT`:** only `statechart/factory.py` and `statechart/persistence.py` may import from `xstate_statemachine`. `SyncInterpreter` is imported nowhere in production code (MUSTNOT-06). Test code may import `SyncInterpreter` only inside `tests/xstate_contract/` to gather parity information.

### 1.2 `factory.py`: the only construction site

`build(machine_key, *, ctx=None, clock, lane) -> Interpreter` and `restore(machine_key, blob, *, clock, lane) -> Interpreter`. Each one applies the FINAL mandatory block from 79-r14 §7 **unconditionally**. A caller cannot opt out of any part of it.

| Setting | Value | Where applied | Ground |
|---|---|---|---|
| `strict_config` | `True` kwarg **and** `"strictConfig": true` in the chart | `create_machine(...)` | #216/#220 |
| Recursive key check over every node, including inline `invoke.src` | our own `KNOWN_MACHINE_KEYS` walk | `registry.validate()` before `create_machine` | CV-C57 |
| `actionErrorPolicy` | `"rollback"` on every chart; services idempotent under re-entry (client id keyed on chart state, never on lap) | chart root, lint-checked | R10-D1 |
| `guardErrorPolicy` | **`"raise"`** on order-path and control charts (a raising guard surfaces as an error and never degrades to a silent deny). Every guarded-only arm carries an ordered unguarded auditing fall-through | chart root, lint-checked | C-07b / R12-14 |
| `onUnhandled` | `"defer"` on every chart, with an ordered, unguarded auditing arm. **Order lane:** `defer` preserves order (MUSTNOT-04 still applies). **Control lane:** a guard-denied or unhandled control event must *error out through `CvErrorHooks`* (page) and must never brick the machine, so the chart value is `defer` plus a hook-level `error` escalation. `"error"` as a chart value is banned (R13-14). | chart root + `CvErrorHooks.on_event_deferred` escalation table | R13-14, 79 §7 |
| `strictTargets` | `true` | chart root | A5 |
| `strict` | `True`; `event_schemas=CV_EVENT_SCHEMAS` | `Interpreter(...)` | unknown events refused |
| Inbox | `max_queue_size=CV_INBOX_BOUND[lane]`, `overflow_policy="refuse"`. The order lane **raises** `QueueOverflowError` to the caller (the gateway turns it into a 503 plus a page), and nothing is dropped silently | `Interpreter(...)` + `gateway.py` | CV-C36 |
| `maxIterations` | 500 default. Sized per chart against the **descent plateau** (`limit+3`) | chart root, lint | CV-C62 |
| Service pool | `service_pool_size=CV_SERVICE_POOL[lane]` (order 32, control 8, platform 16); ≤200 concurrent invoked children per process | `Interpreter(...)` | MUSTNOT-08 |
| Clock | `clock=` injected. Production uses the library monotonic clock; tests use `SimulatedClock`; replay uses `ReplayClock` | `Interpreter(...)` | CV-C10 |
| Plugins | `[CvErrorHooks(), CvMetricsPlugin(), CvAuditPlugin()]`. Fresh builds call `.use(...)`; restores **always** pass them through `from_snapshot(plugins=...)` | factory | R13-W1 |
| Start | `await asyncio.wait_for(interp.start(), CV_START_TIMEOUT)`. A timeout is a hard startup failure | factory | CV-C56 |
| Bring-up | `_cv_bring_up(interp)` in the factory. `on_interpreter_start` is telemetry only, branching on `restored_from_snapshot` | factory | CV-C66′ |
| Registry | a fresh `MachineLogic` per `create_machine()`, one spelling per implementation, and every action `asyncio.iscoroutinefunction`-asserted | `bindings/` loader | CV-C18, CV-C67 |
| Engine | the async `Interpreter` only | factory assert | MUSTNOT-06 |

### 1.3 `persistence.py`: snapshot, restore, HMAC, drain journal

**Snapshot, only at quiescence** (CV-C23, CV-C40, CV-C41, CV-C49′, CV-C65′):

```python
async def persist(interp, *, key: MachineKey) -> None:
    assert interp.started and interp.settled_after_start          # CV-C40, CV-C49'/C58
    drained = await interp.drain_pending()                        # both lanes, priority first (#239)
    for r in drained:
        if r.error is not None: audit.drain_error(key, r)         # R14-02
    journal.append(key, drained, dedupe_key=stable_send_id)       # replayed exactly once after restore
    blob = interp.get_persisted_snapshot()                        # root only (CV-C41); v3 carries chain_trips
    envelope = seal(blob, machine_hash=registry.hash(key),        # CV-C53: HMAC-SHA256 over chart bytes + blob
                    version=SNAPSHOT_V, key_id=KMS.current())     #   version >= 3
    await repo.write_snapshot(key, envelope)                      # never when context carries _fault (MUST-01)
    await interp.stop()
```

**Restore:**

```python
async def restore(key, envelope) -> Interpreter:
    blob = open_sealed(envelope)                                  # HMAC fail -> refuse, quarantine row, P1 alert
    interp = Interpreter.from_snapshot(machine, blob, minimum_version=3,          # CV-C52
                                       expected_machine_hash=registry.hash(key),  # MUST-12; never a no-op upcaster
                                       plugins=plugins())                         # R13-W1: kwarg, not .use()
    assert interp.last_transition_ok is not None and interp.last_error is None    # CV-C45'', CV-C60, before start()
    assert set(interp.state_ids) <= set(interp.configuration)                     # CV-C27'
    reconcile_counts(blob, interp)                                                # CV-C54
    _cv_bring_up(interp)                                                          # CV-C66'
    await asyncio.wait_for(interp.start(), CV_START_TIMEOUT)                      # CV-C56
    await journal.replay_once(key, interp)                                        # CV-C65'
    if interp.chain_trips > 0: latch.page(key, interp.last_chain_error)           # CV-C63: read the count
    return interp
```

**The `chain_trips` latch.** A restored machine with `chain_trips > 0` stays latched. It is admitted as *degraded*: it serves reads and refuses new order-path commands until an operator acknowledges it in the admin inspector (§4d, E42). Supervisors never poll `last_error` for chain health (CV-C59). They read `chain_trips` and `dropped_receipts`/`on_receipt_dropped` (CV-C69). The `on_receipt_dropped` hook body is thread-safe and never touches the loop.

**Compaction and migration jobs** always `start()` before re-persisting (CV-C58).

_Implemented (E50-T10):_ `persistence.Persister.persist` realises the snapshot block above with injected `SnapshotRepo` / `DrainJournal` / `PersistAudit` / seal callbacks (tables: `machine_snapshots`, `machine_drain_journal`, `24-internal-schemas.md` §17.6; migration E29-T12). A `_fault` context is refused and audited before anything is drained. `InMemoryDrainJournal` is the reference journal for the contract suite; restore + HMAC stay in E50-T49.

_Implemented (E50-T49):_ `persistence.Restorer.restore` realises the restore block above. `seal`/`open_sealed` compute HMAC-SHA256 over length-prefixed `canonical_json(chart) || canonical_json(blob) || machine_hash || version`, keyed by `HmacKeys.current()` and verified by the envelope's `key_id` (rotation-safe). Any refusal (bad HMAC, unknown key id, registry `machine_hash` mismatch, version < 3, library `Snapshot*Error`, a C45''/C60/C27'/C54 pre-start check) writes a quarantine row via `RestoreAudit` and pages P1; the blob is never loaded. `chain_trips > 0` sets `ChainTripLatch` (reads served, `admit_command` refuses) and pages. `factory.make_machine`/`apply_lane_config` are shared so a restored interpreter carries the same mandatory config as `build()`. The KMS-backed `HmacKeys`, Postgres quarantine sink and gateway consultation of the latch are wired by their owning tickets (E29-T12, E50-T15, E42).


### 1.4 `gateway.py`: the only send path

- `Gateway.send(key, event)` runs on the owning loop. `Gateway.send_threadsafe(key, event)` is the only cross-thread path (CV-C33, CV-C43-class loop affinity). It wraps `run_coroutine_threadsafe`, **reads every future** (CV-C36), and counts refusals in `cv_machine_send_refused_total{kind,reason}`.
- `priority=True` is never set, on any event, from any origin (CV-C42).
- A `wait=True` receipt with `changed=False, error=None` is never used as a gate on a `defer` chart (CV-C06).
- No `Event(system=True)` is ever constructed, and `is_system_event()` is never trusted (CV-C19).
- **`cv_re_mint(ev, **payload)`** accepts only `data`, `error`, `fired_at` and `scheduled_for`. Any other key raises `ReMintForbidden`, `type` and `src` in particular (CV-C68 / R14-01). A lint bans a bare `events.re_mint(` outside `gateway.py`.
- The event-name gate: every event name a gateway call site can send must be in the target machine's descriptor set. CI fails otherwise (MUST-10).

### 1.5 `registry.py`: machine JSON and `machine_hash`

- There is one file per lifecycle, `machines/B<nn>.<id>.machine.json`, extracted from `28-statechart-catalogue.md` §Bn.1. The files are seeded from `docs/research/xstate/battle-v0.9.1/contracts/`, which already carries the four our-side fixes:
  - **B16 C-04:** the revocation events are hoisted to the session root.
  - **B18 C-07b:** an unguarded auditing RELEASE fall-through.
  - **B11:** the R14-03 fix.
  - **B8 High:** the attempt counter B610-OC-CD03.
- The registry loads each file and validates it against the schema, checks every target and walks all keys recursively. It then computes `machine_hash = sha256(canonical_json(chart))` and diffs it against `machine_hashes.lock`. A hash change without a version bump **and** a registered upcaster with a golden-snapshot test fails the build (MUST-12, MUSTNOT-09).
  A lock entry with no recorded `version` (`None`) is treated as version `0` for this comparison: if the
  chart's hash changed and it now declares any integer `version`, that counts as a version bump (there is
  nothing to bump *from*). This only matters for a machine's first lock entry or one hand-edited to omit
  `version`; every machine added via `/statechart-new` starts at `version: 1` in its JSON.
- Charts are Stately-compatible. `registry.export_stately(key)` produces importable JSON for design review and for the admin inspector.

### 1.6 `tools/lint_statecharts.py`: the standing CV lint set

J = JSON rule, A = AST rule. Every rule is an error unless it is marked W (warning).

| Rule | Kind | Enforces |
|---|---|---|
| `CV-LINT-IMPORT` | A | Only factory and persistence import the library. No `SyncInterpreter` in production (MUSTNOT-06, CV-C03) |
| `CV-LINT-POLICY` | J | The mandatory root keys are present and sized (CV-C01, CV-C62) |
| `CV-LINT-FALLTHROUGH` | J | Every guarded-only arm has an ordered, unguarded, auditing fall-through (C-07b). Every operator-recovery event has an arm in each state that must honour it (R12-15) |
| `CV-LINT-ALWAYS` | J | No `always` into an invoke-bearing child, and no `always` to an ancestor (CV-C35) |
| `CV-LINT-KILL-ANCESTOR` | J | Kill/cancel events are declared on an ancestor of every invoking state (C-04) |
| `CV-LINT-REENTER` | J | Restart self-targets declare `reenter:true` (A4) |
| `CV-LINT-TIMER` | J | `after:`/`raise(delay=)` never on a state tagged `x-hard-deadline`; delay ≥10 ms; stable `send_id` (CV-C12′, CV-C55, R11-W-1) |
| `CV-LINT-INVOKE-CYCLE` | J, W | An invoke cycle without an attempt counter (CV-C38, retired to W) |
| `CV-LINT-NO-SELF-SEND` | A | No `interp.send()`/`send_threadsafe` inside `bindings/` (CV-C16, CV-C25) |
| `CV-LINT-SELF-RECEIPT` | A | No `await send(..., wait=True)` on the machine's own interpreter from any action, entry or exit (CV-C51, CV-C64′) |
| `CV-LINT-CORO` | A | Actions and services are `async def`, registered directly (CV-C67). Services yield at least once (CV-C32, CV-C44) |
| `CV-LINT-REMINT` | A | `re_mint` is called only through `cv_re_mint`, with payload keys only (CV-C68) |
| `CV-LINT-PRIORITY` | A | No `priority=True` (CV-C42) |
| `CV-LINT-SYSTEM-EVENT` | A | No `system=True` and no `is_system_event` (CV-C19) |
| `CV-LINT-RESTORE` | A | `from_snapshot(` appears only in persistence, always with `minimum_version=3` and `plugins=` (CV-C52, R13-W1) |
| `CV-LINT-DRAIN` | A | `drain_pending()` is called only in `persistence.persist` (CV-C65′) |
| `CV-LINT-ERROREVENT` | A | `onError` actions use `isinstance(event, ErrorEvent)` and `event.error` (CV-C21) |
| `CV-LINT-INSPECTOR` | A | No `LoggingInspector` in production (CV-C28′) |
| `CV-LINT-HOTPATH` | A | No import of `candleviewer.statechart` from any hot-path module in §3 (MUSTNOT-01..03) |

MUST-09 applies: the linter ships before the first machine JSON merges.

### 1.7 `tests/xstate_contract/`: a BLOCKING CI gate

- **Membership.** The suite discovers every file in `machines/` automatically. A machine without a contract module fails collection.
- **Matrix.** The gate runs every machine on **both service spellings** (`def` returning a coroutine, and `async def`) on the async engine. A separate *informational* job runs the sync engine for parity only. It never gates and never ships.
- **Per machine:**
  - every transition in §Bn.3;
  - every §Bn.7 invariant;
  - a **snapshot round-trip at every quiescence point**: persist → restore gives the identical configuration, context and scheduled sends, and the journal replays exactly once;
  - a restore with the wrong `machine_hash`, a bad HMAC or `version < 3` is refused loudly;
  - guard-denied and unhandled events are audited and never brick the machine;
  - a chain-trip latch survives restore.
- **Runner.** Runs with `-W error::RuntimeWarning` (CV-C67). The suite must finish in under 60 s. A per-machine throughput budget is checked against the BENCH-1 and BENCH-6 baselines. (E50-T06: `tools/statechart/suite_budget.py` enforces the 60 s wall budget and a per-machine cases/s floor in the `xstate-contract` job from the JUnit report; the BENCH-1 idle re-run status is in `docs/research/xstate/bench1-idle-rerun-p3-g4.md`.)
- **Nightly.**
  - `docs/research/xstate/gate/run_gate.py` runs against the **pinned** 0.9.1 wheel (hash-verified). A second run against the latest upstream release is informational and feeds the liaison chore.
  - `docs/research/xstate/bench/bench_c_timers_v2.py` (BENCH-6) also runs nightly. It gates on target hardware (P3-G6).
  - The report is published to `artifacts/xstate-gate/<date>.md`.
  - **Implementation (E50-T04, E50-C17).** `.github/workflows/xstate-nightly.yml`: job `pinned` (gating; `run_gate.py --with-bench` + BENCH-6 on the `CV_TARGET_HW_RUNNER` runner; `contents: read` only), job `notify` (`issues: write` only: on a red or failed `pinned` run it comments on the one E50-C17 tracker issue, repo variable `CV_XSTATE_TRACKER_ISSUE`, instead of filing an issue each night) and job `upstream` (informational, `continue-on-error`). `tools/statechart/nightly_gate.py` turns the gate JSON into the report and the verdict: a regression is a blocking check failing that is not in the committed `result-v0.9.1.json` baseline, not a `KNOWN_DELTAS` entry (one excused status per row, each with a written justification; `bench:BENCH-2` only at or above its 380.9 ev/s floor) and not the superseded `bench:BENCH-6` row (judged once, from the BENCH-6 step). The verdict is also red when BENCH-6 p99 > 100 ms at 500 busy machines (or is missing), or when a check that passed in the baseline is skipped for environment reasons (lost coverage).
- **Event-name coverage (E50-T05, MUST-10).** CI job `event-coverage` runs `tools/statechart/event_coverage.py`: it AST-scans every `Gateway.send` / `send_threadsafe` call site under `services/api/candleviewer` and fails, naming `file:line`, when a literal event name (string, `{"type": ...}` or `Event(...)`) is not declared in the target machine's descriptor, or the literal machine key matches no machine. The machine is resolved from the literal key, or from the `kind=` the key expression was `register`-ed under; wrapper functions that forward an event parameter into a send (e.g. `SessionChart.record`) are followed so their literal call sites are checked against that machine. Non-literal events are not statically checkable and are skipped. The check also runs inside the `xstate-contract` job (`-W error::RuntimeWarning`).
- **Implementation (E50-T31).** CI job `xstate-contract` (`.github/workflows/_job-xstate-contract.yml`, in `ci-required`) runs `pytest tests/xstate_contract -m "not sync_parity" -W error::RuntimeWarning`; the per-arm and per-quiescence-point cases are generated from the chart JSON (`_harness.py`), each `test_bNN_<id>.py` pins the §Bn.7 ledger to this catalogue (`deferred:E<nn>` where an invariant depends on binding bodies), and `xstate-sync-parity` is the informational sync job. `xstate-contract-nightly.yml` runs the same job nightly for the 5-green exit criterion.


---

## 2. Constraint table: CV-C01 … CV-C69

The source of truth is 79-r14 §7, read together with the per-round retire/stand tables it carries forward (r6–r13 verdicts, ADR-0016 Amendments 1–14).

- **F** = enforced by `factory.py`
- **P** = enforced by `persistence.py`
- **G** = enforced by `gateway.py`
- **R** = enforced by `registry.py`
- **L** = enforced by lint (§1.6)
- **CT** = enforced by the contract test (§1.7)
- **PL** = enforced by a plugin

| ID | Status | Rule (short) / why retired | Enforcement |
|---|---|---|---|
| CV-C01 | STANDS | Mandatory policy block, applied only through the single factory | F, L `CV-LINT-POLICY` |
| CV-C02 | STANDS | Outward effects (exchange I/O) happen only from committed-state `entry`, or last in the action list. `sendTo` is not withdrawn on rollback | L, CT |
| CV-C03 | STANDS | Async `Interpreter` only (owner choice, MUSTNOT-06). This holds even though CV-C46 retired | F assert, L `CV-LINT-IMPORT` |
| CV-C04 | STANDS | Dynamic (callable) `raise` targets are validated against the machine's event set | R, CT |
| CV-C05 | STANDS (narrowed) | No reliance on child output, and no BLOCK overflow policy. The root-target clause retired (#147) | L |
| CV-C06 | STANDS | A `wait=True` receipt with `changed=False, error=None` is never a gate on a `defer` chart | G, CT |
| CV-C07 | STANDS | Restore-side invoke reconciliation. Nothing is snapshotted with an in-flight `ErrorEvent` | P, CT |
| CV-C08 | STANDS | Snapshots are JSON strings, only via `statechart.persistence` | L `CV-LINT-RESTORE` |
| CV-C09 | STANDS | Plugins filter the init event and dedupe `on_transition_failed` | PL |
| CV-C10 | STANDS | Clock injected: `SimulatedClock` in tests, `ReplayClock` in replay | F |
| CV-C11 | STANDS | Read `last_transition_ok` immediately, or not at all | P, G |
| CV-C12 → **C12′** | STANDS (relaxed) | `after:` for coarse timeouts with ≥250 ms tolerance only. Hard deadlines and algo timing stay on `MonotonicScheduler`. BENCH-6 must be ≤100 ms p99 on target hardware | L `CV-LINT-TIMER`, nightly BENCH-6 (P3-G6) |
| CV-C13 | STANDS | BENCH-1 (rollback overhead) below 3.0×. The order lane runs on a dedicated loop and never shares one with the platform lane | F lane table, nightly bench |
| CV-C14 | STANDS (ban only) | Cross-thread `send` idiom banned (`WrongThreadError`). The validation clause retired | G, L |
| CV-C15 | STANDS (narrowed) | Event-name discipline. The case-insensitivity clause retired | R, CT (MUST-10 gate) |
| CV-C16 | STANDS | No action sends on its own interpreter; self-events use `raise` | L `CV-LINT-NO-SELF-SEND` |
| CV-C17 | STANDS (folded into C62) | No reliance on a `raise` chain deeper than `maxIterations`; the depth is asserted in a test | L, CT |
| CV-C18 | STANDS | A fresh `MachineLogic` per `create_machine()`, with one spelling per implementation | F, bindings loader |
| CV-C19 | STANDS | Never construct `system=True` events, and never trust `is_system_event()` | L |
| CV-C20 | STANDS (via C65′) | Persistence owns the mailbox across the snapshot boundary | P |
| CV-C21 | STANDS | `onError` uses `isinstance(ErrorEvent)` + `event.error` | L |
| CV-C22 | STANDS (to verify) | No `-W error::DeprecationWarning` against library code until the contract suite shows zero library deprecations on 0.9.1. After that it retires, which E50-T31 checks | CT job flag |
| CV-C23 | STANDS | Snapshots only at quiescence, through the persistence wrapper. Envelope carries version, `machine_hash` and HMAC | P |
| CV-C24 | RETIRED | "Never trust `Receipt.deferred` alone": fixed upstream (#170) | none |
| CV-C25 | STANDS (lint) | No external `send()` from inside an action; the gateway queue only. The runtime guard retired | L |
| CV-C26 | RETIRED | Superseded in round 5 by library fixes | none |
| CV-C27 → **C27′** | STANDS (residual) | Assert `set(state_ids) ⊆ set(configuration)` before `start()` | P |
| CV-C28 → **C28′** | STANDS | No `LoggingInspector` in production. The `_timer_handles` gauge is kept as telemetry | L, PL metrics |
| CV-C29 | RETIRED | Root-target lint redundant: `RootTargetError` is non-downgradable (#147) | none |
| CV-C30 | RETIRED | "No parallel regions on the order path": #142/#143 share one legality predicate | none |
| CV-C31 (′, ″) | RETIRED | `fail`/`rollback` combination bans. #193/#204 fixed the unwind on both engines | none |
| CV-C32 | STANDS (new ground) | Invoke-bearing states with an escape transition use services that yield (R10-D2) | L `CV-LINT-CORO` |
| CV-C33 | STANDS | Gateway-only `send_threadsafe`, applying the self-send classification | G |
| CV-C34 | RETIRED | Contract defects OC-01..OC-10 fixed in the catalogue | none |
| CV-C35 | STANDS | No `always` into an invoked child, and no `always` to an ancestor | L |
| CV-C36 | STANDS | Every `send_threadsafe` future is read, and refusals are counted and paged | G, PL |
| CV-C37 | RETIRED | `children_ready()` barrier (#171) | none |
| CV-C38 | RETIRED → W | The engine bounds invoke cycles itself (#179). Lint warning only | L (W) |
| CV-C39 | RETIRED | Superseded by CV-C56 | none |
| CV-C40 | STANDS | No snapshot before the machine is observed settled after `start()` | P |
| CV-C41 | STANDS | Snapshots capture the root only; children report upward via `sendTo` | P |
| CV-C42 | STANDS | No `priority=True` anywhere, from any origin | G, L |
| CV-C43 | RETIRED | Out-of-process progress counter. Its ground (R8-01) is fixed; in-process `chain_trips` is observable | none (liveness via PL) |
| CV-C44 | STANDS | Child bring-up bounded per child; entry actions on invoked children are coroutines that yield | F, L |
| CV-C45 → **C45″** | STANDS | Read `last_error` right after `from_snapshot`. The stripping clause retired (#214) | P |
| CV-C46 | RETIRED | "Order path never on SyncInterpreter" as a safety rule (#204). Async-only is kept by CV-C03/MUSTNOT-06 | (C03) |
| CV-C47 | RETIRED | `raise(delay=)` ban (#212, #218) | none |
| CV-C48 | RETIRED | 0.8.0-era snapshot fence (#214 v2 upcast). Superseded by `minimum_version=3` | none |
| CV-C49 → **C49′** | STANDS | Snapshot only at quiescence, and never re-persist an un-`start()`ed interpreter | P |
| CV-C50 | STANDS | `on_invocation_stranded` + `on_event_dropped("chain_budget")` sampled; health sweep asserts no dormant invocations | PL errors |
| CV-C51 | STANDS | No entry/exit action awaits a receipt on its own interpreter (the library also refuses) | L |
| CV-C52 | STANDS (hygiene) | `minimum_version=3` at every restore site | L, P |
| CV-C53 | STANDS | The snapshot journal is HMAC'd at rest over chart bytes + blob. **The load-bearing security control** | P, CT |
| CV-C54 | STANDS | Restore reconciles persisted vs admitted record counts | P |
| CV-C55 | STANDS | No delay below 10 ms | L |
| CV-C56 | STANDS | `start()` is wrapped in `wait_for(CV_START_TIMEOUT)`, and a timeout is a hard failure | F |
| CV-C57 | STANDS | Own recursive key check, including inline `invoke.src` (Q-5) | R |
| CV-C58 | STANDS | Compaction and migration jobs `start()` before re-persisting | P, L |
| CV-C59 | STANDS | Never poll `last_error` for chain health | PL |
| CV-C60 | STANDS | Read `last_error`/`last_transition_ok` before `start()` on restore | P |
| CV-C61 | RETIRED | Retired with CV-C47. The gauge survives as telemetry | none |
| CV-C62 | STANDS | Size `maxIterations` against the descent plateau (`limit+3`) | L |
| CV-C63 | STANDS (narrowed) | Read `chain_trips > 0`; v3 snapshots carry the latch natively | PL, P |
| CV-C64 → **C64′** | STANDS (lint) | No reentrant in-step self-receipt await. Spawning workers is legal | L |
| CV-C65 → **C65′** | STANDS (relaxed) | Shutdown order is `drain_pending()`, then journal, then `get_persisted_snapshot()`, then `stop()`. Check `Receipt.error` and dedupe re-submits | P, L `CV-LINT-DRAIN`, CT |
| CV-C66 → **C66′** | STANDS (relaxed) | Bring-up happens in the factory. `on_interpreter_start` is telemetry only | F, CT |
| CV-C67 | STANDS | Coroutine actions registered directly; `-W error::RuntimeWarning` | F, L, CT |
| **CV-C68** | NEW | `re_mint` takes payload overrides only, through `cv_re_mint`. Retires when upstream closes R14-01 | G, L |
| **CV-C69** | NEW | Supervise with `dropped_receipts`/`on_receipt_dropped`; the hook is thread-safe and loop-free | PL |

**Count:** 14 constraints are fully retired: C24, C26, C29, C30, C31, C34, C37, C38 (down to a warning), C39, C43, C46, C47, C48 and C61. Seven more have a clause retired and continue as primes or in narrowed form: C05, C12′, C14, C15, C25, C27′ and C45″. C68 and C69 are new. Everything else stands.


---

## 3. Hot-path exclusion list: never statecharts

These components are plain Python (or TypeScript) with no interpreter in the loop, now and after adoption. MUSTNOT-01..03 apply, and `CV-LINT-HOTPATH` blocks any `candleviewer.statechart` import from these modules. When one of them needs lifecycle state, it reads a plain `bool` or enum that a machine publishes on state entry.

| Component | Module / owner | Why it is excluded | Its statechart neighbour, if any |
|---|---|---|---|
| Order-book engine (snapshot + delta apply, depth tiers, tick aggregation) | M9 book engine, E08-S05, E21-T01 | ~1–10 k msg/s per symbol; BENCH-2 is 381 ev/s | B14 book *health* FSM (resync/stale only) |
| Bar builders (time, tick, volume, range, renko) | E12 | per-trade work | none |
| Footprint, CVD and delta aggregation | E18, E23-T01 | per-trade work | none |
| Heatmap and liquidity columns | E21-T02, E21-T04 | per-delta work | none |
| Big-trade clustering | E22-T01 | per-trade work | none |
| Per-tick rule evaluation, trigger pre-filter (≥99 % rejection, MUST-05), metric reads | E35-S02, E35-S03 evaluator | BENCH-2 381 vs 2,000 ev/s. **Permanent** | B9 rule *instance* lifecycle (armed/firing/cooldown/disarmed) |
| Alert condition evaluation | E40-T03 evaluator core | per-tick | B10 alert lifecycle (armed/triggered/snoozed) |
| Per-UID rate-limit governor and fan-out admission control | E34-T02 | MUSTNOT-02 | B2/B3 fan-out lifecycle |
| Paper matcher queue / fill / fee arithmetic | E38-S03 matcher core | per-tick | B15 paper-account liquidation FSM |
| Algo timing: TWAP intervals, chase repricing, iceberg release | `MonotonicScheduler`, E33-T01 | hard deadlines; CV-C12′ | B4–B7 algo lifecycles (the scheduler sends coarse events in) |
| WS server fan-out, coalescing, throttling | E17-T03 | per-message | none (the client session is not a catalogue machine) |
| Topic bus | E08-T03 | per-message | none |
| Recorder `StreamWriter` batching | E16-T03 | per-message | B11 recording session |
| Replay injector and pacing | E26-T03 | per-message; uses `ReplayClock` | B12 replay session |

---

## 4. Ticket change-list

The next phases execute this section against `docs/plan/backlog/E*.json`, using the house rules:

- JSON is edited with Python (`ensure_ascii=False`, `indent=2`).
- **RETIRE** means: `labels += ["retired"]`, `sprint = "Backlog"`, `estimate = 0`, and the body starts with `> **RETIRED 2026-09-24: <reason>**`. The key is kept so `blocked_by` still resolves, and every live `blocked_by` pointing at a retired key is re-pointed as the tables below specify.
- **RE-SCOPE** means the `## Context` section starts with `> **Re-scoped 2026-09-24 for full xstate-statemachine adoption (ADR-0016 Accepted):** …`, and Scope, Technical notes, Test plan and DoD are all updated.
- Then run `validate.py --fix` to re-level.

### 4a. RETIRE list

**E50: shim, dual runtime, gate and decision (9)**

| Key | Old est. / sprint | Reason |
|---|---|---|
| E50-K01 | 3 / S02 | There is no in-house shim to size. The owner decided on full adoption |
| E50-T07 | 8 / S04 | In-house interpreter shim. Withdrawn (ADR-0016 Part 2 withdrawn) |
| E50-T03 | 8 / S05 | Dual-runtime harness. There is only one runtime; E50-T31 is the contract gate |
| E50-T26 | 3 / Backlog | Shim retirement ladder. There is no shim |
| E50-T32 | 5 / Backlog | Phase-1 shim retirement. There is no shim; B10–B20 are built on the library from day one |
| E50-T33 | 5 / Backlog | Phase-2 shim retirement. The B16/B18 Blockers are fixed in the corrected JSON (E50-T42/T43) |
| E50-T34 | 8 / Backlog | Phase-3 order-path shim retirement. Built directly on the library, and P3-G1 moves to E50-T31 |
| E50-X01 | 3 / S09 | Go/no-go review. Decided: row 8, ADOPT (79-r14 §6) |
| E50-T08 | 2 / S10 | Fold the decision into ADR-0016, the catalogue and the architecture. Done by this plan (§5.3) |

**E50: upstream-tracking chores, all closed upstream at v0.9.1 (13) and M-1 (1)**

| Key | Closed by |
|---|---|
| E50-C03 | Action-raise commits: `actionErrorPolicy` + rollback (cec108b → 0.9.1) |
| E50-C04 | `always` self-target deadlock: fixed 0.8.0 |
| E50-C05 | Silent discard of unhandled events: `onUnhandled` + hooks |
| E50-C06 | Failed-action state persisted: fixed 0.8.0 |
| E50-C07 | `sendTo` by invoke id / `systemId`: fixed 0.8.0 |
| E50-C08 | Restore restarting invokes and timers: fixed (#214 v3) |
| E50-C09 | Timer starvation: BENCH-6 p99 55–92 ms at 0.9.1. It is now governed by CV-C12′ and nightly BENCH-6, not a tracking chore |
| E50-C10 | Unknown/relative targets: `strictTargets` + `RootTargetError` |
| E50-C11 | Raising guard swallowed: `guardErrorPolicy` |
| E50-C12 | Error-observability hooks: `CvErrorHooks` surface exists (#222, #244) |
| E50-C13 | `send(wait=True)` hang: fixed |
| E50-C14 | Sync macrostep budget (N-3): sync engine not used in production (MUSTNOT-06); fixed upstream |
| E50-C15 | N-4 / #79: fixed at 0.9.x |
| E50-C16 | M-1 receipt-gate hold. #170 fixed `Receipt.deferred`/`denied` (CV-C24 retired); CV-C06 stands in the gateway |

The single residual, R14-01, and every future release go to the **one recurring liaison chore, E50-C17** (§4b).

**E50: per-constraint tickets folded into the consolidated adoption modules (36).** These tickets implemented one CV constraint each against a shim or a wrapper-on-shim. Some of them are now absorbed by one of the four modules (factory, persistence, gateway, lint). The rest are moot because their constraint retired.

| Key | Old est. / sprint | Disposition |
|---|---|---|
| E50-T09 | 2 / S10 | A3 deferral scaffolding strip: done in the corrected JSON (CV-C34 retired) |
| E50-T19 | 2 / Backlog | Already dead (CV-C37); this formalises the retirement |
| E50-T12 | 1 / S08 | CV-C27′ assertion → **E50-T49** (restore) |
| E50-T13 | 2 / S11 | CV-C05 lint → **E50-T11** (lint set) |
| E50-T17 | 3 / S08 | CV-C35 lint → **E50-T11** |
| E50-T18 | 2 / Backlog | CV-C36 future-read → **E50-T15** (gateway) |
| E50-T20 | 2 / Backlog | Bounded `start()` (CV-C56) → **E50-T59** (factory) |
| E50-T21 | 3 / Backlog | Invoke-cycle W lint → **E50-T11** |
| E50-T22 | 3 / Backlog | Settle gate + root-only (C40/C41) → **E50-T10** (persistence) |
| E50-T23 | 2 / Backlog | `priority=True` ban (C42) → **E50-T15** + T11 |
| E50-T24 | 2 / Backlog | Gate-harness round-8 fixtures → **E50-T04** (nightly `run_gate.py`) |
| E50-T25 | 5 / Backlog | "Migrate non-order machines to the library": there is nothing to migrate, because every machine is born on the library |
| E50-T27 | 1 / Backlog | Out-of-process progress supervisor: CV-C43 retired |
| E50-T28 | 3 / Backlog | Per-child bring-up bound (C44) → **E50-T59** + T11 |
| E50-T29 | 2 / S10 | Restore strip Done/AfterEvent: CV-C45 stripping clause retired (#214) |
| E50-T30 | 3 / Backlog | CV-C46 retired; async-only (C03) → **E50-T59** assert + T11 `CV-LINT-IMPORT` |
| E50-T35 | 3 / Backlog | HMAC envelope → **E50-T49** |
| E50-T36 | 2 / Backlog | QueueOverflowError accounting → **E50-T15** |
| E50-T37 | 3 / Backlog | CV-C48 retired |
| E50-T38 | 3 / Backlog | CV-C47 retired; the C49′ half → **E50-T10** |
| E50-T39 | 2 / Backlog | Chain-trip observability (C50/C63) → **E50-T60** (plugins) |
| E50-T40 | 3 / Backlog | Kill-on-ancestor + `reenter` lints → **E50-T11** |
| E50-T41 | 3 / Backlog | Gate-harness round 10 → **E50-T04** |
| E50-T42 | 2 / Backlog | C-04 B16 hoist → **E50-T43** (all four round-14 chart fixes) |
| E50-T44 | 3 / Backlog | Recursive key validator (C57) → **E50-T01** (registry) |
| E50-T45 | 1 / S10 | C47/C61 retired; the `_timer_handles` gauge → **E50-T60** |
| E50-T46 | 3 / Backlog | C51 lint → T11; C56 → **E50-T59** |
| E50-T47 | 3 / Backlog | C49′/C58 → **E50-T10** |
| E50-T48 | 3 / Backlog | C59 → T60; C60/C54 → **E50-T49** |
| E50-T50 | 1 / Backlog | "Delete workaround tests": they were never written on the adopted path |
| E50-T51 | 3 / Backlog | Measurement debt → **E50-T06** (BENCH-1 idle re-run, P3-G4) + T04 (BENCH-6) |
| E50-T52 | 5 / Backlog | K11 "deadlines into charts" decided by CV-C12′ (coarse only) |
| E50-T53 | 2 / S10 | C62 sizing + R11-W lints → **E50-T11** |
| E50-T54 | 2 / S10 | C63: v3 carries `chain_trips` natively; the read → **E50-T49**/T60 |
| E50-T55 | 2 / S10 | C64′ lint → **E50-T11** |
| E50-T58 | 2 / S10 | C65′ drain journal → **E50-T10**; C69 → **E50-T60** |

**Outside E50.** A full scan of `E01–E49` for *shim / in-house interpreter / dual-runtime / hand-rolled state machine* found **no genuine hit**. Eleven matches are false positives, and none is retired:
- *Motion shim* or *DPI shim*: E05-D03, E05-S02, E11-Q07, E11-S10, E15-D14, E29-D04, E47-S04, E49-D04.
- *Fault-injection shim*: E45-K01, E45-T09.
- *Hand-rolled state pattern*, which here means UI empty/loading states: E49-S05.

The only hand-rolled state machine in the backlog is **E29-T03**'s `frozenset` transition table. It is **re-scoped** (§4c), not retired, because the order lifecycle is still needed.

**Retire total: 59 tickets, all in E50. 149 pts leave the plan, 58 of them from sprinted tickets.**

**`blocked_by` re-pointing.** Any live ticket blocked by a retired key is re-pointed to its disposition target in the tables above. If there is no target, the blocker is re-pointed as follows:
- `E50-T07` → `E50-T59`
- `E50-T03` → `E50-T31`
- `E50-X01` → `E50-T57`
- `E50-K01` → `E50-T01`

### 4b. E50 KEEP / RE-SCOPE / NEW

The epic is renamed **"Statechart runtime: xstate-statemachine 0.9.1 adoption (factory, persistence, gateway, contracts)"** and runs from **S02 to S08** (R0–R1). Order matters: MUST-09 requires the pin and the lint to land first, then the registry and factory, then persistence and plugins, then the charts and gateway, then the gate.

| Key | Action | Title (new) | Old → new est. | Sprint | Blocked by |
|---|---|---|---|---|---|
| E50-T57 | KEEP (re-sprint) | Adopt `xstate-statemachine==0.9.1`: dependency pin with hash lock + PEP 740 attestation verify in CI | 2 → 2 | S10 → **S02** | E02-T02 |
| E50-T11 | RE-SCOPE (consolidate T11/T13/T17/T21/T40/T53/T55 + §1.6) | `tools/lint_statecharts.py`: the full standing CV lint set, JSON + AST, CI-blocking | 1 → **5** | S11 → **S02** | E50-T57 |
| E50-T01 | RE-SCOPE | Machine-JSON registry: schema/target validation, recursive key walk (CV-C57), Stately export | 5 → 5 | S03 | E50-T11, E03-T02 |
| **E50-T59** | **NEW** | Statechart factory + mandatory config block (`factory.py`, `config.py`, lane table, bounded `start()`, bring-up, async-only assert) | – → **5** | **S03** | E50-T57, E50-T01 |
| E50-T02 | RE-SCOPE | `machine_hash` lock in CI, snapshot envelope version ≥3, upcaster registry with golden-snapshot rule | 5 → **3** | S04 | E50-T01 |
| E50-T10 | RE-SCOPE ("factory snapshot wrapper" → **"Persistence module: quiescent persist + drain journal"**) | `persistence.persist`: settle gate (C40), root-only (C41), `drain_pending()`→journal→`get_persisted_snapshot()`→`stop()` (C65′), never re-persist un-started (C49′/C58) | 3 → **5** | S11 → **S04** | E50-T59, E50-T02 |
| E50-T49 | RE-SCOPE | Persistence restore + HMAC envelope: `from_snapshot(plugins=, minimum_version=3, expected_machine_hash=)`, C53 HMAC, C27′/C45″/C54/C60 checks, `chain_trips` latch | 3 → **5** | Backlog → **S04** | E50-T10 |
| **E50-T60** | **NEW** | `CvErrorHooks` / `CvMetricsPlugin` / `CvAuditPlugin` (C09, C36, C50, C59, C63, C69; `cv_machine_*` families; write-ahead `machine_events`) | – → **5** | **S04** | E50-T59, E04-T03, E09-T02 |
| E50-S01 | RE-SCOPE | Commit B1–B9 `machine.json` + `bindings/` stubs from the corrected v0.9.1 contracts; hashes locked | 5 → 5 | S03 → **S05** | E50-T01, E50-T02 |
| E50-S02 | RE-SCOPE | Commit B10–B20 `machine.json` + `bindings/` stubs; hashes locked | 5 → 5 | S04 → **S05** | E50-T01, E50-T02 |
| E50-T14 | RE-SCOPE | Verify OC-01..OC-10 fixes are present in committed JSON (regression tests only) | 3 → **1** | S05 | E50-S01 |
| E50-T16 | RE-SCOPE | Verify mandatory-config round-6 keys on all 20 charts (policy lint fixtures) | 3 → **1** | S05 | E50-S02, E50-T11 |
| E50-T43 | RE-SCOPE (absorbs T42) | Land the round-14 four our-side fixes: B16 C-04 hoist, B18 C-07b fall-through, B11 R14-03, B8 attempt counter B610-OC-CD03 (P3-G1) | 3 → 3 | S10 → **S05** | E50-S01, E50-S02 |
| E50-T15 | RE-SCOPE (absorbs T18/T23/T36) | `gateway.py`: `send`/`send_threadsafe` (C33), futures read + refusals paged (C36), no `priority` (C42), receipt rule (C06), order-lane RAISE→503 | 3 → **5** | S08 → **S05** | E50-T59, E50-T60 |
| E50-T56 | KEEP | CV-C68 payload-only `cv_re_mint` wrapper + `CV-LINT-REMINT` (R14-01 containment) | 2 → 2 | S10 → **S05** | E50-T15, E50-T11 |
| E50-T31 | RE-SCOPE | `tests/xstate_contract/` BLOCKING gate: all 20 machines, both spellings, snapshot round-trip at every quiescence point, `-W error::RuntimeWarning`, sync-engine parity job (informational); retires CV-C22 when zero library deprecations | 5 → **8** | Backlog → **S06** | E50-S01, E50-S02, E50-T49, E50-T15 |
| E50-T05 | KEEP | Event-name coverage gate (MUST-10) | 3 → 3 | S10 → **S06** | E50-T15, E50-T31 |
| E50-T06 | RE-SCOPE (absorbs T51) | Contract suite <60 s budget gate + throughput budget; BENCH-1 idle re-run (P3-G4) | 3 → 3 | S10 → **S06** | E50-T31 |
| E50-Q01 | KEEP (QA pool) | Invariant and chaos suite over every §Bn.7 invariant | 5 → 5 | S07 | E50-T31 |
| E50-T04 | RE-SCOPE (absorbs T24/T41) | Nightly `run_gate.py` against the **pinned** 0.9.1 wheel + latest-upstream informational run + nightly BENCH-6 (`bench_c_timers_v2.py`) gating on target hardware (P3-G6); published report | 5 → **3** | S09 → **S07** | E50-T57, E50-T31 |
| E50-C01 | KEEP | Contribute the conformance suite upstream | 3 → 3 | S10 → **S08** | E50-T31 |
| E50-C02 | KEEP | Contribute the benchmark harness upstream | 2 → 2 | S10 → **S08** | E50-T06 |
| **E50-C17** | **NEW** (recurring chore) | Upstream liaison: track #26 meta + R14-01; re-verify (T04 nightly + T31) on every library release; propose pin bumps via ADR-0016 amendment | – → **1** | **S08** (recurs each release) | E50-T04 |

**E50 after the change: 23 live tickets.** That is 20 kept or re-scoped, plus 3 new: T59, T60 and C17. They carry **85 pts**: 80 engineering pts plus 5 on the QA pool (Q01). Per-sprint engineering load is S02 7, S03 10, S04 18, S05 22, S06 14, S07 3 and S08 6. Before the change the epic had 79 live tickets and 218 pts.

### 4c. RE-SCOPE across other epics: the lifecycle implementers

Every ticket below gets the same four-part edit. `<Bn>`, `<id>` and `<file>` are filled in from the table.

- **Scope** adds these bullets:
  - "Implement the `<Bn>` lifecycle as `statechart/machines/<file>` (committed by E50-S01/S02, hash-locked). Do not hand-write the state enum or transition table."
  - "Build it only through `statechart.factory.build('<id>', lane=…)`, and restore it only through `statechart.persistence.restore`."
  - "Write guards, actions and services in `statechart/bindings/<bnn>_<id>.py` as a `MachineLogic`. Everything is `async def`, and services are idempotent under re-entry."
  - "Add `tests/xstate_contract/test_<bnn>_<id>.py`, which becomes a member of the blocking gate."
  - "All sends go through `statechart.gateway`."
- **Technical notes** adds: "Normative contract: `28-statechart-catalogue.md` §`<Bn>`.1–.8. Mandatory config: 29-statechart-adoption-plan §1.2 (79-r14 §7 FINAL block). Hot-path parts listed in 29 §3 stay plain code."
- **Test plan** adds three parts:
  - pure-API unit tests of the binding module with a `SimulatedClock`;
  - contract-suite membership, covering both spellings and every §Bn.7 invariant;
  - a snapshot round-trip (persist→restore) at every quiescence point the ticket introduces, plus a refused restore on a hash or HMAC mismatch.
- **DoD** adds: "`machine_hash` committed in `machine_hashes.lock`; `tools/lint_statecharts.py` green; `tests/xstate_contract` green; no import of `xstate_statemachine` outside `statechart/`."
- **`blocked_by`** adds `E50-T59` (factory) and the E50 story that commits the chart: `E50-S01` for B1–B9, `E50-S02` for B10–B20. Tickets that persist machines also add `E50-T49`.

**Estimate deltas** use one rule. The saving comes from replacing hand-rolled state code (an enum, a transition table, illegal-transition handling, timer bookkeeping, and snapshot/rehydrate code) with JSON plus bindings. Tickets whose bulk is exchange I/O, persistence or UI keep their estimate.

| Key | Bn / machine | Title (short) | Old → new | Δ | Why |
|---|---|---|---|---|---|
| E29-T03 | B1 `order` | Canonical order state machine with write-ahead events | 5 → **3** | −2 | The `frozenset` transition table, `IllegalTransition` and S6 terminal immutability become the chart plus `strict`. S1–S9 bindings, `apply_execution` and the write-ahead `CvAuditPlugin` wiring stay |
| E29-T04 | B1 | Submission pipeline | 3 → 3 | 0 | Transport and rounding. It sends via the gateway only |
| E29-T05 | B1 | Private WS as source of truth | 3 → 3 | 0 | Maps pushes to events; `(ts_exec, seq)` ordering stays in bindings (MUSTNOT-04) |
| E29-T06 | B1/B19 | Reconciliation loop | 3 → 3 | 0 | It feeds B19 events; the logic is I/O |
| E29-T08 | B1 | Stuck/unknown-order detection | 2 → **1** | −1 | The detection is the chart's coarse `after:` (≥250 ms tolerant) plus `cv_machine_*` metrics from T60 |
| E32-T01 | B8 `position_protection` | Native-SL invariant at the OMS choke point | 5 → **3** | −2 | The protection region becomes a chart with the B610-OC-CD03 attempt counter; the choke-point guard stays |
| E32-T02 | B8 | Unprotected-position watchdog | 2 → **1** | −1 | The watchdog is a chart state plus a coarse `after:` |
| E32-S01 | B8/B1 | Bracket as first-class object | 5 → **3** | −2 | The bracket child lifecycle rides B1 and B8 charts; partial-fill sizing stays |
| E34-T01 | B2 `trade_group` / B3 `leg` | Trade-group persistence + lifecycle derivation | 5 → **3** | −2 | "Lifecycle derivation" is the B2 chart, and legs are invoked B3 children (root-only snapshot, C41) |
| E34-S02 | B2/B3 | Execute fan-out | 5 → 5 | 0 | Admission control stays in the governor (MUSTNOT-02). No change |
| E34-S03 | B2/B3 | Compensating unwind | 5 → **3** | −2 | The restartable unwind comes from `actionErrorPolicy:"rollback"` plus chart states. Services stay idempotent under re-entry |
| E33-T01 | B4–B7 | AlgoSupervisor: state store, scheduler, resume, adoption | 5 → **3** | −2 | The state store and resume come from persistence restore. `MonotonicScheduler` (hard timing) stays in plain code |
| E33-S01 | B4 `oco` | Emulate OCO | 5 → **3** | −2 | The race and settle logic is chart-defined |
| E33-S02 | B5 `iceberg` | Emulate iceberg | 5 → **3** | −2 | The tranche lifecycle is in the chart; the release timing is the scheduler |
| E33-S03 | B6 `twap` | Emulate TWAP | 5 → **3** | −2 | Same as S02, with the interval timing on the scheduler |
| E33-S04 | B7 `chase` | Emulate chase | 5 → **3** | −2 | The anti-runaway bounds become chart guards; repricing stays on the scheduler |
| E33-T02 | B4–B7 | Algo control API, WS projection, audit | 3 → **2** | −1 | The audit events come from `CvAuditPlugin`; the WS projection is `machines.algo.state` (§4d) |
| E35-S01 | B9 `rule_instance` | Store, version, mode-switch rules | 3 → **2** | −1 | The mode switch (armed/simulate/disarmed) is the B9 chart |
| E35-S06 | B9 | Firing log + rule state on WS | 2 → 2 | 0 | Unchanged. Rule state is taken from the machine's published enum |
| E35-S02 | (excluded) | Deterministic evaluator | 5 → 5 | 0 | **Not a statechart** (§3). Recorded only to confirm the exclusion; Technical notes adds "per-tick evaluation is plain code (BENCH-2)" |
| E40-T03 | B10 `alert` | Alert evaluator with gating and storm suppression | 2 → 2 | 0 | Evaluation stays plain code; the gating and snooze lifecycle is B10. It nets to zero |
| E16-T02 | B11 `recording` | RecordingPolicy: auto-record triggers, grace period | 5 → **3** | −2 | The grace period and trigger lifecycle are B11 states with a coarse `after:` |
| E16-T04 | B11 | Recording sessions, gap detection | 3 → **2** | −1 | The session lifecycle becomes the chart; gap detection stays |
| E26-T01 | B12 `replay` | replay_sessions migration + session lifecycle service | 2 → 2 | 0 | The migration dominates; the lifecycle service becomes a factory call. `ReplayClock` is injected |
| E08-T04 | B13 `ws_conn` | Public WS ingestion skeleton: ConnectionManager, reconnect | 5 → **3** | −2 | The reconnect, backoff and resubscribe lifecycle is B13. Frame handling stays in plain code |
| E08-S05 | B14 `book` | Order-book reconstruction | 5 → 5 | 0 | The book engine is **excluded** (§3). Only resync/stale health moves to B14, which is net zero |
| E38-S03 | B15 `paper_account` | Paper matcher | 5 → 5 | 0 | The matcher is excluded; the liquidation FSM moves to B15, which is net zero |
| E09-S03 | B16 `session` | Session lifetime, idle lock, sign-out everywhere | 5 → **3** | −2 | Idle and absolute timeouts are coarse `after:`. Revocation events sit on the root (C-04) |
| E09-S04 | B16 | Step-up re-auth, TOTP reset | 3 → **2** | −1 | The step-up sub-state is in the chart |
| E44-T04 | B17 `live_gate` | live_trading gate: evidence-bound flag + gate evaluation | 5 → **3** | −2 | The gate states come from the chart; evidence binding stays |
| E39-S03 | B18 `kill_switch` | Kill-switch engine | 5 → **3** | −2 | B18 carries the C-07b unguarded RELEASE fall-through; the control lane escalates through hooks and never bricks |
| E45-T01 | B19 `reconciliation` | Reconciliation core | 5 → 5 | 0 | The diff logic dominates. It runs as a B19-invoked service, so there is no change |
| E45-T02 | B19/B20 | Reconciliation triggers + stale-account lockout | 3 → **2** | −1 | The trigger and lockout lifecycle is B19 plus B20; `OPERATOR_RESOLVED` has an arm in every state (R12-15) |
| E39-S02 | B20 `risk_lockout` | Automatic lockout, day-boundary reset, step-up override | 3 → **2** | −1 | The lockout, reset and override lifecycle is B20 |

**RE-SCOPE totals outside E50: 34 tickets across 14 epics.** 23 of them get an estimate reduction and 11 keep their estimate, getting only the text edits and the `blocked_by` additions. **Net −38 engineering pts.**

E13, E17, E23 and E42 have no re-scoped ticket, because none of them implements a catalogue machine. E13 is the indicator epic; connection and ingestion supervision is entirely B13, which lives in E08. E17, E23 and E42 receive new tickets instead (§4d).

### 4d. NEW tickets outside E50

| Key | Epic | Kind | Title | Est. | Sprint | Blocked by |
|---|---|---|---|---|---|---|
| **E17-T08** | E17 WS gateway | Task | `machines.{entity}.state` WS topic: publish the statechart state/enum on entry, snapshot+delta, per-entity RBAC (no interpreter query on the hot path, MUSTNOT-03) | 3 | S06 | E17-S02, E17-S03, E50-T60 |
| **E23-T06** | E23 CVD/delta | Chore | Assert exclusion: CvdEngine and delta aggregation stay plain code, with a `CV-LINT-HOTPATH` fixture and a BENCH-2 note in the ADR-0017 draft | 1 | S11 | E50-T11, E23-T01 |
| **E42-T07** | E42 Admin | Task | Statechart inspector read API: list live machines by kind, current configuration, context summary, `chain_trips`, `dropped_receipts`, deferred depth, and the Stately-compatible JSON export per `machine_hash` | 3 | S16 | E50-T60, E50-T01, E42-T01 |
| **E42-S08** | E42 Admin | Story | Build the admin statechart inspector screen: machine list, state diagram from the Stately JSON, event timeline from `machine_events`, and a latch-acknowledge action with step-up and audit | 5 | S17 | E42-T07, E42-S01, E09-S04 |

The per-epic D/Q/X companions (a design task for E42-S08, QA for T07/S08) are not new keys. The existing E42-D*/Q* tickets absorb them, and each one gets a one-line Scope bullet.

**NEW total: 7 tickets.** Three are in E50 (T59, T60, C17) and four are elsewhere (E17-T08, E23-T06, E42-T07, E42-S08). They add 23 engineering pts: 11 in E50 and 12 in E17, E23 and E42. The E42-S08 story is FE-weighted.

---

## 5. Sprint and roadmap impact

### 5.1 E50 shrinks to R0–R1 (S02–S08)

| | Before | After |
|---|---|---|
| Live tickets | 79 | 23 |
| Engineering pts in sprints | 111 across S02–S11 | 80 across S02–S08 |
| Backlog pts parked in E50 | 107 | 0 |
| Last sprint | S11 (R2) | **S08 (R1)** |
| Retired | 0 | 59 tickets / 149 pts |

The epic `estimate` field becomes 85. The roadmap §3 epic register row becomes E50 / R0–R1 / 85, with R0 35 and R1 50.

### 5.2 Freed points and re-level rules

- **Freed engineering capacity:**
  - E50 in-sprint: 111 → 80 (−31). R2 gains the most: S09–S11 drop from 48 E50 pts to 0.
  - Re-scoped lifecycle tickets: −38 pts in S02–S21.
  - New tickets outside E50: +12 pts.
  - **Net: about −57 engineering pts across the plan.**
- **Re-level rules for `validate.py --fix`:**
  1. The E50 order is fixed by `blocked_by` (§4b). No E50 ticket may move later than S08, and the validator fails otherwise.
  2. The E50 overload in S04 and S05 (18 + 22 pts) is fine against the 90-pt capacity. It must not push R0 exit tickets out of S04. If S04 overflows, move **E50-T60**, never E50-T59 or T10/T49.
  3. Every re-scoped lifecycle ticket now requires `E50-T59` plus its chart story. All of them already sit at S03 or later: E08-T04 in S02 is the one exception, and it is re-sprinted to **S03**, with E08-S05 following to S04 if the validator requires it. That is the only forced move.
  4. Freed points are **not** back-filled by pulling tickets earlier. They lower the utilisation of the §13–16 overage sprints first: the R1/R2 accepted overages in `_reconciliation-report.md` §13–16 are re-computed, and every overage that clears is removed from the accepted list.
  5. S07 stays at 45 capacity. E50-T04 (3) and E50-Q01 (QA pool) are the only E50 work there.

### 5.3 Document changes that go with this plan (replacing E50-T08)

- **ADR-0016:** status becomes **Accepted**. Add *Amendment 15 (2026-09-24): full adoption*: Part 2 withdrawn, Part 3 satisfied, MUST-08 superseded by pin + hash + attestation, the E50 re-plan referenced to this doc.
- **`28-statechart-catalogue.md` §0/§1.3b:** the runtime is `xstate-statemachine==0.9.1` via `statechart.factory`. "Shim" wording is removed, and the §1.3b block is replaced by a pointer to 29 §1.2.
- **`20-architecture.md`:** a statechart package subsection (29 §1.1) and the lane table.
- **`24-internal-schemas.md`:** the snapshot envelope v3 (HMAC, `machine_hash`, `key_id`) and the drain journal table.
- **`30-release-roadmap.md` §3/§3.1.1:** the E50 row and the R0–R1 span.
- **`31-sprint-plan.md`:** regenerated from the backlog by `sync_sprint_plan.py`.
- **`18-traceability-matrix.md`:** re-point retired E50 keys to the T59/T60/T10/T49/T31 successors.
- **`AGENTS.md`:** one rule. Statecharts are built only through `candleviewer.statechart`, never hand-rolled.
