import { useEffect, useRef, type JSX } from "react";
import { Outlet } from "react-router";
import { GatedAnnounceProvider } from "@candleviewer/ui";
import { ShellAnnouncer } from "./announcer";
import { AppShell } from "./AppShell";
import { NavRailFrame } from "./NavRailFrame";
import { RIGHT_RAIL_LABEL, RightRail } from "./RightRail";
import { SymbolSearchHost } from "../symbol-search/SymbolSearch";
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
import { probeCommits, probeRender } from "./perfProbe";
import { SHELL_PERF_MARKS, markShellStage } from "../../shell/perfMarks.js";

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
  probeRender("shell"); // E10-Q04 render counter: a probe build only (perfProbe)
  useRouteFocus(mainRef);
  // Budget #10 (E10-Q04): a child's effects run first, so the chrome and its first route element
  // are both committed here; marked once per page load (perfMarks).
  useEffect(() => markShellStage(SHELL_PERF_MARKS.routeMounted), []);
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
          status={probeCommits("status", <ShellStatusSlot />)}
        >
          {probeCommits("outlet", <Outlet />)}
        </AppShell>
        <ShellAnnouncer />
        <SymbolSearchHost mainRef={mainRef} />
      </InShellProvider>
    </GatedAnnounceProvider>
  );
}
