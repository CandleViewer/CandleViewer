import type { CSSProperties, JSX } from "react";
import { IconButton } from "@candleviewer/ui";
import { setRailCollapsed, useShellLayout } from "./layoutStore";
import { useReducedMotion } from "./motion";
import { NavRail } from "./NavRail";

/** D03 §2: 240 px expanded, 64 collapsed (geometry, not tokens: `size.navrail.width` is not one). */
const EXPANDED = "240px";
const COLLAPSED = "64px";

function frameStyle(collapsed: boolean): CSSProperties {
  // The width snaps (never transitions): only the labels move, by `transform` (D04 T-01 / T-02).
  return {
    display: "flex",
    flexDirection: "column",
    height: "100%",
    width: collapsed ? COLLAPSED : EXPANDED,
    overflow: "hidden",
  };
}

const TOGGLE_ROW: CSSProperties = { marginTop: "auto", padding: "var(--space-inset-sm)" };

/**
 * The nav rail with its collapse toggle (E10-S01 S6, #304), inside the shell's `nav` "Primary".
 * The toggle sits in the rail's static column, under the items (D04 T-01 PROPOSED placement; the
 * ticket puts the pin in the rail, the sitemap in Settings: plan gap 10). Per D03 :357 and the D04
 * names table it carries `aria-expanded` (true while expanded) and swaps its name between
 * "Collapse navigation rail" and "Expand navigation rail". The rail reads the layout store here,
 * so the outlet never re-renders.
 */
export function NavRailFrame(): JSX.Element {
  const collapsed = useShellLayout("railCollapsed");
  const reduceMotion = useReducedMotion();
  return (
    <div style={frameStyle(collapsed)} data-rail={collapsed ? "collapsed" : "expanded"}>
      <NavRail collapsed={collapsed} reduceMotion={reduceMotion} />
      <div style={TOGGLE_ROW}>
        <IconButton
          icon="chevron-right"
          label={collapsed ? "Expand navigation rail" : "Collapse navigation rail"}
          variant="ghost"
          size="sm"
          aria-expanded={!collapsed}
          onClick={() => setRailCollapsed(!collapsed)}
        />
      </div>
    </div>
  );
}
