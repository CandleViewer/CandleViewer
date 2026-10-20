# src/lib/auth

Session/auth client helpers and RBAC guard hooks. Empty at E02-T04; the
route tree, auth/RBAC guards and env badge are E10's scope.

- `accessToken.ts` (#2712, ADR-0020): the tab's access token, in memory only. It
  gives the bearer to same-origin `/api/v1/` calls (`apiFetch`, the bootstrap's
  `fetchJson`), refreshes at `expires_at - 60 s` under the `cv.auth.refresh` Web
  Lock, and is the WS client's `TokenSource` (`startShell`).
- `meCache.ts`: the `/me` claims the route guards read.
