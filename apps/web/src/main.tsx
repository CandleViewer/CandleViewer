/// <reference types="vite/client" />
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// Token values per theme, then the runtime styles that key off the root attributes (export names only:
// the packages' build output is not importable by path). Order matters: theme.css overrides the tokens.
import "@candleviewer/ui/tokens.dark.css";
import "@candleviewer/ui/tokens.light.css";
import "@candleviewer/ui/tokens.high-contrast.css";
import "@candleviewer/ui/theme.css";
import { startShell } from "./shell/startShell";

const container = document.getElementById("root");
if (!container) {
  throw new Error("root element not found");
}

/** WS URL per docs/plan/23-ws-protocol.md §3: same origin as REST. */
function systemWsUrl(): string {
  const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${window.location.host}/api/v1/ws`;
}

// E10-T04-B1 (#1725): the bootstrap (/me, preferences, keymap) must run
// before the router renders, otherwise the R-101 guard sees no session and
// redirects every route to /login. runBootstrap never rejects and each call
// has a hard timeout, so this cannot hang the first paint.
const shell = startShell({ wsUrl: systemWsUrl() });
// App is imported lazily: its module creates the data router, which runs the
// initial route loaders (guards) at creation time.
void shell.ready.then(async () => {
  const { App } = await import("./App");
  createRoot(container).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
});

// Teardown on HMR so a replaced module does not leak a reconnecting socket.
if (import.meta.hot) {
  import.meta.hot.dispose(() => shell.stop());
}
