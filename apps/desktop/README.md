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
`will-navigate` restricted to the app origin. `e2e/hardening.spec.ts` fails
if any flag drifts.

## Load path: `app://candleviewer`, not `file://` (#3410)

Without `CV_DEV_SERVER_URL`, the main window loads `app://candleviewer/`. A
privileged custom scheme (`src/main/appProtocol.ts`) serves `apps/web/dist`
read-only: one fixed host, the path decoded once and confined to the dist
root (SR-174), extension-less routes fall back to `index.html` for the
history-API router, and every response carries the shell's CSP header from
`csp.ts` (SR-112). The scheme is `standard` and `secure` only and never
bypasses the CSP; the electron-hardening gate asserts that set.

Why not `file://`: Vite emits root-absolute asset URLs, which resolve to the
filesystem root under `file://`, so the window stayed blank. A relative
`base` would fix the asset paths, but the page would still share the broad
`file://` origin; the Electron security checklist recommends a custom
protocol, which also confines reads to the dist root and gives the CSP header
one delivery point.

Packaged builds: `electron-builder.yml` packages only this package's `dist/`,
so `apps/web/dist` is not in the installer yet. The handler expects it at
`<resources>/web/dist`; adding it (without source maps, SR-116) and checking
the installer the same way is still open.

## Scripts

- `pnpm --filter @candleviewer/desktop build` — compiles `src/` to `dist/`.
- `pnpm --filter @candleviewer/desktop dev` — build then launch Electron.
- `pnpm --filter @candleviewer/desktop e2e` — Playwright-Electron specs
  (requires `build` to have run first).
- `pnpm --filter @candleviewer/desktop build:installer` — electron-builder
  packaging (real signing/notarization/auto-update land in E10).

## Out of scope (E10)

Route tree, auth/RBAC guards, env badge, global shortcut registry,
auto-update, crash reporting, GPU flag tuning (depends on E06).
