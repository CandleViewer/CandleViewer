# E28 exploratory charters — profiles, sizing and trade groups

Ticket: E28-Q01 (issue #904), slice B, with the black-box plan
`qa/plans/e28-profiles-test-plan.md`. Executed by E28-Q04 once its screens and routes land. Status:
**Written — not executed.** The path follows the flat `qa/plans/` convention instead of the
ticket's `qa/plans/e28/`, as the plan's header records.

Four session-based charters of 90 minutes each, named as #904 names them. Scripted cases confirm
what was anticipated; these sessions look for what was not (`docs/plan/03-testing-strategy.md`
§11.2). Each session:

- runs on the stub stack with the fixture set loaded (`tests/fixtures/e28/README.md`, "Loading")
  and the plan's users (§12.2); never against a live exchange (C-13.5) and never with a real key;
- keeps to its mission for most of the box, and notes opportunities outside it for a later session
  rather than chasing them;
- files each defect under the plan's §0.1 conventions (a sizing error is P0; a bypass or a
  disclosure goes privately to the Security engineer), with the build sha, the fixture handles and
  the evidence codes of the plan's §0;
- ends with the debrief filled in, and names every finding worth a scripted case so E28-Q02 or
  E28-X03 can promote it.

The handles (E28-A to E28-D, E28-LIVE-MAIN, E28-LIVE-SUB, P-RISK, P-QTY, P-PCT, P-NOTIONAL, Core3,
Pair, G-CORE3, G-PAIR, V01 to V14) are slice A's, defined in its README.

---

## Charter 1 — "sizing rules under extreme equity"

**Mission.** Explore the sizer through the preview and the single-account ticket at extremes of
equity, price and instrument limits, to discover a quantity that is oversized, rounded up, off the
lot step, or let through by a cap applied out of order.

**Areas.**

- Equity: 0, 1, 20 and 30 (around the minimum lot, V03 and V04), 4000 (V13), 9980 (V09), 10000
  (V01), 10^9 (V11) and larger; available margin below equity; a wallet frame arriving while the
  ticket is open.
- Each sizing mode on its profile (P-RISK, P-QTY, P-PCT, P-NOTIONAL), long and short; stops in
  ticks, percent and ATR, and the ATR fallback (V06).
