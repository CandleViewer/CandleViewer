# E28 black-box fixture set (E28-Q01, #904)

The fixtures of the E28 black-box plan (profiles, sizing and trade groups), for E28-Q02, E28-D07
and E28-X03, and the golden sizing vectors E28-T03 must meet. Every value is synthetic: no real
API key, UID, label or balance. Ids are fixed placeholders (`e28f0000-…`), labels `fx-e28-*`,
UIDs `928…`, the one address `example.invalid`; no `api_keys` row and no audit row is seeded
(below).

| File                         | What it holds                                                               | Symbol                              | Source                                                                                        | Date       | Env                | Redaction                |
| ---------------------------- | --------------------------------------------------------------------------- | ----------------------------------- | --------------------------------------------------------------------------------------------- | ---------- | ------------------ | ------------------------ |
| `seed.sql`                   | The world below, as rows of a migrated database                             | BTCUSDT                             | Synthetic; profiles and snapshots from `profiles.json` through the real model                 | 2026-10-24 | demo and live rows | none needed (synthetic)  |
| `profiles.json`              | P-RISK, P-QTY, P-PCT, P-NOTIONAL: each a frozen profile, fields set (below) | Each profile's allow-list (below)   | `services/api/tests/fixtures/profiles/*.json` (frozen, unchanged)                             | 2026-10-24 | none               | none needed (synthetic)  |
| `instruments.json`           | The capture's rows: three the vectors use, and LUNAUSDT; patches: none      | BTCUSDT, ETHUSDT, SOLUSDT, LUNAUSDT | `packages/fixtures/bybit/2026-10-05/rest/instruments_before.json` (documented shape, #1778 A) | 2026-10-05 | demo host          | none needed (no account) |
| `golden_sizing_vectors.json` | 14 vectors: inputs, expected results and the rule each exercises            | BTCUSDT, ETHUSDT, SOLUSDT           | QA, by hand from US-PROF-002 and 24 §9.3                                                      | 2026-10-24 | none               | none needed (synthetic)  |
| `sizing_recomputation.md`    | Each vector derived step by step, with its rules and readings               | As above                            | As above                                                                                      | 2026-10-24 | none               | none needed              |
| `sizing_recomputation.csv`   | The spreadsheet: one row per vector, every intermediate value               | As above                            | As above                                                                                      | 2026-10-24 | none               | none needed              |
| `README.md`                  | This file                                                                   | —                                   | —                                                                                             | 2026-10-24 | none               | none needed              |

## Loading

Into a clean test database (named `test` or `*_test`; the seed refuses any other) migrated to
head, from the repository root, once:

```sh
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f tests/fixtures/e28/seed.sql
```

`$DATABASE_URL` is a libpq URL (`postgresql://…`), not the app's `postgresql+asyncpg://` DSN. One
transaction: a failure writes nothing, and so does a second run, whose first row's key is taken.
SQL, as #904 asks, rather than a loader: its computed values (each profile in stored units, each
leg's profile snapshot) were made once through the real model. `test_e28_fixture_set.py` checks,
with no database, every row's columns against the models, each stored profile against
`profile_values` and each leg's snapshot against its profile;
`tests/integration/accounts/test_e28_fixture_seed_pg.py` loads the seed into Postgres.

### Regenerating the seed's computed rows

For each `profiles.json` entry, take `p = AccountProfile.model_validate({**frozen, **set})`
(`candleviewer.accounts.profiles`). Then:

- its `account_profiles` row is `profile_values(p)`, each `Decimal` as a plain string
  (`format(d, "f")`), a ladder rung as `{"pct": …, "r": …}` in JSON numbers and an empty list as
  `null`; with `id` and `exchange_account_id` from `p.profile_id` and `p.account_id`, `created_at`
  and `updated_at` from `p.updated_at`, and the Owner as `created_by` and `updated_by`;
- a leg's `profile_snapshot` is `p.model_dump(mode="json")`, as `LegDraft` stores it (24 §9.1);
  its `target_qty`, `resolved_sl_price` and `risk_usd` are its vector's (V01 for E28-A, V05 for
  E28-C), and its `resolved_leverage` is `p.leverage`.

