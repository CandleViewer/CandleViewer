import { useRef, type JSX } from "react";
import { Outlet } from "react-router";
import { ShellAnnouncer } from "./announcer";
import { AppShell } from "./AppShell";
import { NavRailFrame } from "./NavRailFrame";
import { RIGHT_RAIL_LABEL, RightRail } from "./RightRail";
import { InShellProvider } from "./ScreenRoot";
import {
  ShellBannerSlot,
  ShellCanvasOverlaySlot,
  ShellConnectionSlot,
  ShellPanicSlot,
} from "./slots";
import { TopBarSlot } from "./TopBarSlot";
import { useRouteFocus } from "./useRouteFocus";

/** id of the shell's one `main` landmark. */
export const SHELL_MAIN_ID = "cv-main";

/**
 * SCR-010 shell layout route (E10-S01 S1, #304): the pathless parent of every non-public route
 * in `routes/tree.tsx`. Public and error routes render outside it with their own `main`.
 * The rails read the layout store themselves (S6), so a collapse never re-renders the outlet.
 */
export function ShellLayout(): JSX.Element {
  const mainRef = useRef<HTMLElement>(null);
  useRouteFocus(mainRef);
  return (
    <InShellProvider>
      <AppShell
        mainId={SHELL_MAIN_ID}
        mainRef={mainRef}
        nav={<NavRailFrame />}
        connection={<ShellConnectionSlot />}
        topBar={(connection) => <TopBarSlot connection={connection} />}
        panic={<ShellPanicSlot />}
        banner={<ShellBannerSlot />}
        canvasOverlay={<ShellCanvasOverlaySlot />}
        rightRail={<RightRail />}
        rightRailLabel={RIGHT_RAIL_LABEL}
      >
        <Outlet />
      </AppShell>
      <ShellAnnouncer />
    </InShellProvider>
  );
}
