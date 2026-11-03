# Engine E2E harness (E11-Q02, #444)

Its own Vite entry and build (`dist-engine-harness/`, never `dist/`). `pnpm --filter @candleviewer/web
check:harness-excluded` builds production and fails on any `__engine*` marker in `dist/`. Specs:
`../specs/e11-chart`; page object and fixtures: `../support/engine`. Run: `pnpm --filter
@candleviewer/web e2e:engine`.

- **Data:** seeded synthetic generators (provenance in `fixtures.ts`), served by `routeWebSocket` under
  the shared egress guard.
- **Waits:** public engine events or frames; no timers. `page.clock` cannot reach the engine's worker
  clock (Playwright fakes the page's timers only), so a flick dispatches one pointer move per frame with
  real timestamps and is asserted relative to the release.
- **Retries:** zero; a flaky spec is tagged `@flaky` (quarantine lane).
- **Coverage:** E2E adds none to the floors (C-9.4): recorded as "none".
- **No pixel asserts:** goldens are E11-T08 (#391).
