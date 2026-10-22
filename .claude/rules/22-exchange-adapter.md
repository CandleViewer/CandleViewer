---
description: Bybit v5 exchange-adapter rules (orderLinkId idempotency, native SL always, demo has no WS order entry, per-UID rate budget, recorded fixtures only in tests).
---

# Exchange adapter (Bybit v5)

Source: `CONSTITUTION.md` C-2.2, C-2.6, C-2.8, C-2.10, C-2.11, C-12.7, C-13.5; `docs/plan/20-architecture.md`
(environment table, P9); ADR-0006 (OMS), ADR-0008 (trade-group fan-out).

## Placement

- All Bybit knowledge (endpoints, signing, symbols, error codes, topics) lives in
  `services/api/exchange/bybit/` behind `exchange/base/` interfaces (C-2.2). Other modules consume
  normalised domain events only (C-2.3).
- Scope: USDT linear perpetuals. Do not add spot/options/inverse without an ADR.

## Order safety

- **Idempotency (C-2.10):** every outbound order carries a client-generated `orderLinkId`
  (deterministic from intent id + leg + attempt; max 36 chars, Bybit charset). Retries reuse the same id;
  a duplicate-id rejection is looked up and adopted only after the full match with the persisted row
  (`24-internal-schemas.md` §8.3 rule 3, §14.2 rule 2), never taken as "already accepted", and is never
  re-submitted under a new id.
- **Native SL always (C-2.6, C-4.14):** every position-opening order attaches an exchange-native stop-loss
  (`stopLoss` on create, or immediate `trading-stop`). If SL attachment fails, flatten or retry per policy;
  the position must never stay unprotected. No flag, config, or role can disable this.
- **No withdrawal (C-2.8):** never call, wrap, or expose any withdrawal/transfer endpoint. Key validation
  rejects keys with withdrawal permission. A Semgrep rule enforces this.
- **Audit (C-2.9):** submit / amend / cancel / fill / fan-out expansion each write an audit record
  (write-ahead, before the result is returned to the caller).
- Round to tick size / qty step / min notional from the instrument-info cache, using `Decimal`.
- Reconcile via REST (open orders, positions, executions) on startup and after any reconnect; the exchange is truth.

## Environments (C-2.11, P9)

- `live`, `demo`, `testnet` are separate credential sets, base URLs, storage namespaces and code paths.
  Host tables live only in the bybit adapter config (mirrored in `20-architecture.md`).
- **Demo has no WS order entry**: demo orders go via REST only; the WS-trade path must be unreachable for demo.
- Demo has no separate public feed; public market data uses the live public stream.
- A request built for one environment must never be signed with another environment's keys.

## Rate limits (C-12.7)

- Limits are **per UID**. The adapter owns a token-bucket budget per UID and per endpoint class,
  with a **reserve** for stop / cancel / SL paths that normal submits cannot consume.
- Fan-out spreads legs within each UID's budget; on `10006` / `10018` back off with jitter and emit a metric.
- `10002` (recv_window / clock drift) is surfaced distinctly and halts order entry until time sync recovers.

## WebSockets

- Public: snapshot + delta with sequence checks; gap / out-of-order / duplicate means resync from snapshot (C-2.5).
- Private (`order`, `execution.fast`, `position`, `wallet`): heartbeat watchdog; on drop, REST reconciliation.
  The private stream's contract (ping, watchdog, backoff, statuses, revoke) is 24 §14.2 rule 13.
- Ping per Bybit spec; reconnect with exponential backoff + jitter; bounded queues (C-2.18).

## Tests

- **Only recorded, redacted fixtures** from `packages/fixtures/bybit/` (C-13.5). No network egress to
  `*.bybit.com` / `*.bytick.com` in any test; the settings deny list and CI egress block enforce it.
- Signing tests use fixed test vectors, never real keys.
- Every handled error code has a fixture-driven test; chaos scenarios 2, 4-9 and 12 (C-13.6) exercise this module.
