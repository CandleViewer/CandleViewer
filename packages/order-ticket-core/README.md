# @candleviewer/order-ticket-core

The order-ticket core (E30-T01, #984): pure TypeScript shared by every ticket surface (SCR-060,
SCR-061, E31's click-trade, E33's algo builders), so a draft is built, checked and sized the same
way everywhere. No React, DOM, `fetch`, UI package, chart engine or app (ESLint purity rules in
`eslint.config.mjs`, `order-ticket-core-framework-free` in `.dependency-cruiser.js`); the only
workspace import is `@candleviewer/protocol`'s generated types (C-4.16).

It is defence in depth, never the only check: the server sizes every entry and enforces every
rule (C-2.12). The sizing mirror is **display-only** and says how exact it is (`exactness`,
`unmirrored[]`; BQ 1 and the orchestrator's agreement of 2026-11-04 07:18Z).

## Slices

| Slice | Holds                                                                                      |
| ----- | ------------------------------------------------------------------------------------------ |
| S1    | `model.ts` (draft and context types), `decimal.ts` (exact decimals), `instrument.ts` grids |
| S2a   | entry classification and `validate()`                                                      |
| S2b   | the copy-deck messages (`messages.ts`)                                                     |
| S3    | the `24` §9.3 sizing mirror and the shared golden vectors (parity, run in `unit-frontend`) |
| S4    | `buildRequest()`, `Idempotency-Key`, the arm header, acceptance, errors, metrics, perf     |

## Rules this package keeps

- **Exact arithmetic** (`decimal.ts`): every price and quantity is a `22` `Decimal` string parsed
  to a scaled `BigInt`; never a JS `number`.
- **Grids** (`instrument.ts`): quantities floor to the lot; a stop rounds away from entry and a
  take-profit toward it, as the server's sizer does (`24` §9.3.1, §9.3.3); minimums are checked
  quantity first, then notional (the profile's leg floor when it is higher).
- **Validation** (`validate.ts`): every failure in the ticket's field order, each with `22`'s
  `field` / `rule` / code and its message data; a check without its inputs, and every server
  rule not mirrored yet, is listed in `unmirrored`, never assumed to pass.
- **Plain data** (`model.ts`): a draft and its context are structured-clone safe, so a worker can
  host the reducer if E30-K01 places it there.
- **Fail closed**: an unknown position classes an order as an entry; an entry with no stop is
  refused (C-2.6); a missing optional filter is listed, never guessed.
