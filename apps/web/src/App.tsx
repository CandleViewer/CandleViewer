import { useEffect } from "react";
import { RouterProvider } from "react-router-dom";
import { ThemeProvider } from "@candleviewer/ui";
import { WsErrorHost } from "./lib/ws/WsErrorHost";
import { startTelemetry } from "./lib/telemetry/aggregator";
import { KeymapHost } from "./keymap/KeymapHost";
import { PreferencesProvider } from "./features/a11y-preferences/PreferencesContext";
import { usePublishEngineFlags } from "./features/a11y-preferences/consumers";
import { createRouteTree } from "./routes/tree";
import { APP_THEME_OPTIONS } from "./shell/bootstrap/themeStore";

/**
 * Root application shell (E10-T01). Renders the React Router data router
 * built from the route manifest (`docs/plan/12-sitemap.md` §2). The router
 * instance is created once per app instance, not per render.
 *
 * `<ThemeProvider>` (E05-T02 runtime, #3139) sits once above the router, on the one theme store
 * of the page that the bootstrap already fed; it is the only writer of the root theme attributes.
 */
const router = createRouteTree();

export function App(): JSX.Element {
  // E04-T06: frontend telemetry push loop lives exactly as long as the app.
  useEffect(() => startTelemetry().stop, []);
  const publishFlags = usePublishEngineFlags();
  return (
    <ThemeProvider options={APP_THEME_OPTIONS}>
      <PreferencesProvider onEngineFlags={publishFlags}>
        <RouterProvider router={router} />
        <WsErrorHost />
        <KeymapHost />
      </PreferencesProvider>
    </ThemeProvider>
  );
}
