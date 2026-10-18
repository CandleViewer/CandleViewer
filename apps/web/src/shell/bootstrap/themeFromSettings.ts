/**
 * Maps the server's `Settings` (`appearance` and `accessibility`) onto the preferences of the theme
 * runtime in `@candleviewer/ui` (E05-T02), which owns the `data-theme`, `data-density`, `data-motion`
 * and `data-text-scale` root attributes (#3139). Pure: no DOM, no store.
 *
 * A field is in the patch only when at least one of its server inputs is present and valid. An absent
 * or invalid input is left out, so `store.apply` keeps what the field already holds (a persisted local
 * choice or the pre-paint value) instead of resetting it to a default.
 *
 * | server input                                  | runtime field                                         |
 * | --------------------------------------------- | ----------------------------------------------------- |
 * | `appearance.theme` dark / light               | `baseTheme`, with `matchSystem: false`                |
 * | `appearance.theme` system                     | `matchSystem: true` (`baseTheme` stays as it is)      |
 * | `appearance.density` compact / comfortable    | `density`                                             |
 * | `appearance.density` spacious                 | `density: "comfortable"` (the runtime has two)        |
 * | `appearance.font_scale` (a factor, 0.75 to 2) | `textScale`: nearest of 100, 112, 125, 150 percent    |
 * | `appearance.high_contrast`, `accessibility.increased_contrast` | `highContrast`, see below            |
 * | `accessibility.reduced_motion`, `appearance.reduce_motion`     | `motionOverride`, see below          |
 *
 * `font_scale` is nearest-wins and a tie rounds up (1.06 is 112, not 100). A value outside the 0.75 to 2
 * range of the contract (`22-api-openapi.yaml`, Settings.appearance.font_scale) or a non-number is invalid.
 *
 * Reduced motion has two server inputs for one concept. The tri-state `accessibility.reduced_motion`
 * (`system|on|off`) wins. The boolean `appearance.reduce_motion` is honoured only while the tri-state is
 * `system` or absent: `true` gives `on`, and `false` stays `system` (the OS decides, it never forces
 * motion on). An invalid tri-state counts as absent.
 *
 * High contrast is one overlay (it keeps the base theme) with two inputs that are OR-ed:
 * `appearance.high_contrast: true` and `accessibility.increased_contrast: "on"` both turn it on.
 * `increased_contrast` of `off` or `system` leaves the overlay to `appearance.high_contrast`, and an
 * absent flag counts as off once the accessibility subtree has spoken (so switching "on" back to "off"
 * there really turns the overlay off). `system` does not follow `prefers-contrast`: the runtime has no
 * such input.
 */
import {
  TEXT_SCALES,
  type MotionOverride,
  type TextScale,
  type ThemePreferences,
} from "@candleviewer/ui";
import type { Settings } from "./store.js";

/** The two `Settings` subtrees the theme runtime reads; a whole `Settings` fits. */
export interface ThemeSettings {
  readonly appearance?: Settings["appearance"] | undefined;
  readonly accessibility?: Settings["accessibility"] | undefined;
}

/** What `ThemeStore.apply` accepts: any subset of the preferences. */
export type ThemePatch = { -readonly [K in keyof ThemePreferences]?: ThemePreferences[K] };

type Accessibility = NonNullable<Settings["accessibility"]>;

/** `Settings.appearance.font_scale` bounds in the contract (a factor: 1 is 100 percent). */
const MIN_FONT_SCALE = 0.75;
const MAX_FONT_SCALE = 2;

type Leaves = Readonly<Record<string, unknown>>;

/** The server's JSON is untyped at runtime: anything that is not a plain object has no leaves. */
function leavesOf(subtree: unknown): Leaves {
  if (typeof subtree !== "object" || subtree === null || Array.isArray(subtree)) return {};
  return subtree as Leaves; // narrowed to a non-array object above; every leaf is re-checked before use
}

function nearestTextScale(fontScale: unknown): TextScale | undefined {
  if (typeof fontScale !== "number" || !Number.isFinite(fontScale)) return undefined;
  if (fontScale < MIN_FONT_SCALE || fontScale > MAX_FONT_SCALE) return undefined;
  const percent = fontScale * 100;
  return TEXT_SCALES.reduce((best, step) => {
    const gap = Math.abs(percent - step);
    const bestGap = Math.abs(percent - best);
    return gap < bestGap || (gap === bestGap && step > best) ? step : best;
  });
}

function highContrastOf(flag: unknown, increasedContrast: unknown): boolean | undefined {
  const fromAppearance = typeof flag === "boolean" ? flag : undefined;
  const spoke =
    increasedContrast === "on" || increasedContrast === "off" || increasedContrast === "system";
  if (!spoke) return fromAppearance;
  return fromAppearance === true || increasedContrast === "on";
}

function motionOverrideOf(triState: unknown, flag: unknown): MotionOverride | undefined {
  if (triState === "on" || triState === "off") return triState;
  if (flag === true) return "on";
  if (triState === "system" || flag === false) return "system";
  return undefined;
}

export function themeFromSettings(settings: ThemeSettings | undefined): ThemePatch {
  const appearance = leavesOf(settings?.appearance);
  const accessibility = leavesOf(settings?.accessibility);
  const patch: ThemePatch = {};

  const theme = appearance["theme"];
  if (theme === "dark" || theme === "light") {
    patch.baseTheme = theme;
    patch.matchSystem = false;
  } else if (theme === "system") {
    patch.matchSystem = true;
  }

  const density = appearance["density"];
  if (density === "compact" || density === "comfortable") patch.density = density;
  else if (density === "spacious") patch.density = "comfortable";

  const textScale = nearestTextScale(appearance["font_scale"]);
  if (textScale !== undefined) patch.textScale = textScale;

  const highContrast = highContrastOf(
    appearance["high_contrast"],
    accessibility["increased_contrast"],
  );
  if (highContrast !== undefined) patch.highContrast = highContrast;

  const motionOverride = motionOverrideOf(
    accessibility["reduced_motion"],
    appearance["reduce_motion"],
  );
  if (motionOverride !== undefined) patch.motionOverride = motionOverride;

  return patch;
}

/**
 * `ThemeSettings` for the reduced-motion preference on its own: its tri-state plus its appearance
 * twin (`reduce_motion`), which it is combined with. It yields `motionOverride` and nothing else, so
 * feeding it never touches the contrast overlay, the theme, the density or the text scale, any of which
 * the user may have set since the bootstrap (the session overrides of 05-accessibility-standard.md
 * §3.2 are exactly that).
 */
export function reducedMotionThemeSettings(
  reducedMotion: NonNullable<Accessibility["reduced_motion"]>,
  appearance: Settings["appearance"],
): ThemeSettings {
  return {
    appearance:
      appearance?.reduce_motion === undefined ? {} : { reduce_motion: appearance.reduce_motion },
    accessibility: { reduced_motion: reducedMotion },
  };
}

/**
 * The same for increased contrast: its tri-state plus its appearance twin (`high_contrast`), yielding
 * `highContrast` and nothing else, so it never reverts a reduced-motion override of the session.
 */
export function increasedContrastThemeSettings(
  increasedContrast: NonNullable<Accessibility["increased_contrast"]>,
  appearance: Settings["appearance"],
): ThemeSettings {
  return {
    appearance:
      appearance?.high_contrast === undefined ? {} : { high_contrast: appearance.high_contrast },
    accessibility: { increased_contrast: increasedContrast },
  };
}
