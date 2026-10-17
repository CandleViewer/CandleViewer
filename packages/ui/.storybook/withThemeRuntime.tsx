import { useEffect, type JSX } from "react";
import type { Decorator } from "@storybook/react";
import {
  ThemeProvider,
  createThemeStore,
  type DensityName,
  type MotionOverride,
  type ThemeName,
} from "../src/theme/index.js";

/** One in-memory store for the preview: the toolbar globals, not localStorage, are the source of truth. */
const store = createThemeStore({ storage: { getItem: () => null, setItem: () => undefined } });

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
    store.apply({ ...base, density, motionOverride: motion });
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
