# Profile fixtures (E28-T01 #905)

Synthetic `AccountProfile` documents (`docs/plan/24-internal-schemas.md` §9.2), one per sizing mode,
in the model's JSON form (fractions 0..1, `Decimal` as strings, `updated_at` in µs). They are not
recorded from an exchange and hold no credential, account UID or personal data; the ids are fixed
placeholders. Every one is trading-enabled, so each bounds every cap (SR-E28-01). Reused by E28-T03
(sizing) and E28-Q01 (black-box plan).

| File                  | Sizing                | Stop                         | Symbols              |
| --------------------- | --------------------- | ---------------------------- | -------------------- |
| `risk_based.json`     | 1 % of equity at risk | 20 ticks; ladder 50 %/1R, 2R | BTCUSDT, ETHUSDT     |
| `fixed_qty.json`      | 0.01 contracts        | 1 %; TP at 2R                | BTCUSDT              |
| `pct_equity.json`     | 5 % of equity         | 1.5 × ATR(14), 2 % fallback  | all, DOGEUSDT denied |
| `fixed_notional.json` | 1 000 USDT            | 50 ticks                     | `*USDT` pattern      |

The SOLUSDT 20x row (ruling B9, #906) is derived in code by `test_profile_validator.py`, never
stored: the recorded SOLUSDT row of `packages/fixtures/bybit/2026-10-05/rest/instruments_before.json`
(C-13.5) with one field patched, `leverageFilter.maxLeverage` from `100.00` to `20.00`. That file's
`_LISTED` derives its other rows from the same capture, each patched field named in `_PATCHES`.
