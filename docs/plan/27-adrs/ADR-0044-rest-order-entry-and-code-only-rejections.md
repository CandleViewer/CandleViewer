# ADR-0044 — REST order entry in every environment in v1, and the exchange's reject text code-only (E29-T09)

- Status: **accepted (interim)**: decided 2026-11-03 by main-orchestrator under the owner's delegation (#1778), in its
  ruling of record on #1029 (BQ-2, [comment 6603185027](https://github.com/CandleViewer/CandleViewer/issues/1029#issuecomment-6603185027)),
  and binding now. The ratification still due is the owner's, on #2701, where the owner may veto it. **Supersedes**
  `ADR-0006-oms-state-machine.md` binding rule 5 and the last clause of its rule 6, and nothing else: ADR-0006 stays
  `decided` for every other rule and carries Amendments 1 and 2.
- Date: 2026-11-03
- Deciders: Owner (`@basiltt`) through main-orchestrator (the delegation on #1778, owner veto on #2701; ruling of
  record on #1029); the Architect and the Security engineer as CODEOWNERS of `docs/plan/` and `docs/security/`.
  Author: virtarix-worker-3 for main-orchestrator.
- Consulted: `docs/plan/04-security-program.md` SR-040a (W9, W10, KV14); `docs/security/threat-models/E29-oms.md` O-9,
  F-18, OM-T10, OM-D07, OM-I05, OM-I06, SR-E29-08, SR-E29-09, §12.3 notes 2 and 10; `24-internal-schemas.md` §8.6, §14.2;
  `20-architecture.md` §9; `21-database-schema.md` §3.3.5; the #913 rulings (R8) and the plan-doc follow-ups #3863
  handed to E29-T09 (#1029, [comment 6301697653](https://github.com/CandleViewer/CandleViewer/issues/1029#issuecomment-6301697653)).
- Numbering note: 0041 is #5474's (the backup engine) and 0042 and 0043 are E42-T06's (#1085), none yet on `main`, so
  this record takes 0044.
- Related: ADR-0006 (rules 5 and 6 superseded here), ADR-0008 (the native-SL invariant is untouched), E29-T04 (#913),
  E29-K01 (#843), E29-Q03 (#977), E44-X01 (#1249), E38-T01 (#1006).
- Evidence: every `file:line` holds on `main` at `b81479ab0`. Module paths are under `services/api/candleviewer/`, test
  paths under `services/api/tests/`.

## Context and problem statement

Two binding rules of ADR-0006 (2026-09-14) did not survive the security review of the contract or the build of the order
path. The decisions are small; they are recorded here because each changes an outcome, so ADR-0006's own amendment
mechanism (a refinement) does not fit (`27-adrs/README.md`, "Writing a new ADR", 3).

**Rule 5** chose the transport from a capability: `supports_ws_order_entry` picks WS trade on live and REST on demo.
SR-040a (`04-security-program.md`) names WS Trade on live an optional optimisation only and bars dual dispatch (W9), and
`04`'s KV14 reads v1 order entry as REST-only; the E29 threat model recorded the disagreement with rule 5 as open input
O-9 and finding F-18, and asked E29-T09 to settle the plan text (§12.3 note 10). The build settled it first: E29-T04 (#913) routes every order over REST
(`oms/routing.py`: `Transport = Literal["rest"]`, and `TradingRouter.transport_for` answers `rest` for every
environment it serves), and no code in the OMS opens a trade socket. The module's docstring cites a sentence of
`20-architecture.md` §9 rule 7 that did not exist until this change.

**Rule 6**'s last clause carried "business rejections ... the exchange message verbatim to the UI". Bybit's `retMsg`
can repeat the order's money values and, on a signature error, echo the signed string, API key included
(`21-database-schema.md` §3.3.5). SR-E29-09 therefore withholds the text from every order and position route: a `502`
is `OrderExchangeProblem`, whose `exchange` member holds the return code only (`22-api-openapi.yaml`), and the text is
stored redacted and served only by the audited diagnostics read. #3863's plan-doc follow-up 2 recorded that this
contradicts rule 6 as written.

## Decision drivers

- One transport per environment and no dual dispatch (SR-040a, W9): two paths for one order are two ways to place it
  twice, and demo (REST only) could never exercise the live one.
- A trade socket is a third `auth`-frame carrier with frame-level ambiguity (an ack by `reqId` after a reconnect, a
  frame with no ack) and a per-IP connection budget shared with market data: the E29 threat model rates it Medium
  until O-9 is answered (F-18, OM-T10, OM-D07), and nothing in v1 builds it.
- E29-K01 excludes WS order entry (unavailable on demo), so no measurement of ours could confirm a live trade socket.
- An exchange message is untrusted text that can carry secrets and order values (SR-E29-08, SR-E29-09, C-12.6); the user
  still needs to know why an order was refused, and CandleViewer's own taxonomy (`24-internal-schemas.md` §8.6) says it.

## Considered options

Transport: (1) **REST in every environment in v1; a WS trade path later, under its own ADR.** (2) WS trade on live, REST
on demo (ADR-0006 rule 5). (3) Both on live, with a fallback from one to the other.

Rejection text: (1) **Code-only to every client; stored redacted; the detail through audited diagnostics.** (2) Verbatim
to the UI (ADR-0006 rule 6). (3) The redacted text to every `orders:read` holder.

## Decision outcome

**Decision 1: order entry is REST in every environment in v1; supersedes ADR-0006 rule 5.** `transport_for` answers
`rest` for `demo` and `live` and refuses an environment no port is wired for (`EnvironmentMismatch`); the unit test
`test_the_transport_is_rest_for_every_routed_environment` pins it. `ExchangeCapabilities.supports_ws_order_entry` stays,
as data about the venue (True on live, False on demo: `exchange/bybit/capabilities.py`); no OMS code reads it to choose
a transport, and `20-architecture.md` §9 rule 7 says so. The WS trade path (`wss://.../v5/trade`) is post-v1 and not
built: its code path stays absent, not gated off, so demo cannot reach it and no flag can enable it. Building it takes
a new ADR that carries SR-040a's gate, an ack pairing by `reqId`, a lookup before any resend (SR-E29-15, 24 §8.6) and
the per-IP connection budget; E44-X01 and E38-T01 are the tickets the E29 model names for it.

**Decision 2: the exchange's reject text is code-only to every client and stored redacted; supersedes the last clause of
ADR-0006 rule 6.** A business rejection reaches the caller as CandleViewer's own code and text with the exchange's
return code (`OrderExchangeProblem`; the `rejected_reason` of an order item is the row's `reject_code`, a code and never
the exchange's text: `oms/ws_topics.py`, `22-api-openapi.yaml` `Order`). The exchange's `retMsg` reaches no order,
position or WS answer. It is stored only after `redact_exchange_text(..., message=True)` (`orders.reject_message` and
`order_events.ret_msg`: `storage/repositories/orders.py`, `orders_sqlalchemy.py`) and served only by
`getOrderDiagnostics`, the Owner's alone (decision D7), which records every read before it answers. The rest of rule 6
stands: `ClockDriftError` (10002) blocks order entry and raises a distinct alert; `RateLimitError` (10018) feeds the
token bucket and rejects submits with `RATE_BUDGET_EXCEEDED`.

### Consequences

Positive:

- One order path to test, reconcile and threat-model in v1; the demo path is the live path with other hosts and keys.
- No trade-socket threats to carry: the F8b rows of the E29 model describe a path that does not exist.
- No exchange text, and so no key or order value an exchange echoes, reaches a client; the stored copy is redacted
  before it is bound.

Negative / risks:

- Live order entry has no WS figure: the live "order click to ack" budget in `20-architecture.md` §13.2 assumed one.
  E29-K01 (#843) and E29-Q03 (#977) own the measured REST numbers and the renegotiation of budget #4
  (`06-performance-and-load-standard.md` §5.2); live itself is measured only in R4 (E44).
- A refusal's exact exchange wording is one audited read away for the Owner, and absent for a Manager or a Viewer: the
  CandleViewer text and the return code are what they have.

### Why not the alternatives

- **WS trade on live (ADR-0006 rule 5)**: the live path would differ from the one demo can exercise, its ack pairing and
  connection budget are open findings (F-18), and it buys latency no measurement shows we need.
- **Both on live**: dual dispatch is what SR-040a forbids.
- **Verbatim text**, or the redacted text to every `orders:read` holder: the redactor is the last control and leaves a
  residual (SR-E29-08), so no client should hold the text unaudited.

## Validation

- `services/api/tests/unit/oms/test_routing.py` (`test_the_transport_is_rest_for_every_routed_environment`): REST for
  `demo` and `live`, and an environment with no port refused.
- `services/api/tests/unit/storage/test_orders_store.py`: `reject_code` and `reject_message` pass the redactor, the
  message rule included. `services/api/tests/contract/test_place_order_contract.py` validates the real `502` of a
  rejected create against `OrderExchangeProblem`, and `services/api/tests/unit/api/test_order_problems.py` shows that
  schema refusing any other `exchange` member.
- Not validated: the REST latency of live order entry (E29-K01, E29-Q03).

## Reversal path

A WS trade path reopens decision 1 through a new ADR that supersedes it, not an amendment. Showing the exchange's text to
a client reopens decision 2 through a new ADR and a security review: SR-E29-09 is a security requirement.
