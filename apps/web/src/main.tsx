/// <reference types="vite/client" />
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// Token values per theme, then the runtime styles that key off the root attributes (export names only:
// the packages' build output is not importable by path). Order matters: theme.css overrides the tokens.
import "@candleviewer/ui/tokens.dark.css";
import "@candleviewer/ui/tokens.light.css";
import "@candleviewer/ui/tokens.high-contrast.css";
import "@candleviewer/ui/theme.css";
import "@candleviewer/ui/components.css";
import { startShell } from "./shell/startShell";
import { runBootstrap } from "./shell/bootstrap/bootstrap";
import { getShellState } from "./shell/bootstrap/store";
import { divertUnreachableBoot } from "./features/system-states/bootOffline";
import { TAPE_ENABLED } from "./features/tape/flag";

const container = document.getElementById("root");
if (!container) {
  throw new Error("root element not found");
}

/** WS URL per docs/plan/23-ws-protocol.md §3: same origin as REST. */
function systemWsUrl(): string {
  const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${window.location.host}/api/v1/ws`;
}

// E22-S01 (#714) BQ-206 / BQ-215: the tape's dev / Playwright harness, only in a build made with
// `VITE_FLAG_ORDERFLOW_TAPE=1` (off in every environment) and only on its own path. It replaces the
// shell for that page: no session, no socket. The E15 dock ticket removes it with the flag.
const TAPE_HARNESS_PATH = "/__dev/tape";

if (TAPE_ENABLED && window.location.pathname === TAPE_HARNESS_PATH) {
  void import("./features/tape/harness/mountHarness").then((m) => m.mountTapeHarness(container));
} else {
  boot(container);
}

function boot(container: HTMLElement): void {
  // E10-T04-B1 (#1725): the bootstrap (/me, preferences, keymap) must run
  // before the router renders, otherwise the R-101 guard sees no session and
  // redirects every route to /login. runBootstrap never rejects and each call
  // has a hard timeout, and the page-load token refresh before it is waited for
  // at most REFRESH_WAIT_MS (#2712), so this cannot hang the first paint.
  const shell = startShell({ wsUrl: systemWsUrl() });
  // App is imported lazily: its module creates the data router, which runs the
  // initial route loaders (guards) at creation time.
  void shell.ready.then(async () => {
    const root = createRoot(container);
    // #1640: a reload into an idle-locked session unlocks first (SCR-005), then boots for real
    if (getShellState().bootstrap.kind === "locked") {
      const { unlockBeforeBoot } = await import("./features/session/lockedBoot");
      await unlockBeforeBoot(root);
      await runBootstrap();
    }
    // SCR-159 (#306): a boot that found no server opens R-902 `/offline`, before the router reads the URL
    divertUnreachableBoot();
    const { App } = await import("./App");
    root.render(
      <StrictMode>
        <App />
      </StrictMode>,
    );
  });

  // Teardown on HMR so a replaced module does not leak a reconnecting socket.
  if (import.meta.hot) {
    import.meta.hot.dispose(() => shell.stop());
  }
}
