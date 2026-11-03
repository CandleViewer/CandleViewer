import type { CSSProperties } from "react";
import type { Root } from "react-dom/client";
import { ThemeProvider } from "@candleviewer/ui";
import { APP_THEME_OPTIONS } from "../../shell/bootstrap/themeStore";
import { ShellAnnouncer } from "../app-shell/announcer";
import { SessionLockHost } from "../session/SessionLockHost";
import { VA_COPY } from "./copy";
import { ViewAsBanner } from "./ViewAsBanner";

/** Outside the shell the page paints its own surface behind its text, as the shell's frame does. */
const PAGE: CSSProperties = {
  position: "fixed",
  inset: 0,
  display: "flex",
  flexDirection: "column",
  background: "var(--color-surface-app)",
  color: "var(--color-text-primary)",
};

/**
 * E42-S03 V-8 at boot: a load into a view-as context the server ended (the bootstrap's `held`).
 * The server refuses every read but the viewer's own then, `/me` included, so no route, claim or
 * datum mounts: the page is SCR-124's banner, with `va.ended` and Exit as its first Tab stop, which
 * loads SCR-121 in the owner's own scope. A sibling's Exit reloads this page too (the sync). The
 * idle-lock host (SCR-005, as `lockedBoot` mounts it) is here too: an Exit the server refuses as
 * idle-locked is unlocked on the page, then pressed again. The page names itself apart from the
 * app's other windows.
 */
export function showHeldBoot(root: Root): void {
  document.title = VA_COPY.heldTitle;
  root.render(
    <ThemeProvider options={APP_THEME_OPTIONS}>
      <div style={PAGE}>
        <ViewAsBanner />
        <main id="cv-main" tabIndex={-1} style={{ flex: "1 1 auto" }}>
          <h1 className="cv-visually-hidden">{VA_COPY.region}</h1>
        </main>
      </div>
      <SessionLockHost enabled />
      <ShellAnnouncer />
    </ThemeProvider>,
  );
}
