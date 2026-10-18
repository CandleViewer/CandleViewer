# ADR-0038 — Desktop shell to backend: the backend address, the `app://` allowed origin, CORS and the CSRF token path (#3519)

- Status: **proposed**. Decision deadline: before S1, the contract slice, merges; owner decisions D1 to D6
  (below) are due by then (`docs/plan/27-adrs/README.md:5`). Nothing here is binding yet, and this PR
  changes no product code, no CONSTITUTION rule and no accepted ADR.
- Date: 2026-10-18
- Deciders: Owner (`@basiltt`); the Security engineer through the `security-review` label on #3519 (C-10.2).
  To consult before S6: the owner of #2712 (SPA access-token client), on the shared backend-origin rule
  (decision 3e).
- Numbering note: 0031 is reserved by E45-K01 (`ADR-0031-resilience-and-chaos`, not on `main`) and 0037 is
  the last on `main`. The E42 admin model says the E42-T06 ADR takes the next free number when it is
  written (`docs/security/threat-models/e42-admin.md:61-64`), so this record takes 0038 and that one the
  next free number. The model's "ADR-0038 at the time of writing" (`:63-64`) is then out of date (F4).
- Related: #3519 (this record is its slice 0), #3410 and #3529 (the `app://` load path), #3411 and #3609
  (merged: `resolveDevServerUrl`), #3600 (merged: the E10-X02 gate asserts the `app://` CSP and window URLs
  at runtime), #2712 (SPA access-token client), #2711 (TOTP step on the login screen), #2490 (real-backend
  auth E2E); ADR-0010, ADR-0011 (proposed: the shell is built on Electron meanwhile), ADR-0020; SR-006,
  SR-012, SR-041, SR-042, SR-049, SR-111, SR-112, SR-113, SR-173, SR-174, SR-181, SR-183.
- Evidence: every `file:line` holds on `main` at `474f36339`. Unless a full path is given, web paths are
  under `apps/web/src/`, shell paths under `apps/desktop/src/` and backend paths under
  `services/api/candleviewer/`.

## Context and problem statement

Since #3410 the shell serves the web app from `app://candleviewer` (`main/appProtocol.ts:12-16`). The scheme
is `standard` and `secure`; it is not granted CORS or renderer `fetch()` of `app:` URLs
(`main/appProtocol.ts:18-29`).

**The web app derives its backend from its page location.** REST calls use page-relative `/api/v1` paths at
eleven sites in nine files: `features/auth/authApi.ts:5`, `shell/bootstrap/bootstrap.ts:55,59,63`,
`lib/http/csrfFetch.ts:25`, `features/invites/inviteApi.ts:5`, `features/a11y-preferences/prefsApi.ts:4`,
`features/onboarding/checklistApi.ts:19`, `routes/StepUpGate.tsx:52`, `keymap/audit.ts:52` and
`lib/telemetry/aggregator.ts:127`. The WS URL is built from `window.location` (`main.tsx:17-21`). On
`app://candleviewer` these resolve to the scheme itself or to a host named `candleviewer`, so no request
reaches the backend.

**Backend, today:**

- One SR-042 allow-list, `CV_ALLOWED_ORIGINS` (`settings.py:336-342`, `668-672`), each entry validated as
  a serialised origin at startup (`settings.py:175-193`, `1042-1055`). It feeds the CSRF guard
  (`api/csrf.py:213-227`, mounted at `app.py:2072-2081`), the cookie refresh (`api/sessions.py:367-375`,
  `app.py:1316`) and the WS upgrade (`ws/lifecycle.py:256-278`, `app.py:1381`). `app://candleviewer` is
  already a valid entry: `is_serialised_origin("app://candleviewer")` returns true (checked 2026-10-18).
  The dev compose file lists only the Vite origins (`infra/compose/docker-compose.dev.yml:19-22`).
  Production leaves the list empty, which fails closed.
- No CORS layer. The stack is HttpDuration → Correlation → MeshOnly → Csrf → IdleLock → the inner guards
  (`app.py:2066-2095`), and the Correlation → MeshOnly → Csrf adjacency is pinned by
  `services/api/tests/security/auth/test_csrf_double_submit.py:452-455`. A cross-origin page can read no
  response, and its preflighted requests (JSON bodies, `Authorization`, `X-CSRF-Token`) fail.
- CSRF is double-submit: the header and the cookie must both be present and equal, and the token's MAC must
  verify for the session the server resolves itself (`api/csrf.py:454-478`; contract
  `docs/plan/22-api-openapi.yaml:99-140`). The `__Host-cv_csrf` cookie is
  `Secure; SameSite=Strict; Path=/` and not HttpOnly (`api/csrf.py:161-165`). Three sites issue it: MFA
  verify (`api/auth.py:479`), refresh (`api/sessions.py:1035`), and `GET /auth/session`, which re-issues
  only when the cookie is absent or does not verify (`api/sessions.py:1052-1055`).
- The access token comes back in the response body and is memory-only (`api/auth.py:469-476`,
  `api/sessions.py:413-420`; ADR-0020 decision 1). `cv_refresh` is
  `HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth` (`api/sessions.py:378-387`). `GET /me` accepts
  only the bearer (`api/me.py:146-148`, `179`). `GET /auth/session`, unlock and logout accept the
  `cv_refresh` cookie when no live access token is sent (`api/sessions.py:763-782`; contract
  `22-api-openapi.yaml:157-172`).

**Web client, today.** It reads the CSRF cookie from `document.cookie` (`lib/http/csrfFetch.ts:31-41`). It
attaches the header only on the page's own origin (`csrfFetch.ts:49-56`, `87`) and recovers through
`GET /auth/session` with `credentials: "same-origin"` (`csrfFetch.ts:93-106`). The SPA holds no bearer
yet: #2712 adds one and limits it to same-origin URLs. The TOTP step is #2711. After sign-in the login
screen does a full navigation (`features/auth/LoginScreen.tsx:56-57`).

**Shell, today.** `buildCsp` reads `CV_BACKEND_ORIGIN`, checks only the parsed hostname against the loopback
set and silently falls back to `http://127.0.0.1:8000` (`main/csp.ts:12-13`, `23-53`). Checked with
Node's `URL` on 2026-10-18: `foo://127.0.0.1:8000` gives `connect-src 'self' null null`;
`ws://127.0.0.1:8000` is taken as the HTTP origin; userinfo, path and query are silently dropped. That is
the #3519 note. The CSP is built once at startup (`main/index.ts:266-271`), and navigation is confined to
the app origin (`main/index.ts:80-100`, `182-197`; SR-113). The preload exposes three functions over three
allow-listed channels (`preload/index.ts:21-25`, `preload/allowList.ts:11-15`). The web
`CvBridge` type declares twelve (`shell/ElectronShellAdapter.ts:21-34`).

