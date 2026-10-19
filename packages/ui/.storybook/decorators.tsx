import {
  createContext,
  useContext,
  useLayoutEffect,
  useRef,
  type JSX,
  type ReactNode,
} from "react";
import type { Decorator } from "@storybook/react-vite";

/** Story mounts on this page so far; a play function compares the value before and after a switch. */
let mounts = 0;
const Counted = createContext(false);

/**
 * Counts mounts, not renders, of the story under it into a hidden `<output aria-label="Mount count">`
 * (a layout effect, so a play function can read it). Only the outermost counter counts.
 */
function MountCount({ children }: { readonly children: ReactNode }): JSX.Element {
  const outer = useContext(Counted);
  const out = useRef<HTMLOutputElement>(null);
  useLayoutEffect(() => {
    if (outer) return;
    mounts += 1;
    if (out.current) out.current.value = String(mounts);
  }, [outer]);
  if (outer) return <>{children}</>;
  return (
    <Counted.Provider value>
      <output ref={out} aria-label="Mount count" hidden />
      {children}
    </Counted.Provider>
  );
}

/** Mount-count instrumentation for no-remount assertions (E05-T02's theme and density switches). */
export const withMountCount: Decorator = (Story) => (
  <MountCount>
    <Story />
  </MountCount>
);

/** The app's own surface and text colour, as the custom properties every theme bundle defines. */
const SURFACE = "var(--color-surface-app)";
const TEXT = "var(--color-text-primary)";

/** Canvases mounted: several stories can share one page. */
let canvases = 0;

/** The canvas is the app's own surface in every theme, so axe measures contrast against it. */
function TokenCanvas(): null {
  useLayoutEffect(() => {
    const { style } = document.body;
    canvases += 1;
    style.setProperty("background-color", SURFACE);
    style.setProperty("color", TEXT);
    // The last story to go takes the surface with it, so the page shown next keeps its own.
    return () => {
      canvases -= 1;
      if (canvases > 0) return;
      style.removeProperty("background-color");
      style.removeProperty("color");
    };
  }, []);
  return null;
}

/**
 * Token-proof background: `surface.app` behind every story. The story view's body is its canvas,
 * so a story there gets no wrapper element. A docs page shows its stories inline on Storybook's own
 * light canvas, where the body is the page's: each story gets a wrapper painted with the surface
 * instead, or its text would be the theme's near-white text on white.
 */
export const withTokenBackground: Decorator = (Story, { viewMode }) =>
  viewMode === "docs" ? (
    <div style={{ backgroundColor: SURFACE, color: TEXT }}>
      <Story />
    </div>
  ) : (
    <>
      <TokenCanvas />
      <Story />
    </>
  );