Each row is one line of its table's JSON array in `seed.sql`; the unit test then holds it to the
model.

## The world

| Handle                      | What it is                                                                                   |
| --------------------------- | -------------------------------------------------------------------------------------------- |
| E28-LIVE-MAIN, E28-LIVE-SUB | Live main account and its sub-account; never armed; their bootstrap `Default` profile, inert |
| E28-A                       | Demo main account; P-RISK (risk-based, TP ladder); holds the open BTCUSDT position           |
| E28-B                       | Demo sub-account; P-QTY (fixed quantity); its key self-check failed: disarmed                |
| E28-C                       | Demo sub-account; P-PCT (percent of equity, all symbols but DOGEUSDT)                        |
| E28-D                       | Demo sub-account; P-NOTIONAL (fixed notional) with the empty allow-list                      |
| Core3, Pair                 | Group definitions: E28-A, B, C (2 of 3 ready) and E28-A, C (2 of 2 ready)                    |
| G-CORE3, G-PAIR             | One BTCUSDT limit buy fired from each, cancelled unfilled; legs on E28-A (V01), E28-C (V05)  |
| Owner                       | `fx-e28-owner`, who made them; its hash verifies no password                                 |

- **Six accounts, two main: a deviation.** #904 asks for one main and five subs, four demo and two
  live. Its text predates `trg_ea_env_parent`, which keeps a sub-account in its parent's
  environment, so two environments need two mains, as in `packages/fixtures/accounts/accounts.json`.
- **Documented-shape instruments: a deviation.** #904 asks for real instrument values. The
  instruments come from the 2026-10-05 capture, documented-shape under exception #1778 A, not a
  live recording; a live `instruments-info` recording, together with DOGEUSDT's, is one follow-up.
- **The profiles.** Each is its frozen original with these fields set, and no others:
  - all four: a new `profile_id` and `account_id` (its E28 account), and version 1, a new row's
    (P-RISK's was 3, P-PCT's 2);
  - P-RISK: `risk_pct_equity` 0.01 → 0.005, `sl_offset_value` 20 → 1200 ticks and the name
    `Risk 0.5%`: the story's 0.5 % and 120 USDT stop on BTCUSDT (V01); allows BTCUSDT, ETHUSDT;
  - P-QTY: `is_default` false → true, as each E28 profile is its account's default; allows
    BTCUSDT;
  - P-PCT: `leverage` 3 → 10, `max_leverage_cap` 5 → 10 (never below the leverage) and
    `max_position_pct_equity` 0.25 → 1: the story's 5 % at 10x (V05), which 0.25 would cut to
    0.039 (Q3); allows every symbol but DOGEUSDT;
  - P-NOTIONAL: `allowed_symbols` `["*USDT"]` → `[]`, the empty allow-list: it allows nothing.
- **The empty allow-list.** P-NOTIONAL has no allow-list and `all_symbols` false, so it allows no
  symbol at all (US-PROF-003 "Empty list allows nothing", D11), and the profile is flagged so.
- **The failing self-check** is where the self-check's force-disable writes it: E28-B has
  `trading_enabled` false and `policy_disarm_code` `key_ip_whitelist_mismatch`, its record still
  owed (`policy_disarm_audited_at` NULL; 21 §3.2.1), so the next pass writes it. No `api_keys`
  row is seeded: one would be KEK evidence that opens under no KEK (21 §3.2.3a), and the #2893
  transport refuses a stored key id outside `fixture-<scenario>-NNNN`. A suite imports its keys
  through the API, as E27's do.
