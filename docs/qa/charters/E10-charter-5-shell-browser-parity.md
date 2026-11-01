# E10-C5 Charter: shell and browser parity

- Ticket: E10-Q02 (#301) · Format: session-based, 45 min · Status: not yet run
- Mission: find behaviour the browser build and the Electron shell disagree on, where the shell is weaker.
- Oracles: I2 in the shell where the browser holds; a renderer that reaches Node or raw IPC; a CSP that differs from SR-112.
- Areas: the same routes and roles in both; window.open and navigation; the packaged build against `dist/`.
- Automated neighbours: `@plan-EL-1`..`@plan-EL-3`, `@plan-AB-5`, `@plan-RM-2`.