**Policy already written.**

- SR-042 lists an "`app://`-style Electron origin". It requires CORS as an explicit allow-list with
  credentials, never `*` and never origin reflection (`docs/plan/04-security-program.md:744`).
- SR-112 names `connect-src 'self' https://<tailnet-host> wss://<tailnet-host>` for packaged builds
  (`04-security-program.md:819`), but the shell implements loopback only.
- SR-049 allows plain HTTP only on `127.0.0.1`, for the host-local shell (`04-security-program.md:761`).
- ADR-0010 decisions 2 and 3 (`ADR-0010-auth-and-rbac.md:33-34`) and SR-012 and SR-041
  (`04-security-program.md:682`, `743`) make `SameSite=Strict` part of the session and CSRF controls.

**The cross-site cookie problem.** `app://candleviewer` and `http://127.0.0.1:8000` are different sites:
both the scheme and the host differ. Under the same-site cookie rules (RFC 6265bis), a browser neither
stores a `SameSite=Strict` or `Lax` cookie from the response to a cross-site subresource request nor sends
one on such a request. `document.cookie` on the `app://` page shows only that page's own cookies. So with
today's attributes the desktop page can hold neither `cv_refresh` (it could not refresh its 12-minute token
or survive a reload) nor the CSRF cookie, and it cannot read the token. Making the address configurable is
necessary but not sufficient.

## Decision drivers

1. One source for the backend address, owned by the main process, so the CSP and the page never disagree.
2. No weakening for the browser deployment: `SameSite=Strict`, the SR-042 check and the SR-041
   double-submit stay as they are for every origin except the desktop's.
3. One server-side CSRF check for every client: no bearer exemption and no header-only mode.
4. The long-lived refresh credential never becomes readable by script (SR-012; ADR-0020 decision 1).
5. The `app://` handler stays a read-only static-file server (SR-174).
6. Contract first (C-6.1); slices of at most 400 changed lines (C-4.8). No slice changes what an unlisted
   origin or a same-origin browser page sees: the backend slices change cookie attributes for the
   `app://candleviewer` origin only and add CORS answers and response headers for listed origins only,
   and the web slices act only when `window.cv` is present. So no flag is needed (C-4.13). The one
   widening, read access for every listed origin, is the purpose of S3 (see Consequences).
7. The browser-engine behaviour this design relies on is pinned by a kept test, not assumed.

## Considered options

- **A. Direct cross-origin calls from the `app://` page (chosen).** The shell provides the address, the
  backend answers CORS for listed origins, the desktop origin alone gets cross-site cookies, and the CSRF
  token is also delivered in a response header.
- **B. A main-process relay.** The `app://` handler forwards `/api/*` to the backend, so REST becomes
  same-origin. Rejected:
  - SR-174 requires a read-only static-file handler that changes no state.
  - The scheme would need fetch (and likely CORS) privileges, widening `APP_SCHEME_PRIVILEGES`, which tests
    and the hardening gate pin (`main/appProtocol.ts:18-29`; SR-174, `04-security-program.md:838`).
  - Every order would pass through the most privileged process.
  - A protocol handler cannot carry the WS, so the WS would stay cross-origin anyway.
- **C. The backend serves the web app** and the shell loads it from the backend's origin. Rejected: it
  reverses #3410 (SR-174, SR-173), makes the shell render remote content, ties the desktop UI to the
  backend's deploy, and leaves nothing to render while the backend is down.
- **D. A non-cookie desktop client**, holding a refresh token taken from response bodies.
  `POST /auth/refresh` already accepts `RefreshRequest.refresh_token` (`22-api-openapi.yaml:14299-14303`,
  `api/sessions.py:921-928`). Rejected:
  - It puts the long-lived credential in memory that script can read, against SR-012 and ADR-0020
    decision 1.
  - Every reload would lose the session, and sign-in itself reloads (`LoginScreen.tsx:57`).
  - The `cookie_auth:false` flag that one description mentions (`22-api-openapi.yaml:14204`) is defined
    by no request schema; see F1.
