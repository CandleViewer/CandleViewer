# ADR-0048 — Emulated-algo crash seam, scheduler and adoption (E33-K01)

- Status: **proposed (gated)** (2026-11-04). Nothing in this record binds until the owner approves it (pending, #2701). Once it is approved, Decisions 1 to 4 and the requirement rows bind E33-T01 (#993), and the parts that rest on venue behaviour stay gated on the demo leg (`docs/plan/spikes/E33-K01.md` §10, waiting for E29-K01 #843): read-after-create for the orphan lookup, the `10018` hold while many runs resume, and the demo round trip. E33-T03 (#1107) finalises the record.
- Date: 2026-11-04
- Deciders: Owner (`@basiltt`) and Architect, on #2701; the main-orchestrator's BQ ruling on #991 (comment 6631215534) and its rulings of 2026-11-04 on the requirement rows. The Security engineer through E33-X03 (#1109) and E33-T03's consequences review.
- Consulted: `docs/security/threat-models/E33-emulated-algos.md` (O-2, AS-T05, AS-D03, SR-E33-10, SR-E33-14, SR-E33-22, F-11, CX-13, CX-17); `28-statechart-catalogue.md` §B6 and §B7; ADR-0006; ADR-0016.
- Numbering note: E33-K01 names ADR-0016 (the statechart runtime, accepted) and E33-T03 names ADR-0030 (taken); CX-17 asks for a free number, and the orchestrator assigned 0048. Nothing here cites ADR-0031 as a record in force: the kill hooks' promotion needs the fence ADR-0031 reserves for E45-K01 (#1252, open).
- Related: #991 (E33-K01), #993 (E33-T01), #1103 (E33-S03), #1104 (E33-S04), #1107 (E33-T03), #1098 (E33-Q03), #1099 (E33-Q04), #914 (E29-T06), #843 (E29-K01); ADR-0006, ADR-0008, ADR-0016. Finding: [`docs/plan/spikes/E33-K01.md`](../spikes/E33-K01.md), with [`E33-K01-results.json`](../spikes/E33-K01-results.json).
- Evidence: the spikes ran on `main` at `f79d6fa37`; every `file:line` holds on `main` at `aa0a02b8c`. Every figure is M (local) and printed from the results file; the D figures wait for #843.

## Context and problem statement

24 §10.1 rule (1) says "every algo persists its state transactionally with each child submission, so a restart resumes exactly where it stopped", and the OCO story asks for completion "within 5 seconds of process start" (US-ALGO-002). RSK-017 carries the duplication and orphan risk of a restart, and the threat model's F-11 (High, before E33-T01 merges) says nothing reconciles before a resumed run's first child and B7 resumes with no reconcile. Nothing had been measured.

29 §4c's E33-T01 row says "the state store and resume come from persistence restore". But `statechart/persistence.py` "Owns the shutdown path of every catalogue machine": it drains, journals, seals and then stops the interpreter, so a SIGKILL leaves no snapshot of the process it kills. A restore is static as well: it re-runs no entry action, restarts no invoke and re-arms no deadline (`docs/research/xstate/10-fit-analysis.md` §C3.3). E33-K01 measured where the seam sits, how the schedule survives, what binds an orphan and how long a resume takes.

## Decision drivers

- C-2.10: a deterministic `orderLinkId`, reused on every retry; ADR-0006 rule 2: no blind resubmission.
- C-2.6: every position-opening child carries a native stop; C-2.9: every order action is audited.
- C-2.18: bounded queues; C-2.20 and C-2.21: hot paths are never statecharts, and synchronous code enforces.
- C-2.22 item 8: hard deadlines and algo timing stay on the external `MonotonicScheduler`.
- 28 §1.3 A7: Postgres is authoritative, and every transition is written ahead.
- INV-B6-b and INV-B6-e; SR-E33-10, SR-E33-14 and SR-E33-22; 24 §8.3 rules 2 to 6.

## Considered options

- **Seam:** (a) intent-first, the slice row with its id committed before the send; (b) an outbox relay.
- **Recovery:** (a) hydration from the rows, as B1 recovers; (b) restoring the sealed snapshot; (c) skipping the snapshot.
- **Scheduler:** V1, polling a due index; V2, one task per run (the B19 idiom); V3, one heap (the `ws/pacing.py` idiom); each due time anchored to `loop.time()` (mode A) or read from exchange time at every wake (mode B).
- **Orphans:** binding by the id alone, or by the whole id plus the full match.

## Decision outcome

### Decision 1 — The seam is intent-first

The `algo_slices` row, with its allocated `order_link_id` and its terms, is committed before the child is sent. The child then rides the real `OrderSubmission` (24 §8.4) through a server-side entry (row 4 below), so B1's rows follow it, and the slice joins its order by the whole id. No cross-module transaction is needed: a slice id with no `orders` row was never sent, because a send needs B1's `validated` row first (24 §8.4 step 5). Under SIGKILL at seven kill points, K4u and the `cancel_pending`, `amend_pending` and `partially_filled` states (`held` is E5c, n = 10), no child was duplicated or lost (finding §3: 0 duplicated and 0 lost over 340 killed trials, k of n per cell). The outbox relay is not pursued by the pre-agreed rule; the rule's latency half is unmet, which the finding (§1) puts to the owner.

### Decision 2 — Recovery is hydration from the rows, one procedure

After a SIGKILL and after a graceful stop alike, B4 to B7 are rebuilt from their rows: a fresh `factory.build(<kind>, lane="order")`, a `rebuild` and `replay_plan` pair of their own (B1's `oms/recovery.py` is B1-specific), deadlines re-armed from the rows, unanswered invokes re-driven idempotently, and the fold of a run's slices and their children equal to its run row. The rows are the recovery truth (A7). The sealed snapshot stays a shutdown artefact: it never seeds a resumed run, and where one exists it must agree with the rows, which win. B4 to B7 keep the catalogue's shutdown persist under requirement row 7; "B4 to B7 skip the snapshot" would make them the first catalogue machines without it, so E33-T01 takes that option only by amending this record. B6 runs only through `factory.build`, with no chart edit beyond the change routed on #993. Measured in process (finding §4.1): a graceful restore of 100 runs with an invoke in flight re-drove 0 invokes, and hydration re-drove 100.

This departs from 29 §4c's E33-T01 row, which this PR amends (C-16.5). §4c's generic bullet ("restore it only through `statechart.persistence.restore`") still governs any snapshot restore. The restart rules for a half-placed child, by its B1 state, are the finding's §4 table: a new id is never minted for a child not proven absent, and the allocator's collision check sees ids that only a slice row holds.

### Decision 3 — One `MonotonicScheduler`: the pacing heap, due time read per wake

V3 in mode B: one task and one heap entry per run, keyed by `next_action_at`, the key of `ix_algo_runs_due`, so the heap is rebuilt from one read at boot and stays a cache of Postgres. Due time comes from `ClockGuard`'s exchange time read at every wake, `check_host_step()` first; `loop.time()` only sizes the next sleep. Mode B is chosen for clock robustness: in the clock-step shapes a fixed monotonic anchor (mode A) stops a TWAP after a host suspend, while mode B re-plans once per run. This departs from SR-E33-22's mechanism clause ("the monotonic clock within the process, as `MonotonicScheduler` and B6's `slice_deadlines_us` do") while meeting its outcome, a wall step that neither extends a run nor bunches its slices (finding §6.5 and §9.2); E33-T03 (#1107) carries the wording amendment, as BQ-12 did for SR-E33-10. A missed slice is re-planned over the remaining window, never fired back to back (SR-E33-22, INV-B6-b). The heap is bounded by the admitted-runs cap (SR-E33-09); a run has one due event outstanding; a gateway refusal is re-armed with backoff and counted. E33-T01 reuses B19's task conventions (owned tasks through `observability.spawn`, a tracked set, cancel and gather at stop, sends inside `asyncio.timeout`, an injected clock) and not its clock convention, its missed-tick policy or one task per run (finding §6.7), so it is not a second host-timer implementation. Staggering many due children belongs to the rate governor, not the scheduler.

Measured (finding §6): alone, V3's interval error p95 is 0.4 ms (mode A); loaded, every variant misses INV-B6-e's 100 ms (V3 432.0 ms, mode A), because of the order lane's full collections, not the scheduler: with them attributed away V3 sits at 18.6 ms (mode A), and with one shared machine node at 5.7 ms (mode A). The one loaded mode-B row (V3, n = 1) gave interval error p95 483.2 ms and lateness p95 253.4 ms, and 25.0 ms on slices no collection touched; mode B's case rests on the clock-step shapes, where mode A cascades. A factory-built B1 holds 1146 GC-tracked objects, and loop lag p99 under the loaded run is 143.3 ms (V3, mode A) against 20 §4.1 rule 5's 50 ms. That term is routed to its owners (E50 and E29 on CV-C18, E33-S03, E33-T03, E33-Q03); the 100-versus-250 ms bar is one owner-text amendment for E33-S03 and E33-T03.

### Decision 4 — Orphans bind only by the whole id plus the full match

A venue order binds to a run's child only by its whole `order_link_id` plus the SR-E29-03 full match against the slice row persisted before the send; never by prefix and never by the id alone, which "is not an ownership proof" (24 §8.3 rule 2). A run is found by its slice row's whole id, never by decoding `group22`. A venue-only orphan stays an unmanaged `untracked` row (24 §19.61; SR-E29-12), and adoption into a run waits for D7 (#2701). An `untracked` row under a slice's id pauses the run; it is never bound and never a reason to mint a new id. In the four orphan cases (finding §7), 0 of 40 trials bound anything.

### Requirement rows

E33-T01 owns each row unless the row names another owner. The finding's §9.3 carries the same rows.

| #   | Requirement                                                                                                                             | Owner                                                                   |
| --- | --------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| 1   | the resume of an `algo_child` consults the run's state and the creator's authority before any re-send                                   | E33-T01                                                                 |
| 2   | slice rows take the same guard as the tables they drive, and hydration checks a slice row against its run                               | E33-T01                                                                 |
| 3   | a held child id is re-planned under a fresh `seq2` once proven not ours, with the pause reason recorded                                 | E33-T01, in the allocator's own reconciliation, not a TWAP special case |
| 4   | the origin field is settable only in code, never from a request, the stop rule unchanged                                                | E33-T01; the interface comment on #993                                  |
| 5   | an algo's own cancel-and-replace rides a non-reserve lane; only protective cancels (stops, flatten, the kill switch) draw the reserve   | E33-T01; C-12.7                                                         |
| 6   | the lockout's trigger for an id under the account's own `OUR_ID` prefix is reconciled against the slice rows before it freezes entry    | E33-T01                                                                 |
| 7   | B4–B7's shutdown stops or drains invokes before persisting, or skips the snapshot; a restore never resumes a state whose invoke is lost | 28 §B4 to §B7; E33-T01                                                  |

## Consequences

- **Good:** no duplicated or lost child at any measured seam; one recovery procedure for every restart, as B1 already has; a scheduler built from two shipped idioms; orphans that never bind on guesswork.
- **Costs:** B4 to B7 need their own `rebuild` and `replay_plan`; the slice row is one more write ahead of each child; B6 and B7 need one contract-first chart change (finding §9.1) with a hash and version bump.
- **Open:** from `ready`, the resume misses 2 s at 100 runs (p95 10.60 s on five UIDs), bound by per-account serialisation, hydration and the first reconciliation pass rather than the rate budget, and from process start it misses 5 s on the measured host; the order lane's full collections exceed INV-B6-e and 20 §4.1 rule 5 whatever the scheduler; the supervisor needs a per-account first-pass signal from #914.
- **Security:** SR-E33-10's equivalent clause for a run rebuilt from rows is proposed to E33-T03 (finding §9.2) and decided with this record. The kill hooks stay off `main`: promoting them for E33-Q04 needs the fence ADR-0031 reserves for E45-K01 (#1252, open) and E33-X02's test that they are inert outside test builds. The audit writer was a double in the spike, so no C-2.9 coverage is claimed for children.
- **Gated:** the demo leg (#843) confirms or amends the venue-side parts; E33-T03 finalises the record.

## Why not the alternatives

- **The outbox relay:** not pursued by the pre-agreed rule. A relay would also have to hand each slice attempt to the same pipeline once and never re-send on its own backoff (ADR-0006 rule 2; `21-database-schema.md` §3.10.4's generic backoff would be a blind resubmission), and an `order.submit` relay would be a third outbox idiom, needing an ADR and the dispatcher's lease idiom (BQ-7).
- **Restoring the snapshot:** static, so it leaves a run in `submitting_slice` with nothing driving it, and a SIGKILL leaves no snapshot at all.
- **V1, polling:** its lateness spreads over the poll period by construction, and V1-250 and V1-1000 miss 100 ms even alone (192.0 and 805.1 ms).
- **V2, one task per run:** no way to move a sleeping run's due time earlier, a task per run, and awaited sends that cut dispatch to 1274 per second against V3's 15744 (both mode A); B19's skipped tick contradicts INV-B6-b.
- **Mode A, a fixed monotonic anchor:** after a 15 s suspend it fired 0 slices and re-planned 70 times, where mode B fired 203–207 with one re-plan per run.
- **Binding by the id alone:** the id is not an ownership proof (24 §8.3 rule 2), and with no rows there are no terms to match.

## Validation

- E33-T01: the acceptance criterion "Resume after a hard kill", SR-E33-10's tests in the threat model, and the requirement rows above.
- E33-Q04 (#1099): the crash matrix on every merge is the proof of the seam; zero of 30 here bounds a per-trial duplicate rate only at about 10 %.
- E33-Q03 (#1098): scheduler fidelity and the resume budget as baselines.
- The demo addendum to the finding, after #843, which completes #991.
