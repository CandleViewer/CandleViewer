# E39-K01 spike harness

Throwaway prototype for the daily-loss cap's PnL source and day boundary. **Not shippable** — see
`docs/plan/spikes/E39-K01.md` for the finding and its ADR-0047 draft section (E39-T03 #957 authors the ADR).

## What this is

A seeded, in-process simulator (stdlib Python, `Decimal` money, no clock reads in the table, no network) that
compares four daily-PnL sources and the hybrid against closed-PnL over a 3-day **synthetic** trail, and writes
`docs/plan/spikes/E39-K01-results.json`.

- **Every figure it prints is SYNTHETIC**, and so is the JSON (its `label` and `synthetic` keys say so). Its
  divergences evidence the model, never the venue.
- The trail keeps the documented field shapes of the transcribed Bybit fixtures and synthesises only values. It
  emits domain-level numbers (fills, funding, transfers, closed-PnL records), never Bybit payloads, keys or account
  ids.
- It lives only in this directory: never imported by `services/`, never placed in `packages/fixtures`, never
  imported by a test outside this directory. No coverage target applies (DoR §5.1).
- The demo leg (one demo account, 3 days) is the owner-run In Test item pending #843. The owner's demo key is never
  used here and no network call is made.

## Run it

```
python daily_pnl.py            # writes ../E39-K01-results.json and prints its sha256
python daily_pnl.py --check    # builds twice in-process and compares the bytes
python daily_pnl.py --latency  # read-latency micro-benchmark (not deterministic, not in the JSON)
uv run --project services/api python -m pytest -q docs/plan/spikes/E39-K01-harness/test_daily_pnl.py
```
