# ADR-0008 — Trade-group fan-out with a mandatory native exchange-side stop-loss

- Status: **decided**
- Date: 2026-09-14
- Deciders: Owner (decision #5), Architect, Backend lead, Security engineer
- Consulted: `docs/research/09-execution-risk-tools.md` §2, §6, §8, §10, `docs/research/06-bybit-api.md` §13, §18, `docs/research/24-owner-decisions.md` cross-cutting consequence #3
- Related: ADR-0006, ADR-0007, ADR-0009, `docs/plan/20-architecture.md` §3.5, §10.2

## Context and problem statement

One order ticket must execute across N selected accounts (main + sub-accounts), each with its own profile: leverage, sizing rule, SL/TP offsets, risk caps and allowed symbols. Bybit's rate limits are **per UID**, so a fan-out consumes N separate budgets, and Bybit provides no native OCO, iceberg or TWAP via the public API — those must be emulated app-side. Emulated protection only works while our process is alive and connected, which is the single largest correctness risk in the whole system.

## Decision drivers

- Owner requirement: one ticket → N accounts, each executed with its own profile, tracked as a trade group.
- Safety invariant from research: every fan-out order must carry a native exchange-side SL regardless of any rule-engine stop.
- Sub-account cap of 5 (20 with Business KYC) bounds N and must be surfaced in the Admin UI.
- Partial failure across legs is normal, not exceptional, and must be a first-class UI state.
- Protective orders must never lose a rate-limit race to entry orders.

## Considered options

1. **Server-side fan-out with a mandatory native SL per child order, an explicit trade-group aggregate, and a reserved protective rate-limit slice.**
2. **Client-side fan-out** — the browser issues N independent orders.
3. **Fan-out without a mandatory native SL**, relying on the rule engine and a watchdog.

## Decision outcome

**Chosen: option 1.**

Model:

```
TradeGroup { id, created_by, env, symbol, intent, state, created_at, closed_at }
   state: PENDING | PARTIAL | ACTIVE | CLOSING | CLOSED | FAILED
ChildOrder { order_link_id, group_id, account_id, profile_snapshot, qty, price,
             native_sl, native_tp?, state (ADR-0006), exchange_order_id?, legs[] }
```

_As built (2026-10-20, E28-T01 #905):_ the profile snapshot lives on the trade-group leg (`trade_group_legs.profile_snapshot`, `21-database-schema.md` §3.3.3), with the profile id and version it was sized from, not on each child order, which names its leg through `orders.trade_group_leg_id`. A group's states are the eight of `24-internal-schemas.md` §9.1 (`draft`, `submitting`, `partially_open`, `open`, `closing`, `closed`, `failed`, `cancelled`), not the six above.

Binding rules:

1. **Fan-out is server-side.** The client sends one intent; the backend resolves target accounts (after an RBAC scope check), applies each account's profile, sizes each leg, attaches the native SL, and submits. The client is never the orchestrator — a closed browser tab must not be able to leave a half-executed group.
2. **`NativeStopGuard` is unconditional.** No position-opening child order is submitted without `stopLoss` attached (or an immediately following `set_trading_stop`). If an exchange-side SL is not observed within `CV_NATIVE_SL_DEADLINE_MS` (default 3000 ms), the OMS retries once and then **closes the leg reduce-only** and raises a critical `NakedPositionAlert`. This is the P4 invariant and it is not user-configurable.
3. **Per-account profile is snapshotted onto the child order** at fan-out time, so a later profile edit never rewrites the history of an executed trade, and the journal can explain exactly why a leg was sized as it was.
4. **Rate budget is per UID with a reserved protective slice.** Each UID's budget is split into three token buckets — `critical` 40 % (protective/reduce-only/cancel/`set_trading_stop`), `entry` 40 % (new orders, fan-out children, amends), `poll` 20 % (reconciliation and reads). `entry` and `poll` may never borrow from `critical`; `critical` may borrow from both. Entry orders can therefore never starve an exit. Fan-out uses **pre-flight reservation across all target accounts** before sending anything, with a per-ticket `fanout_policy` of `atomic` (reject the whole ticket if any account is starved) or `best_effort` (send the admitted accounts, mark the starved ones `Deferred` with a deadline). Placement runs one task per account so a throttled account cannot head-of-line-block its siblings. The full algorithm, deadlines, partial-failure matrix and metrics are normative in `20-architecture.md` §4.3.
5. **Partial failure is explicit.** If some legs succeed and others fail, the group enters `PARTIAL`, the succeeded legs already carry native SLs, and the UI offers per-leg retry or a one-click rollback (reduce-only close of filled legs). The system never silently retries a leg that might have executed (ADR-0006 `Unknown` handling).
6. **Emulated algos are an enhancement layer above the native floor.** OCO (race two orders, cancel the loser on fill), iceberg (client-side slicing), TWAP (timed slices), chase (bounded cancel/replace), scaled ladders (equal/linear/geometric) and brackets all run in `AlgoSupervisor`. Each declares a crash policy: on restart, an algo either resumes from persisted state or cancels its working orders — never an undefined third thing.
7. **Disconnect policy is per account and opt-in**: if the private stream is down longer than `CV_KILLSWITCH_ON_DISCONNECT_S` (default 30 s) while a position is open, the watchdog may flatten. Even when this is off, the native SL remains the floor.
8. **Owner kill-switch (FREEZE)** operates per manager or globally: blocks new orders, optionally cancels working orders and flattens. It is enforced server-side in the `Validator`, before any adapter call.

### Consequences

Positive:

- Process death, network partition, power loss or a WSL sleep never leaves an unprotected position — the guarantee the entire risk story rests on.
- Group semantics give the UI, the journal and the risk dashboard one coherent object to display, aggregate and audit.
- Reserved protective budget removes a whole class of "couldn't place the stop because the entries used the quota" incidents.

Negative / risks:

- The mandatory SL means every strategy must express a stop level, even ones that would prefer a purely rule-managed exit. Accepted: a very wide native SL is permitted as a disaster floor, and the rule engine may tighten it freely.
- Attaching stops costs extra API calls where `stopLoss` cannot be attached inline. Budgeted in the per-UID accounting and measured in spike S4.
- N-account fan-out multiplies latency variance. Target: all legs submitted within 1.5 s for 5 accounts (spike S4 gate).

### Why not the alternatives

- **Client-side fan-out**: trivially broken by a closed tab, a sleeping laptop or a slow network; also impossible to enforce RBAC and risk caps server-side (violates principle P8).
- **No mandatory native SL**: makes every protection dependent on our own uptime, which directly contradicts the research's single most emphatic risk finding.

## Validation

- Spike S4: 3–5 sub-account fan-out on demo — all legs < 1.5 s, no 10018 under the designed budget, every leg observed with an exchange-side SL.
- Chaos test: kill the process immediately after the first leg's ack; assert on restart that reconciliation finds the leg, that its native SL exists, and that the group state is `PARTIAL`.
- Security test: a Manager attempting to fan out to an account outside their scope receives 403 and an audit entry, with no adapter call made.

## Amendment 1 (2026-10-21, E28-T02 #906; contract rulings of main-orchestrator on #906, issuecomment-6327140077)

Refines binding rule 3 and the _As built_ note above; reverses neither. The REST profile (`22-api-openapi.yaml`) is a
view of the stored profile that rule 3 snapshots, and two things hold of it:

1. **The profile body carries exactly its stored columns.** Every member of `AccountProfileInput`, at any depth, maps to
   a writable column of `account_profiles` (`21-database-schema.md` §3.2.4) and every writable column to a member;
   enums and defaults are the column's, bounds the column's or tighter, and any other member is refused (C-6.3). Gone,
   having no column: `trailing_stop`, `default_tpsl_mode`, `sizing.round_to_lot` and `max_notional_usd`, the offset's
   `atr_bar_type` and `atr_param`, the caps' `max_consecutive_losses` and `lockout_minutes_after_breach`, `is_active`.
2. **`AccountProfile` is the envelope** `{id, exchange_account_id, version, created_at, updated_at, profile: AccountProfileInput}`:
   `id` and `version` are what a snapshot cites, and `profile` is the body `updateAccountProfile` takes back unchanged.

This breaks the `/v1` contract (C-6.3) before any route serves it: all five operations are `not_mounted` and no client
reads these types, so no `/v2` is cut. The commit's `!` and `BREAKING CHANGE` footer record it (C-6.4).
