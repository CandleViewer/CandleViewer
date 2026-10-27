import { useEffect, useId, useRef, type CSSProperties, type JSX } from "react";
import { IconButton } from "@candleviewer/ui";
import { setRightRailOpen, useShellLayout } from "./layoutStore";
import { slide, useReducedMotion } from "./motion";

/** The `complementary` landmark's name (PROPOSED: D02 :255 fixes the role, not the name). */
export const RIGHT_RAIL_LABEL = "Side panels";

/** D04 C-17: the 48 px launcher strip stays; the 192 px panel beside it slides (geometry). */
const PANEL_WIDTH = "192px";

const ROOT: CSSProperties = { display: "flex", height: "100%" };

const STRIP: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  padding: "var(--space-1)",
  borderLeft: "1px solid var(--color-border-default)",
};

const HEADING: CSSProperties = {
  margin: 0,
  font: "inherit",
  fontWeight: "var(--font-weight-medium)",
};

/** On close, a discrete switch at the end of the slide: the panel stays painted while it moves out. */
const AT_CLOSE_END = "0s linear var(--motion-duration-fast)";

function panelBox(open: boolean, reduceMotion: boolean): CSSProperties {
  // The reserved space never animates: it opens at frame 0 and closes in one step at the last frame
  // (D04 T-03 / T-04 "Layout"), so the canvas widens only once the panel has slid out.
  return {
    width: open ? PANEL_WIDTH : 0,
    overflow: "hidden",
    transition: open || reduceMotion ? "none" : `width ${AT_CLOSE_END}`,
  };
}

function panelStyle(open: boolean, reduceMotion: boolean): CSSProperties {
  const move = slide(reduceMotion, open ? "normal" : "fast", open ? "decelerate" : "accelerate");
  return {
    width: PANEL_WIDTH,
    height: "100%",
    padding: "var(--space-inset-sm)",
    boxSizing: "border-box",
    borderLeft: "1px solid var(--color-border-default)",
    transform: open ? "none" : "translateX(100%)",
    // D04 T-04: inert to the pointer from frame 0; out of the Tab order and the a11y tree once the
    // slide ends (`visibility` switches last), at once under reduced motion.
    pointerEvents: open ? undefined : "none",
    visibility: open ? "visible" : "hidden",
    transition: open || reduceMotion ? move : `${move}, visibility ${AT_CLOSE_END}`,
  };
}

/**
 * CMP-209 RightRail (E10-S01 S6, #304): the drawer stack's launcher strip and one panel, mounted
 * and empty. Notifications (SCR-014) is the one drawer D03 names (:358); its content is another
 * ticket's, so the panel holds only its heading. Non-modal: opening keeps focus on the launcher
 * (D04 T-03), nothing is trapped; `Esc` inside the rail closes it and returns focus to the
 * launcher (CMP-209, D04 T-04). The launcher is a disclosure button: `aria-expanded` and
 * `aria-controls` (D04 names table); D04's name is "Notifications, 2 unread", and with no unread
 * count source yet it is "Notifications".
 */
export function RightRail(): JSX.Element {
  const open = useShellLayout("rightRailOpen");
  const reduceMotion = useReducedMotion();
  const panelId = useId();
  const launcherId = useId();
  const headingId = useId();

  const root = useRef<HTMLDivElement>(null);

  // Esc anywhere inside the rail (the strip or the open panel) closes it; focus returns to the launcher.
  useEffect(() => {
    const el = root.current;
    if (!open || el === null) return;
    const onKeyDown = (e: KeyboardEvent): void => {
      // An inner widget that handled its own Esc (a menu, a field) wins: it called preventDefault.
      if (e.key !== "Escape" || e.defaultPrevented) return;
      e.preventDefault();
      setRightRailOpen(false);
      document.getElementById(launcherId)?.focus();
    };
    el.addEventListener("keydown", onKeyDown);
    return () => el.removeEventListener("keydown", onKeyDown);
  }, [open, launcherId]);

  return (
    <div ref={root} style={ROOT}>
      <div style={STRIP}>
        <IconButton
          id={launcherId}
          icon="info"
          label="Notifications"
          variant="ghost"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => setRightRailOpen(!open)}
        />
      </div>
      <div style={panelBox(open, reduceMotion)}>
        {/* A plain group, not a `section`: a named section is one more landmark (`region`). */}
        <div
          id={panelId}
          role="group"
          aria-labelledby={headingId}
          style={panelStyle(open, reduceMotion)}
        >
          <h2 id={headingId} style={HEADING}>
            Notifications
          </h2>
        </div>
      </div>
    </div>
  );
}
