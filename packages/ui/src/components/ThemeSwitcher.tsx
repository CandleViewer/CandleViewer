import { useEffect, useRef, useState, type JSX } from "react";
import { useThemeSnapshot, useThemeStore } from "../theme/ThemeProvider.js";
import type { ThemeName } from "../theme/store.js";
import { SegmentedControl, type SegmentedOptions } from "./SegmentedControl.js";
import { Toggle } from "./Toggle.js";

export interface ThemeSwitcherCopy {
  /** The group's accessible name: SCR-116's field label. */
  readonly label: string;
  readonly dark: string;
  readonly light: string;
  readonly highContrast: string;
  /** The CMP-004 switch beside the segments (E05-D02 J13). */
  readonly matchSystem: string;
  /** The polite sentence spoken once per committed change, keyed by the theme in effect after it (J16). */
  readonly announce: Readonly<Record<ThemeName, string>>;
}

/** Default English copy (the host's copy layer replaces it through `copy`). */
export const THEME_SWITCHER_COPY: ThemeSwitcherCopy = {
  label: "Theme",
  dark: "Dark",
  light: "Light",
  highContrast: "High contrast",
  matchSystem: "Match system",
  announce: {
    dark: "Theme changed to Dark",
    light: "Theme changed to Light",
    "high-contrast": "Theme changed to High Contrast",
  },
};

export interface ThemeSwitcherProps {
  /** The theme in effect (with match system on, the one the system resolves to). */
  readonly value: ThemeName;
  /** A segment was chosen; the host turns match system off with it (J13, `ThemeStore.setTheme` does). */
  readonly onChange?: (value: ThemeName) => void;
  readonly matchSystem?: boolean;
  readonly onMatchSystemChange?: (on: boolean) => void;
  /** Never an RBAC gate: every role changes the theme on this device (J15 (a)). */
  readonly disabled?: boolean;
  /** Emits `data-density` on both controls; absent = inherit. */
  readonly density?: "comfortable" | "compact";
  readonly copy?: Partial<ThemeSwitcherCopy>;
}

const isTheme = (value: string): value is ThemeName =>
  value === "dark" || value === "light" || value === "high-contrast";

/**
 * CMP-062 ThemeSwitcher: CMP-003 with Dark · Light · High contrast, plus the CMP-004 "match system"
 * switch (J13). Props only; it emits no analytics (the store is the only emitter). A committed change
 * (a segment, an arrow, the switch) speaks once in its own polite region, naming the theme in effect
 * after the host applied it; a `value` that changes any other way (load, server, OS) speaks nothing (J16).
 * The host must apply a change synchronously (in the `onChange` / `onMatchSystemChange` call, as the theme
 * store does): the sentence is read from `value` on the commit's render, so a deferred apply (a server round
 * trip) would name the old theme.
 */
export function ThemeSwitcher({
  value,
  onChange,
  matchSystem = false,
  onMatchSystemChange,
  disabled = false,
  density,
  copy: overrides,
}: ThemeSwitcherProps): JSX.Element {
  const copy = { ...THEME_SWITCHER_COPY, ...overrides };
  const [commits, setCommits] = useState(0);
  const [spoken, setSpoken] = useState("");
  const latest = useRef({ value, announce: copy.announce });
  latest.current = { value, announce: copy.announce };
  useEffect(() => {
    // Runs after the commit's render, so it names what the host applied (a refused change names the unchanged theme).
    // A trailing zero-width space on every other commit makes a repeated sentence a DOM change, so it is re-announced.
    // Best-effort: some screen readers ignore a change of that space alone; the manual screen-reader pass confirms it.
    if (commits > 0)
      setSpoken(
        latest.current.announce[latest.current.value] + (commits % 2 === 0 ? "\u200B" : ""),
      );
  }, [commits]);
  const commit = (): void => setCommits((n) => n + 1);
  const dense = density === undefined ? {} : { density };
  const options: SegmentedOptions = [
    { value: "dark", label: copy.dark },
    { value: "light", label: copy.light },
    { value: "high-contrast", label: copy.highContrast },
  ];
  return (
    <div className="cv-theme-switcher" data-cmp="CMP-062" data-density={density}>
      <SegmentedControl
        aria-label={copy.label}
        options={options}
        value={value}
        disabled={disabled}
        {...dense}
        onChange={(next) => {
          if (!isTheme(next)) return;
          onChange?.(next);
          commit();
        }}
      />
      <Toggle
        label={copy.matchSystem}
        checked={matchSystem}
        disabled={disabled}
        {...dense}
        onChange={(on) => {
          onMatchSystemChange?.(on);
          commit();
        }}
      />
      <span className="cv-visually-hidden" role="status" aria-live="polite" aria-atomic="true">
        {spoken}
      </span>
    </div>
  );
}

export type ThemeSwitcherConnectedProps = Omit<
  ThemeSwitcherProps,
  "value" | "onChange" | "matchSystem" | "onMatchSystemChange"
>;

/**
 * CMP-062 bound to the theme runtime (needs `<ThemeProvider>`): reads the snapshot and writes through
 * the store, which persists the choice and emits `appearance.theme_changed` once per change (J16).
 * Turning match system on drops high contrast, so the checked segment is the one the system resolves to (J13).
 * `Ctrl+Shift+H` stays the runtime's (`toggleHighContrastAnnounced`); this control does not bind it.
 */
export function ThemeSwitcherConnected(props: ThemeSwitcherConnectedProps): JSX.Element {
  const store = useThemeStore();
  const { theme, matchSystem } = useThemeSnapshot();
  return (
    <ThemeSwitcher
      {...props}
      value={theme}
      matchSystem={matchSystem}
      onChange={store.setTheme}
      onMatchSystemChange={(on) =>
        store.apply(
          on
            ? { matchSystem: true, highContrast: false }
            : // Off keeps the theme the system resolved to, so the page does not jump back to the old base.
              { matchSystem: false, ...(theme === "high-contrast" ? {} : { baseTheme: theme }) },
        )
      }
    />
  );
}
