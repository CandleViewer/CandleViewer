import { useRef, type JSX } from "react";
import { Outlet } from "react-router";
import { GatedAnnounceProvider } from "@candleviewer/ui";
import { ShellAnnouncer } from "./announcer";
import { AppShell } from "./AppShell";
import { NavRailFrame } from "./NavRailFrame";
import { RIGHT_RAIL_LABEL, RightRail } from "./RightRail";
import { SymbolSearchHost } from "../symbol-search/SymbolSearch";
import { CommandPaletteHost } from "../command-palette/CommandPaletteHost";
import { InShellProvider } from "./ScreenRoot";
import {
  ShellBannerSlot,
  ShellCanvasOverlaySlot,
  ShellConnectionSlot,
  ShellPanicSlot,
  ShellStatusSlot,
} from "./slots";
import { TopBarSlot } from "./TopBarSlot";
import { useRouteFocus } from "./useRouteFocus";

/** id of the shell's one `main` landmark. */
export const SHELL_MAIN_ID = "cv-main";

const ignoreGatedAnnouncement = (): void => undefined;

/**
 * SCR-010 shell layout route (E10-S01 S1, #304): the pathless parent of every non-public route
 * in `routes/tree.tsx`. Public and error routes render outside it with their own `main`.
 * The rails read the layout store themselves (S6), so a collapse never re-renders the outlet.
 */
export function ShellLayout(): JSX.Element {
  const mainRef = useRef<HTMLElement>(null);
  useRouteFocus(mainRef);
  return (
    // Surfaces own the gated announcement (G-T2.3); E17-D02 §11: the shell announcer is the one region, so the
    // atoms' own announcement is a no-op here (ruling on #5135, option A).
    <GatedAnnounceProvider announce={ignoreGatedAnnouncement}>
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
          status={<ShellStatusSlot />}
        >
          <Outlet />
        </AppShell>
        <ShellAnnouncer />
        <SymbolSearchHost mainRef={mainRef} />
        {/* SCR-012 (E10-S05): inside the shell only, so `Ctrl+K` stays inert on the public routes. */}
        <CommandPaletteHost />
      </InShellProvider>
    </GatedAnnounceProvider>
  );
}
