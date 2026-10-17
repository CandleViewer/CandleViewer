import { useEffect, type JSX } from "react";
import type { Decorator } from "@storybook/react";
import {
  ThemeProvider,
  sharedThemeStore,
  type DensityName,
  type MotionOverride,
  type ThemeName,
} from "../src/theme/index.js";

/**
 * One in-memory store for the preview: the toolbar globals, not localStorage, are the source of truth.
 * It is the shared store of `document.documentElement`, so providers a story adds itself agree with it.
 */
const store = sharedThemeStore({ storage: { getItem: () => null, setItem: () => undefined } });

interface ThemeGlobals {
  readonly theme: ThemeName;
  readonly density: DensityName;
  readonly motion: MotionOverride;
}

function SyncGlobals({ theme, density, motion }: ThemeGlobals): JSX.Element | null {
  useEffect(() => {
    const base =
      theme === "high-contrast"
        ? { highContrast: true }
        : { baseTheme: theme, highContrast: false, matchSystem: false };
    // No toolbar for text scale: pin it, or a story that picks 150 % leaks into the next one.
    store.apply({ ...base, density, motionOverride: motion, textScale: 100 });
  }, [theme, density, motion]);
  return null;
}

/** Drives the theme runtime from the Theme / Density / Reduced-motion toolbar globals. */
export const withThemeRuntime: Decorator = (Story, context) => (
  <ThemeProvider store={store}>
    {/* `initialGlobals` in preview.ts guarantees all three globals are set. */}
    <SyncGlobals {...(context.globals as unknown as ThemeGlobals)} />
    <Story />
  </ThemeProvider>
);
