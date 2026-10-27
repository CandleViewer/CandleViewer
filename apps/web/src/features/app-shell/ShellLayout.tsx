import { useRef, type JSX } from "react";
import { Outlet } from "react-router";
import { ShellAnnouncer } from "./announcer";
import { AppShell } from "./AppShell";
import { NavRail } from "./NavRail";
import { InShellProvider } from "./ScreenRoot";
import { ShellBannerSlot, ShellCanvasOverlaySlot, ShellConnectionSlot } from "./slots";
import { TopBarSlot } from "./TopBarSlot";
import { useRouteFocus } from "./useRouteFocus";

/** id of the shell's one `main` landmark. */
export const SHELL_MAIN_ID = "cv-main";

/**
 * SCR-010 shell layout route (E10-S01 S1, #304): the pathless parent of every non-public route
 * in `routes/tree.tsx`. Public and error routes render outside it with their own `main`.
 */
export function ShellLayout(): JSX.Element {
  const mainRef = useRef<HTMLElement>(null);
  useRouteFocus(mainRef);
  return (
    <InShellProvider>
      <AppShell
        mainId={SHELL_MAIN_ID}
        mainRef={mainRef}
        nav={<NavRail />}
        connection={<ShellConnectionSlot />}
        topBar={(connection) => <TopBarSlot connection={connection} />}
        banner={<ShellBannerSlot />}
        canvasOverlay={<ShellCanvasOverlaySlot />}
      >
        <Outlet />
      </AppShell>
      <ShellAnnouncer />
    </InShellProvider>
  );
}
