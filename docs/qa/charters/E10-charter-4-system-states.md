# E10-C4 Charter: system states

- Ticket: E10-Q02 (#301) · Format: session-based, 60 min · Status: not yet run
- Mission: leave the shell in a state that hides a failure or keeps trading enabled with no live data.
- Oracles: I1 through every state; a takeover with no way back; Reconnecting that never resolves after the backend returns.
- Areas: backend restart mid-session; WS flaps; sleep and resume; slow liveness answers; the crash log after a forced renderer crash.
- Automated neighbours: `@plan-SS-1`, `@plan-SS-2`, `e2e/market-data/ws-harness.spec.ts`.