- **E. Header-only CSRF for the desktop** (a synchronizer token checked against the bearer's session).
  Rejected: a second server code path, and one client class would lose SR-041's double-submit. It also does
  nothing for `cv_refresh`, which needs cross-site cookies regardless.
- **F. The main process rewrites `Set-Cookie` or attaches cookies itself** (through `webRequest`).
  Rejected: the shell would handle credential headers across trust boundary B4
  (`docs/plan/20-architecture.md:208`), and the cookie jar would end up holding the same cross-site
  cookies as in option A.

## Decision outcome (proposed): option A

### 1. The backend address: how the page learns it and how it is validated

- **1a. One input, read once.** `CV_BACKEND_ORIGIN` (the existing variable, `main/csp.ts:37`) is resolved
  once at startup by a new pure function, `resolveBackendEndpoint(raw, isPackaged)` in
  `main/backendEndpoint.ts`. It returns `{ kind: "ok", httpOrigin, wsOrigin }` or
  `{ kind: "refused", reason }`. `buildCsp` takes that result instead of reading the environment, so
  `connect-src` and the page's address are always the same value.
- **1b. Validation: refuse, never strip and never fall back.**
  - Unset or empty means the default, `http://127.0.0.1:8000` (`main/csp.ts:12`).
  - A value with any character outside printable ASCII is refused before parsing, because the URL parser
    silently drops tabs and newlines. `resolveDevServerUrl` already does this for the dev-server URL
    (`main/devServer.ts:16-20`, `52`).
  - The value must parse as a WHATWG URL, and its protocol must be exactly `http:` or `https:`. This refuses
    `ws:`, `app:`, `file:` and every non-special scheme, so the `null` origin of the #3519 note cannot
    occur.
  - No username or password, no path other than `/`, no query and no fragment.
  - The parsed, normalised hostname is checked, and the normalised origin is what is used:

    | Build            | `http:` hosts                 | `https:` hosts              |
    | ---------------- | ----------------------------- | --------------------------- |
    | Unpackaged (dev) | `127.0.0.1`, `localhost`      | `127.0.0.1`, `localhost`    |
    | Packaged         | `127.0.0.1` only (SR-049, D5) | `127.0.0.1` only (until D1) |

  - The WS origin is derived, never configured: `http:` gives `ws:` and `https:` gives `wss:`, with the
    same host and port.

  Plain `http:` is accepted for loopback hosts only, in every build. A non-loopback host (SR-112's tailnet
  host) is refused in every build until owner decision D1 records it, and even then only with `https:`,
  so its WS is `wss:`. The `app://` page is a secure context, and SR-049 requires TLS off loopback. D1's
  record is the explicit `connect-src` widening the ticket asks for. "Packaged" is `app.isPackaged`,
  passed in as `resolveDevServerUrl` takes it (`main/index.ts:147`, `main/devServer.ts:42-49`). The dev
  hosts are the closed set `devServer.ts` uses (`main/devServer.ts:9-14`), so the shell has one loopback
  set. `[::1]`, which `csp.ts` accepts today (`main/csp.ts:13`), is dropped, as #3609 dropped it for the
  dev server.

- **1c. A refused value fails closed.** There is no fallback to the default: a silent fallback could connect
  a trader to a different backend from the one configured. `connect-src` becomes `'self'` alone, and the
  bridge reports the refusal. The main process logs one line with the reason code only, never the value,
  which may carry credentials (C-12.6, SR-006). The web app treats it as an unreachable backend (the
  sign-in screen's existing `unreachable` outcome, `features/auth/authApi.ts:17`); there is no new UI.
- **1d. Delivery.** A read-only bridge function, `window.cv.backendEndpoint(): Promise<BackendEndpoint>`,
  over a new allow-listed channel `cv:backend:endpoint` (`preload/allowList.ts`; SR-111, SR-181). It takes
  no arguments, and the handler returns the frozen startup value.
  - The type is
    `{ kind: "ok"; httpOrigin: string; wsOrigin: string } | { kind: "refused" }`. The refusal reason stays
    in the main-process log and does not cross the bridge. S5 pins the type in the preload's typing, S6
    adds the same declaration to the web `CvBridge` (`shell/ElectronShellAdapter.ts:21-34`), and each side
    tests against it.
  - The handler answers only the main window's top frame on the app origin (the dev-server origin when
    unpackaged), checked through `event.senderFrame`. The three existing handlers do not check their
    sender (`main/index.ts:250-254`); this one does.
  - The web app re-validates the shape (`http(s)` origin, the matching `ws(s)` origin, the same host and
    port) and treats anything else as refused, so both sides validate (SR-111).
- **1e. Use in the web app.** When `window.cv` is present (the signal `createShellPort` already uses,
  `shell/index.ts:56-60`), the app awaits `backendEndpoint()` before `startShell`. REST URLs become
  `httpOrigin + "/api/v1/..."`, and the WS URL becomes `wsOrigin + "/api/v1/ws"` (the
  `docs/plan/23-ws-protocol.md` §2.1 path). Without `window.cv` (the browser deployment) nothing changes.
  One module, `lib/http/backend.ts`, owns this, and the eleven call sites go through it.
  - The WS URL also feeds the E17-T04 client in `lib/ws`, which is not yet wired into `main.tsx`
    (`lib/ws/README.md:3-5`). Its shared worker opens the socket at the `wsUrl` a tab sends in its connect
    message, and `isSocketAllowed` admits `wss:` anywhere and `ws:` on loopback only
    (`lib/ws/worker/portHost.ts:85-95`, `435-444`), which every accepted endpoint satisfies. That `wsUrl`
    comes from `lib/http/backend.ts` too: whichever of S6 and the E17-T04 wiring slice lands second routes
    it there, so there is still one derivation.
- **1f. The dev server.** With `CV_DEV_SERVER_URL` the page still uses the bridge, so dev runs the desktop
  code path. But the Vite origin and the backend are the same site (`127.0.0.1` on different ports), so
  `Strict` cookies work there. Dev therefore does not reproduce the `app://` cookie behaviour, and the proof
  (S9) must load `app://`.

### 2. The backend accepts `app://candleviewer` (SR-042) for HTTP and WS

- **2a. Admission by configuration only.** Operators add `app://candleviewer` to `CV_ALLOWED_ORIGINS`.
  There is no code default, and the empty default stays fail-closed (`settings.py:336-342`). Once it is
  listed, the existing checks admit the desktop unchanged: unsafe HTTP (`api/csrf.py:213-227`), the cookie
  refresh (`api/sessions.py:367-375`) and the WS upgrade (`ws/lifecycle.py:256-278`). Per D4, the dev
  compose default gains the entry. The runbook (`docs/ops/runbooks/auth-rbac.md:738-743`) and
  `apps/desktop/README.md:53-57` are updated.
- **2b. CORS, from the same allow-list.** Starlette's `CORSMiddleware` (part of Starlette, so no new
  dependency), configured as follows:
  - `allow_origins` is `Settings.allowed_origin_set`, with credentials on, no regex and never `*`.
  - Methods: `GET, HEAD, POST, PUT, PATCH, DELETE`.
  - Allowed request headers: `Authorization`, `Content-Type` and the contract's header parameters, today
    `X-CSRF-Token`, `Idempotency-Key`, `If-Match` and `X-Reauth-Password` (`22-api-openapi.yaml:1216`,
    `12634-12661`).
  - Exposed response headers: every response header the contract declares, both in `components.headers`
    (`RateLimit-*`, `Retry-After`, `ETag`, `Idempotency-Replayed`; `22-api-openapi.yaml:12914-12929`) and
    inline on operations (for example `Server-Timing` on `POST /auth/login`, `:957`; `Content-Disposition`
    and `Repr-Digest` on the audit export, `:8926`, `:8932`; `Content-Disposition` on the backup
    download, `:9923`). The CORS-safelisted headers and `Set-Cookie`, which script never reads, are left
    out. Added to them: `X-Correlation-Id` (`observability/correlation.py:19`) and `X-CSRF-Token`
    (decision 3). `Retry-After` matters because the lockout screen reads it
    (`features/auth/authApi.ts:32-37`) and it is not a CORS-safelisted header.
  - `max_age` of 600 s.

  A contract test walks every operation's request header parameters and response headers, inline and
  referenced, and derives both lists from them, so they cannot drift. Checked in-process with Starlette
  1.7.0, the locked version (`services/api/uv.lock:2767-2768`):
  - a listed `app://candleviewer` gets its exact origin back, with credentials and `Vary: Origin`;
  - an unlisted origin's preflight gets 400 and no allow-origin header;
  - a simple request from an unlisted origin still gets `Access-Control-Allow-Credentials` and
    `Access-Control-Expose-Headers`, but no `Access-Control-Allow-Origin`, so the browser withholds the
    response. S3's negative tests therefore assert that `Access-Control-Allow-Origin` is absent, not that
    every CORS header is.