- The fee at 0 (the plan's zero-fee overlay, §12.6) and at 0.00055 (V01 against V02).
- A limit order against `max_order_qty` 100.000, a market order against `max_mkt_order_qty` 50.000.
- Prices at the instrument's bounds: BTCUSDT's 0.10 minimum and 999999.00 maximum, LUNAUSDT's
  0.0001 tick.
- The day's remaining room under the daily-loss cap (V10).

**Oracles.**

- The golden vectors V01 to V14 and the rules R1 to R14 of slice A's `sizing_recomputation.md`.
  Any digit of difference is P0.
- A quantity is always a multiple of the step, never above the binding instrument ceiling, never
  raised by a cap.
- The loss at the stop, fees included for risk-based sizing, never exceeds the budget.
- The stop is rounded away from entry.
- A skip and a failure stay distinct, each with its code and the minimum or the binding cap named.
- Decimals have no binary-float artefacts and no exponent form.
- The preview, the ticket and the leg agree digit for digit.

**Heuristics.** Zero, one, many; just below, at and above each boundary; follow the money
(notional = quantity × reference price, exactly); flip the side; change one input at a time; compare
the same intent across the preview, the ticket and the submitted leg.

**Risks.** An oversize repeated on every leg; rounding up; precision lost at extreme equity; the
market ceiling ignored on a market order; the margin check skipped when a cap binds first (V13);
sizing from a wallet older than 2 s (24 §9.4 rule 2).

**Data.** E28-A (P-RISK), E28-C (P-PCT); copies of P-QTY and P-NOTIONAL bound on E28-C for a run,
as the plan's PRO-06 does; V01 to V14; the four recorded instruments; the stub wallets of the
plan's §12.6.

**Notes and debrief.**

| Field                                      | Entry |
| ------------------------------------------ | ----- |
| Tester, date, start and end (UTC)          |       |
| Build sha; stack; seed commit; overlays    |       |
| Time on charter / on opportunity (%)       |       |
| Vectors and equities exercised             |       |
| Findings (id, severity, vector, case)      |       |
| Questions and spec gaps (plan §13 row)     |       |
| Not covered, and why                       |       |
| Debrief: what happened, results, obstacles |       |
| Cases to promote (E28-Q02, E28-X03)        |       |

---

## Charter 2 — "the profile editor under exchange-limit conflicts"

**Mission.** Explore SCR-131 saves, and the same writes by API, where profile values meet the
exchange's limits and the instrument cache's freshness, to discover a stored profile the exchange
would refuse, a misleading refusal, a relaxing write not labelled, or a refusal of policy left
unaudited.

**Areas.**

- Leverage against each allowed symbol's maximum. Every recorded symbol allows 100x, and a capture
  is never patched, so the "SOLUSDT allows at most 20x" refusal waits on a live `instruments-info`
  recording (the plan's BND-19 and §13 C-04); the profile's own cap is reached through
  `max_leverage_cap` below 100. A pattern such as `*USDT` counts as all symbols.
- `sizing.qty` against the minimum and the step: 0.001, 0.0009, 0.0015.
- `max_position_notional_usd` against a symbol's 5 USDT minimum notional: 5 and 4.99.
- Symbol entries not listed (DOGEUSDT, `XYZUSDT`), the patterns `*USD` and a bare `*`.
- Writes that only narrow, which read no cache, against writes that allow something new.
- An instrument cache older than 15 minutes: `503 instrument_cache_unavailable` with `Retry-After`,
  never a save unvalidated.
- Two editors on one profile (`412`, `428`); a step-up expiring mid-edit.
- The `stop_beyond_liquidation` warning at high leverage with the 2 % fallback stop.
- A body over 64 KiB; a decimal with too many places.

**Oracles.**

- `ProfileRejected`: the first pass, then the second, each refusal naming its member, its rule and,
  against an exchange limit, the symbol and the limit.
- Messages in plain language with units (SCR-131: "SOLUSDT allows at most 20x — your 25x would be
  rejected").
- Nothing stored on a refusal: the version and `ETag` unchanged.
- `profile.save_refused` for `native_stop_mandatory`, `above_leverage_cap`, `cap_unbounded` and
  every second-pass refusal.
- `relaxing` on a write that loosens a cap or widens what a trading profile allows, and the Owner
  notified (SR-E28-01); never on a sizing amount alone (the plan's PRO-04).
- Warnings never block a save.

**Heuristics.** One field at a time; narrow, then widen; interrupt (a cache refresh or a step-up
expiry during a save); a stale tab; type attacks on decimals (`"1e2"`, `" 5"`, a value one place
past its column).

**Risks.** A profile that sizes orders the exchange will reject; a stale cache passed off as
current; a relaxing change that reaches no one; exchange text shown raw instead of in domain
language (11 global AC 5).

**Data.** P-RISK on E28-A, P-PCT on E28-C, P-NOTIONAL on E28-D; alternates created on E28-A for
the session and deleted after it; the recorded instruments; DOGEUSDT as the unrecorded symbol.

**Notes and debrief.**

| Field                                       | Entry |
| ------------------------------------------- | ----- |
| Tester, date, start and end (UTC)           |       |
| Build sha; stack; seed commit; cache state  |       |
| Time on charter / on opportunity (%)        |       |
| Limits exercised (symbol, member, value)    |       |
| Findings (id, severity, refusal, audit row) |       |
| Questions and spec gaps (plan §13 row)      |       |
| Not covered, and why                        |       |
| Debrief: what happened, results, obstacles  |       |
| Cases to promote (E28-Q02, E28-X03)         |       |

---

## Charter 3 — "trade-group membership edge cases"

**Mission.** Explore trade-group definitions and their use in tickets across membership edges, to
discover a group that sends to an account it should not, hides a skip, spans two environments or
reveals a member outside the caller's grants.

**Areas.**

- Core3 (2 of 3 ready) and Pair (2 of 2).
- Adding E28-D, which allows no symbol, so the members share none (plan §13 C-16).
- Adding E28-LIVE-SUB to a demo definition; changing a definition's environment.
- A member disabled within a definition.
- A repeated member (`duplicate_account`); 20 and 21 members, from demo account shells the session
  registers for them (`POST /exchange-accounts`, no key; at most 5 sub-accounts to a main).
- Names that differ only in letter case; renaming onto a live name.
- A stale `ETag` (`412`).
- Deleting a definition while a group fired from it is open; firing from a soft-deleted one.
- A member's readiness flipping while a ticket is open (E28-B's self-check).
- The manager's view: Core3 hidden (E28-B not granted), Pair visible.

**Oracles.**

- US-PROF-005's three scenarios.
- `createTradeGroupDefinition` and `updateTradeGroupDefinition`: `environment_mismatch`,
  `write_once`, `duplicate_account`, `409` on a taken name.
- SR-E28-16, SR-E28-21 and SR-E28-31.
- Readiness stated as text with a reason.
- A skip always reported, never silent.
- No leg on a not-ready member, a disabled member or another environment.

**Heuristics.** Count (0, 1, 2, 20, 21 members); change state while it is in use; walk the role
matrix (Owner, Manager, Viewer); compare the UI, the API and the `trade_groups` frames.

**Risks.** Legs sent to a disarmed member; a group spanning demo and live; an ungranted member
leaked through a count, a total or a name; a membership change that skips step-up.

**Data.** Core3, Pair, G-CORE3, G-PAIR; E28-A to E28-D, E28-LIVE-MAIN, E28-LIVE-SUB; the users M
and V of the plan's §12.2; for the 20- and 21-member edges, the demo shells the session registers
and deletes after it.

**Notes and debrief.**

| Field                                      | Entry |
| ------------------------------------------ | ----- |
| Tester, date, start and end (UTC)          |       |
| Build sha; stack; seed commit; actor       |       |
| Time on charter / on opportunity (%)       |       |
| Memberships and states exercised           |       |
| Findings (id, severity, group, account)    |       |
| Questions and spec gaps (plan §13 row)     |       |
| Not covered, and why                       |       |
| Debrief: what happened, results, obstacles |       |
| Cases to promote (E28-Q02, E28-X03)        |       |

---

## Charter 4 — "preview under rapid intent changes"

**Mission.** Explore SCR-061's preview while the intent changes faster than the debounce, with
WS updates and profile edits in flight, to discover a stale preview shown as current, wrong totals,
Send enabled on stale data, lost focus, or a preview that writes or reaches the exchange.

**Areas.**

- Keystroke bursts in the price; the side flipped.
- The symbol switched from allowed to not allowed.
- Members toggled; overrides changed.
- Slow responses arriving out of order; the per-user rate exceeded (`429`).
- A readiness change mid-preview.
- An Owner's profile edit while the ticket is open (`profile_changed` at submit).
- Send pressed while a preview is in flight; `Esc` to cancel.
- Keyboard only, and with a screen reader.

**Oracles.**

- The last keystroke wins; a stale response is discarded, never shown as current (E28-S04).
- The re-run lands within 300 ms of the last keystroke.
- The totals equal the sum of the submittable legs.
- No group, leg or order row and no exchange call from a preview (SR-E28-22).
- A submit never sends at a profile version the preview did not show.
- Focus never moves on an update (`05-accessibility-standard.md` §3.4).
- Announcements are throttled (§6.2).
- A `429` shows the wait message and keeps the last good preview.

**Heuristics.** Interrupt; race two inputs; repeat fast; slow the network; never trust a spinner;
compare the last preview with the submitted result.

**Risks.** A send of sizes the user never saw; previews flooding the server; an ungranted account's
sizing leaked in a rejection; a screen-reader user flooded with announcements.

**Data.** Core3 and Pair; BTCUSDT and ETHUSDT; the plan's reference intent RI at 64000.0; V01 and
V05 for the expected legs.

**Notes and debrief.**

| Field                                      | Entry |
| ------------------------------------------ | ----- |
| Tester, date, start and end (UTC)          |       |
| Build sha; stack; seed commit; latency     |       |
| Time on charter / on opportunity (%)       |       |
| Intent changes and rates exercised         |       |
| Findings (id, severity, step, evidence)    |       |
| Questions and spec gaps (plan §13 row)     |       |
| Not covered, and why                       |       |
| Debrief: what happened, results, obstacles |       |
| Cases to promote (E28-Q02, E28-X03)        |       |
