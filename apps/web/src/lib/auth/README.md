# src/lib/auth

Session/auth client helpers and RBAC guard hooks. Empty at E02-T04; the
route tree, auth/RBAC guards and env badge are E10's scope.

- `accessToken.ts` (#2712, ADR-0020): the access token, in memory only. It
  gives the bearer to same-origin `/api/v1/` calls (`apiFetch`, the bootstrap's
  `fetchJson`), refreshes at `expires_at - 60 s` under the `cv.auth.refresh` Web
  Lock, and is the WS client's `TokenSource` (`startShell`). A rotation revokes
  the token before it, so every bundle a tab receives is posted to its
  same-origin sibling tabs over the `cv.auth.token` BroadcastChannel (memory
  only), which hold it in place of an older one: one token per origin. A tab
  that forgets the token tells them too: each forgets it, and one that held it
  routes to sign-in. A logout's `2xx` forgets it but does not route its own
  tab: the sign-out UI routes that one to sign-in after `apiFetch` of the
  logout.
- `meCache.ts`: the `/me` claims the route guards read.

Known gaps, both server-side (#2712 changes no server code):

- ADR-0020 decision 5 has no rotation leeway: a spent `cv_refresh` presented
  again revokes the whole session family. A refresh leaves
  `cv.auth.refresh_sent_at` (a time, never the token) until an answer shows
  what became of the cookie, so a tab that closes or reloads mid-refresh (it
  lets go of the lock but not of its keepalive request), a lost answer and a
  `5xx` all leave it. The next holder waits up to 2 s for the cookie of a
  refresh sent less than 10 s before, then asks `GET /auth/session` (at once
  for an older one), where a spent cookie gets a `401` that revokes nothing.
  That narrows the window but cannot close it: the cookie of a refresh slower
  than that wait can still be presented again. A leeway for a token presented
  soon after its own rotation would close it.
- `POST /auth/refresh` refuses an idle-locked session with
  `refresh_token_invalid`, not the contract's `session_idle_locked`, so a
  locked tab goes to sign-in at its next refresh instead of to unlock, and so
  does every sibling tab that holds the token.
