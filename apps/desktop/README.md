# @candleviewer/desktop

Electron shell wrapping `apps/web`'s build. **No business logic** (C-3.5) —
that stays behind the `ShellPort` abstraction in `src/main/shellPort.ts`
because ADR-0011 (Electron vs Tauri) is `proposed`, not decided.

- `src/main/` — main process: window creation, hardening, CSP header,
  startup/audit logging.
- `src/preload/` — context-isolated preload; exposes exactly one namespaced
  object, `window.cv`, built from an explicit IPC channel allow-list (empty
  at E02-T04; editing `allowList.ts` is code-owned by the security engineer,
  trust boundary B4, `20-architecture.md` §2.2).
- `e2e/` — Playwright-Electron: main-window smoke spec, the hardening
  assertion test that reads live `webPreferences` at runtime, and
  `app-protocol.spec.ts` (the default load path renders, under the CSP).

## Hardened defaults (asserted, not just configured)

`contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`,
`webSecurity: true`; `window.open` denied via `setWindowOpenHandler`;
`will-navigate` and `will-redirect` restricted to the app origin; `<webview>`
refused; IPC handlers answer only the app origin's main frame (#3608).
`e2e/hardening.spec.ts` fails if any flag drifts.

Dev server hook: `CV_DEV_SERVER_URL` is honoured only in an unpackaged build
and only for `http://127.0.0.1:<port>` or `http://localhost:<port>`, checked
on the parsed URL (`src/main/devServer.ts`, #3411). Otherwise the shell loads
its own bundle and logs one `dev-server-url-ignored` line naming the reason
(`unpackaged-only`, `not-loopback-http` or `malformed`), never the value.

## Load path: `app://candleviewer`, not `file://` (#3410)

Without `CV_DEV_SERVER_URL`, the main window loads `app://candleviewer/`. A
privileged custom scheme (`src/main/appProtocol.ts`) serves `apps/web/dist`
read-only: one fixed host, the path decoded once and confined to the dist
root (SR-174), an extension-less route outside `/api` gets `index.html` for
the history-API router, and every response carries the shell's CSP header from
`csp.ts` (SR-112). The scheme is `standard` and `secure` only and never
bypasses the CSP; `test/index.test.ts` and the electron-hardening gate pin
that set.

Why not `file://`: Vite emits root-absolute asset URLs, which resolve to the
filesystem root under `file://`, so the window stayed blank. A relative
`base` would fix the asset paths, but the page would still share the broad
`file://` origin; the Electron security checklist recommends a custom
protocol, which also confines reads to the dist root and gives the CSP header
one delivery point.

Packaged builds (#3518): `electron-builder.yml` copies `apps/web/dist`, without
source maps (SR-116), to `<resources>/web/dist`, where the handler reads it
(`dist/main` inside `app.asar` resolves `../../../web/dist` there). The
electron-hardening gate fails if a packaging list could ship a `.map` file, if
anything other than that entry could write into that root, or if the built
handler stops reading `../../../web/dist`; `check_packaging` names the few
config forms it does not see. These files sit outside `app.asar`, so ASAR
integrity does not cover them: the SR-118 startup check (#1231, E43-T02) must,
by packing them into `app.asar` or by checking them against a hash list kept
there. What CI runs: the `build` job builds both dists, launches the unpackaged
`dist/main/index.js` under `xvfb-run` (`collect-hardening-facts.mjs`) and runs
the gate; `e2e-electron` (nightly and on release cuts) launches that same
unpackaged build. No job packages an installer and launches it, so that an
installer renders the app is not yet proven. `release.yml`'s
`build-sign-installer` runs `build:installer` without building either dist, so
it fails at the check below until that workflow (E10) builds both first. The
next step, part of #1231's packaged-artefact checks, is to build the unpacked
app in the `build` job (`electron-builder --linux dir` with `electronDist` set
to the Electron that job installs) and launch it with Playwright-Electron
(`executablePath`) under `xvfb-run`, as `collect-hardening-facts.mjs` launches
`dist/main/index.js`, before #1231 turns off the
`enableNodeCliInspectArguments` fuse that Playwright attaches through.

Backend connection: the web app calls `/api` relative to its page and builds
its socket URL from `location.host`, so on `app://candleviewer` the sign-in
screen renders but cannot reach the backend yet. Giving the desktop build the
backend's address, listing `app://candleviewer` in `CV_ALLOWED_ORIGINS`
(SR-042) and a CSRF token path for an `app://` page are #3519.

## Scripts

- `pnpm --filter @candleviewer/desktop build` — compiles `src/` to `dist/`.
- `pnpm --filter @candleviewer/desktop dev` — build then launch Electron.
- `pnpm --filter @candleviewer/desktop e2e` — Playwright-Electron specs
  (requires `build` to have run first).
- `pnpm --filter @candleviewer/desktop build:installer` — electron-builder
  packaging (real signing/notarization/auto-update land in E10). Build
  `apps/web` and this package first: it stops if `apps/web/dist/index.html`
  is missing (`scripts/require-web-dist.mjs`), because electron-builder only
  warns and that installer would open an empty window. Package only through
  this script: `electron-builder` run on its own skips that check.

## Out of scope (E10)

Route tree, auth/RBAC guards, env badge, global shortcut registry,
auto-update, crash reporting, GPU flag tuning (depends on E06).
