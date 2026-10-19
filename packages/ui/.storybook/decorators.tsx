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

/** The canvas is the app's own surface in every theme, so axe measures contrast against it. */
function TokenCanvas(): null {
  useLayoutEffect(() => {
    const { style } = document.body;
    style.setProperty("background-color", "var(--color-surface-app)");
    style.setProperty("color", "var(--color-text-primary)");
  }, []);
  return null;
}

/** Token-proof background: `surface.app` behind every story, with no wrapper element. */
export const withTokenBackground: Decorator = (Story) => (
  <>
    <TokenCanvas />
    <Story />
  </>
);