- **2c. Placement.** The new layer goes inside the CSRF guard: HttpDuration → Correlation → MeshOnly → Csrf
  → Cors → IdleLock → the inner guards → routes.
  - The pinned adjacency still holds (`test_csrf_double_submit.py:452-455`), and off-mesh traffic never
    reaches the new layer.
  - Preflights are `OPTIONS`, a safe method (`api/csrf.py:432-434`), so they pass the guard and are answered
    inside the mesh.
  - The guard's own token refusals (`403 csrf_token_invalid`: missing, mismatch, bad MAC, wrong session) add
    the allow-origin, allow-credentials, exposed-headers and `Vary: Origin` headers when the request's
    `Origin` is listed. The page can then read the refusal and run its recover-once path. A `cross_origin`
    refusal never carries them.
  - **One policy, one origin match.** S3 builds a single frozen CORS policy value from
    `Settings.allowed_origin_set` (`settings.py:668-672`, exact match after its trailing-`/` trim) and the
    contract-derived header lists. The CORS layer is configured from it, and the guard's refusals take
    their headers from it through one function, so there is no second origin match. A parity test checks
    that a refusal for a listed origin carries exactly the headers the CORS layer adds to a simple
    response, and that an unlisted origin gets no `Access-Control-Allow-Origin` from either.
  - The alternative placements are under "Why not the alternatives".
- **2d. What the Origin header proves, and what it does not.** A browser engine sets `Origin` to the
  requesting page's origin, and web content cannot set it. So no page in a user's ordinary browser can
  present `app://candleviewer`, and the exact entry admits no other `app://` host. It does not identify the
  client: any non-browser program, or another local Chromium-based app that registers the same scheme and
  host, can send the same value. The allow-list therefore remains an anti-CSRF and anti-hijacking control,
  not client authentication. Access still needs a password and TOTP to get a bearer (ADR-0010, ADR-0020),
  and every unsafe request still needs the session-bound token. On the shell side, only the shell's own
  pages run in its session: navigation and new windows are confined to the app origin (SR-113,
  `main/index.ts:80-100`, `182-197`), and `default-src 'self'` covers frames (`main/csp.ts:42`).

### 3. The CSRF token path for the `app://` page (the double-submit stays)

- **3a. The server check does not change.** Header and cookie present, equal in constant time, and a MAC
  bound to the session the server resolves (`api/csrf.py:454-478`; `22-api-openapi.yaml:115-120`).
- **3b. New: the token in a response header.** Every response that issues a new `__Host-cv_csrf` value
  (not an expiry) also carries the same value in an `X-CSRF-Token` response header, in the request
  header's format (`<nonce>.<mac>`, `components.parameters.CsrfToken`). It is set inside
  `set_csrf_cookie` (`api/csrf.py:161-165`), which every issuing site calls (`api/auth.py:479`,
  `api/sessions.py:1035`, `1055`), so no issuing path can miss it. `GET /auth/session` always carries the
  current session's token: re-issued as today when the cookie is absent or does not verify
  (`api/sessions.py:1052-1055`), otherwise the verified cookie value.
  - The header is the same in every deployment: a same-origin page can read the cookie anyway, and CORS
    hides the header from unlisted origins.
  - The value is a session-bound MAC, not a credential (`api/csrf.py:162-164`). The redaction filter
    (SR-006) adds this response header to its list. Any reverse proxy or access log in front of the
    backend that records response headers must treat it as sensitive too (SR-006): such tools often
    leave out `Set-Cookie` by default, but not custom headers. The runbook update in S8 says so.
  - Every response that carries it is `Cache-Control: no-store`, as `GET /me`'s responses already are
    (`api/me.py:76`).
- **3c. The client.** Where the page can read the backend's cookie (the browser deployment, same origin),
  nothing changes: the cookie is read at send time (`csrfFetch.ts:31-41`). Where it cannot (the desktop
  page):
  - the token lives only in memory, never in web storage;
  - it is updated from every backend response that carries the `X-CSRF-Token` header;
  - it is shared with the app's other same-origin windows over a `BroadcastChannel`;
  - after a reload the page calls `GET /auth/session` to get it (the session is identified by
    `cv_refresh`, `api/sessions.py:763-782`), then `POST /auth/refresh` for a bearer.
- **3d. Recovery.** On `403 csrf_token_invalid` the desktop page calls `GET /auth/session`, takes the
  header, and retries once if the token changed. This is the multi-tab rule (`22-api-openapi.yaml:129-131`)
  with a different token source. A second refusal is shown to the user.
- **3e. One "backend origin" rule.** The `X-CSRF-Token` header and `credentials: "include"` go only to
  URLs on the configured backend origin, which in the browser deployment is the page's own origin. This
  replaces `isSameOrigin` (`csrfFetch.ts:49-56`, `87`) and the recovery call's `credentials: "same-origin"`
  (`csrfFetch.ts:99`). #2712's rule, never attach the bearer to a cross-origin URL, becomes "only to the
  backend origin" through the same predicate. #2712's owner agrees before S6.
- **3f. Contract changes (C-6.1), all in S1.**
  - `22-api-openapi.yaml` info "CSRF": the response header, the two client modes, recovery through
    `GET /auth/session`, and the cookie attributes of decision 4.
  - A new info paragraph, "Cross-origin (CORS)": 2b and 2c.
  - A new `components.headers.CsrfTokenIssued`, referenced from the 2xx responses of every operation that
    issues or rotates the token. Today that is `POST /auth/mfa/verify`, `POST /auth/refresh` and
    `GET /auth/session`. The contract's issue list also names `POST /auth/login`, `/auth/mfa/recovery`,
    `/auth/mfa/enroll/confirm` and `/auth/step-up` (`22-api-openapi.yaml:121-128`).
  - `23-ws-protocol.md` §2.1: the endpoint is on the REST backend origin. That is the page's origin in a
    browser and the shell-provided origin on the desktop. §2.5's Electron bullet
    (`23-ws-protocol.md:125`) points here. No WS frame, auth step or close code changes.
  - Regenerate `packages/protocol` if the header component changes the generated output.

