---
description: Statechart rules (xstate-statemachine 0.9.1 per ADR-0016) — factory-only construction, mandatory config block, hot-path exclusions, contract suite, machine_hash, pin.
---
# Statecharts

Source (normative): `docs/plan/28-statechart-catalogue.md` (B1–B20, §1.3b/§1.3c),
`docs/plan/29-statechart-adoption-plan.md`, `docs/plan/27-adrs/ADR-0016-statechart-runtime.md` (Accepted).

## Pin
- `xstate-statemachine==0.9.1`, exact pin with hash in the lockfile. Never bump, vendor, or shim it
  without an ADR-0016 amendment. No second runtime exists.

## Layout (`services/api/candleviewer/statechart/`)
- `factory.py` — the ONLY construction site (`build()`, `restore()`).
- `config.py` — `CV_INBOX_BOUND`, `CV_START_TIMEOUT`, `CV_EVENT_SCHEMAS`, lane table.
- `persistence.py` — quiescent snapshot, HMAC envelope, restore, drain journal.
- `gateway.py`, `registry.py`, `plugins/{errors,metrics,audit}.py`.
- `bindings/bNN_<name>.py` — guards, actions, services for one machine.
- `machines/BNN.<name>.machine.json` + committed `machine_hashes.lock`.

## Import rule (CV-LINT-IMPORT)
- Only `statechart/factory.py` and `statechart/persistence.py` import `xstate_statemachine`.
  A project hook blocks edits that add this import anywhere outside `statechart/`.
- `SyncInterpreter` is never used in production; only in `tests/xstate_contract/` for parity.

## Mandatory config (applied unconditionally by the factory; callers cannot opt out)
- `create_machine(chart, logic=..., strict_config=True)` and `"strictConfig": true` in the chart.
- `Interpreter(machine, strict=True, event_schemas=CV_EVENT_SCHEMAS, max_queue_size=CV_INBOX_BOUND,
  overflow_policy="refuse").use(CvErrorHooks())` (+ metrics, audit plugins).
- Chart root: `"onUnhandled": "defer"` plus an ordered unguarded audit arm where a guarded transition
  may be denied; `"maxIterations": 500`.
- Restore: `Interpreter.from_snapshot(machine, blob, minimum_version=3, plugins=[...])` (kwarg, not
  `.use()`), assert `last_transition_ok is not None` before `start()`, then `_cv_bring_up()`.
- Snapshot only at quiescence; never when context carries `_fault`; HMAC envelope binds `machine_hash` and the machine identity (29 §1.3).
- Shutdown: `drain_pending()` → journal → snapshot → `stop()`; journal replayed exactly once.
- Re-mint events with `cv_re_mint(ev, data=...)`; never forge `type=`/`src=`.
- Timers (`after:`, delayed raise) are coarse only: ≥10 ms, ≥250 ms tolerance.
- Actions are coroutine functions; no external `send()` inside actions.
- Supervise `chain_trips` and `dropped_receipts` (page / alert).
The full, authoritative block is §1.3c of the catalogue — re-read it; do not work from memory.

## Hot-path exclusions (never a statechart)
- Anything per-tick / per-message: order-book deltas, trade prints, bar/footprint aggregation, WS fan-out,
  render loop, chart engine. See catalogue §1.2 for the full out-of-scope list.

## Adding or changing a machine
1. Contract first: edit the B-entry in `28-statechart-catalogue.md` (states, events, guards, invariants).
2. `/statechart-new <B>` scaffolds JSON + bindings + contract test.
3. Update `machine_hashes.lock` (CI recomputes and diffs); any chart change changes the hash and
   invalidates old snapshots — include a snapshot migration note in the PR.
4. `tools/lint_statecharts.py` and `tests/xstate_contract/` (blocking gate) must pass.
5. Every invariant in B*.7 has a hypothesis/property test; every transition in B*.3 has a test.
