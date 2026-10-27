import type { Root } from "react-dom/client";
import { ThemeProvider } from "@candleviewer/ui";
import { APP_THEME_OPTIONS } from "../../shell/bootstrap/themeStore";
import { SessionLockHost } from "./SessionLockHost";
import type { SessionApi } from "./sessionApi";

/**
 * #1640: a reload into an idle-locked session (the bootstrap's `/me` answered
 * `401 session_idle_locked`) shows SCR-005 instead of routing to /login. Nothing else mounts: no
 * route, no claims, no private data. Resolves once a read finds the session unlocked; the caller
 * then runs the bootstrap again and mounts the app. Five strikes, expiry and "Sign out instead" end
 * in SCR-001 through `endSession`, so they never resolve.
 */
export function unlockBeforeBoot(root: Root, api?: SessionApi): Promise<void> {
  return new Promise((resolve) => {
    root.render(
      <ThemeProvider options={APP_THEME_OPTIONS}>
        <SessionLockHost enabled onUnlocked={resolve} {...(api === undefined ? {} : { api })} />
      </ThemeProvider>,
    );
  });
}