- **The open position** lives in `positions` (E29's position store, which the matrix reads):
  E28-A's BTCUSDT long of `packages/fixtures/accounts/open_position_btcusdt_5x_sl`, field for
  field, so a stack serving that overlay agrees with it.
- **The defaults.** Each demo account's bootstrap `Default` is soft-deleted and its E28 profile
  inserted as the default, so `default_binding_version` stays 1 (21 §3.2.4); no tag exists yet.
  The six bootstrap `Default` profiles (`trg_ea_default_profile`; the live accounts' two, live, and
  the demo accounts' four, soft-deleted) have random ids, and a time the seed leaves out, such as
  `users.created_at`, is the load time: a consumer finds a bootstrap profile by its account.
- **No audit row.** The audit log is append-only and hash-chained, so the seed writes none: the
  accounts, profiles and groups have no record behind them.
- **Symbols.** BTCUSDT, ETHUSDT, SOLUSDT and LUNAUSDT are the capture's rows, unchanged. #904
  names DOGEUSDT, which no capture holds: it appears only where no instrument row is read, as
  P-PCT's denied symbol. A recorded DOGEUSDT row (the recorder tool, C-13.5) is the follow-up
  above, never a patched or invented row.

## The vectors

Each vector names its profile (`profiles.json`, plus any fields it sets), its intent, wallet and
market inputs, and its expected results; decimals are strings and compare by value. The readings
the text left open are in `sizing_recomputation.md`; E28-T03's values are compared with these when
it lands.

| Vector | Profile    | What it pins                                                                |
| ------ | ---------- | --------------------------------------------------------------------------- |
| V01    | P-RISK     | Risk-based, the story's example: a ticks stop, the lot floor, the TP ladder |
| V02    | P-RISK     | The fee-aware correction, at a 0.00055 taker fee                            |
| V03    | P-RISK     | A quantity of exactly the minimum lot                                       |
| V04    | P-RISK     | One step below the minimum lot: skipped                                     |
| V05    | P-PCT      | Percent of equity, the story's example: an ATR stop and the initial margin  |
| V06    | P-PCT      | No ATR: the fallback stop, rounded away from entry                          |
| V07    | P-QTY      | Fixed quantity; a short's percent stop, rounded up; a 2R take-profit        |
| V08    | P-QTY      | Under the instrument's minimum notional: skipped                            |
| V09    | P-RISK     | The ladder's rounding remainder, taken by the last rung                     |
| V10    | P-NOTIONAL | The day's remaining loss room, which clamps fixed notional to 4.000         |
| V11    | P-PCT      | Extreme equity: the instrument's `max_order_qty` binds                      |
| V12    | P-NOTIONAL | The empty allow-list: `symbol_not_allowed`                                  |
| V13    | P-RISK     | `max_leverage_cap`, then insufficient margin (the cap's part rests on Q2)   |
| V14    | P-NOTIONAL | Fixed notional's own formula, with no cap binding                           |

So V14 pins the `fixed_notional` formula, and V10 only the day's room: any raw quantity of 4 or
more gives V10 the same result.

**`binding_cap`** is QA's label for the clamp that binds, as the step check keys its caps. A
sizer's own names compare by this mapping, not verbatim:

| Label        | The spec's field                                                           |
| ------------ | -------------------------------------------------------------------------- |
| `leverage`   | `max_leverage_cap`                                                         |
| `pct_equity` | `max_position_pct_equity`                                                  |
| `notional`   | `max_position_notional`                                                    |
| `daily_loss` | The tighter of `max_daily_loss` and `max_daily_loss_pct` × equity          |
| `instrument` | `max_order_qty` for a limit order (`max_mkt_order_qty` for a market order) |
| `none`       | No clamp binds                                                             |

**Not covered here; proposed for E28-T03's vector set:**

- a binding `max_position_notional` (T03 AC 8's example) or `max_position_pct_equity`;
- `symbol_denied`, `profile_disabled` and a market order (`max_mkt_order_qty`, and a reference
  price that is not the order's: T03's mark price, or 24:2512's mid or last price);
- a short with a ticks or an ATR stop;
- a plain insufficient margin: a low available margin, with no cap binding;
- a take-profit in ticks, percent or ATR: `tp_offset_unit` allows them (24:2410), but §9.3.3
  resolves only `r_multiple` (24:2560), so V10's and V14's 100-tick take-profits are unpinned.