### 4. Cookies, the session transport and the CSP

- **4a. Credentials.** The desktop page sends `credentials: "include"`, to the backend origin only (3e).
- **4b. Cookie attributes**, chosen by one pure function of the request's `Origin` for every `Set-Cookie`
  that names either cookie: issue, rotate, re-issue and expiry alike.

  | Request's `Origin`                            | `__Host-cv_csrf`                                 | `cv_refresh`                                             |
  | --------------------------------------------- | ------------------------------------------------ | -------------------------------------------------------- |
  | Exactly `app://candleviewer`, and listed (2a) | `Secure; SameSite=None; Path=/`, not HttpOnly    | `HttpOnly; Secure; SameSite=None; Path=/api/v1/auth`     |
  | Anything else, or no `Origin`                 | Unchanged: `SameSite=Strict` (`api/csrf.py:165`) | Unchanged: `SameSite=Strict` (`api/sessions.py:378-387`) |

  Only `SameSite` changes; `Secure`, `HttpOnly`, `Path`, the `__Host-` prefix and `Max-Age` stay.
  - Web content never sends `Origin: app://candleviewer`, so browser sessions keep `Strict`.
  - The desktop's cookies live in the shell's own session, where only the shell's pages run (2d).
  - Every unsafe request still needs a listed `Origin` and the session-bound token.
  - `cv_refresh` stays path-scoped, and the refresh route refuses an unlisted `Origin` before using the
    cookie (`api/sessions.py:924-928`).
  - **Expiry goes through the same function.** The clearing helpers, `clear_csrf_cookie`
    (`api/csrf.py:168-169`) and `_clear_refresh_cookie` (`api/sessions.py:390-396`), expire both cookies
    with `SameSite=Strict` today. They run on logout (`api/sessions.py:1229`, `1323-1324`) and when a user
    revokes their own current session (`api/sessions.py:1327`, `1361-1362`). A browser ignores such a
    deletion on a cross-site response (A7). Left as it is, a desktop sign-out would leave both cookies in
    the shell's profile, the revoked `cv_refresh` included, against the contract's "`POST /auth/logout`
    expires it" (`22-api-openapi.yaml:128`). So both helpers take their attributes from the 4b function,
    and if 4c adds `Partitioned`, deletions carry it too. Logout revokes the session on the server before
    it clears the cookies (`api/sessions.py:1300-1303`), so a leftover cookie would name a dead session.

  This needs owner decision D2. It refines ADR-0010 decisions 2 and 3 and the `SameSite=Strict` wording of
  SR-012 and SR-041, for this one origin. **Form:** a dated amendment section in ADR-0010, under rule 3 of
  `27-adrs/README.md:50`. It is a refinement, not a superseding record, because every other origin keeps
  `Strict`. S1 carries the amendment, under `security-review`, together with the other documents that
  rest on `SameSite=Strict`:
  - the SR-012 and SR-041 rows (`04-security-program.md:682`, `743`);
  - the E09 threat model's U5 control (`docs/security/threat-models/e09-auth-rbac.md:95`);
  - the contract's "Exempt" bullet, which names `SameSite=Strict` as an additional control
    (`22-api-openapi.yaml:132-136`). For the desktop origin, the additional control is the `Origin`
    check alone.

  This record edits none of them.

- **4c. `Partitioned` (CHIPS).** Added to both desktop cookies if S2 shows that Electron keys them to the
  `app://candleviewer` top-level site and sends them; otherwise left out.
