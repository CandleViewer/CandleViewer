# ADR-0040 — Per-trade profile overrides and profile-change propagation to open tickets (E28-K01)

- Status: **proposed** (2026-10-25). The recommended decision and its evidence are below. The owner's and the
  Architect's sign-off of the decision table and of the items under "Owner sign-off items" is tracked on #2701;
  E28-K01 (#968) is Done only after it, while this record and its prototype merge without it (the orchestrator's note
  1 on #968). Until the sign-off, E28-S05 (#1144) may build against this record but must not ship a route that serves
  an override.
- Date: 2026-10-25
- Deciders: Owner (`@basiltt`) and Architect, on #2701; the Security engineer through the `security-review` label
  (C-10.2) and E28-X01's model. Author: hpe-worker-2 for main-orchestrator.
- Consulted: `docs/security/threat-models/E28-profiles-trade-groups.md` (PF-T03, PF-T04, PF-T05, PF-T06, PF-T15,
  PF-T20; SR-E28-03, SR-E28-04, SR-E28-15; §11.1 F-01, F-02, F-26); ADR-0008 Amendment 3; the #906 hand-off of
  `ProfilesChanged` (#968 comment 6356205285).
- Numbering note: the ticket names ADR-0016, which is the statechart runtime (F-26, #2623). ADR-0039 is the last
  record on `main` and 0031 is reserved by E45-K01, so this record takes 0040. `docs/design/E42/E42-D03.md` CG-1
  expected the E42-T06 ADR (#1085) to take "the next free number ADR-0040"; that ADR is not written, so it takes the
  next free number after this one. The coordinator confirmed this on 2026-10-25 (00:41Z): ADR-0040 stands, and #1085
  (E42-T06) takes the next free number when it is written.
- Related: #968 (E28-K01), #906 (E28-T02), #1144 (E28-S05), #971 (E28-S01), #2635 (F-01), #1110 (E34-S02), E30;
  ADR-0008, ADR-0005. Finding: `docs/plan/spikes/E28-K01.md`. Prototype (throwaway):
  `spikes/e28-override-propagation/`.
- Evidence: every `file:line` holds on `main` at `28ae3f1db`. Module paths are under `services/api/candleviewer/`;
  `yaml:n` is a line of `docs/plan/22-api-openapi.yaml`.

## Context and problem statement

US-PROF-008 lets a trader override profile fields for one trade, under three invariants: an override never widens a
hard risk cap, it resets to the profile default for the next ticket, and it is audited and journal-tagged
(`11-user-stories.md` US-PROF-008). It leaves open which fields an override may touch and what an open ticket does
when its profile changes underneath it.

The contract has since moved: `createTradeGroup` resolves each leg as **later narrows** — the leg's account's bound
profile (its default) is the ceiling, request `defaults`, the leg's `overrides` and an alternate
`overrides.profile_id` only narrow it, judged on the resulting leg after the sizer and its clamps run again, and a
widening request is refused whole with `403 risk_limit_breached` (yaml:6292-6314; ADR-0008 Amendment 3 rule 1). The
override members are `profile_id`, `sizing`, `price`, `leverage`, `stop_loss`, `take_profit`, `trailing_stop`,
`time_in_force`, `tpsl_mode`, `position_idx` and `skip` (yaml:18435-18465). What the contract does not yet say is
the comparator for each profile field: the threat model's F-02 (High) asks for it, with every field `never` unless
this record names it `narrow_only` (SR-E28-04, PF-T05), and F-01 (Critical, #2635) takes its never-widen rule from
this table.

Propagation: SCR-130 promises that profile changes reach open tickets within 2 s "over the private channel"
(`14-screens-catalogue.md` SCR-130), but the private topics are a fixed list with no `profiles` topic
(`23-ws-protocol.md` §6.2), `cv.v1` is frozen (§2.3, E17-T07), and the ticket's decision rule is that a topic is never
added: if an existing topic cannot meet 2 s without conflation loss, the client re-fetches over REST. #906 publishes
an internal bus event, `ProfilesChanged` on `{env}.profiles.{account_id}.changed`, rows and versions only, never
values (#968 comment 6356205285); the client half is this record's.

## Decision drivers

- The safety floor is fixed: no override widens `max_position_notional`, `max_daily_loss`, `max_open_positions`,
  `max_leverage_cap`, the allowed-symbol set or `require_native_sl` (the orchestrator's note 2 on #968).
- Deny by default (SR-E28-04): a field is `narrow_only` only with a named comparator; a field added to
  `AccountProfile` later is `never` until an amendment of this record classifies it.
- Server-side authority (C-2.12, C-12.5): every comparator runs in the backend; the client only renders.
- Reject, never clamp silently (C-12.5, E28 threat model D6).
- The native stop is never optional (C-2.6, C-4.14).
- The wire contract is frozen (`23-ws-protocol.md` §2.3); additive changes only, contract first (C-6.1, C-6.3).
- SCR-130's 2 s propagation and SCR-061's 300 ms preview.

## Considered options

- **Overrides (a).** O1 per-field comparators only (the cap fields compared one by one); **O2 per-field rules plus one
  resulting-leg comparator** (chosen); O3 any override within the caps alone.
- **Lifetime (b).** **L1 per ticket** (chosen); L2 per session.
- **Transport (c).** T1 a sub-event on an existing private topic (`trade_groups`, or `wallet`); **T2 an
  event-triggered REST re-fetch, triggered by T3's frame** (chosen); T3 a `system` sub-event alone; T4 a REST poll
  with no push.
- **Mid-ticket edits (d).** D1 silent re-price; **D2 an explicit "profile changed — review" state** (chosen); D3 block
  the ticket.

## Decision outcome

### Decision 1 — the override decision table (a)

**Terms.** _B_ is the leg's account's bound profile: its default, at the version the server reads for this request.
_A_ is an alternate profile named by `overrides.profile_id` (one of the same account's live profiles). _O_ is the
request's `defaults` then the leg's `overrides`, applied in that order. _L_B_ is the leg the sizer and its clamps
(24 §9.3, §9.3.2) produce from _B_ alone; _L_ is the leg they produce from _B_ with _A_ and _O_ applied. Both are
computed in the same request, from the same wallet, instrument and reference price, after the same rounding
(quantity floored to the lot step, the stop rounded away from entry, 24 §9.3.1).

**The ceiling is the bound profile's caps and budget, not the leg it would size by itself** (coordinator ruling,
2026-10-25, on #968). A request may raise size up to the bound profile's caps and is refused above them; it never
gets more than the caps and the risk budget allow. The _effective caps_ are _B_'s, tightened by _A_ (rows 29 to 39
and 42). The _risk ceiling_, for every _B_, is the **net daily-loss headroom**: the remaining headroom under the
effective `max_daily_loss` and `max_daily_loss_pct` (the sizer's daily-loss clamp, 24 §9.3.2) minus the account's
committed risk. When _B_ sizes `risk_based`, its per-trade budget (`risk_fixed_amount`, or `risk_pct_equity` times
equity) is a further per-leg cap: the ceiling is the lesser of that budget and the net headroom.

**Committed risk is one ledger of reservations.** The account's committed risk is the sum of its live reservations, and
nothing is counted twice. A reservation is the leg's risk at the stop, made for every admitted leg at admission, in the
same transaction as the leg insert (the SR-E28-15 transaction). When the order fills, the same reservation covers the
position; no second one is made. It is reduced pro rata as quantity leaves the order or the position (a partial fill
then a cancel, a partial close, a take-profit ladder fill), and released when the order is cancelled or the position
closes otherwise. When the stop fills, the release and the count of the realised loss in the headroom are one step, so
the loss is neither counted twice nor missing between them. Reduce-only and take-profit ladder orders add nothing to
the committed risk. On an amend of a leg's quantity or stop, that leg's own reservation is left out while R judges it
again (`amendTradeGroup`, yaml:6548-6550), and the new reservation replaces it on admission. So concurrent legs and
tickets on one account together never risk more than `max_daily_loss`, where each judged alone against the full
headroom could. The preview shows the net figure. When the committed risk cannot be established (a position or
working order whose stop is unknown, or an account whose positions and orders are not reconciled), the net headroom is
zero: rule 2 fails every leg (fail closed), and the preview and the refusal name the reason. The netting is a
money-semantics decision and is on the owner's sign-off list (Owner sign-off items).

**The resulting-leg comparator R (SR-E28-04).** A leg is admitted only if every one of these holds for _L_:

1. its notional is within the effective position caps (`max_position_notional`, `max_position_pct_equity`) as the
   sizer's clamps compute them (24 §9.3.2);
2. its risk at the stop (quantity times the resolved stop distance, entry and exit fees included as 24 §9.3 step 5)
   is within the risk ceiling (the net daily-loss headroom, capped by the per-trade budget for a `risk_based` _B_;
   the request's other legs on the same account count as committed);
3. its leverage is within the effective `max_leverage_cap`, and its resolved stop lies between the entry and the
   estimated liquidation price at that leverage (RSK-085). The estimate is an isolated-margin figure from the
   symbol's risk-limit tier and its maintenance margin rate, whatever `margin_mode` says; when the tier or its rate is
   unavailable, the leg fails (fail closed; OPEN-2);
4. its stop is no further from `ref` than _L_B_'s and is on the loss side of `ref`:
   `abs(ref - L.stop) <= abs(ref - L_B.stop)` (the stop never moves away from entry and never crosses it);
5. its quantity and notional meet the instrument's minimums and _B_'s `min_leg_notional`; a quantity below them is
   never rounded up, and a minimum order that breaks rule 1 or 2 is refused with its reason (coordinator ruling: a
   one-click minimum above the budget is refused, never rounded up; #904 QA plan (V04));
6. its initial margin is within the available margin times 0.98 (24 §9.3 step 8), a failure and never a shrink;
7. every other cap the guard reads (open positions, concurrent orders, order rate, daily loss) and the symbol rows
   hold;
8. at admission, the leg's first native stop covers _L_'s full quantity under either `tpsl_mode`: the leg request has
   no stop-size member, and under `Partial` the server sets the stop's size to the leg's full quantity itself (C-2.6;
   PF-T20). After admission the only path to a smaller stop is 24 §8.8 rule 5, the owner-only `sl_loosen` step-up on
   a `SetTpSlRequest` `sl_size` (yaml:6847-6858, yaml:18861). A stop that cannot be placed for the full quantity
   under `Partial` is a post-entry failure: it starts E34-S03's unwind (no position is left without a native SL,
   C-2.6), never a refusal.

Equality is admitted. Comparisons are `Decimal`, in the domain's units (fractions, not the REST percent; 24 §9.2
"REST projection"), on quantized values only: quantity floored to the lot step, the stop rounded away from entry.

**Refused, never clamped** (coordinator ruling, 2026-10-25). A request value that breaks R is refused at admission and
never silently clamped to the limit, as the sizer's margin check fails a leg rather than shrinking it (24 §9.3 step
8; C-12.5; E28 threat model D6). The refusal is the whole request's, before any leg is sent, whatever `atomicity` says:
`403 risk_limit_breached`, the problem code `22-api-openapi.yaml` already registers (yaml:588), with one `errors[]`
entry per offending leg naming the field, the requested value and the limit (yaml:6297-6301); a rule-2 entry also
carries the net headroom and the committed risk. It is audited before
the answer, as the refused-widening row the threat model lists beside `tradegroup.row_overridden{field, from, to}`
(§8; E28-S05 registers its action name), with `cv_override_refused_total{field}`. Only the profile's own sizing, with
no request value, is clamped and explained (`sizing_explanation`, yaml:6308-6309). The "clamp" reading of a widening
override in E28-S05 (#1144) and E28-X03 (#976) is wrong; the comment drafts correct it. The contract's sentence that
"quantity, notional, leverage, margin and risk at the stop may not rise" (yaml:6296-6299) reads, under this ruling,
"may not exceed the bound profile's caps and risk budget"; that wording change is a contract follow-up (C-6.1) for
#2635.

**Absent, null and alternates.** An absent override member takes _B_'s value. An override member set to JSON `null`
is refused `422 validation_failed` (an override cannot unset a field; `stop_loss: null` is also
`native_stop_required`, as on amend). For an alternate _A_, each field follows its row below: a cap or symbol row
(29 to 39, 42) combines _A_ with _B_ as the row says, so _A_ only ever tightens it; any other `narrow_only` field takes
_A_'s value as if the request had sent it, judged by its comparator and R, so an _A_ that would widen a leg refuses the
request like any widening value; a `never` field takes _B_'s value, and the preview's `sizing_explanation` names each
field of _A_ that was held at _B_. Request values apply after _A_. A `NULL` cap on either side is "no value from this
side", never "no cap" when the other side has one. An `overrides.profile_id` that is not one of the leg's account's
live profiles — missing, deleted or another account's, granted or not — refuses the whole request with
`404 not_found`, one title and `detail` for all, decided at validation after the account-scope check and before any
leg is sized (yaml:6309-6314, SR-E28-03; #2635 owns the route half).

**The table.** Every field of `AccountProfile` (24 §9.2), 42 in all, in the model's order, except
`updated_at`, which the model lists last and the table keeps beside `version`. `never`: no request value
changes the field for this leg. `narrow_only`: a request value may move it only within the ceiling, by the comparator
in the last column, then R; past the ceiling it is refused.

| #   | Field                     | Class         | Override source       | Comparator (judged on the resulting leg, against _B_ as the ceiling)                                                                                          |
| --- | ------------------------- | ------------- | --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `profile_id`              | `never`       | —                     | identity; an alternate is a selection, recorded on the leg snapshot, not an override of this field                                                            |
| 2   | `account_id`              | `never`       | —                     | identity; an alternate of another account is the `404` above                                                                                                  |
| 3   | `name`                    | `never`       | —                     | display only                                                                                                                                                  |
| 4   | `is_default`              | `never`       | —                     | the ceiling's identity (D7); moved only by `setAccountDefaultProfile`                                                                                         |
| 5   | `enabled`                 | `never`       | —                     | a disabled _A_ is refused `403 risk_limit_breached`; narrowing a leg away is `overrides.skip`, not this field                                                 |
| 6   | `trading_enabled`         | `never`       | —                     | as `enabled`: a not-trading-enabled _A_ is refused `403 risk_limit_breached`                                                                                  |
| 7   | `version`                 | `never`       | —                     | server-set; the leg records it (Decision 4)                                                                                                                   |
| 8   | `updated_at`              | `never`       | —                     | server-set                                                                                                                                                    |
| 9   | `sizing_mode`             | `narrow_only` | `sizing.mode`, _A_    | any mode, admitted only through R (a mode switch is how PF-T04 widens, so R's caps and risk ceiling decide)                                                   |
| 10  | `fixed_qty`               | `narrow_only` | `sizing.qty`, _A_     | may be raised (US-PROF-008) or lowered; the resulting leg within R rules 1, 2 and 5; above the caps refused                                                   |
| 11  | `fixed_notional`          | `narrow_only` | `sizing.notional_usd` | as 10                                                                                                                                                         |
| 12  | `pct_equity`              | `narrow_only` | `sizing.pct`, _A_     | as 10                                                                                                                                                         |
| 13  | `risk_pct_equity`         | `narrow_only` | `sizing.*`, _A_       | the resolved per-trade budget in USDT (`risk_pct_equity` times equity, or `risk_fixed_amount`) `<=` _B_'s resolved budget when _B_ sizes `risk_based`; then R |
| 14  | `risk_fixed_amount`       | `narrow_only` | `sizing.*`, _A_       | as 13: one resolved USDT budget, whichever of 13 and 14 sets it; then R (still exactly one of 13 and 14)                                                      |
| 15  | `min_leg_notional`        | `never`       | —                     | _B_'s; a leg the trader does not want is `overrides.skip`                                                                                                     |
| 16  | `qty_rounding`            | `never`       | —                     | always `floor`                                                                                                                                                |
| 17  | `leverage`                | `narrow_only` | `leverage`, _A_       | `<=` the effective `max_leverage_cap`, the stop inside the isolated-margin liquidation estimate (R rule 3, fail closed; OPEN-2); then R                       |
| 18  | `margin_mode`             | `never`       | —                     | an account-wide exchange setting (PF-T05)                                                                                                                     |
| 19  | `position_mode`           | `never`       | —                     | account-wide; `overrides.position_idx` must match _B_'s mode, else `422 validation_failed`                                                                    |
| 20  | `require_native_sl`       | `never`       | —                     | the floor; always `true` (C-2.6)                                                                                                                              |
| 21  | `sl_offset_value`         | `narrow_only` | `stop_loss`, _A_      | the resolved stop: R rule 4 (no further from entry); then R, so a tighter stop that raises a `risk_based` size passes only within the caps                    |
| 22  | `sl_offset_unit`          | `narrow_only` | `stop_loss.unit`, _A_ | judged only through the resolved stop (as 21); `r_multiple` refused (`stop_defines_r`)                                                                        |
| 23  | `sl_atr_period`           | `narrow_only` | _A_                   | judged only through the resolved stop (as 21)                                                                                                                 |
| 24  | `sl_atr_multiple`         | `narrow_only` | _A_                   | judged only through the resolved stop (as 21)                                                                                                                 |
| 25  | `fallback_sl_offset_pct`  | `never`       | —                     | _B_'s: the ATR-warm-up stop is the profile's (PF-T05)                                                                                                         |
| 26  | `tp_offset_value`         | `narrow_only` | `take_profit`, _A_    | the resolved take-profit on the profit side, no further from entry than _B_'s, or added where _B_ has none                                                    |
| 27  | `tp_offset_unit`          | `narrow_only` | `take_profit.unit`    | judged only through the resolved take-profit (as 26)                                                                                                          |
| 28  | `tp_ladder`               | `never`       | —                     | _B_'s; no override member names it                                                                                                                            |
| 29  | `max_position_notional`   | `narrow_only` | _A_ only              | effective `= min(B, A)`; never from a request value; **floor**                                                                                                |
| 30  | `max_position_pct_equity` | `narrow_only` | _A_ only              | effective `= min(B, A)`                                                                                                                                       |
| 31  | `max_daily_loss`          | `narrow_only` | _A_ only              | effective `= min(B, A)`; **floor**                                                                                                                            |
| 32  | `max_daily_loss_pct`      | `narrow_only` | _A_ only              | effective `= min(B, A)`                                                                                                                                       |
| 33  | `max_open_positions`      | `narrow_only` | _A_ only              | effective `= min(B, A)`; **floor**                                                                                                                            |
| 34  | `max_concurrent_orders`   | `narrow_only` | _A_ only              | effective `= min(B, A)`                                                                                                                                       |
| 35  | `max_leverage_cap`        | `narrow_only` | _A_ only              | effective `= min(B, A)`; **floor**                                                                                                                            |
| 36  | `max_orders_per_minute`   | `narrow_only` | _A_ only              | effective `= min(B, A)`                                                                                                                                       |
| 37  | `all_symbols`             | `narrow_only` | _A_ only              | the symbol must be allowed by _B_ **and** by _A_ (an `all_symbols` _A_ adds nothing); **floor**                                                               |
| 38  | `allowed_symbols`         | `narrow_only` | _A_ only              | effective allow-list `= B ∩ A` by pattern match; an empty list without `all_symbols` allows nothing (D11, US-PROF-003: fail closed); **floor**                |
| 39  | `denied_symbols`          | `narrow_only` | _A_ only              | effective deny-list `= B ∪ A`                                                                                                                                 |
| 40  | `reduce_only_default`     | `narrow_only` | request `reduce_only` | may set `true` where _B_ is `false`; never `false` where _B_ is `true`                                                                                        |
| 41  | `time_in_force_default`   | `narrow_only` | `time_in_force`, _A_  | resting life no longer than _B_'s: `FOK`, `IOC` `<=` `GTC`, `PostOnly`; `GTC` and `PostOnly` are peers                                                        |
| 42  | `slippage_tolerance_bps`  | `narrow_only` | _A_ only              | effective `= min(B, A)`                                                                                                                                       |

Totals: 15 `never`, 27 `narrow_only`, 0 unclassified. The prototype checks the count against the live model
(`measure.py`, `decision_table_check`). The six floor fields are never widened: rows 29, 31, 33 and 35 take only a
stricter alternate's value and no request value; rows 37 and 38 only intersect; row 20 is `never`.

**Request members that are not profile fields** are outside the table and stay ticket parameters, each still judged
through R: `price` (it sets `ref`, and _L_B_ is computed at the same `ref`), `trailing_stop` (additional to the native
stop, never instead of it: C-2.6), `tpsl_mode` (R rule 8), `position_idx` (row 19) and `skip`. The `Offset` and
`Sizing` schemas carry more (yaml:17143-17185):

- `sizing.max_notional_usd` only narrows: the leg's cap is `min(request, effective caps)`.
- `sizing.round_to_lot` (default `true`): `false` conflicts with row 16 (`qty_rounding` is `never`, always `floor`) and
  is refused `422 validation_failed`.
- The sugar modes `pct_position` and `profile` (yaml:16074) are modes like any other: judged through R (row 9).
- `atr_period`, `atr_bar_type` and `atr_param` on `stop_loss` or `take_profit` are judged only through the resolved
  stop or take-profit, as rows 22 to 24.
- A sizing override incomplete for its mode (for example `mode: risk_based` with neither `risk_per_trade_usd` nor
  `risk_per_trade_pct` while _B_ sizes `fixed_qty`) is refused `422 validation_failed`; a missing member is never
  taken from a _B_ that sizes another mode.

**Enforcement.** Server-side only (C-2.12); the client greys out what the preview refuses, which is no control.
E28-S05 (#1144) makes the table an automated test, not a convention: `test_every_profile_field_has_an_override_class`
fails on a model field missing from the table or a table row naming no field; `test_override_cannot_exceed_bound_profile_field_by_field`
and `test_submit_beyond_cap_is_rejected_not_clamped` (SR-E28-03); `test_narrowing_is_judged_on_the_resulting_leg`, a
hypothesis property over random _B_, _A_ and _O_ that asserts R (SR-E28-04); and an alternate of another account
answers `404` exactly as a missing one does.

```gherkin
Feature: Per-trade overrides against the bound profile (ADR-0040 Decision 1; E28-S05, E30)

  Background:
    Given account B's bound profile sizes fixed_qty 0.100 BTC with max_position_notional 20000 USDT
    And BTCUSDT is at 64010 and the ticket targets B

  Scenario: Raise size within the profile cap
    When the trader overrides B's size to 0.250 BTC (16002.5 USDT)
    Then the preview and the submit admit it, flagged as an override
    And the override is audited as tradegroup.row_overridden and journal-tagged

  Scenario: Raise size above the profile cap
    When the trader overrides B's size to 0.400 BTC (25604 USDT)
    Then the preview and the submit refuse the whole request with 403 risk_limit_breached, naming B's leg, the field,
      the requested value and the 20000 USDT limit
    And the size is never clamped to the cap, the refusal is audited, and the control shows "capped by profile"

  Scenario: A one-click minimum above the risk budget is refused (#904 QA plan (V04))
    Given account B's bound profile sizes risk_based with a risk budget of 0.10 USDT
    And the computed quantity is below the 0.001 BTC minimum, and 0.001 BTC at the resolved stop risks 0.12 USDT
    Then the ticket does not offer the minimum as a one-click choice, and states "the 0.001 BTC minimum risks
      0.12 USDT, above the 0.10 USDT budget"
    And a submit of 0.001 BTC is refused 403 risk_limit_breached and audited, never rounded up

  Scenario: An empty allow-list allows nothing
    Given an alternate profile of B has no allowed symbols and all_symbols is not set
    When the trader selects it for a BTCUSDT ticket
    Then B's leg is refused as symbol not allowed, and nothing is sent for B
```

### Decision 2 — override lifetime: per ticket (b)

An override lives in one ticket and is cleared when the ticket is submitted, cancelled, or retargeted (another symbol
or another set of accounts). It is never stored on the server between requests: each request carries its overrides
and is judged on its own (SR-E28-03). It is not kept per session.

Reasons: US-PROF-008 states the reset ("resets to the profile default for the next ticket"); a per-session override
outlives the profile version it was judged against, so it would be re-applied after an edit the trader may not have
seen; a session spans symbols and accounts, so one override would reach legs it was never judged for; and a
per-ticket override gives each `tradegroup.row_overridden` record exactly one order to name.

### Decision 3 — propagation transport inside the frozen topic list (c)

**Chosen: T3's frame as the trigger, T2's REST re-fetch for the values.**

1. **Server.** A gateway bridge subscribes to #906's `{env}.profiles.*.changed` (`NEVER_DROP`: writes are rare) and,
   for each event, offers every authenticated socket one `system` frame of `kind: "account_notice"` with
   `reason: "profiles.changed"`, `severity: "info"`, a role-neutral `message` ("An account profile changed.") and
   `exchange_account_ids: [account_id]` — and no other field: no profile id, no version, no value. It goes through
   `GatewayHub.broadcast_system` (`ws/gateway.py:493-498`), so `system_view` cuts it to each socket's
   `account_scope` and sends nothing to a socket that may view none of the accounts (`ws/system_filter.py:88-117`,
   SR-188, SR-E29-10).
2. **Client.** On that frame, for an account an open ticket targets, the client re-fetches
   `GET /exchange-accounts/{accountId}/profiles` through its own session and scope (`api/profiles.py:188-206`,
   `accounts:read`, the same `account_scope`), compares each profile's `version` with the one the ticket holds, and on a
   change enters Decision 4's review state. Backstops, because a `system` frame is not replayed after a disconnect:
   the client re-fetches on ticket open, on every `auth_ok`, and on a `profile_changed` refusal.
3. **Guard.** Propagation is the experience; the submit-time version check is the control (Decision 4).

**Why it is inside the frozen list.** No topic is added. `system` is in the list and auto-subscribed (§6.2);
`account_notice` exists (§15.9, #3864); its `reason` set is open and `system.kind` is an open enum (§2.3), so a new
code is additive and the golden (`packages/protocol/wire-contract.v1.golden.json`) does not change. What 23 must
still say, contract first (C-6.1), is one paragraph in §15.9: `profiles.changed` is an **event**, not an account
state — §15.9 has a client keep "the latest `reason` per account id, which `oms.account_synced` clears"; a
`profiles.changed` must not replace an `oms.*` state in that latch. That edit, the new code in the open list and the
bridge are #906's late contract-first slice (coordinator ruling, 2026-10-25 00:41Z; Consequences), not this PR.

**Pacing.** As built, `push_system` queues a `system` frame at once (`ws/gateway.py:839-853`); notices are never
merged (§8.2). The 1 000 ms default that §6.2 lists for `system` is the worst case, and the prototype measures both.

**Measured** (local dev stack, the Deviation in `docs/plan/spikes/E28-K01.md` §4; 200 iterations each, commit to the
re-rendered preview, milliseconds):

| Transport                                                       | n   | p50   | p95   | p99   | max     | of which: client learns, p95 | re-fetch p95 | preview p95 |
| --------------------------------------------------------------- | --- | ----- | ----- | ----- | ------- | ---------------------------- | ------------ | ----------- |
| (iii)+(ii) `system` `account_notice`, as built (sent at once)   | 200 | 2.9   | 3.8   | 4.5   | 10.1    | 0.6                          | 1.8          | 1.4         |
| (iii)+(ii) the same, 1 000 ms `system` window (23 §6.2 default) | 200 | 508.5 | 951.3 | 995.0 | 1 001.0 | 948.7                        | 2.6          | 3.4         |
| (i)+(ii) `trade_groups` sub-event, 100 ms window                | 200 | 53.8  | 99.3  | 104.2 | 104.5   | 95.8                         | 2.3          | 1.7         |
| (ii) REST poll every 1 000 ms, no frame                         | 200 | 500.5 | 946.3 | 989.6 | 999.0   | 943.3                        | 2.6          | 1.7         |

| Stand-in preview alone | n   | p50 | p95 | p99 | max  |
| ---------------------- | --- | --- | --- | --- | ---- |
| 5 legs                 | 200 | 1.1 | 1.4 | 2.0 | 11.1 |
| 20 legs                | 200 | 1.1 | 1.3 | 1.8 | 3.0  |

The chosen path meets SCR-130's 2 s as built (p95 3.8 ms, max 10.1 ms) and under the documented 1 000 ms window
(p95 951.3 ms, max 1 001.0 ms). The stand-in preview is far inside SCR-061's 300 ms but reads no Postgres, wallet or
instrument cache: E28-S05 and E34 measure the real `previewTradeGroup`.

**Why not the others.**

- **T1 `trade_groups` sub-event.** It is the group lifecycle topic: an open single-account ticket (SCR-060) need not
  subscribe to it, its snapshot is the active groups, and its payload schema is closed (`additionalProperties: false`,
  §15.5), so a `profiles_changed` member is a schema change every consumer meets, under `orders:read` rather than the
  profile read's `accounts:read`. It carries no values either, so it still needs the re-fetch. `wallet` matches the
  permission (`accounts:read`) but is coalesced last-write-wins per object (§8.2) and its 500 ms window lies between
  the two windows measured; it is balances and health, not policy. Measured at 100 ms, T1 meets 2 s, so it is not
  rejected on time: it is rejected on meaning and on the schema change.
- **T3 alone (values on the frame).** Values on `system` would reach every role's socket through `system_view`, which
  passes only role-neutral fields (§15.9); and the event carries none (#906: rows and versions only).
- **`notice` instead of `account_notice`.** A `notice` may name no account (`ws/system_filter.py`; §15.9), so it would
  reach every socket and tell every role that some profile changed somewhere.
- **T4 REST poll.** Meets 2 s at a 1 s interval but costs one profile read per open ticket per second whether or not
  anything changed; kept only as the backstops of step 2.

### Decision 4 — a profile changed under an open ticket (d)

**Chosen: an explicit "profile changed — review" state (D2).** The event propagates; the submit-time version check
guards (SR-E28-15). Silent re-price (D1) would send a size the trader never saw; blocking (D3) discards a ticket for a
change that needs only a look.

- On a change the ticket re-fetches, asks the server for a new preview, shows each changed number as before and
  after, and disables Send until the trader confirms the review. Overrides are re-judged against the new _B_: one
  that now widens is cleared and shown as "capped by profile"; one that still narrows is kept, and the review lists it.
- **The guard has a contract gap.** SR-E28-15 compares the leg's `profile_version` with the current one inside the
  leg-insert transaction, which closes the server's own window between sizing and insert. It does not tie the submit to
  the preview the trader reviewed: the server sizes from the current profile, so a submit sent after an unseen edit
  is sized at the new version without any refusal. The submit must therefore carry the versions the ticket previewed —
  each leg's bound profile version and default-binding version, and an alternate's version — and the server refuses
  `409 profile_changed` when any differs, whole, before any leg is sent. `profile_changed` is not in
  `22-api-openapi.yaml` today (the problem code and the members are a contract follow-up for #906 and #1110), and the
  preview's legs must return the versions they used (`TradeGroupPreview.legs[]` has `account_profile_id` only).
- The versions are **required** members of `createTradeGroup`, and of `placeOrder` wherever it takes a `profile_id`; a
  submit without them is refused `422 validation_failed`. The check is a trader-awareness control: the server still
  sizes every leg from the current profile version (C-2.12), so the safety floor and R never depend on what the client
  sends.

```gherkin
Feature: A profile changes under an open ticket (ADR-0040 Decision 4; E28-S05, E30)

  Background:
    Given account B's bound profile is at version 7 with max_position_notional 50000
    And a ticket targeting account B shows a preview sized at version 7

  Scenario: An edit narrows a cap under an open ticket
    When the owner lowers B's max_position_notional to 20000 (version 8)
    Then within 2 s the ticket shows "Profile changed — review" with the old and new size of B's leg
    And Send is disabled until the trader confirms the review
    And the status message is announced once, politely, and the disabled reason is text, not colour alone

  Scenario: An edit widens a cap under an open ticket
    When the owner raises B's max_position_notional to 80000 (version 8)
    Then the ticket enters "Profile changed — review" with the new preview
    And no size larger than the reviewed one is sent until the trader confirms the review
    And the ticket keeps the previously reviewed size until the trader confirms the review

  Scenario: The bound profile changes because the default moved
    When the owner makes another of B's profiles the default (binding version 4 to 5)
    Then the ticket enters "Profile changed — review" against the new bound profile
    And every override is re-judged against the new bound profile

  Scenario: The selected alternate profile is deleted
    Given the ticket names B's alternate profile P
    When the owner deletes P
    Then the ticket clears P, shows "Selected profile no longer exists", and enters "Profile changed — review"
    And a submit that still names P is refused 404 not_found, as a missing profile is

  Scenario: The change notice is lost or late
    Given the client missed the profiles.changed notice for B
    When the trader submits with the versions the preview used (profile 7, binding 4)
    And B's bound profile is at version 8
    Then the submit is refused 409 profile_changed before any leg is sent, and the refusal is audited
    And the ticket re-fetches B's profiles and enters "Profile changed — review"

  Scenario: A submit without the previewed versions
    When a submit names B's leg without the profile versions its preview used
    Then the submit is refused 422 validation_failed before any leg is sent

  Scenario: The profile narrows below an override
    Given the trader overrode B's leverage to 8 while B's max_leverage_cap is 10
    When the owner lowers B's max_leverage_cap to 5 (version 8)
    Then the leverage override is cleared and the control shows "capped by profile: 5x"
    And a submit that still sends leverage 8 is refused 403 risk_limit_breached and audited, never clamped to 5

  Scenario: An override that still narrows survives the review
    Given the trader overrode B's stop to 15 ticks while B's stop is 20 ticks under fixed_qty sizing
    When the owner raises B's max_daily_loss (version 8)
    Then the review lists the 15-tick stop as kept, and the trader confirms it before Send is enabled
```

### Observability

`cv_profile_propagation_seconds`, a histogram, is observed by the gateway bridge (#906's late slice) when it hands a
socket its `profiles.changed` frame, from the commit time `ProfilesChanged` carries (#906 should add it to the event)
to that hand-off; labels `env` only, never an account id. The client's half (the re-fetch and the preview) is the
existing HTTP latency series of the two routes; the end-to-end 2 s is asserted by E28-S01's (#971) end-to-end test. A
refused stale submit counts in `cv_override_refused_total{field="profile_version"}` beside the threat model's
`cv_override_refused_total{field}` (§8 of the model).

### Accessibility constraint for the designer (E28-D03, SCR-061)

The control an override cannot raise shows its limit in text, "capped by profile: 5x", as its accessible description,
and the disabled reason is announced when the control takes focus; colour is never the only signal (C-14.1,
`05-accessibility-standard.md`). An override is marked by a text label ("override") as well as by any styling. The
review state is a text status (`role="status"`, polite, announced once per change, never per tick) and the Send
button's accessible name states why it is disabled. This record designs no control.

## Consequences

- Good: one comparator decides every narrowing, so PF-T04's "narrow one field, widen another" cannot pass; the six
  floor fields are never widened by construction; no topic, frame shape or golden changes.
- Good: a stale ticket is caught at submit even when every notice is lost.
- Bad: a request value past the ceiling is refused, never trimmed to fit, so the trader re-enters it; the ticket must
  say why, from the refusal's `errors[]`, and the "capped by profile" control limits what can be typed.
- Bad: the review state adds a step whenever an owner edits a profile under an open ticket; edits are rare.
- Follow-ups, on existing tickets only (the filing freeze): **#906** E28-T02 — the commit time on `ProfilesChanged`;
  and, as a late contract-first slice (coordinator ruling, 2026-10-25 00:41Z; OPEN-4), first the 23 §15.9 paragraph
  and the `profiles.changed` reason in their own small PR, then the server bridge from `ProfilesChanged` to
  `account_notice` and its `cv_profile_propagation_seconds` observation. **#906 and #1110** (E34-S02, the route half of
  SR-E28-15) — the `profile_changed` problem code, the versions on the preview legs, and the previewed versions as
  required members of the submit (Decision 4). **#1144** E28-S05 — the table as code and its four tests, R (the net
  risk ceiling and rule 8 included), the review state's server half. **#971** E28-S01 — the client half: the re-fetch
  on the notice, the backstops, the review state and the 2 s end-to-end test. **#2635** F-01 — the never-widen rule is
  this table's R and rows 29 to 39 and 42; the contract wording of "may not rise" and rule 8's full-quantity stop.
  **E30** — the ticket's override controls, the "capped by profile" text and the review state.

## Why not the alternatives

- **O1 per-field comparators only.** Each field narrows on its own, yet a tighter stop raises a `risk_based` size and
  a `fixed_qty` override replaces risk sizing (PF-T04); only a resulting-leg check sees that.
- **O3 any override within the caps alone.** It is "later wins" bounded by the caps: a stop could move away from
  entry, the risk budget would not bind, and a `never` field (margin mode, the fallback stop) could change; the contract
  says "later narrows" (ADR-0008 Amendment 3), and the stop and the risk budget are part of the ceiling.
- **L2 per session.** See Decision 2.
- **D1 silent re-price, D3 block.** See Decision 4.

## Open questions

- **OPEN-1 — resolved** by the coordinator's ruling of 2026-10-25 on #968: US-PROF-008's "raise size within its risk
  cap" stands; size may rise up to the bound profile's caps and is refused above them (R rules 1 and 2); the contract
  sentence follows (#2635). The owner may still override the ruling on #2701.
- **OPEN-2 (risk semantics; Security engineer).** By the same ceiling, leverage may rise up to the effective
  `max_leverage_cap` (US-PROF-008's second scenario refuses only "above the profile cap"), guarded by R rule 3's check
  that the stop lies inside the estimated liquidation price (RSK-085). Recommendation, adopted in rule 3 and row 17:
  the estimate is an isolated-margin figure from the symbol's risk-limit tier and its maintenance margin rate, whatever
  `margin_mode` says, and when the tier or its rate is unavailable rule 3 fails the leg (fail closed). With that
  estimate row 17's "up to the effective cap" stands; without it, row 17 narrows to `<= B.leverage`. The Security
  engineer confirms the estimate's source.
- **OPEN-3 (contract).** A leg stores one `profile_version` (24 §9.1); with an alternate, the submit check needs the
  bound profile's version and the binding's too. Recommendation: the leg snapshot records all three, and #906 / #1110
  decide the columns.
- **OPEN-4 — resolved** by the coordinator's ruling of 2026-10-25 (00:41Z): the bridge from `ProfilesChanged` to
  `account_notice` (reason `profiles.changed`) and the one-paragraph 23 §15.9 change are a late slice of #906
  (E28-T02), contract first (the 23 paragraph and the new reason in their own small PR, then the bridge); #971
  (E28-S01) consumes it in the UI.

## Owner sign-off items (#2701)

The status stays `proposed` until the owner and the Architect sign off, on #2701, on:

1. the decision table and the comparator R (Decision 1);
2. the net risk ceiling for every _B_: the remaining daily-loss headroom minus the committed risk (one ledger of
   reservations, made for every admitted leg in the leg-insert transaction, covering the position once filled,
   reduced pro rata, released on cancel, stop fill or close, and shown in the preview); for a `risk_based` _B_ the
   ceiling is the lesser of its per-trade budget and that net headroom; when the committed risk cannot be
   established, the net headroom is zero and every leg fails (fail closed) (Decision 1; a money-semantics decision);
3. OPEN-1's ruling (size up to the caps) and OPEN-2's fail-closed isolated-margin liquidation estimate behind row 17.

## Validation

- `measure.py` reproduces the numbers above and the table's field count; `results.json` holds the raw samples.
- E28-S05's four tests (Decision 1) and E28-S01's end-to-end test (Decision 3) are the lasting checks.
- The threat model's AC-04, AC-11, AC-12, AC-21 and AC-32 (E28-X03) exercise the table and the version check.

## References

`docs/plan/24-internal-schemas.md` §9.1–§9.3.2; `docs/plan/22-api-openapi.yaml` (`createTradeGroup`,
`previewTradeGroup`, `TradeGroupLegInput`); `docs/plan/23-ws-protocol.md` §2.3, §6.2, §8.2, §15.5, §15.9;
`docs/plan/11-user-stories.md` US-PROF-001..008; `docs/plan/14-screens-catalogue.md` SCR-060, SCR-061, SCR-130;
`docs/security/threat-models/E28-profiles-trade-groups.md`; ADR-0008; `docs/plan/spikes/E28-K01.md`.
