import { useEffect, useRef, useState, type CSSProperties, type FocusEvent, type JSX } from "react";
import { useLocation } from "react-router";
import { IconButton } from "@candleviewer/ui";
import { setRailCollapsed, useShellLayout } from "./layoutStore";
import { useReducedMotion } from "./motion";
import { NavRail } from "./NavRail";
import { useReflow } from "./reflow";

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

/** At the breakpoint the rail's column stays 64 px wide; an expanded rail is drawn over `main`. */
const COLUMN: CSSProperties = { position: "relative", width: COLLAPSED, height: "100%" };
/**
 * The drawer pattern (#304 S10, A11Y-F-0016): over the workspace, never a column, so `main` keeps
 * its width at 320 CSS px. `zIndex: 1` only orders it above its grid sibling `main` (positioned,
 * later in the DOM); it is no layer of its own (no z-index token exists, and none is needed).
 */
const OVERLAY: CSSProperties = {
  position: "absolute",
  insetBlock: 0,
  insetInlineStart: 0,
  zIndex: 1,
  background: "var(--color-surface-raised)",
  boxShadow: "var(--elevation-popover)",
};

const TOGGLE_ROW: CSSProperties = { marginTop: "auto", padding: "var(--space-inset-sm)" };

/**
 * The nav rail with its collapse toggle (E10-S01 S6, #304), inside the shell's `nav` "Primary".
 * The toggle sits in the rail's static column, under the items (D04 T-01 PROPOSED placement; the
 * ticket puts the pin in the rail, the sitemap in Settings: plan gap 10). Per D03 :357 and the D04
 * names table it carries `aria-expanded` (true while expanded) and swaps its name between
 * "Collapse navigation rail" and "Expand navigation rail". The rail reads the layout store here,
 * so the outlet never re-renders.
 *
 * At CMP-043's reflow breakpoint (#304 S10, A11Y-F-0016, SC 1.4.10; D03 :275) the rail is
 * collapsed whatever the stored choice, which is neither read nor overwritten there, so widening
 * the window restores it. The toggle then opens the rail as an overlay (the drawer pattern) for
 * this page only: Escape, a navigation or focus moving out of the rail closes it (so a focused control
 * is never left under the drawer, SC 2.4.11), and focus goes back to the toggle on Escape.
 */
export function NavRailFrame(): JSX.Element {
  const stored = useShellLayout("railCollapsed");
  const narrow = useReflow();
  const reduceMotion = useReducedMotion();
  const toggleRow = useRef<HTMLDivElement>(null);
  const { pathname } = useLocation();
  // The route the overlay was opened on: it never outlives a navigation or a widening of the window.
  const [openedAt, setOpenedAt] = useState<string | null>(null);
  if (!narrow && openedAt !== null) setOpenedAt(null); // state adjusted while rendering, no effect
  const open = narrow && openedAt === pathname;
  const collapsed = narrow ? !open : stored;
  const setOverlay = (next: boolean): void => setOpenedAt(next ? pathname : null);
  const frame = useRef<HTMLDivElement>(null);

  // Escape closes an open overlay; focus inside it goes back to the toggle (the drawer pattern).
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event: KeyboardEvent): void => {
      if (event.key !== "Escape" || event.defaultPrevented) return; // a dialog's Escape is its own
      const inside = frame.current?.contains(document.activeElement) === true;
      setOpenedAt(null);
      if (inside) toggleRow.current?.querySelector("button")?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  const rail = (
    <div
      ref={frame}
      style={frameStyle(collapsed)}
      data-rail={collapsed ? "collapsed" : "expanded"}
      data-rail-mode={narrow ? "overlay" : "column"}
    >
      <NavRail collapsed={collapsed} reduceMotion={reduceMotion} />
      <div ref={toggleRow} style={TOGGLE_ROW}>
        <IconButton
          icon="chevron-right"
          label={collapsed ? "Expand navigation rail" : "Collapse navigation rail"}
          variant="ghost"
          size="sm"
          aria-expanded={!collapsed}
          onClick={() => (narrow ? setOverlay(!open) : setRailCollapsed(!collapsed))}
        />
      </div>
    </div>
  );
  if (!narrow) return rail;
  // focus that leaves the rail for another control closes the overlay, so the drawer never hides it
  const onBlur = (event: FocusEvent<HTMLDivElement>): void => {
    const next = event.relatedTarget;
    if (open && next instanceof Node && frame.current?.contains(next) !== true) setOpenedAt(null);
  };
  return (
    <div style={COLUMN} onBlur={onBlur}>
      <div style={open ? OVERLAY : { height: "100%" }}>{rail}</div>
    </div>
  );
}