- **4d. `Secure` over plain loopback HTTP.** This relies on `http://127.0.0.1` being treated as a secure
  origin for cookies, as the contract already states for local development (`22-api-openapi.yaml:107-109`).
  S2 pins it from an `app://` page. If it does not hold, owner decision D3 picks the fallback. The
  recommended fallback is TLS on loopback (SR-049's local CA option): `https://127.0.0.1` and `wss://`.
  The API contract does not change either way.
- **4e. The session transport is otherwise unchanged.** The bearer goes in `Authorization` for REST and in
  the WS `auth` frame (`23-ws-protocol.md` §4.3), never in a URL.
- **4f. CSP.** `connect-src 'self' <httpOrigin> <wsOrigin>`, from the one resolved endpoint (1a). Packaged
  builds stay loopback-only, and nothing else is added. A refused endpoint gives `connect-src 'self'`.
  Widening to a tailnet host is D1's to decide. The hardening gate's `connect-src` rules
  (`tools/ci/electron_hardening_checks.py:305-322`) stay as they are.

### Browser-engine assumptions (pinned by S2)

| Id  | Expected behaviour                                                                                                                                                                                             | If it does not hold                                                                                                                                                                                                                                                                                                                              |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| A1  | The page sends `Origin: app://candleviewer` on cross-origin fetches and on the WS upgrade, including an upgrade opened by a worker the page starts (1e; relied on by `23-ws-protocol.md:125`)                  | This record is void (SR-042 never lists `null`); re-open it                                                                                                                                                                                                                                                                                      |
| A2  | `SameSite=Strict` and `Lax` cookies are neither stored from nor sent on those requests                                                                                                                         | Re-check 4b; it may become unnecessary                                                                                                                                                                                                                                                                                                           |
| A3  | `SameSite=None; Secure` cookies from `http://127.0.0.1` are stored and sent on credentialed CORS requests from the page                                                                                        | D3 (TLS on loopback)                                                                                                                                                                                                                                                                                                                             |
| A4  | Electron honours `Partitioned` for an `app://` top-level site                                                                                                                                                  | Leave `Partitioned` out (4c)                                                                                                                                                                                                                                                                                                                     |
| A5  | `document.cookie` on the page shows none of the backend's cookies                                                                                                                                              | No change: the header path still works                                                                                                                                                                                                                                                                                                           |
| A6  | `BroadcastChannel` works between the app's windows                                                                                                                                                             | Windows fall back to the recovery path (3d)                                                                                                                                                                                                                                                                                                      |
| A7  | A cross-site expiry removes a desktop cookie when it carries the same `SameSite=None; Secure` (and `Partitioned`, if 4c adds it), and a `SameSite=Strict` expiry does not                                      | D3; until then a leftover cookie names a revoked session (4b)                                                                                                                                                                                                                                                                                    |
| A8  | The secure `app://` page (`main/appProtocol.ts:24-25`) may fetch `http://127.0.0.1` and open `ws://127.0.0.1`, because loopback counts as potentially trustworthy, so neither is blocked as mixed content      | D3 (TLS on loopback)                                                                                                                                                                                                                                                                                                                             |
| A9  | Chromium's local-network access rules let the page reach the loopback backend with no permission (the shell refuses every permission request, `main/index.ts:243-247`) and no private-network preflight answer | A preflight: S3 turns on the locked Starlette's `allow_private_network`, which only a passing, listed-origin preflight returns. A permission: S5 grants that one permission to the main window on the app origin only and keeps refusing every other request (`security-review`); `connect-src` still limits the page to the backend origin (4f) |
| A10 | The telemetry transport's keep-alive JSON `POST` (`lib/telemetry/aggregator.ts:127-138`) is sent cross-origin with its preflight                                                                               | On the desktop, S6 sends it without `keepalive`; at most the batch in flight at unload is lost                                                                                                                                                                                                                                                   |
| A11 | A shared worker the page starts runs under the frozen `app:` privileges (`main/appProtocol.ts:18-29`)                                                                                                          | The E17-T04 wiring slice opens the desktop's socket another way; the privileges are not widened without a dated amendment here                                                                                                                                                                                                                   |

None of A1 to A11 was measured for this record: the design machine had no offline Electron binary. S2
measures them with the repo's Electron (`apps/desktop/package.json:29`, `^41.10.7`) before the slices that
rely on them (S3 to S7 and S9) merge. S2 tells a blocked request (A8, A9) apart from a missing or wrong
`Origin` (A1), so a blocked request is never read as A1 failing.

### 5. STRIDE for the new paths

| Id    | STRIDE | Threat on a new path                                                                          | Control                                                                                                                                                                                                                          | Residual                                                                               |
| ----- | ------ | --------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| BC-S1 | S      | A page in the user's ordinary browser makes the backend act for a signed-in desktop user      | It cannot send a listed `Origin` (2d); cross-site cookies exist only in the shell's own session (4b); double-submit unchanged (3a)                                                                                               | Low                                                                                    |
| BC-S2 | S      | A local program presents `Origin: app://candleviewer`                                         | `Origin` is not client identity (2d); a session still needs password, TOTP and the session-bound token; the backend is loopback/mesh only (`net/cidr.py:21`)                                                                     | Accepted: a program running as the same OS user is outside the app's control (B1, B2)  |
| BC-T1 | T      | A tampered `CV_BACKEND_ORIGIN` points the shell at another host or injects CSP tokens         | One parser, printable ASCII only, an exact scheme set, refusal of userinfo, path and query, loopback-only packaged builds, fail closed; the CSP comes only from the resolved value (1a to 1c)                                    | Low                                                                                    |
| BC-T2 | T      | Script in the renderer redirects API calls to another host                                    | The address comes from the main process at startup, and `connect-src` admits only that origin (4f)                                                                                                                               | Low                                                                                    |
| BC-R1 | R      | Desktop requests cannot be attributed                                                         | No new path: the existing records (`auth.csrf_refused`, `auth.ws_origin_refused`, session events) cover them, within their budgets                                                                                               | None new                                                                               |
| BC-I1 | I      | The CSRF token in a response header reaches another origin, a log or a cache                  | CORS exposes it only to listed origins (2b); it is a session-bound MAC; the redaction filter and `no-store` keep it out of logs and caches, and proxies and access logs treat it as sensitive (3b)                               | Low                                                                                    |
| BC-I2 | I      | Another page running in the shell's session sends the cross-site desktop cookies              | Only app pages run there (SR-113, CSP); unsafe requests still need a listed `Origin` and the token; `cv_refresh` is path-scoped and its route checks `Origin` (4b)                                                               | Low                                                                                    |
| BC-I3 | I      | An over-broad CORS policy lets another origin read authenticated responses                    | The exact list from the startup-validated `CV_ALLOWED_ORIGINS`; no regex, no `*`, no reflection; one policy for the layer and the guard's refusals; tests that an unlisted origin gets no `Access-Control-Allow-Origin` (2b, 2c) | Low; in a dev stack the compose default's Vite origins can read too (Consequences, D4) |
| BC-I4 | I      | A desktop sign-out leaves the revoked `cv_refresh` and the CSRF cookie in the shell's profile | Every `Set-Cookie` for the two cookies, expiry included, takes the desktop attributes (4b); logout revokes the session on the server first; S4 and S9 check the cookie jar is empty                                              | Low                                                                                    |
| BC-D1 | D      | A flood of preflights                                                                         | Inside MeshOnly, no I/O, `max_age` 600 s; the CSRF refusal audits keep their budgets (`api/csrf.py:100-109`)                                                                                                                     | Low                                                                                    |
| BC-D2 | D      | A wrong address leaves the desktop unable to connect                                          | Fails closed by design (1c), with the reason in the main-process log and the existing unreachable state shown                                                                                                                    | Accepted: availability over silent misrouting                                          |
| BC-E1 | E      | The new bridge function widens the renderer's reach into the main process                     | Read-only, no arguments, a constant return value, on the allow-list, answered only to the main window's top frame on the app origin; the hardening gate and tests cover it (1d)                                                  | Low                                                                                    |
| BC-E2 | E      | A browser session gets the desktop's `SameSite=None` attributes                               | Chosen only for the exact desktop origin, which web content cannot send; one pure function, tested both ways (4b)                                                                                                                | Low                                                                                    |
| BC-E3 | E      | A9's fallback permission grant widens what the renderer may do                                | Taken only if S2 shows it is needed; one permission, to the main window on the app origin only; every other request is still refused, and `connect-src` still limits the target (A9)                                             | Low                                                                                    |

### 6. Slices

Each slice is one PR of at most 400 changed lines (C-4.8), with its tests. Product code starts only after S1
(contract first, C-6.1). S2 is test-only and can run alongside S1.

| #   | Slice                                                                                                                                                                         | Paths                                                                                                                                                                                                   | Tests (in the same PR)                                                                                                                                                                                                                                       | Est. LOC | After                                     |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------- | ----------------------------------------- |
| S1  | Contract: CSRF response header, cookie attributes (issue and expiry), CORS paragraph, WS §2.1/§2.5; the D2 amendment of ADR-0010 with the SR-012, SR-041 and E09 U5 rows (4b) | `docs/plan/22-api-openapi.yaml`, `23-ws-protocol.md`, `27-adrs/ADR-0010-auth-and-rbac.md`, `04-security-program.md`, `docs/security/threat-models/e09-auth-rbac.md`, `packages/protocol` if regenerated | Contract lint, generated-code and governance doc checks                                                                                                                                                                                                      | 200      | This record; D2                           |
| S2  | Browser-behaviour probe that pins A1 to A11, plus a dated amendment here with the result                                                                                      | `apps/desktop/e2e/` with a loopback fixture server inside the spec                                                                                                                                      | The spec itself (`127.0.0.1` only, no other network)                                                                                                                                                                                                         | 320      | -                                         |
| S3  | Backend CORS layer, and one CORS policy shared with the CSRF guard's token refusals (2c)                                                                                      | `api/csrf.py`, `app.py`, a CORS module                                                                                                                                                                  | Listed and unlisted origins (no `Access-Control-Allow-Origin` for an unlisted one, refusals included), preflight, refusal parity with the layer, middleware order, header lists derived from every operation; the private-network answer only if A9 needs it | 300      | S1, S2 (A1, A9)                           |
| S4  | Backend token header, `GET /auth/session` always returning the token, desktop cookie attributes for issue and expiry                                                          | `api/csrf.py`, `api/sessions.py`, `api/auth.py`                                                                                                                                                         | Attributes both ways; issue, rotate, re-issue; desktop logout and own-session `DELETE` expire both cookies, browser expiry unchanged; `no-store`                                                                                                             | 280      | S1, S2 (A2, A3, A7), D2                   |
| S5  | Shell: `resolveBackendEndpoint`, the CSP built from it, the `cv:backend:endpoint` channel and bridge function                                                                 | `apps/desktop/src/main`, `apps/desktop/src/preload`, the hardening gate                                                                                                                                 | Accepted and refused inputs, packaged and unpackaged; CSP; allow-list; the sender-frame check; the bridge type; the A9 permission only if S2 needs it                                                                                                        | 340      | S1, S2 (A9), D1, D5                       |
| S6  | Web: backend module, URL helper, backend-origin predicate, credentials, WS URL from the bridge                                                                                | `apps/web/src/lib/http`, `main.tsx`, the eleven call sites, the web `CvBridge` type                                                                                                                     | Browser and desktop modes; nothing attached off the backend origin; the telemetry transport per A10                                                                                                                                                          | 380      | S5, S2 (A8, A10); #2712 owner agrees (3e) |
| S7  | Web: in-memory token for the desktop page, `BroadcastChannel`, recovery through `GET /auth/session`                                                                           | `apps/web/src/lib/http`                                                                                                                                                                                 | Token updates, recovery once, a leak test (no token in storage, the URL or `document.cookie`)                                                                                                                                                                | 260      | S4, S6                                    |
| S8  | Config and docs: the dev compose default lists `app://candleviewer`; runbook (with the `X-CSRF-Token` note for proxies and access logs, 3b); desktop README                   | `infra/compose/docker-compose.dev.yml`, `docs/ops/runbooks/auth-rbac.md`, `apps/desktop/README.md`                                                                                                      | Compose config check                                                                                                                                                                                                                                         | 70       | S3, S4, D4                                |
| S9  | Done-when proof: the shell signs in and out against a local backend                                                                                                           | `apps/desktop/e2e/`, a test backend, the `e2e-electron` job                                                                                                                                             | See below                                                                                                                                                                                                                                                    | 390      | S2 to S8                                  |

**Done when (S9).**

- **The positive path.** The shell loads `app://candleviewer` (no dev server) and signs in against a local
  backend:
  - `POST /auth/login`, then `POST /auth/mfa/verify` with a code from a fixed test-vector TOTP secret;
  - `GET /me` with the bearer succeeds;
  - one CSRF-guarded write (for example `PUT /me/preferences`) succeeds;
  - `POST /auth/refresh` rotates both cookies and the page's token;
  - a WS upgrade from the page reaches `auth_ok`;
  - `POST /auth/logout` expires both cookies, and the shell's cookie jar then holds neither (4b, A7).
- **The checks are enforced**, each as a failing case in the same spec:
  - the same write without `X-CSRF-Token` gets `403 csrf_token_invalid`, which the page can read;
  - against a backend started without `app://candleviewer` listed, sign-in fails (the preflight is
    refused, and an unsafe request would be refused as `cross_origin`), and the WS upgrade is refused
    (counted as `origin_forbidden` by the backend);
  - with a refused `CV_BACKEND_ORIGIN`, no request leaves the page.
- **The backend.** The production `create_app` (`app.py:1081-1100`, which builds the app without
  Postgres, QuestDB or network), with test doubles where it takes them, served by a real uvicorn on
  `127.0.0.1`, as the chaos suite serves the real `/ws` gateway
  (`services/api/tests/chaos/ws/_server.py:1-21`). So the middleware order and the guards that the
  negative cases prove are the ones that ship. No exchange and no network beyond loopback (C-13.5).
- **Where it runs.**
  - Locally, under WSLg or xvfb.
  - In CI only in the `e2e-electron` job. It runs when its caller asks for it, as the nightly and a
    dispatch do (`.github/workflows/e2e-nightly.yml:19-22`), and on the PR lane only for the head refs
    that `.github/workflows/_job-e2e.yml:185` names. That job starts no backend today
    (`.github/workflows/_job-e2e.yml:183-232`), so S9 adds a Python step to it (a workflow change,
    `security-review`).
  - It is not a required PR check (C-9.1). The PR's evidence is a local run log and a dispatch run link.
    The server-side checks of S3 and S4 also run in the normal PR suites.
- **Through the UI or not.** Sign-in through the UI needs #2711 and #2712. If they have not merged when S9
  starts, S9 drives the same calls through the web app's own REST modules inside the `app://` page (same
  origin, CSP and cookie jar), and a follow-up switches the spec to the UI.

