# src/lib/auth

Session/auth client helpers and RBAC guard hooks. Empty at E02-T04; the
route tree, auth/RBAC guards and env badge are E10's scope.

- `accessToken.ts` (#2712, ADR-0020): the access token, in memory only. It
  gives the bearer to same-origin `/api/v1/` calls (`apiFetch`, the bootstrap's
  `fetchJson`), refreshes at `expires_at - 60 s` under the `cv.auth.refresh` Web
  Lock, and is the WS client's `TokenSource` (`startShell`). A rotation revokes
  the token before it, so every bundle a tab receives is posted to its
  same-origin sibling tabs over the `cv.auth.token` BroadcastChannel (memory
  only), which hold it in its place: one token per origin. A tab that forgets
  the token tells them to forget it too. A logout's `2xx` forgets it but routes
  nowhere: the sign-out UI routes to sign-in after `apiFetch` of the logout.
- `meCache.ts`: the `/me` claims the route guards read.

Known gaps, both server-side (#2712 changes no server code):

- ADR-0020 decision 5 has no rotation leeway: a spent `cv_refresh` presented
  again revokes the whole session family. A tab that closes or reloads lets go
  of the lock but not of its keepalive refresh, so it leaves
  `cv.auth.refresh_sent_at` (a time, never the token): the next holder waits
  up to 2 s for that refresh's cookie, then asks `GET /auth/session`, where a
  spent cookie gets a `401` that revokes nothing. That narrows the window but
  cannot close it: the cookie of a refresh slower than that wait, or of one
  whose answer was lost and that was sent more than 10 s before the next
  refresh, can still be presented again. A leeway for a token presented soon
  after its own rotation would close it.
- `POST /auth/refresh` refuses an idle-locked session with
  `refresh_token_invalid`, not the contract's `session_idle_locked`, so a
  locked tab goes to sign-in at its next refresh instead of to unlock.
