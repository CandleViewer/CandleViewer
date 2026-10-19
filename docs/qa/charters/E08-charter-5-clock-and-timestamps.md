# E08-C5 Charter: clock and timestamp behaviour across DST, host sleep and skew

- Ticket: E08-Q06 (#283) · Format: session-based test management · Date: 2026-10-19
- Tester: AI agent (hcl-worker-2, run8 aa6271c0). **Deviation (honest scope):** no real host sleep or resume, no WSL clock jump, no staging and no 90-minute human time box. The session was in-process: the clock and event-window suites and chaos s08 re-run on a virtual clock, E08 modules searched for local or naive time, and a throwaway probe of event timestamps, including an instant on a DST transition.
- No credentials used; no network.

## Charter

Explore clock and timestamp behaviour across DST, host sleep and skew to discover bar-boundary and ordering defects.

## Oracles (defined before probing)

- O1 Any local-time or naive `datetime` in E08 code (24 section 1.1 C3: UTC everywhere).
- O2 An exchange timestamp altered on the way in (a print at a DST transition instant must keep its exact UTC microseconds).
- O3 A host clock step that makes live prints look implausible (#1912), or a signature failure that retries on a stale offset (#1911).
- O4 Drift beyond the warn or block threshold that is not flagged.
- O5 `ts_ingest` that is not our receipt time (24 section 1.4: the difference is feed latency).

## Areas covered (in-process evidence)

| Probe                                        | Evidence                                                                                                                                                        | Result                                         |
| -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| Local or naive time in E08 modules           | search of `candleviewer/{ingestion,book,exchange,bus}` and `orderbook_wiring.py` for `datetime.now()`, `utcnow`, `localtime`, `mktime`, tz-less `fromtimestamp` | none (O1 ok)                                   |
| A print at the 2026-03-29 01:00Z DST instant | probe `p5`: `T` in ms becomes exactly `T * 1000` µs                                                                                                             | exact (O2 ok)                                  |
| Host step backwards and forwards             | `services/api/tests/unit/ingestion/test_event_window_clock.py` (14 cases, #1912)                                                                                | prints accepted on the corrected clock (O3 ok) |
| 10002 re-measure before the retry            | `services/api/tests/unit/exchange/bybit/test_rest_clock_resync.py` (#1911), chaos `test_s08_clock_skew.py`                                                      | ok (O3 ok)                                     |
| Drift thresholds                             | `services/api/tests/contract/bybit/test_contract_clock.py`; `infra/prometheus/alerts/clock_sync.yml` (warn above 500 ms, critical above 2000 ms)                | flagged (O4 ok)                                |
| `ts_ingest` on book events                   | probe `p5`: a parsed book delta has `ts_ingest == ts_event` (the exchange time)                                                                                 | known defect #3033 (P2, open)                  |

## Session metrics

- Time: about 8 minutes of agent time (09:47-09:48 UTC search and probe, suites re-run at 09:50), not a 90-minute human session.
- Tests re-run: clock guard, clock REST fetcher, event window, server time, 10002 re-measure, the clock contract pack and chaos s08: 73 passed, 2.0 s wall.
- Probes: 1 (`p5`), not promoted: its DST case passes and its `ts_ingest` case is already #3033.

## Findings

No new finding. The `ts_ingest` observation reproduces #3033 (P2, open): book events carry the exchange time as `ts_ingest`, so feed latency cannot be read off book events; recorded, not refiled. Bar boundaries themselves are built by E12 from `ts_event` in UTC and are out of this epic's code.

## Not probed (needs a real host or staging)

- A real host sleep and resume on WSL (24 section 2.8 notes WSL clocks drift after resume), and a chrony or NTP step on the backend host.
- Bar-boundary behaviour across a DST change in the E12 builders and the chart axis (E12, E11).
- The SCR-147 clock-drift warning (E08-TC-F05): E08-Q05, #282.

## Regression recommendation

None new: the existing clock, event-window and s08 suites are in the pack. When #3033 is fixed, its regression test joins `services/api/tests/unit/ingestion/` and so the pack.