### 7. Owner decisions

| #   | Decision                                                                                                                                                                                                                                                                                                            | Recommendation                                                                                                                                             |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D1  | Packaged builds: loopback only (`127.0.0.1`), or also one `https://<tailnet-host>` as SR-112 names. A yes is the recorded `connect-src` widening, and it must also fix the host rule.                                                                                                                               | Loopback only for now; widen later by a dated amendment here                                                                                               |
| D2  | Desktop-origin cookies get `SameSite=None` (4b), on every `Set-Cookie` of the two cookies, expiry included. This refines ADR-0010 decisions 2 and 3 and the SR-012 and SR-041 wording, for exactly `app://candleviewer`, as a dated amendment section in ADR-0010 that S1 carries with the SR and E09 U5 rows (4b). | Yes: without it the desktop cannot hold a session at all                                                                                                   |
| D3  | If S2 shows that `Secure` cookies (A3, A7) or loopback requests (A8) are not honoured over plain `http://127.0.0.1`: TLS on loopback, or re-open this record                                                                                                                                                        | TLS on loopback (SR-049's local CA)                                                                                                                        |
| D4  | `app://candleviewer` in the dev compose default allow-list, and how production lists it. After S3 every listed origin can also read credentialed responses, the default's four Vite origins included (Consequences).                                                                                                | Dev default: yes, and the Vite entries stay (they are this web app in dev). Production: the operator lists it explicitly, as with the tailnet origin today |
| D5  | Packaged builds also accept `http://localhost`                                                                                                                                                                                                                                                                      | No: `127.0.0.1` only, as SR-049 names it. Dev builds accept `127.0.0.1` and `localhost` (1b)                                                               |
| D6  | The Done-when proof runs nightly and on dispatch, not per PR, with a Python step added to the `e2e-electron` job                                                                                                                                                                                                    | Accept; making it a required check would be a separate C-9.1 amendment                                                                                     |

## Consequences

- **Positive.** The desktop signs in over loopback with every existing check in place. The browser
  deployment is unchanged. There is one source for the address. The contract describes the cross-origin
  client explicitly.
- **Negative.**
  - Two `SameSite` values are now in play, kept to one pure function tested both ways.
  - The backend gains a CORS layer, and responses to listed origins carry more headers.
  - Every listed origin can now read credentialed responses, which no origin can today. In a dev stack
    the listed origins include the compose default's four Vite origins
    (`infra/compose/docker-compose.dev.yml:22`). Two of them, `http://127.0.0.1:5173` and `:4173`, are
    the same site as a backend on `127.0.0.1`, so their requests to it carry its `SameSite=Strict`
    cookies as well. A listed origin is already trusted to send writes with the token (SR-042); S3
    extends that trust to reads. Production's list is empty by
    default (`settings.py:336-342`), so nothing changes there until an operator lists an origin (D4).
  - The desktop page holds a CSRF token in memory (not a credential).
  - The desktop's `cv_refresh` is a cross-site cookie in the shell's profile, persisted like a browser
    profile's cookies.
  - The proof needs a Python backend in the Electron job.
- **Neutral.** No new dependency (the CORS layer is Starlette's). No flag: no slice changes what an
  unlisted origin or a same-origin browser page sees (driver 6).

## Why not the alternatives

The overall options B to F are rejected under "Considered options". Within option A:

**For decision 1 (the backend address):**

- A build-time define (`import.meta.env`): one web build serves both deployments, the address differs per
  install, and the runtime CSP could disagree with the baked-in value.
- A query string or fragment on the entry URL: the page location becomes input again (deep links, SR-175)
  and is lost on navigation.
- A generated `config.json` from the `app://` handler: not a static asset (SR-174).
- A synchronous constant passed through the preload's process arguments: no gain over one async call, and it
  depends on what a sandboxed preload exposes.
- A loopback constant in the web app: a second copy of the main-process default.

**For decision 2 (where the CORS layer sits):** the chosen place, inside Csrf, costs the guard's
refusals their own CORS headers, which come from the one shared policy (2c).

- Between HttpDuration and Correlation. One layer would make every refusal readable, and the pinned trio
  would stay adjacent (`test_csrf_double_submit.py:446-455` checks only the trio). Rejected: off-mesh
  peers would get CORS answers before MeshOnly refuses them, so MeshOnly (`app.py:2082-2088`) would no
  longer be the first gate every request meets. Preflight answers would also carry no correlation id,
  against `app.py:2089-2090`.
- Outermost, outside HttpDuration: the same objections, and preflights would no longer be timed
  (`app.py:2092-2094`, #2421).
- Between Correlation and MeshOnly, or between MeshOnly and Csrf: it breaks the adjacency that
  `app.py:2092-2093` and the test pin.

**For decision 3 (the token path):**

- The token in each issuing operation's JSON body: seven schemas and seven code paths that could drift,
  against one function.
- A dedicated `GET /auth/csrf`: a round trip after every rotation, and until it returns the page holds a
  stale token, so its next write is refused and audited.
- Header-only CSRF: option E.

## Validation

This record moves to `decided` when D1 to D6 are recorded and S2 has pinned A1 to A11, or when the
fallbacks in the assumptions table have been taken. Each slice's own tests are listed in the slice table.
The record's end-to-end validation is S9.

## Follow-ups (not this ticket's scope)

- **F1.** `22-api-openapi.yaml:14204` describes a `cookie_auth:false` login flag that no request schema
  defines. This needs a contract clean-up issue.
- **F2.** The web `CvBridge` declares twelve functions, while the preload exposes three
  (`shell/ElectronShellAdapter.ts:21-34`, `preload/index.ts:21-25`). S5 adds the new function to both
  sides; the existing gap is not this record's.
- **F3.** Invite links are built from `window.location.origin` (`features/invites/AdminInviteScreen.tsx:50`,
  `65`), so on the desktop they would be `app://` links. This needs a separate ticket.
- **F4.** The E42 admin model forecasts "ADR-0038" for the E42-T06 record
  (`docs/security/threat-models/e42-admin.md:63-64`). This record takes 0038, so that line needs the next
  free number when E42-T06 is written; the E42 owner updates it, not this PR.

## References

- `apps/web/src/main.tsx`, `apps/web/src/lib/http/csrfFetch.ts`, `apps/web/src/shell/`
- `apps/desktop/src/main/{appProtocol,csp,index}.ts`, `apps/desktop/src/preload/{index,allowList}.ts`
- `services/api/candleviewer/{settings,app}.py`, `services/api/candleviewer/api/{csrf,sessions,auth,me}.py`,
  `services/api/candleviewer/ws/{gateway,lifecycle,origin_audit}.py`, `services/api/candleviewer/auth/csrf.py`
- `docs/plan/22-api-openapi.yaml` (info "CSRF", "Idle lock"), `docs/plan/23-ws-protocol.md` §2.1, §2.5, §4.3
- `docs/plan/04-security-program.md` SR-006, SR-012, SR-041, SR-042, SR-049, SR-111 to SR-113, SR-173,
  SR-174, SR-181, SR-183; `docs/plan/20-architecture.md` §2.2
- ADR-0010, ADR-0020; `docs/ops/runbooks/auth-rbac.md` §8
